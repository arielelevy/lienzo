"""Asociación automática con el UUID publicado por la TUI, sin queue."""

import json

import codex_status as status
import pytest
import sessions as ses

SID = "01a15006-3510-7343-b379-ea69964d4ea5"
OTHER = "01a15038-1ced-7163-8c63-1f6c1fb937bf"


def snapshot(prompt="› Ask Codex to do anything", prefix=()):
    return {"ok": True, "lines": [*prefix, "", prompt, "", "  GPT-6.1-Sol low · D:/apps/lienzo", "  ? for shortcuts"]}


def block(sid=SID):
    return ["/status", "  >_ OpenAI Codex (v0.163.0)", "  Model: GPT-6.1-Sol",
            "  Directory: D:/apps/lienzo", "  Permissions: Workspace", f"  Session: {sid}"]


@pytest.mark.parametrize("prompt,prefix", [
    ("› no borres este borrador", ()), ("›", ("• Working (2s • esc to interrupt)",)),
    ("›", ("• Queued follow-up inputs",)), ("›", ("Waiting for approval",)),
])
def test_drafts_busy_and_queued_input_never_allow_status(prompt, prefix):
    assert not status.idle(snapshot(prompt, prefix))


def test_idle_requires_known_footer_and_exact_empty_box():
    assert status.idle(snapshot())
    assert status.idle(snapshot("›"))
    assert not status.idle({"ok": False, "lines": snapshot()["lines"]})
    assert not status.idle({"ok": True, "lines": ["›", "texto multilínea", "GPT", "? for shortcuts"]})


def test_only_latest_complete_status_block_identifies_session():
    assert status.session_from_status(block() + block(OTHER)) == OTHER
    assert status.session_from_status(block() + ["/status", "  Session: " + OTHER]) is None
    assert status.session_from_status(block() + ["  Session: " + OTHER]) is None
    assert status.session_from_status(["  Session: " + SID]) is None


@pytest.fixture
def console(monkeypatch):
    import screen
    import send

    monkeypatch.setattr(status.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(status.procs, "creation_filetime", lambda pid: 123)
    monkeypatch.setattr(status.time, "sleep", lambda _: None)
    screens = [snapshot(), snapshot(), snapshot(prefix=block())]
    monkeypatch.setattr(screen, "read_screen", lambda pid: screens.pop(0))
    sent = []
    monkeypatch.setattr(send, "inject", lambda *a, **kw: sent.append((a, kw)) or {"ok": True})
    return screens, sent


def test_query_reads_actual_tui_uuid_and_pins_process(console):
    _, sent = console
    assert status.query_console(4242, 123) == SID
    assert sent == [((4242, "/status"), {"expected_start": 123})]


def test_typing_between_snapshots_prevents_injection(console):
    screens, sent = console
    screens[1] = snapshot("› borrador nuevo")
    assert status.query_console(4242, 123) is None
    assert sent == []


def test_recycled_pid_prevents_injection(console):
    _, sent = console
    assert status.query_console(4242, 124) is None
    assert sent == []


@pytest.fixture
def store(tmp_path):
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / f"rollout-{SID}.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": SID, "originator": "codex-tui"}}), encoding="utf-8")
    return home, path


def test_uuid_resolves_exact_rollout_without_requiring_a_database(store):
    home, path = store
    assert status.rollout(SID, home) == str(path)
    assert status.rollout(OTHER, home) is None


def test_duplicate_files_for_one_uuid_are_ambiguous(store):
    home, path = store
    path.with_name(f"rollout-copy-{SID}.jsonl").write_bytes(path.read_bytes())
    assert status.rollout(SID, home) is None


def test_two_terminals_in_one_folder_keep_separate_threads(monkeypatch):
    from types import SimpleNamespace

    status._cache.clear()
    monkeypatch.setattr(status.procinfo, "_WIN", True)
    monkeypatch.setattr(status.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(status.procs, "creation_filetime", lambda pid: pid * 100)
    monkeypatch.setattr(status, "rollout", lambda sid: f"rollout-{sid}.jsonl")
    def run(argv, **kwargs):
        pid = int(argv[argv.index("--pid") + 1])
        return SimpleNamespace(returncode=0, stdout=json.dumps({"thread": SID if pid == 42 else OTHER}))
    monkeypatch.setattr(status.subprocess, "run", run)
    assert status.discover(42)["thread"] == SID
    assert status.discover(43)["thread"] == OTHER
    assert status.discover(42)["verified"] is False
    status._cache.clear()


@pytest.mark.parametrize("thread", [SID, None])
def test_status_only_once_until_manual_scan_or_new_process(monkeypatch, thread):
    from types import SimpleNamespace

    status._cache.clear()
    status._running.clear()
    clock = [0]
    start = [123]
    calls = []
    monkeypatch.setattr(status.procinfo, "_WIN", True)
    monkeypatch.setattr(status.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(status.procs, "creation_filetime", lambda pid: start[0])
    monkeypatch.setattr(status.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(status, "rollout", lambda sid: "rollout.jsonl")
    monkeypatch.setattr(status.subprocess, "run", lambda *a, **kw:
                        calls.append(a) or SimpleNamespace(returncode=0, stdout=json.dumps({"thread": thread})))
    try:
        status.discover(42)
        for tick in (11, 61, 301, 3600):
            clock[0] = tick
            status.discover(42)
        assert len(calls) == 1
        status.request_scan()
        status.discover(42)
        assert len(calls) == 2
        start[0] = 456
        status.discover(42)
        assert len(calls) == 3
    finally:
        status._cache.clear()
        status._running.clear()


def test_manual_scan_does_not_duplicate_running_query():
    key = (42, 123)
    status._cache[key] = (0, None)
    status._running.add(key)
    try:
        status.request_scan()
        assert key in status._cache
    finally:
        status._cache.clear()
        status._running.clear()


@pytest.mark.parametrize("payload", [{"id": OTHER, "originator": "codex-tui"},
                                     {"id": SID, "originator": "codex_exec"}])
def test_wrong_thread_or_headless_file_rejected(store, payload):
    home, path = store
    path.write_text(json.dumps({"type": "session_meta", "payload": payload}), encoding="utf-8")
    assert status.rollout(SID, home) is None


def test_hook_card_and_console_merge_without_losing_receipt(monkeypatch):
    provisional = ses.new_session("pid-4242", "codex", "sweep")
    provisional.update(pid=4242, alive=True, agent_exe="codex.exe",
                       envio_codex={"estado": "sin_confirmacion", "transporte": "tecleo", "at": 1})
    target = ses.new_session(SID, "codex", "hook")
    target.update(hooked=True, transcript_path="rollout.jsonl", pending_id="permission",
                  needs={"kind": "permission"})
    cards = {provisional["session_id"]: provisional, SID: target}
    monkeypatch.setattr(ses, "sessions", cards)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses, "repoint_refs", lambda *a: (0, 0))
    monkeypatch.setattr(ses, "drop_session", lambda sid, reason: cards.pop(sid))
    monkeypatch.setattr(ses.backend, "is_tui", lambda s: True)
    monkeypatch.setattr(ses.backend, "external_origin", lambda ev: None)
    monkeypatch.setattr(ses, "apply_repo", lambda *a: None)
    monkeypatch.setattr(ses, "refresh_from_transcript", lambda s: None)
    monkeypatch.setattr(ses.codex_identity, "transcript_identity", lambda pid: {
        "verified": False, "observed": True, "thread": SID, "path": "rollout.jsonl",
        "process_start": 123, "reason": "/status"})
    ses.attach_transcript(provisional, (SID, "rollout.jsonl"))
    assert list(cards) == [SID]
    assert target["pid"] == 4242 and target["codex_console_start"] == 123
    assert target["envio_codex"] == provisional["envio_codex"]
    assert target["pending_id"] == "permission" and target["needs"]["kind"] == "permission"
    assert "codex_process_start" not in target
