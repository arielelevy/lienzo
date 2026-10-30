"""Nivel 3 para sistemas externos (registro_niveles.externo_detalle, externo_buscar, externo_indice):
qué sale con texto, qué queda afuera y que el texto salga sin secretos, rutas ni IDs. Sobre un
LIENZO_HOME temporal (conftest)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import conocimiento_api as api
import registro_niveles as registro

P = "teorema"
COORD = "coordinadora:test"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)


@pytest.fixture
def proy():
    k.registrar_proyecto(P, "Teorema")
    tema = k.crear_nodo(P, "tema", "Cuotas de Claude", autor="f")["id"]
    vigente = k.crear_nodo(P, "decision", "Leer cuotas de las dos cuentas", {"motivo": "m"}, autor="f")["id"]
    k.cambiar_estado(P, vigente, "vigente", por=COORD, motivo="ok")
    k.vincular(P, vigente, "sobre", tema, autor="f")
    revertida = k.crear_nodo(P, "decision", "Cuotas por scraping descartado", {"motivo": "m"}, autor="f")["id"]
    k.cambiar_estado(P, revertida, "revertida", por=COORD, motivo="no")
    k.crear_nodo(
        P,
        "hallazgo",
        r"El log en C:\Users\ana\.lienzo\x.log trae sesion 0123456789abcdef0123456789abcdef y token sk-ant-abcdefghijklmnopqrstuvwxyz0123",
        autor="f",
    )
    k.crear_nodo(P, "pregunta", "¿Cuotas por PC o por cuenta?", autor="f")
    k.crear_nodo(P, "incidente", "cuotas interno del frente", autor="f")
    return {"tema": tema}


def test_detalle_trae_lo_vivo_con_temas(proy):
    d = registro.externo_detalle(P)
    assert d["nivel"] == 3 and d["proyecto"] == P
    assert d["actividad"]  # el agregado de siempre sigue
    assert d["temas"] == [{"tema": "Cuotas de Claude", "nodos": 1}]
    assert [x["texto"] for x in d["decisiones"]] == ["Leer cuotas de las dos cuentas"]
    assert d["decisiones"][0]["estado"] == "vigente"
    assert d["decisiones"][0]["temas"] == ["Cuotas de Claude"]
    assert [x["texto"] for x in d["preguntas"]] == ["¿Cuotas por PC o por cuenta?"]
    assert "id" not in d["decisiones"][0]


def test_detalle_tapa_rutas_ids_y_secretos(proy):
    texto = registro.externo_detalle(P)["hallazgos"][0]["texto"]
    assert "C:\\Users" not in texto and "[ruta]" in texto
    assert "0123456789abcdef0123456789abcdef" not in texto and "[id]" in texto
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz0123" not in texto


def test_buscar_solo_nivel3(proy):
    r = registro.externo_buscar(P, "cuotas")
    textos = {x["texto"] for x in r["resultados"]}
    assert "Leer cuotas de las dos cuentas" in textos
    assert "Cuotas de Claude" in textos
    assert "Cuotas por scraping descartado" not in textos  # revertida
    assert "cuotas interno del frente" not in textos  # incidente: no sale


def test_buscar_fts_invalida_es_400(proy):
    with pytest.raises(k.Rechazo) as e:
        registro.externo_buscar(P, '"sin cerrar')
    assert e.value.codigo == 400


def test_indice_sin_carpetas(proy):
    k.registrar_proyecto("vacio", "Vacio")
    i = registro.externo_indice()
    assert [p["proyecto"] for p in i["proyectos"]] == [P]
    p = i["proyectos"][0]
    assert p["nombre"] == "Teorema"
    assert p["cantidades"] == {"decision": 1, "hallazgo": 1, "pregunta": 1, "tema": 1}
    assert set(p) == {"proyecto", "nombre", "cantidades", "ultima_fecha"}


def test_api(proy):
    code, d = api.dispatch("GET", [P, "registro-externo"], None, {})
    assert code == 200 and "decisiones" not in d
    code, d = api.dispatch("GET", [P, "registro-externo"], None, {"detalle": "1", "limite": "5"})
    assert code == 200 and d["decisiones"]
    code, d = api.dispatch("GET", [P, "registro-externo", "buscar"], None, {"q": "cuotas"})
    assert code == 200 and d["resultados"]
    code, d = api.dispatch("GET", [P, "registro-externo", "buscar"], None, {})
    assert code == 400
    code, d = api.dispatch("GET", ["registro-externo"], None, {})
    assert code == 200 and d["proyectos"][0]["proyecto"] == P
    code, _ = api.dispatch("GET", ["nadie", "registro-externo"], None, {"detalle": "1"})
    assert code == 404


def test_bot_externo_clave_y_lista(proy):
    import bot_externo as bot

    k.registrar_proyecto("cliente", "Cliente")
    k.crear_nodo("cliente", "pregunta", "dato del cliente", autor="f")
    cfg = {"clave": "abc", "url": "https://x.example", "proyectos": [P]}
    ok = "Bearer abc"
    assert bot.responder(cfg, "GET", "/proyectos", None)[0] == 401
    assert bot.responder(cfg, "GET", "/proyectos", "Bearer otra")[0] == 401
    assert bot.responder(cfg, "POST", "/proyectos", ok)[0] == 405
    code, d = bot.responder(cfg, "GET", "/proyectos", ok)
    assert code == 200 and [p["proyecto"] for p in d["proyectos"]] == [P]
    assert bot.responder(cfg, "GET", "/proyectos/cliente", ok)[0] == 404
    assert bot.responder(cfg, "GET", "/proyectos/cliente/buscar?q=dato", ok)[0] == 404
    code, d = bot.responder(cfg, "GET", f"/proyectos/{P}?limite=2", ok)
    assert code == 200 and d["decisiones"]
    code, d = bot.responder(cfg, "GET", f"/proyectos/{P}/buscar?q=cuotas", ok)
    assert code == 200 and d["resultados"]
    assert bot.responder(cfg, "GET", f"/proyectos/{P}/buscar?q=%22mal", ok)[0] == 400
    assert bot.responder(cfg, "GET", f"/proyectos/{P}?limite=x", ok)[0] == 400
    code, spec = bot.responder(cfg, "GET", "/openapi.json", None)  # el esquema no lleva datos
    assert code == 200 and spec["servers"] == [{"url": "https://x.example"}]
    assert {"listarProyectos", "verProyecto", "buscarEnProyecto"} == {
        op["operationId"] for path in spec["paths"].values() for op in path.values()
    }


def test_bot_externo_config_crea_clave(tmp_path, monkeypatch):
    import bot_externo as bot

    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    a = bot.config()
    assert len(a["clave"]) >= 40 and a["proyectos"] is None
    assert bot.config() == a  # no la regenera


def test_bot_externo_arranca_solo_con_config(tmp_path, monkeypatch):
    import socket
    import urllib.request

    import bot_externo as bot

    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    assert bot.arrancar(lambda m: None) is None  # sin config no arranca ni crea clave
    assert not os.path.exists(bot.config_path())
    bot.config()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    hilo = bot.arrancar(lambda m: None, puerto=puerto, reintento_s=0.05)
    assert hilo is not None
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/openapi.json", timeout=1) as r:
                assert r.status == 200
                break
        except OSError:
            __import__("time").sleep(0.05)
    else:
        pytest.fail("no arrancó")
