"""El cliente del skill (skills/lienzo/coordinar.py): lo que se aprendio repartiendo trabajo a otra PC."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def _tarjeta(sid, **kw):
    return {"session_id": sid, "pc": "pcB", "pid": 100, "cwd": r"D:\apps\x", "agent": "coda", "state": "termino", **kw}


def test_reubicar_sigue_a_la_tarjeta_cuando_cambia_de_id():
    vieja = _tarjeta("pid-100")
    nueva = _tarjeta("uuid-real")
    assert c.reubicar(vieja, [nueva])["session_id"] == "uuid-real"
    assert c.reubicar(vieja, [vieja, nueva])["session_id"] == "pid-100"
    assert c.reubicar(vieja, [_tarjeta("otra", pid=200)]) is None
    assert c.reubicar(vieja, [_tarjeta("otra", pc="pcC")]) is None  # mismo pid en otra PC no es la misma


def test_enviar_seguro_da_ok_aunque_la_tarjeta_cambie_de_id(monkeypatch):
    vieja = _tarjeta("pid-100")
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, {"ok": True}))
    monkeypatch.setattr(c, "sesiones", lambda: [_tarjeta("uuid-real", state="corriendo")])
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = c.enviar_seguro(vieja, "hola", enlazar=False, espera=3)
    assert r["ok"] is True and r["sid"] == "uuid-real"


def test_capacidad_avisa_si_no_alcanza_la_memoria(monkeypatch):
    monkeypatch.setattr(c, "salud", lambda: [{"pc_id": "pcB", "health": {"mem_free_gb": 2.7}}])
    assert c.capacidad("pcB", 1)["ok"] is True
    assert c.capacidad("pcB", 2)["ok"] is False  # 2,7 - 1,4 = 1,3 GB: por debajo de la reserva
    assert c.capacidad("pcB", 10) == {"ok": False, "libre_gb": 2.7, "necesita_gb": 7.0, "entran": 1}
    assert c.capacidad("desconocida", 1)["ok"] is False


def test_estancada_solo_si_la_pantalla_no_cambia_y_sigue_corriendo(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr("time.time", lambda: t[0])
    pantalla = {"lines": ["Waiting for model…"]}
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, pantalla))
    c._PANTALLAS.clear()
    s = _tarjeta("u1", state="corriendo")
    assert c.estancada(s, minutos=5) is False  # primera vez: solo la memoriza
    t[0] += 301
    assert c.estancada(s, minutos=5) is True
    pantalla["lines"] = ["otra cosa"]
    assert c.estancada(s, minutos=5) is False  # cambio: ya no esta clavada
    t[0] += 301
    assert c.estancada(_tarjeta("u1", state="termino"), minutos=5) is False  # terminada no es clavada


def test_enviar_seguro_rechaza_caracteres_de_control(monkeypatch):
    monkeypatch.setattr(c, "pedir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe enviar")))
    r = c.enviar_seguro(_tarjeta("u1"), "leé D:" + chr(7) + "pps")  # un "\a" sin escapar es BEL: la ruta llega rota
    assert r["ok"] is False and r["code"] == 400 and "0x7" in r["motivo"]
    assert c.enviar_seguro.__doc__  # y un texto normal con saltos de linea no se rechaza


def test_enviar_seguro_acepta_saltos_de_linea(monkeypatch):
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, {"ok": True}))
    monkeypatch.setattr(c, "sesiones", lambda: [_tarjeta("u1", state="corriendo")])
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert c.enviar_seguro(_tarjeta("u1"), "linea 1\nlinea 2\t con tab", enlazar=False, espera=2)["ok"] is True


def test_cablear_crea_una_regla_por_frente_vivo_y_no_repite(monkeypatch):
    c.YO = "coord"
    creadas = []
    ses = [
        _tarjeta("coord"),
        _tarjeta("a", alive=True),
        _tarjeta("b", alive=True),
        _tarjeta("muerta", alive=False),
        _tarjeta("c", alive=True, coordinator=True),
    ]

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "GET":
            return 200, [{"kind": "on_stop", "from": "b", "to": "coord"}]
        creadas.append(cuerpo["from"])
        return 200, {"id": "x"}

    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: ses)
    r = c.cablear()
    assert r["creadas"] == ["a"] and r["ya_estaban"] == ["b"] and r["fallaron"] == [] and creadas == ["a"]


def test_cablear_cuenta_los_fallos_con_el_motivo(monkeypatch):
    c.YO = "coord"
    monkeypatch.setattr(c, "sesiones", lambda: [_tarjeta("a", alive=True)])
    monkeypatch.setattr(
        c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, []) if m == "GET" else (502, {"error": "git pull"})
    )
    r = c.cablear()
    assert r["creadas"] == [] and r["fallaron"][0]["code"] == 502 and "git pull" in r["fallaron"][0]["error"]


def test_pedir_devuelve_el_dict_del_error_http_o_el_texto_recortado(monkeypatch):
    import io
    import urllib.error

    def falla(cuerpo):
        def _urlopen(req, timeout=20):
            raise urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO(cuerpo))

        return _urlopen

    monkeypatch.setattr("urllib.request.urlopen", falla('{"error": "ñ", "gone": true}'.encode()))
    assert c.pedir("GET", "/x") == (404, {"error": "ñ", "gone": True})
    monkeypatch.setattr("urllib.request.urlopen", falla(b"<html>" + b"x" * 300))
    code, texto = c.pedir("GET", "/x")
    assert code == 404 and isinstance(texto, str) and len(texto) == 200


def test_enviar_seguro_reubica_el_frente_cuando_la_tarjeta_ya_no_existe(monkeypatch):
    c.YO = ""
    llamadas = []

    def pedir(m, r, cuerpo=None, timeout=20):
        llamadas.append(r)
        if "viejo" in r:
            return 404, {"error": "esa tarjeta ya no existe", "gone": True}
        return 200, {"ok": True}

    nuevo = _tarjeta("nuevo", title="app - encargo A - x", alive=True, state="termino")
    monkeypatch.setattr(c, "pedir", pedir)
    # la nueva pasa a corriendo recien cuando le llega el envio (si ya corria, eso no probaria nada)
    monkeypatch.setattr(
        c, "sesiones", lambda: [{**nuevo, "state": "corriendo"} if "/sessions/nuevo/send" in llamadas else nuevo]
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = c.enviar_seguro(_tarjeta("viejo"), "hola", proyecto="app", letra="A", enlazar=False, espera=2)
    assert r["ok"] is True and r["sid"] == "nuevo" and llamadas == ["/sessions/viejo/send", "/sessions/nuevo/send"]


def test_cuerpo_envio_enlaza_solo_con_yo():
    c.YO = ""
    assert c._cuerpo_envio("s", "t", True) == {"text": "t"}
    c.YO = "coord"
    assert c._cuerpo_envio("s", "t", True) == {"text": "t", "from": "coord", "link_to": "s"}
    assert c._cuerpo_envio("s", "t", False) == {"text": "t"}
    c.YO = ""


def test_lanzar_y_titular_cablea_la_tarjeta_nueva_a_la_coordinadora(monkeypatch):
    c.YO = "coord"
    nueva = _tarjeta("pid-9", pid=9, cwd=r"D:\apps\x")
    vistas = [[], [nueva]]  # antes de lanzar no hay nada; despues aparece la provisoria
    monkeypatch.setattr(c, "sesiones", lambda: vistas.pop(0) if len(vistas) > 1 else vistas[0])
    pedidos = []

    def pedir(m, r, cuerpo=None, timeout=20):
        pedidos.append((m, r, cuerpo))
        return 200, {"ok": True}

    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = c.lanzar_y_titular("pcB", r"D:\apps\x", "t", "coda", espera=5)
    assert r["session_id"] == "pid-9"
    regla = next(b for m, ruta, b in pedidos if ruta == "/rules")
    assert (
        regla["kind"] == "on_stop" and regla["from"] == "pid-9" and regla["to"] == "coord" and regla["repeat"] is True
    )


def test_lanzar_y_titular_sin_cablear_no_crea_regla(monkeypatch):
    c.YO = "coord"
    nueva = _tarjeta("pid-9", pid=9, cwd=r"D:\apps\x")
    vistas = [[], [nueva]]
    monkeypatch.setattr(c, "sesiones", lambda: vistas.pop(0) if len(vistas) > 1 else vistas[0])
    pedidos = []
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: pedidos.append(r) or (200, {"ok": True}))
    monkeypatch.setattr("time.sleep", lambda s: None)
    c.lanzar_y_titular("pcB", r"D:\apps\x", "t", "coda", espera=5, cablear_al_lanzar=False)
    assert "/rules" not in pedidos


def test_informe_ignora_el_estado_de_herramienta_y_lo_que_corre():
    import coordinar as c

    assert c.informe({"state": "termino", "last_reply": "usando bash"}) is None
    assert c.informe({"state": "termino", "last_reply": "usando read (subagente)"}) is None
    assert c.informe({"state": "corriendo", "last_reply": "Listo, termine"}) is None
    assert c.informe({"state": "termino", "last_reply": ""}) is None
    assert c.informe({"state": "termino", "last_reply": "B LISTA - hash abc"}) == "B LISTA - hash abc"


def test_restaurar_espera_mas_que_el_reenvio_a_la_otra_pc(monkeypatch):
    """El server local reenvia /restaurar a la PC dueña con RESTORE_TIMEOUT_S (300 s); el skill
    esperaba 120 y veia un timeout aunque el relanzamiento siguiera andando (revision B16)."""
    import federation

    pedidos = []
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: pedidos.append(timeout) or (200, {}))
    c.restaurar(todas=True, pc="pcB")
    assert pedidos[0] > federation.RESTORE_TIMEOUT_S
