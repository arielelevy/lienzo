"""V-3: la identidad del bloqueo se consulta en la PC dueña, sin títulos ni entrada."""

import browser_stream as stream
import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(
        stream,
        "_native_windows",
        lambda window: [
            {"id": "202", "pid": 42, "bounds": {"left": 100, "top": 0, "width": 800, "height": 600}},
        ],
    )
    instance = stream.Worker.__new__(stream.Worker)
    instance.window = "202"
    return instance


def test_lock_uses_native_pid_and_bounds_and_returns_checked_target(worker, monkeypatch):
    calls = []
    target = {"id": "target-2", "context": "profile-2", "window": "202", "windowId": 2}

    def request(data):
        calls.append(data)
        return 200, {"activeTarget": target}

    monkeypatch.setattr(stream.browser_remote, "request", request)
    assert worker._active_target() == {"activeTarget": target}
    assert calls == [
        {
            "action": "resolve-window",
            "window": "202",
            "nativeWindows": [
                {"id": "202", "pid": 42, "bounds": {"left": 100, "top": 0, "width": 800, "height": 600}},
            ],
        }
    ]


@pytest.mark.parametrize("code", [409, 503, 504])
def test_lock_resolution_failure_never_selects_a_target(worker, monkeypatch, code):
    monkeypatch.setattr(stream.browser_remote, "request", lambda data: (code, {"error": "sin identidad"}))
    assert worker._active_target()["activeTarget"] is None


def test_native_window_disappeared_never_asks_cdp_to_guess(worker, monkeypatch):
    def gone():
        raise OSError("ventana cerrada")

    monkeypatch.setattr(stream, "_native_windows", lambda window: gone())
    monkeypatch.setattr(stream.browser_remote, "request", lambda data: pytest.fail("no debe consultar"))
    assert worker._active_target()["activeTarget"] is None


def test_window_change_during_resolution_keeps_view_paused(worker, monkeypatch):
    def request(data):
        worker.window = "303"
        return 200, {"activeTarget": {"id": "old", "context": "old", "window": "202", "windowId": 2}}

    monkeypatch.setattr(stream.browser_remote, "request", request)
    assert worker._active_target()["activeTarget"] is None


def test_geometry_change_during_resolution_keeps_view_paused(worker, monkeypatch):
    before = stream._native_windows("202")
    calls = iter([before, []])
    monkeypatch.setattr(stream, "_native_windows", lambda window: next(calls))
    monkeypatch.setattr(stream.browser_remote, "request", lambda data: (200, {"activeTarget": {"id": "old"}}))
    assert worker._active_target()["activeTarget"] is None
