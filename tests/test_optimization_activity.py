import datetime as dt

import optimization_activity as a
import pytest


def good():
    return {"idle_seconds": 180, "ui_idle_seconds": 180, "cpu_pct": 35, "mem_free_gb": 1.5, "pending": False, "agents_busy": False}


@pytest.mark.parametrize("key,value", [("idle_seconds", None), ("cpu_pct", float("nan")), ("mem_free_gb", True), ("ui_idle_seconds", -1), ("pending", None), ("agents_busy", True), ("idle_seconds", 179.9), ("cpu_pct", 35.1), ("mem_free_gb", 1.49)])
def test_unknown_or_busy_blocks(key, value):
    signals = good()
    signals[key] = value
    assert a.block_reason(signals)


def test_exact_limits_allow():
    assert a.block_reason(good()) is None


def test_unknown_live_session_blocks_snapshot(monkeypatch):
    monkeypatch.setattr(a.state, "sessions", {"unknown": {"session_id": "unknown"}})
    monkeypatch.setattr(a.state, "pending", {})
    monkeypatch.setattr(a, "idle_seconds", lambda: 200)
    monkeypatch.setattr(a.health, "_memoria", lambda: (3, 10))
    monkeypatch.setattr(a.health, "_cpu_pct", lambda: 10)
    assert a.snapshot(0)["agents_busy"] is True


@pytest.mark.parametrize("expiry,session,expected", [
    ("2026-10-13T00:00:00+00:00", {"alive": True}, True),
    ("2026-10-11T00:00:00+00:00", {"alive": True}, False),
    ("2026-10-13T00:00:00+00:00", {"alive": False}, False),
    (None, {"state": "muerta"}, False),
    (None, {"alive": True}, True),
    ("bad-date", {"alive": True}, True),
    ("2026-10-11T00:00:00+00:00", None, False),
    (None, None, True),
])
def test_only_current_permissions_block_without_altering_history(expiry, session, expected):
    permission = {"session_id": "s", "expires_at": expiry}
    original = dict(permission)
    sessions = {"s": session} if session is not None else {}
    assert a.pending_active([permission], sessions, dt.datetime(2026, 10, 12, tzinfo=dt.UTC)) is expected
    assert permission == original
