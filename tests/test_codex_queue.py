"""Transporte `codex queue` (CLI y app de Codex) y su elección en sessions. Sin codex real: `subproc.correr` se
reemplaza por un doble que registra el argv y, si se le pide, escribe el mensaje en el rollout como lo hace Codex."""

import json
import time

import codex_queue as cq
import pytest
import sessions as ses

THREAD = "01a14a70-1105-73b3-87ce-7a60b4b925fd"
QUEUE_ID = "01a14a71-0eac-73b1-a211-162a130dca2f"
PROCESS_START = 134367484919993003


def iso_now():
    return cq._iso(time.time())


def user_line(text):
    payload = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
    return json.dumps({"timestamp": iso_now(), "type": "response_item", "payload": payload})


class FakeCodex:
    def __init__(self, rollout, deliver=True, code=0, stderr=""):
        self.rollout, self.deliver, self.code, self.stderr = rollout, deliver, code, stderr
        self.calls = []

    def __call__(self, argv, timeout, **kw):
        self.calls.append((argv, timeout, kw))
        if self.code:
            return self.code, "", self.stderr
        if self.deliver:
            with open(self.rollout, "a", encoding="utf-8") as fh:
                fh.write(user_line(argv[argv.index("--message") + 1] + "\n") + "\n")
        return 0, f"Queued message {QUEUE_ID} for thread {argv[argv.index('--thread') + 1]}.\n", ""


@pytest.fixture
def card(tmp_path, monkeypatch):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": THREAD}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cq, "codex_exe", lambda: r"C:\codex\codex.exe")
    monkeypatch.setattr(cq.procinfo, "alive", lambda pid: pid == 4242)
    # Prueba independiente de la tarjeta: cambiar su hilo/PID/FILETIME debe rechazar.
    proof = {"verified": True, "pid": 4242, "process_start": PROCESS_START,
             "thread": THREAD, "path": str(rollout)}

    def probe(pid):
        assert pid == 4242, "el transporte consultó otro proceso"
        return dict(proof)

    monkeypatch.setattr(cq.codex_identity, "probe", probe)
    monkeypatch.setattr(cq, "store_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(cq, "app_running", lambda: True)
    logs = []
    monkeypatch.setattr(cq.state, "log", logs.append)
    import os

    os.makedirs(ses.state.SESSIONS, exist_ok=True)  # touch() guarda la tarjeta ahí
    s = {"session_id": THREAD, "agent": "codex", "pid": 4242, "transcript_path": str(rollout), "external": None,
         "codex_process_start": PROCESS_START}
    return {"s": s, "rollout": rollout, "logs": logs}


def desktop(card):
    return {**card["s"], "pid": None, "no_console": True, "external": dict(ses.CODEX_DESKTOP)}


# ------------------------------------------------------------------ puede_enviar


def test_live_cli_and_open_app_can_use_the_queue(card):
    assert cq.puede_enviar(card["s"]) == {"puede": True, "motivo": None, "transporte": "codex_queue"}
    assert cq.puede_enviar(desktop(card))["transporte"] == "codex_queue"


@pytest.mark.parametrize(
    "change,fragment",
    [
        ({"agent": "claude"}, "no es una sesión de Codex"),
        ({"session_id": "pid-4242"}, "id de hilo"),
        ({"transcript_path": "no/existe.jsonl"}, "rollout"),
        ({"pid": 999}, "el proceso del hilo terminó"),
        ({"pid": None}, "el proceso del hilo terminó"),
    ],
)
def test_rejections_carry_a_reason(card, change, fragment):
    plan = cq.puede_enviar({**card["s"], **change})
    assert plan["puede"] is False and fragment in plan["motivo"] and plan["transporte"] is None


def test_desktop_thread_needs_the_app_open_and_codex_must_be_native(card, monkeypatch):
    monkeypatch.setattr(cq, "app_running", lambda: False)
    assert "la app de Codex no está abierta" in cq.puede_enviar(desktop(card))["motivo"]
    monkeypatch.setattr(cq, "codex_exe", lambda: None)
    assert "codex.exe" in cq.puede_enviar(card["s"])["motivo"]
    monkeypatch.setattr(cq.shutil, "which", lambda name: r"C:\npm\codex.cmd")
    monkeypatch.undo()
    monkeypatch.setattr(cq.shutil, "which", lambda name: r"C:\npm\codex.cmd")
    assert cq.codex_exe() is None  # un .cmd haría pasar el texto por cmd.exe


# ------------------------------------------------------------------ enviar


def test_delivered_when_text_shows_up_in_rollout_and_argv_has_no_shell(card, monkeypatch):
    fake = FakeCodex(card["rollout"])
    monkeypatch.setattr(cq.subproc, "correr", fake)
    message = 'línea uno\nlínea dos "comillas" $HOME %PATH% & | < > ^ ! 🙂'
    res = cq.enviar(card["s"], message)
    assert res["estado"] == "entregado" and res["referencia"] == QUEUE_ID and res["transporte"] == "codex_queue"
    argv, timeout, _ = fake.calls[0]
    assert argv == [r"C:\codex\codex.exe", "queue", "--thread", THREAD, "--message", message.strip()]
    assert timeout == cq.QUEUE_TIMEOUT
    assert message not in " ".join(card["logs"]) and "entregado" in card["logs"][-1]


def test_queued_but_unconfirmed_stays_queued_then_becomes_visible(card, monkeypatch):
    fake = FakeCodex(card["rollout"], deliver=False)
    monkeypatch.setattr(cq.subproc, "correr", fake)
    res = cq.enviar(card["s"], "hola", esperar=0.3)
    assert res["estado"] == "encolado" and res["referencia"] == QUEUE_ID
    assert cq.confirmar(res["envio_id"])["estado"] == "encolado"
    with open(card["rollout"], "a", encoding="utf-8") as fh:
        fh.write(user_line("hola\n") + "\n")
    assert cq.confirmar(res["envio_id"])["estado"] == "entregado"
    res2 = cq.enviar(card["s"], "otro", esperar=0.1)
    data = cq._load()
    data[res2["envio_id"]]["at"] -= cq.CONFIRM_LIMIT_S + 1
    cq._save(data)
    late = cq.confirmar(res2["envio_id"])
    assert late["estado"] == "sin_confirmacion" and "no se reintenta" in late["motivo"]
    assert len(fake.calls) == 2  # confirmar nunca encola de nuevo


def test_same_send_is_never_queued_twice_even_if_already_delivered(card, monkeypatch):
    fake = FakeCodex(card["rollout"], deliver=False)
    monkeypatch.setattr(cq.subproc, "correr", fake)
    first = cq.enviar(card["s"], "repetido", esperar=0.1)
    second = cq.enviar(card["s"], "repetido", esperar=0.1)
    assert len(fake.calls) == 1 and second["estado"] == "encolado" and "no se encola de nuevo" in second["motivo"]
    assert second["envio_id"] == first["envio_id"]
    fake.deliver = True
    delivered = cq.enviar(card["s"], "ok", esperar=1)
    again = cq.enviar(card["s"], "ok", esperar=1)  # doble clic tras una entrega rápida (medido en la prueba real)
    assert delivered["estado"] == again["estado"] == "entregado" and len(fake.calls) == 2
    data = cq._load()
    data[delivered["envio_id"]]["at"] -= cq.DUPLICATE_S + 1
    cq._save(data)
    cq.enviar(card["s"], "ok", esperar=1)
    assert len(fake.calls) == 3  # pasado el plazo, repetir a propósito sí se encola
    cq.enviar(card["s"], "ok", {"envio_id": "otro-envio"}, esperar=1)
    assert len(fake.calls) == 4  # o con otro envio_id


def test_codex_error_is_rejected_without_leaking_the_message(card, monkeypatch):
    secret_text = "texto privado del usuario"
    fake = FakeCodex(card["rollout"], code=1, stderr=f"Error: failed for {secret_text}: no rollout found (code -32603)")
    monkeypatch.setattr(cq.subproc, "correr", fake)
    res = cq.enviar(card["s"], secret_text)
    assert res["estado"] == "rechazado" and "código 1" in res["motivo"] and "[mensaje]" in res["motivo"]
    assert secret_text not in res["motivo"] and secret_text not in " ".join(card["logs"])


def test_wrong_thread_in_confirmation_line_is_uncertain(card, monkeypatch):
    monkeypatch.setattr(
        cq.subproc, "correr", lambda argv, timeout, **kw: (0, f"Queued message {QUEUE_ID} for thread {QUEUE_ID}.", "")
    )
    assert cq.enviar(card["s"], "x")["estado"] == "sin_confirmacion"


@pytest.mark.parametrize("message,fragment", [("   ", "vacío"), ("a" * (cq.MAX_MESSAGE + 1), "adjunto")])
def test_empty_and_too_long_are_rejected_before_calling_codex(card, monkeypatch, message, fragment):
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: pytest.fail("no debe llamar a codex"))
    res = cq.enviar(card["s"], message)
    assert res["estado"] == "rechazado" and fragment in res["motivo"]


def test_enviar_rechecks_the_target(card, monkeypatch):
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: pytest.fail("no debe llamar a codex"))
    res = cq.enviar({**card["s"], "pid": 999}, "hola")
    assert res["estado"] == "rechazado" and "proceso del hilo terminó" in res["motivo"]


# ------------------------------------------------------------------ sessions: elección de transporte y envío


def test_sessions_facade_chooses_transport(card):
    s = card["s"]
    assert ses.puede_enviar(s)["transporte"] == "codex_queue"
    assert ses.puede_enviar(desktop(card))["transporte"] == "codex_queue"
    stopped = ses.puede_enviar({**s, "stopped_by": "coord"})
    assert not stopped["puede"] and "detenida" in stopped["motivo"]
    claude_desktop = {
        **s,
        "agent": "claude",
        "pid": None,
        "external": {"kind": "claude-desktop", "desktop": True, "canal": "lienzo-C"},
    }
    plan = ses.puede_enviar(claude_desktop)
    assert (
        plan == {"puede": False, "motivo": plan["motivo"], "transporte": "claude_pipe"}
        and "adaptador" in plan["motivo"]
    )
    orchestrated = ses.puede_enviar({**s, "external": {"kind": "stepwise"}})
    assert not orchestrated["puede"] and "stepwise" in orchestrated["motivo"]


def test_cli_without_known_thread_rejects_without_typing(card, monkeypatch):
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("identidad incierta no habilita tecleo"))
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: pytest.fail("identidad incierta no habilita cola"))
    s = {**card["s"], "session_id": "pid-4242", "transcript_path": None}
    plan = ses.puede_enviar(s)
    assert plan == {"puede": False, "motivo": plan["motivo"], "transporte": None}
    assert "id de hilo" in plan["motivo"]
    code, body = ses.send_to_session(s, "hola", [])
    assert code == 409 and "id de hilo" in body["error"]


@pytest.mark.parametrize("change,reason", [
    ({"codex_process_start": PROCESS_START + 1}, "PID reciclado"),
    ({"session_id": QUEUE_ID}, "otro rollout activo"),
])
def test_verified_double_does_not_follow_changes_to_the_card(card, monkeypatch, change, reason):
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **k: pytest.fail("no debe encolar"))
    result = cq.enviar({**card["s"], **change}, "hola")
    assert result["estado"] == "rechazado" and reason in result["motivo"]


def test_send_to_desktop_thread_goes_by_queue_never_by_typing(card, monkeypatch):
    fake = FakeCodex(card["rollout"])
    monkeypatch.setattr(cq.subproc, "correr", fake)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("la app nunca se teclea"))
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **k: None)
    monkeypatch.setattr(ses, "_mirror_owner", lambda sid: None)
    s = desktop(card)
    with ses.lock:
        ses.sessions[THREAD] = s
    try:
        code, body = ses.send_to_session(s, "hola desde Lienzo", [])
        assert code == 200 and body["transporte"] == "codex_queue" and body["estado"] == "entregado"
        assert s["envio_codex"]["referencia"] == QUEUE_ID and s["prompt_via"] == "lienzo"
        monkeypatch.setattr(cq, "app_running", lambda: False)
        code, body = ses.send_to_session(s, "otra", [])
        assert code == 409 and "app de Codex no está abierta" in body["error"] and len(fake.calls) == 1
    finally:
        with ses.lock:
            ses.sessions.pop(THREAD, None)


def test_long_text_goes_as_attachment_by_queue(card, monkeypatch):
    fake = FakeCodex(card["rollout"])
    monkeypatch.setattr(cq.subproc, "correr", fake)
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **k: None)
    monkeypatch.setattr(ses, "_mirror_owner", lambda sid: None)
    s = dict(card["s"])
    with ses.lock:
        ses.sessions[THREAD] = s
    try:
        code, body = ses.send_to_session(s, "x" * (cq.MAX_MESSAGE + 10), [])
        sent = fake.calls[0][0][-1]
        assert code == 200 and sent.startswith(ses.ATTACH_WRAPPER) and "Adjunto: " in sent and len(sent) < 2000
    finally:
        with ses.lock:
            ses.sessions.pop(THREAD, None)
