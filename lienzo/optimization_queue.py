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
REQUESTABLE_ADAPTERS = ("codex", "claude", "azure-openai")  # lo que una persona puede pedir por trabajo


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
                # un pausado no tiene proceso propio vivo: se conserva tal cual (pid incluido, nunca se mata)
                if job["state"] == "running":
                    previous_reason = job.get("reason")
                    job["state"] = "cancelled" if job.get("cancel_requested") else "review"
                    job["reason"] = (
                        "cancelado por el usuario; ejecución interrumpida"
                        if job.get("cancel_requested")
                        else "ejecución interrumpida; revisar antes de reencolar"
                    )
                    if job.get("kind") == "research" and job.get("pid"):
                        # El PID pudo reutilizarse: nunca se mata un proceso que no lanzó este server.
                        job["reason"] += f"; el PID {job['pid']} registrado no se mata tras el reinicio"
                    job["pid"] = None
                    job["history"] = [
                        *job.get("history", []),
                        {
                            "at": time.time(),
                            "from": "running",
                            "to": job["state"],
                            "reason": previous_reason,
                        },
                    ]

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
                if type(job.get("cancel_requested", False)) is not bool:
                    raise ValueError("cancelación de investigación inválida")
                if job.get("adapter") is not None and job["adapter"] not in REQUESTABLE_ADAPTERS:
                    raise ValueError("adaptador de investigación inválido")
                if type(attempts) is not int or not 0 <= attempts <= MAX_RESEARCH_ATTEMPTS:
                    raise ValueError("intentos de investigación inválidos")
                if not isinstance(job.get("runs"), list) or not all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) for x in job["runs"]
                ):
                    raise ValueError("ejecuciones de investigación inválidas")
                if not isinstance(job.get("history", []), list) or not all(
                    isinstance(x, dict) for x in job.get("history", [])
                ):
                    raise ValueError("historial de investigación inválido")

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

    def enqueue_research(self, project: str, case: dict, *, automatic=False, adapter=None):
        """Un caso por clave en todo el historial (observado, fallido o cancelado no se repite solo) y a lo
        sumo una investigación activa por proyecto. `adapter` lo pide una persona (p. ej. azure-openai);
        sin él, el scheduler elige. Devuelve None si no encola."""
        if not isinstance(case, dict) or not isinstance(case.get("case_key"), str) or case.get("project") != project:
            raise ValueError("caso de investigación inválido")
        if adapter is not None and (automatic or adapter not in REQUESTABLE_ADAPTERS):
            raise ValueError("adaptador de investigación inválido o pedido automático")
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
            if adapter is not None:
                job["adapter"] = adapter
            job.update(created_at=time.time(), source_version=case["case_key"], source_ids=case.get("source_ids"))
            self.jobs.append(job)
            try:
                self.save()
            except OSError:
                self.jobs.pop()
                raise
            return dict(job)

    def research_runs_since(self, since: float, adapter: str | None = None) -> int:
        """Inicios desde `since`; con `adapter`, sólo los de ese adaptador (cada uno tiene su tope diario).
        Un inicio sin adaptador registrado (anterior al registro) cuenta para todos."""
        with self.lock:
            count = 0
            for job in self.jobs:
                if job.get("kind") != "research":
                    continue
                names = job.get("run_adapters") or []
                for i, moment in enumerate(job["runs"]):
                    name = names[i] if i < len(names) else None
                    count += moment >= since and (adapter is None or name in (None, adapter))
            return count

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

    def requeue_research(self, job_id: str, max_starts: int):
        """review -> queued por pedido explícito del usuario. Conserva intentos, corridas e historial:
        un caso agotado no vuelve, y sigue a lo sumo una investigación activa por proyecto."""
        with self.lock:
            job = self._in_review(job_id)
            if job["attempts"] >= max_starts:
                raise ValueError(f"intentos agotados ({job['attempts']} de {max_starts}); el caso no se reencola")
            if any(
                j is not job and j.get("kind") == "research" and j["project"] == job["project"] and j["state"] in ACTIVE
                for j in self.jobs
            ):
                raise ValueError("hay otra investigación activa en el proyecto")
            self._transition(
                job, "queued", f"reencolado por el usuario; conserva intentos {job['attempts']} de {max_starts}"
            )
            return dict(job)

    def dismiss_research(self, job_id: str):
        """review -> cancelled por pedido explícito. El caso sigue en el historial: no vuelve solo y
        sus corridas siguen contando en las 24 h."""
        with self.lock:
            job = self._in_review(job_id)
            self._transition(job, "cancelled", "descartado por el usuario tras revisión")
            return dict(job)

    def _in_review(self, job_id):
        job = next((j for j in self.jobs if j["id"] == job_id), None)
        if job is None or job.get("kind") != "research" or job["state"] != "review":
            raise ValueError("no hay una investigación en revisión con ese id")
        return job

    def cancel_research(self, job_id):
        """La aceptación se persiste bajo el mismo lock que el inicio y el resultado."""
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if job is None or job.get("kind") != "research" or job["state"] not in ACTIVE:
                raise ValueError("no hay una investigación activa con ese id")
            running = job["state"] == "running"
            if running and job.get("cancel_requested"):
                return
            self._transition(
                job,
                "running" if running else "cancelled",
                "cancelación solicitada por el usuario" if running else "cancelado por el usuario antes de ejecutar",
                cancel_requested=running,
            )

    def _transition(self, job, new_state, reason, **values):
        previous = json.loads(json.dumps(job))
        entry = {"at": time.time(), "from": job["state"], "to": new_state, "reason": job.get("reason")}
        job.update(state=new_state, reason=reason, history=[*job.get("history", []), entry], **values)
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
