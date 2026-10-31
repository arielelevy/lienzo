"""coordinar.liberar_turno dice quién suelta el turno, para que el lienzo le avise al dueño (openSeec, 2026-10-30)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def test_liberar_el_turno_de_otra_manda_por(monkeypatch):
    pedidos = []
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (pedidos.append(r), (200, {}))[1])
    monkeypatch.setattr(c, "YO", "coord")
    c.liberar_turno("motores", "g")
    c.liberar_turno("motores", "coord")
    assert pedidos == ["/turnos/motores?session_id=g&por=coord", "/turnos/motores?session_id=coord"]


def test_cerrar_sesion_manda_la_confirmacion(monkeypatch):
    # openSeec, 2026-10-30: /kill exige confirm=<session_id> y no había ayudante (se probó {} y {"confirmar": true})
    pedidos = []
    monkeypatch.setattr(
        c, "pedir", lambda m, r, cuerpo=None, timeout=20: (pedidos.append((m, r, cuerpo)), (200, {}))[1]
    )
    c.cerrar_sesion({"session_id": "s1"})
    assert pedidos == [("POST", "/sessions/s1/kill", {"confirm": "s1"})]


def test_un_envio_que_rebota_por_el_nombre_nativo_se_reintenta(monkeypatch):
    # openSeec 0.21: dos de cuatro encargos rebotaron con 409 «se está actualizando el nombre nativo»
    respuestas = [
        (409, {"error": "se está actualizando el nombre nativo; reintentá cuando termine"}),
        (200, {"ok": True}),
    ]
    enviados = []

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "POST":
            enviados.append(r)
            return respuestas.pop(0)
        raise AssertionError(r)

    tarjeta = {"session_id": "u1", "pc": "p", "pid": 1, "cwd": "x", "agent": "claude", "state": "termino"}
    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: [{**tarjeta, "state": "corriendo" if len(enviados) > 1 else "termino"}])
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = c.enviar_seguro(tarjeta, "leé el encargo", enlazar=False, espera=2)
    assert r["ok"] is True and len(enviados) == 2
