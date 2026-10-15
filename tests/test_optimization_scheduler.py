import time

import optimization_scheduler as s
import pytest


@pytest.fixture(autouse=True)
def known_idle_boundary(monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)


def good():
    return {
        "idle_seconds": 190,
        "ui_idle_seconds": 190,
        "cpu_pct": 10,
        "mem_free_gb": 3,
        "pending": False,
        "agents_busy": False,
    }


def test_two_samples_then_user_return_pauses_and_never_starts_agent(monkeypatch):
    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")
    monkeypatch.setattr(s.memory, "sources", lambda p: ["source"])
    calls = []
    monkeypatch.setattr(s.memory, "propose", lambda *a: calls.append(a) or "hypothesis")
    monkeypatch.setattr(s.memory, "record_analysis", lambda *a: "evidence")
    scheduler.tick(good())
    assert not calls
    scheduler.tick(good())
    assert len(calls) == 1
    scheduler.tick({**good(), "idle_seconds": 0})
    assert scheduler.queue.view()["jobs"][0]["state"] == "paused"
    assert len(calls) == 1
    scheduler.tick(good())
    scheduler.tick(good())
    assert scheduler.queue.view()["jobs"][0]["state"] == "observed"
    scheduler.tick(good())
    assert len(calls) == 1
    assert scheduler.status()["paid_enabled"] is False
    assert scheduler.status()["new_agents_enabled"] is False


@pytest.mark.parametrize(
    "data",
    [
        {"action": "launch"},
        {"action": "enqueue", "project": "p", "command": "whoami"},
        {"action": "configure", "enabled": "yes"},
        {"action": "pay", "budget": 1},
    ],
)
def test_no_arbitrary_execution_or_budget(data):
    with pytest.raises(ValueError):
        s.Scheduler().command(data)


def test_time_limit_keeps_partial_for_review(monkeypatch):
    scheduler = s.Scheduler()
    job = scheduler.queue.enqueue("p")
    scheduler.started[job["id"]] = time.monotonic() - 30
    monkeypatch.setattr(s.memory, "sources", lambda p: pytest.fail("should not read"))
    scheduler.tick(good())
    scheduler.tick(good())
    assert scheduler.queue.view()["jobs"][0]["state"] == "review"


def test_failure_visible_without_retry(monkeypatch):
    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")

    def fail(p):
        raise OSError("SQLite unavailable")

    monkeypatch.setattr(s.memory, "sources", fail)
    scheduler.tick(good())
    scheduler.tick(good())
    scheduler.tick(good())
    assert scheduler.queue.view()["jobs"][0]["state"] == "failed"
    assert "OSError" in scheduler.reason or scheduler.reason == "sin trabajos en cola"


def test_parallel_tick_cannot_start_second_step(monkeypatch):
    import threading

    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def read(p):
        calls.append(p)
        entered.set()
        assert release.wait(2)
        return []

    monkeypatch.setattr(s.memory, "sources", read)
    monkeypatch.setattr(s.memory, "record_analysis", lambda *a: "evidence")
    scheduler.tick(good())
    worker = threading.Thread(target=scheduler.tick, args=(good(),))
    worker.start()
    assert entered.wait(2)
    try:
        scheduler.tick(good())
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(2)


def test_activity_during_sources_prevents_proposal_and_preserves_cursor(monkeypatch):
    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")
    changed = {"active": False}

    def sources(_):
        changed["active"] = True
        return ["source"]

    monkeypatch.setattr(s.memory, "sources", sources)
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: "usuario volvió" if changed["active"] else None)
    monkeypatch.setattr(s.memory, "propose", lambda *a: pytest.fail("must not propose"))
    scheduler.tick(good())
    scheduler.tick(good())
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["cursor"] == 0


def test_pause_before_write_preserves_pending_source(monkeypatch):
    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")
    monkeypatch.setattr(s.memory, "sources", lambda _: ["source"])
    calls = iter([None, "pausado"])
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: next(calls))
    monkeypatch.setattr(s.memory, "propose", lambda *a: pytest.fail("must not propose"))
    scheduler.tick(good())
    scheduler.tick(good())
    assert scheduler.queue.view()["jobs"][0]["state"] == "paused"


def test_auto_enqueue_new_memory_once_without_own_hypothesis_loop(monkeypatch):
    scheduler = s.Scheduler()
    monkeypatch.setattr(s.conocimiento, "proyectos", lambda: [{"id": "p"}])
    sample = {"ids": ["source"], "version": "v1"}
    monkeypatch.setattr(s.memory, "source_snapshot", lambda _: sample)
    monkeypatch.setattr(s.memory, "propose", lambda *a: "hypothesis")
    monkeypatch.setattr(s.memory, "record_analysis", lambda *a: "evidence")
    for _ in range(8):
        scheduler.tick(good())
    jobs = scheduler.queue.view()["jobs"]
    assert len(jobs) == 1 and jobs[0]["automatic"] and jobs[0]["state"] == "observed"
    assert jobs[0]["results"] == ["hypothesis"]
    sample["version"] = "v2"
    scheduler.tick(good())
    assert len(scheduler.queue.view()["jobs"]) == 1  # cooldown
    scheduler.queue.change(jobs[0]["id"], created_at=0)
    scheduler.tick(good())
    assert len(scheduler.queue.view()["jobs"]) == 2


def test_activity_during_proposal_keeps_transaction_result_then_pauses(monkeypatch):
    scheduler = s.Scheduler()
    scheduler.queue.enqueue("p")
    changed = {"active": False}
    monkeypatch.setattr(s.memory, "sources", lambda _: ["source"])
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: "usuario volvió" if changed["active"] else None)

    def propose(*_):
        changed["active"] = True
        return "confirmed-transaction-result"

    monkeypatch.setattr(s.memory, "propose", propose)
    scheduler.tick(good())
    scheduler.tick(good())
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["cursor"] == 1
    assert job["results"] == ["confirmed-transaction-result"]


@pytest.mark.parametrize("state,cursor,version", [("queued", 0, "new"), ("running", 0, "old"), ("paused", 1, "old")])
def test_explicit_reenqueue_refreshes_only_unstarted_experiment(monkeypatch, state, cursor, version):
    scheduler = s.Scheduler()
    job = scheduler.queue.enqueue("p", kind="off_on_local", version="old", source_ids=[])
    scheduler.queue.change(job["id"], state=state, cursor=cursor, profiles=[])
    monkeypatch.setattr(s.experiment, "manifest", lambda: "new")
    monkeypatch.setattr(scheduler, "status", scheduler.queue.view)
    scheduler.command({"action": "enqueue_off_on", "project": "p"})
    jobs = scheduler.queue.view()["jobs"]
    assert len(jobs) == 1 and jobs[0]["id"] == job["id"]
    assert jobs[0]["source_version"] == version
    assert jobs[0]["state"] == state and jobs[0]["cursor"] == cursor
