"""Scheduler local, piloto Jev explícito e investigador CLI bajo su política (optimization_research_policy)."""

from __future__ import annotations

import threading
import time

import agent_evaluation
import conocimiento
import health
import jev
import optimizacion_trabajo as trabajo
import optimization_activity as activity
import optimization_budget
import optimization_cost
import optimization_experiment as experiment
import optimization_memory as memory
import optimization_pilot as pilot
import optimization_research as research
import optimization_research_policy as research_policy
import patrones_desarrollo
import research_creencias as creencias_research
import state
from optimization_queue import ACTIVE, Queue


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
        self.trabajo_visto = {}  # proyecto -> monotonic del ultimo analisis de como se trabaja
        self.research_adapter = research.adapter_for  # proyecto -> adaptador; las pruebas lo reemplazan
        self.research_named = research.adapter_named  # adaptador pedido por trabajo; las pruebas lo reemplazan
        self.research_view = None  # última evaluación de política; un GET no lee la cuota
        self.research_visto = {}  # proyecto -> monotonic de la última selección automática
        self.creencias_visto = {}  # proyecto -> monotonic de la última mirada a su cursor de creencias
        self.creencias_view = {}  # proyecto -> cursor y pendientes de la última mirada; un GET no recorre fuentes
        self.fondo_samples = 0  # muestras seguidas con recursos de sobra mientras hay agentes: no son ratos quietos

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
            "automatic_scope": "hasta 30 incidentes recientes por proyecto; deduplicación por versión, cooldown 120 s, cola máxima 100; "
            "cómo se trabaja (esperas, acuses, avisos repetidos o intermedios, difusiones, pico de sesiones) cada hora por proyecto",
            "new_agents_enabled": bool(self.research_view and self.research_view["enabled"]),
            "research": {
                "last_evaluation": self.research_view,
                "areas": research.AREAS,
                "ceilings": research_policy.CEILINGS,
                "enable_path": research_policy.ENABLE_PATH,
                "scope": "sólo lectura; propuestas sin promoción; Jev filtra y prioriza; sin reintento automático",
                "note": "sin evaluar en este proceso" if self.research_view is None else None,
            },
            "projects": [{"id": p["id"], "name": p.get("nombre", p["id"])} for p in conocimiento.proyectos()],
            "creencias": {
                "scope": "investigador de creencias: mejoras del proceso de desarrollo como creencias propuestas, "
                "contrastadas con el motor lógico; nada pasa a vigente sin veredicto",
                "cada_s": CREENCIAS_CADA_S,
                "fondo": {
                    "admite": list(activity.FONDO_ADMITE),
                    "min_gb": activity.FONDO_GB,
                    "max_cpu_pct": activity.MAX_CPU,
                    "prioridad": "baja",
                    "de_a_uno": True,
                },
                "proyectos": dict(self.creencias_view),
            },
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
        elif action in ("research_check", "enqueue_research") and set(data) - {"adapter"} == {"action", "project"}:
            # `adapter` lo pide una persona para este trabajo (Azure nunca se elige solo: decisión 1)
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            named = data.get("adapter")
            if named is not None and named not in research.NAMED:
                raise ValueError("adaptador pedido desconocido")
            conocimiento.proyecto(data["project"])
            decision = self._research_evaluate(data["project"], named)
            taken = {j["case"]["case_key"] for j in self.queue.view()["jobs"] if j.get("kind") == "research"}
            cases = research.select(data["project"], exclude=taken)
            if action == "research_check":
                return {**self.status(), "research_preview": cases}
            if not decision["enabled"]:
                raise ValueError("investigador bloqueado: " + "; ".join(decision["reasons"]))
            if not cases or not self.queue.enqueue_research(data["project"], cases[0], adapter=named):
                raise ValueError("sin casos nuevos o hay una investigación activa en el proyecto")
        elif action == "enqueue_research_unit" and set(data) == {"action", "project", "folders"}:
            # una ronda, ola o feature que abarca varias carpetas de coordinación (p. ej. dos días)
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            conocimiento.proyecto(data["project"])
            root, folders = research.unit.resolve_folders(data["project"], data["folders"])
            decision = self._research_evaluate(data["project"])
            if not decision["enabled"]:
                raise ValueError("investigador bloqueado: " + "; ".join(decision["reasons"]))
            if not self.queue.enqueue_research(data["project"], research.unit.case(data["project"], root, folders)):
                raise ValueError("esa unidad ya se investigó o hay una investigación activa en el proyecto")
        elif action == "enqueue_creencias" and set(data) == {"action", "project"}:
            # una vuelta de creencias pedida por una persona: la misma política y el mismo tope diario
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            conocimiento.proyecto(data["project"])
            decision = self._research_evaluate(data["project"])
            if not decision["enabled"]:
                raise ValueError("investigador bloqueado: " + "; ".join(decision["reasons"]))
            if not self.queue.enqueue_research(data["project"], creencias_research.case(data["project"])):
                raise ValueError("esa vuelta ya se hizo hoy o hay una investigación activa en el proyecto")
        elif action == "cancel_research" and set(data) == {"action", "job"}:
            self.queue.cancel_research(data["job"])
        elif action in ("requeue_research", "dismiss_research") and set(data) == {"action", "job"}:
            # acciones explícitas sobre un trabajo en revisión; nunca las dispara la cola sola
            if not isinstance(data["job"], str):
                raise ValueError("trabajo inválido")
            job = next((j for j in self.queue.view()["jobs"] if j["id"] == data["job"]), None)
            if job is None or job.get("kind") != "research" or job["state"] != "review":
                raise ValueError("no hay una investigación en revisión con ese id")
            if action == "dismiss_research":
                self.queue.dismiss_research(job["id"])
            else:
                ceiling = research_policy.CEILINGS["max_starts_per_case"]
                if job["attempts"] >= ceiling:
                    raise ValueError(f"intentos agotados ({job['attempts']} de {ceiling}); el caso no se reencola")
                decision = self._research_evaluate(job["project"])
                if not decision["enabled"]:
                    raise ValueError("investigador bloqueado: " + "; ".join(decision["reasons"]))
                self.queue.requeue_research(job["id"], ceiling)
        elif action == "enqueue_off_on" and set(data) == {"action", "project"}:
            if not isinstance(data["project"], str):
                raise ValueError("proyecto inválido")
            for pending in self.queue.view()["jobs"]:
                if pending.get("kind") == "research":
                    continue
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
            raise ValueError(
                "solo actividad, pausa, análisis local, investigador bajo política o revisión explícita; sin comandos ni pagos"
            )
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
        if reason in activity.FONDO_ADMITE:
            self._fondo(signals, reason)
            return
        self.fondo_samples = 0
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
            self._creencias_discover()
            return
        self.reason = "analizando memoria local; sin gasto"
        self._guarded_step(job)

    def _guarded_step(self, job):
        try:
            self._step(job)
        except Exception as error:
            self.reason = f"análisis detenido: {type(error).__name__}"
            with self.queue.lock:
                current = next(j for j in self.queue.view()["jobs"] if j["id"] == job["id"])
                cancelled = current.get("cancel_requested") or current["state"] == "cancelled"
                self.queue.change(
                    job["id"],
                    state="cancelled" if cancelled else "failed",
                    reason=RESEARCH_CANCELLED if cancelled else self.reason,
                )

    def _fondo(self, signals, busy):
        """Agentes trabajando o usuario activo: sólo el investigador de creencias, si sobran recursos, de a
        uno y con prioridad baja (pedido de Ariel, 2026-10-22). Lo demás espera un rato quieto."""
        for job in self.queue.view()["jobs"]:
            if job["state"] == "running" and not _is_creencias(job):
                self.queue.change(job["id"], state="paused")
        self.good_samples = 0  # un rato con agentes no cuenta para arrancar lo que pide quietud
        tight = activity.fondo_reason(signals)
        if tight:
            self.reason, self.fondo_samples = f"{busy}; segundo plano en pausa: {tight}", 0
            return
        self.fondo_samples += 1
        if self.fondo_samples < 2:
            self.reason = "esperando segunda muestra de recursos"
            return
        now = time.time()
        job = next(
            (
                j
                for j in self.queue.view()["jobs"]
                if _is_creencias(j) and j["state"] in ACTIVE and j.get("not_before", 0) <= now
            ),
            None,
        )
        if job is None:
            self.reason = f"{busy}; investigador de creencias sin vuelta pendiente"
            self._creencias_discover()
            return
        self.reason = "investigador de creencias en segundo plano (prioridad baja)"
        self._guarded_step(job)

    def _creencias_discover(self):
        """A lo sumo cada CREENCIAS_CADA_S por proyecto: mira cursores hasta el primer proyecto con algo nuevo
        y le encola una vuelta. Nunca con otra investigación activa: de a una por vez."""
        if not self.queue.view()["enabled"] or any(
            j.get("kind") == "research" and j["state"] in ACTIVE for j in self.queue.view()["jobs"]
        ):
            return
        for project in conocimiento.proyectos():
            pid = project["id"]
            if time.monotonic() - self.creencias_visto.get(pid, -1e9) < CREENCIAS_CADA_S:
                continue
            self.creencias_visto[pid] = time.monotonic()
            try:
                view = creencias_research.estado(pid)
                self.creencias_view[pid] = {**view, "calculado_en": time.time()}
                if not any(view["pendientes"].values()):
                    continue
                decision = self._research_evaluate(pid)
                if not decision["enabled"]:
                    # la política (cuota, tope diario) bloquea a todos: no se relee la cuota proyecto por proyecto
                    self.creencias_visto = {p["id"]: time.monotonic() for p in conocimiento.proyectos()}
                    self.reason = "investigador de creencias bloqueado: " + "; ".join(decision["reasons"])
                elif self.queue.enqueue_research(pid, creencias_research.case(pid, view["pendientes"]), automatic=True):
                    self.reason = f"vuelta de creencias encolada en {pid}"
            except Exception as error:
                self.reason = f"cursor de creencias bloqueado en {pid}: {type(error).__name__}"
            return

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
        if job.get("kind") == "research":
            self._research_step(job)
            return
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
        reason = activity.fondo_stop() if _is_creencias(job) else activity.cancellation_reason(self.last_ui)
        if not self.queue.view()["enabled"]:
            reason = "pausado por el usuario"
        if reason:
            self.reason, self.good_samples = reason, 0
            self.queue.change(job["id"], state="paused", reason=reason)
            return True
        return False

    def _adapter(self, project, named=None):
        """El adaptador pedido para el trabajo, o el que elige la regla (Codex con cuota, si no Claude)."""
        return self.research_named(named, project) if named else self.research_adapter(project)

    def _research_evaluate(self, project, named=None):
        since = time.time() - 86400  # tope diario en 24 h móviles
        adapter = self._adapter(project, named)
        _, decision = research.evaluate(
            project,
            adapter,
            runs_today=self.queue.research_runs_since(since),
            adapter_runs_today=self.queue.research_runs_since(since, adapter.name),
        )
        self.research_view = {**decision, "project": project, "evaluated_at": time.time()}
        return decision

    def _research_stop(self, jid):
        job = next(j for j in self.queue.view()["jobs"] if j["id"] == jid)
        if job.get("cancel_requested"):
            return RESEARCH_CANCELLED
        if not self.queue.view()["enabled"]:
            return RESEARCH_PAUSED
        if _is_creencias(job):
            return activity.fondo_stop()
        reason = activity.cancellation_reason(self.last_ui)
        if reason:
            return reason
        free, _ = health._memoria()
        if free is None or free < health.RESERVA_GB:
            return "recursos insuficientes o memoria desconocida"
        return None

    def _research_step(self, job):
        jid, project = job["id"], job["project"]
        with self.queue.lock:
            job = next(j for j in self.queue.view()["jobs"] if j["id"] == jid)
            if job["state"] not in ("queued", "paused"):
                return
            if job["attempts"] >= research_policy.CEILINGS["max_starts_per_case"]:
                self.queue.change(jid, state="review", reason="intentos agotados; sin reintento automático")
                return
        since = time.time() - 86400
        chosen = self._adapter(project, job.get("adapter"))
        adapter, decision = research.evaluate(
            project,
            chosen,
            runs_today=self.queue.research_runs_since(since),
            adapter_runs_today=self.queue.research_runs_since(since, chosen.name),
        )
        self.research_view = {**decision, "project": project, "evaluated_at": time.time()}
        with self.queue.lock:
            # La política puede tardar: una cancelación aceptada mientras tanto gana.
            job = next(j for j in self.queue.view()["jobs"] if j["id"] == jid)
            if job["state"] not in ("queued", "paused"):
                return
            if not decision["enabled"]:
                reason = "investigador bloqueado: " + "; ".join(decision["reasons"])
                self.reason = reason
                self.queue.change(jid, state="paused", reason=reason, not_before=time.time() + RESEARCH_BACKOFF_S)
                return
            if self._cancelled(job):
                return
            attempts = job["attempts"] + 1
            self.queue.change(
                jid,
                state="running",
                attempts=attempts,
                runs=[*job["runs"], time.time()],
                run_adapters=[*job.get("run_adapters", [None] * len(job["runs"])), adapter.name],
                reason="investigando",
                pid=None,
            )
        self.reason = f"investigando con {adapter.name} (sólo lectura)"
        try:
            outcome = research.investigate(
                {**job, "attempts": attempts},
                adapter,
                decision,
                should_stop=lambda: self._research_stop(jid),
                on_start=lambda pid: self.queue.change(jid, pid=pid),
            )
        finally:
            self.queue.change(jid, pid=None)  # el proceso propio terminó; conservar cancelación persistida
        if outcome["status"] == "ok" and _is_creencias(job):
            # fuera del lock de la cola: el contraste puede despertar WSL y el estado no debe trabarse
            try:
                saved = creencias_research.record(
                    project, job["case"], outcome["result"], outcome["meta"], outcome["lectura"]
                )
                outcome = {**outcome, "saved": saved}
            except Exception as error:
                why = f"registro de la vuelta falló: {type(error).__name__}: {error}"[:300]
                outcome = {**outcome, "status": "failed", "reason": why}
        with self.queue.lock:
            current = next(j for j in self.queue.view()["jobs"] if j["id"] == jid)
            if current.get("cancel_requested"):
                outcome = {**outcome, "status": "stopped", "reason": RESEARCH_CANCELLED}
            self._research_result(job, outcome)

    def _research_result(self, job, outcome):
        """Se registra bajo el lock de cola: cancelar y publicar el resultado tienen un orden único."""
        jid, project = job["id"], job["project"]
        meta, why = outcome.get("meta"), outcome.get("reason")
        if outcome["status"] == "ok" and _is_creencias(job):
            saved = outcome["saved"]
            self.queue.change(
                jid,
                state="observed",
                pid=None,
                evidence=saved["evidence"],
                results=creencias_research.proposals(saved),
                last_run=meta,
                reason="vuelta de creencias registrada; propuestas contrastadas sin veredicto",
            )
            self.reason = "vuelta de creencias registrada; propuestas pendientes de veredicto"
        elif outcome["status"] == "ok":
            saved = research.record(project, job["case"], outcome["result"], meta)
            self.queue.change(
                jid,
                state="observed",
                pid=None,
                evidence=saved["evidence"],
                results=saved["proposals"],
                last_run=meta,
                reason="investigación observada; propuestas sin veredicto",
            )
            self.reason = "investigación registrada; propuestas pendientes de veredicto"
        elif outcome["status"] == "stopped" and why == RESEARCH_CANCELLED:
            evidence = research.record_failure(project, job["case"], meta, why)
            self.queue.change(jid, state="cancelled", pid=None, evidence=evidence, last_run=meta, reason=why)
        elif outcome["status"] == "stopped" and (meta or {}).get("launched") is False:
            # nada se lanzó (tope mensual o ledger): no gasta el inicio del caso ni el tope diario
            self.queue.change(
                jid,
                state="paused",
                pid=None,
                attempts=job["attempts"],
                runs=job["runs"],
                run_adapters=job.get("run_adapters", [None] * len(job["runs"])),
                reason=why,
                not_before=time.time() + RESEARCH_BACKOFF_S,
            )
            self.reason, self.good_samples = why, 0
        elif outcome["status"] == "stopped":
            # un corte del entorno (actividad, agentes, memoria o cuota) pospone: retomar en el próximo
            # tick gastaría el otro inicio del caso en las mismas condiciones. La pausa del usuario no.
            later = {} if why == RESEARCH_PAUSED else {"not_before": time.time() + RESEARCH_BACKOFF_S}
            self.queue.change(jid, state="paused", pid=None, last_run=meta, reason=why, **later)
            self.reason, self.good_samples = why, 0
        else:
            evidence = research.record_failure(project, job["case"], meta, why)
            self.queue.change(jid, state="failed", pid=None, evidence=evidence, last_run=meta, reason=why)
            self.reason = f"investigación fallida: {why}; sin reintento"

    def _research_discover(self, project):
        """A lo sumo cada RESEARCH_EVERY_S por proyecto: elegir el mejor caso nuevo y encolarlo si la
        política lo habilita. Evaluar lee la cuota (sin inferencia)."""
        if time.monotonic() - self.research_visto.get(project, -1e9) < RESEARCH_EVERY_S:
            return
        self.research_visto[project] = time.monotonic()
        try:
            taken = {j["case"]["case_key"] for j in self.queue.view()["jobs"] if j.get("kind") == "research"}
            cases = research.select(project, limit=1, exclude=taken)
            if not cases or activity.cancellation_reason(self.last_ui) or not self.queue.view()["enabled"]:
                return
            if self._research_evaluate(project)["enabled"] and self.queue.enqueue_research(
                project, cases[0], automatic=True
            ):
                self.reason = f"caso de investigación encolado ({cases[0]['area']})"
        except Exception as error:
            self.reason = f"selección de investigación bloqueada: {type(error).__name__}"

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
        self._trabajo(project)
        self._research_discover(project)

    def _trabajo(self, project):
        """Cómo se trabaja en el proyecto (optimizacion_trabajo): a lo sumo cada TRABAJO_CADA_S, en un
        rato quieto, y sólo deja hallazgos propuestos. Lee la memoria; no manda nada ni gasta."""
        if time.monotonic() - self.trabajo_visto.get(project, -1e9) < TRABAJO_CADA_S:
            return
        try:
            analisis = trabajo.analizar(project)
            if activity.cancellation_reason(self.last_ui) or not self.queue.view()["enabled"]:
                return  # sin marcar la hora: lo retoma el proximo rato quieto
            ids = trabajo.registrar(project, analisis)
            patrones_desarrollo.registrar(project, patrones_desarrollo.analizar(project))
            if ids:
                self.reason = f"cómo se trabaja: {len(ids)} hallazgo(s) nuevo(s) en {project}; sin gasto"
        except Exception as error:
            self.reason = f"análisis de cómo se trabaja bloqueado: {type(error).__name__}"
        self.trabajo_visto[project] = time.monotonic()


def _is_creencias(job) -> bool:
    return job.get("kind") == "research" and (job.get("case") or {}).get("kind") == "creencias"


TRABAJO_CADA_S = 3600
CREENCIAS_CADA_S = 1800
RESEARCH_EVERY_S = 1800
RESEARCH_BACKOFF_S = 1800
RESEARCH_CANCELLED = "cancelado por el usuario"
RESEARCH_PAUSED = "pausado por el usuario"

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
