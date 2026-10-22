"""Adaptador azure-openai (decisión 1): tope mensual con ledger, sólo proyectos propios, key del almacén DPAPI,
una llamada sin herramientas. Sin ninguna llamada paga: el hijo real habla con un doble HTTP en 127.0.0.1."""

import http.server
import json
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path

import conocimiento as k
import jev_credentials
import optimization_cost
import optimization_research as r
import optimization_research_ledger as ledger
import optimization_research_policy as policy
import pytest
import research_azure_call
import state
from test_optimization_research import (  # noqa: F401 - fixture autouse
    PROJECT,
    answer,
    good,
    incident,
    isolated,
    write_auth,
)

KEY = "synthetic-azure-key-" + "Q" * 32
CHILD = Path(r.__file__).with_name("research_azure_call.py")


@pytest.fixture(autouse=True)
def own_project(monkeypatch, tmp_path):
    folder = tmp_path / "apps" / PROJECT
    folder.mkdir(parents=True)
    k.registrar_proyecto(PROJECT, carpetas=[{"pc": "ariel", "cwd": str(folder)}])
    auth = {**policy.AZURE_AUTHORIZATION, "proyectos": [PROJECT], "raices_propias": [str(tmp_path / "apps")]}
    monkeypatch.setattr(policy, "AZURE_AUTHORIZATION", auth)
    jev_credentials.store(KEY, "azure-openai")


class Double(http.server.BaseHTTPRequestHandler):
    """Responses API falsa: responde según `mode` y guarda lo que recibió."""

    mode, seen = "ok", []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Double.seen.append({"path": self.path, "key": self.headers.get("api-key"), "body": body})
        if Double.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "https://evil.example.com/")
            self.end_headers()
            return
        if Double.mode == "array":
            out = b"[1, 2]"
            self.send_response(200)
        elif Double.mode == "error":
            out = json.dumps({"error": {"code": "content_filter", "message": "secreto " + KEY}}).encode()
            self.send_response(400)
        else:
            data = json.loads(body["input"].split("CASO:\n", 1)[1])
            text = json.dumps(answer(data) if Double.mode == "ok" else {"case_id": data["case_id"]})
            out = json.dumps(
                {
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
                    "usage": {"input_tokens": 10_000, "output_tokens": 2_000},
                }
            ).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def double():
    Double.mode, Double.seen = "ok", []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Double)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/openai/v1"
    server.shutdown()


class LocalAzure(r.AzureOpenAIAdapter):
    """El adaptador real con el endpoint de la prueba: sólo `command` agrega `local_test` y la URL local."""

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.argv = None

    def command(self, work, root, seconds):
        argv, stdin_text = super().command(work, root, seconds)
        payload = {**json.loads(stdin_text), "base_url": self.url, "local_test": True}
        self.argv = argv
        return argv, json.dumps(payload)


def scheduler_named(adapter):
    import optimization_scheduler as s

    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: pytest.fail("Azure no se elige solo")
    scheduler.research_named = lambda name, project: adapter if name == "azure-openai" else pytest.fail(name)
    return scheduler


def run_ticks(scheduler, n=3):
    for _ in range(n):
        scheduler.tick(good())


# ------------------------------------------------------------------ política


def evaluate(adapter=None):
    return r.evaluate(PROJECT, adapter or r.AzureOpenAIAdapter())[1]


def test_enabled_with_own_project_key_and_ledger_and_budget_is_visible():
    decision = evaluate()
    assert decision["enabled"], decision["reasons"]
    assert decision["budget_granted_usd"] == "5" and decision["limits"]["monthly_budget_usd"] == "5"
    bound = decision["adapter"]["consumption_bound"]
    assert Decimal(decision["service_max_usd"]) == Decimal("1.25") and bound["ledger"]["available_usd"] == "5"
    assert decision["adapter"]["sandbox"] == "no-tools" and decision["adapter"]["budget"]["month"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"proyectos": ["otro"]}, "fuera de los propios"),
        ({"raices_propias": ["Z:/nada"]}, "fuera de las raíces propias"),
        ({"base_url": "https://evil.example.com/openai/v1"}, "endpoint de Azure no permitido"),
        ({"base_url": "http://arielfoundry.cognitiveservices.azure.com/openai/v1"}, "endpoint de Azure no permitido"),
    ],
)
def test_blocked_outside_the_decision(monkeypatch, change, reason):
    monkeypatch.setattr(policy, "AZURE_AUTHORIZATION", {**policy.AZURE_AUTHORIZATION, **change})
    decision = evaluate()
    assert not decision["enabled"] and any(reason in x for x in decision["reasons"])


def test_client_projects_of_the_real_decision_are_excluded():
    for project in ("pepsico_bi", "unicef_bi", "globant", "smarthome", "vidaestilo_bi"):
        assert project not in policy.AZURE_AUTHORIZATION["proyectos"]


def test_missing_key_or_bad_ledger_blocks():
    jev_credentials.path("azure-openai").unlink()
    assert any("py ops/importar-azure.py" in x for x in evaluate()["reasons"])
    jev_credentials.store(KEY, "azure-openai")
    ledger.path().write_bytes(b"no es sqlite" * 50)
    assert any("ledger del investigador ilegible" in x for x in evaluate()["reasons"])


def test_spent_month_blocks_before_launch():
    ledger.reserve("azure-openai", PROJECT, "x", Decimal(4), Decimal(5))
    decision = evaluate()
    assert not decision["enabled"] and any(x.startswith("tope de gasto") for x in decision["reasons"])


def test_a_file_cannot_authorize_azure_spending():
    write_auth(adaptador="azure-openai", uso_semanal_max_pct=None)
    auth, reason = policy.load_authorization()
    assert auth is None and reason == "adaptador no autorizable por archivo"
    assert not evaluate()["enabled"]  # un archivo inválido bloquea a todos


def test_positive_maximum_requires_the_ledger():
    base = {"cancellable": True, "timeout": True}
    bound = {"unit": "usd", "maximum": "1", "verified": True, "basis": "x"}
    with pytest.raises(ValueError, match="ledger"):
        optimization_cost.cli_maximum({**base, "consumption_bound": bound})
    ledger_view = {"read": True, "available_usd": "0.5", "max_usd_per_run": "1.5"}
    with pytest.raises(ValueError, match="tope de gasto"):
        optimization_cost.cli_maximum({**base, "consumption_bound": {**bound, "ledger": ledger_view}})
    ok = {**bound, "ledger": {**ledger_view, "available_usd": "2"}}
    assert optimization_cost.cli_maximum({**base, "consumption_bound": ok}) == "1"
    with pytest.raises(ValueError, match="ledger"):
        optimization_cost.cli_maximum({**base, "consumption_bound": {**bound, "maximum": "-1", "ledger": ledger_view}})


def test_azure_is_never_chosen_automatically(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda _: None)  # sin codex: va a Claude, nunca a Azure
    assert r.adapter_for(PROJECT).name == "claude"
    assert r.adapter_named("azure-openai", PROJECT).name == "azure-openai"
    with pytest.raises(ValueError):
        r.adapter_named("coda-dgx", PROJECT)


# ------------------------------------------------------------------ hijo y red


def test_child_only_talks_https_to_azure():
    assert research_azure_call.allowed("https://arielfoundry.cognitiveservices.azure.com/openai/v1/responses", False)
    assert research_azure_call.allowed("https://x.openai.azure.com/openai/v1/responses", False)
    for url in (
        "http://arielfoundry.cognitiveservices.azure.com/r",
        "https://cognitiveservices.azure.com.evil.com/r",
        "https://evil.com/?h=.openai.azure.com",
        "https://.openai.azure.com/r",
        "http://127.0.0.1:9/r",
    ):
        assert not research_azure_call.allowed(url, False), url
    assert research_azure_call.allowed("http://127.0.0.1:9/r", True)


def test_child_refuses_a_redirect_and_never_prints_the_key(tmp_path, double):
    Double.mode = "redirect"
    payload = {"key": KEY, "base_url": double, "deployment": "d", "max_output_tokens": 10, "prompt": "CASO:\n{}"}
    payload.update(schema=r.SCHEMA, local_test=True, timeout=10)
    run = subprocess.run(
        [sys.executable, "-I", str(CHILD), str(tmp_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert run.returncode == 2 and "HTTP 302" in run.stderr and KEY not in run.stdout + run.stderr
    assert not (tmp_path / "result.json").exists() and len(Double.seen) == 1


# ------------------------------------------------------------------ de punta a punta por la cola


def files_text():
    return "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in Path(state.LIENZO).rglob("*") if p.is_file()
    )


def test_end_to_end_settles_the_real_cost_and_the_key_stays_out_of_disk(double):
    incident()
    adapter = LocalAzure(double)
    scheduler = scheduler_named(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    assert scheduler.queue.view()["jobs"][0]["adapter"] == "azure-openai"
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed", job["reason"]
    assert job["run_adapters"] == ["azure-openai"]
    entry = job["last_run"]["ledger"]
    # 10 000 × 5 + 2 000 × 15 por millón = USD 0.08; la reserva previa fue mayor
    assert entry["state"] == "liquidado" and Decimal(entry["real_usd"]) == Decimal("0.08")
    assert Decimal(entry["reserved_usd"]) > Decimal("0.08")
    assert ledger.status("azure-openai", Decimal(5))["spent_usd"] == "0.08"
    seen = Double.seen[0]
    assert seen["key"] == KEY and seen["body"]["model"] == "gpt-6.1-sol" and seen["path"] == "/openai/v1/responses"
    assert "No tenés herramientas" in seen["body"]["input"] and "Base agéntica" not in seen["body"]["input"]
    assert KEY not in " ".join(adapter.argv) and KEY not in files_text()
    assert k.nodo(PROJECT, job["results"][0])["estado"] == "propuesta"


def test_failed_call_keeps_the_whole_reservation_and_no_secret_leaks(double):
    incident()
    Double.mode = "error"
    scheduler = scheduler_named(LocalAzure(double))
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and "código 2" in job["reason"]
    entry = job["last_run"]["ledger"]
    assert entry["state"] == "desconocido" and entry["real_usd"] is None
    assert ledger.status("azure-openai", Decimal(5))["spent_usd"] == entry["reserved_usd"]
    assert "HTTP 400 (content_filter)" in job["last_run"]["stderr_tail"] and KEY not in files_text()


def test_invalid_answer_is_charged_and_rejected(double):
    incident()
    Double.mode = "invalid"
    scheduler = scheduler_named(LocalAzure(double))
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and "respuesta inválida" in job["reason"]
    assert job["last_run"]["ledger"]["state"] == "liquidado"


def test_reservation_race_postpones_without_launching(double, monkeypatch):
    incident()
    adapter = LocalAzure(double)
    scheduler = scheduler_named(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    real = adapter.reserve

    def spent_meanwhile(case, work):  # otra ejecución gastó el mes entre la evaluación y la reserva
        ledger.reserve("azure-openai", PROJECT, "otro", Decimal("4.9"), Decimal(5))
        return real(case, work)

    monkeypatch.setattr(adapter, "reserve", spent_meanwhile)
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "paused" and job["reason"].startswith("tope mensual") and not Double.seen
    # nada se lanzó: no gasta el inicio del caso ni el tope diario
    assert job["attempts"] == 0 and job["runs"] == [] and scheduler.queue.research_runs_since(0) == 0


def test_oversized_packet_fails_before_sending(double, monkeypatch):
    incident()
    monkeypatch.setattr(policy, "AZURE_AUTHORIZATION", {**policy.AZURE_AUTHORIZATION, "max_prompt_bytes": 500})
    scheduler = scheduler_named(LocalAzure(double))
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and "supera el máximo" in job["reason"] and not Double.seen
    assert ledger.status("azure-openai", Decimal(5))["spent_usd"] == "0"


def test_requested_adapter_is_validated():
    incident()
    scheduler = scheduler_named(None)
    with pytest.raises(ValueError, match="desconocido"):
        scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "coda-dgx"})
    with pytest.raises(ValueError, match="automático"):
        scheduler.queue.enqueue_research(PROJECT, r.select(PROJECT)[0], automatic=True, adapter="azure-openai")


def test_per_run_cap_fails_once_instead_of_postponing(double, monkeypatch):
    incident()
    monkeypatch.setattr(policy, "AZURE_AUTHORIZATION", {**policy.AZURE_AUTHORIZATION, "max_output_tokens": 200_000})
    adapter = LocalAzure(double)
    scheduler = scheduler_named(adapter)
    monkeypatch.setattr(adapter, "ceiling", lambda: Decimal("0.1"))  # la política deja pasar; el paquete no
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "failed" and "por ejecución" in job["reason"] and not Double.seen


def test_nothing_sent_is_settled_at_zero(double, monkeypatch):
    incident()
    adapter = LocalAzure(double)

    def broken():
        raise ValueError("azure-openai no tiene credencial en esta PC")

    adapter.credential_loader = broken
    scheduler = scheduler_named(adapter)
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})
    run_ticks(scheduler)
    assert scheduler.queue.view()["jobs"][0]["state"] == "failed"
    assert ledger.status("azure-openai", Decimal(5))["spent_usd"] == "0"


def test_child_refusing_the_host_reports_zero_usage(tmp_path):
    payload = {"key": KEY, "base_url": "https://evil.example.com/v1", "deployment": "d", "max_output_tokens": 10}
    payload.update(prompt="x", schema={}, timeout=5)
    run = subprocess.run(
        [sys.executable, "-I", str(CHILD), str(tmp_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert run.returncode == 2 and "host no permitido" in run.stderr
    assert r.CodexAdapter.usage(run.stdout) == {"input_tokens": 0, "output_tokens": 0, "sin_envio": 1}
    bad = subprocess.run(
        [sys.executable, "-I", str(CHILD), str(tmp_path)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert bad.returncode == 2 and "entrada inválida" in bad.stderr and "Traceback" not in bad.stderr


def test_child_rejects_a_non_object_response(tmp_path, double):
    Double.mode = "array"
    payload = {"key": KEY, "base_url": double, "deployment": "d", "max_output_tokens": 10, "prompt": "CASO:\n{}"}
    payload.update(schema=r.SCHEMA, local_test=True, timeout=10)
    run = subprocess.run(
        [sys.executable, "-I", str(CHILD), str(tmp_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert run.returncode == 2 and "no es un objeto" in run.stderr and "Traceback" not in run.stderr


def test_ledger_failure_after_the_call_keeps_the_result_and_the_reservation(double, monkeypatch):
    incident()
    scheduler = scheduler_named(LocalAzure(double))
    scheduler.command({"action": "enqueue_research", "project": PROJECT, "adapter": "azure-openai"})

    def locked(*args):
        raise ledger.Unreadable("ledger del investigador ilegible: OperationalError")

    monkeypatch.setattr(ledger, "settle", locked)
    run_ticks(scheduler)
    job = scheduler.queue.view()["jobs"][0]
    assert job["state"] == "observed", job["reason"]
    entry = job["last_run"]["ledger"]
    assert entry["state"] == "reservado" and "OperationalError" in entry["error"]
    assert job["last_run"]["raw_output"]["stdout"]
    assert ledger.status("azure-openai", Decimal(5))["spent_usd"] == entry["reserved_usd"]  # cuenta entera


def test_a_coda_project_cannot_be_sent_to_another_adapter():
    policy.rules_path().write_text(
        json.dumps(
            {"version": 1, "coda_dgx": {"proyectos": [PROJECT], "perfil": "p", "modelo": "m", "herramientas": ["Read"]}}
        ),
        encoding="utf-8",
    )
    import optimization_scheduler as s

    incident()
    for name in ("claude", "codex", "azure-openai"):
        with pytest.raises(ValueError, match="coda-dgx"):
            r.adapter_named(name, PROJECT)
        with pytest.raises(ValueError, match="coda-dgx"):
            s.Scheduler().command({"action": "enqueue_research", "project": PROJECT, "adapter": name})
