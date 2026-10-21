"""Real child processes; no Claude session, credentials or running server touched."""

import subprocess
import sys

import claude_pipe_adapter as adapter
import pytest


@pytest.mark.parametrize("outcome", ["ready", "exit", "timeout"])
def test_child_start_requires_authenticated_readiness(tmp_path, monkeypatch, outcome):
    script = tmp_path / "child.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdin.read()\n"
        + {
            "ready": "print('claude_pipe_adapter_ready', flush=True)\n",
            "exit": "sys.exit(2)\n",
            "timeout": "time.sleep(30)\n",
        }[outcome],
        encoding="utf-8",
    )
    monkeypatch.setattr(adapter, "__file__", str(script))
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    if outcome == "ready":
        adapter.launch_adapter({"session_id": "fixture"})
        assert children[0].wait(timeout=5) == 0
    else:
        with pytest.raises((ValueError, TimeoutError), match="adapter_start_"):
            adapter.launch_adapter({"session_id": "fixture"}, timeout=0.2)
        assert children[0].poll() is not None
    assert children[0].stdin.closed and children[0].stdout.closed


def test_bootstrap_missing_claude_channel_fails_before_consuming_command(monkeypatch, capsys):
    monkeypatch.delenv("CLAUDE_CODE_MESSAGING_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
    monkeypatch.setattr(sys, "argv", ["adapter", "--bootstrap", "public", "session", "1", "2"])
    assert adapter.cli() == 2
    assert "no heredó el canal de Claude" in capsys.readouterr().err


def test_ready_only_after_successful_poll(monkeypatch, capsys):
    class Kernel:
        def __init__(self):
            self.WaitForSingleObject = lambda *args: 258
            self.CloseHandle = lambda *args: None

    class Response:
        def __enter__(self):
            import io

            return io.StringIO("{}")

        def __exit__(self, *args):
            return False

    class Opener:
        calls = 0

        def open(self, request, timeout):
            self.calls += 1
            if self.calls == 2:
                raise OSError("connection_lost")
            return Response()

    for key, value in {
        "LIENZO_CLAUDE_BRIDGE_SESSION": "fixture",
        "LIENZO_CLAUDE_BRIDGE_URL": "http://127.0.0.1:1",
        "LIENZO_CLAUDE_BRIDGE_SECRET": "synthetic",
        "CLAUDE_CODE_MESSAGING_TOKEN": "synthetic",
        "CLAUDE_CODE_MESSAGING_SOCKET": "synthetic",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(adapter, "owner_handle", lambda sid: (Kernel(), 1))
    monkeypatch.setattr(adapter, "pin_ancestors", lambda *args: [])
    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(OSError, match="connection_lost"):
        adapter.run_adapter({"session_id": "fixture"})
    assert capsys.readouterr().out == "claude_pipe_adapter_ready\n"
