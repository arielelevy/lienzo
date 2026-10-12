"""Cola operacional; las hipótesis y su evidencia viven en conocimiento.sqlite."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import state
from atomico import atomic_write


class Queue:
    def __init__(self):
        self.lock = threading.RLock()
        self.path = Path(state.LIENZO) / "optimization-queue.json"
        self.enabled = True
        self.jobs = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or type(data.get("enabled")) is not bool or not isinstance(data.get("jobs"), list):
                raise ValueError("cola de optimización inválida")
            self.enabled, self.jobs = data["enabled"], data["jobs"]
            self._validate()
            for job in self.jobs:
                if job["state"] in ("running", "paused"):
                    job["state"] = "review"
                    job["reason"] = "ejecución interrumpida; revisar antes de reencolar"

    def activate(self):
        with self.lock:
            if self.path.exists():
                self.save()  # persistir recuperación explícitamente al iniciar, nunca en GET

    def _validate(self):
        if len(self.jobs) > 100:
            raise ValueError("cola excede 100 trabajos")
        ids = set()
        for job in self.jobs:
            if not isinstance(job, dict) or not all(isinstance(job.get(k), str) for k in ("id", "project", "state")):
                raise ValueError("trabajo inválido")
            if job["state"] not in ("queued", "running", "paused", "review", "observed", "failed") or job["id"] in ids:
                raise ValueError("estado o ID de trabajo inválido")
            ids.add(job["id"])
            if type(job.get("cursor")) is not int or not 0 <= job["cursor"] <= 30:
                raise ValueError("cursor inválido")
            if not isinstance(job.get("results"), list) or not all(isinstance(x, str) for x in job["results"]):
                raise ValueError("referencias inválidas")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(self.path), json.dumps({"enabled": self.enabled, "jobs": self.jobs}, ensure_ascii=False))

    def view(self):
        with self.lock:
            return json.loads(json.dumps({"enabled": self.enabled, "jobs": self.jobs}))

    def enqueue(self, project: str, *, version=None, source_ids=None, automatic=False, kind="analysis"):
        with self.lock:
            if automatic:
                previous = [j for j in self.jobs if j["project"] == project]
                if any(j.get("source_version") == version for j in previous):
                    return None
                if previous and time.time() - max(j.get("created_at", 0) for j in previous) < 120:
                    return None
            for job in self.jobs:
                if job["project"] == project and job["state"] in ("queued", "running", "paused"):
                    return dict(job)
            if len(self.jobs) >= 100:
                raise ValueError("cola llena; revisar historial antes de agregar trabajos")
            job = {"id": str(uuid.uuid4()), "project": project, "state": "queued", "cursor": 0, "results": []}
            job.update(source_version=version, source_ids=source_ids, automatic=automatic, created_at=time.time())
            job.update(kind=kind, profiles=[] if kind == "off_on_local" else None)
            self.jobs.append(job)
            try:
                self.save()
            except OSError:
                self.jobs.pop()
                raise
            return dict(job)

    def configure(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("enabled debe ser booleano")
        with self.lock:
            previous = self.enabled
            self.enabled = enabled
            try:
                self.save()
            except OSError:
                self.enabled = previous
                raise

    def change(self, job_id: str, **values):
        with self.lock:
            job = next(j for j in self.jobs if j["id"] == job_id)
            previous = dict(job)
            job.update(values)
            try:
                self.save()
            except OSError:
                job.clear()
                job.update(previous)
                raise

    def next_job(self):
        with self.lock:
            return next((dict(j) for j in self.jobs if j["state"] in ("queued", "running", "paused")), None)
