"""La ventana corta agotada bloquea aunque la semanal y los flags permitan uso."""

import optimization_research as research
import optimization_research_quota as quota
import pytest


def reading(short):
    return {
        "ok": True,
        "used_pct": 20.0,
        "ordinary_usage_allowed": True,
        "spend_control_reached": False,
        "rate_limit_reached_type": None,
        "credits_has": False,
        "credits_unlimited": False,
        "credits_balance": "0",
        "five_hour_used_pct": short,
    }


@pytest.mark.parametrize("short,blocked", [(None, False), (99.9, False), (100.0, True)])
def test_short_window_boundary(short, blocked):
    bound, reasons = quota.assess(reading(short), 80)
    assert bool(reasons) is blocked
    assert (bound is None) is blocked
    if blocked:
        assert "ventana de 5 h agotada" in reasons


def test_exhaustion_blocks_start_and_midrun(monkeypatch):
    monkeypatch.setattr(research.shutil, "which", lambda _: "simulated-codex")
    current = reading(100.0)
    adapter = research.CodexAdapter(quota_reader=lambda: current)
    _, decision = research.evaluate("test-project", adapter)
    assert decision["enabled"] is False
    assert "ventana de 5 h agotada" in decision["reasons"]
    current["five_hour_used_pct"] = 99.9
    _, decision = research.evaluate("test-project", adapter)
    assert decision["enabled"] is True
    current["five_hour_used_pct"] = 100.0
    assert adapter.midrun_reason() == "ventana de 5 h agotada"
