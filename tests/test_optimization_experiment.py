import optimization_experiment as e
import optimization_scheduler as s
import pytest


def test_changed_manifest_does_not_execute_commands(monkeypatch):
    monkeypatch.setattr(e, "manifest", lambda: "new")
    monkeypatch.setattr(e.subproc, "correr", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(ValueError, match="fuentes cambiaron"):
        e.step({"source_version": "old", "cursor": 0})


def test_experiment_preserves_profile_and_pauses_before_next(monkeypatch):
    scheduler = s.Scheduler()
    job = scheduler.queue.enqueue("p")
    scheduler.queue.change(job["id"], kind="off_on_local", profiles=[])
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.experiment, "step", lambda _: {"profile": "OFF", "code": 0})
    scheduler._experiment_step(scheduler.queue.next_job())
    assert scheduler.queue.next_job()["cursor"] == 1
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: "usuario volvió")
    monkeypatch.setattr(s.experiment, "step", lambda _: pytest.fail("must not launch ON"))
    scheduler._experiment_step(scheduler.queue.next_job())
    paused = scheduler.queue.next_job()
    assert paused["state"] == "paused" and len(paused["profiles"]) == 1


def test_failing_oracle_requires_review_without_retry(monkeypatch):
    scheduler = s.Scheduler()
    job = scheduler.queue.enqueue("p")
    scheduler.queue.change(job["id"], kind="off_on_local", profiles=[])
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.experiment, "step", lambda _: {"profile": "OFF", "code": 1})
    scheduler._experiment_step(scheduler.queue.next_job())
    assert scheduler.queue.next_job() is None
    assert scheduler.queue.view()["jobs"][0]["state"] == "review"
