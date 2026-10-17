"""Glue only: runtime and launch transport doubles, no Claude process, pipe or credential."""
import json
import time
from pathlib import Path

import claude_pipe_runtime as runtime
import launch
import pytest
import sessions as ses
import state

from lienzo import server

SID = "01a14a70-1105-73b3-87ce-7a60b4b925fd"
PIPE = {"puede": True, "motivo": None, "transporte": "claude_pipe"}


@pytest.fixture
def card(monkeypatch, tmp_path):
    s = {"session_id": SID, "agent": "claude", "pid": 42, "alive": True,
         "external": {"kind": "claude-desktop", "desktop": True, "canal": "elegida"}, "no_console": True}
    monkeypatch.setattr(ses, "sessions", {SID: s})
    monkeypatch.setattr(server, "sessions", ses.sessions)
    monkeypatch.setattr(ses, "_mirror_owner", lambda sid: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    monkeypatch.setattr(runtime, "availability", lambda card: PIPE)
    monkeypatch.setattr(runtime, "reap", lambda cards: None)
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **kw: None)
    monkeypatch.setattr(ses, "_envio_poll_at", -1e9)
    monkeypatch.setattr(ses, "_envio_publico", {})
    return s


def test_only_live_registered_pipe_can_enable_desktop(card, monkeypatch):
    assert ses.puede_enviar(card) == PIPE
    monkeypatch.setattr(runtime, "availability", lambda c: {"puede": False, "motivo": "sin adaptador", "transporte": "claude_pipe"})
    assert not ses.puede_enviar(card)["puede"]
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("Desktop nunca se teclea"))
    assert ses.send_to_session(card, "hola", [])[0] == 409


@pytest.mark.parametrize("field", ["pending_id", "stopped_by"])
def test_guarded_session_cannot_use_registered_pipe(card, field):
    card[field] = "blocking"
    assert not ses.puede_enviar(card)["puede"]
    assert ses.send_claude_pipe(card, "hola", [])[0] == 409


def test_pipe_written_result_stays_queued_and_periodic_confirm_updates(card, monkeypatch):
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("no consola"))
    calls = []
    def send(s, text):
        calls.append((s["session_id"], text))
        return {"estado": "encolado", "motivo": "pipe_written no es entrega", "envio_id": "msg", "at": time.time(), "transporte": "claude_pipe"}
    monkeypatch.setattr(runtime, "send", send)
    code, result = ses.send_to_session(card, "hola", [])
    assert code == 200 and result["estado"] == "encolado"
    assert card["envio_claude"]["estado"] == "encolado" and calls == [(SID, "hola")]
    monkeypatch.setattr(runtime, "confirm", lambda eid: {"estado": "entregado", "envio_id": eid, "motivo": None})
    ses.refresh_envios()
    assert card["envio_claude"]["estado"] == "entregado" and len(calls) == 1


def test_lost_adapter_with_uncertain_cli_send_never_falls_back_to_typing(card, monkeypatch):
    card.update(external=None, no_console=False, envio_claude={"estado": "sin_confirmacion", "envio_id": "old"})
    monkeypatch.setattr(runtime, "availability", lambda c: {"puede": False, "motivo": "perdido", "transporte": "claude_pipe"})
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("no duplicar por consola"))
    assert ses.send_to_session(card, "hola", [])[0] == 409


@pytest.mark.parametrize("newer", [False, True], ids=["confirmed-same-send", "newer-send"])
@pytest.mark.parametrize("late_state", ["encolado", "sin_confirmacion", "rechazado"])
def test_late_pipe_result_preserves_confirmed_or_newer_send(card, monkeypatch, newer, late_state):
    preserved = {"envio_id": "new" if newer else "same", "at": 20 if newer else 10,
                 "estado": "entregado", "transporte": "claude_pipe"}

    def delayed_send(chosen, text):
        # Simulate a confirmation/new send winning while the first call is pending.
        card["envio_claude"] = dict(preserved)
        card["last_prompt"] = "visible confirmed prompt"
        return {"envio_id": "same", "at": 10, "estado": late_state,
                "motivo": "late response", "transporte": "claude_pipe"}

    monkeypatch.setattr(runtime, "send", delayed_send)
    ses.send_to_session(card, "old prompt", [])
    assert card["envio_claude"] == preserved
    assert card["last_prompt"] == "visible confirmed prompt"


@pytest.mark.parametrize("origin,via,pid,expected", [
    ({"kind": "batch", "via": "comando"}, "registro", 42, True),
    ({"kind": "batch", "via": "comando"}, "ruta", 42, False),
    ({"kind": "batch", "via": "comando"}, "registro", 43, False),
    ({"kind": "codex", "via": "proceso", "runner_pid": 7}, "registro", 42, False),
], ids=["validated-desktop", "path-insufficient", "different-process", "preserve-orchestrator"])
def test_desktop_registry_can_replace_only_generic_batch(card, monkeypatch, origin, via, pid, expected):
    card["external"] = dict(origin)
    monkeypatch.setattr(ses.backend, "proc_key", lambda row: row.get("pid"))
    observed = {"pid": pid, "external": {"kind": "claude-desktop", "desktop": True, "via": via}}
    ses.marcar_desktop(observed)
    assert card["external"] == (observed["external"] if expected else origin)


def test_explicit_registration_returns_public_command_for_chosen_card_only(card, monkeypatch):
    seen = []
    def register(chosen):
        seen.append(chosen["session_id"])
        return {"command": "public --bootstrap id sid pid start", "session_id": SID, "expires_at": time.time() + 120, "private": "must-not-be-published"}
    monkeypatch.setattr(runtime, "register", register)
    code, result = server.accion_claude_pipe(card, {})
    assert code == 200 and seen == [SID] and result["envio"] == PIPE
    assert "secret" not in json.dumps(result).lower() and "token" not in json.dumps(result).lower()
    assert "private" not in result and "must-not-be-published" not in json.dumps(result)


def test_launch_opt_in_uses_public_settings_not_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(launch, "_cwd_allowed", lambda *a: True)
    monkeypatch.setattr(launch, "_allowed_roots", list)
    monkeypatch.setattr(launch, "_exe_path", lambda exe: "C:/fake/claude.exe")
    monkeypatch.setattr(launch.harness_updates, "before_launch", lambda *a: None)
    monkeypatch.setattr(launch.agent_improvements, "launch_instructions", lambda *a: ("", []))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    prepared = []
    def prepare(sid):
        prepared.append(sid)
        return {"hook_settings": {"hooks": {"SessionStart": [{"hooks": [{"command": "python adapter.py --bootstrap public-id sid pid start"}]}]}}}
    monkeypatch.setattr(runtime, "prepare_launch", prepare)
    assert launch.launch(str(tmp_path), "plain", "claude")["ok"] and prepared == []
    result = launch.launch(str(tmp_path), "opt-in", "claude", claude_pipe=True)
    assert result["ok"] and prepared == [result["session_id"]]
    cmd = Path(result["cmd_path"]).read_text(encoding="cp1252")
    assert "--session-id" in cmd and "--settings" in cmd
    settings = (tmp_path / "launch" / f"{result['session_id']}.claude-settings.json").read_text(encoding="utf-8")
    assert "--bootstrap public-id" in settings
    assert "LIENZO_CLAUDE_BRIDGE_SECRET" not in cmd + settings
    closed = []
    monkeypatch.setattr(runtime, "close", closed.append)
    monkeypatch.setattr(launch, "_launch_cmd", lambda *a: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(OSError):
        launch.launch(str(tmp_path), "failed", "claude", claude_pipe=True)
    assert closed == [prepared[-1]]


def test_server_shutdown_closes_only_owned_bridges(monkeypatch):
    closed = []
    monkeypatch.setattr(runtime, "close_all", lambda: closed.append("owned"))
    monkeypatch.setattr(server.plugins, "detener", lambda: ["plugin"])
    assert server.detener_plugins() == ["plugin"]
    assert closed == ["owned"]


@pytest.mark.parametrize("message", [
    "protocolo Claude desconocido o incompatible: se requiere peerProtocol entero 1",
    "versión Claude anterior al mínimo Windows 2.1.234",
    "límite de enlaces Claude alcanzado; cerrá los enlaces sin uso",
    "bootstrap Claude finalizado sin conexión vigente; cerrá el enlace y registrá de nuevo",
])
def test_registration_preserves_controlled_public_reason(card, monkeypatch, message):
    monkeypatch.setattr(runtime, "register", lambda s: (_ for _ in ()).throw(ValueError(message)))
    code, result = server.accion_claude_pipe(card, {})
    assert code == 409 and result["error"] == message


def test_arbitrary_error_is_not_published_and_launch_limit_is_readable(tmp_path, monkeypatch):
    assert "private-token" not in launch.claude_pipe_error(ValueError("private-token"))
    assert "private-token" not in launch.claude_pipe_error(OSError("private-token"))
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(launch, "_cwd_allowed", lambda *a: True)
    monkeypatch.setattr(launch, "_allowed_roots", list)
    monkeypatch.setattr(launch, "_exe_path", lambda exe: "C:/fake/claude.exe")
    monkeypatch.setattr(launch.harness_updates, "before_launch", lambda *a: None)
    monkeypatch.setattr(launch.agent_improvements, "launch_instructions", lambda *a: ("", []))
    reason = "límite de enlaces Claude alcanzado; cerrá los enlaces sin uso"
    monkeypatch.setattr(runtime, "prepare_launch", lambda sid: (_ for _ in ()).throw(ValueError(reason)))
    monkeypatch.setattr(launch, "_launch_cmd", lambda *a: pytest.fail("no proceso tras rechazo"))
    result = launch.launch(str(tmp_path), "limit", "claude", claude_pipe=True)
    assert result == {"ok": False, "code": 409, "error": reason}
