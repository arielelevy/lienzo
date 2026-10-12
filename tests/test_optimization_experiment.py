import optimization_experiment as e
import optimization_scheduler as s
import pytest


@pytest.mark.parametrize("command_code,filter_code,expected", [(0, 0, 0), (7, 0, 7), (0, 2, 2)])
def test_on_filters_same_interpreter_output_without_losing_failure(monkeypatch, command_code, filter_code, expected):
    monkeypatch.setattr(e, "manifest", lambda: "same")
    monkeypatch.setattr(e.agent_improvements, "rtk_path", lambda: "rtk.exe")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return (command_code, "raw pytest output", "") if len(calls) == 1 else (filter_code, "compact", "")

    monkeypatch.setattr(e.subproc, "correr", run)
    result = e.step({"source_version": "same", "cursor": 1})
    assert calls[0][0][:3] == [e.sys.executable, "-m", "pytest"]
    assert calls[1][0] == ["rtk.exe", "pipe", "--filter", "pytest"]
    assert calls[1][1]["entrada"] == "raw pytest output"
    assert result["code"] == expected
    assert result["raw_stdout"] == "raw pytest output"


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
