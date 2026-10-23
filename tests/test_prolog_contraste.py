"""Contraste lógico de candidatos (contrato 3): SWI real contra el oráculo Python, casos dirigidos por
observación, snapshot en solo lectura y fallos visibles. Ninguna prueba promueve ni cierra nada."""

import json
import random
import shutil
import sqlite3
from pathlib import Path

import conocimiento as k
import prolog_contraste as pc
import prolog_learning as motor
import pytest

REAL = pytest.mark.skipif(
    not (shutil.which("wsl.exe") or shutil.which("swipl")) or not motor.ENGINE.is_file(),
    reason="Falta WSL/SWI-Prolog o el repo motor-logico",
)


def nodo(i, tipo, estado, clase=None, autor=None):
    facts = [pc._lit("nodo", i, tipo, estado or pc.SIN_ESTADO, source="grafo")]
    facts += [pc._lit("clase", i, clase, source="grafo")] if clase else []
    if tipo == "evidencia":
        facts.append(pc._lit("autor_rol", i, autor or "server", source="grafo"))
    return facts


def v(de, rel, a, activo=True):
    return pc._lit("vinculo" if activo else "vinculo_retirado", de, rel, a, source="grafo")


def real(facts):
    return pc.resultados(pc.run(pc.consulta(facts)), facts)


def base():
    """c: propuesta con evidencia de una persona; nada observado."""
    return [*nodo("c", "decision", "propuesta"), *nodo("e", "evidencia", None, autor="persona"), v("c", "apoya", "e")]


CASOS = {
    "listo": ([], {"listo_para_revision": {("c",)}}),
    "respaldo caído transitivo por decisiones": (
        [
            *nodo("d", "decision", "vigente"),
            *nodo("h", "hallazgo", "rechazado"),
            v("c", "motivada_por", "d"),
            v("d", "motivada_por", "h"),
        ],
        {"respaldo_caido": {("c", "h")}, "listo_para_revision": set()},
    ),
    "la cadena no atraviesa un hallazgo": (
        [
            *nodo("x", "hallazgo", "confirmado"),
            *nodo("y", "hallazgo", "rechazado"),
            v("c", "motivada_por", "x"),
            v("x", "motivada_por", "y"),
        ],
        {"respaldo_caido": set(), "listo_para_revision": {("c",)}},
    ),
    "ciclo entre decisiones termina": (
        [*nodo("d", "decision", "vigente"), v("c", "motivada_por", "d"), v("d", "motivada_por", "c")],
        {"respaldo_caido": set(), "listo_para_revision": {("c",)}},
    ),
    "regla derivada de una decisión revertida": (
        [*nodo("r", "regla", "propuesta"), *nodo("d", "decision", "revertida"), v("r", "derivada_de", "d")],
        {"respaldo_caido": {("r", "d")}},
    ),
    "reemplaza una regla cuestionada": (
        [*nodo("q", "regla", "cuestionada"), v("c", "reemplaza", "q")],
        {"regla_cuestionada": {("c", "q")}, "listo_para_revision": set()},
    ),
    "contradice una decisión vigente": (
        [
            *nodo("a", "alternativa", None),
            *nodo("d", "decision", "vigente"),
            v("c", "elige", "a"),
            v("d", "descarta", "a"),
        ],
        {"contradice": {("c", "d", "a")}, "listo_para_revision": set()},
    ),
    "una decisión revertida no contradice": (
        [
            *nodo("a", "alternativa", None),
            *nodo("d", "decision", "revertida"),
            v("c", "elige", "a"),
            v("d", "descarta", "a"),
        ],
        {"contradice": set(), "listo_para_revision": {("c",)}},
    ),
    "reabre un hallazgo rechazado": (
        [*nodo("h1", "hallazgo", "propuesto"), *nodo("h0", "hallazgo", "rechazado"), v("h1", "mismo_que", "h0")],
        {"reabre_rechazado": {("h1", "h0")}, "sin_evidencia_independiente": {("h1",)}},
    ),
    "apoyo retirado": (
        [*nodo("e2", "evidencia", None, autor="persona"), v("c", "apoya", "e2", activo=False)],
        {"apoyo_retirado": {("c", "e2")}, "listo_para_revision": set()},
    ),
    "evidencia autogenerada no es contraste": (
        [
            *nodo("p", "decision", "propuesta"),
            *nodo("ia", "evidencia", None, clase="investigacion_cli"),
            v("p", "apoya", "ia"),
        ],
        {
            "sin_evidencia_independiente": {("p",)},
            "independencia_no_verificada": set(),
            "listo_para_revision": {("c",)},
        },
    ),
    "clase desconocida de un agente no prueba independencia": (
        [
            *nodo("p", "decision", "propuesta"),
            *nodo("x", "evidencia", None, clase="clase_nueva", autor="frente"),
            v("p", "apoya", "x"),
        ],
        {"sin_evidencia_independiente": {("p",)}, "independencia_no_verificada": {("p",)}},
    ),
    "evidencia sin clase del server queda sin verificar": (
        [*nodo("p", "decision", "propuesta"), *nodo("x", "evidencia", None), v("p", "apoya", "x")],
        {"independencia_no_verificada": {("p",)}, "listo_para_revision": {("c",)}},
    ),
    "evidencia de persona cuenta aunque haya autogenerada": (
        [
            *nodo("ia", "evidencia", None, clase="investigacion_cli"),
            v("c", "apoya", "ia"),
        ],
        {"sin_evidencia_independiente": set(), "listo_para_revision": {("c",)}},
    ),
    "una vigente no es candidata": (
        [*nodo("w", "decision", "vigente"), v("w", "apoya", "e")],
        {"candidato": {("c",)}},
    ),
}


@pytest.mark.parametrize("name", list(CASOS))
def test_oraculo_por_observacion(name):
    extra, expected = CASOS[name]
    rows = pc.oraculo(base() + extra)
    for pred, value in expected.items():
        assert rows[pred] == value, pred


@REAL
@pytest.mark.parametrize("name", list(CASOS))
def test_motor_real_por_observacion(name):
    extra, expected = CASOS[name]
    facts = base() + extra
    found, why = real(facts)
    assert found == pc.oraculo(facts)
    for pred, value in expected.items():
        assert found[pred] == value, pred
    for pred in pc.OBSERVACIONES:  # cada observación trae su prueba, que cierra contra hechos enviados
        for row in found[pred]:
            assert why[(pred, row)]["prueba"]["rule"] in pc.RULE_IDS
            assert why[(pred, row)]["fuentes"] == ["grafo"] and why[(pred, row)]["prueba_truncada"] is False


@REAL
def test_motor_real_igual_al_oraculo_en_grafos_aleatorios():
    """Diferencial sembrado: estados, clases, vínculos activos y retirados, ciclos y oposiciones."""
    estados = {
        "decision": ["propuesta", "vigente", "revertida", "reemplazada"],
        "hallazgo": ["propuesto", "confirmado", "rechazado", "corregido"],
        "regla": ["propuesta", "vigente", "cuestionada", "retirada"],
        "medicion": ["propuesta", "valida", "rechazada"],
        "evidencia": [None],
        "alternativa": [None],
    }
    rels = ["motivada_por", "derivada_de", "apoya", "mismo_que", "reemplaza", "elige", "descarta"]
    for seed in range(25):
        rnd = random.Random(seed)
        ids = [f"n{i}" for i in range(rnd.randint(4, 18))]
        facts = []
        for i in ids:
            tipo = rnd.choice(list(estados))
            clase = (
                rnd.choice([None, None, "investigacion_cli", "analisis_optimizacion", "prueba"])
                if tipo == "evidencia"
                else None
            )
            autor = rnd.choice(["persona", "server", "frente", "desconocido"])
            facts += nodo(i, tipo, rnd.choice(estados[tipo]), clase, autor)
        for _ in range(rnd.randint(0, 30)):
            facts.append(v(rnd.choice(ids), rnd.choice(rels), rnd.choice(ids), activo=rnd.random() > 0.2))
        assert real(facts)[0] == pc.oraculo(facts), f"semilla {seed}"


@REAL
def test_textos_que_parecen_codigo_son_datos():
    facts = base() + nodo('x"),halt(77),write("y', "decision", "propuesta")
    assert ('x"),halt(77),write("y',) in real(facts)[0]["sin_evidencia_independiente"]


# ------------------------------------------------------------------ grafo real en tmp, solo lectura


def _escribir_estado(pid, nid, estado):
    with sqlite3.connect(k.db_path()) as con:  # fuerza estados que la API no arma en una prueba corta
        con.execute("UPDATE nodo SET estado=? WHERE proyecto=? AND id=?", (estado, pid, nid))


def _grafo(pid="contraste"):
    k.registrar_proyecto(pid)
    fuente = k.crear_nodo(pid, "hallazgo", "fuente", {}, autor="server")
    cand = k.crear_nodo(
        pid,
        "decision",
        "propuesta del investigador",
        {"clase": "propuesta_investigacion", "requiere_veredicto": True},
        autor="server",
    )
    auto = k.crear_nodo(pid, "evidencia", "investigación", {"clase": "investigacion_cli"}, autor="server")
    k.vincular(pid, cand["id"], "motivada_por", fuente["id"], autor="server", motivo="fuente citada")
    k.vincular(pid, cand["id"], "apoya", auto["id"], autor="server")
    return pid, fuente["id"], cand["id"]


def _foto():
    with sqlite3.connect(k.db_path()) as con:
        return con.execute("SELECT * FROM nodo ORDER BY id").fetchall(), con.execute(
            "SELECT * FROM vinculo ORDER BY de, a"
        ).fetchall()


def test_snapshot_lee_el_grafo_sin_escribir():
    pid, fuente, cand = _grafo()
    antes = _foto()
    snap = pc.snapshot(pid)
    assert _foto() == antes
    preds = {(f["pred"], tuple(f["args"])) for f in snap["facts"]}
    assert ("vinculo", (cand, "motivada_por", fuente)) in preds
    assert ("nodo", (fuente, "hallazgo", "propuesto")) in preds
    assert all(f.get("source") == "grafo" for f in snap["facts"])
    rows = pc.oraculo(snap["facts"])
    # el hallazgo fuente nace propuesto: también espera veredicto
    assert rows["candidato"] == {(cand,), (fuente,)}
    assert rows["sin_evidencia_independiente"] == {(cand,), (fuente,)} and rows["listo_para_revision"] == set()


def test_snapshot_rechaza_proyecto_desconocido_y_excesos(monkeypatch):
    with pytest.raises(k.Rechazo):
        pc.snapshot("no-existe")
    pid, _, _ = _grafo("contraste-grande")
    monkeypatch.setattr(pc, "MAX_NODOS", 1)
    with pytest.raises(k.Rechazo, match="no se contrasta con datos truncados"):
        pc.snapshot(pid)


@REAL
def test_contrastar_grafo_real_sin_escribir_y_ve_la_fuente_caida():
    pid, fuente, cand = _grafo()
    antes = _foto()
    code, out = pc.contrastar(pid)
    assert code == 200 and out["diferencias_python"] == [] and out["concluyente"] is True and _foto() == antes
    assert out["candidatos"][cand]["evidencia_independiente"] == "ausente"
    assert out["candidatos"][cand]["listo_para_revision"] is False
    assert out["motor"]["name"] == "motor-logico" and out["program_hash"].startswith("sha256:")
    _escribir_estado(pid, fuente, "rechazado")
    code, out = pc.contrastar(pid)
    assert code == 200 and out["diferencias_python"] == []
    [obs] = out["candidatos"][cand]["observaciones"]
    assert obs["tipo"] == "respaldo_caido" and obs["con"] == [fuente] and obs["prueba"]["rule"] == "respaldo_caido"
    assert k.nodo(pid, cand)["estado"] == "propuesta"  # nunca promueve ni rechaza


@REAL
def test_con_diferencias_no_declara_listo(monkeypatch):
    pid, _, cand = _grafo()
    evidencia = k.crear_nodo(pid, "evidencia", "prueba humana", {"clase": "prueba"}, autor="persona:Ariel")
    k.vincular(pid, cand, "apoya", evidencia["id"], autor="persona:Ariel")
    code, out = pc.contrastar(pid)
    assert code == 200 and out["candidatos"][cand]["listo_para_revision"] is True
    assert out["candidatos"][cand]["justificacion_listo"]["prueba"]["rule"] == "listo_para_revision"
    original = pc.oraculo
    monkeypatch.setattr(pc, "oraculo", lambda facts: {**original(facts), "listo_para_revision": set()})
    code, out = pc.contrastar(pid)
    assert code == 200 and out["concluyente"] is False and out["diferencias_python"]
    assert (
        out["candidatos"][cand]["listo_para_revision"] is None
        and out["candidatos"][cand]["justificacion_listo"] is None
    )


# ------------------------------------------------------------------ fallos visibles


def test_motor_ausente_o_caido_no_es_vacio(monkeypatch, tmp_path):
    monkeypatch.setattr(motor, "despertar", lambda: None)
    pid, _, _ = _grafo()
    monkeypatch.setattr(motor, "ENGINE", tmp_path / "motor-logico/main.pl")
    code, out = pc.contrastar(pid)
    assert code == 503 and out["code"] == "prolog_unavailable" and "candidatos" not in out

    monkeypatch.setattr(motor, "ENGINE", Path(__file__))  # existe: se prueba el proceso, no la ruta

    import prolog_servicio

    def timeout(*a, **kw):
        raise prolog_servicio.ErrorServicio("plazo del motor excedido")

    monkeypatch.setattr(prolog_servicio, "consultar", timeout)
    assert pc.contrastar(pid)[0] == 503


def test_rechazo_del_motor_informa_su_codigo(monkeypatch):
    monkeypatch.setattr(motor, "despertar", lambda: None)
    pid, _, _ = _grafo()
    monkeypatch.setattr(motor, "ENGINE", Path(__file__))
    import prolog_servicio

    def reject(*args, **kwargs):
        raise prolog_servicio.ErrorServicio("unsafe_rule: x")

    monkeypatch.setattr(prolog_servicio, "consultar", reject)
    code, out = pc.contrastar(pid)
    assert code == 503 and "unsafe_rule" in out["error"]


@pytest.mark.parametrize(
    "romper",
    [
        lambda o: o.update(contract=2),
        lambda o: o.update(contract=True),
        lambda o: o["answers"].pop(),
        lambda o: o["answers"][0].update(truncated=True),
        lambda o: o["answers"][0]["results"].append({"bindings": {"C": "ajeno"}}),
        lambda o: o["answers"][0]["results"][0].update(bindings={"X": "c"}),
        lambda o: o["answers"][0].update(count=9),
        lambda o: o.pop("program_hash"),
        lambda o: o["answers"][1].pop("results"),
        lambda o: o["answers"][1].update(results=None),
        lambda o: o["answers"][1].update(count=False),
        lambda o: o["answers"][0]["results"][0].pop("proof"),
        lambda o: o["answers"][0]["results"][0].pop("sources"),
        lambda o: o["answers"][0]["results"][0]["proof"].update(rule="ajena"),
        lambda o: o["answers"][0]["results"][0]["proof"]["premises"][0]["fact"].update(
            args=["c", "decision", "vigente"]
        ),
        lambda o: o["answers"][0]["results"][0]["proof"]["premises"].append(
            {"by": "stored", "fact": {"pred": "nodo", "args": []}}
        ),
        lambda o: o["answers"][0]["results"][0]["proof"]["premises"].append("x"),
        lambda o: o["answers"][0]["results"][0]["proof"]["fact"].update(args=["e"]),
    ],
)
def test_respuesta_invalida_es_error(romper):
    facts = base()
    leaf = {"by": "given", "fact": {"pred": "nodo", "args": ["c", "decision", "propuesta"]}, "sources": ["grafo"]}
    proof = {
        "by": "rule",
        "rule": "candidato_decision",
        "fact": {"pred": "candidato", "args": ["c"]},
        "premises": [leaf],
    }
    good = {
        "contract": 3,
        "domain": "logic",
        "engine": {"name": "motor-logico", "version": "0.2.0"},
        "program_hash": "sha256:x",
        "answers": [
            {
                "pred": p,
                "truncated": False,
                "count": 1 if p == "candidato" else 0,
                "results": [{"bindings": {"C": "c"}, "proof": proof, "sources": ["grafo"]}] if p == "candidato" else [],
            }
            for p in pc.QUERIES
        ],
    }
    found, why = pc.resultados(json.loads(json.dumps(good)), facts)
    assert found["candidato"] == {("c",)} and why[("candidato", ("c",))]["prueba_truncada"] is False
    broken = json.loads(json.dumps(good))
    romper(broken)
    with pytest.raises((ValueError, TypeError)):
        pc.resultados(broken, facts)


def test_prueba_valida_todas_las_premisas_aunque_una_este_truncada():
    """Una premisa recortada no excusa a la siguiente: se validan todas antes de agregar."""
    facts = base()
    hechos = {(f["pred"], tuple(f["args"])) for f in facts}
    negables = pc._modelo(facts)

    def given(pred, *args):
        return {"by": "given", "fact": {"pred": pred, "args": list(args)}, "sources": ["grafo"]}

    humana = {
        "by": "rule",
        "rule": "humana",
        "fact": {"pred": "humana", "args": ["e"]},
        "premises": [given("autor_rol", "e", "persona")],
    }
    proof = {"by": "rule", "rule": "evidencia_humana", "fact": {"pred": "evidencia_humana", "args": ["c"]}}
    recorte = {"by": "truncated", "fact": {"pred": "candidato", "args": ["c"]}}
    ok = [recorte, given("vinculo", "c", "apoya", "e"), given("nodo", "e", "evidencia", "sin_estado"), humana]
    assert pc._prueba({**proof, "premises": ok}, hechos, negables) is True
    mala = [recorte, given("vinculo", "c", "apoya", "e"), given("nodo", "c", "decision", "propuesta"), humana]
    with pytest.raises(ValueError):
        pc._prueba({**proof, "premises": mala}, hechos, negables)


@REAL
def test_listo_con_prueba_recortada_queda_sin_conclusion(monkeypatch):
    pid, _, cand = _grafo("contraste-recorte")
    evidencia = k.crear_nodo(pid, "evidencia", "prueba humana", {"clase": "prueba"}, autor="persona:Ariel")
    k.vincular(pid, cand, "apoya", evidencia["id"], autor="persona:Ariel")
    original = pc.resultados

    def recortar(output, facts):
        found, why = original(output, facts)
        return found, {
            key: {**j, "prueba_truncada": key[0] == "listo_para_revision" or j["prueba_truncada"]}
            for key, j in why.items()
        }

    monkeypatch.setattr(pc, "resultados", recortar)
    code, out = pc.contrastar(pid)
    assert code == 200 and out["concluyente"] is True
    assert (
        out["candidatos"][cand]["listo_para_revision"] is None
        and out["candidatos"][cand]["justificacion_listo"] is None
    )


# ------------------------------------------------------------------ API


@REAL
def test_api_contraste_es_post_explicito_sin_escrituras():
    import aprendizaje_api

    pid, fuente, cand = _grafo("contraste-api")
    antes = _foto()
    code, out = aprendizaje_api.dispatch("POST", [pid, "candidatos", "contraste"], {}, {})
    assert code == 200 and out["concluyente"] is True and cand in out["candidatos"] and _foto() == antes
    assert out["nodos"][cand]["texto"] == "propuesta del investigador"
    assert aprendizaje_api.dispatch("GET", [pid, "candidatos", "contraste"], {}, {})[0] == 404
    assert aprendizaje_api.dispatch("POST", ["no-existe", "candidatos", "contraste"], {}, {})[0] == 404


# ------------------------------------------------------------------ pruebas coherentes con las reglas


def _salida_con(prueba, pred="candidato", row=("c",)):
    names = pc.QUERIES[pred]
    return {
        "contract": 3,
        "domain": "logic",
        "engine": {"name": "motor-logico", "version": "0.2.0"},
        "program_hash": "sha256:x",
        "answers": [
            {
                "pred": p,
                "truncated": False,
                "count": 1 if p == pred else 0,
                "results": [{"bindings": dict(zip(names, row, strict=True)), "proof": prueba, "sources": ["grafo"]}]
                if p == pred
                else [],
            }
            for p in pc.QUERIES
        ],
    }


LEAF_C = {"by": "given", "fact": {"pred": "nodo", "args": ["c", "decision", "propuesta"]}, "sources": ["grafo"]}
CANDIDATO_C = {
    "by": "rule",
    "rule": "candidato_decision",
    "fact": {"pred": "candidato", "args": ["c"]},
    "premises": [LEAF_C],
}


@pytest.mark.parametrize(
    "prueba",
    [
        # contraejemplo de la raíz: regla ajena a la cabeza y sin premisas
        {
            "by": "rule",
            "rule": "caida_hallazgo_rechazado",
            "fact": {"pred": "candidato", "args": ["c"]},
            "premises": [],
        },
        # regla correcta sin premisas
        {**CANDIDATO_C, "premises": []},
        # premisa de otro predicado que el cuerpo
        {**CANDIDATO_C, "premises": [{"by": "given", "fact": {"pred": "clase", "args": ["c", "x"]}, "sources": []}]},
        # la premisa no instancia la misma variable que la cabeza
        {
            **CANDIDATO_C,
            "premises": [
                {"by": "given", "fact": {"pred": "nodo", "args": ["e", "evidencia", "sin_estado"]}, "sources": []}
            ],
        },
        # constante del cuerpo distinta (tipo hallazgo en una regla de decisión)
        {**CANDIDATO_C, "premises": [{**LEAF_C, "fact": {"pred": "nodo", "args": ["c", "hallazgo", "propuesta"]}}]},
        # negación donde el cuerpo pide un literal positivo
        {**CANDIDATO_C, "premises": [{"not": {"pred": "nodo", "args": ["c", "decision", "propuesta"]}}]},
    ],
)
def test_prueba_incoherente_con_la_regla_es_error(prueba):
    with pytest.raises((ValueError, TypeError)):
        pc.resultados(_salida_con(prueba), base())


def test_negacion_falsa_es_error():
    """sin_evidencia_independiente(c) con «no evidencia_humana(c)» cuando c sí la tiene."""
    prueba = {
        "by": "rule",
        "rule": "sin_evidencia_independiente",
        "fact": {"pred": "sin_evidencia_independiente", "args": ["c"]},
        "premises": [CANDIDATO_C, {"not": {"pred": "evidencia_humana", "args": ["c"]}}],
    }
    with pytest.raises(ValueError, match="negación"):
        pc.resultados(_salida_con(prueba, "sin_evidencia_independiente"), base())


def test_prueba_coherente_se_acepta_y_un_recorte_quita_el_listo():
    found, why = pc.resultados(_salida_con(CANDIDATO_C), base())
    assert found["candidato"] == {("c",)} and why[("candidato", ("c",))]["prueba_truncada"] is False
    recortada = {**CANDIDATO_C, "premises": [{"by": "truncated", "fact": LEAF_C["fact"]}]}
    _, why = pc.resultados(_salida_con(recortada), base())
    assert why[("candidato", ("c",))]["prueba_truncada"] is True


@REAL
def test_router_real_despacha_el_contraste_sin_escrituras():
    import conocimiento_api

    pid, fuente, cand = _grafo("contraste-router")
    antes = _foto()
    code, out = conocimiento_api.dispatch("POST", [pid, "candidatos", "contraste"], {}, {})
    assert code == 200 and out["concluyente"] is True and set(out["candidatos"]) == {cand, fuente} and _foto() == antes
    assert conocimiento_api.dispatch("GET", [pid, "candidatos", "contraste"], {}, {})[0] == 404
    assert conocimiento_api.dispatch("POST", ["no-existe", "candidatos", "contraste"], {}, {})[0] == 404
    # el router rechaza un actor server en el cuerpo antes de llegar al contraste
    assert conocimiento_api.dispatch("POST", [pid, "candidatos", "contraste"], {"por": "server"}, {})[0] == 403
