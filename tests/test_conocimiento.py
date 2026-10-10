"""Conocimiento por proyecto, etapa 1 (docs/propuesta-memoria-2026-10-08/v5.md): identidad,
esquema, nodos con transiciones, vinculos tipados, historial, rondas, encargos, entrega idempotente,
BM25 y expansion por grafo, y los adaptadores. Todo sobre un LIENZO_HOME temporal (conftest)."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import conocimiento_api as api
from conocimiento import Rechazo


def test_api_integrada_recuperacion_aprendizaje_y_cierre_atomico(proy, monkeypatch):
    code, tema = api.dispatch("POST", ["teorema", "temas"], {"texto": "memoria", "por": "coordinadora:c"}, {})
    assert code == 200
    for ruta in ("briefing", "preguntar", "pendientes", "duplicados", "avisos"):
        assert api.dispatch("GET", ["teorema", ruta], None, {"q": ["memoria"]})[0] == 200
    assert api.dispatch("GET", ["teorema", "vista"], None, {"tema": [tema["id"]]})[0] == 200
    assert api.dispatch("GET", ["lecciones"], None, {"agente": ["codex"]})[0] == 200
    assert api.dispatch("POST", ["teorema", "veredictos"], {"items": [], "por": "frente:c"}, {})[0] == 403
    ronda = k.abrir_ronda("teorema", "cierre", autor="coordinadora:c")
    original = k.actualizar_datos

    def fallo(pid, nid, datos, **kwargs):
        if "cierre_seq" in datos:
            raise OSError("fallo al guardar ancla")
        return original(pid, nid, datos, **kwargs)

    monkeypatch.setattr(k, "actualizar_datos", fallo)
    cambios = k.cambios("teorema")
    with pytest.raises(OSError, match="ancla"):
        k.cerrar_ronda("teorema", ronda["id"], por="coordinadora:c")
    assert k.nodo("teorema", ronda["id"])["estado"] == "abierta"
    assert k.cambios("teorema") == cambios


@pytest.mark.parametrize("cuerpo", [[], ["x"], "x", 0])
def test_api_integrada_rechaza_cuerpo_no_objeto(cuerpo):
    assert api.dispatch("POST", ["proyectos"], cuerpo, {})[0] == 400


def test_tema_canonico_concurrente_no_duplica_ni_pierde_aliases(proy):
    import veredictos

    def registrar(alias):
        return veredictos.tema("teorema", "Memoria", por="coordinadora:c", aliases=[alias])

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(registrar, ["captura", "recuperacion"]))
    assert resultados[0]["id"] == resultados[1]["id"]
    temas = veredictos.temas("teorema")
    assert len(temas) == 1
    assert set(temas[0]["aliases"]) == {"captura", "recuperacion"}


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    # la API busca la tarjeta real; aca el lienzo conoce s1 (claude, en pcA) y ninguna otra
    tarjetas = {"s1": {"session_id": "s1", "agent": "claude", "model": "opus", "pc": "pcA", "cwd": "D:/Apps/lienzo"}}
    monkeypatch.setattr(api.ses, "sessions", tarjetas)
    # una tarjeta espejada de otra PC: el lienzo la conoce pero no es de esta PC
    monkeypatch.setattr(
        api.ses, "find_session", lambda sid: tarjetas.get(sid) or ({"session_id": sid} if sid == "s-otra-pc" else None)
    )


@pytest.fixture
def proy():
    return k.registrar_proyecto(
        "teorema", "Teorema", ["github.com/arielelevy/teorema"], [{"pc": "pcA", "cwd": "D:/Apps/Teorema"}]
    )


# --- identidad ----------------------------------------------------------------------------


def test_registrar_crea_carpeta_base_y_aliases(proy):
    assert os.path.isfile(os.path.join(k.raiz(), "teorema", "conocimiento.sqlite"))
    assert k.resolver_proyecto(repo_key="github.com/arielelevy/teorema") == "teorema"
    assert k.resolver_proyecto(cwd="d:\\apps\\teorema\\", pc="pcA") == "teorema"
    assert k.resolver_proyecto(cwd="D:/Apps/Teorema", pc="pcB") is None  # otra PC, misma carpeta: no se adivina
    assert k.resolver_proyecto(repo_key="github.com/otro/repo") is None


def test_registrar_rechaza_id_invalido_y_alias_de_otro(proy):
    with pytest.raises(Rechazo):
        k.registrar_proyecto("Teorema Mayus")
    with pytest.raises(Rechazo) as e:
        k.registrar_proyecto("otro", remotes=["github.com/arielelevy/teorema"])
    assert e.value.codigo == 409


def test_registrar_dos_veces_suma_aliases_sin_duplicar(proy):
    p = k.registrar_proyecto("teorema", remotes=["gitlab.com/x/y"], carpetas=[{"pc": "pcA", "cwd": "D:/Apps/Teorema"}])
    assert p["remotes"] == ["github.com/arielelevy/teorema", "gitlab.com/x/y"]
    assert len(p["carpetas"]) == 1


# --- nodos, estados, vinculos ----------------------------------------------------------------


def test_nodo_nace_con_estado_inicial_y_queda_en_el_historial(proy):
    h = k.crear_nodo(
        "teorema", "hallazgo", "pierde el invariante con k impar", {"gravedad": "alta"}, autor="codex:gpt-5"
    )
    assert h["estado"] == "propuesto" and h["creado"]
    a = k.crear_nodo("teorema", "alternativa", "halving entero", autor="codex:gpt-5")
    assert a["estado"] is None
    c = k.cambios("teorema")
    assert [x["accion"] for x in c] == ["nodo", "nodo"]


def test_transiciones_respetan_tabla_y_rol(proy):
    h = k.crear_nodo("teorema", "hallazgo", "x", autor="f")
    with pytest.raises(Rechazo) as e:
        k.cambiar_estado("teorema", h["id"], "corregido", por="coordinadora:1")  # propuesto -> corregido no existe
    assert e.value.codigo == 409
    with pytest.raises(Rechazo) as e:
        k.cambiar_estado("teorema", h["id"], "confirmado", por="frente:1")  # el frente no confirma
    assert e.value.codigo == 403
    h2 = k.cambiar_estado("teorema", h["id"], "confirmado", por="coordinadora:1", motivo="test lo prueba")
    assert h2["estado"] == "confirmado" and h2["estado_por"] == "coordinadora:1"
    assert (
        k.cambiar_estado("teorema", h["id"], "confirmado", por="coordinadora:1")["estado"] == "confirmado"
    )  # idempotente
    ultimo = k.cambios("teorema")[-1]
    assert ultimo["accion"] == "estado" and ultimo["anterior"]["estado"] == "propuesto"


def test_vinculos_tipados_motivo_y_ciclos(proy):
    d = k.crear_nodo("teorema", "decision", "halving racional", {"motivo": "conserva el invariante"}, autor="f")
    a = k.crear_nodo("teorema", "alternativa", "halving entero", autor="f")
    h = k.crear_nodo("teorema", "hallazgo", "pierde el invariante", autor="f")
    with pytest.raises(Rechazo):
        k.vincular("teorema", d["id"], "descarta", a["id"], autor="f")  # sin motivo
    with pytest.raises(Rechazo):
        k.vincular("teorema", a["id"], "motivada_por", h["id"], autor="f")  # alternativa no se motiva
    v = k.vincular("teorema", d["id"], "descarta", a["id"], autor="f", motivo="pierde el invariante")
    assert v["creado"] and v["motivo"]
    assert not k.vincular("teorema", d["id"], "descarta", a["id"], autor="f", motivo="otra vez")["creado"]
    h2 = k.crear_nodo("teorema", "hallazgo", "lo mismo", autor="g")
    k.vincular("teorema", h["id"], "mismo_que", h2["id"], autor="c")
    with pytest.raises(Rechazo) as e:
        k.vincular("teorema", h2["id"], "mismo_que", h["id"], autor="c")
    assert e.value.codigo == 409
    k.retirar_vinculo("teorema", h["id"], "mismo_que", h2["id"], por="coordinadora:1", motivo="no eran lo mismo")
    assert k.nodo("teorema", h["id"])["vinculos"]["salen"] == []
    assert k.cambios("teorema")[-1]["accion"] == "vinculo_retirado"


# --- rondas, encargos, entregas -------------------------------------------------------------


def test_ronda_encargo_envio_entrega_y_cierre(proy):
    r = k.abrir_ronda("teorema", "ronda 3: halving", autor="coordinadora:1", coordinadora="sid-coord")
    assert r["estado"] == "abierta"
    e = k.crear_encargo(
        "teorema",
        r["id"],
        "A",
        "# Encargo A\n\nhalving entero en sustituciones",
        autor="coordinadora:1",
        archivos=["codigo/sustituciones.py"],
    )
    assert e["estado"] == "pendiente" and e["datos"]["letra"] == "A"
    assert k.leer_cuerpo("teorema", e["datos"]["ruta"]).startswith("# Encargo A")
    with pytest.raises(Rechazo) as x:
        k.crear_encargo("teorema", r["id"], "A", "otro", autor="c")
    assert x.value.codigo == 409
    e2 = k.encargo_enviado(
        "teorema", e["id"], {"session_id": "01a11bca-sid", "agent": "codex", "model": "gpt-5", "pc": "pcA"}
    )
    assert e2["estado"] == "enviado"
    ses = k.nodos("teorema", tipo="sesion")["nodos"]
    assert len(ses) == 1 and ses[0]["datos"]["agente"] == "codex"
    assert k.nodo("teorema", e["id"])["vinculos"]["salen"][0]["relacion"] == "ejecutado_por"
    inf = k.entregar("teorema", e["id"], "## Resultado\n\nlisto", revision=1, autor="frente:01a11bca")
    assert inf["creado"] and inf["estado"] == "recibido" and len(inf["datos"]["hash"]) == 64
    assert k.nodo("teorema", e["id"])["estado"] == "entregado"
    assert k.leer_cuerpo("teorema", inf["datos"]["ruta"]) == "## Resultado\n\nlisto"
    # idempotente por (encargo, revision, hash); la misma revision con otro contenido se rechaza
    assert not k.entregar("teorema", e["id"], "## Resultado\n\nlisto", revision=1, autor="frente:01a11bca")["creado"]
    with pytest.raises(Rechazo) as x:
        k.entregar("teorema", e["id"], "otro cuerpo", revision=1, autor="frente:01a11bca")
    assert x.value.codigo == 409
    inf2 = k.entregar("teorema", e["id"], "## Resultado r2", revision=2, autor="frente:01a11bca")
    assert inf2["creado"]
    cerrada = k.cerrar_ronda("teorema", r["id"], por="coordinadora:1")
    assert cerrada["estado"] == "cerrada" and cerrada["datos"]["cierre_seq"] > 0
    with pytest.raises(Rechazo):
        k.crear_encargo("teorema", r["id"], "B", "tarde", autor="c")
    res = k.resumen("teorema")
    assert res["nodos"]["encargo"] == {"entregado": 1} and res["nodos"]["informe"] == {"recibido": 2}


def test_entregar_sin_enviar_no_pasa_a_entregado_y_rechaza_revision_invalida(proy):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "B", "x", autor="c")
    with pytest.raises(Rechazo):
        k.entregar("teorema", e["id"], "cuerpo", revision=0, autor="f")
    k.entregar("teorema", e["id"], "cuerpo", revision=1, autor="f")
    assert k.nodo("teorema", e["id"])["estado"] == "pendiente"  # entregado solo desde enviado (v5 §3.4)


# --- adaptadores ------------------------------------------------------------------------------


def test_sesion_cerrada_e_incidente_solo_para_sesiones_con_encargo(proy):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "A", "x", autor="c")
    k.encargo_enviado("teorema", e["id"], {"session_id": "sid-1", "agent": "coda"})
    assert k.incidente_operativo("sid-ajena", "no cuenta", herramienta="x") is None
    i = k.incidente_operativo(
        "sid-1", "permiso denegado: Bash rm", herramienta="permiso", datos={"motivo": "clasificador"}
    )
    assert i["estado"] == "observado" and i["ronda"] == r["id"] and i["datos"]["agente"] == "coda"
    k._sesion_proyecto.clear()  # el mapa en memoria se perdio (reinicio): se busca en las bases
    k.sesion_cerrada("sid-1")
    assert k.nodos("teorema", tipo="sesion")["nodos"][0]["estado"] == "cerrada"
    k.sesion_cerrada("sid-que-no-existe")  # no rompe


def test_sesion_que_revive_vuelve_a_viva_y_la_cache_negativa_se_invalida(proy, monkeypatch):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "A", "x", autor="c")
    # una tarjeta comun: se busca una vez en las bases y despues no se vuelve a abrir nada
    k.sesion_cerrada("sid-comun")
    assert "sid-comun" in k._sesion_sin_proyecto
    aperturas = []
    monkeypatch.setattr(k, "_abrir", lambda pid: aperturas.append(pid) or k._Conexion(k._db_path(pid)))
    k.sesion_cerrada("sid-comun")
    assert aperturas == []
    # esa misma tarjeta toma un encargo: sale de la cache negativa y el server la observa
    k.encargo_enviado("teorema", e["id"], {"session_id": "sid-comun", "agent": "claude"})
    k.sesion_cerrada("sid-comun")
    assert k.nodos("teorema", tipo="sesion")["nodos"][0]["estado"] == "cerrada"
    k.sesion_viva("sid-comun")  # claude --resume: la tarjeta vuelve con el mismo id
    n = k.nodos("teorema", tipo="sesion")["nodos"][0]
    assert n["estado"] == "viva" and n["estado_por"] == "server"


def test_cuerpo_que_no_se_puede_escribir_no_deja_nodo(proy, monkeypatch):
    """El cuerpo se escribe dentro de la transaccion: si el disco falla, no queda un encargo huerfano
    que convierta cada reintento en 409 (code review 2026-10-08). La ronda creada por POST /nodos no
    tiene carpeta: se crea al escribir."""
    r = k.crear_nodo("teorema", "ronda", "ronda sin carpeta", autor="c")
    escribir = k.escribir_exacto
    monkeypatch.setattr(k, "escribir_exacto", lambda *a, **kw: (_ for _ in ()).throw(OSError("disco lleno")))
    with pytest.raises(OSError):
        k.crear_encargo("teorema", r["id"], "A", "cuerpo", autor="c")
    assert k.nodos("teorema", tipo="encargo")["total"] == 0
    monkeypatch.setattr(k, "escribir_exacto", escribir)
    e = k.crear_encargo("teorema", r["id"], "A", "cuerpo", autor="c")  # el reintento anda
    assert k.leer_cuerpo("teorema", e["datos"]["ruta"]) == "cuerpo"
    k.encargo_enviado("teorema", e["id"], {"session_id": "s9"})
    monkeypatch.setattr(k, "escribir_exacto", lambda *a, **kw: (_ for _ in ()).throw(OSError("disco lleno")))
    with pytest.raises(OSError):
        k.entregar("teorema", e["id"], "informe", revision=1, autor="f")
    assert k.nodos("teorema", tipo="informe")["total"] == 0
    assert k.nodo("teorema", e["id"])["estado"] == "enviado"


def test_la_clave_no_se_quema_si_el_incidente_no_se_escribio(proy, monkeypatch):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "A", "x", autor="c")
    k.encargo_enviado("teorema", e["id"], {"session_id": "sid-1"})
    original = k.crear_nodo
    monkeypatch.setattr(k, "crear_nodo", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("database is locked")))
    assert k.incidente_operativo("sid-1", "error de API", herramienta="api", clave="incidente:api:sid-1:t1") is None
    assert not k.visto("incidente:api:sid-1:t1")
    monkeypatch.setattr(k, "crear_nodo", original)
    assert k.incidente_operativo("sid-1", "error de API", herramienta="api", clave="incidente:api:sid-1:t1")["creado"]
    assert k.visto("incidente:api:sid-1:t1")
    # la misma denegacion por dos fuentes (log de coda y transcripcion) tiene una sola clave
    assert k.clave_permiso("sid-1", "Bash", "clasificador", "rm -rf x") == k.clave_permiso(
        "sid-1", "Bash", "clasificador", "rm -rf x"
    )


def test_incidente_con_clave_es_idempotente_y_no_reabre_las_bases(proy, monkeypatch):
    """El error de API llega en cada refresco de la tarjeta (apply_turn): una vez por turno."""
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "A", "x", autor="c")
    k.encargo_enviado("teorema", e["id"], {"session_id": "sid-1", "agent": "claude"})
    clave = "incidente:api:sid-1:turno-7"
    i = k.incidente_operativo("sid-1", "error de API: stopped", herramienta="api", clave=clave)
    assert i["creado"] and i["datos"]["herramienta"] == "api"
    aperturas = []
    monkeypatch.setattr(k, "_abrir", lambda pid: aperturas.append(pid) or k._Conexion(k._db_path(pid)))
    assert k.incidente_operativo("sid-1", "error de API: stopped", herramienta="api", clave=clave) is None
    assert aperturas == []  # la clave ya vista no toca SQLite
    k._incidentes_vistos.clear()  # reinicio del server: la base sigue siendo la que decide
    assert not k.incidente_operativo("sid-1", "otro texto", herramienta="api", clave=clave)["creado"]
    assert k.resumen("teorema")["nodos"]["incidente"] == {"observado": 1}


def test_apply_turn_manda_el_error_de_api_como_incidente_una_vez_por_turno(monkeypatch):
    import sessions as ses

    llamadas = []
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *a: llamadas.append((fn, a)) if fn is ses._incidente else None)
    monkeypatch.setattr(ses.transcripts, "retryable_error", lambda e: True)
    monkeypatch.setattr(ses, "limit_until_of", lambda t: None)
    monkeypatch.setattr(ses, "on_api_error", lambda s, sig: None)
    s = {"session_id": "s" * 36, "state": "termino", "agent": "claude", "needs": None, "hooked": True}
    t = {"id": "t9", "error": "API Error: The response stopped arriving", "ended": True, "final": False}
    ses.apply_turn(s, t, False)
    assert len(llamadas) == 1
    fn, a = llamadas[0]
    assert a[1].startswith("error de API") and a[2] == "api" and a[4] == f"incidente:api:{'s' * 36}:t9"


# --- busqueda y grafo -------------------------------------------------------------------------


def test_bm25_sin_tildes_y_expansion_por_grafo(proy):
    d = k.crear_nodo(
        "teorema", "decision", "sustituciones con halving racional", {"motivo": "conserva el invariante"}, autor="f"
    )
    a = k.crear_nodo("teorema", "alternativa", "halving entero en sustituciones", autor="f")
    h = k.crear_nodo(
        "teorema",
        "hallazgo",
        "el halving entero pierde el invariante con k impar",
        {"donde": "codigo/sustituciones.py:88"},
        autor="f",
    )
    ev = k.crear_nodo(
        "teorema", "evidencia", "tests/test_sustituciones.py::test_k_impar", {"clase": "prueba"}, autor="f"
    )
    t = k.crear_nodo("teorema", "tema", "sustituciones", autor="f")
    k.vincular("teorema", d["id"], "descarta", a["id"], autor="f", motivo="pierde el invariante")
    k.vincular("teorema", d["id"], "motivada_por", h["id"], autor="f")
    k.vincular("teorema", h["id"], "apoya", ev["id"], autor="f")
    k.vincular("teorema", d["id"], "sobre", t["id"], autor="f")
    lejos = k.crear_nodo("teorema", "pregunta", "¿vale el 2x para n grande?", {"para_quien": "ariel"}, autor="f")
    k.vincular("teorema", lejos["id"], "sobre", t["id"], autor="f")

    hits = k.buscar("teorema", "invariante")
    assert {x["tipo"] for x in hits} == {"decision", "hallazgo"}
    assert k.buscar("teorema", "invariánte")  # remove_diacritics: con tilde encuentra sin tilde (no hay stemming)
    assert k.buscar("teorema", "sustitu*", tipo="alternativa")[0]["id"] == a["id"]
    with pytest.raises(Rechazo):
        k.buscar("teorema", "invariante AND (")  # sintaxis FTS invalida: 400, no 500

    # desde la alternativa (salto 0) se llega a la decision (1), al hallazgo y al tema (2); la evidencia
    # queda a 3 saltos y el tema no hace de puente hacia la pregunta
    ids = {x["id"]: x["salto"] for x in k.expandir("teorema", [a["id"]], saltos=2)}
    assert ids[a["id"]] == 0 and ids[d["id"]] == 1 and ids[h["id"]] == 2 and ids[t["id"]] == 2
    assert ev["id"] not in ids and lejos["id"] not in ids
    vinculos_d = next(x for x in k.expandir("teorema", [a["id"]], saltos=1) if x["id"] == d["id"])["vinculos"]
    assert {v["relacion"] for v in vinculos_d} == {"descarta"}


def test_cadena_por_que_se_descarto(proy):
    """La consulta 1 de v5 §8.5, tal como la usara `preguntar` en la etapa 3."""
    d = k.crear_nodo("teorema", "decision", "racional", {"motivo": "m"}, autor="f")
    a = k.crear_nodo("teorema", "alternativa", "entero", autor="f")
    h = k.crear_nodo("teorema", "hallazgo", "pierde", autor="f")
    k.vincular("teorema", d["id"], "descarta", a["id"], autor="f", motivo="pierde el invariante")
    k.vincular("teorema", d["id"], "motivada_por", h["id"], autor="f")
    with k._abrir("teorema") as con:
        filas = con.execute(
            """WITH RECURSIVE cadena(id) AS (
                 SELECT v.de FROM vinculo v JOIN nodo d ON d.id = v.de
                 WHERE v.a = :alt AND v.relacion = 'descarta' AND v.activo = 1 AND d.proyecto = :p
                 UNION
                 SELECT v.a FROM cadena c JOIN vinculo v ON v.de = c.id AND v.activo = 1
                 JOIN nodo n ON n.id = v.a AND n.proyecto = :p
                 WHERE v.relacion IN ('motivada_por','apoya','confirmado_por'))
               SELECT n.tipo, n.texto FROM cadena c JOIN nodo n ON n.id = c.id ORDER BY n.tipo""",
            {"alt": a["id"], "p": "teorema"},
        ).fetchall()
    assert [tuple(f) for f in filas] == [("decision", "racional"), ("hallazgo", "pierde")]


# --- API -------------------------------------------------------------------------------------


def test_api_recorrido_completo_y_errores():
    code, p = api.dispatch(
        "POST", ["proyectos"], {"id": "lienzo", "nombre": "Lienzo", "remotes": ["github.com/arielelevy/lienzo"]}, {}
    )
    assert code == 200 and p["id"] == "lienzo"
    assert api.dispatch("GET", ["resolver"], None, {"repo_key": ["github.com/arielelevy/lienzo"]})[1] == {
        "proyecto": "lienzo"
    }
    assert api.dispatch("GET", ["nadie"], None, {})[0] == 404
    code, r = api.dispatch("POST", ["lienzo", "rondas"], {"objetivo": "etapa 1"}, {})
    assert code == 200
    code, e = api.dispatch(
        "POST",
        ["lienzo", "encargos"],
        {"ronda": r["id"], "letra": "A", "texto": "hacer X", "archivos": ["lienzo/conocimiento.py"]},
        {},
    )
    assert code == 200 and e["estado"] == "pendiente"
    # un id que el lienzo no conoce es 404; con el real, agente y modelo salen de la tarjeta, no del cuerpo
    assert api.dispatch("POST", ["lienzo", "encargos", e["id"], "enviado"], {"session_id": "nadie"}, {})[0] == 404
    assert api.dispatch("POST", ["lienzo", "encargos", e["id"], "enviado"], {"session_id": "s-otra-pc"}, {})[0] == 409
    assert (
        api.dispatch("POST", ["lienzo", "encargos", e["id"], "enviado"], {"session_id": "s1", "agent": "codex"}, {})[1][
            "estado"
        ]
        == "enviado"
    )
    assert (
        api.dispatch("GET", ["lienzo", "nodos"], None, {"tipo": ["sesion"]})[1]["nodos"][0]["datos"]["agente"]
        == "claude"
    )
    code, inf = api.dispatch(
        "POST", ["lienzo", "entregas"], {"encargo": e["id"], "revision": 1, "cuerpo": "hecho", "autor": "frente:s1"}, {}
    )
    assert code == 200 and inf["creado"]
    assert (
        api.dispatch("POST", ["lienzo", "entregas"], {"encargo": e["id"], "revision": 1, "cuerpo": "distinto"}, {})[0]
        == 409
    )
    assert (
        api.dispatch("POST", ["lienzo", "entregas"], {"encargo": e["id"], "revision": "1", "cuerpo": "x"}, {})[0] == 400
    )
    code, n = api.dispatch(
        "POST",
        ["lienzo", "nodos"],
        {
            "tipo": "hallazgo",
            "texto": "falta FTS en la busqueda",
            "autor": "frente:s1",
            "datos": {"gravedad": "media", "donde": "lienzo/conocimiento.py"},
        },
        {},
    )
    assert code == 200
    assert (
        api.dispatch("POST", ["lienzo", "nodos", n["id"], "estado"], {"estado": "confirmado", "por": "frente:s1"}, {})[
            0
        ]
        == 403
    )
    assert (
        api.dispatch(
            "POST", ["lienzo", "nodos", n["id"], "estado"], {"estado": "confirmado", "por": "coordinadora:c"}, {}
        )[1]["estado"]
        == "confirmado"
    )
    code, b = api.dispatch("GET", ["lienzo", "buscar"], None, {"q": ["FTS"], "saltos": ["1"]})
    assert code == 200 and b["semillas"][0]["id"] == n["id"]
    assert api.dispatch("GET", ["lienzo", "buscar"], None, {"q": ["("]})[0] == 400
    assert api.dispatch("GET", ["lienzo", "nodos"], None, {"tipo": ["informe"]})[1]["total"] == 1
    assert api.dispatch("GET", ["lienzo", "cuerpo"], None, {"ruta": [inf["datos"]["ruta"]]})[1]["texto"] == "hecho"
    assert api.dispatch("GET", ["lienzo", "cuerpo"], None, {"ruta": ["../../indice.json"]})[0] == 404
    assert api.dispatch("GET", ["lienzo", "cambios"], None, {"desde": ["0"]})[0] == 200
    assert (
        api.dispatch(
            "POST", ["lienzo", "rondas", r["id"], "estado"], {"estado": "cerrada", "por": "coordinadora:c"}, {}
        )[1]["datos"]["cierre_seq"]
        > 0
    )
    assert api.dispatch("GET", ["lienzo", "lo-que-sea"], None, {})[0] == 404


def test_api_cuerpo_invalido_no_es_500():
    api.dispatch("POST", ["proyectos"], {"id": "p"}, {})
    assert api.dispatch("POST", ["p", "nodos"], {"tipo": "cosa", "texto": "x", "autor": "a"}, {})[0] == 400
    assert api.dispatch("POST", ["p", "nodos"], {"tipo": ["cosa"], "texto": "x", "autor": "a"}, {})[0] == 400
    assert (
        api.dispatch("POST", ["p", "nodos"], {"tipo": "encargo", "texto": "x", "autor": "a"}, {})[0] == 400
    )  # lo crea el server
    code, res = api.dispatch("POST", ["p", "nodos"], {"tipo": "hallazgo", "texto": "x", "autor": "a", "datos": {}}, {})
    assert code == 400 and "donde" in res["error"]
    assert api.dispatch("POST", ["p", "nodos"], {"tipo": "tema", "texto": "", "autor": "a"}, {})[0] == 400
    assert (
        api.dispatch("POST", ["p", "vinculos"], {"de": "x", "relacion": "sobre", "a": "y", "autor": "a"}, {})[0] == 404
    )
    assert (
        api.dispatch("POST", ["p", "vinculos"], {"de": "x", "relacion": "rara", "a": "y", "autor": "a"}, {})[0] == 400
    )
    assert api.dispatch("GET", ["p", "nodos"], None, {"limite": ["muchos"]})[0] == 400


def test_datos_y_origen_se_guardan_como_json(proy):
    n = k.crear_nodo(
        "teorema",
        "medicion",
        "error relativo",
        {"valor": 1e-9, "unidad": "1", "condicion": {"commit": "7c2e"}},
        autor="f",
        origen={"session_id": "s", "turno": 3},
    )
    with k._abrir("teorema") as con:
        raw = con.execute("SELECT datos, origen FROM nodo WHERE id = ?", (n["id"],)).fetchone()
    assert json.loads(raw["datos"])["condicion"]["commit"] == "7c2e" and json.loads(raw["origen"])["turno"] == 3


# --- el bloque `conocimiento` del informe (etapa 2) -----------------------------------------------


def _bloque(obj):
    return "## Resultado\n\nlisto\n\n```conocimiento\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


BLOQUE_OK = {
    "version": 1,
    "nodos": [
        {
            "id": "h1",
            "tipo": "hallazgo",
            "texto": "la cota del LP no acota el halving entero",
            "datos": {"donde": "dominio:halving", "gravedad": "alta"},
        },
        {"id": "a1", "tipo": "alternativa", "texto": "descartar el halving entero con la cota del LP", "datos": {}},
        {
            "id": "d1",
            "tipo": "decision",
            "texto": "mantener abierta la ruta de perfiles",
            "datos": {"motivo": "la barrera del LP tiene otro alcance"},
        },
        {
            "id": "p1",
            "tipo": "pregunta",
            "texto": "¿como obtener exceso de tamano bajo F chico?",
            "datos": {"para_quien": "coordinadora"},
        },
        {"id": "t1", "tipo": "tema", "texto": "halving", "datos": {}},
        {
            "id": "m1",
            "tipo": "medicion",
            "texto": "error relativo",
            "datos": {"metrica": "err", "valor": 1e-9, "unidad": "1", "condicion": "commit 7c2e"},
        },
    ],
    "vinculos": [
        {"de": "d1", "relacion": "motivada_por", "a": "h1"},
        {"de": "d1", "relacion": "descarta", "a": "a1", "motivo": "confunde V con S"},
        {"de": "h1", "relacion": "sobre", "a": "t1"},
        {"de": "p1", "relacion": "sobre", "a": "t1"},
    ],
}


def _encargo_enviado(sid="sid-f"):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "A", "x", autor="c")
    k.encargo_enviado("teorema", e["id"], {"session_id": sid, "agent": "codex"})
    return r, e


def test_bloque_valido_se_incorpora_entero_y_el_reenvio_devuelve_los_mismos_ids(proy):
    r, e = _encargo_enviado()
    inf = k.entregar("teorema", e["id"], _bloque(BLOQUE_OK), revision=1, autor="frente:sid-f")
    c = inf["datos"]["conocimiento"]
    assert c["estado"] == "incorporado" and c["nodos"] == 6 and c["vinculos"] == 4
    assert set(c["ids"]) == {"h1", "a1", "d1", "p1", "t1", "m1"}
    h = k.nodo("teorema", c["ids"]["h1"])
    assert h["estado"] == "propuesto" and h["ronda"] == r["id"] and h["origen"]["local"] == "h1"
    assert {(v["relacion"], v["a"]) for v in h["vinculos"]["salen"]} >= {
        ("declarado_en", inf["id"]),
        ("sobre", c["ids"]["t1"]),
    }
    assert any(v["relacion"] == "encontrado_por" for v in h["vinculos"]["salen"])  # la sesion del encargo
    d = k.nodo("teorema", c["ids"]["d1"])
    assert {v["relacion"] for v in d["vinculos"]["salen"]} == {"declarado_en", "motivada_por", "descarta"}
    assert next(v for v in d["vinculos"]["salen"] if v["relacion"] == "descarta")["motivo"] == "confunde V con S"
    # el mismo informe otra vez: nada nuevo, los mismos ids
    otra = k.entregar("teorema", e["id"], _bloque(BLOQUE_OK), revision=1, autor="frente:sid-f")
    assert not otra["creado"] and otra["datos"]["conocimiento"]["ids"] == c["ids"]
    assert k.resumen("teorema")["nodos"]["hallazgo"] == {"propuesto": 1}
    assert k.cambios("teorema")[-1]["accion"] in ("conocimiento", "vinculo", "estado")
    assert any(x["accion"] == "conocimiento" and x["motivo"] == "incorporado" for x in k.cambios("teorema"))


def test_bloque_con_errores_no_incorpora_nada_y_los_dice_por_posicion(proy):
    r, e = _encargo_enviado()
    malo = {
        "version": 1,
        "nodos": [
            {"id": "h1", "tipo": "hallazgo", "texto": "sin donde", "datos": {"gravedad": "enorme"}},
            {"id": "h1", "tipo": "regla", "texto": "repetido y sin derivada_de", "datos": {"ambito": "agente"}},
            {"id": "d1", "tipo": "decision", "texto": "sin elige ni descarta", "datos": {"motivo": "m"}},
            {"id": "s1", "tipo": "sesion", "texto": "no declarable", "datos": {}},
            {
                "id": "m1",
                "tipo": "medicion",
                "texto": "x",
                "datos": {"metrica": "e", "valor": "1", "unidad": "1", "condicion": "c"},
            },
        ],
        "vinculos": [
            {"de": "d1", "relacion": "descarta", "a": "h1"},
            {"de": "d1", "relacion": "mismo_que", "a": "h1"},
            {"de": "h1", "relacion": "sobre", "a": "nodo:no-existe"},
            {"de": "zz", "relacion": "apoya", "a": "h1"},
        ],
    }
    inf = k.entregar("teorema", e["id"], _bloque(malo), revision=1, autor="frente:sid-f")
    c = inf["datos"]["conocimiento"]
    assert c["estado"] == "pendiente_de_vincular"
    donde = {(x["donde"], x["error"]) for x in c["errores"]}
    assert ("nodo h1", "falta datos.donde") in donde
    assert ("nodo h1", "datos.gravedad debe ser una de baja, media, alta, critica") in donde
    assert ("nodo h1", "id local repetido") in donde
    assert ("nodo d1", "una decision exige al menos un vinculo elige o descarta") not in donde  # tiene descarta
    assert ("nodo s1", "tipo no declarable: sesion") in donde
    assert ("nodo m1", "datos.valor debe ser un numero finito") in donde
    assert ("vinculos[0]", "descarta no admite decision -> hallazgo") in donde
    assert ("vinculos[0]", "descarta exige motivo") in donde
    assert ("vinculos[1]", "relacion no declarable por un frente: mismo_que") in donde
    assert ("vinculos[2]", "nodo:no-existe no existe en el proyecto") in donde
    assert ("vinculos[3]", "id local desconocido: zz") in donde
    # el informe existe y el encargo esta entregado, pero el grafo no tiene nada del bloque
    assert inf["estado"] == "recibido" and k.nodo("teorema", e["id"])["estado"] == "entregado"
    assert k.resumen("teorema")["nodos"].keys() == {"ronda", "encargo", "sesion", "informe"}
    # JSON roto, y un informe sin bloque
    inf2 = k.entregar("teorema", e["id"], "x\n```conocimiento\n{no es json\n```", revision=2, autor="f")
    assert inf2["datos"]["conocimiento"]["errores"][0]["donde"] == "bloque"
    inf3 = k.entregar("teorema", e["id"], "sin bloque", revision=3, autor="f")
    assert "conocimiento" not in inf3["datos"]


def test_bloque_referencia_nodos_existentes_y_regla_derivada(proy):
    r, e = _encargo_enviado()
    t = k.crear_nodo("teorema", "tema", "sustituciones", autor="c")
    inc = k.incidente_operativo("sid-f", "permiso denegado: Bash rm", herramienta="permiso")
    b = {
        "version": 1,
        "nodos": [
            {
                "id": "r1",
                "tipo": "regla",
                "texto": "no borrar con rm -rf en este repo",
                "datos": {"ambito": "agente", "agente": "codex"},
            },
            {
                "id": "e1",
                "tipo": "evidencia",
                "texto": "la corrida",
                "datos": {"clase": "prueba", "referencia": "tests/x.py::t"},
            },
        ],
        "vinculos": [
            {"de": "r1", "relacion": "derivada_de", "a": f"nodo:{inc['id']}"},
            {"de": "r1", "relacion": "aplica_a", "a": f"nodo:{t['id']}"},
            {"de": "r1", "relacion": "apoya", "a": "e1"},
        ],
    }
    inf = k.entregar("teorema", e["id"], _bloque(b), revision=1, autor="frente:sid-f")
    c = inf["datos"]["conocimiento"]
    assert c["estado"] == "incorporado" and c["vinculos"] == 3
    regla = k.nodo("teorema", c["ids"]["r1"])
    assert regla["estado"] == "propuesta"
    assert {(v["relacion"], v["a"]) for v in regla["vinculos"]["salen"]} >= {
        ("derivada_de", inc["id"]),
        ("aplica_a", t["id"]),
    }
    # la busqueda y la expansion ya ven lo declarado
    assert k.buscar("teorema", "borrar")[0]["id"] == c["ids"]["r1"]
    ids = {x["id"] for x in k.expandir("teorema", [inc["id"]], saltos=1)}
    assert c["ids"]["r1"] in ids


def test_api_entrega_con_bloque(proy, monkeypatch):
    r, e = _encargo_enviado("s1")
    code, inf = api.dispatch(
        "POST",
        ["teorema", "entregas"],
        {"encargo": e["id"], "revision": 1, "cuerpo": _bloque(BLOQUE_OK), "autor": "frente:s1"},
        {},
    )
    assert code == 200 and inf["datos"]["conocimiento"]["estado"] == "incorporado"
    assert api.dispatch("GET", ["teorema", "nodos"], None, {"tipo": ["decision"]})[1]["total"] == 1


# --- segundo code review (2026-10-08) --------------------------------------------------------------


def test_cerrar_una_ronda_cerrada_es_409_y_no_pisa_cierre_seq(proy):
    r = k.abrir_ronda("teorema", "r", autor="c")
    c1 = k.cerrar_ronda("teorema", r["id"], por="coordinadora:1")
    k.crear_nodo("teorema", "tema", "despues del cierre", autor="c")
    with pytest.raises(Rechazo) as e:
        k.cerrar_ronda("teorema", r["id"], por="coordinadora:1")
    assert e.value.codigo == 409
    assert k.nodo("teorema", r["id"])["datos"]["cierre_seq"] == c1["datos"]["cierre_seq"]


def test_letra_sin_mayusculas_es_el_mismo_encargo(proy):
    r = k.abrir_ronda("teorema", "r", autor="c")
    e = k.crear_encargo("teorema", r["id"], "a", "primero", autor="c")
    assert e["datos"]["letra"] == "A" and e["datos"]["ruta"].endswith("encargo-A.md")
    with pytest.raises(Rechazo) as x:
        k.crear_encargo("teorema", r["id"], "A", "segundo", autor="c")
    assert x.value.codigo == 409
    assert k.leer_cuerpo("teorema", e["datos"]["ruta"]) == "primero"


def test_base_a_medio_crear_se_repara_por_user_version(proy, monkeypatch):
    """connect crea el archivo antes de que corra el esquema: una base vacia no puede quedar como
    «ya inicializada» para siempre."""
    import sqlite3

    ruta = k._db_path("teorema")
    os.remove(ruta)
    sqlite3.connect(ruta).close()  # un archivo vacio, como el que deja un fallo a mitad del esquema
    assert k.nodos("teorema")["total"] == 0  # el esquema se vuelve a crear y la base funciona
    with k._abrir("teorema") as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == k.VERSION_ESQUEMA


def test_bloque_con_tipo_o_relacion_no_hasheables_es_error_de_validacion(proy):
    r, e = _encargo_enviado()
    malo = {
        "version": 1,
        "nodos": [
            {"id": "h1", "tipo": ["hallazgo"], "texto": "x", "datos": {}},
            {"id": "t1", "tipo": "tema", "texto": "t", "datos": {}},
        ],
        "vinculos": [{"de": "t1", "relacion": {"x": 1}, "a": "t1"}],
    }
    inf = k.entregar("teorema", e["id"], _bloque(malo), revision=1, autor="f")
    c = inf["datos"]["conocimiento"]
    assert c["estado"] == "pendiente_de_vincular"
    assert {(x["donde"], x["error"][:22]) for x in c["errores"]} >= {
        ("nodo h1", "tipo no declarable: ['"),
        ("vinculos[0]", "relacion no declarable"),
    }
