import json

import agent_improvements as improvements
import pytest
import state


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(improvements.shutil, "which", lambda name: None)
    return tmp_path


def test_preferences_are_opt_in_and_do_not_expose_keys(isolated):
    before = improvements.status()
    assert before["preferences"] == {"brief": False, "rtk": False}
    after = improvements.configure({"brief": True})
    assert after["preferences"] == {"brief": True, "rtk": False}
    assert "api_key" not in json.dumps(after)
    text, warnings = improvements.launch_instructions("claude")
    assert "Responde breve" in text and "No comprimas archivos" in text and not warnings


@pytest.mark.parametrize("data", [{}, {"brief": 1}, {"rtk": "true"}, {"command": "whoami"}])
def test_bad_config_does_not_change_preferences(isolated, data):
    with pytest.raises(ValueError):
        improvements.configure(data)
    assert not (isolated / "agent-improvements.json").exists()


def test_rtk_windows_does_not_claim_wsl_availability(isolated, monkeypatch):
    binary = isolated / "bin" / ("rtk.exe" if improvements.os.name == "nt" else "rtk")
    binary.parent.mkdir()
    binary.write_bytes(b"fixture")
    improvements.configure({"rtk": True})
    monkeypatch.setattr(improvements.tmux, "en_distro", lambda distro, name: False)
    text, warnings = improvements.launch_instructions("codex", "Ubuntu")
    assert not text and "RTK no esta instalado" in warnings[0]
    assert improvements.rtk_path() == str(binary)


def test_corrupt_preferences_are_visible(isolated):
    (isolated / "agent-improvements.json").write_text("{broken")
    with pytest.raises(ValueError):
        improvements.preferences()
