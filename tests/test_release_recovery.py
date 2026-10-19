"""Release 0.4: synthetic owners/transports; never send to another live session."""

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import claude_pipe as pipe
import claude_pipe_adapter as adapter
import claude_pipe_bootstrap as bootstrap
import claude_pipe_reconnect as reconnect
import claude_pipe_runtime as runtime
import pytest
import rules
import rules_api
import sessions
import state


@pytest.fixture(autouse=True)
def isolated_sessions():
    state.sessions.clear()
    yield
    state.sessions.clear()


def rule(**changes):
    return {
        "id": "r",
        "from": "worker",
        "to": "coord",
        "kind": "on_stop",
        "text": "{respuesta}",
        "enabled": False,
        "repeat": True,
        "limit": "rate",
        "fired": 0,
        **changes,
    }


def test_recovered_same_id_does_not_enable_manual_or_exhausted_rule():
    parked = rule(
        parked_from="worker",
        parked_since=state.now(),
        parked_was_enabled=True,
        archived_at=state.now(),
        disabled_reason="origen muerto",
    )
    manual = rule(id="manual")
    exhausted = rule(id="exhausted", parked_to="coord", parked_since=state.now(), parked_was_enabled=False)
    state.rules.items[:] = [parked, manual, exhausted]
    state.sessions.update(worker={"alive": True}, coord={"alive": True})
    rules.reconciliar_cableado()
    assert parked["enabled"] and "parked_from" not in parked and "archived_at" not in parked
    assert not manual["enabled"] and not exhausted["enabled"]


@pytest.mark.parametrize("alive,expected", [(True, 200), (False, 409)])
def test_put_parked_enables_only_when_both_ends_live(alive, expected):
    parked = rule(parked_from="worker", parked_since=state.now(), parked_was_enabled=True)
    state.rules.items[:] = [parked]
    state.sessions.update(worker={"alive": alive}, coord={"alive": True})
    assert rules_api.edit_rule("r", {"enabled": True})[0] == expected
    assert parked["enabled"] is alive
    assert ("parked_from" in parked) is not alive


def test_orphan_archives_visibly_and_restorable_waits(monkeypatch):
    orphan = rule(enabled=True)
    waiting = rule(id="waiting", **{"from": "restorable"}, parked_from="restorable")
    state.rules.items[:] = [orphan, waiting]
    monkeypatch.setattr(sessions.restore, "restorables", lambda: [{"session_id": "restorable"}])
    rules.reconciliar_cableado()
    assert orphan["archived_at"] and not orphan["enabled"]
    assert orphan["disabled_reason"] == "origen muerto y no restaurable"
    assert "archived_at" not in waiting
    assert {r["id"] for r in state.rules.snapshot()} == {"r", "waiting"}
    orphan["parked_since"] = "2000-01-01T00:00:00+00:00"
    rules.purge_stale_xpc(lambda sid: False, lambda sid: False)
    assert orphan in state.rules.items
    state.sessions["worker"] = {"alive": True}
    rules.reconciliar_cableado()
    assert orphan["enabled"] and "archived_at" not in orphan


def test_manual_close_removes_opt_in_without_an_entry():
    sid = str(uuid.uuid4())
    path = reconnect.descriptor_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    runtime.close(sid)
    assert not path.exists()


def test_placeholder_claude_does_not_abort_reaper(monkeypatch):
    sid = str(uuid.uuid4())
    inspected = []
    original = reconnect.descriptor_path

    def inspect(chosen):
        inspected.append(chosen)
        return original(chosen)

    monkeypatch.setattr(reconnect, "descriptor_path", inspect)
    runtime.reap([{"session_id": "pid-123", "agent": "claude"}, {"session_id": sid, "agent": "claude"}])
    assert inspected == ["pid-123", sid]


@pytest.mark.parametrize("pending", [False, True])
def test_peer_http_delete_reports_pending_explicitly(monkeypatch, pending):
    import federation
    import server

    key = b"synthetic-pair-key-for-test-only!!"
    peer_id = uuid.uuid4().hex[:12]
    monkeypatch.setattr(server, "_peer_key", lambda chosen: key if chosen == peer_id else None)
    row = rule(informes=[{"estado": "pendiente", "respuesta": "informe"}] if pending else [])
    state.rules.items[:] = [row]
    instance = server.QuietServer(("127.0.0.1", 0), server.PeerHandler)
    thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        peer = federation.PeerConn(host="127.0.0.1", port=instance.server_port, key=key, self_pc_id=peer_id)
        status, body = federation.HTTPTransport().request(peer, "DELETE", "/peer/rules/r")
        assert status == (409 if pending else 200), body
        assert (row in state.rules.items) is pending
        if pending:
            assert "informes pendientes" in body["error"]
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(3)


def test_reconnect_rejects_other_owner_or_server_before_receiving(monkeypatch):
    sid = str(uuid.uuid4())
    stub = type("Bootstrap", (), {"public_id": str(uuid.uuid4()), "server_pid": 111, "server_start": 222})()
    reconnect.publish(sid, (1, 2), stub)
    monkeypatch.setattr(reconnect, "receive_environment", lambda *a: pytest.fail("must not read secrets"))
    with pytest.raises(ValueError, match="owner_changed"):
        reconnect.reconnect(sid, (1, 3), ("python", []))
    monkeypatch.setattr(reconnect, "server_identity", lambda *a: ("other", []))
    with pytest.raises(ValueError, match="server_changed"):
        reconnect.reconnect(sid, (1, 2), ("python", []))
    assert "SECRET" not in reconnect.descriptor_path(sid).read_text()


@pytest.mark.skipif(os.name != "nt", reason="pinned test process handle")
@pytest.mark.parametrize(
    "candidate",
    [
        {"LIENZO_CLAUDE_BRIDGE_URL": "http://example.invalid:1234", "LIENZO_CLAUDE_BRIDGE_SECRET": "new"},
        {"LIENZO_CLAUDE_BRIDGE_URL": "http://127.0.0.1:1234"},
        {"LIENZO_CLAUDE_BRIDGE_URL": "http://127.0.0.1:1234", "LIENZO_CLAUDE_BRIDGE_SECRET": None},
    ],
)
def test_malformed_reconnect_never_changes_url_or_leaks_previous_bearer(monkeypatch, candidate):
    import urllib.error
    from types import SimpleNamespace

    sid = str(uuid.uuid4())
    kernel = bootstrap.kernel_api()
    handle = reconnect.procinfo.open_process(os.getpid(), 0x101000)
    old_url = "http://127.0.0.1:23456"
    environment = {
        "LIENZO_CLAUDE_BRIDGE_SESSION": sid,
        "LIENZO_CLAUDE_BRIDGE_URL": old_url,
        "LIENZO_CLAUDE_BRIDGE_SECRET": "synthetic-old",
        "CLAUDE_CODE_MESSAGING_TOKEN": "synthetic-token",
        "CLAUDE_CODE_MESSAGING_SOCKET": "synthetic-socket",
        "LIENZO_CLAUDE_SERVER_PID": str(os.getpid()),
        "LIENZO_CLAUDE_SERVER_START": "1",
        "LIENZO_CLAUDE_RECONNECT_HOME": state.LIENZO,
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(adapter, "owner_handle", lambda chosen: (kernel, handle))
    monkeypatch.setattr(adapter, "pin_ancestors", lambda *a: [])
    monkeypatch.setattr(reconnect, "server_identity", lambda *a: ("synthetic", []))
    monkeypatch.setattr(reconnect, "reconnect", lambda *a: candidate)
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: None)
    requests = []

    def open_request(request, timeout):
        requests.append((request.full_url, request.get_header("Authorization")))
        if len(requests) == 2:
            raise RuntimeError("test_stop")
        raise urllib.error.URLError("synthetic disconnect")

    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=open_request))
    with pytest.raises(RuntimeError, match="test_stop"):
        adapter.run_adapter({"session_id": sid})
    assert requests == [(old_url + "/poll", "Bearer synthetic-old")] * 2


@pytest.mark.skipif(os.name != "nt", reason="real Windows named pipe and HTTP bridge")
@pytest.mark.parametrize("in_flight", [False, True], ids=["idle-poll", "uncertain-result"])
def test_adapter_survives_graceful_bridge_restart_without_replay(monkeypatch, in_flight):
    sid = str(uuid.uuid4())
    kernel = bootstrap.kernel_api()
    handle = reconnect.procinfo.open_process(os.getpid(), 0x101000)
    start = bootstrap.process_start(kernel, handle)
    monkeypatch.setattr(adapter, "owner_handle", lambda chosen: (kernel, handle))
    monkeypatch.setattr(adapter, "pin_ancestors", lambda *args: [])
    # This test process substitutes the Claude ancestor only at the bootstrap gate.
    monkeypatch.setattr(bootstrap, "verified_child", lambda pid, chosen: pid == os.getpid() and chosen == sid)
    first = pipe.ClaudePipeBridge(sid)
    second = pipe.ClaudePipeBridge(sid)
    wrote, release = threading.Event(), threading.Event()
    writes, errors = [], []

    def write(address, token, chosen, key, text):
        writes.append((key, text))
        wrote.set()
        assert release.wait(5)

    monkeypatch.setattr(adapter, "write_pipe", write)
    for key, value in first.environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "synthetic-test-socket")
    monkeypatch.setenv("LIENZO_CLAUDE_SERVER_PID", str(os.getpid()))
    monkeypatch.setenv("LIENZO_CLAUDE_SERVER_START", str(start))
    monkeypatch.setenv("LIENZO_CLAUDE_RECONNECT_HOME", state.LIENZO)

    def run():
        try:
            adapter.run_adapter({"session_id": sid})
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    listener = bootstrap.ClaudePipeBootstrap(second)
    thread.start()
    sender = None
    try:
        assert first.registered.wait(4)
        key = str(uuid.uuid4())
        if in_flight:
            sender = threading.Thread(target=lambda: first.send("informe incierto", key, timeout=3))
            sender.start()
            assert wrote.wait(4)
        first.resume = True
        first.close()  # real graceful HTTP shutdown while a job is in flight
        reconnect.publish(sid, (os.getpid(), start), listener)
        release.set()
        assert second.registered.wait(8), errors
        assert writes == ([(key, "informe incierto")] if in_flight else [])
        second.close()  # explicit close must stop, not reconnect
        thread.join(5)
        assert not thread.is_alive() and not errors
        row = json.loads(reconnect.descriptor_path(sid).read_text())
        assert set(row) == {"session_id", "owner", "public_id", "server_pid", "server_start"}
    finally:
        release.set()
        first.close()
        second.close()
        listener.close()
        thread.join(5)
        if sender:
            sender.join(5)


@pytest.mark.skipif(os.name != "nt", reason="real Windows process ancestry")
def test_registry_does_not_impersonate_a_real_python_process(tmp_path, monkeypatch):
    """El registro no convierte Python en Claude; se conserva el nombre real del binario."""
    sid = str(uuid.uuid4())
    registry = tmp_path / "claude" / "sessions"
    registry.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(registry.parent))
    owner = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        handle = reconnect.procinfo.open_process(owner.pid, 0x101000)
        assert handle
        try:
            start = bootstrap.process_start(bootstrap.kernel_api(), handle)
        finally:
            reconnect.procinfo.close_handle(handle)
        (registry / f"{owner.pid}.json").write_text(
            json.dumps({"pid": owner.pid, "procStart": str(start), "sessionId": sid}),
            encoding="utf-8",
        )
        assert reconnect.procinfo.alive(owner.pid)
        assert not bootstrap.verified_child(owner.pid, sid)
        assert Path(reconnect.procinfo.image_path(owner.pid)).name.lower().startswith("python")
    finally:
        owner.stdin.close()
        owner.terminate()
        owner.wait(timeout=5)
