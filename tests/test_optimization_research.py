"""Investigador CLI: selección, validación, memoria, política y scheduler con un adaptador falso.

El adaptador falso lanza un proceso Python real (sin inferencia ni red) que lee el paquete del caso y
escribe una respuesta determinista; así se prueban timeout, cancelación y pausa sobre un proceso de verdad.
"""

import datetime as dt
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import conocimiento as k
import optimization_research as r
import optimization_research_policy as policy
import optimization_research_quota as quota
import optimization_scheduler as s
import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "research-test"
CHILD = r"""
import json, sys, time
mode, work = sys.argv[1], sys.argv[2]
payload = json.load(open(work + "/fake.json", encoding="utf-8"))
if mode == "sleep":
    time.sleep(60)
if mode == "exit3":
    sys.exit(3)
if mode == "none":
    sys.exit(0)
if mode == "flood":
    while True:
        sys.stdout.write("x" * 4096)
        sys.stdout.flush()
if mode == "big":
    payload["result"]["limitations"] = ["z" * 1000] * 300
if mode == "leak":
    payload["result"]["problem"] = "el log mostró ghp_" + "A" * 36 + " en claro"
out = payload["result"] if mode in ("ok", "big", "leak") else {"case_id": payload["result"]["case_id"]}
json.dump(out, open(work + "/result.json", "w", encoding="utf-8"))
"""


def answer(data, **override):
    first = data["memory_sources"][0]["id"]
    result = {
        "case_id": data["case_id"],
        "areas": [data["area"], "capacidades_ausentes"],
        "problem": "Salidas largas de pytest ocultan el error",
        "causes": [
            {
                "claim": "La salida completa supera el contexto",
                "basis": "inferido",
                "confidence": "baja",
                "sources": [first],
            }
        ],
        "proposals": [
            {
                "title": "Probar RTK con oráculo OFF/ON",
                "problem": "Diagnóstico perdido en salidas largas",
                "scope": "comandos pytest del proyecto",
                "alternative": "resumen manual de la salida",
                "verification": "misma tarea OFF/ON con el mismo oráculo",
                "risk": "perder un diagnóstico",
                "sources": [first, "lienzo/optimization_research.py"],
            }
        ],
        "missing_capabilities": [
            {"capability": "comparar perfiles por tarea", "need": "aislar el efecto", "sources": [first]}
        ],
        "limitations": ["sin ejecutar la tarea; sólo lectura"],
        "not_measured": ["tokens ahorrados"],
        "sources": [
            {"ref": first, "kind": "memoria", "detail": "incidente observado"},
            {"ref": "lienzo/optimization_research.py", "kind": "codigo", "detail": "selección"},
        ],
    }
    result.update(override)
    return result


class FakeAdapter:
    name = "codex"
    agent = "codex"
    quota_every = None

    def __init__(self, mode="ok", bound=True, midrun=None):
        self.mode, self.bound, self.midrun = mode, bound, midrun
        self.launched = []

    def limits(self, auth, project):
        return {
            "name": self.name,
            "available": True,
            "sends_to_external_service": True,
            "sandbox": "read-only",
            "cancellable": True,
            "timeout": True,
            "consumption_bound": {"unit": "usd", "maximum": "0", "verified": True, "basis": "adaptador falso"}
            if self.bound
            else None,
            "blocked_by": [] if self.bound else ["uso semanal 85 % supera el tope 80 %"],
        }

    def command(self, work, root, seconds):
        text = (work / "prompt.md").read_text(encoding="utf-8")
        data = json.loads(text.split("CASO:\n", 1)[1])
        (work / "fake.json").write_text(json.dumps({"result": answer(data)}), encoding="utf-8")
        self.launched.append(work)
        return [sys.executable, "-c", CHILD, self.mode, str(work)], ""

    def midrun_reason(self):
        return self.midrun

    @staticmethod
    def usage(stdout):
        return None


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    k.registrar_proyecto(PROJECT, nombre="Research")
    monkeypatch.setattr(policy, "rules_path", lambda: tmp_path / "investigador-reglas.json")
    monkeypatch.setattr(quota, "read_codex", lambda *a, **kw: pytest.fail("no leer la cuota real en pruebas"))
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))


def incident(text="pytest largo", **data):
    return k.crear_nodo(PROJECT, "incidente", text, {"herramienta": "shell", **data}, autor="server")["id"]


def good():
    return {
        "idle_seconds": 190,
        "ui_idle_seconds": 190,
        "cpu_pct": 10,
        "mem_free_gb": 3,
        "pending": False,
        "agents_busy": False,
    }


def scheduler_with(adapter):
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: adapter
    return scheduler


def run_ticks(scheduler, n=3):
    for _ in range(n):
        scheduler.tick(good())


# ------------------------------------------------------------------ selección


def test_selection_lets_jev_filter_and_prioritize():
    old = incident("viejo")
    k.crear_nodo(PROJECT, "evidencia", "jev dice nada", {"clase": "piloto_jev", "hipotesis": "ninguna"}, autor="server")
    jev = k.crear_nodo(PROJECT, "evidencia", "jev rtk", {"clase": "piloto_jev", "hipotesis": "rtk"}, autor="server")
    finding = k.crear_nodo(
        PROJECT, "hallazgo", "acuses", {"clase": "optimizacion_trabajo", "metrica": "acuses"}, autor="server"
    )
    cases = r.select(PROJECT, limit=10)
    assert [c["origin"] for c in cases] == ["evidencia", "hallazgo", "incidente"]
    assert cases[0]["source_ids"] == [jev["id"]] and cases[0]["selected_by"] == "jev"
    assert cases[1]["area"] == "coordinacion" and cases[1]["source_ids"] == [finding["id"]]
    assert cases[2]["source_ids"] == [old]
    assert r.select(PROJECT, limit=10, exclude={cases[0]["case_key"]})[0]["origin"] == "hallazgo"


def test_own_proposals_are_not_selected_again():
    k.crear_nodo(PROJECT, "decision", "propia", {"clase": "propuesta_investigacion"}, autor="server")
    assert r.select(PROJECT) == []


SECRETS = {
    "sk": "clave sk-proj-" + "a1B2" * 8,
    "github": "token ghp_" + "Z" * 36,
    "jwt": "auth eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4fw",
    "bearer": "Authorization: Bearer abcdefghijklmnop1234",
    "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
    "slack": "xoxb-1234567890-abcdef",
    "google": "AIza" + "B" * 35,
    "url_con_credenciales": "git clone https://ariel:hunter22@example.com/repo.git",
    "asignacion": "DB_PASSWORD=supersecreta123",
    "clave_privada": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize("kind", list(SECRETS))
def test_redact_known_credential_formats(kind):
    counts = {}
    text = r.redact(SECRETS[kind], counts)
    assert f"[redactado:{kind}]" in text and counts == {kind: 1}
    assert SECRETS[kind].split()[-1] not in text or kind in ("asignacion", "url_con_credenciales")


@pytest.mark.parametrize(
    "safe",
    [
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "51e145b5-c6e7-41e3-ab54-e2ffd45c4196",
        "token_count=3 y sk-corto",
        "C:/Users/ArielLevy/.codex/hooks.json",
        "docs sobre password reset y api key rotation",
        "Bearer corto",
    ],
)
def test_redact_leaves_hashes_ids_and_prose(safe):
    counts = {}
    assert r.redact(safe, counts) == safe and counts == {}


def test_packet_redacts_values_and_counts_them():
    incident("falló con " + SECRETS["github"], salida="curl -H 'Authorization: Bearer abcdefghijklmnop1234'")
    data = r.packet(r.select(PROJECT)[0])
    text = json.dumps(data["memory_sources"], ensure_ascii=False)
    assert "ghp_" not in text and "abcdefghijklmnop1234" not in text
    assert data["redactions"] == {"github": 1, "bearer": 1}


def test_packet_drops_secrets_and_rejects_foreign_source():
    nid = incident(api_key="sk-secreto", token_count=3, nota="visible")
    case = r.select(PROJECT)[0]
    data = r.packet(case)
    assert data["memory_sources"][0]["datos"] == {"herramienta": "shell", "nota": "visible"}
    assert "capacidades_ausentes" in data["questions"] and len(data["all_areas"]) == 20
    k.registrar_proyecto("otro-research")
    foreign = k.crear_nodo("otro-research", "incidente", "x", {}, autor="server")["id"]
    with pytest.raises(ValueError, match="otro proyecto"):
        r.packet({**case, "source_ids": [nid, foreign]})


# ------------------------------------------------------------------ validación


@pytest.fixture
def data():
    incident()
    return r.packet(r.select(PROJECT)[0])


def test_valid_answer_passes(data):
    assert r.validate(answer(data), data, ROOT)["case_id"] == data["case_id"]


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda a: a["sources"].append({"ref": "inventado", "kind": "memoria", "detail": "x"}), "no verificable"),
        (lambda a: a["sources"].append({"ref": "../secreto.txt", "kind": "codigo", "detail": "x"}), "no verificable"),
        (
            lambda a: a["sources"].append({"ref": "C:/Windows/win.ini", "kind": "documento", "detail": "x"}),
            "no verificable",
        ),
        (lambda a: a["sources"].append({"ref": "no/existe.py:3", "kind": "codigo", "detail": "x"}), "no verificable"),
        (lambda a: a["sources"].append({"ref": "sesion:ajena", "kind": "traza", "detail": "x"}), "no verificable"),
        (lambda a: a["proposals"][0]["sources"].append("docs/PRODUCTO.md"), "no declarada"),
        (lambda a: a["proposals"][0].update(sources=[]), "sin fuentes"),
        (lambda a: a.update(case_id="otro"), "case_id"),
        (lambda a: a.update(extra=1), "campos"),
        (lambda a: a.update(limitations=[]), "cantidad"),
        (lambda a: a.update(areas=["inventada"]), "enumeración"),
        (lambda a: a["causes"][0].update(confidence=0.9), "texto"),
    ],
)
def test_invalid_answers_are_rejected(data, mutate, message):
    result = answer(data)
    mutate(result)
    with pytest.raises(ValueError, match=message):
        r.validate(result, data, ROOT)


# ------------------------------------------------------------------ memoria


def test_record_keeps_evidence_and_proposals_without_promotion(data):
    case = r.select(PROJECT)[0]
    saved = r.record(PROJECT, case, answer(data), {"adapter": "codex"})
    assert r.record(PROJECT, case, answer(data), {"adapter": "codex"}) == saved
    evidence = k.nodo(PROJECT, saved["evidence"])
    assert evidence["datos"]["clase"] == "investigacion_cli" and evidence["datos"]["requiere_veredicto"]
    assert evidence["datos"]["limitaciones"] and evidence["datos"]["no_medido"] == ["tokens ahorrados"]
    proposal = k.nodo(PROJECT, saved["proposals"][0])
    assert proposal["tipo"] == "decision" and proposal["estado"] == "propuesta"
    assert {"apoya", "motivada_por"} == {v["relacion"] for v in proposal["vinculos"]["salen"]}
    failed = r.record_failure(PROJECT, case, {"attempt": 1}, "plazo agotado")
    assert k.nodo(PROJECT, failed)["datos"]["reintento_automatico"] is False


# ------------------------------------------------------------------ política y cuota


def write_auth(**values):
    now = dt.datetime.now(dt.UTC)
    auth = {
        "version": 1,
        "autorizado_por": "persona:Ariel",
        "fecha": (now - dt.timedelta(hours=1)).isoformat(),
        "vence": (now + dt.timedelta(days=1)).isoformat(),
        "adaptador": "codex",
        "modo": "read_only",
        "max_ejecuciones_dia": 2,
        "max_segundos": 120,
        "envia_a_servicio_externo": True,
        "presupuesto_usd": "0",
        "uso_semanal_max_pct": 70,
    }
    auth.update(values)
    policy.authorization_path().parent.mkdir(parents=True, exist_ok=True)
    policy.authorization_path().write_text(json.dumps(auth), encoding="utf-8")


def limits_of(adapter):
    return adapter.limits(*policy.effective_authorization(adapter.name)[:1], PROJECT)


def test_codex_default_authorization_is_the_conversation_rule():
    decision = policy.evaluate(limits_of(FakeAdapter()))
    assert decision["enabled"] and decision["limits"]["max_weekly_used_pct"] == 80
    assert decision["authorization"]["autorizado_por"] == "persona:Ariel" and decision["budget_granted_usd"] == "0"


def test_file_restricts_codex_and_invalid_file_blocks():
    write_auth()
    decision = policy.evaluate(limits_of(FakeAdapter()), runs_today=1)
    assert decision["limits"]["max_seconds"] == 120 and decision["limits"]["max_weekly_used_pct"] == 70
    assert policy.evaluate(limits_of(FakeAdapter()), runs_today=2)["reasons"] == ["tope diario alcanzado (2 de 2)"]
    write_auth(presupuesto_usd="5")
    assert "presupuesto monetario" in policy.evaluate(limits_of(FakeAdapter()))["reasons"][0]
    write_auth(vence=(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)).isoformat())
    assert policy.evaluate(limits_of(FakeAdapter()))["reasons"] == ["autorización vencida"]


@pytest.mark.parametrize("mode", ["isolated_experiment", "apply"])
def test_experiments_and_apply_stay_blocked(mode):
    assert not policy.evaluate(limits_of(FakeAdapter()), mode=mode)["enabled"]


def test_unbounded_adapter_is_blocked_by_cost_contract():
    decision = policy.evaluate(limits_of(FakeAdapter(bound=False)))
    assert not decision["enabled"] and any("máximo comprobable" in x for x in decision["reasons"])


def test_coda_requires_local_rule_and_signed_zero_cost(tmp_path):
    adapter = r.CodaDgxAdapter()
    adapter.limits = lambda auth, project, real=adapter.limits: {**real(auth, project), "available": True}
    reasons = policy.evaluate(adapter.limits(None, PROJECT))["reasons"]
    assert "proyecto fuera de la regla local de coda-dgx" in reasons
    policy.rules_path().write_text(
        json.dumps(
            {"version": 1, "coda_dgx": {"proyectos": [PROJECT], "perfil": "p", "modelo": "m", "herramientas": ["Read"]}}
        ),
        encoding="utf-8",
    )
    assert policy.adapter_for(PROJECT) == "coda-dgx" and policy.adapter_for("otro") == "codex"
    assert "falta autorización" in policy.evaluate(adapter.limits(None, PROJECT))["reasons"][0]
    write_auth(adaptador="coda-dgx", uso_semanal_max_pct=None, costo_por_uso_usd="0")
    auth = json.loads(policy.authorization_path().read_text(encoding="utf-8"))
    auth.pop("uso_semanal_max_pct")
    policy.authorization_path().write_text(json.dumps(auth), encoding="utf-8")
    decision = policy.evaluate(adapter.limits(policy.effective_authorization("coda-dgx")[0], PROJECT))
    assert decision["enabled"], decision["reasons"]
    assert decision["adapter"]["consumption_bound"]["basis"].startswith("declaración firmada")


SAMPLE = {
    "ordinaryUsageAllowed": True,
    "rateLimits": {
        "primary": {"usedPercent": 33, "windowDurationMins": 10080, "resetsAt": 1792672991},
        "secondary": None,
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "spendControlReached": False,
        "planType": "prolite",
        "rateLimitReachedType": None,
    },
}


def reading(**over):
    return {"ok": True, **quota._parse(SAMPLE), **over}


@pytest.mark.parametrize(
    "over,blocked",
    [
        ({}, None),
        ({"used_pct": 80.0}, None),
        ({"used_pct": 80.5}, "supera el tope"),
        ({"credits_has": True, "credits_balance": "12"}, "créditos"),
        ({"spend_control_reached": None}, "control de gasto"),
        ({"rate_limit_reached_type": "weekly"}, "límite"),
        ({"ok": False, "error": "timeout"}, "desconocida"),
    ],
)
def test_quota_assessment(over, blocked):
    bound, reasons = quota.assess(reading(**over), 80)
    if blocked is None:
        assert bound["maximum"] == "0" and bound["verified"] and not reasons
    else:
        assert bound is None and any(blocked in x for x in reasons)


def test_quota_parse_requires_weekly_window():
    sample = json.loads(json.dumps(SAMPLE))
    sample["rateLimits"]["primary"]["windowDurationMins"] = 300
    with pytest.raises(ValueError, match="semanal"):
        quota._parse(sample)


def test_codex_adapter_uses_live_quota_and_blocks_over_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(r.shutil, "which", lambda _: "codex.exe")
    adapter = r.CodexAdapter(quota_reader=lambda: reading(used_pct=81.0))
    decision = policy.evaluate(adapter.limits(policy.CODEX_AUTHORIZATION, PROJECT))
    assert not decision["enabled"] and any("81 %" in x for x in decision["reasons"])
    adapter = r.CodexAdapter(quota_reader=lambda: reading())
    decision = policy.evaluate(adapter.limits(policy.CODEX_AUTHORIZATION, PROJECT))
    assert decision["enabled"] and decision["service_max_usd"] == "0"
    (tmp_path / "prompt.md").write_text("caso", encoding="utf-8")
    argv, stdin_text = adapter.command(tmp_path, ROOT, 60)
    assert argv[1:5] == ["exec", "--sandbox", "read-only", "--ephemeral"] and argv[-1] == "-"
    assert stdin_text == "caso" and "--output-schema" in argv


# ------------------------------------------------------------------ scheduler de punta a punta


def test_end_to_end_selection_to_visible_proposal():
    source = incident()
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    status = scheduler.command({"action": "research_check", "project": PROJECT})
    assert status["research_preview"][0]["source_ids"] == [source] and status["research"]["last_evaluation"]["enabled"]
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed" and job["attempts"] == 1 and job["last_run"]["code"] == 0
    proposal = k.nodo(PROJECT, job["results"][0])
    assert proposal["estado"] == "propuesta" and proposal["datos"]["investigacion"] == job["evidence"]
    with pytest.raises(ValueError, match="sin casos nuevos"):
        scheduler.command({"action": "enqueue_research", "project": PROJECT})


@pytest.mark.parametrize(
    "mode,reason", [("exit3", "código 3"), ("invalid", "respuesta inválida"), ("none", "no dejó respuesta")]
)
def test_failures_keep_evidence_without_retry(mode, reason):
    incident()
    adapter = FakeAdapter(mode)
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler, 5)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and reason in job["reason"] and len(adapter.launched) == 1
    assert k.nodo(PROJECT, job["evidence"])["datos"]["clase"] == "investigacion_cli_fallida"


def test_output_flood_kills_own_process_and_fails_with_evidence(monkeypatch):
    incident()
    monkeypatch.setitem(policy.CEILINGS, "max_output_bytes", 20_000)
    monkeypatch.setitem(policy.CEILINGS, "max_seconds", 30)  # sin tope de salida, falla por plazo y no cuelga
    scheduler = scheduler_with(FakeAdapter("flood"))
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    started = time.monotonic()
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert time.monotonic() - started < 20 and job["last_run"]["output_exceeded"]
    assert job["state"] == "failed" and job["reason"].startswith("salida mayor a 20000 bytes")
    assert k.nodo(PROJECT, job["evidence"])["datos"]["ejecucion"]["output_exceeded"] is True


def test_oversized_result_file_is_rejected():
    incident()
    scheduler = scheduler_with(FakeAdapter("big"))
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and job["reason"] == f"respuesta mayor a {r.MAX_RESULT_BYTES} bytes"


def test_secret_echoed_by_cli_is_redacted_before_memory():
    incident()
    scheduler = scheduler_with(FakeAdapter("leak"))
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    evidence = k.nodo(PROJECT, job["evidence"])
    assert "ghp_" not in json.dumps(evidence, ensure_ascii=False)
    assert "[redactado:github]" in evidence["texto"]
    assert evidence["datos"]["ejecucion"]["redactions_result"] == {"github": 1}


def test_timeout_kills_own_process_and_fails(monkeypatch):
    incident()
    write_auth(max_segundos=60)
    monkeypatch.setitem(policy.CEILINGS, "max_seconds", 1)
    scheduler = scheduler_with(FakeAdapter("sleep"))
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    started = time.monotonic()
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert time.monotonic() - started < 20
    assert job["state"] == "failed" and job["reason"] == "plazo agotado" and job["last_run"]["timed_out"]


def start_running(scheduler):
    worker = threading.Thread(target=run_ticks, args=(scheduler,))
    worker.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        jobs = scheduler.queue.view()["jobs"]
        if jobs and jobs[0].get("pid"):
            return worker, jobs[0]
        time.sleep(0.05)
    pytest.fail("el proceso falso no arrancó")


def test_user_activity_pauses_and_resume_starts_new_attempt(monkeypatch):
    incident()
    flag = {"active": False}
    monkeypatch.setattr(
        s.activity, "cancellation_reason", lambda _: "actividad del usuario" if flag["active"] else None
    )
    adapter = FakeAdapter("sleep")
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    worker, job = start_running(scheduler)
    flag["active"] = True
    worker.join(15)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["reason"] == "actividad del usuario" and job["pid"] is None
    assert job["last_run"]["stopped"] == "actividad del usuario"
    assert job["not_before"] >= time.time() + s.RESEARCH_BACKOFF_S - 60
    flag["active"] = False
    adapter.mode = "ok"
    run_ticks(scheduler)  # dentro del plazo: no vuelve a arrancar
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["attempts"] == 1 and len(job["runs"]) == 1 and len(adapter.launched) == 1
    scheduler.queue.change(job["id"], not_before=time.time() - 1)  # pasó la espera
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed" and job["attempts"] == 2 and len(job["runs"]) == 2


def test_cancel_running_stops_only_own_process_and_records_evidence():
    incident()
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        scheduler = scheduler_with(FakeAdapter("sleep"))
        scheduler.command({"action": "enqueue_research", "project": PROJECT})
        worker, job = start_running(scheduler)
        scheduler.command({"action": "cancel_research", "job": job["id"]})
        worker.join(15)
        job = scheduler.queue.view()["jobs"][0]
        assert (
            job["state"] == "cancelled" and k.nodo(PROJECT, job["evidence"])["datos"]["motivo"] == s.RESEARCH_CANCELLED
        )
        assert bystander.poll() is None  # el proceso ajeno sigue vivo
    finally:
        bystander.kill()


def test_cancel_queued_and_unknown_job():
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    job = scheduler.queue.view()["jobs"][0]
    scheduler.command({"action": "cancel_research", "job": job["id"]})
    assert scheduler.queue.view()["jobs"][0]["state"] == "cancelled"
    with pytest.raises(ValueError):
        scheduler.command({"action": "cancel_research", "job": job["id"]})


def test_quota_block_mid_run_pauses_with_backoff(monkeypatch):
    incident()
    adapter = FakeAdapter("sleep", midrun="uso semanal 81 % supera el tope 80 %")
    adapter.quota_every = 0.1
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["reason"].startswith("cuota") and job["not_before"] > time.time()
    assert scheduler.queue.next_job() is None


def test_blocked_policy_launches_nothing_and_backs_off():
    incident()
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    adapter.bound = False
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and "bloqueado" in job["reason"] and not adapter.launched
    with pytest.raises(ValueError, match="bloqueado"):
        scheduler_with(adapter).command({"action": "enqueue_research", "project": PROJECT})


def test_attempts_are_bounded():
    incident()
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    job = scheduler.queue.view()["jobs"][0]
    scheduler.queue.change(job["id"], attempts=policy.CEILINGS["max_starts_per_case"], state="paused")
    run_ticks(scheduler)
    assert scheduler.queue.view()["jobs"][0]["state"] == "review" and not adapter.launched


def test_restart_moves_running_to_review_and_never_kills_recorded_pid(monkeypatch):
    incident()
    scheduler = scheduler_with(FakeAdapter())
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    job = scheduler.queue.view()["jobs"][0]
    scheduler.queue.change(job["id"], state="running", pid=4242, attempts=1)
    monkeypatch.setattr(s.research.runner.subproc, "_matar_arbol", lambda p: pytest.fail("no matar"))
    restored = s.Scheduler().queue.view()["jobs"][0]
    assert restored["state"] == "review" and "4242" in restored["reason"]


def test_automatic_discovery_enqueues_once_and_status_get_reads_no_quota(monkeypatch):
    incident()
    monkeypatch.setattr(s.conocimiento, "proyectos", lambda: [{"id": PROJECT}])
    monkeypatch.setattr(s.memory, "source_snapshot", lambda _: {"ids": [], "version": "v"})
    monkeypatch.setattr(s.trabajo, "analizar", lambda _: {})
    monkeypatch.setattr(s.trabajo, "registrar", lambda *a: [])
    monkeypatch.setattr(s.patrones_desarrollo, "analizar", lambda _: {})
    monkeypatch.setattr(s.patrones_desarrollo, "registrar", lambda *a: [])
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    assert scheduler.status()["research"]["last_evaluation"] is None
    run_ticks(scheduler, 6)
    jobs = [j for j in scheduler.queue.view()["jobs"] if j.get("kind") == "research"]
    assert len(jobs) == 1 and jobs[0]["automatic"] and jobs[0]["state"] == "observed"
    run_ticks(scheduler, 4)
    assert len([j for j in scheduler.queue.view()["jobs"] if j.get("kind") == "research"]) == 1


def test_investigator_uses_shared_agent_base_and_keeps_raw_output():
    import agent_improvements
    from tools import breve

    incident()
    agent_improvements.configure({"brief": True, "rtk": True})
    adapter = FakeAdapter()
    scheduler = scheduler_with(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    prompt_text = (adapter.launched[0] / "prompt.md").read_text(encoding="utf-8")
    assert "Base agéntica de Lienzo" in prompt_text and breve.TEXTO in prompt_text
    base = job["last_run"]["base"]
    assert base["preferences"] == {"brief": True, "rtk": True} and base["instructions_applied"]
    assert any("RTK" in w for w in base["warnings"])  # sin RTK en el entorno de prueba: aviso explícito
    for name, path in job["last_run"]["raw_output"].items():
        assert (Path(s.state.LIENZO) / path).is_file(), name


def capture(clase, text, sid="s-uno", agent="codex"):
    return k.capturar(PROJECT, clase, text, {"session_id": sid, "agent": agent, "model": "gpt", "pc": "pc1"})


def test_packet_brings_how_it_happened_from_captures_without_transcripts():
    first = capture("pedido", "Implementá el frente A " + "detalle " * 200)
    capture("respuesta", "Listo, token ghp_" + "Q" * 36 + " visto en el log")
    capture("pedido", "otra sesión", sid="s-ajena")
    k.crear_nodo(
        PROJECT, "incidente", "falló", {"herramienta": "shell"}, autor="server", origen={"session_id": "s-uno"}
    )
    data = r.packet(r.select(PROJECT)[0])
    assert data["trace_refs"] == ["sesion:s-uno"]
    how = data["how_it_happened"]["sesion:s-uno"]
    assert how["eventos_por_clase"] == {"pedido": 1, "respuesta": 1} and how["agente"] == "codex"
    first_event, second = how["eventos"]
    assert first_event["espera_s"] is None and second["espera_s"] is not None and second["espera_s"] >= 0
    assert first_event["bytes"] == first["bytes"] and len(first_event["inicio"]) <= r.HOW_HEAD
    assert "ghp_" not in json.dumps(how) and data["redactions"].get("github") == 1
    assert "sesion:s-ajena" not in data["how_it_happened"]


def test_how_follows_example_captures_of_a_work_finding_and_caps_events(monkeypatch):
    monkeypatch.setattr(r, "HOW_EVENTS", 3)
    ids = [capture("envio", f"aviso {i}", sid="s-coord")["id"] for i in range(5)]
    k.crear_nodo(
        PROJECT,
        "hallazgo",
        "acuses repetidos",
        {"clase": "optimizacion_trabajo", "metrica": "acuses", "capturas_ejemplo": ids[:1]},
        autor="server",
    )
    data = r.packet(r.select(PROJECT)[0])
    how = data["how_it_happened"]["sesion:s-coord"]
    assert len(how["eventos"]) == 3 and how["eventos_anteriores_omitidos"]
    assert [e["inicio"] for e in how["eventos"]] == ["aviso 2", "aviso 3", "aviso 4"]
    assert r.validate(answer(data), data, ROOT)


def test_how_adds_tool_calls_for_local_sessions_and_declares_remote_ones(monkeypatch):
    capture("pedido", "pedido local", sid="s-local")
    capture("pedido", "pedido remoto", sid="s-remota")
    for sid in ("s-local", "s-remota"):
        k.crear_nodo(PROJECT, "incidente", "x", {"herramienta": "shell"}, autor="server", origen={"session_id": sid})
    monkeypatch.setitem(
        s.state.sessions, "s-local", {"session_id": "s-local", "agent": "codex", "transcript_path": "t.jsonl"}
    )
    page = {
        "turns": [
            {
                "id": "t1",
                "ended": True,
                "blocks": [
                    {"kind": "tool", "id": "c1", "name": "shell", "result": {"text": "boom", "is_error": True}},
                    {"kind": "tool", "id": "c2", "name": "read", "result": None},
                ],
            }
        ],
        "meta": {},
    }
    monkeypatch.setattr(r.agent_evaluation.transcripts, "turns", lambda *a, **kw: page)
    cases = {c["source_ids"][0]: c for c in r.select(PROJECT, limit=10)}
    hows = [r.packet(c)["how_it_happened"] for c in cases.values()]
    local = next(h["sesion:s-local"] for h in hows if "sesion:s-local" in h)["herramientas"]
    remote = next(h["sesion:s-remota"] for h in hows if "sesion:s-remota" in h)["herramientas"]
    assert local["disponible"] and local["conteos"]["tools"] == 2 and local["conteos"]["errors"] == 1
    assert local["llamadas"][0] == {"tool": "shell", "characters": 4, "error": True, "result_known": True}
    assert "boom" not in json.dumps(local)  # nombres y tamaños, nunca salidas
    assert remote == {"disponible": False, "motivo": "sesión no conocida en esta PC; consultar la PC dueña"}
