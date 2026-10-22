"""Investigador de creencias en segundo plano (encargo S, 2026-10-22): cursor por fuente, respuestas fijas
de la IA (sin llamarla), creencias propuestas contrastadas y arranque con agentes trabajando si sobran
recursos. El adaptador falso lanza un proceso Python real que devuelve una respuesta determinista."""

import json
import os
import sys
import time
from pathlib import Path

import conocimiento as k
import optimization_activity as activity
import optimization_queue
import optimization_research as research
import optimization_research_runner as runner
import optimization_scheduler as s
import prolog_contraste
import pytest
import research_creencias as rc

PROJECT = "creencias-test"
CHILD = r"""
import json, sys
work = sys.argv[1]
json.dump(json.load(open(work + "/fake.json", encoding="utf-8")), open(work + "/result.json", "w", encoding="utf-8"))
"""


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    (root / "review" / "2026-10-22").mkdir(parents=True)
    (root / ".temp" / "coordinacion" / "2026-10-22").mkdir(parents=True)
    k.registrar_proyecto(PROJECT, nombre="Creencias", carpetas=[{"pc": "ariel", "cwd": str(root)}])
    k.registrar_proyecto(rc.PROCESO, nombre="Lienzo")
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))
    monkeypatch.setattr(rc.trabajo, "analizar", lambda pid: {"capturas": 0, "hasta": None, "hallazgos": []})
    monkeypatch.setattr(rc.trabajo, "registrar", lambda pid, a: [])
    monkeypatch.setattr(prolog_contraste, "contrastar", fixed_contrast())
    return root


def fixed_contrast(observations=None, code=200, independent="ausente", ready=False, conclusive=True):
    def contrastar(pid):
        if code != 200:
            return code, {"error": "motor ausente", "code": "prolog_unavailable"}
        with k._abrir(pid) as con:
            ids = [
                r[0]
                for r in con.execute(
                    "SELECT id FROM nodo WHERE proyecto=? AND tipo='decision' AND estado='propuesta'", (pid,)
                )
            ]
        return 200, {
            "concluyente": conclusive,
            "reglas": "contraste-1",
            "motor": "fijo",
            "program_hash": "h",
            "snapshot": "s",
            "candidatos": {
                i: {
                    "observaciones": [{"tipo": t, "con": []} for t in (observations or {}).get("all", [])],
                    "evidencia_independiente": independent,
                    "listo_para_revision": ready,
                }
                for i in ids
            },
        }

    return contrastar


def incident(text="los frentes esperaron a la coordinadora 40 minutos"):
    return k.crear_nodo(PROJECT, "incidente", text, {"herramienta": "lienzo"}, autor="server")["id"]


def belief(data, refs, **over):
    item = {
        "alcance": "proceso_lienzo",
        "dimension": "coordinacion",
        "texto": "Los frentes entregados esperan a una coordinadora ocupada.",
        "accion": "Avisar a la coordinadora con el ESTADO del frente apenas entrega.",
        "contexto": [{"clave": "fase", "valor": "cierre"}],
        "excepciones": "",
        "fuentes": refs,
    }
    item.update(over)
    return item


def answer(data, beliefs=None):
    refs = [f["ref"] for f in data["fuentes"]["memoria"]][:1]
    return {
        "case_id": data["case_id"],
        "leido": "un incidente de espera",
        "conclusiones": ["la espera repite el patrón del 21/10"],
        "creencias": beliefs if beliefs is not None else [belief(data, refs)],
        "limitaciones": ["sin medir la espera real"],
    }


class FakeAdapter:
    name = "claude"
    agent = "claude"
    quota_every = None

    def __init__(self, beliefs=None):
        self.beliefs = beliefs
        self.launched = []

    def limits(self, auth, project):
        return {
            "name": self.name,
            "available": True,
            "sends_to_external_service": True,
            "sandbox": "read-only-tools",
            "cancellable": True,
            "timeout": True,
            "consumption_bound": {"unit": "usd", "maximum": "0", "verified": True, "basis": "falso"},
            "blocked_by": [],
        }

    def command(self, work, root, seconds):
        data = json.loads((work / "prompt.md").read_text(encoding="utf-8").split("CASO:\n", 1)[1])
        assert json.loads((work / "schema.json").read_text(encoding="utf-8")) == rc.SCHEMA
        beliefs = self.beliefs(data) if callable(self.beliefs) else self.beliefs
        (work / "fake.json").write_text(json.dumps(answer(data, beliefs)), encoding="utf-8")
        self.launched.append(data)
        return [sys.executable, "-c", CHILD, str(work)], ""

    def midrun_reason(self):
        return None

    @staticmethod
    def usage(stdout):
        return None


def busy():
    """Agentes trabajando y usuario activo, pero sobran recursos."""
    return {
        "idle_seconds": 5,
        "ui_idle_seconds": 5,
        "cpu_pct": 10,
        "mem_free_gb": 6,
        "pending": False,
        "agents_busy": True,
    }


def scheduler_with(adapter):
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: adapter
    return scheduler


# ------------------------------------------------------------------ cursor


def test_memory_cursor_reads_newest_first_with_cap_and_never_rereads(monkeypatch):
    monkeypatch.setattr(rc, "TOPE", {**rc.TOPE, "memoria": 2})
    ids = [incident(f"incidente {i}") for i in range(5)]
    first, lectura, _ = rc.gather(PROJECT)
    assert [m["ref"] for m in first["fuentes"]["memoria"]] == [ids[4], ids[3]]
    assert first["pendiente_tras_esta_vuelta"]["memoria"] == 3
    rc.save_lectura(PROJECT, lectura)
    k.crear_nodo(PROJECT, "sesion", "ruido", {}, autor="server")  # irrelevante: se marca leído sin mandarse
    newest = incident("nuevo")
    second, lectura, _ = rc.gather(PROJECT)
    assert [m["ref"] for m in second["fuentes"]["memoria"]] == [newest, ids[2]]  # lo nuevo no espera a lo viejo
    rc.save_lectura(PROJECT, lectura)
    third, lectura, _ = rc.gather(PROJECT)
    assert [m["ref"] for m in third["fuentes"]["memoria"]] == [ids[1], ids[0]]
    rc.save_lectura(PROJECT, lectura)
    assert rc.estado(PROJECT)["pendientes"]["memoria"] == 0


def test_files_are_read_once_by_path_and_hash_and_reread_when_they_change(isolated):
    review = isolated / "review" / "2026-10-22" / "code-review-S.md"
    review.write_text("hallazgo: falta pipefail", encoding="utf-8")
    informe = isolated / ".temp" / "coordinacion" / "2026-10-22" / "informe-S.md"
    informe.write_text("ESTADO: esperando a la coordinadora", encoding="utf-8")
    data, lectura, _ = rc.gather(PROJECT)
    assert [f["ref"] for f in data["fuentes"]["review"]] == ["review/2026-10-22/code-review-S.md"]
    assert [f["ref"] for f in data["fuentes"]["coordinacion"]] == [".temp/coordinacion/2026-10-22/informe-S.md"]
    rc.save_lectura(PROJECT, lectura)
    assert rc.estado(PROJECT)["pendientes"]["review"] == 0
    review.write_text("hallazgo: falta pipefail; corregido", encoding="utf-8")
    case, data = pack()
    assert [f["ref"] for f in data["fuentes"]["review"]] == ["review/2026-10-22/code-review-S.md"]
    assert data["fuentes"]["coordinacion"] == []


def test_test_runs_send_only_failures_and_advance_by_run(isolated):
    suite = isolated / "pruebas-agenticas" / "resultados" / "suite-x"
    suite.mkdir(parents=True)
    run = {
        "idCorrida": "c1",
        "estado": "fallo",
        "resultados": [
            {"id": "ok", "codigo": 0, "fallas": []},
            {"id": "roto", "codigo": 1, "error": "WinError 6", "fallas": ["test_x"], "cola": "E   WinError 6"},
        ],
    }
    (suite / "actual.json").write_text(json.dumps(run), encoding="utf-8")
    data, lectura, _ = rc.gather(PROJECT)
    [item] = data["fuentes"]["pruebas"]
    assert [f["id"] for f in item["fallas"]] == ["roto"]
    rc.save_lectura(PROJECT, lectura)
    assert rc.gather(PROJECT)[0]["fuentes"]["pruebas"] == []
    (suite / "actual.json").write_text(json.dumps({**run, "idCorrida": "c2"}), encoding="utf-8")
    assert rc.gather(PROJECT)[0]["fuentes"]["pruebas"][0]["corrida"] == "c2"


def test_uploaded_evidence_content_is_read_and_redacted():
    secret = "ghp_" + "A" * 36
    node = k.recibir_evidencia(
        PROJECT, "coordinacion.md", f"frente esperó; token {secret}".encode(), clase="registro", autor="server"
    )
    data, lectura, _ = rc.gather(PROJECT)
    [item] = data["fuentes"]["evidencia"]
    assert item["ref"] == node["id"] and secret not in item["contenido"] and "redactado" in item["contenido"]
    rc.save_lectura(PROJECT, lectura)
    assert rc.gather(PROJECT)[0]["fuentes"]["evidencia"] == []


# ------------------------------------------------------------------ validación con respuestas fijas


def test_valid_answer_passes_and_unknown_source_discards_only_that_belief():
    incident()
    case, data = pack()
    ref = data["fuentes"]["memoria"][0]["ref"]
    result = answer(data, [belief(data, [ref]), belief(data, ["inventado"], texto="otra")])
    checked = rc.validate(result, data, None)
    assert len(checked["creencias"]) == 1
    assert checked["descartadas_validacion"][0]["motivo"].startswith("fuente fuera del paquete")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(case_id="otro"),
        lambda r: r.update(limitaciones=[]),
        lambda r: r["creencias"][0].update(dimension="producto"),
        lambda r: r["creencias"][0].update(alcance="global"),
        lambda r: r["creencias"][0].update(texto=""),
        lambda r: r.update(extra=1),
    ],
)
def test_invalid_answers_are_rejected(mutate):
    incident()
    case, data = pack()
    result = answer(data)
    mutate(result)
    with pytest.raises(ValueError):
        rc.validate(result, data, None)


# ------------------------------------------------------------------ registro y contraste


def pack():
    case = rc.case(PROJECT)
    return case, rc.packet(case)


def record_with(case, data, lectura, beliefs):
    result = rc.validate(answer(data, beliefs), data, None)
    return rc.record(PROJECT, case, result, {"adapter": "claude"}, lectura)


def test_record_proposes_contrasted_beliefs_and_moves_the_cursor():
    incident()
    case, data = pack()
    lectura = data["lectura"]
    ref = data["fuentes"]["memoria"][0]["ref"]
    own = belief(data, [ref], alcance="proyecto", dimension="pruebas", texto="Las pruebas de UI tardan.")
    saved = record_with(case, data, lectura, [belief(data, [ref]), own])
    by_project = {p["proyecto"]: p for p in saved["creencias"]}
    process = k.nodo(rc.PROCESO, by_project[rc.PROCESO]["id"])
    local = k.nodo(PROJECT, by_project[PROJECT]["id"])
    for node in (process, local):
        assert node["estado"] == "propuesta" and node["datos"]["clase"] == "creencia_operativa"
        assert node["datos"]["contraste"]["resultado"] == "cuestionada"
    assert process["datos"]["alcance"] == "proceso_lienzo"
    assert local["datos"].get("alcance", "proyecto") == "proyecto"
    vuelta = k.nodo(PROJECT, saved["evidence"])
    assert vuelta["datos"]["clase"] == "investigacion_creencias"
    assert vuelta["datos"]["leido"]["memoria"] == [ref]
    assert vuelta["datos"]["conclusiones"] == ["la espera repite el patrón del 21/10"]
    assert saved["evidence"] in local["datos"]["fuentes"] and ref in local["datos"]["fuentes"]
    assert rc.estado(PROJECT)["pendientes"]["memoria"] == 0
    nxt, _, _ = rc.gather(PROJECT)  # la próxima vuelta parte de lo concluido, no de cero
    assert nxt["vueltas_previas"][0]["id"] == saved["evidence"]
    assert {c["texto"] for c in nxt["creencias_existentes"]} >= {"Las pruebas de UI tardan."}


@pytest.mark.parametrize(
    ("observations", "code", "expected"),
    [
        (["contradice"], 200, "contradice"),
        (["respaldo_caido"], 200, "cuestionada"),
        ([], 503, "sin_motor"),
    ],
)
def test_contrast_result_is_kept_in_the_proposal(monkeypatch, observations, code, expected):
    monkeypatch.setattr(prolog_contraste, "contrastar", fixed_contrast({"all": observations}, code))
    incident()
    case, data = pack()
    lectura = data["lectura"]
    ref = data["fuentes"]["memoria"][0]["ref"]
    saved = record_with(case, data, lectura, [belief(data, [ref], alcance="proyecto")])
    node = k.nodo(PROJECT, saved["creencias"][0]["id"])
    assert node["datos"]["contraste"]["resultado"] == expected
    assert node["estado"] == "propuesta"


def test_process_scope_from_another_project_cites_a_mirror_evidence_in_lienzo():
    incident()
    case, data = pack()
    lectura = data["lectura"]
    ref = data["fuentes"]["memoria"][0]["ref"]
    saved = record_with(case, data, lectura, [belief(data, [ref])])
    node = k.nodo(rc.PROCESO, saved["creencias"][0]["id"])
    [mirror] = node["datos"]["fuentes"]
    assert k.nodo(rc.PROCESO, mirror)["datos"]["vuelta"] == saved["evidence"]


# ------------------------------------------------------------------ condición de arranque


def test_fondo_admits_busy_agents_only_with_spare_resources():
    assert activity.block_reason(busy()) == "agentes trabajando o permisos pendientes"
    assert activity.fondo_reason(busy()) is None
    assert activity.fondo_reason({**busy(), "mem_free_gb": 2.9}) == "memoria justa para el segundo plano"
    assert activity.fondo_reason({**busy(), "cpu_pct": 90}) == "CPU ocupada"
    assert activity.fondo_reason({**busy(), "cpu_pct": None}) == "señal desconocida: cpu_pct"


def test_runs_with_busy_agents_when_resources_spare_and_leaves_contrasted_proposal(monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: "agentes trabajando o permisos pendientes")
    incident()
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    scheduler.queue.enqueue("otro")  # un análisis local no corre en segundo plano
    for _ in range(4):
        scheduler.tick(busy())
    jobs = {j.get("kind"): j for j in scheduler.queue.view()["jobs"]}
    assert jobs["analysis"]["state"] == "queued"
    research_job = jobs["research"]
    assert research_job["case"]["kind"] == "creencias" and research_job["state"] == "observed"
    assert len(adapter.launched) == 1
    belief_id = research_job["results"][0]
    assert k.nodo(rc.PROCESO, belief_id)["datos"]["contraste"]["resultado"] == "cuestionada"
    status = scheduler.status()["creencias"]
    assert status["proyectos"][PROJECT]["pendientes"]["memoria"] == 1  # vista calculada antes de la vuelta
    assert status["fondo"]["min_gb"] == activity.FONDO_GB


@pytest.mark.parametrize(
    ("independent", "ready", "expected"),
    [
        ("ausente", False, "cuestionada"),
        ("no_verificada", False, "cuestionada"),
        ("humana", False, "cuestionada"),
        ("humana", None, "cuestionada"),
        ("humana", True, "sostenida"),
    ],
)
def test_support_requires_independent_human_evidence(monkeypatch, independent, ready, expected):
    monkeypatch.setattr(prolog_contraste, "contrastar", fixed_contrast(independent=independent, ready=ready))
    incident()
    case, data = pack()
    saved = record_with(case, data, data["lectura"], [belief(data, [data["fuentes"]["memoria"][0]["ref"]])])
    assert set(saved["contraste"].values()) == {expected}


def test_disagreement_between_engines_never_supports_even_with_human_evidence(monkeypatch):
    monkeypatch.setattr(
        prolog_contraste,
        "contrastar",
        fixed_contrast(
            independent="humana",
            ready=True,
            conclusive=False,
        ),
    )
    incident()
    case, data = pack()
    saved = record_with(case, data, data["lectura"], [belief(data, [data["fuentes"]["memoria"][0]["ref"]])])
    assert set(saved["contraste"].values()) == {"cuestionada"}


def test_tight_memory_or_user_pause_keeps_it_from_starting(monkeypatch):
    incident()
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    for _ in range(4):
        scheduler.tick({**busy(), "mem_free_gb": 2})
    assert not adapter.launched and "memoria justa" in scheduler.reason
    scheduler.command({"action": "configure", "enabled": False})
    for _ in range(4):
        scheduler.tick(busy())
    assert not adapter.launched and scheduler.reason == "pausado por el usuario"


def test_memory_turning_tight_mid_run_pauses_the_job(monkeypatch):
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_creencias", "project": PROJECT})
    monkeypatch.setattr(s.health, "_memoria", lambda: (2.0, 16.0))
    scheduler.tick(busy())
    scheduler.tick(busy())
    [job] = scheduler.queue.view()["jobs"]
    assert job["state"] == "paused" and "memoria justa" in job["reason"]


def test_daily_cap_and_dedup_still_apply(monkeypatch):
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_creencias", "project": PROJECT})
    with pytest.raises(ValueError):
        scheduler.command({"action": "enqueue_creencias", "project": PROJECT})  # una activa por proyecto
    k.registrar_proyecto("otro-sin-activa")
    monkeypatch.setattr(scheduler.queue, "research_runs_since", lambda since, adapter=None: 6)
    with pytest.raises(ValueError, match="tope diario"):
        scheduler.command({"action": "enqueue_creencias", "project": "otro-sin-activa"})


# ------------------------------------------------------------------ cola, runner y adaptador


def test_full_queue_drops_oldest_finished_belief_rounds_only():
    queue = optimization_queue.Queue()
    for i in range(99):
        queue.jobs.append({"id": f"a{i}", "project": "p", "state": "review", "cursor": 0, "results": []})
    queue.jobs.insert(0, {"id": "old", "project": "p", "state": "observed", "cursor": 0, "results": []})
    queue.jobs[0].update(kind="research", case={"kind": "creencias", "case_key": "x"}, attempts=1, runs=[])
    job = queue.enqueue_research("p", {"kind": "creencias", "case_key": "y", "project": "p"})
    assert job and "old" not in {j["id"] for j in queue.jobs} and len(queue.jobs) == 100


@pytest.mark.skipif(os.name != "nt", reason="clase de prioridad de Windows")
def test_runner_launches_with_below_normal_priority(tmp_path):
    code = (
        "import ctypes; k=ctypes.windll.kernel32; k.GetCurrentProcess.restype=ctypes.c_void_p; "
        "k.GetPriorityClass.argtypes=[ctypes.c_void_p]; print(k.GetPriorityClass(k.GetCurrentProcess()))"
    )
    out = runner.run(
        [sys.executable, "-c", code],
        stdin_text="",
        cwd=str(tmp_path),
        timeout=30,
        should_stop=lambda: None,
        max_output=10_000,
    )
    assert int(out["stdout"].strip()) == runner.BELOW_NORMAL


def test_claude_adapter_sends_the_schema_of_the_work(monkeypatch, tmp_path):
    monkeypatch.setattr(research.shutil, "which", lambda _: "claude.exe")
    adapter = research.ClaudeAdapter(quota_reader=lambda: {"ok": False, "error": "x"})
    adapter.limits(None, PROJECT)
    (tmp_path / "prompt.md").write_text("caso", encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(rc.SCHEMA), encoding="utf-8")
    argv, _ = adapter.command(tmp_path, Path("."), 60)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == rc.SCHEMA


def test_retention_guard_reports_what_the_investigator_summarized():
    rc.save_lectura(PROJECT, {"capturas_hasta": "2026-10-20T10:00:00+00:00"})
    assert rc.resguardo_capturas() == {PROJECT: "2026-10-20T10:00:00+00:00"}


# ------------------------------------------------------------------ hallazgos del code review


def test_irrelevant_changes_are_absorbed_without_a_model_round():
    nid = incident()
    _, data = pack()
    rc.save_lectura(PROJECT, data["lectura"])
    k.actualizar_datos(PROJECT, nid, {"nota": 1}, por="server")  # cambio de un nodo ya leído, sin texto nuevo
    k.crear_nodo(PROJECT, "sesion", "ruido", {}, autor="server")
    view = rc.estado(PROJECT)
    assert view["pendientes"]["memoria"] == 0 and view["cursor"]["memoria_absorbidos"] >= 2
    scheduler = scheduler_with(FakeAdapter())
    for _ in range(3):
        scheduler.tick(busy())
    assert scheduler.queue.view()["jobs"] == []


def test_busy_samples_do_not_count_as_quiet_ones(monkeypatch):
    scheduler = scheduler_with(FakeAdapter())
    monkeypatch.setattr(scheduler, "_creencias_discover", lambda: None)
    for _ in range(3):
        scheduler.tick(busy())
    assert scheduler.good_samples == 0
    calls = []
    monkeypatch.setattr(s.memory, "sources", lambda p: ["source"])
    monkeypatch.setattr(s.memory, "propose", lambda *a: calls.append(a) or "hypothesis")
    scheduler.queue.enqueue("p")
    scheduler.tick({**busy(), "idle_seconds": 190, "ui_idle_seconds": 190, "agents_busy": False})
    assert not calls  # primera muestra quieta: todavía no corre


def test_record_failure_leaves_failed_job_with_evidence_and_cursor_untouched(monkeypatch):
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_creencias", "project": PROJECT})

    def broken(*a, **kw):
        raise RuntimeError("base trabada")

    monkeypatch.setattr(rc, "record", broken)
    scheduler.tick(busy())
    scheduler.tick(busy())
    [job] = scheduler.queue.view()["jobs"]
    assert job["state"] == "failed" and "base trabada" in job["reason"] and job.get("evidence")
    assert rc.estado(PROJECT)["cursor"]["vueltas"] == 0


def test_cancel_before_publication_creates_no_beliefs_and_keeps_actual_cursor(monkeypatch):
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_creencias", "project": PROJECT})
    before = rc.cursor(PROJECT)
    original = scheduler.queue.change
    cancelled = []

    def change(jid, **values):
        if values == {"pid": None} and not cancelled:
            cancelled.append(scheduler.command({"action": "cancel_research", "job": jid}))
        return original(jid, **values)

    monkeypatch.setattr(scheduler.queue, "change", change)
    scheduler.tick(busy())
    scheduler.tick(busy())
    assert cancelled
    [job] = scheduler.queue.view()["jobs"]
    assert job["state"] == "cancelled" and job["results"] == []
    assert rc.cursor(PROJECT) == before  # estado() absorbe metadatos irrelevantes al consultar
    for pid in (PROJECT, rc.PROCESO):
        with k._abrir(pid) as con:
            assert con.execute("SELECT count(*) FROM nodo WHERE tipo='decision'").fetchone()[0] == 0
            assert (
                con.execute(
                    "SELECT count(*) FROM nodo WHERE json_extract(datos, '$.clase')='investigacion_creencias'"
                ).fetchone()[0]
                == 0
            )


def test_status_returns_a_copy_of_the_belief_view():
    scheduler = s.Scheduler()
    scheduler.creencias_view["x"] = {"pendientes": {}}
    scheduler.status()["creencias"]["proyectos"]["y"] = {}
    assert set(scheduler.creencias_view) == {"x"}


def test_touched_file_with_same_content_is_not_rehashed_forever(isolated, monkeypatch):
    review = isolated / "review" / "r.md"
    review.write_text("igual", encoding="utf-8")
    _, data = pack()
    rc.save_lectura(PROJECT, data["lectura"])
    os.utime(review, (time.time() + 50, time.time() + 50))
    assert rc.estado(PROJECT)["pendientes"]["review"] == 0
    hashed = []
    monkeypatch.setattr(rc, "_sha", lambda path: hashed.append(path) or "x")
    rc.estado(PROJECT)
    assert hashed == []


def test_full_queue_keeps_belief_rounds_that_ran_today():
    queue = optimization_queue.Queue()
    for i in range(99):
        queue.jobs.append({"id": f"a{i}", "project": "p", "state": "review", "cursor": 0, "results": []})
    queue.jobs.insert(0, {"id": "hoy", "project": "p", "state": "observed", "cursor": 0, "results": []})
    queue.jobs[0].update(kind="research", case={"kind": "creencias", "case_key": "x"}, attempts=1, runs=[time.time()])
    with pytest.raises(ValueError, match="cola llena"):
        queue.enqueue_research("p", {"kind": "creencias", "case_key": "y", "project": "p"})


def test_existing_beliefs_and_proposals_are_context_not_sources():
    """Las creencias de la coordinadora y las propuestas del investigador viejo van como existentes, nunca como
    fuente nueva ni como pendiente (si no, cada una dispararía otra vuelta sobre lo ya propuesto)."""
    nid = incident()
    belief_node = k.crear_nodo(
        PROJECT,
        "decision",
        "Lanzar frentes de interfaz de a uno con Chrome en uso",
        {"clase": "creencia_operativa", "dimension": "coordinacion", "accion": "medir memoria"},
        autor="coordinadora:x",
    )["id"]
    k.crear_nodo(PROJECT, "decision", "Probar RTK", {"clase": "propuesta_investigacion"}, autor="server")
    _, data = pack()
    assert [m["ref"] for m in data["fuentes"]["memoria"]] == [nid]
    assert belief_node in {c["id"] for c in data["creencias_existentes"]}
    rc.save_lectura(PROJECT, data["lectura"])
    assert rc.estado(PROJECT)["pendientes"]["memoria"] == 0
