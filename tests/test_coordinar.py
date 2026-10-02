"""El cliente del skill (skills/lienzo/coordinar.py): lo que se aprendio repartiendo trabajo a otra PC."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c  # noqa: E402


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
    assert c.capacidad("pcB", 10) == {"ok": False, "libre_gb": 2.7, "necesita_gb": 7.0}
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
