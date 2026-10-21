"""Intentos del investigador: un corte del entorno pospone 30 min, el reinicio conserva lo pausado y
la revisión tiene acciones explícitas. Reencolar conserva intentos, corridas e historial y revalida
la política; descartar sólo lo pide el usuario. Sin investigador real: evaluate e investigate falsos."""

import json
import time
from types import SimpleNamespace

import optimization_research_policy as policy
import optimization_scheduler as s
import pytest
from optimization_queue import Queue

MAX = policy.CEILINGS["max_starts_per_case"]
ENTORNO = (
    "recursos insuficientes o memoria desconocida",
    "agentes trabajando o permisos pendientes",
    "actividad del usuario",
    "cuota: uso semanal 81 % supera el tope 80 %",
)


def case(key="k1", project="p"):
    return {"case_key": key, "project": project, "area": "herramientas", "source_ids": ["n1"]}


def good():
    return {
        "idle_seconds": 190,
        "ui_idle_seconds": 190,
        "cpu_pct": 10,
        "mem_free_gb": 3,
        "pending": False,
        "agents_busy": False,
    }


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))


@pytest.fixture
def scheduler(monkeypatch):
    sch = s.Scheduler()
    sch.research_adapter = lambda project: SimpleNamespace(name="falso")
    sch.decision = {"enabled": True, "reasons": []}
    sch.outcome = {"status": "stopped", "reason": ENTORNO[0], "meta": {"stopped": ENTORNO[0]}}
    sch.calls, sch.evaluations = [], []

    def evaluate(project, adapter, runs_today):
        sch.evaluations.append(project)
        return adapter, dict(sch.decision)

    def investigate(job, adapter, decision, should_stop, on_start):
        sch.calls.append(job["attempts"])
        return dict(sch.outcome)

    monkeypatch.setattr(s.research, "evaluate", evaluate)
    monkeypatch.setattr(s.research, "investigate", investigate)
    return sch


def research_job(sch):
    return next(j for j in sch.queue.view()["jobs"] if j.get("kind") == "research")


def in_review(sch, attempts=1, key="k1", project="p"):
    job = sch.queue.enqueue_research(project, case(key, project))
    sch.queue.change(
        job["id"],
        state="review",
        attempts=attempts,
        runs=[time.time() - 60] * attempts,
        reason="ejecución interrumpida",
    )
    return job["id"]


# --- D1: un corte del entorno pospone; no se gasta el segundo inicio en las mismas condiciones


@pytest.mark.parametrize("why", ENTORNO)
def test_corte_del_entorno_pospone_30_min_y_no_reintenta_enseguida(scheduler, why):
    scheduler.outcome = {"status": "stopped", "reason": why, "meta": {"stopped": why}}
    scheduler.queue.enqueue_research("p", case())
    for _ in range(6):
        scheduler.tick(good())
    job = research_job(scheduler)
    assert scheduler.calls == [1]
    assert job["state"] == "paused" and job["reason"] == why
    assert job["attempts"] == 1 and len(job["runs"]) == 1
    assert job["not_before"] >= time.time() + s.RESEARCH_BACKOFF_S - 60


def test_pausa_del_usuario_no_pospone(scheduler):
    why = "pausado por el usuario"
    scheduler.outcome = {"status": "stopped", "reason": why, "meta": {"stopped": why}}
    scheduler.queue.enqueue_research("p", case())
    scheduler.tick(good())
    scheduler.tick(good())
    job = research_job(scheduler)
    assert job["state"] == "paused" and job.get("not_before", 0) <= time.time()


def test_tras_la_espera_retoma_y_el_tope_de_inicios_sigue_igual(scheduler):
    scheduler.queue.enqueue_research("p", case())
    for _ in range(3):
        scheduler.tick(good())
    jid = research_job(scheduler)["id"]
    scheduler.queue.change(jid, not_before=time.time() - 1)  # pasó la espera
    for _ in range(3):
        scheduler.tick(good())
    job = research_job(scheduler)
    assert scheduler.calls == [1, 2] and job["attempts"] == MAX
    scheduler.queue.change(jid, not_before=time.time() - 1)
    scheduler.tick(good())
    job = research_job(scheduler)
    assert job["state"] == "review" and "intentos agotados" in job["reason"] and scheduler.calls == [1, 2]


# --- D3: el reinicio conserva lo pausado; un running sigue pasando a revisión


def test_reinicio_conserva_pausado_y_su_pid_sin_matar():
    q = Queue()
    job = q.enqueue_research("p", case())
    q.change(job["id"], state="paused", attempts=1, runs=[time.time()], reason="actividad del usuario", pid=999999)
    restored = Queue().view()["jobs"][0]
    assert restored["state"] == "paused" and restored["reason"] == "actividad del usuario"
    assert restored["attempts"] == 1 and restored["pid"] == 999999


def test_reinicio_conserva_analisis_pausado():
    q = Queue()
    job = q.enqueue("p")
    q.change(job["id"], state="paused", cursor=3, reason="usuario volvió")
    restored = Queue().view()["jobs"][0]
    assert restored["state"] == "paused" and restored["cursor"] == 3


def test_reinicio_sigue_mandando_running_a_revision():
    q = Queue()
    job = q.enqueue_research("p", case())
    q.change(job["id"], state="running", pid=999999)
    restored = Queue().view()["jobs"][0]
    assert restored["state"] == "review" and "999999" in restored["reason"]


# --- D2: acciones explícitas sobre un trabajo en revisión


def test_reencolar_conserva_intentos_corridas_e_historial_y_revalida(scheduler):
    jid = in_review(scheduler, attempts=1)
    runs = research_job(scheduler)["runs"]
    scheduler.command({"action": "requeue_research", "job": jid})
    job = research_job(scheduler)
    assert job["state"] == "queued" and job["attempts"] == 1 and job["runs"] == runs
    assert job["history"][-1]["from"] == "review" and job["history"][-1]["reason"] == "ejecución interrumpida"
    assert "reencolado por el usuario" in job["reason"]
    assert scheduler.evaluations == ["p"]


def test_reencolar_un_caso_agotado_se_rechaza_con_motivo_claro(scheduler):
    jid = in_review(scheduler, attempts=MAX)
    before = research_job(scheduler)
    with pytest.raises(ValueError, match=f"intentos agotados \\({MAX} de {MAX}\\)"):
        scheduler.command({"action": "requeue_research", "job": jid})
    assert research_job(scheduler) == before
    assert scheduler.evaluations == []  # ni siquiera lee la cuota


def test_reencolar_con_politica_bloqueada_no_cambia_nada(scheduler):
    jid = in_review(scheduler, attempts=1)
    scheduler.decision = {"enabled": False, "reasons": ["uso semanal 85 % supera el tope 80 %"]}
    before = research_job(scheduler)
    with pytest.raises(ValueError, match="bloqueado"):
        scheduler.command({"action": "requeue_research", "job": jid})
    assert research_job(scheduler) == before


def test_reencolar_con_otra_investigacion_activa_en_el_proyecto(scheduler):
    jid = in_review(scheduler, attempts=1)
    scheduler.queue.enqueue_research("p", case("k2"))
    with pytest.raises(ValueError, match="activa"):
        scheduler.command({"action": "requeue_research", "job": jid})
    assert next(j for j in scheduler.queue.view()["jobs"] if j["id"] == jid)["state"] == "review"


def test_descartar_conserva_contabilidad_y_deduplicacion(scheduler):
    jid = in_review(scheduler, attempts=MAX)
    since = time.time() - 86400
    runs_before = scheduler.queue.research_runs_since(since)
    scheduler.command({"action": "dismiss_research", "job": jid})
    job = research_job(scheduler)
    assert job["state"] == "cancelled" and job["attempts"] == MAX and len(job["runs"]) == MAX
    assert job["history"][-1]["from"] == "review" and "descartado por el usuario" in job["reason"]
    assert scheduler.queue.research_runs_since(since) == runs_before
    assert scheduler.queue.enqueue_research("p", case()) is None  # el caso no vuelve solo
    assert scheduler.evaluations == []


@pytest.mark.parametrize("action", ["requeue_research", "dismiss_research"])
@pytest.mark.parametrize("state", ["queued", "running", "paused", "observed", "failed", "cancelled"])
def test_acciones_solo_sobre_revision(scheduler, action, state):
    jid = in_review(scheduler)
    scheduler.queue.change(jid, state=state)
    with pytest.raises(ValueError, match="revisión"):
        scheduler.command({"action": action, "job": jid})
    assert research_job(scheduler)["state"] == state


@pytest.mark.parametrize("action", ["requeue_research", "dismiss_research"])
def test_acciones_rechazan_analisis_desconocidos_y_campos_extra(scheduler, action):
    analysis = scheduler.queue.enqueue("p")
    scheduler.queue.change(analysis["id"], state="review")
    jid = in_review(scheduler, key="k9", project="q")
    for data in (
        {"action": action, "job": analysis["id"]},
        {"action": action, "job": "no-existe"},
        {"action": action, "job": jid, "attempts": 0},
        {"action": action, "job": 3},
    ):
        with pytest.raises(ValueError):
            scheduler.command(data)
    assert next(j for j in scheduler.queue.view()["jobs"] if j["id"] == jid)["state"] == "review"


def test_falla_al_guardar_no_deja_la_accion_a_medias(scheduler, monkeypatch):
    jid = in_review(scheduler, attempts=1)
    before = research_job(scheduler)

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(scheduler.queue, "save", fail)
    for action in ("requeue_research", "dismiss_research"):
        with pytest.raises(OSError):
            scheduler.command({"action": action, "job": jid})
        assert research_job(scheduler) == before


def test_historial_corrupto_es_visible():
    q = Queue()
    job = q.enqueue_research("p", case())
    q.path.write_text(
        json.dumps({"enabled": True, "jobs": [{**q.view()["jobs"][0], "id": job["id"], "history": ["x"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        Queue()
