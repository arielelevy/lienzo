"""Readiness must preserve opt-in without waiting for a card or a background sweep."""

import json
import threading
import uuid
from types import SimpleNamespace

import claude_pipe_reconnect as rendezvous
import claude_pipe_runtime as runtime
import pytest


@pytest.fixture
def launch(monkeypatch):
    runtime.close_all()
    sid = str(uuid.uuid4())
    runtime.prepare_launch(sid)
    entry = runtime._entries[sid]
    closed = []

    class ProcessId:
        def __call__(self, handle):
            assert handle == 33
            return 77

    get_pid = ProcessId()
    monkeypatch.setattr(runtime, "kernel_api", lambda: SimpleNamespace(GetProcessId=get_pid))
    monkeypatch.setattr(
        runtime,
        "pin_ancestors",
        lambda pid, chosen: [22, 33] if (pid, chosen) == (99, sid) else pytest.fail("unexpected adapter"),
    )
    monkeypatch.setattr(runtime, "process_start", lambda kernel, handle: 88)
    close_handle = runtime.procinfo.close_handle

    def close(handle):
        if handle in (22, 33):
            closed.append(handle)
        else:
            close_handle(handle)

    monkeypatch.setattr(runtime.procinfo, "close_handle", close)
    monkeypatch.setattr(runtime, "_compatibility", lambda owner: None)
    yield sid, entry, closed
    runtime.close_all()


def test_first_poll_persists_before_ready_and_survives_immediate_restart(launch, monkeypatch):
    sid, entry, closed = launch
    assert entry["owner"] is None and not rendezvous.descriptor_path(sid).exists()
    assert entry["bridge"]._request("/poll", {"adapter_pid": 99}) == {}
    assert entry["bridge"].registered.is_set()
    row = json.loads(rendezvous.descriptor_path(sid).read_text())
    assert row["owner"] == [77, 88] and entry["owner"] == (77, 88)
    assert closed == [22, 33]
    runtime.close_all(restarting=True)
    monkeypatch.setattr(runtime, "_owner", lambda card: (77, 88))
    runtime.reap([{"session_id": sid, "agent": "claude", "alive": True, "pid": 77}])
    recovered = runtime._entries[sid]
    assert recovered is not entry and recovered["owner"] == (77, 88)
    assert json.loads(rendezvous.descriptor_path(sid).read_text())["public_id"] == recovered["bootstrap"].public_id


def test_failed_persistence_never_announces_ready(launch, monkeypatch):
    sid, entry, closed = launch

    def fail(*args):
        raise OSError("synthetic persistence failure")

    monkeypatch.setattr(rendezvous, "publish", fail)
    with pytest.raises(OSError, match="synthetic persistence failure"):
        entry["bridge"]._request("/poll", {"adapter_pid": 99})
    assert not entry["bridge"].registered.is_set() and entry["owner"] is None
    assert closed == [22, 33] and not rendezvous.descriptor_path(sid).exists()


def test_explicit_close_cannot_be_undone_by_first_poll(launch, monkeypatch):
    sid, entry, _ = launch
    publishing, release = threading.Event(), threading.Event()
    publish = rendezvous.publish

    def paused_publish(*args):
        publishing.set()
        assert release.wait(5)
        publish(*args)

    monkeypatch.setattr(rendezvous, "publish", paused_publish)
    errors = []

    def poll():
        try:
            entry["bridge"]._request("/poll", {"adapter_pid": 99})
        except BaseException as error:
            errors.append(error)

    polling = threading.Thread(target=poll)
    polling.start()
    assert publishing.wait(5)
    closing = threading.Thread(target=lambda: runtime.close(sid))
    closing.start()
    release.set()
    polling.join(5)
    closing.join(5)
    assert not polling.is_alive() and not closing.is_alive() and not errors
    assert sid not in runtime._entries and not rendezvous.descriptor_path(sid).exists()
