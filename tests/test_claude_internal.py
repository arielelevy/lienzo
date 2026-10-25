"""Regresion del arbol daemon -> PTY -> conversaciones observado en Claude 2.1.310."""

import json

import pytest

from lienzo import procinfo, procs


@pytest.mark.parametrize("binary", ["claude.exe", "claude.exe.old.123"])
@pytest.mark.parametrize(
    "args",
    [
        'daemon run --origin transient --spawned-by "{}"',
        r"--bg-pty-host \\.\pipe\cc-daemon-pty-sid 138 25 -- claude.exe --session-id sid",
    ],
)
def test_helpers_excluded_from_sweep_liveness_and_typing(monkeypatch, binary, args):
    cmd = f"{binary} {args}"
    monkeypatch.setattr(procinfo, "image_path", lambda pid: binary)
    monkeypatch.setattr(procs, "image_path", lambda pid: binary)
    monkeypatch.setattr(procinfo, "command_line", lambda pid: cmd)
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    rows = [{"pid": 42, "exe": binary, "cmd": cmd, "parent": "claude.exe"}]
    monkeypatch.setattr(procs.subproc, "correr", lambda *a, **kw: (0, json.dumps(rows), ""))
    assert procinfo.agent_of(binary, cmd) is None
    assert procs.sweep() == []
    assert not procs.agent_alive(42)
    assert not procs.is_tui(42)


@pytest.mark.parametrize(
    "args",
    [
        "",
        '--session-id sid --agent claude --inherit-permission-mode auto -- "que falta"',
        "--session-id sid --agent claude",
        '-p "que falta"',
        '"explicar daemon y --bg-pty-host"',
        '-- "--bg-pty-host"',
        "--agent daemon",
        '--agent "--bg-pty-host"',
    ],
)
def test_real_conversations_and_batch_remain_agents(monkeypatch, args):
    monkeypatch.setattr(procinfo, "image_path", lambda pid: "claude.exe")
    monkeypatch.setattr(procinfo, "command_line", lambda pid: f"claude.exe {args}")
    assert procinfo.process_agent(42) == "claude"


def test_unreadable_claude_keeps_previous_liveness_policy(monkeypatch):
    monkeypatch.setattr(procinfo, "image_path", lambda pid: "claude.exe")
    monkeypatch.setattr(procinfo, "command_line", lambda pid: None)
    assert procinfo.process_agent(42) == "claude"
