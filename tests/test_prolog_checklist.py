"""Checklist sostenido por el motor lógico (encargo J, 2026-10-22): sólo aplica lo que el motor
sostiene con una prueba que cierra, lo cuestionado se marca con su porqué, el cálculo Python
sigue como contraste y sin motor el checklist se lee igual, sin decir que algo está sostenido."""

import datetime as dt
import json
import random
import shutil
from pathlib import Path

import conocimiento as k
import conocimiento_api as api
import creencias as c
import prolog_checklist as pk
import prolog_contraste as pc
import prolog_learning as motor
import pytest

REAL = pytest.mark.skipif(
    not (shutil.which("wsl.exe") or shutil.which("swipl")) or not motor.ENGINE.is_file(),
    reason="Falta WSL/SWI-Prolog o el repo motor-logico",
)
CTX = {"tipo_trabajo": "bugfix", "agente": "codex"}


def _creencia(pid, texto="Los bugfix necesitan diagnóstico focal", validar=True):
    k.registrar_proyecto(pid)
    source = k.crear_nodo(pid, "hallazgo", "espera observada " + texto, {}, autor="server")
    evidence = k.crear_nodo(pid, "evidencia", "comparación revisada " + texto, {}, autor="persona:Ariel")
    belief = c.proponer(
        pid,
        {
            "texto": texto,
            "accion": "Revisar " + texto,
            "dimension": "pruebas",
            "contexto": CTX,
            "fuentes": [source["id"]],
        },
        autor="server",
    )
    if validar:
        c.resolver(
            pid,
            belief["id"],
            {
                "por": "persona:Ariel",
                "motivo": "verificada",
                "resultado": "validada",
                "evidencia": evidence["id"],
                "vigente_hasta": (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat(),
            },
        )
    return belief["id"], source["id"]


def _regla_cuestionada(pid, origen):
    rule = k.crear_nodo(pid, "regla", "regla derivada", {}, autor="persona:Ariel")
    k.vincular(pid, rule["id"], "derivada_de", origen, autor="persona:Ariel", motivo="derivada de la creencia")
    with k._abrir(pid) as con:  # la recurrencia que la cuestiona la arma aprendizaje; acá se fuerza el estado
        con.execute("UPDATE nodo SET estado='cuestionada' WHERE id=?", (rule["id"],))
        con.commit()
    return rule["id"]


def _checklist(pid, ctx=CTX):
    code, out = api.dispatch("GET", [pid, "checklist"], None, ctx)
    assert code == 200, out
    return out


def _foto(pid):
    with k._abrir(pid) as con:
        return con.execute("SELECT id, estado, datos FROM nodo WHERE proyecto=? ORDER BY id", (pid,)).fetchall()


@REAL
def test_aplicable_sostenida_con_prueba_del_motor_sin_escribir():
    pid = "chk-sostenida"
    bid, _ = _creencia(pid)
    before = [tuple(r) for r in _foto(pid)]
    out = _checklist(pid)
    assert out["motor"]["estado"] == "sostenido" and out["motor"]["diferencias"] == []
    (item,) = out["items"]
    assert item["creencia"] == bid and item["estado"] == "aplicable"
    prueba = item["sostenida"]["prueba"]
    assert prueba["rule"] == "sostenida" and prueba["fact"] == {"pred": "sostenida", "args": [bid]}
    assert item["sostenida"]["fuentes"] == ["grafo"] and item["sostenida"]["prueba_truncada"] is False
    assert [tuple(r) for r in _foto(pid)] == before  # leer el checklist no escribe nada


@REAL
@pytest.mark.parametrize("via", ["creencia", "decision"])
def test_regla_cuestionada_marca_la_creencia_y_la_saca_del_checklist(via):
    """Rojo en HEAD: el checklist Python la sigue dando por aplicable."""
    pid = f"chk-cuestionada-{via}"
    bid, _ = _creencia(pid)
    origen = bid
    if via == "decision":
        origen = k.crear_nodo(pid, "decision", "decisión que la motiva", {}, autor="persona:Ariel")["id"]
        with k._abrir(pid) as con:
            con.execute("UPDATE nodo SET estado='vigente' WHERE id=?", (origen,))
            con.execute(
                "INSERT INTO vinculo(de,relacion,a,activo,fecha,autor,origen) VALUES (?,?,?,1,?,?,?)",
                (bid, "motivada_por", origen, k.ahora(), "persona:Ariel", "{}"),
            )
            con.commit()
    rid = _regla_cuestionada(pid, origen)
    assert [x["creencia"] for x in c.checklist(pid, CTX)["items"]] == [bid]  # Python solo no lo ve
    out = _checklist(pid)
    assert out["items"] == [] and out["total"] == 0 and out["motor"]["diferencias"] == []
    (item,) = out["cuestionadas"]
    assert (
        out["cuestionadas_total"] == 1 and item["estado"] == "cuestionada" and item["motivo"] == pk.MOTIVO_CUESTIONADA
    )
    (por,) = item["cuestionada_por"]
    assert por["regla"] == rid and por["prueba"]["rule"].startswith("cuestionada_")
    assert out["no_aplican"] == [] and out["no_aplican_total"] == 0  # no se repite en las que no aplican


def test_sin_motor_el_checklist_sigue_sin_decir_sostenida(monkeypatch, tmp_path):
    pid = "chk-sin-motor"
    bid, _ = _creencia(pid)
    monkeypatch.setattr(motor, "ENGINE", tmp_path / "motor-logico/main.pl")
    out = _checklist(pid)
    assert out["motor"]["estado"] == "no_disponible" and "no encontrado" in out["motor"]["error"]
    (item,) = out["items"]
    assert item["creencia"] == bid and item["sostenida"] is None


def test_respuesta_invalida_o_diferencia_no_sostiene(monkeypatch):
    pid = "chk-invalida"
    bid, _ = _creencia(pid)
    monkeypatch.setattr(motor, "ENGINE", Path(__file__))
    monkeypatch.setattr(pc, "run", lambda payload, **kw: {"contract": 3})
    out = _checklist(pid)
    assert out["motor"]["estado"] == "respuesta_invalida" and out["items"][0]["sostenida"] is None

    # el motor responde bien pero no sostiene la que Python da por aplicable: queda cuestionada
    def sin_sostenida(output, facts, programa):
        found = {p: set() for p in pk.QUERIES}
        found["aplicable"] = {(bid,)}
        return found, {}

    monkeypatch.setattr(pc, "run", lambda payload, **kw: {"engine": {"name": "m", "version": "0"}, "program_hash": "h"})
    monkeypatch.setattr(pc, "resultados", sin_sostenida)
    out = _checklist(pid)
    assert out["items"] == [] and out["motor"]["estado"] == "con_diferencias"
    assert out["cuestionadas"][0]["motivo"] == pk.MOTIVO_DISCREPA
    assert {"consulta": "sostenida", "solo_prolog": [], "solo_python": [(bid,)]} in out["motor"]["diferencias"]


def test_motor_ocupado_no_traba_el_checklist(monkeypatch):
    pid = "chk-ocupado"
    _creencia(pid)

    def ocupado(payload, **kw):
        raise k.Rechazo("El contraste lógico está ocupado; volvé a consultar", 409)

    monkeypatch.setattr(pc, "run", ocupado)
    out = _checklist(pid)
    assert out["motor"]["estado"] == "no_disponible" and out["items"][0]["sostenida"] is None


def test_sin_creencias_no_consulta_el_motor(monkeypatch):
    pid = "chk-vacio"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(pc, "run", lambda payload, **kw: pytest.fail("no hay nada que contrastar"))
    out = _checklist(pid)
    assert out["motor"]["estado"] == "sin_creencias" and out["items"] == []


def test_el_encargo_dice_si_lo_mostrado_no_tuvo_contraste(monkeypatch, tmp_path):
    pid = "chk-encargo"
    bid, _ = _creencia(pid)
    monkeypatch.setattr(motor, "ENGINE", tmp_path / "motor-logico/main.pl")
    ronda = k.abrir_ronda(pid, "ronda", autor="coordinadora")
    code, out = api.dispatch(
        "POST",
        [pid, "encargos"],
        {"ronda": ronda["id"], "letra": "A", "texto": "# A", "contexto_desarrollo": CTX},
        None,
    )
    assert code == 200 and [x["creencia"] for x in out["aprendizajes"]] == [bid]
    assert "sin contraste del motor lógico" in out["aprendizajes_texto"]
    assert out["datos"]["aprendizajes_mostrados"][0]["sostenida"] is False


def _grafo_aleatorio(pid, rng):
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat()
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    k.registrar_proyecto(pid)
    evidence = k.crear_nodo(pid, "evidencia", "evidencia", {}, autor="persona:Ariel")["id"]
    sources = [k.crear_nodo(pid, rng.choice(["hallazgo", "medicion"]), f"f{i}", {}, autor="server") for i in range(4)]
    decisions = [k.crear_nodo(pid, "decision", f"d{i}", {}, autor="server")["id"] for i in range(3)]
    beliefs = [
        k.crear_nodo(pid, "decision", f"c{i}", {"clase": "creencia_operativa"}, autor="server")["id"] for i in range(10)
    ]
    rules = [k.crear_nodo(pid, "regla", f"r{i}", {}, autor="server")["id"] for i in range(3)]
    with k._abrir(pid) as con:
        ins = "INSERT OR IGNORE INTO vinculo(de,relacion,a,activo,fecha,autor,origen) VALUES (?,?,?,?,?,?,?)"
        for s in sources:
            fallen = {"hallazgo": "rechazado", "medicion": "rechazada"}[s["tipo"]]
            con.execute(
                "UPDATE nodo SET estado=? WHERE id=?", (fallen if rng.random() < 0.25 else s["estado"], s["id"])
            )
        for d in decisions:
            con.execute("UPDATE nodo SET estado=? WHERE id=?", (rng.choice(["vigente", "vigente", "revertida"]), d))
        for r in rules:
            con.execute("UPDATE nodo SET estado=? WHERE id=?", (rng.choice(["cuestionada", "vigente"]), r))
            con.execute(ins, (r, "derivada_de", rng.choice(beliefs + decisions), 1, "x", "server", "{}"))
        for b in beliefs:
            data = {
                "clase": "creencia_operativa",
                "resultado": rng.choice(["validada"] * 6 + ["refutada", None]),
                "veredicto_por": rng.choice(["persona:Ariel"] * 6 + ["frente:x", None]),
                "evidencia_veredicto": rng.choice([evidence] * 5 + ["otra"]),
                "vigente_hasta": rng.choice([future, future, past, "2026-10-19T00:00:00", None]),
                "contexto": rng.choice(
                    [
                        CTX,
                        CTX,
                        CTX,
                        {"tipo_trabajo": "bugfix"},
                        {"tipo_trabajo": "refactor"},
                        {"fase": "x"},
                        {},
                        {"tipo_trabajo": True},
                        {"otro": "x"},
                        None,
                    ]
                ),
            }
            state = rng.choice(["vigente"] * 8 + ["propuesta", "revertida", "reemplazada"])
            con.execute("UPDATE nodo SET estado=?, datos=? WHERE id=?", (state, json.dumps(data), b))
            if rng.random() < 0.8:
                con.execute(ins, (b, "apoya", evidence, int(rng.random() < 0.85), "x", "persona:Ariel", "{}"))
            for target in rng.sample(beliefs + decisions + [s["id"] for s in sources], rng.choice([0, 1, 2])):
                if target != b:
                    con.execute(ins, (b, "motivada_por", target, 1, "x", "server", "{}"))
        for d in decisions:
            for target in rng.sample(decisions + [s["id"] for s in sources], rng.choice([0, 1, 2])):
                if target != d:
                    con.execute(ins, (d, "motivada_por", target, 1, "x", "server", "{}"))
        con.commit()


def test_modelo_python_desde_hechos_igual_a_creencias_en_grafos_aleatorios():
    """Sin motor: la lectura desde los hechos coincide con creencias._evaluar en cada estado."""
    rng = random.Random(20261022)
    seen = set()
    for n in range(30):
        pid = f"chk-modelo-{n}"
        _grafo_aleatorio(pid, rng)
        evaluated, facts = pk._foto(pid, CTX)
        model = pk._modelo(facts)
        for node, state, _ in evaluated:
            found = [s for s in pk.ESTADOS if any(r[0] == node["id"] for r in model[s])]
            assert found == [state], (n, node["id"])
            seen.add(state)
        seen |= {"cuestionada"} if model["cuestionada"] else set()
    assert seen == set(c.MOTIVOS) | {"cuestionada"}


@REAL
def test_motor_real_igual_a_python_en_grafos_aleatorios():
    rng = random.Random(20261022)
    sostenidas = cuestionadas = 0
    for n in range(12):
        pid = f"chk-real-{n}"
        _grafo_aleatorio(pid, rng)
        out = _checklist(pid)
        assert out["motor"].get("diferencias") == [], (n, out["motor"])
        assert out["motor"]["estado"] == "sostenido"
        assert all(x["sostenida"]["prueba"]["rule"] == "sostenida" for x in out["items"])
        assert all(x["cuestionada_por"] for x in out["cuestionadas"])
        sostenidas, cuestionadas = sostenidas + out["total"], cuestionadas + out["cuestionadas_total"]
    assert sostenidas and cuestionadas  # el muestreo pasó por las dos salidas


def test_una_prueba_con_comparacion_falsa_se_rechaza():
    """El motor no pone las comparaciones en la prueba: Lienzo las comprueba con las ligaduras."""
    facts = [pc._lit("activa", "b"), pc._lit("hasta", "b", 100), pc._lit("ahora", 200)]
    leaf = lambda f: {"by": "given", "fact": f, "sources": []}
    proof = {
        "by": "rule",
        "rule": "en_fecha",
        "fact": {"pred": "en_fecha", "args": ["b"]},
        "premises": [
            leaf({"pred": "activa", "args": ["b"]}),
            {"not": {"pred": "con_caida", "args": ["b"]}},
            leaf({"pred": "hasta", "args": ["b", 100]}),
            leaf({"pred": "ahora", "args": [200]}),
        ],
    }
    hechos = {(f["pred"], tuple(f["args"])) for f in facts}
    with pytest.raises(ValueError, match="comparación"):
        pc._prueba(proof, hechos, {"con_caida": set()}, 0, pk.RULE_BY_ID, pk.BASE)
    hechos = (hechos - {("hasta", ("b", 100))}) | {("hasta", ("b", 300))}
    proof["premises"][2] = leaf({"pred": "hasta", "args": ["b", 300]})
    assert pc._prueba(proof, hechos, {"con_caida": set()}, 0, pk.RULE_BY_ID, pk.BASE) is False


def test_resumen_del_tablero_cuenta_por_proyecto_sin_escribir():
    bid, _ = _creencia("chk-resumen")
    _creencia("chk-resumen", texto="otra", validar=False)
    _regla_cuestionada("chk-resumen", bid)
    k.registrar_proyecto("chk-resumen-vacio")
    code, out = api.dispatch("GET", ["aprendizaje-resumen"], None, {})
    assert code == 200
    (fila,) = [x for x in out if x["proyecto"] == "chk-resumen"]
    assert fila["creencias"] == {"vigente": 1, "propuesta": 1} and fila["reglas_cuestionadas"] == 1
    assert not [x for x in out if x["proyecto"] == "chk-resumen-vacio"]  # sin nada que mirar no aparece


def test_regla_cuestionada_con_dos_origenes_cuestiona_a_las_dos():
    """Una regla derivada de dos creencias: el modelo Python no puede quedarse con un solo origen."""
    facts = [
        {**f, "source": "grafo"}
        for f in [
            pc._lit("nodo", "b1", "decision", "vigente"),
            pc._lit("nodo", "b2", "decision", "vigente"),
            pc._lit("nodo", "r", "regla", "cuestionada"),
            pc._lit("deriva", "r", "b1"),
            pc._lit("deriva", "r", "b2"),
            pc._lit("ahora", 1),
        ]
    ]
    for b in ("b1", "b2"):
        facts += [
            pc._lit(p, *a)
            for p, a in (
                ("creencia", (b,)),
                ("veredicto", (b, "validada")),
                ("por_persona", (b,)),
                ("evidencia_veredicto", (b, "e")),
                ("apoyo", (b, "e")),
                ("hasta", (b, 9)),
            )
        ]
    model = pk._modelo(facts)
    assert model["cuestionada"] == {("b1", "r"), ("b2", "r")} and model["sostenida"] == set()


def test_crear_un_encargo_no_espera_que_arranque_wsl(monkeypatch):
    """El alta de un encargo no espera el arranque de WSL (hasta 90 s): la coordinadora corta a los 20 s
    y su reintento daría 409. Con WSL dormido lo mostrado va sin contraste; despertarlo es de la vista."""
    pid = "chk-encargo-frio"
    bid, _ = _creencia(pid)
    monkeypatch.setattr(motor, "WSL", True)
    monkeypatch.setattr(motor, "_ultimo_ok", None)
    monkeypatch.setattr(motor, "despertar", lambda: pytest.fail("el alta de un encargo no despierta WSL"))
    ronda = k.abrir_ronda(pid, "ronda", autor="coordinadora")
    code, out = api.dispatch(
        "POST",
        [pid, "encargos"],
        {"ronda": ronda["id"], "letra": "A", "texto": "# A", "contexto_desarrollo": CTX},
        None,
    )
    assert code == 200 and [x["creencia"] for x in out["aprendizajes"]] == [bid]
    assert "sin contraste del motor lógico" in out["aprendizajes_texto"]


def test_contexto_sugerido_sale_del_encargo_de_la_sesion_y_de_su_tarjeta():
    """Agregado de Ariel (12:11): el contexto se completa solo desde la sesión elegida o el encargo en curso."""
    pid = "chk-sugerido"
    k.registrar_proyecto(pid)
    ronda = k.abrir_ronda(pid, "ronda", autor="coordinadora")
    viejo = k.crear_encargo(
        pid, ronda["id"], "A", "# A", autor="coordinadora", contexto_desarrollo={"tipo_trabajo": "feature"}
    )
    nuevo = k.crear_encargo(
        pid,
        ronda["id"],
        "B",
        "# B",
        autor="coordinadora",
        contexto_desarrollo={"tipo_trabajo": "bugfix", "tecnologia": "python", "area": "memoria"},
    )
    k.encargo_enviado(pid, nuevo["id"], {"session_id": "s-uno", "agent": "claude", "model": "opus"})
    out = c.contexto_sugerido(pid, session_id="s-uno", tarjeta={"agent": "claude", "model": "claude-opus-5-5"})
    assert out["contexto"] == {
        "tipo_trabajo": "bugfix",
        "tecnologia": "python",
        "area": "memoria",
        "agente": "claude",
        "modelo": "claude-opus-5-5",
    }
    assert out["encargo"] == nuevo["id"] and "B" in out["fuente"]
    # sin sesión: el encargo en curso más nuevo del proyecto
    out = c.contexto_sugerido(pid)
    assert out["encargo"] == nuevo["id"] and out["contexto"]["tipo_trabajo"] == "bugfix"
    # una sesión sin encargo acá suma su tarjeta al encargo en curso; sin_clasificar no se sugiere como tipo
    k.crear_encargo(
        pid, ronda["id"], "C", "# C", autor="coordinadora", contexto_desarrollo={"tipo_trabajo": "sin_clasificar"}
    )
    out = c.contexto_sugerido(pid, session_id="s-otra", tarjeta={"agent": "codex"})
    assert out["contexto"] == {"tipo_trabajo": "bugfix", "tecnologia": "python", "area": "memoria", "agente": "codex"}
    assert out["encargo"] == nuevo["id"] != viejo["id"]


def test_contexto_sugerido_por_http_lee_la_tarjeta_viva(monkeypatch):
    import sessions as ses

    pid = "chk-sugerido-http"
    k.registrar_proyecto(pid)
    monkeypatch.setitem(ses.sessions, "s-viva", {"session_id": "s-viva", "agent": "codex", "model": "gpt-5"})
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {"session_id": "s-viva"})
    assert code == 200 and out["contexto"] == {"agente": "codex", "modelo": "gpt-5"}
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {})
    assert code == 200 and out == {"contexto": {}, "encargo": None, "fuente": None, "fuentes": {}, "session_id": None}


def test_una_tarjeta_de_otro_proyecto_no_sugiere(monkeypatch, tmp_path):
    import sessions as ses

    pid = "chk-sugerido-ajeno"
    k.registrar_proyecto(pid)
    monkeypatch.setitem(ses.sessions, "s-ajena", {"session_id": "s-ajena", "agent": "codex", "cwd": str(tmp_path)})
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {"session_id": "s-ajena"})
    assert code == 200 and out["contexto"] == {}


def test_sugerido_sin_encargo_de_la_sesion_cae_al_en_curso_y_no_atribuye_lo_vacio():
    """Revisión del agregado: una sesión sin encargo acá no tapa el encargo en curso del proyecto, la
    fuente nombra un encargo sólo si aportó algo, y los valores se recortan como los de la API."""
    pid = "chk-sugerido-caida"
    k.registrar_proyecto(pid)
    ronda = k.abrir_ronda(pid, "ronda", autor="coordinadora")
    curso = k.crear_encargo(
        pid,
        ronda["id"],
        "A",
        "# A",
        autor="coordinadora",
        contexto_desarrollo={"tipo_trabajo": "bugfix", "tecnologia": "  python  ", "area": "x" * 100},
    )
    out = c.contexto_sugerido(pid, session_id="s-sin-encargo", tarjeta={"agent": "claude"})
    assert out["encargo"] == curso["id"] and out["contexto"]["agente"] == "claude"
    assert out["contexto"]["tecnologia"] == "python" and len(out["contexto"]["area"]) == 100
    vacio = k.crear_encargo(
        pid, ronda["id"], "B", "# B", autor="coordinadora", contexto_desarrollo={"tipo_trabajo": "sin_clasificar"}
    )
    k.encargo_enviado(pid, vacio["id"], {"session_id": "s-vacia", "agent": "codex"})
    out = c.contexto_sugerido(pid, session_id="s-vacia", tarjeta={"agent": "codex"})
    assert out["encargo"] == curso["id"]  # el de la sesión no aportó nada: vale el en curso
    assert "A" in out["fuente"] and out["contexto"]["tipo_trabajo"] == "bugfix"


def test_una_tarjeta_resuelta_por_remote_cuenta_como_del_proyecto(monkeypatch, tmp_path):
    """Revisión del agregado: una tarjeta cuya carpeta no está registrada se resuelve por su remote."""
    import sessions as ses

    pid = "chk-sugerido-remote"
    k.registrar_proyecto(pid, remotes=["github.com/ariel/chk-remote"])
    monkeypatch.setitem(
        ses.sessions,
        "s-remote",
        {"session_id": "s-remote", "agent": "claude", "cwd": str(tmp_path), "repo_key": "github.com/ariel/chk-remote"},
    )
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {"session_id": "s-remote"})
    assert code == 200 and out["contexto"] == {"agente": "claude"}
