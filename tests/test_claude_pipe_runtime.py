"""Runtime contracts with explicit transport doubles; no real model or credential access."""

import json
import threading
import time
import uuid
from types import SimpleNamespace

import claude_pipe_runtime as runtime
import pytest

SID = "99ba9409-9b60-405b-a771-6d475e41f4e6"
REAL_REGISTRY = runtime.agentes.claude_registro


class Bridge:
    def __init__(self, sid):
        self.available = True
        self.calls = []
        self.closed = False
        self.registered = threading.Event()
        self.registered.set()
        self.last_poll = time.monotonic()
        self.handler = lambda text, key: {"id": key, "status": "pipe_written"}

    def send(self, text, key, timeout):
        self.calls.append((text, key))
        return self.handler(text, key)

    def close(self):
        self.closed = True
        self.available = False


class Bootstrap:
    def __init__(self, bridge, timeout):
        self.closed = False
        self.result = "listening"

    def hook_settings(self):
        return {"hooks": {"SessionStart": ["public-hook"]}}

    def command(self, powershell):
        return "public bootstrap command"

    def close(self):
        self.closed = True


@pytest.fixture
def card(tmp_path, monkeypatch):
    runtime.close_all()
    runtime._records.clear()
    runtime._latest.clear()
    monkeypatch.setattr(runtime, "ClaudePipeBridge", Bridge)
    monkeypatch.setattr(runtime, "ClaudePipeBootstrap", Bootstrap)
    monkeypatch.setattr(runtime.procs, "creation_filetime", lambda pid: 111)
    monkeypatch.setattr(runtime.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(
        runtime.agentes,
        "claude_registro",
        lambda pid, start: {"sessionId": SID, "version": "2.1.302", "peerProtocol": 1},
    )
    path = tmp_path / "transcript.jsonl"
    path.write_text("", encoding="utf-8")
    value = {
        "session_id": SID,
        "agent": "claude",
        "pid": 123,
        "alive": True,
        "external": {"kind": "claude-desktop"},
        "transcript_path": str(path),
    }
    yield value
    runtime.close_all()
    runtime._records.clear()
    runtime._latest.clear()


def peer(card, key, **changes):
    row = {"type": "user", "sessionId": SID, "origin": {"kind": "peer", "msg_id": key}, **changes}
    with open(card["transcript_path"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def test_launch_and_registration_only_return_public_settings(card):
    launched = runtime.prepare_launch(SID)
    assert set(launched) == {"session_id", "hook_settings", "expires_at"}
    registered = runtime.register(card)
    assert registered["command"] == "public bootstrap command"
    assert registered["connected"]
    assert runtime.availability(card) == {"puede": True, "motivo": None, "transporte": "claude_pipe"}


@pytest.mark.parametrize(
    "changes",
    [{"alive": False}, {"agent": "codex"}, {"external": {"kind": "orchestrator"}}, {"session_id": str(uuid.uuid4())}],
)
def test_unverified_owner_cannot_register(card, changes):
    with pytest.raises(ValueError, match="verificar"):
        runtime.register({**card, **changes})
    assert runtime._entries == {}


def test_owner_recycled_stopped_or_pending_cannot_send(card, monkeypatch):
    runtime.register(card)
    for changes in ({"stopped_by": "other"}, {"pending_id": "permission"}):
        assert not runtime.availability({**card, **changes})["puede"]
    monkeypatch.setattr(runtime.procs, "creation_filetime", lambda pid: 222)
    assert runtime.send(card, "hola")["estado"] == "rechazado"
    assert runtime._entries[SID]["bridge"].calls == []


def test_pipe_written_is_not_delivery_and_exact_peer_correlates(card):
    runtime.register(card)
    sent = runtime.send(card, "hola")
    assert sent["estado"] == "encolado"
    peer(card, sent["envio_id"], sessionId=str(uuid.uuid4()))
    peer(card, sent["envio_id"], origin={"kind": "typed", "msg_id": sent["envio_id"]})
    assert runtime.confirm(sent["envio_id"])["estado"] == "encolado"
    peer(card, sent["envio_id"])
    assert runtime.confirm(sent["envio_id"])["estado"] == "entregado"


def test_concurrent_duplicate_reserves_before_transport(card):
    runtime.register(card)
    bridge = runtime._entries[SID]["bridge"]
    entered, finish = threading.Event(), threading.Event()

    def handler(text, key):
        entered.set()
        assert finish.wait(3)
        return {"id": key, "status": "pipe_written"}

    bridge.handler = handler
    results = []
    worker = threading.Thread(target=lambda: results.append(runtime.send(card, "same")))
    worker.start()
    try:
        assert entered.wait(2)
        second = runtime.send(card, "same")
        assert second["estado"] == "pendiente"
        assert len(bridge.calls) == 1
    finally:
        finish.set()
        worker.join(3)
    assert results[0]["envio_id"] == second["envio_id"]


def test_unknown_expiry_never_rewrites_and_late_delivery_can_confirm(card):
    runtime.register(card)
    bridge = runtime._entries[SID]["bridge"]
    bridge.handler = lambda text, key: {"id": key, "status": "unknown"}
    result = runtime.send(card, "same")
    runtime._records[result["envio_id"]]["at"] -= runtime.CONFIRM_LIMIT_S + 1
    assert runtime.confirm(result["envio_id"])["estado"] == "sin_confirmacion"
    assert runtime.send(card, "same")["envio_id"] == result["envio_id"]
    assert len(bridge.calls) == 1
    peer(card, result["envio_id"])
    assert runtime.confirm(result["envio_id"])["estado"] == "entregado"


def test_delivered_repeat_window_and_explicit_id_conflict(card):
    runtime.register(card)
    first = runtime.send(card, "same")
    peer(card, first["envio_id"])
    runtime.confirm(first["envio_id"])
    assert runtime.send(card, "same")["envio_id"] == first["envio_id"]
    runtime._records[first["envio_id"]]["at"] -= runtime.REPEAT_AFTER_S + 1
    assert runtime.send(card, "same")["envio_id"] != first["envio_id"]
    with pytest.raises(ValueError, match="otro destino o texto"):
        runtime.send(card, "different", {"envio_id": first["envio_id"]})


def test_utf8_size_guard_does_not_write(card):
    runtime.register(card)
    assert runtime.send(card, "😀" * (runtime.MAX_TEXT // 4 + 1))["estado"] == "rechazado"
    assert runtime._entries[SID]["bridge"].calls == []


def test_reap_closes_recycled_owner_and_retains_pending_launch(card, monkeypatch):
    runtime.prepare_launch(SID)
    runtime.reap([])
    assert SID in runtime._entries
    runtime.register(card)
    entry = runtime._entries[SID]
    monkeypatch.setattr(runtime.procs, "creation_filetime", lambda pid: 222)
    runtime.reap([card])
    assert SID not in runtime._entries
    assert entry["bridge"].closed and entry["bootstrap"].closed


def test_transcript_error_is_visible_and_no_retry(card):
    runtime.register(card)
    result = runtime.send({**card, "transcript_path": None}, "hola")
    assert "no se pudo comprobar" in result["motivo"]
    assert len(runtime._entries[SID]["bridge"].calls) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"peerProtocol": True},
        {"peerProtocol": "1"},
        {"peerProtocol": 2},
        {"peerProtocol": None},
        {"version": None},
        {"version": 302},
        {"version": "2.1.302-beta"},
        {"version": "2.1.233"},
    ],
)
def test_unknown_protocol_or_version_rejects_registration_and_capability(card, monkeypatch, metadata):
    runtime.register(card)
    row = {"sessionId": SID, "version": "2.1.302", "peerProtocol": 1, **metadata}
    monkeypatch.setattr(runtime.agentes, "claude_registro", lambda pid, start: row)
    with pytest.raises(ValueError, match="protocolo|versión"):
        runtime.register(card)
    result = runtime.send(card, "hola")
    assert result["estado"] == "rechazado"
    assert runtime._entries[SID]["bridge"].calls == []


@pytest.mark.parametrize("version", ["2.1.234", "2.1.302", "2.1.303", "3.0.0"])
def test_minimum_version_and_protocol_are_guards_not_a_tested_version_whitelist(card, monkeypatch, version):
    monkeypatch.setattr(
        runtime.agentes, "claude_registro", lambda pid, start: {"sessionId": SID, "version": version, "peerProtocol": 1}
    )
    runtime.register(card)
    assert runtime.availability(card)["puede"]


def test_registry_exports_only_public_metadata(card, monkeypatch, tmp_path):
    registry = tmp_path / "sessions"
    registry.mkdir()
    row = {
        "pid": 123,
        "procStart": "111",
        "sessionId": SID,
        "version": "2.1.302",
        "peerProtocol": 1,
        "messagingSocketPath": "private",
        "secret": "never-export",
    }
    (registry / "123.json").write_text(json.dumps(row), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    result = REAL_REGISTRY(123, 111)
    assert result["version"] == "2.1.302" and result["peerProtocol"] == 1
    assert "secret" not in result and "messagingSocketPath" not in result
    assert REAL_REGISTRY(123, 222) is None


def test_failed_bootstrap_creation_closes_bridge(card, monkeypatch):
    bridges = []

    def bridge(sid):
        value = Bridge(sid)
        bridges.append(value)
        return value

    def fail(*args, **kwargs):
        raise OSError("bootstrap failure")

    monkeypatch.setattr(runtime, "ClaudePipeBridge", bridge)
    monkeypatch.setattr(runtime, "ClaudePipeBootstrap", fail)
    with pytest.raises(OSError, match="bootstrap failure"):
        runtime.prepare_launch(SID)
    assert bridges[0].closed and not runtime._entries


def test_finished_bootstrap_never_creates_second_writer_implicitly(card):
    runtime.register(card)
    entry = runtime._entries[SID]
    entry["bridge"].available = False
    entry["bootstrap"].closed = True
    entry["bootstrap"].result = "error"
    entry["bridge"].registered.clear()
    with pytest.raises(ValueError, match="bootstrap Claude finalizado"):
        runtime.register(card)
    assert runtime._entries[SID] is entry
    runtime.reap([card])
    assert entry["bridge"].closed and SID not in runtime._entries


def test_explicit_reconnect_replaces_failed_adapter_after_closing_it(card):
    runtime.register(card)
    old = runtime._entries[SID]
    old["bridge"].available = False
    old["bridge"].registered.clear()
    old["bootstrap"].closed = True
    old["bootstrap"].result = "error"
    result = runtime.register(card, reconnect=True)
    assert old["bridge"].closed
    assert runtime._entries[SID] is not old
    assert result["connected"] is True


def test_reconnect_keeps_healthy_adapter_and_delivery_history(card):
    runtime.register(card)
    entry = runtime._entries[SID]
    sent = runtime.send(card, "preservar historial")
    runtime.register(card, reconnect=True)
    assert runtime._entries[SID] is entry
    assert not entry["bridge"].closed
    assert runtime.confirm(sent["envio_id"])["estado"] == "encolado"


def test_reconnect_cannot_replace_a_different_process(card):
    runtime.register(card)
    entry = runtime._entries[SID]
    entry["bridge"].available = False
    entry["owner"] = (123, 999)
    with pytest.raises(ValueError, match="proceso de la sesión cambió"):
        runtime.register(card, reconnect=True)
    assert runtime._entries[SID] is entry and not entry["bridge"].closed


def test_reap_stale_snapshot_does_not_close_replacement(card, monkeypatch):
    runtime.register(card)
    old = runtime._entries[SID]
    old["expires_at"] = 0
    old["bridge"].available = False
    old["bridge"].last_poll -= runtime.HEARTBEAT_CLOSE_GRACE_S + 1
    real_close = runtime._close

    def replace_then_close(sid, expected=None):
        real_close(sid)
        runtime.register(card)
        real_close(sid, expected)

    monkeypatch.setattr(runtime, "_close", replace_then_close)
    try:
        runtime.reap([card])
    finally:
        monkeypatch.setattr(runtime, "_close", real_close)
    assert runtime._entries[SID] is not old
    assert not runtime._entries[SID]["bridge"].closed


def test_send_rechecks_owner_after_availability(card, monkeypatch):
    runtime.register(card)
    original = runtime.availability

    def replace_owner(value):
        result = original(value)
        monkeypatch.setattr(runtime.procs, "creation_filetime", lambda pid: 222)
        return result

    monkeypatch.setattr(runtime, "availability", replace_owner)
    assert runtime.send(card, "hola")["estado"] == "rechazado"
    assert not runtime._entries[SID]["bridge"].calls


@pytest.mark.parametrize("limit", ["MAX_RECORDS", "MAX_SESSION_RECORDS"])
def test_capacity_rejects_without_forgetting_uuid_or_writing(card, monkeypatch, limit):
    runtime.register(card)
    monkeypatch.setattr(runtime, limit, 1)
    first = runtime.send(card, "first")
    assert runtime.send(card, "second")["estado"] == "rechazado"
    assert runtime.send(card, "first")["envio_id"] == first["envio_id"]
    assert len(runtime._records) == len(runtime._latest) == 1
    assert len(runtime._entries[SID]["bridge"].calls) == 1


def test_entry_capacity_rejects_before_creating_listener(card, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_ENTRIES", 1)
    runtime.prepare_launch(SID)
    with pytest.raises(ValueError, match="límite de enlaces"):
        runtime.prepare_launch(str(uuid.uuid4()))
    assert len(runtime._entries) == 1


def test_utf8_exact_boundary_and_invalid_surrogate(card):
    runtime.register(card)
    assert runtime.send(card, "😀" * (runtime.MAX_TEXT // 4))["estado"] == "encolado"
    assert runtime.send(card, "\ud800")["estado"] == "rechazado"
    assert len(runtime._entries[SID]["bridge"].calls) == 1


def test_assistant_wrong_id_and_partial_transcript_never_confirm(card):
    runtime.register(card)
    result = runtime.send(card, "hola")
    peer(card, result["envio_id"], type="assistant")
    peer(card, str(uuid.uuid4()))
    peer(card, result["envio_id"], origin=["peer"])
    with open(card["transcript_path"], "a", encoding="utf-8") as stream:
        stream.write('{"type":"user"')
    assert runtime.confirm(result["envio_id"])["estado"] == "encolado"


def test_close_reserves_entry_until_listener_stops_and_rejects_send(card):
    runtime.register(card)
    entry = runtime._entries[SID]
    entered, finish = threading.Event(), threading.Event()

    def closing():
        entered.set()
        assert finish.wait(3)
        entry["bootstrap"].closed = True

    entry["bootstrap"].close = closing
    worker = threading.Thread(target=lambda: runtime.close(SID))
    worker.start()
    try:
        assert entered.wait(2)
        assert runtime._entries[SID] is entry
        assert runtime.send(card, "hola")["estado"] == "rechazado"
        assert not entry["bridge"].calls
    finally:
        finish.set()
        worker.join(3)
    assert not worker.is_alive()
    assert SID not in runtime._entries and entry["bridge"].closed


def test_late_transport_result_cannot_downgrade_transcript_delivery(card):
    runtime.register(card)
    bridge = runtime._entries[SID]["bridge"]

    def handler(text, key):
        peer(card, key)
        assert runtime.confirm(key)["estado"] == "entregado"
        return {"id": key, "status": "unknown"}

    bridge.handler = handler
    assert runtime.send(card, "hola")["estado"] == "entregado"
    assert len(bridge.calls) == 1


def test_close_all_attempts_other_entries_after_failure(card):
    runtime.register(card)
    entry = runtime._entries[SID]
    other = str(uuid.uuid4())
    runtime.prepare_launch(other)
    second = runtime._entries[other]
    original = entry["bootstrap"].close

    def fail():
        raise TimeoutError("listener still alive")

    entry["bootstrap"].close = fail
    try:
        with pytest.raises(ExceptionGroup, match="cerrar todos"):
            runtime.close_all()
        assert entry["bridge"].closed
        assert second["bootstrap"].closed and second["bridge"].closed
        assert SID in runtime._entries and other not in runtime._entries
        assert not runtime.availability(card)["puede"]
    finally:
        entry["bootstrap"].close = original


def test_concurrent_first_capability_cannot_rebind_another_process(card):
    runtime.prepare_launch(SID)
    bridge = runtime._entries[SID]["bridge"]
    first = True

    class RacingBridge(Bridge):
        @property
        def available(self):
            nonlocal first
            if first:
                first = False
                assert runtime.availability({**card, "pid": 456})["puede"]
            return not self.closed

    bridge.__class__ = RacingBridge
    try:
        assert not runtime.availability(card)["puede"]
        assert runtime._entries[SID]["owner"] == (456, 111)
    finally:
        # Restore the normal double before teardown assigns available = False.
        bridge.__class__ = Bridge


@pytest.mark.parametrize("registered_owner", [False, True])
def test_transferred_before_first_poll_preserves_launch_until_expiry(card, monkeypatch, registered_owner):
    runtime.prepare_launch(SID)
    entry = runtime._entries[SID]
    bridge = entry["bridge"]
    bridge.available = False
    bridge.registered.clear()
    bridge.last_poll = 0
    entry["bootstrap"].closed = True
    entry["bootstrap"].result = "transferred"
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time=lambda: entry["expires_at"] - 1, monotonic=lambda: 500))
    if registered_owner:
        assert not runtime.register(card)["connected"]
    runtime.reap([card] if registered_owner else [])
    assert runtime._entries[SID] is entry
    assert not bridge.closed and not runtime.availability(card)["puede"]
    assert runtime.send(card, "not yet")["estado"] == "rechazado"
    assert not bridge.calls


def test_transferred_without_first_poll_closes_at_launch_deadline(card, monkeypatch):
    runtime.prepare_launch(SID)
    entry = runtime._entries[SID]
    bridge = entry["bridge"]
    bridge.available = False
    bridge.registered.clear()
    entry["bootstrap"].closed = True
    entry["bootstrap"].result = "transferred"
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time=lambda: entry["expires_at"], monotonic=lambda: 500))
    runtime.reap([])
    assert SID not in runtime._entries and bridge.closed


@pytest.mark.parametrize("delay,closes", [(4, False), (29.999, False), (30, True), (31, True)])
def test_stale_heartbeat_hides_capability_but_closes_only_after_grace(card, monkeypatch, delay, closes):
    runtime.register(card)
    entry = runtime._entries[SID]
    bridge = entry["bridge"]
    bridge.available = False
    bridge.last_poll = 100
    entry["bootstrap"].closed = True
    entry["bootstrap"].result = "transferred"
    # Launch deadline has passed; after a first poll, only monotonic heartbeat age matters.
    monkeypatch.setattr(
        runtime, "time", SimpleNamespace(time=lambda: entry["expires_at"] + 1, monotonic=lambda: 100 + delay)
    )
    assert not runtime.availability(card)["puede"]
    assert runtime.send(card, "no replay")["estado"] == "rechazado"
    runtime.reap([card])
    assert (SID not in runtime._entries) == closes
    assert bridge.closed == closes
    assert not bridge.calls
    if not closes:
        assert not runtime.register(card)["connected"]
        # The same adapter resumes polling, without reconnecting or another bridge.
        bridge.last_poll = 100 + delay
        bridge.available = True
        runtime.reap([card])
        assert runtime._entries[SID] is entry and runtime.availability(card)["puede"]


@pytest.mark.parametrize("first_poll", [False, True])
def test_dead_owner_closes_immediately_even_before_heartbeat_grace(card, monkeypatch, first_poll):
    runtime.register(card)
    entry = runtime._entries[SID]
    entry["bridge"].available = False
    if not first_poll:
        entry["bridge"].registered.clear()
    entry["bootstrap"].closed = True
    entry["bootstrap"].result = "transferred"
    monkeypatch.setattr(runtime.procinfo, "alive", lambda pid: False)
    runtime.reap([card])
    assert SID not in runtime._entries
    assert entry["bridge"].closed and not entry["bridge"].calls
