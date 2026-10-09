"""«Autorizar y que reintente»: lo autorizado desde el tablero no vuelve a aparecer al releer el mismo
turno (sessions.autorizar_denegado y el filtro de set_denied), lo nuevo del turno sí, y un pedido
nuevo lo olvida. Medido el 2026-10-09 en ar-it33940: el aviso volvía en cada relectura."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import sessions as ses
import state as st
from test_server import aislado  # noqa: F401

SID = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
CLIC = {"tool": "Bash", "motivo": "auto mode", "detalle": "node cdp.mjs click", "turno": "t1"}
DRIVE = {"tool": "Bash", "motivo": "auto mode", "detalle": "node cdp.mjs drive", "turno": "t1"}


def tarjeta():
    s = ses.new_session(SID, "claude", "hook")
    s["state"] = "corriendo"
    with ses.lock:
        st.sessions[SID] = s
    return s


def test_lo_autorizado_no_vuelve_en_el_mismo_turno_y_lo_nuevo_si(aislado):  # noqa: F811
    s = tarjeta()
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})
    assert s["last_denied"]["detalle"] == "node cdp.mjs click"
    ses.autorizar_denegado(s)
    assert s["last_denied"] is None
    # la relectura del mismo turno trae la misma denegacion: no vuelve
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})
    assert s["last_denied"] is None
    # una denegacion nueva del turno, junto a la vieja: se ve solo la nueva
    ses.set_denied(s, {**DRIVE, "n": 2, "todas": [CLIC, DRIVE]})
    assert s["last_denied"]["detalle"] == "node cdp.mjs drive"
    assert s["last_denied"]["n"] == 1 and [x["detalle"] for x in s["last_denied"]["todas"]] == ["node cdp.mjs drive"]
    # un pedido nuevo olvida lo autorizado: la misma denegacion en otro turno es nueva
    ses.hook_prompt_submit(s, {})
    assert s["denied_ok"] is None
    ses.set_denied(s, {**CLIC, "turno": "t2", "n": 1, "todas": [{**CLIC, "turno": "t2"}]})
    assert s["last_denied"]["detalle"] == "node cdp.mjs click"


def test_el_envio_con_autoriza_denegado_marca_la_tarjeta(aislado, monkeypatch):  # noqa: F811
    s = tarjeta()
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})
    monkeypatch.setattr(server, "send_to_session", lambda s, text, att: (200, {"chars": len(text)}))
    code, _ = server.accion_send(s, {"text": "autorizo", "attachments": []})
    assert code == 200 and s["last_denied"] is not None  # un envio comun no toca el aviso
    code, _ = server.accion_send(s, {"text": "autorizo", "attachments": [], "autoriza_denegado": True})
    assert code == 200 and s["last_denied"] is None
    assert s["denied_ok"] == [["Bash", "node cdp.mjs click"]]
    # si el envio falla, no se marca nada
    s2 = tarjeta()
    ses.set_denied(s2, {**DRIVE, "n": 1, "todas": [DRIVE]})
    monkeypatch.setattr(server, "send_to_session", lambda s, text, att: (409, {"error": "ocupada"}))
    server.accion_send(s2, {"text": "x", "attachments": [], "autoriza_denegado": True})
    assert s2["last_denied"] is not None
