"""Cola operacional; las hipótesis y su evidencia viven en conocimiento.sqlite."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import state
from atomico import atomic_write

STATES = ("queued", "running", "paused", "review", "observed", "failed", "cancelled")
ACTIVE = ("queued", "running", "paused")
MAX_RESEARCH_ATTEMPTS = 10


class Queue:
    def __init__(self):
        self.lock = threading.RLock()
        self.path = Path(state.LIENZO) / "optimization-queue.json"
        self.enabled = True
        self.jobs = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or type(data.get("enabled")) is not bool
                or not isinstance(data.get("jobs"), list)
            ):
                raise ValueError("cola de optimización inválida")
            self.enabled, self.jobs = data["enabled"], data["jobs"]
            self._validate()
            for job in self.jobs:
                if job["state"] in ("running", "paused"):
                    job["state"] = "review"
                    job["reason"] = "ejecución interrumpida; revisar antes de reencolar"
                    if job.get("kind") == "research" and job.get("pid"):
                        # El PID pudo reutilizarse: nunca se mata un proceso que no lanzó este server.
                        job["reason"] += f"; el PID {job['pid']} registrado no se mata tras el reinicio"

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
            if job["state"] not in STATES or job["id"] in ids:
                raise ValueError("estado o ID de trabajo inválido")
            ids.add(job["id"])
            if type(job.get("cursor")) is not int or not 0 <= job["cursor"] <= 30:
                raise ValueError("cursor inválido")
            if not isinstance(job.get("results"), list) or not all(isinstance(x, str) for x in job["results"]):
                raise ValueError("referencias inválidas")
            if job.get("kind") == "research":
                case = job.get("case")
                if not isinstance(case, dict) or not isinstance(case.get("case_key"), str):
                    raise ValueError("caso de investigación inválido")
                attempts = job.get("attempts")
                if type(attempts) is not int or not 0 <= attempts <= MAX_RESEARCH_ATTEMPTS:
                    raise ValueError("intentos de investigación inválidos")
                if not isinstance(job.get("runs"), list) or not all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) for x in job["runs"]
                ):
                    raise ValueError("ejecuciones de investigación inválidas")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(self.path), json.dumps({"enabled": self.enabled, "jobs": self.jobs}, ensure_ascii=False))

    def view(self):
        with self.lock:
            return json.loads(json.dumps({"enabled": self.enabled, "jobs": self.jobs}))

    def enqueue(self, project: str, *, version=None, source_ids=None, automatic=False, kind="analysis"):
        with self.lock:
            if automatic:
                previous = [j for j in self.jobs if j["project"] == project and j.get("kind") != "research"]
                if any(j.get("source_version") == version for j in previous):
                    return None
                if previous and time.time() - max(j.get("created_at", 0) for j in previous) < 120:
                    return None
            for job in self.jobs:
                if job["project"] == project and job["state"] in ACTIVE and job.get("kind") != "research":
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

    def enqueue_research(self, project: str, case: dict, *, automatic=False):
        """Un caso por clave en todo el historial (observado, fallido o cancelado no se repite solo) y a lo
        sumo una investigación activa por proyecto. Devuelve None si no encola."""
        if not isinstance(case, dict) or not isinstance(case.get("case_key"), str) or case.get("project") != project:
            raise ValueError("caso de investigación inválido")
        with self.lock:
            research = [j for j in self.jobs if j.get("kind") == "research"]
            if any(j["case"]["case_key"] == case["case_key"] for j in research):
                return None
            if any(j["project"] == project and j["state"] in ACTIVE for j in research):
                return None
            if len(self.jobs) >= 100:
                raise ValueError("cola llena; revisar historial antes de agregar trabajos")
            job = {"id": str(uuid.uuid4()), "project": project, "state": "queued", "cursor": 0, "results": []}
            job.update(kind="research", case=dict(case), attempts=0, runs=[], automatic=automatic)
            job.update(created_at=time.time(), source_version=case["case_key"], source_ids=case.get("source_ids"))
            self.jobs.append(job)
            try:
                self.save()
            except OSError:
                self.jobs.pop()
                raise
            return dict(job)

    def research_runs_since(self, since: float) -> int:
        with self.lock:
            return sum(1 for j in self.jobs if j.get("kind") == "research" for t in j["runs"] if t >= since)

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
            now = time.time()  # una investigación bloqueada por política espera su `not_before`
            return next(
                (dict(j) for j in self.jobs if j["state"] in ACTIVE and j.get("not_before", 0) <= now),
                None,
            )
