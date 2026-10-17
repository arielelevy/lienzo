import sys
import time

import optimization_research_runner as runner
import pytest
import subproc

FLOOD = "import sys\nwhile True:\n    sys.stdout.write('y' * 1000)\n    sys.stdout.flush()"
BURST = "import sys, time\nsys.stdout.write('x' * 5_000_000)\nsys.stdout.flush()\ntime.sleep(60)"
BOTH = (
    "import sys, time\nsys.stdout.write('o' * 600)\nsys.stdout.flush()\n"
    "sys.stderr.write('e' * 600)\nsys.stderr.flush()\ntime.sleep(60)"
)


def run_code(code, *, max_output, timeout=60):
    return runner.run(
        [sys.executable, "-c", code],
        stdin_text="abc",
        cwd=None,
        timeout=timeout,
        should_stop=lambda: None,
        max_output=max_output,
    )


def test_missing_program_does_not_raise():
    result = runner.run(
        ["no-existe-lienzo-xyz"], stdin_text="", cwd=None, timeout=5, should_stop=lambda: None, max_output=100
    )
    assert result["code"] == subproc.NO_ARRANCO and result["pid"] is None


def test_output_under_limit_is_complete():
    result = run_code("import sys; print(sys.stdin.read() * 5)", max_output=1000)
    assert result["code"] == 0 and result["stdout"].strip() == "abc" * 5 and not result["output_exceeded"]


def test_fast_burst_over_limit_kills_own_tree_and_keeps_only_limit():
    started = time.monotonic()
    result = run_code(BURST, max_output=10_000)
    assert result["output_exceeded"] and not result["timed_out"] and time.monotonic() - started < 15
    assert len(result["stdout"]) == 10_000 and "salida mayor a 10000 bytes" in result["stderr"]


def test_process_that_keeps_emitting_is_stopped_before_timeout():
    started = time.monotonic()
    result = run_code(FLOOD, max_output=50_000)
    assert result["output_exceeded"] and not result["timed_out"] and time.monotonic() - started < 15
    assert set(result["stdout"]) == {"y"} and len(result["stdout"]) == 50_000


def test_stdout_and_stderr_share_one_limit():
    result = run_code(BOTH, max_output=1000)
    stderr = result["stderr"].split("\nsalida mayor")[0]
    assert result["output_exceeded"] and len(result["stdout"]) + len(stderr) == 1000


def test_quick_exit_over_limit_is_still_flagged():
    result = run_code("print('z' * 150)", max_output=30)
    assert result["output_exceeded"] and result["stdout"] == "z" * 30


def test_stop_reason_kills_tree_quickly():
    calls = []
    started = time.monotonic()
    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin_text="",
        cwd=None,
        timeout=60,
        should_stop=lambda: calls.append(1) or ("pausa" if len(calls) > 1 else None),
        max_output=100,
        poll=0.1,
    )
    assert result["stopped"] == "pausa" and not result["timed_out"] and time.monotonic() - started < 15


def test_own_error_in_callback_still_kills_child(monkeypatch):
    killed = []
    real = subproc._matar_arbol
    monkeypatch.setattr(subproc, "_matar_arbol", lambda p: killed.append(p.pid) or real(p))

    def boom(_pid):
        raise RuntimeError("persistencia caída")

    with pytest.raises(RuntimeError):
        runner.run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin_text="",
            cwd=None,
            timeout=60,
            should_stop=lambda: None,
            max_output=100,
            on_start=boom,
        )
    assert len(killed) == 1
