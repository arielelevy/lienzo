import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import conocimiento as k
import conocimiento_api as api
import creencias
import prolog_learning as motor
import pytest

REAL = pytest.mark.skipif(
    not (shutil.which("wsl.exe") or shutil.which("swipl")) or not motor.ENGINE.is_file(),
    reason="Falta WSL/SWI-Prolog o el repo motor-logico",
)


def payload():
    return {
        "contract": 1,
        "domain": "learning",
        "now": 100,
        "context": {"tipo_trabajo": "bugfix"},
        "nodes": [{"id": "b", "kind": "decision", "state": "vigente"}, {"id": "e", "kind": "evidencia", "state": None}],
        "edges": [{"from": "b", "to": "e", "relation": "apoya"}],
        "beliefs": [
            {
                "id": "b",
                "state": "vigente",
                "verdict": "validada",
                "approved_by": "persona:Ariel",
                "evidence": "e",
                "until": 200,
                "required": {"tipo_trabajo": "bugfix"},
            }
        ],
    }


@REAL
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, "aplicable"),
        ({"state": "reemplazada"}, "refutada"),
        ({"verdict": None}, "sin_veredicto"),
        ({"approved_by": "frente:x"}, "sin_veredicto"),
        ({"evidence": "missing"}, "respaldo_retirado"),
        ({"until": 100}, "vencida"),
        ({"required": {"agente": "codex"}}, "contexto_insuficiente"),
        ({"required": {"tipo_trabajo": "refactor"}}, "fuera_de_contexto"),
        ({"required": {"tipo_trabajo": True}}, "contexto_invalido"),
    ],
)
def test_real_engine_states(change, expected):
    data = payload()
    data["beliefs"][0].update(change)
    assert motor.run(data)["conclusions"][0]["status"] == expected


@REAL
def test_real_engine_transitive_cycle_and_data_injection():
    data = payload()
    data["nodes"] += [
        {"id": "d", "kind": "decision", "state": "vigente"},
        {"id": "h", "kind": "hallazgo", "state": "rechazado"},
    ]
    data["edges"] += [
        {"from": "b", "to": "d", "relation": "motivada_por"},
        {"from": "d", "to": "b", "relation": "motivada_por"},
        {"from": "d", "to": "h", "relation": "motivada_por"},
    ]
    result = motor.run(data)["conclusions"][0]
    assert result["status"] == "respaldo_caido" and result["chains"] == [["b", "d", "h"]]
    clean = payload()
    clean["context"]["tipo_trabajo"] = 'x"),halt(77),write("injected'
    assert motor.run(clean)["conclusions"][0]["status"] == "fuera_de_contexto"
    assert motor.run(payload())["conclusions"][0]["status"] == "aplicable"


@REAL
def test_api_compares_real_graph_without_writes():
    pid = "prolog-real"
    k.registrar_proyecto(pid)
    source = k.crear_nodo(pid, "hallazgo", "fuente", {}, autor="server")
    belief = creencias.proponer(
        pid,
        {
            "dimension": "pruebas",
            "texto": "regla",
            "accion": "probar",
            "contexto": {"tipo_trabajo": "bugfix"},
            "fuentes": [source["id"]],
        },
        autor="server",
    )
    evidence = k.crear_nodo(pid, "evidencia", "evidencia", {}, autor="persona:Ariel")
    creencias.resolver(
        pid,
        belief["id"],
        {
            "por": "persona:Ariel",
            "motivo": "prueba",
            "resultado": "validada",
            "evidencia": evidence["id"],
            "vigente_hasta": (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat(),
        },
    )
    before = k.nodo(pid, belief["id"])
    code, result = api.dispatch("POST", [pid, "razonamiento"], {"contexto": {"tipo_trabajo": "bugfix"}}, {})
    assert code == 200 and result["diferencias"] == []
    assert result["conclusiones"][0]["status"] == "aplicable"
    assert k.nodo(pid, belief["id"]) == before
    k.cambiar_estado(pid, source["id"], "rechazado", por="persona:Ariel", motivo="retirada")
    code, result = api.dispatch("POST", [pid, "razonamiento"], {"contexto": {"tipo_trabajo": "bugfix"}}, {})
    assert code == 200 and result["diferencias"] == []
    assert result["conclusiones"][0]["chains"] == [[belief["id"], source["id"]]]


@REAL
def test_real_engine_matches_python_on_random_graphs():
    """Diferencial sembrado: grafos con ciclos, fuentes caídas, veredictos, vencimientos y contextos
    rotos. Los estados y vínculos se fuerzan por SQL para cubrir combinaciones que la API no arma."""
    import random

    rng = random.Random(20261019)
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat()
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    seen = set()
    for round_ in range(8):
        pid = f"prolog-diff-{round_}"
        k.registrar_proyecto(pid)
        evidence = k.crear_nodo(pid, "evidencia", "evidencia", {}, autor="persona:Ariel")["id"]
        sources = [
            k.crear_nodo(pid, rng.choice(["hallazgo", "medicion"]), f"f{i}", {}, autor="server") for i in range(4)
        ]
        beliefs = [
            k.crear_nodo(pid, "decision", f"c{i}", {"clase": "creencia_operativa"}, autor="server")["id"]
            for i in range(12)
        ]
        with k._abrir(pid) as con:
            for source in sources:
                fallen = {"hallazgo": "rechazado", "medicion": "rechazada"}[source["tipo"]]
                con.execute(
                    "UPDATE nodo SET estado=? WHERE id=?",
                    (fallen if rng.random() < 0.25 else source["estado"], source["id"]),
                )
            for belief in beliefs:
                data = {
                    "clase": "creencia_operativa",
                    "resultado": rng.choice(["validada"] * 6 + ["refutada", None]),
                    "veredicto_por": rng.choice(["persona:Ariel"] * 6 + ["frente:x", None]),
                    "evidencia_veredicto": rng.choice([evidence] * 5 + ["otra"]),
                    "vigente_hasta": rng.choice([future, future, past, "2026-10-19T00:00:00", None]),
                    "contexto": rng.choice(
                        [
                            {"tipo_trabajo": "bugfix"},
                            {"tipo_trabajo": "refactor"},
                            {"agente": "codex"},
                            {"agente": "codex"},
                            {},
                            {"tipo_trabajo": True},
                            {"otro": "x"},
                            None,
                        ]
                    ),
                }
                state = rng.choice(["vigente"] * 8 + ["propuesta", "revertida", "reemplazada"])
                con.execute("UPDATE nodo SET estado=?, datos=? WHERE id=?", (state, json.dumps(data), belief))
                if rng.random() < 0.8:
                    con.execute(
                        "INSERT OR IGNORE INTO vinculo(de,relacion,a,activo,fecha,autor,origen) VALUES (?,?,?,?,?,?,?)",
                        (belief, "apoya", evidence, int(rng.random() < 0.85), "x", "persona:Ariel", "{}"),
                    )
                for target in rng.sample(beliefs + [s["id"] for s in sources], rng.choice([0, 0, 1, 2])):
                    if target != belief:
                        con.execute(
                            "INSERT OR IGNORE INTO vinculo(de,relacion,a,activo,fecha,autor,origen) "
                            "VALUES (?,?,?,1,?,?,?)",
                            (belief, "motivada_por", target, "x", "server", "{}"),
                        )
            con.commit()
        code, result = api.dispatch("POST", [pid, "razonamiento"], {"contexto": {"tipo_trabajo": "bugfix"}}, {})
        assert code == 200 and result["diferencias"] == [], result["diferencias"]
        seen |= {c["status"] for c in result["conclusiones"]}
    assert seen == set(creencias.MOTIVOS)  # el muestreo recorrió los nueve estados


def test_unavailable_timeout_and_invalid_result_are_visible(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("swipl", 12)

    monkeypatch.setattr(motor, "ENGINE", Path(__file__))  # existe en cualquier PC: se prueba el proceso
    monkeypatch.setattr(motor.subprocess, "run", fail)
    with pytest.raises(motor.MotorError, match="TimeoutExpired"):
        motor.run(payload())
    monkeypatch.setattr(
        motor.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, '{"conclusions":[]}')
    )
    with pytest.raises(motor.MotorError, match="inválida"):
        motor.run(payload())


def test_missing_engine_is_reported_as_absence(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(motor, "ENGINE", tmp_path / "motor-logico/main.pl")
    monkeypatch.setattr(motor.subprocess, "run", lambda *a, **kw: calls.append(a))
    with pytest.raises(motor.MotorError, match="no encontrado"):
        motor.run(payload())
    assert calls == []


def test_missing_results_never_mean_empty_success():
    with pytest.raises(ValueError):
        motor.validate(
            {"contract": 1, "domain": "learning", "rules": 1, "authority": "observation_only", "conclusions": []},
            payload(),
        )
    data = payload()
    assert len(json.dumps(data)) < 1024 * 1024
    ok = {"id": "b", "status": "aplicable", "rule": "aplicable", "chains": []}
    for field in ("contract", "rules"):
        output = {"contract": 1, "domain": "learning", "rules": 1, "authority": "observation_only", "conclusions": [ok]}
        motor.validate(output, data)  # control: la versión entera pasa
        with pytest.raises(ValueError, match="contrato"):
            motor.validate({**output, field: True}, data)


def test_optional_engine_failure_does_not_block_learning(monkeypatch):
    pid = "prolog-optional"
    k.registrar_proyecto(pid)
    calls = []

    def missing(data):
        calls.append(data)
        raise motor.MotorError("Motor no instalado")

    monkeypatch.setattr(motor, "run", missing)
    assert creencias.checklist(pid, {"tipo_trabajo": "bugfix"}) is not None
    assert calls == []
    code, result = api.dispatch("POST", [pid, "razonamiento"], {"contexto": {"tipo_trabajo": "bugfix"}}, {})
    assert code == 503 and result["code"] == "prolog_unavailable"
    assert len(calls) == 1
    assert creencias.checklist(pid, {"tipo_trabajo": "bugfix"}) is not None
    assert len(calls) == 1
