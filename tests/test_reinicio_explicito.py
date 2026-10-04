"""El server ya no se reinicia solo al cambiar un .py (salvo auto_reload): se reinicia explicito, y
la tarjeta real hereda el titulo puesto a mano en la provisoria (medido el 2026-10-04)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sessions as ses

from lienzo import server


def test_reiniciar_sin_lienzo_server_cmd_no_sale(monkeypatch):
    monkeypatch.delenv("LIENZO_RELOAD", raising=False)
    code, res = server.reiniciar()
    assert code == 409 and "lienzo-server.cmd" in res["error"]


def test_reiniciar_bajo_el_cmd_sale_con_75_despues_de_contestar(monkeypatch):
    monkeypatch.setenv("LIENZO_RELOAD", "1")
    monkeypatch.setattr(server, "log", lambda m: None)
    programado = []
    monkeypatch.setattr(
        server.threading, "Timer", lambda t, fn: type("T", (), {"start": lambda self: programado.append(t)})()
    )
    code, res = server.reiniciar()
    assert code == 202 and res["reinicia"] and programado == [0.5]


def test_la_tarjeta_real_hereda_el_titulo_de_la_provisoria():
    prov = {
        "session_id": "pid-123",
        "title": "ariel.levy - encargo F - mutacion",
        "title_source": "user",
        "coordinator": True,
    }
    real = {"session_id": "uuid", "title": "Bien el diagnostico. Reintenta", "title_source": "prompt"}
    ses.heredar_de_provisoria(prov, real)
    assert (
        real["title"] == "ariel.levy - encargo F - mutacion" and real["title_source"] == "user" and real["coordinator"]
    )
