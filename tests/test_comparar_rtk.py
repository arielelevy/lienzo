import runpy
from pathlib import Path

import pytest


def script():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "ops/comparar-rtk.py"))


def test_comparison_checks_actual_server_before_any_process(monkeypatch, capsys):
    module = script()
    monkeypatch.setattr(module["sys"], "argv", ["comparar-rtk", "--run"])
    monkeypatch.setattr(module["time"], "sleep", lambda _: None)
    monkeypatch.setattr(module["agent_improvements"], "rtk_path", lambda: "synthetic-rtk")
    monkeypatch.setattr(module["subproc"], "correr", lambda *a, **k: pytest.fail("must not launch commands"))
    module["main"].__globals__["signals"] = lambda: {"idle_seconds": 200, "ui_idle_seconds": 200, "cpu_pct": 1, "mem_free_gb": 3, "pending": True, "agents_busy": False}
    module["main"]()
    assert "bloqueado" in capsys.readouterr().out


def test_plan_is_free_and_does_not_claim_agent_quality(monkeypatch, capsys):
    module = script()
    monkeypatch.setattr(module["sys"], "argv", ["comparar-rtk"])
    monkeypatch.setattr(module["subproc"], "correr", lambda *a, **k: pytest.fail("must not launch commands"))
    module["main"]()
    result = module["json"].loads(capsys.readouterr().out)
    assert result["profiles"] == [] and result["max_service_cost_usd"] == "0"
    assert result["agent_cost"] is None and result["agent_quality"] == "no evaluada"
