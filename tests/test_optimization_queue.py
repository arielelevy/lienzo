import json

import pytest
from optimization_queue import Queue


def test_queue_persists_deduplicates_and_requires_review_after_restart():
    q = Queue()
    job = q.enqueue("project")
    assert q.enqueue("project")["id"] == job["id"]
    q.change(job["id"], state="running", cursor=2)
    restored = Queue()
    assert restored.view()["jobs"][0]["state"] == "review"
    assert restored.next_job() is None


def test_corrupt_queue_is_visible():
    q = Queue()
    q.path.parent.mkdir(parents=True, exist_ok=True)
    q.path.write_text(json.dumps({"enabled": True, "jobs": [{"id": "x"}]}))
    with pytest.raises(ValueError):
        Queue()


def test_failed_save_does_not_enable_or_advance(monkeypatch):
    q = Queue()
    job = q.enqueue("project")

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(q, "save", fail)
    with pytest.raises(OSError):
        q.change(job["id"], cursor=1)
    assert q.view()["jobs"][0]["cursor"] == 0
    with pytest.raises(OSError):
        q.configure(False)
    assert q.enabled


def case(key="k1", project="project"):
    return {"case_key": key, "project": project, "area": "herramientas", "source_ids": ["n1"]}


def test_research_cases_deduplicate_across_history_and_one_active_per_project():
    q = Queue()
    job = q.enqueue_research("project", case())
    assert q.enqueue_research("project", case()) is None
    assert q.enqueue_research("project", case("k2")) is None  # una activa por proyecto
    q.change(job["id"], state="observed")
    assert q.enqueue_research("project", case()) is None  # observado no se repite solo
    assert q.enqueue_research("project", case("k2"))["case"]["case_key"] == "k2"
    with pytest.raises(ValueError):
        q.enqueue_research("project", case("k3", project="otro"))


def test_research_does_not_hide_or_cool_down_local_analysis():
    q = Queue()
    q.enqueue_research("project", case())
    analysis = q.enqueue("project", version="v1", source_ids=["s"], automatic=True)
    assert analysis is not None and analysis["kind"] == "analysis"


def test_research_backoff_and_daily_runs():
    import time

    q = Queue()
    job = q.enqueue_research("project", case())
    q.change(job["id"], state="paused", not_before=time.time() + 60, runs=[time.time() - 90000, time.time()])
    assert q.next_job() is None
    assert q.research_runs_since(time.time() - 86400) == 1


@pytest.mark.parametrize("field,value", [("attempts", -1), ("attempts", "1"), ("runs", ["x"]), ("case", {})])
def test_corrupt_research_job_is_visible(field, value):
    q = Queue()
    job = q.enqueue_research("project", case())
    q.change(job["id"], **{field: value})
    with pytest.raises(ValueError):
        Queue()


def test_restart_flags_research_pid_without_killing():
    q = Queue()
    job = q.enqueue_research("project", case())
    q.change(job["id"], state="running", pid=999999)
    restored = Queue().view()["jobs"][0]
    assert restored["state"] == "review" and "999999" in restored["reason"]
