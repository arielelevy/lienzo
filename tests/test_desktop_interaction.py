"""Conexión explícita y publicación de capacidad Desktop sin procesos reales."""

import pytest
import sessions as ses

from lienzo import server


@pytest.mark.parametrize("value", [None, 1, "true", {}, []])
def test_reconnect_requires_explicit_boolean(value):
    assert server.validar_claude_pipe({"reconnect": value})[0] == 400


def test_disconnected_claude_desktop_keeps_specific_connection_reason(monkeypatch):
    card = {"agent": "claude", "external": {"kind": "claude-desktop"}}
    plan = {"puede": False, "motivo": "adaptador vencido", "transporte": "claude_pipe"}
    monkeypatch.setattr(ses.claude_pipe_runtime, "availability", lambda s: plan)
    assert ses.puede_enviar(card) == plan


def test_explicit_reconnect_is_forwarded_without_public_credentials(monkeypatch):
    import claude_pipe_runtime as runtime

    calls = []
    monkeypatch.setattr(runtime, "register", lambda card, **kw: calls.append(kw) or {
        "session_id": "fixture", "command": "public", "expires_at": 123,
        "connected": False, "secret": "must-not-leave-runtime",
    })
    monkeypatch.setattr(runtime, "availability", lambda s: {"puede": False})
    code, result = server.accion_claude_pipe({"session_id": "fixture"}, {"reconnect": True})
    assert code == 200 and calls == [{"reconnect": True}]
    assert "secret" not in result
