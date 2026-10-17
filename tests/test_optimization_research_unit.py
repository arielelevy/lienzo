"""Caso del investigador sobre una unidad de trabajo (ronda, ola o feature): armado, selección y recorrido.

Determinista: carpetas de coordinación en un directorio temporal con fechas fijadas, capturas de la base de
prueba y un adaptador falso que lanza un proceso Python real (sin inferencia ni red)."""

import datetime as dt
import json
import os
import sys
import time

import conocimiento as k
import optimization_research as r
import optimization_research_policy as policy
import optimization_research_quota as quota
import optimization_research_unit as unit
import optimization_scheduler as s
import pytest

PROJECT = "unidad-test"
TOKEN = "ghp_" + "U" * 36
CHILD = r"""
import json, sys
work = sys.argv[1]
payload = json.load(open(work + "/fake.json", encoding="utf-8"))
json.dump(payload["result"], open(work + "/result.json", "w", encoding="utf-8"))
"""


def unit_answer(data):
    report = next(i["archivo"] for f in data["unidad"]["frentes"].values() for i in f["informes"])
    trace = data["trace_refs"][0]
    return {
        "case_id": data["case_id"],
        "areas": ["reparto", "reaccion_coordinadora"],
        "problem": "El frente B esperó a la coordinadora después de entregar",
        "causes": [
            {"claim": "La entrega no tuvo acuse", "basis": "inferido", "confidence": "media", "sources": [trace]}
        ],
        "proposals": [
            {
                "title": "Aviso a la coordinadora al llegar un informe con ESTADO",
                "problem": "Entregas sin reacción",
                "scope": "rondas coordinadas por Lienzo",
                "alternative": "revisión manual del tablero",
                "verification": "medir esperas_h antes y después en dos rondas comparables",
                "risk": "avisos de más",
                "sources": [report, trace],
            }
        ],
        "missing_capabilities": [
            {"capability": "vista de la ronda por frente", "need": "ver qué falta", "sources": [report]}
        ],
        "limitations": ["fechas de archivo = última modificación"],
        "not_measured": ["calidad de lo entregado"],
        "sources": [
            {"ref": report, "kind": "documento", "detail": "informe del frente"},
            {"ref": trace, "kind": "traza", "detail": "sesión de la ventana"},
        ],
    }


class FakeAdapter:
    name = agent = "codex"
    quota_every = None

    def __init__(self):
        self.launched = []

    def limits(self, auth, project):
        bound = {"unit": "usd", "maximum": "0", "verified": True, "basis": "adaptador falso"}
        return {
            "name": "codex",
            "available": True,
            "sends_to_external_service": True,
            "sandbox": "read-only",
            "cancellable": True,
            "timeout": True,
            "consumption_bound": bound,
            "blocked_by": [],
        }

    def command(self, work, root, seconds):
        data = json.loads((work / "prompt.md").read_text(encoding="utf-8").split("CASO:\n", 1)[1])
        (work / "fake.json").write_text(json.dumps({"result": unit_answer(data)}), encoding="utf-8")
        self.launched.append((work, root))
        return [sys.executable, "-c", CHILD, str(work)], ""

    def midrun_reason(self):
        return None

    @staticmethod
    def usage(stdout):
        return None


def touch(path, text, minutes_ago):
    path.write_text(text, encoding="utf-8")
    moment = time.time() - minutes_ago * 60
    os.utime(path, (moment, moment))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    folder = root / ".temp" / "coordinacion" / "2026-10-16"
    folder.mkdir(parents=True)
    k.registrar_proyecto(PROJECT, nombre="Unidad", carpetas=[{"pc": "pc1", "cwd": str(root)}])
    monkeypatch.setattr(policy, "rules_path", lambda: tmp_path / "reglas.json")
    monkeypatch.setattr(quota, "read_codex", lambda *a, **kw: pytest.fail("no leer la cuota real"))
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))
    touch(folder / "comun.md", "# Ronda\nreglas comunes", 300)
    touch(folder / "A.md", "# A\nImplementá el investigador " + TOKEN, 290)
    touch(folder / "plan-A.md", "plan", 280)
    touch(folder / "B.md", "# B\nCatálogo", 285)
    touch(
        folder / "informe-A.md",
        "# Informe A\nESTADO: listo con token " + TOKEN + "\n## Ronda 2\npytest 223 passed; mutación 8 de 8\n"
        "## Ronda 3\ncode review y compuerta sin baseline\n",
        170,
    )
    touch(folder / "traspaso-coordinacion.md", "Codex pasa a Claude", 200)
    touch(folder / "notas.py", "print(1)", 250)
    return root, folder


def capture(clase, sid, text, origen=None):
    return k.capturar(
        PROJECT, clase, text, {"session_id": sid, "agent": "claude", "model": "opus", "pc": "pc1"}, origen=origen
    )


def test_folder_summary_fronts_reports_rework_controls_and_redaction(repo):
    root, folder = repo
    counts = {}
    summary = unit.summarize_folders(root, [folder], lambda text: r.redact(text, counts))
    a, b = summary["frentes"]["A"], summary["frentes"]["B"]
    report = a["informes"][0]
    assert report["rondas_extra"] == 2 and report["horas_desde_encargo"] == pytest.approx(2.0, abs=0.05)
    assert report["controles_declarados"] == {"pruebas": 2, "mutacion": 1, "compuerta": 2, "review": 1}
    assert TOKEN not in json.dumps(summary) and counts == {"github": 2}
    assert a["planes"][0]["archivo"].endswith("plan-A.md") and a["encargos_sin_informe"] == []
    assert b["encargos_sin_informe"] == [".temp/coordinacion/2026-10-16/B.md"]
    assert [c["archivo"].split("/")[-1] for c in summary["comunes_y_traspasos"]] == [
        "comun.md",
        "traspaso-coordinacion.md",
    ]
    assert summary["otros_artefactos"] == 1


def test_unit_packet_brings_window_sessions_metrics_and_validates(repo):
    root, folder = repo
    touch(folder / "informe-B.md", "ESTADO: listo", 1)  # la ventana llega hasta ahora: incluye las capturas
    capture("pedido", "coord", "coordiná la ronda")
    capture("envio", "frente-b", "encargo B", origen={"de": "coord"})
    capture("respuesta", "frente-b", "ESTADO: listo")
    case = unit.case(PROJECT, root, [folder])
    data = r.packet(case)
    assert data["unidad"]["carpetas"] == [".temp/coordinacion/2026-10-16"] and data["memory_sources"] == []
    assert {s["session_id"] for s in data["sesiones"]} == {"coord", "frente-b"}
    assert "sesion:frente-b" in data["trace_refs"] and "sesion:frente-b" in data["how_it_happened"]
    assert data["coordinacion"]["capturas"] == 3 and "metricas" in data["coordinacion"]
    assert (
        set(r.UNIT_QUESTIONS) <= set(data["questions"])
        and "reparto" in r.SCHEMA["properties"]["areas"]["items"]["enum"]
    )
    assert r.validate(unit_answer(data), data, r.case_root(case))["case_id"] == case["case_key"]
    assert "UNIDAD DE TRABAJO" in r.prompt(data)


def test_selection_offers_quiet_units_with_reports_after_jev(repo):
    root, folder = repo
    jev = k.crear_nodo(PROJECT, "evidencia", "jev", {"clase": "piloto_jev", "hipotesis": "rtk"}, autor="server")
    k.crear_nodo(PROJECT, "incidente", "x", {"herramienta": "shell"}, autor="server")
    cases = r.select(PROJECT, limit=10)
    assert [c["origin"] for c in cases] == ["evidencia", "unidad", "incidente"]
    assert cases[0]["source_ids"] == [jev["id"]] and cases[1]["folders"] == [".temp/coordinacion/2026-10-16"]
    touch(folder / "informe-B.md", "ESTADO: en curso", 5)  # una ola con cambios recientes no es candidata
    assert [c["origin"] for c in r.select(PROJECT, limit=10)] == ["evidencia", "incidente"]


def test_folder_without_reports_is_not_a_candidate(repo):
    root, folder = repo
    (folder / "informe-A.md").unlink()
    assert unit.candidate_folders(PROJECT) == []


@pytest.mark.parametrize(
    "folders",
    [["../afuera"], [".temp/coordinacion/2026-10-16/../../.."], ["src"], [], ["a", "b", "c", "d", "e"], "texto"],
)
def test_resolve_folders_rejects_anything_outside_coordination(repo, folders):
    with pytest.raises(ValueError):
        unit.resolve_folders(PROJECT, folders)


def test_scheduler_runs_an_explicit_multi_folder_unit_end_to_end(repo):
    root, folder = repo
    second = root / ".temp" / "coordinacion" / "2026-10-17"
    second.mkdir()
    touch(second / "A-cuotas.md", "# A cuotas", 60)
    touch(second / "informe-A-cuotas.md", "ESTADO: hecho", 1)
    capture("respuesta", "frente-a", "ESTADO: hecho")
    adapter = FakeAdapter()
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: adapter
    folders = [".temp/coordinacion/2026-10-16", ".temp/coordinacion/2026-10-17"]
    scheduler.command({"action": "enqueue_research_unit", "project": PROJECT, "folders": folders})
    for _ in range(3):
        scheduler.tick(
            {
                "idle_seconds": 190,
                "ui_idle_seconds": 190,
                "cpu_pct": 10,
                "mem_free_gb": 3,
                "pending": False,
                "agents_busy": False,
            }
        )
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed", job.get("reason")
    assert adapter.launched[0][1] == root.resolve()  # corre en la raíz del proyecto de la unidad
    proposal = k.nodo(PROJECT, job["results"][0])
    assert proposal["estado"] == "propuesta" and proposal["datos"]["areas"] == ["reparto", "reaccion_coordinadora"]
    with pytest.raises(ValueError, match="ya se investigó"):
        scheduler.command({"action": "enqueue_research_unit", "project": PROJECT, "folders": folders})


def test_case_key_is_stable_per_folder_set(repo):
    root, folder = repo
    assert unit.case(PROJECT, root, [folder])["case_key"] == unit.case(PROJECT, root, [folder])["case_key"]
    assert dt.datetime.fromisoformat(unit.case(PROJECT, root, [folder])["date"])
