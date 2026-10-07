import datetime as dt

import federation
import mirror
import protocol
import pytest
import sessions
import state


@pytest.mark.parametrize(
    "argv",
    [["cmd", "/c", "echo hi"], ["git", "push", "--force"], ["git", "push", "+main"], ["python", "-c", "print(1)"], []],
)
def test_remote_run_rejects_shell_and_force(argv):
    import remote_run

    assert not remote_run.permitted(argv)


def test_remote_run_is_denied_without_local_allowlist(monkeypatch, tmp_path):
    import remote_run

    monkeypatch.setattr(state, "load_config", lambda: {"launch_roots": [str(tmp_path)]})
    monkeypatch.setattr(remote_run.subproc, "correr", lambda *a, **k: pytest.fail("no debe ejecutar"))
    assert remote_run.run({"command": "status", "cwd": str(tmp_path)}, "peer")[0] == 403


def test_remote_run_executes_only_named_argv_and_valid_cwd(monkeypatch, tmp_path):
    import remote_run

    monkeypatch.setattr(
        state,
        "load_config",
        lambda: {"launch_roots": [str(tmp_path)], "run_allowlist": {"status": ["git", "status", "--short"]}},
    )
    calls = []
    monkeypatch.setattr(remote_run.subproc, "correr", lambda args, **kw: calls.append((args, kw)) or (0, "ok", ""))
    assert remote_run.run({"command": "status", "cwd": str(tmp_path.parent)}, "peer")[0] == 403
    assert remote_run.run({"command": "status", "cwd": str(tmp_path), "argv": ["calc"]}, "peer")[0] == 400
    assert not calls
    assert remote_run.run({"command": "status", "cwd": ""}, "peer")[0] == 400
    code, result = remote_run.run({"command": "status", "cwd": str(tmp_path)}, "peer")
    assert code == 200 and result["stdout"] == "ok"
    assert calls[0][0] == ["git", "status", "--short"]
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_kill_rejects_recycled_pid(monkeypatch):
    import kill_agent

    card = {
        "session_id": "target",
        "pid": 123,
        "agent": "codex",
        "started": "2026-10-07T00:00:00+00:00",
        "backend": "win32",
    }
    monkeypatch.setattr(kill_agent.procinfo, "open_process", lambda pid: "handle")
    closed = []
    monkeypatch.setattr(kill_agent.procinfo, "close_handle", closed.append)
    monkeypatch.setattr(kill_agent, "created_at", lambda h: state.parse_ts(card["started"]).timestamp() + 60)
    monkeypatch.setattr(kill_agent.subproc, "correr", lambda *a, **k: pytest.fail("PID reciclado"))
    assert kill_agent.close(card, "target")[0] == 409
    assert closed == ["handle"]


def test_kill_requires_confirmation_and_holds_handle_during_close(monkeypatch):
    import kill_agent

    card = {
        "session_id": "target",
        "pid": 123,
        "agent": "codex",
        "started": "2026-10-07T00:00:00+00:00",
        "backend": "win32",
    }
    events = []
    monkeypatch.setattr(kill_agent.procinfo, "open_process", lambda pid: events.append("open") or "handle")
    monkeypatch.setattr(kill_agent.procinfo, "close_handle", lambda h: events.append("close"))
    monkeypatch.setattr(kill_agent.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(kill_agent, "created_at", lambda h: state.parse_ts(card["started"]).timestamp() - 1)

    def terminate(argv, **kwargs):
        assert events == ["open"]
        assert argv == ["taskkill", "/PID", "123", "/T", "/F"]
        events.append("taskkill")
        return 0, "", ""

    monkeypatch.setattr(kill_agent.subproc, "correr", terminate)
    assert kill_agent.close(card, "wrong")[0] == 400
    assert events == []
    assert kill_agent.close(card, "target") == (200, {"ok": True})
    assert events == ["open", "taskkill", "close"]


def test_transport_close_does_not_retain_inflight_connection():
    transport = federation.HTTPTransport()
    peer = federation.PeerConn("localhost", 1, b"key", "local")

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    transport.close()
    transport._release(peer, connection, True)
    assert connection.closed
    assert transport._idle == []


def test_handover_failure_does_not_stop_origin_or_resend(monkeypatch):
    import server

    calls = []

    def action(method, sid, verb, data, **kw):
        calls.append((method, sid, verb))
        return 503, {"error": "peer desconectado"}

    monkeypatch.setattr(server, "atender_accion", action)
    result = {"ok": True}
    server.remote_hand_over("destination", {"session_id": "source", "title": "Trabajo"}, {}, result)
    assert result["ok"]
    assert result["handover_error"] == "peer desconectado"
    assert calls == [("PUT", "destination", "copycat")]


def test_unknown_coda_stop_does_not_invent_completion():
    import agentes

    assert agentes.perfil("coda").stop_is_final("turn_complete")
    assert not agentes.perfil("coda").stop_is_final("another_reason")


@pytest.mark.parametrize(
    "screen,cleared",
    [
        ({"ok": False}, False),
        ({"ok": True}, False),
        ({"ok": True, "area": {"input": "", "placeholder": True}}, True),
    ],
)
def test_old_terminal_permission_requires_visible_prompt(monkeypatch, screen, cleared):
    card = sessions.new_session("test", "claude", "hook")
    since = (dt.datetime.now().astimezone() - dt.timedelta(minutes=10)).isoformat()
    card.update(
        pid=42, alive=True, state="te_necesita", needs={"kind": "permission", "where": "terminal", "since": since}
    )
    monkeypatch.setattr(sessions, "sessions", {"test": card})
    monkeypatch.setattr(sessions, "read_screen", lambda s: screen)
    monkeypatch.setattr(sessions, "touch", lambda s: None)
    sessions.screen_once()
    assert (card["state"] == "termino") is cleared


def test_contract_only_publishes_roots_and_capabilities(monkeypatch):
    monkeypatch.setattr(state, "load_config", lambda: {"launch_roots": ["D:/Apps", None], "secret": "private"})
    info = protocol.info()
    assert info["launch_roots"] == ["D:/Apps"]
    assert "rules.create" in info["capabilities"]
    assert "secret" not in info


def test_snapshot_reconciles_without_waiting_for_a_failed_send():
    board = mirror.Mirror()
    pm = mirror._PeerMirror("remote", {}, federation.PeerConn("localhost", 1, b"key", "local"))
    board._peers["remote"] = pm
    board._apply_event(pm, {"type": "snapshot", "sessions": [{"session_id": "old"}]})
    calls = []
    board.on_snapshot = lambda pc, ids: calls.append((pc, ids))

    class Transport:
        def request(self, *args):
            return 200, {"sessions": [{"session_id": "new"}]}

    board.transport = Transport()
    board._poll_snapshot(pm)
    assert board.owner_of("old") is None
    assert board.owner_of("new") == "remote"
    assert calls == [("remote", {"new"})]


def test_snapshot_in_flight_does_not_replace_newer_sse():
    board = mirror.Mirror()
    pm = mirror._PeerMirror("remote", {}, federation.PeerConn("localhost", 1, b"key", "local"))
    board._peers["remote"] = pm

    class Transport:
        def request(self, *args):
            board._apply_event(pm, {"type": "session", "session": {"session_id": "new"}})
            return 200, {"sessions": []}

    board.transport = Transport()
    board._poll_snapshot(pm)
    assert board.owner_of("new") == "remote"


def test_rule_reconciliation_only_affects_its_peer(monkeypatch):
    import rules

    entries = [
        {"id": "a", "to": "gone-a", "to_pc": "a", "xpc": True, "enabled": True},
        {"id": "b", "to": "gone-b", "to_pc": "b", "xpc": True, "enabled": True},
    ]
    monkeypatch.setattr(state.rules, "items", entries)
    monkeypatch.setattr(state.rules, "save", lambda: None)
    assert rules.purge_stale_xpc(lambda sid: False, lambda sid: False, peer_id="a") == 1
    assert entries[0]["parked_to"] == "gone-a"
    assert entries[1]["enabled"]
    assert "parked_to" not in entries[1]
