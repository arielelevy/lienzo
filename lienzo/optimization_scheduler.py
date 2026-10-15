"""Scheduler local y piloto Jev explícito: sin lanzar nuevas CLI."""

from __future__ import annotations

import threading
import time

import agent_evaluation
import conocimiento
import jev
import optimization_activity as activity
import optimization_budget
import optimization_cost
import optimization_experiment as experiment
import optimization_memory as memory
import optimization_pilot as pilot
import state
from optimization_queue import Queue


class Scheduler:
    def __init__(self):
        self.queue = Queue()
        self.last_ui = time.monotonic()
        self.reason = "esperando señales de inactividad"
        self.good_samples = 0
        self.sources = {}
        self.started = {}
        self.tick_lock = threading.Lock()
        self.project_cursor = 0

    def status(self):
        budget = optimization_budget.Budget().status()
        active = bool(budget.get("pilot", {}).get("within_window")) if budget.get("pilot") else False
        adapters = optimization_cost.status()
        ready = active and self.queue.view()["enabled"] and adapters["jev"]["enabled"] and self.good_samples >= 2
        eligible = (
            ready
            and optimization_budget.Budget().pilot_eligible("status-only")
            and not activity.cancellation_reason(self.last_ui)
        )
        return {
            **self.queue.view(),
            "reason": self.reason,
            "paid_enabled": bool(eligible),
            "pilot_enabled": active,
            "budget": budget,
            "adapters": adapters,
            "paid_scope": "piloto Jev métricas; precio y reserva revalidados antes de cada envío",
            "automatic_scope": "hasta 30 incidentes recientes por proyecto; deduplicación por versión, cooldown 120 s, cola máxima 100",
            "new_agents_enabled": False,
            "projects": [{"id": p["id"], "name": p.get("nombre", p["id"])} for p in conocimiento.proyectos()],
        }

    def command(self, data):
        if not isinstance(data, dict):
            raise ValueError("pedido inválido")  # noqa: TRY004 - contrato de validación HTTP
        action = data.get("action")
        if action == "activity" and set(data) == {"action"}:
            self.last_ui = time.monotonic()
        elif action == "configure" and set(data) == {"action", "enabled"}:
            self.queue.configure(data["enabled"])
        elif action == "start_pilot" and set(data) == {"action"}:
            pilot.activate()
        elif action == "enqueue" and set(data) == {"action", "project"}:
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            conocimiento.proyecto(data["project"])
            self.queue.enqueue(data["project"])
        elif action == "enqueue_off_on" and set(data) == {"action", "project"}:
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            for pending in self.queue.view()["jobs"]:
                if pending["project"] == data["project"] and pending["state"] in ("queued", "running", "paused"):
                    if pending.get("kind") == "off_on_local":
                        if pending["state"] == "queued" and pending["cursor"] == 0:
                            version = experiment.manifest()
                            if version != pending["source_version"]:
                                self.queue.change(
                                    pending["id"],
                                    source_version=version,
                                    reason="fuentes renovadas por encolado explícito; sin perfiles ejecutados",
                                )
                        return self.status()
                    raise ValueError("hay un análisis del proyecto pendiente; no se reemplaza")
            project = conocimiento.proyecto(data["project"])
            from pathlib import Path

            if not any(
                Path(p.get("cwd", "")).resolve() == Path(experiment.state.ROOT).resolve()
                for p in project.get("carpetas", [])
            ):
                raise ValueError("ensayo solo disponible para la carpeta local Lienzo")
            job = self.queue.enqueue(data["project"], kind="off_on_local", version=experiment.manifest(), source_ids=[])
            if job.get("kind") != "off_on_local":
                raise ValueError("hay un análisis pendiente; no se reemplaza")
        else:
            raise ValueError("solo actividad, pausa o análisis local; sin comandos, agentes ni pagos")
        return self.status()

    def tick(self, signals=None):
        if not self.tick_lock.acquire(blocking=False):
            return
        try:
            self._tick(activity.snapshot(self.last_ui) if signals is None else signals)
        finally:
            self.tick_lock.release()

    def _tick(self, signals):
        reason = activity.block_reason(signals)
        if not self.queue.view()["enabled"]:
            reason = "pausado por el usuario"
        job = self.queue.next_job()
        if reason:
            self.reason, self.good_samples = reason, 0
            if job and job["state"] == "running":
                self.queue.change(job["id"], state="paused")
            return
        self.good_samples += 1
        if self.good_samples < 2:
            self.reason = "esperando segunda muestra de recursos"
            return
        if job is None:
            self.reason = "sin trabajos en cola"
            if self._pilot_tick():
                return
            self._discover()
            return
        self.reason = "analizando memoria local; sin gasto"
        try:
            self._step(job)
        except Exception as error:
            self.reason = f"análisis detenido: {type(error).__name__}"
            self.queue.change(job["id"], state="failed", reason=self.reason)

    def _pilot_tick(self):
        budget = optimization_budget.Budget()
        status = budget.status()
        if status["blocked"] or not status.get("pilot") or not status["pilot"]["within_window"]:
            return False

        def before_send():
            reason = activity.cancellation_reason(self.last_ui)
            if reason or not self.queue.view()["enabled"]:
                raise ValueError(reason or "pausado por el usuario")

        try:
            with state.lock:
                sessions = [
                    dict(s) for s in state.sessions.values() if s.get("state") == "termino" and s.get("alive") is True
                ]
            for session in sessions:
                report = agent_evaluation.evaluate(session)
                counts = report["evidence"]["counts"]
                if not counts.get("closed") or not counts.get("tools"):
                    continue
                sample = pilot.sample(report, experiment.manifest())
                if not budget.pilot_eligible("jev-pilot:" + sample["snapshot"]):
                    continue
                conocimiento.proyecto(session["repo"])
                before_send()
                decision = jev.pilot_decide(sample["state"], sample["snapshot"], before_send)
                artifact = pilot.save(sample, decision)
                memory.record_jev(session["repo"], artifact, decision)
                self.reason = "Jev observado con costo; hipótesis pendiente de oráculo/veredicto"
                return True
        except Exception as error:
            self.reason = f"piloto detenido: {type(error).__name__}; revisar reserva/evidencia, sin reintento"
            return True
        return False

    def _step(self, job):
        jid = job["id"]
        self.started.setdefault(jid, time.monotonic())
        if time.monotonic() - self.started[jid] >= 30:
            self.queue.change(jid, state="review", reason="plazo local agotado; revisar muestra parcial")
            return
        self.queue.change(jid, state="running")
        if job.get("kind") == "off_on_local":
            self._experiment_step(job)
            return
        if jid not in self.sources:
            self.sources[jid] = (
                job.get("source_ids") if job.get("source_ids") is not None else memory.sources(job["project"])
            )
        if self._cancelled(job):
            return
        refs = self.sources[jid]
        if job["cursor"] >= len(refs):
            evidence = memory.record_analysis(job["project"], jid, job["cursor"], job["results"])
            self.queue.change(
                jid,
                state="observed",
                evidence=evidence,
                reason="análisis local observado; hipótesis sin veredicto humano",
            )
            self.sources.pop(jid, None)
            self.started.pop(jid, None)
            return
        if self._cancelled(job):
            return
        result = memory.propose(job["project"], refs[job["cursor"]])
        results = list(job["results"])
        if result and result not in results:
            results.append(result)
        self.queue.change(jid, cursor=job["cursor"] + 1, results=results)
        self._cancelled(job)  # conservar resultado ya confirmado; pausar después de la transacción

    def _experiment_step(self, job):
        if self._cancelled(job):
            return
        result = experiment.step(job)
        profiles = [*job.get("profiles", []), result]
        self.queue.change(job["id"], cursor=job["cursor"] + 1, profiles=profiles)
        if result["code"]:
            self.queue.change(job["id"], state="review", reason="oráculo local falló; sin reintento automático")
        elif len(profiles) == 2:
            artifact = experiment.save({**job, "profiles": profiles})
            evidence = memory.record_local_experiment(job["project"], artifact, profiles)
            self.queue.change(
                job["id"],
                state="observed",
                evidence=evidence,
                artifact=artifact,
                reason="OFF/ON local observado; calidad de agentes no medida, requiere veredicto",
            )
        else:
            self._cancelled(job)

    def _cancelled(self, job):
        reason = activity.cancellation_reason(self.last_ui)
        if not self.queue.view()["enabled"]:
            reason = "pausado por el usuario"
        if reason:
            self.reason, self.good_samples = reason, 0
            self.queue.change(job["id"], state="paused", reason=reason)
            return True
        return False

    def _discover(self):
        projects = conocimiento.proyectos()
        if not projects or activity.cancellation_reason(self.last_ui):
            return
        project = projects[self.project_cursor % len(projects)]["id"]
        self.project_cursor += 1
        try:
            sample = memory.source_snapshot(project)
            if activity.cancellation_reason(self.last_ui) or not self.queue.view()["enabled"]:
                return
            if sample["ids"]:
                job = self.queue.enqueue(project, version=sample["version"], source_ids=sample["ids"], automatic=True)
                if job:
                    self.reason = "evidencia nueva encolada automáticamente; sin gasto"
        except Exception as error:
            self.reason = f"descubrimiento local bloqueado: {type(error).__name__}"


INSTANCE = None
ERROR = None
INIT_LOCK = threading.Lock()


def get():
    global INSTANCE
    if ERROR:
        raise ValueError(ERROR)
    with INIT_LOCK:
        if INSTANCE is None:
            INSTANCE = Scheduler()
    return INSTANCE


def start(log):
    def loop():
        global ERROR
        try:
            scheduler = get()
            scheduler.queue.activate()
            optimization_budget.Budget().activate()
            while True:
                scheduler.tick()
                time.sleep(2)
        except Exception as error:
            ERROR = f"scheduler detenido: {type(error).__name__}; revisar cola/señales"
            log(ERROR)

    threading.Thread(target=loop, name="optimization", daemon=True).start()
