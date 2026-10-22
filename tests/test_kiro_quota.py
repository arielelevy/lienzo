"""Contrato de /usage Kiro: créditos y mensajes mensuales, sin inferencia."""

import queue
from types import SimpleNamespace

import cuotas
import kiro_quota
import pytest


def test_usage_has_both_resources_and_reset():
    value = kiro_quota.parse_usage(
        {
            "planName": "KIRO PRO",
            "billingCycleReset": "2026-11-01",
            "usageBreakdowns": [
                {"resourceType": "CREDIT", "used": 12.37, "limit": 1000, "hasLimit": True},
                {"resourceType": "CHAT", "displayName": "Messages", "used": 8, "limit": 500, "hasLimit": True},
            ],
        }
    )
    assert value["credits"] == {"used": 12.37, "limit": 1000, "available": 987.63}
    assert value["messages"]["available"] == 492
    assert value["resets_at"] == "2026-11-01"


def test_partial_never_invents_messages_or_turn_credit_as_monthly():
    value = kiro_quota.parse_usage(
        {"usageBreakdowns": [{"resourceType": "CREDIT", "used": 0.8, "limit": 0, "hasLimit": False}]}
    )
    assert value["messages"] is None
    assert value["credits"] == {"used": 0.8, "limit": None, "available": None}
    assert value["resets_at"] is None


@pytest.mark.parametrize("used", [True, -1, float("nan"), "12"])
def test_invalid_usage_is_rejected(used):
    with pytest.raises(ValueError):
        kiro_quota.parse_usage(
            {"usageBreakdowns": [{"resourceType": "CREDIT", "used": used, "limit": 1000, "hasLimit": True}]}
        )


def test_kiro_is_cached_for_five_minutes_without_changing_auto_launch(monkeypatch):
    calls = []

    def read():
        calls.append("kiro")
        return {
            "credits": {"used": 130.37, "limit": 1000, "available": 869.63},
            "messages": None,
            "resets_at": "2026-11-01",
            "plan": "KIRO PRO",
        }

    monkeypatch.setattr(kiro_quota, "read_usage", lambda timeout: read())
    monkeypatch.setitem(cuotas.READERS, "kiro", cuotas.read_kiro)
    first = cuotas.estado()
    assert first["kiro"]["credits"]["available"] == 869.63
    assert first["kiro"]["messages"] is None
    assert first["sugerido"] is None  # los lectores Claude/Codex de conftest no tienen lectura
    cuotas.estado()
    assert calls == ["kiro"]
    cuotas.estado(refrescar=True)
    assert calls == ["kiro", "kiro"]


def test_timeout_is_unknown_not_zero(monkeypatch):
    def fail(timeout):
        raise TimeoutError("secreto que no debe salir")

    monkeypatch.setattr(kiro_quota, "read_usage", fail)
    reading = cuotas.read_kiro()
    assert not reading["ok"]
    assert reading["credits"] is None and reading["messages"] is None
    assert "TimeoutError" in reading["error"] and "secreto" not in reading["error"]


def test_acp_waits_for_initialize_and_never_creates_a_session(monkeypatch):
    import json

    output, methods, killed = queue.Queue(), [], []

    class Output:
        def __iter__(self):
            while (line := output.get()) is not None:
                yield line

    def write(text):
        request = json.loads(text)
        methods.append(request["method"])
        result = (
            {}
            if request["id"] == 1
            else {
                "success": True,
                "data": {"usageBreakdowns": [{"resourceType": "CREDIT", "used": 0, "limit": 1000, "hasLimit": True}]},
            }
        )
        output.put(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    process = SimpleNamespace(stdout=Output(), stdin=SimpleNamespace(write=write, flush=lambda: None))
    monkeypatch.setattr(kiro_quota.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(kiro_quota.subproc, "_matar_arbol", lambda p: (killed.append(p), output.put(None)))
    assert kiro_quota.read_usage(exe="kiro-cli")["credits"]["available"] == 1000
    assert methods == ["initialize", "_kiro/account/getUsage"]
    assert killed == [process]


def test_claude_launch_does_not_start_unrelated_kiro_reader(monkeypatch):
    calls = []

    def kiro():
        calls.append("kiro")
        return cuotas._failure("lectura ajena al lanzamiento")

    monkeypatch.setitem(cuotas.READERS, "kiro", kiro)
    cuotas.para_lanzar("claude")
    assert calls == []
