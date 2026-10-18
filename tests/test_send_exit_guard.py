import pytest
import sessions


@pytest.mark.parametrize("agent", ["codex", "pi"])
@pytest.mark.parametrize("command", ["/exit", " /quit\n", "/EXIT"])
def test_send_rejects_exit_without_claiming_process_closed(monkeypatch, agent, command):
    monkeypatch.setattr(sessions, "_mirror_owner", lambda sid: None)

    def forbidden(*args):
        pytest.fail("exit must not reach message transport")

    monkeypatch.setattr(sessions, "puede_enviar", forbidden)
    monkeypatch.setattr(sessions, "send_blocked", forbidden)
    card = {"session_id": "fixture", "agent": agent, "alive": True}
    code, result = sessions.send_to_session(card, command, [])
    assert code == 400
    assert not result["ok"]
    assert "send no cierra" in result["error"]
    assert card["alive"]
