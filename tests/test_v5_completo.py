"""Los huecos de v5 que la auditoria del 2026-10-09 encontro y cerro (tabla en el anexo B de v5):
respaldo de las transiciones (§3.4), vigente_desde por cualquier ruta, cuestionar al confirmar un
repite (§6.2), entrega tardia, «¿por que se descarto?» (§8.5.1), encargos abiertos (§4), briefing desde
los encargos y en Markdown (§7.2, etapa 5), fusion por mejor puesto y apoyo rechazado en los candidatos
(§7.1, §6.3), incidentes por agente entre proyectos (§4), bloque pendiente que se reincorpora (§5.2),
evidencia recibida (§8.2), respaldo con la API de backup (§8.3) y el cambio de la sesion (§8.4)."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import aprendizaje as ap
import conocimiento as k
import conocimiento_api as api
import veredictos as v
from conocimiento import Rechazo

P = "teorema"
C = "coordinadora:c"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    k.registrar_proyecto(P, "Teorema")


def _n(tipo, texto, datos=None):
    return k.crear_nodo(P, tipo, texto, datos or {}, autor="f")["id"]


def test_transiciones_con_respaldo():
    h = _n("hallazgo", "h", {"donde": "a.py:1", "gravedad": "baja"})
    k.cambiar_estado(P, h, "confirmado", por=C)
    with pytest.raises(Rechazo, match="corregido exige") as e:
        k.cambiar_estado(P, h, "corregido", por=C)
    assert e.value.codigo == 409
    ev = _n("evidencia", "parche", {"clase": "prueba", "referencia": "tests/a.py"})
    k.cambiar_estado(P, h, "corregido", por=C, origen={"evidencia": [ev]})  # evidencia citada
    i = _n("incidente", "se colgo", {"herramienta": "Bash", "agente": "codex"})
    k.vincular(P, i, "corregido_en", ev, autor=C)
    assert k.cambiar_estado(P, i, "resuelto", por=C)["estado"] == "resuelto"  # vinculo corregido_en
    p = _n("pregunta", "¿y?", {"para_quien": "ariel"})
    with pytest.raises(Rechazo, match="contesta"):
        k.cambiar_estado(P, p, "contestada", por=C)
    m1 = _n("medicion", "m1", {"metrica": "x", "valor": 1, "unidad": "ms", "condicion": "c"})
    k.cambiar_estado(P, m1, "valida", por=C)
    with pytest.raises(Rechazo, match="sucesora"):
        k.cambiar_estado(P, m1, "superada", por=C)
    m2 = _n("medicion", "m2", {"metrica": "x", "valor": 2, "unidad": "ms", "condicion": "c"})
    # en un veredicto el vinculo puede venir despues del estado: se mira al final
    v.veredicto(P, [{"nodo": m1, "estado": "superada"}, {"de": m2, "relacion": "reemplaza", "a": m1}], por=C)
    assert k.nodo(P, m1)["estado"] == "superada"


def test_regla_vigente_por_la_ruta_de_nodos_tiene_vigente_desde():
    i = _n("incidente", "timeout", {"herramienta": "red", "agente": "codex"})
    r = k.declarar_nodo(P, "regla", "reintentar", {"ambito": "proyecto"}, autor="f")["id"]
    k.vincular(P, r, "derivada_de", i, autor="f")
    code, n = api.dispatch("POST", [P, "nodos", r, "estado"], {"estado": "vigente", "por": C}, {})
    assert code == 200 and n["datos"]["vigente_desde"] == n["estado_fecha"]


def test_confirmar_un_repite_cuestiona_la_regla_en_el_acto():
    i1 = _n("incidente", "timeout del espejo", {"herramienta": "red", "agente": "codex"})
    r = _n("regla", "reintentar", {"ambito": "proyecto"})
    k.vincular(P, r, "derivada_de", i1, autor="f")
    k.cambiar_estado(P, r, "vigente", por=C)
    i2 = _n("incidente", "timeout del espejo otra vez", {"herramienta": "red", "agente": "codex"})
    res = v.veredicto(P, [{"de": i2, "relacion": "repite", "a": i1}], por=C)
    assert [x["id"] for x in res["reglas_cuestionadas"]] == [r]
    assert k.nodo(P, r)["estado"] == "cuestionada"
    assert "reglas_cuestionadas" not in v.veredicto(P, [{"nodo": i2, "estado": "diagnosticado"}], por=C)


def test_entrega_tardia_explicita_pasa_sin_entrega_a_entregado():
    r = k.abrir_ronda(P, "r", autor=C)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=C)
    k.cambiar_estado(P, e["id"], "sin_entrega", por=C)
    k.entregar(P, e["id"], "informe tardio", revision=1, autor="frente:f")  # el frente no la reabre
    assert k.nodo(P, e["id"])["estado"] == "sin_entrega"
    k.entregar(P, e["id"], "informe tardio r2", revision=2, autor=C)
    assert k.nodo(P, e["id"])["estado"] == "entregado"


def test_por_que_se_descarto_una_alternativa():
    h = _n("hallazgo", "la cota no alcanza", {"donde": "dominio:lp", "gravedad": "alta"})
    a = _n("alternativa", "usar la cota LP")
    d = _n("decision", "dejar la mejora LP", {"motivo": "no alcanza"})
    otra = _n("decision", "otra decision", {"motivo": "contexto distinto"})
    k.vincular(P, d, "descarta", a, autor="f", motivo="la cota no controla S")
    k.vincular(P, d, "motivada_por", h, autor="f")
    k.vincular(P, otra, "elige", a, autor="f", motivo="en otro contexto sirve")
    k.cambiar_estado(P, h, "rechazado", por=C)
    code, res = api.dispatch("GET", [P, "alternativas", a, "por_que"], None, {})
    assert code == 200
    assert [(x["id"], x["motivo_descarte"]) for x in res["descartada_por"]] == [(d, "la cota no controla S")]
    assert res["descartada_por"][0]["apoyo_rechazado"] == [h]
    assert [x["id"] for x in res["fundamentos"]] == [h]
    assert [x["id"] for x in res["elegida_por"]] == [otra]
    with pytest.raises(Rechazo):
        v.por_que_descartada(P, h)


def test_pendientes_traen_encargos_abiertos_y_briefing_parte_de_los_encargos():
    r = k.abrir_ronda(P, "r", autor=C)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=C, archivos=["codigo/a.py"])
    h = k.crear_nodo(P, "hallazgo", "a.py se cuelga", {"donde": "codigo/a.py:3", "gravedad": "media"}, autor="f")
    assert [x["id"] for x in v.pendientes(P)["encargos_abiertos"]] == [e["id"]]
    b = v.briefing(P, encargos=[e["id"]], desde_cierre=False)
    assert b["archivos"] == ["codigo/a.py"] and h["id"] in {n["id"] for n in b["abierto"]}
    md = v.briefing_markdown(b)
    assert f"nodo:{h['id']}" in md and "[hallazgo, propuesto]" in md
    code, res = api.dispatch("GET", [P, "briefing"], None, {"encargos": [e["id"]], "markdown": ["1"]})
    assert code == 200 and res["markdown"].startswith("## Memoria del proyecto")


def test_preguntar_ordena_por_mejor_puesto_y_marca_apoyos_rechazados():
    h = _n("hallazgo", "cola lenta", {"donde": "a.py:1", "gravedad": "baja"})
    d = _n("decision", "cola con hilo propio", {"motivo": "lento"})
    a = _n("alternativa", "cola en el lock")
    k.vincular(P, d, "motivada_por", h, autor="f")
    k.vincular(P, d, "descarta", a, autor="f", motivo="bloquea")
    k.cambiar_estado(P, h, "rechazado", por=C)
    res = v.preguntar(P, ["cola"], saltos=0)
    assert all(c["puesto"] is not None for c in res["candidatos"])
    assert [c["puesto"] for c in res["candidatos"]] == sorted(c["puesto"] for c in res["candidatos"])
    dec = next(c for c in res["candidatos"] if c["id"] == d)
    assert dec["apoyo_rechazado"] == [h]


def test_lecciones_suman_incidentes_del_agente_por_proyecto():
    k.registrar_proyecto("otro")
    _n("incidente", "se colgo la TUI", {"herramienta": "tui", "agente": "Codex", "modelo": "gpt-5"})
    k.crear_nodo("otro", "incidente", "permiso", {"herramienta": "Bash", "agente": "claude"}, autor="f")
    res = ap.lecciones("codex")
    assert [(i["texto"], i["proyecto"]) for i in res["incidentes"]] == [("se colgo la TUI", P)]
    assert ap.lecciones("codex", modelo="o3")["incidentes"] == []


def test_un_bloque_pendiente_se_reincorpora_cuando_existe_lo_que_faltaba():
    r = k.abrir_ronda(P, "r", autor=C)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=C)
    tema = k.crear_nodo(P, "tema", "red", autor=C)
    cuerpo = (
        "informe\n```conocimiento\n"
        '{"version": 1, "nodos": [{"id": "h1", "tipo": "hallazgo", "texto": "el espejo reconecta",'
        ' "datos": {"donde": "dominio:red", "gravedad": "baja"}}], "vinculos": [{"de": "h1", "relacion": "sobre",'
        ' "a": "nodo:TEMA"}]}\n```'
    )
    inf = k.entregar(P, e["id"], cuerpo.replace("TEMA", "falta"), revision=1, autor=C)
    assert inf["datos"]["conocimiento"]["estado"] == "pendiente_de_vincular"
    with pytest.raises(Rechazo):
        k.reincorporar(P, inf["id"], por="frente:x")
    assert k.reincorporar(P, inf["id"], por=C)["conocimiento"]["estado"] == "pendiente_de_vincular"
    # el frente lo corrige como revision siguiente; la r1 sigue pendiente y no se toca sola
    inf2 = k.entregar(P, e["id"], cuerpo.replace("TEMA", tema["id"]), revision=2, autor=C)
    assert inf2["datos"]["conocimiento"]["estado"] == "incorporado"
    # un bloque pendiente porque el nodo citado no existia todavia: se crea y se reincorpora
    nuevo = cuerpo.replace("nodo:TEMA", "nodo:" + "f" * 32)
    inf3 = k.entregar(P, e["id"], nuevo, revision=3, autor=C)
    with k._abrir(P) as con:
        con.execute(
            "INSERT INTO nodo (id, proyecto, tipo, texto, datos, autor, origen, fecha) VALUES (?,?,?,?,?,?,?,?)",
            ("f" * 32, P, "tema", "llego despues", "{}", "c", "{}", k.ahora()),
        )
    res = k.reincorporar(P, inf3["id"], por=C)
    assert res["conocimiento"]["estado"] == "incorporado"
    assert k.nodo(P, inf3["id"])["datos"]["conocimiento"]["estado"] == "incorporado"
    with pytest.raises(Rechazo) as x:
        k.reincorporar(P, inf3["id"], por=C)
    assert x.value.codigo == 409


def test_evidencia_recibida_y_respaldo(tmp_path):
    code, ev = api.dispatch(
        "POST", [P, "evidencia"], {"nombre": "../salida run.log", "clase": "prueba", "contenido_texto": "ok 12"}, {}
    )
    assert code == 200 and ev["datos"]["referencia"].startswith("evidencia/") and ".." not in ev["datos"]["referencia"]
    again = k.recibir_evidencia(P, "otro", b"ok 12", clase="prueba", autor="c")
    assert again["id"] == ev["id"] and not again["creado"]
    with open(os.path.join(k._carpeta(P), *ev["datos"]["referencia"].split("/")), "rb") as f:
        assert f.read() == b"ok 12"
    assert api.dispatch("POST", [P, "evidencia"], {"nombre": "x", "clase": "p", "contenido_base64": "%%"}, {})[0] == 400
    r = k.respaldar(P, str(tmp_path / "resp"))
    con = sqlite3.connect(str(tmp_path / "resp" / "conocimiento.sqlite"))
    assert con.execute("SELECT COUNT(*) FROM nodo WHERE id = ?", (ev["id"],)).fetchone()[0] == 1
    con.close()
    assert r["archivos"] == 1 and os.path.isfile(tmp_path / "resp" / "proyecto.json")


def test_la_sesion_que_cambia_de_modelo_deja_su_cambio():
    with k._abrir(P) as con:
        k._sesion(con, P, "s1", agente="codex", modelo="gpt-5")
        n = k._sesion(con, P, "s1", agente="codex", modelo="o3")
    cambios = [c for c in k.nodo(P, n["id"])["cambios"] if c["accion"] == "datos"]
    assert cambios and cambios[0]["anterior"]["datos"]["modelo"] == "gpt-5"
