"""Guardias del investigador: sin CLI real, cuenta ni scheduler vivo."""
import optimization_research as research
import optimization_research_policy as policy
import optimization_research_runner as runner
import pytest


@pytest.mark.parametrize("requested, effective", [(60, 60), (80, 80), (95, 80)])
def test_weekly_authorization_only_restricts(monkeypatch, requested, effective):
    auth = {**policy.CODEX_AUTHORIZATION, "uso_semanal_max_pct": requested}
    monkeypatch.setattr(research.shutil, "which", lambda _: "fake-codex")
    reading = {
        "ok": True, "used_pct": 81, "ordinary_usage_allowed": True,
        "spend_control_reached": False, "rate_limit_reached_type": None,
        "credits_unlimited": False, "credits_has": False, "credits_balance": "0",
    }
    adapter = research.CodexAdapter(quota_reader=lambda: reading)
    limits = adapter.limits(auth, "fixture")
    assert adapter.max_used == effective
    assert limits["blocked_by"] and limits["consumption_bound"] is None
    assert adapter.midrun_reason()
    monkeypatch.setattr(policy, "effective_authorization", lambda *_: (auth, None))
    decision = policy.evaluate(limits)
    assert not decision["enabled"]
    assert decision["limits"]["max_weekly_used_pct"] == effective


def test_weekly_exact_ceiling_allowed(monkeypatch):
    monkeypatch.setattr(research.shutil, "which", lambda _: "fake-codex")
    reading = {
        "ok": True, "used_pct": 80, "ordinary_usage_allowed": True,
        "spend_control_reached": False, "rate_limit_reached_type": None,
        "credits_unlimited": False, "credits_has": False, "credits_balance": "0",
    }
    adapter = research.CodexAdapter(quota_reader=lambda: reading)
    assert not adapter.limits(policy.CODEX_AUTHORIZATION, "fixture")["blocked_by"]
    assert adapter.midrun_reason() is None


@pytest.mark.parametrize("decision", [{}, {"enabled": False}, {"enabled": 1}])
def test_blocked_investigation_has_no_side_effects(monkeypatch, decision):
    def forbidden(*args, **kwargs):
        pytest.fail("no debe preparar el paquete ni lanzar procesos")
    monkeypatch.setattr(research, "packet", forbidden)
    monkeypatch.setattr(research.runner, "run", forbidden)
    with pytest.raises(ValueError, match="investigador bloqueado por política"):
        research.investigate({}, object(), decision, should_stop=lambda: None)


def test_cancel_before_launch_never_creates_process(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("no debe lanzar un proceso cancelado")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    result = runner.run(["unused"], stdin_text="", cwd=None, timeout=10,
                        should_stop=lambda: "cancelado por el usuario", max_output=100)
    assert result["stopped"] == "cancelado por el usuario"
    assert result["pid"] is None and result["code"] is None
    assert not result["timed_out"] and not result["output_exceeded"]
    assert result["stdout"] == result["stderr"] == ""
