"""Reloj y procesos controlados: nunca actualiza instalaciones reales durante las pruebas."""

import threading
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

# Importar server primero instala lienzo/ en sys.path, igual que test_launch.py.
# ruff: noqa: I001
from lienzo import server  # noqa: F401
import harness_updates as hu
import launch


def setup_updater(monkeypatch, rc=0):
    clock = [100.0]
    calls = []
    monkeypatch.setattr(hu.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(hu.state, "log", lambda message: None)

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return rc, "current", "network unavailable" if rc else ""

    monkeypatch.setattr(hu.subproc, "correr", run)
    monkeypatch.setattr(hu, "latest_version", lambda agent: None)
    return hu.Updater(), clock, calls


def test_codex_up_to_date_skips_reinstall(monkeypatch):
    updater, clock, calls = setup_updater(monkeypatch)
    monkeypatch.setattr(hu, "latest_version", lambda agent: "0.162.1")
    monkeypatch.setattr(hu.subproc, "correr", lambda argv, **k: (calls.append(argv), (0, "codex-cli 0.162.1", ""))[1])
    assert updater.ensure("codex", "/bin/codex") is None
    assert calls == [["/bin/codex", "--version"]]
    clock[0] += hu.INTERVAL_S - 1
    updater.ensure("codex", "/bin/codex")
    assert len(calls) == 1


def test_codex_newer_than_npm_counts_as_current(monkeypatch):
    updater, _, calls = setup_updater(monkeypatch)
    monkeypatch.setattr(hu, "latest_version", lambda agent: "0.162.0")
    monkeypatch.setattr(hu.subproc, "correr", lambda argv, **k: (calls.append(argv), (0, "codex-cli 0.162.1", ""))[1])
    assert updater.ensure("codex", "/bin/codex") is None
    assert calls == [["/bin/codex", "--version"]]


def test_codex_registry_failure_falls_back_to_update(monkeypatch):
    updater, _, calls = setup_updater(monkeypatch)

    def offline(agent):
        raise OSError("sin red")

    monkeypatch.setattr(hu, "latest_version", offline)
    updater.ensure("codex", "/bin/codex")
    assert calls[-1][0] == ["/bin/codex", "update"]


def test_codex_outdated_runs_update(monkeypatch):
    updater, _, calls = setup_updater(monkeypatch)
    monkeypatch.setattr(hu, "latest_version", lambda agent: "0.163.0")
    monkeypatch.setattr(hu.subproc, "correr", lambda argv, **k: (calls.append(argv), (0, "codex-cli 0.162.1", ""))[1])
    updater.ensure("codex", "/bin/codex")
    assert calls == [["/bin/codex", "--version"], ["/bin/codex", "update"]]


def test_startup_and_six_hour_boundary(monkeypatch):
    updater, clock, calls = setup_updater(monkeypatch)
    updater.cycle(lambda agent: "/bin/" + agent)
    assert len(calls) == len(hu.COMMANDS)
    clock[0] += hu.INTERVAL_S - 1
    updater.cycle(lambda agent: "/bin/" + agent)
    assert len(calls) == len(hu.COMMANDS)
    clock[0] += 1
    updater.ensure("claude", "/bin/claude")
    assert len(calls) == len(hu.COMMANDS) + 1
    assert calls[-1][0][-1] == "update"


def test_failure_retry_and_visible_warning(monkeypatch):
    updater, clock, calls = setup_updater(monkeypatch, rc=124)
    error = updater.ensure("codex", "/bin/codex")
    assert "124" in error and "network unavailable" in error
    assert calls[0][1]["timeout"] == hu.TIMEOUT_S
    assert updater.ensure("codex", "/bin/codex") == error
    assert len(calls) == 1
    clock[0] += hu.RETRY_S
    updater.ensure("codex", "/bin/codex")
    assert len(calls) == 2


def test_concurrent_launches_share_check(monkeypatch):
    updater, _, calls = setup_updater(monkeypatch)
    barrier = threading.Barrier(4)

    def ensure(_):
        barrier.wait()
        return updater.ensure("claude", "/bin/claude")

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(ensure, range(4))) == [None] * 4
    assert len(calls) == 1


def test_wsl_separate_from_windows_and_remains_periodic(monkeypatch):
    updater, clock, calls = setup_updater(monkeypatch)
    monkeypatch.setattr(hu.sys, "platform", "win32")
    updater.ensure("codex", "C:/bin/codex.exe")
    updater.ensure("codex", "codex", "Ubuntu")
    assert calls[-1][0] == ["wsl.exe", "-d", "Ubuntu", "--exec", "codex", "update"]
    clock[0] += hu.INTERVAL_S
    updater.cycle(lambda agent: None)
    assert len(calls) == 3
    assert "Ubuntu" in calls[-1][0]


def test_cmd_path_rejects_expansion(monkeypatch):
    updater, _, calls = setup_updater(monkeypatch)
    monkeypatch.setattr(hu.sys, "platform", "win32")
    assert "insegura" in updater.ensure("pi", "C:/%EVIL%/pi.cmd")
    assert not calls
    monkeypatch.setenv("COMSPEC", "C:/Windows/System32/cmd.exe")
    argv = hu.command("C:/Program Files/pi.cmd", "pi", None)
    assert argv.endswith('""C:/Program Files/pi.cmd" update --self --no-approve"')


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe es de Windows")
def test_real_cmd_with_spaces(tmp_path):
    probe = tmp_path / "probe with spaces.cmd"
    probe.write_text("@echo off\necho HELPER_OK\n", encoding="ascii")
    rc, out, err = hu.subproc.correr(hu.command(str(probe), "pi", None), timeout=10)
    assert rc == 0, err
    assert "HELPER_OK" in out


def test_launch_checks_before_spawning_and_exposes_failure(monkeypatch):
    events = []
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(launch, "_cwd_allowed", lambda *args: True)
    monkeypatch.setattr(launch, "_allowed_roots", list)
    monkeypatch.setattr(launch, "_exe_path", lambda name: "C:/bin/claude.exe")

    def check(*args):
        events.append("check")
        return "sin red"

    def spawn(*args):
        events.append("spawn")
        return {"ok": True}

    monkeypatch.setattr(hu, "before_launch", check)
    monkeypatch.setattr(launch, "_launch_cmd", spawn)
    result = launch.launch("D:/Repos/demo", "demo", "claude", resume="last")
    assert events == ["check", "spawn"]
    assert result["ok"] and result["aviso"] == "sin red"
