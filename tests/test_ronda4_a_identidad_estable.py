"""Identidad estable durante lectura de cabecera; sin procesos ni cuentas reales."""
import json

import codex_identity as identity
import pytest

THREAD = "01a14774-aa3f-7062-b3f3-aa996a33ff35"


@pytest.fixture
def header(tmp_path, monkeypatch):
    path = tmp_path / "rollout-fixture.jsonl"
    monkeypatch.setattr(identity.procinfo, "_WIN", True)
    monkeypatch.setattr(identity.procinfo, "process_agent", lambda pid: "codex")

    def write(thread=THREAD):
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": thread, "originator": "codex-tui"}}) + "\n", encoding="utf-8")
        return str(path)

    write()
    return write


@pytest.mark.parametrize("thread", ["inventado", "../otra-sesion", THREAD.upper()])
def test_invalid_thread_never_becomes_verified_identity(header, monkeypatch, thread):
    path = header(thread)
    monkeypatch.setattr(identity, "_snapshot", lambda pid: (123, {path}))
    result = identity.probe(4242)
    assert result["verified"] is False
    assert "id de hilo" in result["reason"]


@pytest.mark.parametrize("change", ["rollout", "process", "ambiguous", "unavailable"])
def test_change_during_header_read_rejects_identity(header, monkeypatch, change):
    path = header()
    calls = []

    def snapshot(pid):
        calls.append(pid)
        if len(calls) == 1:
            return 123, {path}
        if change == "unavailable":
            raise OSError("proceso inaccesible")
        return (124 if change == "process" else 123,
                {"otro-rollout"} if change == "rollout" else
                {path, "otro-rollout"} if change == "ambiguous" else {path})

    monkeypatch.setattr(identity, "_snapshot", snapshot)
    result = identity.probe(4242)
    assert result["verified"] is False
    assert len(calls) == 2


def test_stable_identity_keeps_both_snapshots_intact(header, monkeypatch):
    path = header()
    paths = {path}
    calls = []
    monkeypatch.setattr(identity, "_snapshot", lambda pid: calls.append(pid) or (123, paths))
    assert identity.probe(4242) == {
        "verified": True, "pid": 4242, "process_start": 123, "thread": THREAD, "path": path}
    assert calls == [4242, 4242]
    assert paths == {path}
