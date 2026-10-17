"""Contrato uniforme de plugins: manifiesto validado antes de importar, sin romper los plugins legacy."""

import json
import threading

import plugin_manifest as pm
import plugins
import procinfo
import pytest

MINIMO = {
    "id": "notas",
    "nombre": "Notas de ronda",
    "version": "1.0.0",
    "compatibilidad": {"contrato": 1},
    "permisos": {},
}


@pytest.fixture
def limpio(monkeypatch):
    monkeypatch.setattr(plugins, "_cargados", {})
    monkeypatch.setattr(plugins, "_fichas", {})
    monkeypatch.setattr(procinfo, "EXTERNAL_RUNNERS", {})


def manifiesto(carpeta, nombre, **campos):
    data = {**MINIMO, "id": nombre, **campos}
    (carpeta / f"{nombre}.plugin.json").write_text(json.dumps(data), encoding="utf-8")


def modulo(carpeta, nombre, cuerpo=""):
    """Un modulo que deja constancia de que se importo: lo que no debe importarse se puede comprobar."""
    marca = (carpeta / f"{nombre}.importado").as_posix()
    (carpeta / f"{nombre}.py").write_text(f"open({marca!r}, 'w').close()\n{cuerpo}", encoding="utf-8")
    return carpeta / f"{nombre}.importado"


def ficha(nombre):
    return next(f for f in plugins.resumen() if f["id"] == nombre)


def test_minimo_valido_sin_tools_endpoints_ni_interfaz():
    res = pm.validar(MINIMO, "notas")
    assert res["errores"] == [] and res["advertencias"] == []
    m = res["manifiesto"]
    assert m["origen"] == "local" and m["url"] is None
    assert m["capacidades"] == m["puntos"] == m["ciclo_de_vida"] == m["configuracion"] == []
    assert m["permisos"] == {k: [] for k in pm.PERMISOS}
    assert m["relaciones"] == {"tools": [], "sistemas": []}
    assert m["compatibilidad"] == {"contrato": [1], "plataformas": []}


@pytest.mark.parametrize(
    "cambio,error",
    [
        ({"permisos": None}, "permisos: obligatorio"),
        ({"compatibilidad": None}, "compatibilidad: obligatoria"),
        ({"compatibilidad": {"contrato": "1"}}, "compatibilidad.contrato"),
        ({"compatibilidad": {"contrato": [True]}}, "compatibilidad.contrato"),
        ({"id": "Notas"}, "id: obligatorio"),
        ({"id": "otro"}, "no coincide con el archivo"),
        ({"version": "uno"}, "version"),
        ({"nombre": "  "}, "nombre"),
        ({"origen": {"tipo": "publico"}}, "declara su url"),
        ({"origen": {"tipo": "publico", "url": "http://x"}}, "origen.url"),
        ({"capacidades": ["magia"]}, "capacidades: valores desconocidos"),
        ({"puntos": ["get", "get"]}, "puntos: valores repetidos"),
        ({"permisos": {"root": []}}, "permisos.root"),
        ({"permisos": {"red": "todo"}}, "permisos.red"),
        ({"configuracion": {"campos": [{"clave": "token", "tipo": "clave"}]}}, "configuracion.campos[0]"),
        ({"configuracion": {"campos": [{"clave": "a", "tipo": "texto"}, {"clave": "a", "tipo": "texto"}]}}, "repetida"),
        ({"relaciones": {"tools": "rtk"}}, "relaciones.tools"),
    ],
)
def test_invalido_dice_por_que(cambio, error):
    data = {k: v for k, v in {**MINIMO, **cambio}.items() if v is not None}
    res = pm.validar(data, "notas")
    assert res["manifiesto"] is None
    assert any(error in e for e in res["errores"]), res["errores"]


def test_claves_y_relaciones_desconocidas_son_advertencias():
    res = pm.validar({**MINIMO, "futuro": 1, "relaciones": {"tools": ["rtk", "otra"]}}, "notas", {"rtk"})
    assert res["errores"] == []
    assert any("futuro" in a for a in res["advertencias"])
    assert any("['otra']" in a for a in res["advertencias"])


def test_leer_json_roto_grande_y_con_bom(tmp_path):
    p = tmp_path / "notas.plugin.json"
    p.write_text("{no", encoding="utf-8")
    assert "JSON inválido" in pm.leer(p)["errores"][0]
    p.write_text(" " * (pm.MAX_BYTES + 1), encoding="utf-8")
    assert "supera" in pm.leer(p)["errores"][0]
    p.write_text(json.dumps(MINIMO), encoding="utf-8-sig")
    assert pm.leer(p)["errores"] == []


def test_incompatibilidad_por_contrato_y_plataforma():
    m = pm.validar({**MINIMO, "compatibilidad": {"contrato": [2]}})["manifiesto"]
    assert "este Lienzo usa 1" in pm.incompatibilidad(m)
    m = pm.validar({**MINIMO, "compatibilidad": {"contrato": [1, 2], "plataformas": ["macos"]}})["manifiesto"]
    assert "esta PC es windows" in pm.incompatibilidad(m, "windows")
    assert pm.incompatibilidad(m, "macos") is None


def test_configuracion_no_lee_ni_devuelve_secretos():
    campos = [
        {"clave": "url", "tipo": "texto", "obligatorio": True},
        {"clave": "token_env", "tipo": "secreto", "obligatorio": True},
        {"clave": "poll_s", "tipo": "numero"},
    ]
    m = pm.validar({**MINIMO, "configuracion": {"campos": campos}})["manifiesto"]
    assert pm.estado_configuracion(m, None, {})["faltan"] == ["url", "token_env"]
    res = pm.estado_configuracion(m, {"url": "x", "token_env": "TOKEN_X"}, {})
    assert res["faltan"] == ["token_env (variable TOKEN_X no definida)"]
    res = pm.estado_configuracion(m, {"url": "x", "token_env": "TOKEN_X"}, {"TOKEN_X": "s3cr3t"})
    assert res == {"completa": True, "faltan": [], "errores": []}
    assert "s3cr3t" not in json.dumps(res)
    res = pm.estado_configuracion(m, {"url": "x", "token_env": "sk-ant 123", "poll_s": True}, {})
    assert res["completa"] is False
    assert any("no el secreto" in e for e in res["errores"]) and any("poll_s" in e for e in res["errores"])
    assert "sk-ant" not in json.dumps(res)
    assert pm.estado_configuracion(m, ["x"], {})["completa"] is False


def test_plugin_minimo_declarativo_y_legacy_conviven(limpio, tmp_path):
    manifiesto(tmp_path, "notas", capacidades=["forma-de-trabajo"])
    modulo(tmp_path, "legacy", "def get(p, q):\n    return 200, {'ok': True}\n")
    assert plugins.cargar(str(tmp_path), config={}) == ["legacy"]
    notas = ficha("notas")
    assert notas["estado"] == "declarado" and notas["cargado"] is False and notas["manifiesto"] == "valido"
    assert notas["capacidades"] == ["forma-de-trabajo"] and notas["puntos"] == []
    assert notas["permisos"] == {k: [] for k in pm.PERMISOS}
    legacy = ficha("legacy")
    assert legacy["estado"] == "cargado" and legacy["manifiesto"] == "ausente" and legacy["permisos"] is None
    assert legacy["advertencias"] == [] and legacy["puntos"] == ["get"]
    assert plugins.get("legacy", [], {}) == (200, {"ok": True})
    assert plugins.get("notas", ["_salud"], {})[0] == 404


def test_manifiesto_invalido_no_importa_y_no_frena_a_los_demas(limpio, tmp_path):
    manifiesto(tmp_path, "malo", permisos="todos")
    marca = modulo(tmp_path, "malo", "RUNNERS_EXTERNOS = {'malo.exe': 'x'}\n")
    modulo(tmp_path, "sano", "def get(p, q):\n    return 200, {}\n")
    assert plugins.cargar(str(tmp_path), config={}) == ["sano"]
    assert not marca.exists() and procinfo.EXTERNAL_RUNNERS == {}
    malo = ficha("malo")
    assert malo["estado"] == "error" and malo["cargado"] is False and malo["manifiesto"] == "invalido"
    assert any("manifiesto inválido: permisos" in e for e in malo["errores"])
    assert plugins.get("malo", [], {})[0] == 404


def test_valido_registra_puntos_declarados(limpio, tmp_path):
    manifiesto(
        tmp_path,
        "orq",
        puntos=["get", "runners_externos"],
        ciclo_de_vida=["iniciar"],
        permisos={"red": ["127.0.0.1"], "efectos_externos": []},
    )
    cuerpo = "RUNNERS_EXTERNOS = {'Orq.exe': 'orq'}\nvivo = []\ndef iniciar():\n    vivo.append(1)\ndef get(p, q):\n    return 200, {'p': p}\n"
    marca = modulo(tmp_path, "orq", cuerpo)
    assert plugins.cargar(str(tmp_path), config={}) == ["orq"]
    assert marca.exists() and procinfo.EXTERNAL_RUNNERS == {"orq.exe": "orq"}
    plugins.iniciar()
    orq = ficha("orq")
    assert orq["estado"] == "cargado" and orq["permisos"]["red"] == ["127.0.0.1"]
    assert "no acredita conexión" in orq["detalle"] and orq["salud"] is None
    assert plugins.get("orq", ["a"], {}) == (200, {"p": ["a"]})


@pytest.mark.parametrize(
    "declarado,cuerpo,error",
    [
        (
            {"puntos": ["get"]},
            "def get(p, q):\n    return 200, {}\ndef post(p, c, x):\n    return 200, {}\n",
            "exporta sin declarar: ['post']",
        ),
        (
            {"puntos": ["get"], "ciclo_de_vida": ["salud"]},
            "def get(p, q):\n    return 200, {}\n",
            "declara y no exporta: ['salud']",
        ),
        ({}, "RUNNERS_EXTERNOS = {'x.exe': 'x'}\n", "exporta sin declarar: ['runners_externos']"),
    ],
)
def test_exportado_y_declarado_deben_coincidir(limpio, tmp_path, declarado, cuerpo, error):
    manifiesto(tmp_path, "orq", **declarado)
    modulo(tmp_path, "orq", cuerpo)
    assert plugins.cargar(str(tmp_path), config={}) == []
    assert procinfo.EXTERNAL_RUNNERS == {}
    orq = ficha("orq")
    assert orq["estado"] == "error" and error in orq["errores"][0]
    assert plugins.get("orq", [], {})[0] == 404


def test_declarativo_no_puede_declarar_codigo(limpio, tmp_path):
    manifiesto(tmp_path, "notas", puntos=["get", "vista"])
    plugins.cargar(str(tmp_path), config={})
    notas = ficha("notas")
    assert notas["estado"] == "error" and "['get'] sin notas.py" in notas["errores"][0]


def test_incompatible_y_deshabilitado_no_se_importan(limpio, tmp_path):
    manifiesto(tmp_path, "nuevo", compatibilidad={"contrato": [2]})
    nuevo = modulo(tmp_path, "nuevo")
    apagado = modulo(tmp_path, "apagado")
    assert plugins.cargar(str(tmp_path), config={"plugins_deshabilitados": ["apagado"]}) == []
    assert not nuevo.exists() and not apagado.exists()
    assert ficha("nuevo")["estado"] == "incompatible" and "contrato" in ficha("nuevo")["errores"][0]
    assert ficha("apagado")["estado"] == "deshabilitado"


def test_sin_configurar_carga_pero_lo_dice(limpio, tmp_path, monkeypatch):
    monkeypatch.delenv("NOTAS_TOKEN_PRUEBA", raising=False)
    campos = [{"clave": "token_env", "tipo": "secreto", "obligatorio": True}]
    manifiesto(tmp_path, "notas", configuracion={"campos": campos})
    modulo(tmp_path, "notas")
    assert plugins.cargar(str(tmp_path), config={"plugins": {"notas": {"token_env": "NOTAS_TOKEN_PRUEBA"}}}) == [
        "notas"
    ]
    notas = ficha("notas")
    assert notas["estado"] == "sin-configurar" and notas["cargado"] is True
    assert notas["configuracion"]["faltan"] == ["token_env (variable NOTAS_TOKEN_PRUEBA no definida)"]


def test_iniciar_que_falla_queda_en_la_ficha(limpio, tmp_path):
    manifiesto(tmp_path, "orq", ciclo_de_vida=["iniciar"])
    modulo(tmp_path, "orq", "def iniciar():\n    raise RuntimeError('sin puerto')\n")
    plugins.cargar(str(tmp_path), config={})
    plugins.iniciar()
    orq = ficha("orq")
    assert orq["estado"] == "error" and orq["cargado"] is True
    assert orq["errores"] == ["iniciar falló: RuntimeError: sin puerto"]
    assert plugins.get("orq", ["x"], {})[0] == 503 and plugins.post("orq", [], {}, {"autor": "a"})[0] == 503


def test_import_que_falla_queda_en_la_ficha(limpio, tmp_path):
    (tmp_path / "roto.py").write_text("raise RuntimeError('mal')\n", encoding="utf-8")
    assert plugins.cargar(str(tmp_path), config={}) == []
    assert ficha("roto")["errores"] == ["no cargó: RuntimeError: mal"]


SALUD = """
import threading
liberar = threading.Event()
llamadas = []
modo = ["ok"]
def salud():
    llamadas.append(1)
    if modo[0] == "colgado":
        liberar.wait(5)
    if modo[0] == "falla":
        raise RuntimeError("sin red")
    if modo[0] == "rara":
        return "ok"
    return {"ok": True, "detalle": "x" * 500, "conectado": True}
def detener():
    llamadas.append("detener")
"""


def test_salud_solo_a_pedido_con_limite(limpio, tmp_path, monkeypatch):
    manifiesto(tmp_path, "orq", ciclo_de_vida=["salud", "detener"])
    modulo(tmp_path, "orq", SALUD)
    plugins.cargar(str(tmp_path), config={})
    mod = plugins._cargados["orq"]
    assert ficha("orq")["salud"] is None and mod.llamadas == []  # el inventario no lo llama
    code, body = plugins.get("orq", ["_salud"], {})
    assert code == 200 and body["salud"]["ok"] is True and body["salud"]["conectado"] is True
    assert len(body["salud"]["detalle"]) == plugins.DETALLE_MAX
    assert ficha("orq")["salud"]["ok"] is True
    mod.modo[0] = "falla"
    assert plugins.salud("orq")[1]["salud"]["ok"] is False
    assert "RuntimeError: sin red" in ficha("orq")["salud"]["detalle"]
    mod.modo[0] = "rara"
    assert "respuesta inválida" in plugins.salud("orq")[1]["salud"]["detalle"]
    monkeypatch.setattr(plugins, "SALUD_TIMEOUT_S", 0.2)
    mod.modo[0] = "colgado"
    code, body = plugins.salud("orq")
    assert code == 200 and body["salud"]["ok"] is False and "sin respuesta" in body["salud"]["detalle"]
    assert plugins.salud("orq")[0] == 409  # no apila hilos
    mod.modo[0] = "ok"
    mod.liberar.set()
    hilo = next(t for t in threading.enumerate() if t.name == "salud-orq")
    hilo.join(5)
    assert plugins.salud("orq")[1]["salud"]["ok"] is True
    assert plugins.detener() == ["orq"] and mod.llamadas[-1] == "detener"


def test_salud_reservada_solo_con_manifiesto(limpio, tmp_path):
    modulo(tmp_path, "legacy", "def get(p, q):\n    return 200, {'propia': p}\n")
    manifiesto(tmp_path, "sinsalud", puntos=["get"])
    modulo(tmp_path, "sinsalud", "def get(p, q):\n    return 200, {}\n")
    plugins.cargar(str(tmp_path), config={})
    assert plugins.get("legacy", ["_salud"], {}) == (200, {"propia": ["_salud"]})
    assert plugins.get("sinsalud", ["_salud"], {})[0] == 404
    assert plugins.detener() == []


def test_deshabilitado_no_reporta_su_manifiesto_roto(limpio, tmp_path):
    manifiesto(tmp_path, "viejo", permisos="todos")
    marca = modulo(tmp_path, "viejo")
    assert plugins.cargar(str(tmp_path), config={"plugins_deshabilitados": ["viejo"]}) == []
    viejo = ficha("viejo")
    assert not marca.exists() and viejo["estado"] == "deshabilitado" and viejo["errores"] == []


def test_configuracion_aparte_de_las_claves_de_lienzo(limpio, tmp_path):
    manifiesto(tmp_path, "wait", configuracion={"campos": [{"clave": "url", "tipo": "texto", "obligatorio": True}]})
    modulo(tmp_path, "wait")
    plugins.cargar(str(tmp_path), config={"wait": True, "plugins": {"wait": {"url": "http://127.0.0.1"}}})
    assert ficha("wait")["estado"] == "cargado" and ficha("wait")["configuracion"]["completa"] is True


def test_server_detiene_plugins_con_tope(limpio, tmp_path, monkeypatch):
    """os._exit salta finally y atexit: el server los detiene antes, y uno colgado no traba la salida."""
    import time

    import server

    manifiesto(tmp_path, "lento", ciclo_de_vida=["detener"])
    modulo(tmp_path, "lento", "import threading\nsuelta = threading.Event()\ndef detener():\n    suelta.wait(10)\n")
    manifiesto(tmp_path, "rapido", ciclo_de_vida=["detener"])
    modulo(tmp_path, "rapido", "parado = []\ndef detener():\n    parado.append(1)\n")
    plugins.cargar(str(tmp_path), config={})
    t0 = time.monotonic()
    assert server.detener_plugins(espera=0.3) == []  # el lento no volvio: se sale igual
    assert time.monotonic() - t0 < 2
    plugins._cargados["lento"].suelta.set()
    assert sorted(server.detener_plugins(espera=2)) == ["lento", "rapido"]
    assert plugins._cargados["rapido"].parado == [1, 1]
    salidas = []
    monkeypatch.setattr(server.os, "_exit", salidas.append)
    server._salir(75)
    assert salidas == [75]
