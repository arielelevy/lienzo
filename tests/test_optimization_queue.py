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
