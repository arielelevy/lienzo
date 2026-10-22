"""El título se publica una vez y sólo cuando Claude está quieto."""

import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import native_follow


def session_api():
    return SimpleNamespace(
        lock=threading.RLock(), sessions={}, touch=lambda s: None, state=SimpleNamespace(log=lambda text: None)
    )


def test_deferred_once_and_new_title(monkeypatch):
    ses = session_api()
    card = {
        "session_id": "Y-native",
        "title_source": "user",
        "title": "lienzo - encargo Y - prueba",
        "agent": "claude",
        "state": "corriendo",
        "alive": True,
    }
    calls = []
    ses.en_hilo = lambda fn, *args: fn(*args)
    ses.nombrar_nativo = lambda s, n: calls.append(n) or (200, {"ok": True})
    monkeypatch.setitem(ses.sessions, card["session_id"], card)
    native_follow.schedule(ses, card)
    assert calls == []
    card["state"] = "termino"
    native_follow.schedule(ses, card)
    native_follow.schedule(ses, card)
    assert calls == ["lienzo-Y"]
    card["title"] = "lienzo - encargo Z - otra"
    native_follow.schedule(ses, card)
    assert calls == ["lienzo-Y", "lienzo-Z"]


def test_other_agents_dialogs_and_stopped_never_receive(monkeypatch):
    ses = session_api()
    calls = []
    ses.en_hilo = lambda *args: calls.append(args)
    for extra in (
        {"agent": "kiro"},
        {"agent": "coda"},
        {"agent": "codex"},
        {"title_source": "transcript"},
        {"external": {"kind": "batch"}},
        {"dialog": {"question": "Trust?"}},
        {"stopped_by": "x"},
        {"alive": False},
        {"state": "te_necesita"},
        {"typing": True},
    ):
        card = {
            "session_id": "Y",
            "title_source": "user",
            "title": "prueba",
            "agent": "claude",
            "alive": True,
            "state": "termino",
            **extra,
        }
        native_follow.schedule(ses, card)
    assert calls == []


def test_old_queued_name_does_not_overwrite_new_title():
    ses = session_api()
    jobs, calls = [], []
    ses.en_hilo = lambda fn, *args: jobs.append((fn, args))
    ses.nombrar_nativo = lambda s, n: calls.append(n) or (200, {})
    card = {
        "session_id": "Y",
        "agent": "claude",
        "title_source": "user",
        "alive": True,
        "state": "termino",
        "title": "lienzo - encargo Y - primero",
    }
    ses.sessions["Y"] = card
    native_follow.schedule(ses, card)
    card["title"] = "lienzo - encargo Z - segundo"
    fn, args = jobs.pop()
    fn(*args)
    assert calls == []
    native_follow.schedule(ses, card)
    fn, args = jobs.pop()
    fn(*args)
    assert calls == ["lienzo-Z"]


def test_failed_attempt_is_visible_and_not_repeated():
    ses = session_api()
    calls = []
    ses.en_hilo = lambda fn, *args: fn(*args)
    ses.nombrar_nativo = lambda s, n: calls.append(n) or (500, {"error": "consola inaccesible"})
    card = {
        "session_id": "Y",
        "agent": "claude",
        "title_source": "user",
        "alive": True,
        "state": "termino",
        "title": "lienzo - encargo Y - prueba",
    }
    ses.sessions["Y"] = card
    native_follow.schedule(ses, card)
    native_follow.schedule(ses, card)
    assert calls == ["lienzo-Y"]
    assert card["native_sync_error"] == "consola inaccesible"
    assert not card["_native_queued"]


def test_liveness_pass_calls_name_scheduler(monkeypatch):
    from lienzo import server

    ses = server.ses
    card = {"session_id": "Y", "agent": "claude", "state": "termino"}
    calls = []
    monkeypatch.setattr(ses, "sessions", {"Y": card})
    monkeypatch.setattr(ses, "check_liveness", lambda sid: None)
    monkeypatch.setattr(ses, "refresh_envios", lambda: None)
    monkeypatch.setattr(ses, "remember_live_cards", lambda: None)
    monkeypatch.setattr(native_follow, "schedule", lambda owner, s: calls.append((owner, s)))
    ses.liveness_pass(0)
    assert calls == [(ses, card)]


def test_manual_native_does_not_overlap_automatic():
    from lienzo import server

    ses = server.ses
    card = {"session_id": "Y", "agent": "claude", "state": "corriendo", "native_sync_busy": True}
    code, result = ses.nombrar_nativo(card, "Y")
    assert code == 409
    assert "se está actualizando" in result["error"]


def test_two_native_requests_are_serialized(monkeypatch):
    from lienzo import server

    ses = server.ses
    entered, release = threading.Event(), threading.Event()
    card = {"session_id": "Y"}
    calls, results = [], []

    def native(s, name, timeout):
        calls.append(name)
        entered.set()
        assert release.wait(3)
        return 200, {"ok": True}

    monkeypatch.setattr(ses, "_nombrar_nativo", native)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    worker = threading.Thread(target=lambda: results.append(ses.nombrar_nativo(card, "Y")))
    worker.start()
    try:
        assert entered.wait(3)
        code, _ = ses.nombrar_nativo(card, "Z")
        assert code == 409 and calls == ["Y"]
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert results == [(200, {"ok": True})]
    assert not card["native_sync_busy"]


def test_becoming_busy_between_dispatch_and_send_defers_instead_of_losing_name():
    ses = session_api()
    calls = []
    ses.en_hilo = lambda fn, *args: fn(*args)
    card = {
        "session_id": "Y",
        "agent": "claude",
        "title_source": "user",
        "alive": True,
        "state": "termino",
        "title": "lienzo - encargo Y - prueba",
    }
    ses.sessions["Y"] = card

    def rename(s, name):
        calls.append(name)
        if len(calls) == 1:
            card["state"] = "corriendo"
            return 409, {"code": "native_deferred", "error": "empezó un turno"}
        return 200, {"ok": True}

    ses.nombrar_nativo = rename
    native_follow.schedule(ses, card)
    native_follow.schedule(ses, card)
    assert calls == ["lienzo-Y"]
    card["state"] = "termino"
    native_follow.schedule(ses, card)
    native_follow.schedule(ses, card)
    assert calls == ["lienzo-Y", "lienzo-Y"]
    assert card["native_sync_error"] is None
