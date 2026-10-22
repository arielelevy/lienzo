"""Cancelación aceptada frente a política lenta, resultado concurrente y reinicio."""

import threading
import time
from types import SimpleNamespace

import optimization_scheduler as s
import pytest


@pytest.fixture
def sch(monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda _: SimpleNamespace(name="falso")
    monkeypatch.setattr(s.research, "record", lambda *a: {"evidence": "e", "proposals": []})
    monkeypatch.setattr(s.research, "record_failure", lambda *a: "e")
    return scheduler


def enqueue(sch):
    return sch.queue.enqueue_research("p", {"case_key": "k1", "project": "p"})


def current(sch):
    return sch.queue.view()["jobs"][0]


def evaluate(_, adapter, runs_today, adapter_runs_today=None):
    return adapter, {"enabled": True, "reasons": []}


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("initial", ["queued", "paused"])
def test_cancel_during_policy_never_restarts_or_overwrites(sch, monkeypatch, enabled, initial):
    entered, release = threading.Event(), threading.Event()
    launched, errors = [], []

    def slow_policy(_, adapter, runs_today, adapter_runs_today=None):
        entered.set()
        assert release.wait(5)
        return adapter, {"enabled": enabled, "reasons": ["blocked"]}

    def run():
        try:
            sch._research_step(job)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(s.research, "evaluate", slow_policy)
    monkeypatch.setattr(s.research, "investigate", lambda *a, **kw: launched.append(True))
    job = enqueue(sch)
    sch.queue.change(job["id"], state=initial)
    job = current(sch)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(5)
        sch.command({"action": "cancel_research", "job": job["id"]})
        assert current(sch)["state"] == "cancelled"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    assert not launched
    assert current(sch)["state"] == "cancelled"
    assert current(sch)["attempts"] == 0 and current(sch)["runs"] == []


@pytest.mark.parametrize("status", ["ok", "stopped"])
def test_cancel_after_runner_result_wins_and_survives_restart(sch, monkeypatch, status):
    monkeypatch.setattr(s.research, "evaluate", evaluate)
    original_change = sch.queue.change
    accepted = []

    def change(jid, **values):
        if values == {"pid": None} and not accepted:
            accepted.append(sch.command({"action": "cancel_research", "job": jid}))
            assert s.Queue().view()["jobs"][0]["state"] == "cancelled"
        return original_change(jid, **values)

    monkeypatch.setattr(sch.queue, "change", change)
    monkeypatch.setattr(
        s.research,
        "investigate",
        lambda *a, **kw: {
            "status": status,
            "reason": "actividad del usuario",
            "meta": {},
            "result": {},
        },
    )
    sch._research_step(enqueue(sch))
    assert accepted
    assert current(sch)["state"] == "cancelled"
    assert current(sch)["attempts"] == 1
    assert s.Queue().view()["jobs"][0]["state"] == "cancelled"


def test_cancel_and_restart_transitions_keep_history_and_clear_stale_pid(sch):
    job = enqueue(sch)
    sch.command({"action": "cancel_research", "job": job["id"]})
    assert current(sch)["history"][-1]["from"] == "queued"
    sch.queue.change(job["id"], state="running", attempts=1, runs=[time.time()], pid=4242)
    recovered = s.Queue().view()["jobs"][0]
    assert recovered["state"] == "review"
    assert recovered["pid"] is None and "4242" in recovered["reason"]
    assert recovered["history"][-1]["from"] == "running"


def test_cancel_request_save_failure_does_not_accept_or_mutate(sch, monkeypatch):
    job = enqueue(sch)
    sch.queue.change(job["id"], state="running", attempts=1)
    before = sch.queue.view()
    monkeypatch.setattr(sch.queue, "save", lambda: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        sch.command({"action": "cancel_research", "job": job["id"]})
    assert sch.queue.view() == before


def test_cancel_accepted_before_runner_exception_stays_cancelled(sch, monkeypatch):
    monkeypatch.setattr(s.research, "evaluate", evaluate)

    def investigate(job, *a, **kw):
        sch.command({"action": "cancel_research", "job": job["id"]})
        raise OSError("runner stopped")

    monkeypatch.setattr(s.research, "investigate", investigate)
    enqueue(sch)
    sch.good_samples = 1
    sch.tick(
        {
            "idle_seconds": 190,
            "ui_idle_seconds": 190,
            "cpu_pct": 10,
            "mem_free_gb": 3,
            "pending": False,
            "agents_busy": False,
        }
    )
    assert current(sch)["state"] == "cancelled"
    assert current(sch)["pid"] is None
