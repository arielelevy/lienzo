"""Investigador con Claude (decisión 17): reemplaza a Codex mientras Codex no tenga >= 20 % del semanal.
`claude -p` restringido, sin hooks ni sesión persistida, con la suscripción leída en vivo. Un hijo Python
imita la salida JSON de la CLI: sin inferencia ni red."""

import json
import os
import sys
import time

import optimization_research as r
import optimization_research_policy as policy
import optimization_research_quota as quota
import optimization_scheduler as s
import pytest
from test_optimization_research import PROJECT, answer, good, incident, isolated  # noqa: F401 - fixture autouse

CHILD = r"""
import json, os, sys, time
mode, work = sys.argv[1], sys.argv[2]
prompt = sys.stdin.read()
data = json.loads(prompt.split("CASO:\n", 1)[1])
result = json.load(open(work + "/fake.json", encoding="utf-8"))
if mode == "sleep":
    time.sleep(60)
event = {"type": "result", "subtype": "success", "is_error": mode == "error", "total_cost_usd": 0.0462,
         "usage": {"input_tokens": 4, "output_tokens": 139, "cache_read_input_tokens": 5046},
         "env_key": os.environ.get("ANTHROPIC_API_KEY")}
if mode != "nostructured":
    event["structured_output"] = result
print(json.dumps(event))
"""


def claude_reading(weekly=12.0, five=15.0, ok=True):
    if not ok:
        return {"ok": False, "error": "sin respuesta de Anthropic: URLError"}
    return {"ok": True, "plan": "team", "weekly": {"used_pct": weekly}, "five_hour": {"used_pct": five}}


def codex_reading(used=90.0):
    return {
        "ok": True,
        "used_pct": used,
        "ordinary_usage_allowed": True,
        "spend_control_reached": False,
        "rate_limit_reached_type": None,
        "five_hour_used_pct": None,
        "credits_has": False,
        "credits_unlimited": False,
        "credits_balance": "0",
    }


class FakeClaude(r.ClaudeAdapter):
    """El adaptador real (límites, colecta, uso, entorno) con un hijo Python en lugar de claude.exe."""

    def __init__(self, mode="ok", reading=None, **kw):
        self.reading = reading or claude_reading()
        super().__init__(quota_reader=lambda: self.reading, **kw)
        self.mode = mode
        self.real_argv = None

    def limits(self, auth, project):
        out = super().limits(auth, project)
        return {**out, "available": True, "available_reason": None}

    def command(self, work, root, seconds):
        self.exe = "claude.exe"
        self.real_argv, stdin_text = super().command(work, root, seconds)
        data = json.loads(stdin_text.split("CASO:\n", 1)[1])
        (work / "fake.json").write_text(json.dumps(answer(data)), encoding="utf-8")
        return [sys.executable, "-c", CHILD, self.mode, str(work)], stdin_text


def scheduler_with(adapter):
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: adapter
    return scheduler


def run_ticks(scheduler, n=3):
    for _ in range(n):
        scheduler.tick(good())


def test_assessment_uses_the_same_threshold_and_five_hours():
    bound, reasons = r.claude_assess(claude_reading(), 80)
    assert not reasons and bound["maximum"] == "0" and bound["verified"] and "team" in bound["basis"]
    assert r.claude_assess(claude_reading(weekly=81), 80)[1] == ["uso semanal de Claude 81 % supera el tope 80 %"]
    assert r.claude_assess(claude_reading(five=90), 80)[1] == ["ventana de 5 h de Claude al 90 %"]
    assert "desconocida" in r.claude_assess(claude_reading(ok=False), 80)[1][0]
    assert "sin uso_semanal_max_pct" in r.claude_assess(claude_reading(), None)[1][0]


def test_claude_takes_over_only_when_codex_lacks_quota(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda _: "codex.exe")
    reads = []
    monkeypatch.setattr(quota, "read_codex", lambda *a, **kw: reads.append(1) or codex_reading(90.0))
    chosen = r.adapter_for(PROJECT)
    assert chosen.name == "claude" and "90 % supera el tope 80 %" in chosen.because
    monkeypatch.setattr(quota, "read_codex", lambda *a, **kw: reads.append(1) or codex_reading(50.0))
    chosen = r.adapter_for(PROJECT)
    assert chosen.name == "codex"
    chosen.limits(policy.CODEX_AUTHORIZATION, PROJECT)
    assert len(reads) == 2  # la lectura de la elección se reutiliza: un app-server por evaluación


def test_default_authorization_is_decision_17():
    decision = policy.evaluate(FakeClaude().limits(policy.CLAUDE_AUTHORIZATION, PROJECT))
    assert decision["enabled"], decision["reasons"]
    assert decision["authorization"]["fuente"].startswith("decisión 17") and decision["service_max_usd"] == "0"
    assert decision["limits"]["max_weekly_used_pct"] == 80 and decision["budget_granted_usd"] == "0"
    blocked = policy.evaluate(
        FakeClaude(reading=claude_reading(weekly=85)).limits(policy.CLAUDE_AUTHORIZATION, PROJECT)
    )
    assert not blocked["enabled"] and any("85 %" in x for x in blocked["reasons"])


def test_command_is_read_only_without_hooks_or_persistence(tmp_path):
    adapter = r.ClaudeAdapter(quota_reader=claude_reading)
    adapter.exe = "claude.exe"
    (tmp_path / "prompt.md").write_text("caso", encoding="utf-8")
    argv, stdin_text = adapter.command(tmp_path, tmp_path, 60)
    assert stdin_text == "caso" and argv[:2] == ["claude.exe", "-p"]
    for flag in ("--restricted", "--safe-mode", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob" and "Bash" not in " ".join(argv)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == r.SCHEMA
    assert "dangerously" not in " ".join(argv) and "ANTHROPIC_API_KEY" in adapter.env_remove


def test_end_to_end_with_subscription_env_and_structured_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-que-facturaria-" + "x" * 20)
    incident()
    adapter = FakeClaude()
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed", job["reason"]
    meta = job["last_run"]
    assert meta["adapter"] == "claude" and meta["usage_reported"]["output_tokens"] == 139
    assert meta["usage_reported"]["costo_lista_microusd"] == 46200 and meta["ledger"] is None
    raw = (r.Path(r.state.LIENZO) / meta["raw_output"]["stdout"]).read_text(encoding="utf-8")
    assert json.loads(raw)["env_key"] is None  # el hijo no heredó la clave de API
    assert os.environ["ANTHROPIC_API_KEY"]  # el server la conserva
    assert "SÓLO LECTURA sobre este repositorio" in (
        r.Path(r.state.LIENZO) / "research" / job["case"]["case_key"] / "prompt.md"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", ["error", "nostructured"])
def test_cli_error_or_missing_structured_output_fails_with_evidence(mode):
    incident()
    scheduler = scheduler_with(FakeClaude(mode))
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and "no dejó respuesta" in job["reason"] and job["evidence"]


def test_claude_quota_block_mid_run_pauses_with_backoff():
    incident()
    adapter = FakeClaude("sleep")
    adapter.quota_every = 0.1
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})

    def later():
        time.sleep(1)
        adapter.reading = claude_reading(weekly=95)

    import threading

    threading.Thread(target=later, daemon=True).start()
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["reason"].startswith("cuota: uso semanal de Claude 95 %")
    assert job["not_before"] > time.time()


def test_daily_cap_counts_per_adapter():
    incident()
    scheduler = scheduler_with(FakeClaude())
    queue = scheduler.queue
    job = queue.enqueue_research(PROJECT, r.select(PROJECT)[0])
    now = time.time()
    queue.change(job["id"], runs=[now, now], run_adapters=["codex", "claude"])
    assert queue.research_runs_since(now - 10) == 2
    assert queue.research_runs_since(now - 10, "claude") == 1
    queue.change(job["id"], runs=[now, now, now], run_adapters=["codex", "claude"])  # uno sin registrar
    assert queue.research_runs_since(now - 10, "azure-openai") == 1


def test_switch_uses_the_same_capped_threshold_as_the_evaluation(monkeypatch):
    from test_optimization_research import write_auth

    write_auth(uso_semanal_max_pct=90)  # un archivo no sube el 80 % de la autorización
    monkeypatch.setattr(r.shutil, "which", lambda _: "codex.exe")
    monkeypatch.setattr(quota, "read_codex", lambda *a, **kw: codex_reading(85.0))
    chosen = r.adapter_for(PROJECT)
    assert chosen.name == "claude" and "85 % supera el tope 80 %" in chosen.because


def test_daily_ceiling_is_global_and_the_authorization_cap_is_per_adapter():
    limits = FakeClaude().limits(policy.CLAUDE_AUTHORIZATION, PROJECT)
    blocked = policy.evaluate(limits, runs_today=6, adapter_runs_today=0)
    assert not blocked["enabled"] and blocked["reasons"] == ["tope diario del investigador alcanzado (6 de 6)"]
    ok = policy.evaluate(limits, runs_today=5, adapter_runs_today=0)
    assert ok["enabled"] and ok["adapter_runs_today"] == 0


def test_scheduler_passes_global_and_per_adapter_counts():
    incident()
    adapter = FakeClaude()
    scheduler = scheduler_with(adapter)
    old = scheduler.queue.enqueue_research(PROJECT, {"case_key": "viejo", "project": PROJECT, "area": "x"})
    now = time.time()
    scheduler.queue.change(old["id"], state="observed", runs=[now] * 6, run_adapters=["codex"] * 6)
    with pytest.raises(ValueError, match="tope diario del investigador"):
        scheduler.command({"action": "enqueue_research", "project": PROJECT})


def test_claude_quota_is_not_read_every_minute():
    reads = []
    adapter = r.ClaudeAdapter(quota_reader=lambda: reads.append(1) or claude_reading())
    assert adapter.quota_every >= 300
    adapter.max_used = 80
    adapter.midrun_reason()
    adapter.used_pct()  # reutiliza la lectura reciente
    assert len(reads) == 1
