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


def test_denegacion_de_coda_conserva_su_comando_y_no_vuelve_tras_autorizarla(aislado, monkeypatch):  # noqa: F811
    """La denegacion de coda sale del log; el comando lo pone el lienzo con last_cmd, que avanza con
    cada comando aprobado. Mismo `at`: mismo comando y ningun anuncio nuevo; autorizada, no vuelve
    aunque cambie last_cmd (2026-10-09, cambio de la sesion a1209581 de ar-it33940)."""
    den = {"tool": "bash", "cause": "command-policy", "sub": False, "at": "2026-10-09T16:12:00.000Z"}
    act = {
        "running": True,
        "asking": None,
        "denied": den,
        "last_at": None,
        "last_tool": "bash",
        "tools": 3,
        "sub": False,
    }
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = ses.new_session(SID, "coda", "hook")
    s.update(pid=1, state="corriendo", last_cmd="irm https://x | iex")
    with ses.lock:
        st.sessions[SID] = s
    ses.coda_log_activity(s)
    assert s["last_denied"]["detalle"] == "irm https://x | iex"
    visto = s["last_denied"]["visto"]
    s["last_cmd"] = "curl.exe -sL https://y"  # coda siguio con otro comando, aprobado
    ses.coda_log_activity(s)
    assert s["last_denied"]["detalle"] == "irm https://x | iex" and s["last_denied"]["visto"] == visto
    ses.autorizar_denegado(s)
    s["last_cmd"] = "grep kiro"
    ses.coda_log_activity(s)
    assert s["last_denied"] is None


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


def test_el_hook_del_propio_mensaje_de_autorizacion_no_hace_volver_el_aviso(aislado, monkeypatch):  # noqa: F811
    """Medido el 2026-10-10 en chesstudia C: el mensaje de autorizacion entra como pedido, su
    UserPromptSubmit borraba lo autorizado (llegue antes o despues de que el envio vuelva) y la
    relectura del turno volvia a mostrar la misma denegacion."""
    s = tarjeta()
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})

    def teclea_y_llega_el_hook(tarjeta_, texto, att):
        ses.mark_sent(tarjeta_, texto)
        ses.hook_prompt_submit(tarjeta_, {"prompt": texto, "prompt_id": "p2"})  # el hook gana la carrera
        return 200, {"chars": len(texto)}

    monkeypatch.setattr(server, "send_to_session", teclea_y_llega_el_hook)
    texto = "El humano autoriza lo que se te denegó: Bash node cdp.mjs click. Reintentá sólo eso."
    code, _ = server.accion_send(s, {"text": texto, "attachments": [], "autoriza_denegado": True})
    assert code == 200
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})  # la relectura del mismo turno
    assert s["last_denied"] is None and s["denied_ok"] == [["Bash", "node cdp.mjs click"]]
    # el hook que llega despues de que el envio volvio, tambien
    s2 = tarjeta()
    ses.set_denied(s2, {**DRIVE, "n": 1, "todas": [DRIVE]})
    monkeypatch.setattr(server, "send_to_session", lambda t, texto, att: (ses.mark_sent(t, texto), (200, {}))[1])
    server.accion_send(s2, {"text": "autorizo drive", "attachments": [], "autoriza_denegado": True})
    ses.hook_prompt_submit(s2, {"prompt": "autorizo drive", "prompt_id": "p3"})
    ses.set_denied(s2, {**DRIVE, "n": 1, "todas": [DRIVE]})
    assert s2["last_denied"] is None
    # un pedido del usuario en la terminal, despues, si olvida lo autorizado
    ses.hook_prompt_submit(s2, {"prompt": "otra cosa", "prompt_id": "p4"})
    assert s2["denied_ok"] is None and not s2["autorizando"]


def test_si_el_envio_de_la_autorizacion_falla_el_aviso_vuelve_como_estaba(aislado, monkeypatch):  # noqa: F811
    s = tarjeta()
    ses.set_denied(s, {**CLIC, "n": 1, "todas": [CLIC]})
    antes = dict(s["last_denied"])
    monkeypatch.setattr(server, "send_to_session", lambda t, texto, att: (409, {"error": "ocupada"}))
    server.accion_send(s, {"text": "autorizo", "attachments": [], "autoriza_denegado": True})
    assert s["last_denied"] == antes and not s["denied_ok"] and not s["autorizando"]
