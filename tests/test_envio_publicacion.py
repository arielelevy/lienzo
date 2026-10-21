"""Publicación real HTTP/SSE aislada; transporte Codex simulado, nunca consumo de cuenta."""

import http.client
import json
import os
import threading
import time
from pathlib import Path

import codex_queue as cq
import pytest
import sessions as ses
import state

from lienzo import server

SID = "01a14a70-1105-73b3-87ce-7a60b4b925fd"
PLAN = {"puede": True, "motivo": None, "transporte": "codex_queue"}


@pytest.fixture
def card(monkeypatch, tmp_path):
    s = {
        "session_id": SID,
        "agent": "codex",
        "pid": 42,
        "repo": "fixture",
        "started": "2026-10-17",
        "transcript_path": str(tmp_path / "rollout.jsonl"),
        "envio_codex": {"estado": "encolado", "envio_id": "e1", "at": time.time()},
    }
    monkeypatch.setattr(ses, "sessions", {SID: s})
    monkeypatch.setattr(server, "sessions", ses.sessions)
    monkeypatch.setattr(ses, "_envio_publico", {})
    monkeypatch.setattr(ses, "_envio_poll_at", -1e9)
    monkeypatch.setattr(ses, "_envio_poll_cursor", 0)
    monkeypatch.setattr(ses.captura, "vista", lambda s: None)
    monkeypatch.setattr(state, "clients", [])
    monkeypatch.setattr(server, "clients", state.clients)
    monkeypatch.setattr(server, "ui_clients", [])
    os.makedirs(state.SESSIONS, exist_ok=True)
    return s


def assert_lock_free():
    """Otro hilo debe poder entrar: no depende de detalles privados de RLock."""
    entered = threading.Event()

    def acquire():
        with ses.lock:
            entered.set()

    t = threading.Thread(target=acquire)
    t.start()
    assert entered.wait(1), "IO de capacidad/confirmación bajo lock global"
    t.join(1)


def test_snapshots_copy_and_only_compute_local_capabilities(card, monkeypatch):
    remote = {"session_id": "remote", "pc": "other", "envio": {"puede": False, "motivo": "dueña", "transporte": None}}

    def plan(s):
        assert s["session_id"] == SID
        assert_lock_free()
        return PLAN

    monkeypatch.setattr(ses, "puede_enviar", plan)
    monkeypatch.setattr(server.mirror.MIRROR, "sessions", lambda: [remote])
    snap = server._local_state()
    assert snap["sessions"][0]["envio"] == PLAN
    card["envio_codex"]["estado"] = "entregado"
    assert snap["sessions"][0]["envio_codex"]["estado"] == "encolado"
    assert "envio" not in card  # capacidad derivada nunca persistida en la tarjeta
    ui = json.loads(server.snapshot_json(con_espejo=True))
    peer = json.loads(server.snapshot_json(con_espejo=False))
    assert ui["sessions"][-1] == remote
    assert len(peer["sessions"]) == 1


def test_touch_is_pure_publication_and_invalidates_changed_guard(card, monkeypatch):
    ses.public_session(dict(card), calcular=True)  # default autouse impide codex real
    monkeypatch.setattr(ses, "puede_enviar", lambda s: pytest.fail("touch no hace IO"))
    events = []
    monkeypatch.setattr(state, "broadcast", events.append)
    card["stopped_by"] = "user"
    assert ses.touch(card)
    assert not events[-1]["session"]["envio"]["puede"]
    assert events[-1]["session"]["envio_codex"]["estado"] == "encolado"
    assert "envio" not in json.loads((Path(state.SESSIONS) / (SID + ".json")).read_text(encoding="utf-8"))


def test_periodic_confirmation_persists_and_broadcasts_without_sending(card, monkeypatch):
    monkeypatch.setattr(ses, "puede_enviar", lambda s: PLAN)
    monkeypatch.setattr(cq, "enviar", lambda *a: pytest.fail("sondear nunca envía"))
    calls, events = [], []

    def confirm(eid):
        assert_lock_free()
        calls.append(eid)
        return {
            "estado": "entregado",
            "envio_id": eid,
            "motivo": None,
            "referencia": "ref",
            "transporte": "codex_queue",
        }

    monkeypatch.setattr(cq, "confirmar", confirm)
    monkeypatch.setattr(state, "broadcast", events.append)
    ses.refresh_envios()
    ses.refresh_envios()
    assert calls == ["e1"]
    assert card["envio_codex"]["estado"] == "entregado"
    assert events[-1]["session"]["envio"] == PLAN
    stored = json.loads((Path(state.SESSIONS) / (SID + ".json")).read_text(encoding="utf-8"))
    assert stored["envio_codex"]["estado"] == "entregado"


def test_expiration_is_visible_and_polling_stops(card, monkeypatch):
    card["envio_codex"]["at"] -= cq.CONFIRM_LIMIT_S + 1
    monkeypatch.setattr(ses, "puede_enviar", lambda s: PLAN)
    calls = []

    def confirm(eid):
        calls.append(eid)
        return {"estado": "sin_confirmacion", "envio_id": eid, "motivo": "venció; no se reintenta"}

    monkeypatch.setattr(cq, "confirmar", confirm)
    monkeypatch.setattr(state, "broadcast", lambda e: None)
    ses.refresh_envios()
    monkeypatch.setattr(ses, "_envio_poll_at", -1e9)
    ses.refresh_envios()
    assert calls == ["e1"]
    assert card["envio_codex"]["confirmacion_final"]
    assert card["envio_codex"]["motivo"] == "venció; no se reintenta"


@pytest.mark.parametrize("replace", [False, True])
def test_late_result_never_overwrites_new_send_or_replacement(card, monkeypatch, replace):
    monkeypatch.setattr(ses, "puede_enviar", lambda s: PLAN)

    def confirm(eid):
        if replace:
            ses.sessions[SID] = {**card, "envio_codex": {"envio_id": "new", "estado": "encolado"}}
        else:
            card["envio_codex"] = {"envio_id": "new", "estado": "encolado"}
        return {"estado": "entregado", "envio_id": eid}

    monkeypatch.setattr(cq, "confirmar", confirm)
    monkeypatch.setattr(state, "broadcast", lambda e: None)
    ses.refresh_envios()
    assert ses.sessions[SID]["envio_codex"] == {"envio_id": "new", "estado": "encolado"}


def test_poll_limits_and_round_robin(card, monkeypatch):
    for i in range(20):
        sid = f"extra-{i}"
        ses.sessions[sid] = {**card, "session_id": sid, "envio_codex": None}
    seen = []
    monkeypatch.setattr(ses, "puede_enviar", lambda s: seen.append(s["session_id"]) or PLAN)
    monkeypatch.setattr(cq, "confirmar", lambda e: {"estado": "encolado", "envio_id": e})
    monkeypatch.setattr(state, "broadcast", lambda e: None)
    ses.refresh_envios()
    assert len(seen) == ses.ENVIO_POLL_MAX
    for _ in range(2):
        monkeypatch.setattr(ses, "_envio_poll_at", -1e9)
        ses.refresh_envios()
    assert set(seen) == set(ses.sessions)


def test_liveness_calls_confirmation(card, monkeypatch):
    calls = []
    monkeypatch.setattr(ses, "check_liveness", lambda sid: None)
    monkeypatch.setattr(ses, "remember_live_cards", lambda: None)
    monkeypatch.setattr(ses, "refresh_envios", lambda: calls.append("poll"))
    ses.liveness_pass(0)
    assert calls == ["poll"]


def test_codex_executable_is_disabled_by_default():
    assert cq.codex_exe() is None


def test_real_http_get_and_sse_deliver_updated_card(card, monkeypatch):
    """Sockets reales en puerto efímero; auth/transporte/capacidad fixtures declarados."""
    monkeypatch.setattr(ses, "puede_enviar", lambda s: PLAN)
    monkeypatch.setattr(server.Handler, "_authed", lambda self: True)
    monkeypatch.setattr(server, "log", lambda *a: None)
    monkeypatch.setattr(server.mirror.MIRROR, "sessions", list)
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection(*srv.server_address, timeout=3)
    stream = http.client.HTTPConnection(*srv.server_address, timeout=3)
    try:
        client.request("GET", "/sessions")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())[0]["envio"] == PLAN
        stream.request("GET", "/events")
        response = stream.getresponse()
        assert response.status == 200
        initial = json.loads(response.readline().decode()[6:])
        assert initial["sessions"][0]["envio"] == PLAN
        response.readline()
        card["envio_codex"]["estado"] = "entregado"
        ses.touch(card)
        event = json.loads(response.readline().decode()[6:])
        assert event["type"] == "session"
        assert event["session"]["envio_codex"]["estado"] == "entregado"
        assert event["session"]["envio"] == PLAN
    finally:
        client.close()
        stream.close()
        srv.shutdown()
        srv.server_close()
        thread.join(3)


@pytest.fixture
def queue_card(tmp_path, monkeypatch):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("", encoding="utf-8")
    monkeypatch.setattr(cq, "codex_exe", lambda: "C:/fake/codex.exe")
    monkeypatch.setattr(cq.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(
        cq.codex_identity,
        "probe",
        lambda pid: {"verified": True, "pid": pid, "process_start": 1234, "thread": SID, "path": str(rollout)},
    )
    return {
        "agent": "codex",
        "session_id": SID,
        "pid": 42,
        "transcript_path": str(rollout),
        "codex_process_start": 1234,
    }


def test_atomic_reservation_blocks_parallel_queue_calls(queue_card, monkeypatch):
    barrier = threading.Barrier(2)
    release = threading.Event()
    calls, results = [], []

    def fake(argv, **kw):
        calls.append(argv)
        barrier.wait(3)
        assert release.wait(3)
        return 0, f"Queued message {SID} for thread {SID}", ""

    monkeypatch.setattr(cq.subproc, "correr", fake)
    worker = threading.Thread(target=lambda: results.append(cq.enviar(queue_card, "same", esperar=0)))
    worker.start()
    try:
        barrier.wait(3)
        second = cq.enviar(queue_card, "same", esperar=0)
        assert second["estado"] == "pendiente"
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and results[0]["estado"] == "encolado"


@pytest.mark.parametrize("code", [124, 1, 0])
def test_ambiguous_result_keeps_reservation_past_duplicate_window(queue_card, monkeypatch, code):
    calls = []

    def fake(*a, **kw):
        calls.append(1)
        return code, "", "resultado no correlacionado"

    monkeypatch.setattr(cq.subproc, "correr", fake)
    result = cq.enviar(queue_card, "same", esperar=0)
    assert result["estado"] == "sin_confirmacion" and "incierto" in result["motivo"]
    data = cq._load()
    data[result["envio_id"]]["at"] -= cq.DUPLICATE_S + 1
    cq._save(data)
    assert cq.enviar(queue_card, "same", esperar=0)["estado"] == "sin_confirmacion"
    assert len(calls) == 1


@pytest.mark.parametrize("text", ['"' * 20000, "🙂" * 20000], ids=["quotes", "astral"])
def test_windows_quoted_utf16_limit_sends_attachment(queue_card, monkeypatch, text):
    monkeypatch.setattr(cq.subproc, "WINDOWS", True)
    assert len(text) < cq.MAX_MESSAGE and not cq.message_fits(queue_card, text)
    monkeypatch.setattr(ses, "sessions", {SID: queue_card})
    monkeypatch.setattr(ses, "save_attachment", lambda sid, name, data: "C:/fixture/mensaje.md")
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **kw: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    sent = []

    def send(s, message):
        sent.append(message)
        assert cq.message_fits(s, message)
        return {"estado": "encolado", "envio_id": "bounded"}

    monkeypatch.setattr(cq, "enviar", send)
    assert ses.send_codex_queue(queue_card, text, [])[0] == 200
    assert "Adjunto: C:/fixture/mensaje.md" in sent[0] and text not in sent[0]


def test_unconfirmed_reservation_survives_history_pruning(queue_card, monkeypatch):
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: (124, "", "timeout"))
    result = cq.enviar(queue_card, "same", esperar=0)
    data = cq._load()
    data[result["envio_id"]]["at"] -= 90000
    cq._save(data)
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: pytest.fail("no reenvío tras poda"))
    assert cq.enviar(queue_card, "same", esperar=0)["estado"] == "sin_confirmacion"


def test_late_http_send_result_cannot_replace_newer_send(card, monkeypatch):
    def send(*a):
        card["envio_codex"] = {"envio_id": "newer", "estado": "entregado", "at": 20}
        card["last_prompt"] = "newer prompt"
        return {"envio_id": "older", "estado": "encolado", "at": 10}

    monkeypatch.setattr(cq, "enviar", send)
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **kw: None)
    assert ses.send_codex_queue(card, "older prompt", [])[0] == 200
    assert card["envio_codex"]["envio_id"] == "newer"
    assert card["last_prompt"] == "newer prompt"


@pytest.mark.parametrize("name,user_title", [(None, None), ("Sesión de prueba", None), ("Canal", "Mi título")])
def test_desktop_names_are_derived_from_validated_metadata_not_cwd(card, name, user_title):
    card.update(
        agent="claude",
        repo="scratch-temporal",
        cwd="C:/scratch-temporal",
        title=user_title or "scratch-viejo",
        title_source="user" if user_title else "prompt",
        external={"kind": "claude-desktop", "via": "registro", "desktop": True, "canal": name},
    )
    view = ses.public_session(card)
    assert view["repo"] == "Claude Desktop"
    assert view["title"] == (user_title or name or "Sesión de Claude Desktop")
    assert card["repo"] == "scratch-temporal" and card["title"] == (user_title or "scratch-viejo")
    cli = {**card, "external": None, "repo": "proyecto-real", "title": "Trabajo CLI"}
    assert ses.public_session(cli)["repo"] == "proyecto-real"
    assert ses.public_session(cli)["title"] == "Trabajo CLI"


@pytest.mark.parametrize("estado", ["sin_confirmacion", "pendiente", "encolado", "rechazado"])
@pytest.mark.parametrize("remote", [False, True])
def test_uncertain_copycat_never_transfers_or_stops_origin(card, monkeypatch, estado, remote):
    origin = {"session_id": "origin", "alive": True, "state": "corriendo", "coordinator": True, "title": "Trabajo"}
    monkeypatch.setattr(server, "registrar_envio", lambda sid, d: origin)
    monkeypatch.setattr(server, "hand_over", lambda *a, **k: pytest.fail("no transferir propiedad sin entrega"))
    monkeypatch.setattr(server, "accion_retarget", lambda *a, **k: pytest.fail("no mover conexiones"))
    monkeypatch.setattr(server, "atender_accion", lambda *a, **k: pytest.fail("no detener origen remoto"))
    result = {"estado": estado}
    if remote:
        server.remote_hand_over(SID, origin, {"copycat": True}, result)
    else:
        server.envio_del_tablero(SID, card, {"copycat": True}, result)
    assert "traspaso pendiente" in result["handover_error"]
    assert origin["alive"] and origin["state"] == "corriendo" and not origin.get("stopped_by") and origin["coordinator"]


def test_desktop_send_route_uses_capability_without_opening_other_actions(card, monkeypatch):
    card.update(external={"kind": "codex-desktop", "via": "rollout", "desktop": True}, no_console=True)
    monkeypatch.setattr(ses, "puede_enviar", lambda s: PLAN)
    monkeypatch.setattr(server, "_route_session", lambda sid: (card, None))
    monkeypatch.setattr(server, "registrar_envio", lambda *a: None)
    monkeypatch.setattr(server, "send_to_session", lambda *a: (200, {"estado": "encolado", "ok": True}))
    assert server.atender_accion("POST", SID, "send", {"text": "hola"}, desde_tablero=True)[0] == 200
    assert server.atender_accion("POST", SID, "interrupt", {}, desde_tablero=True)[0] == 409
