import json

import agent_improvements as improvements
import pytest
import state
from tools import rtk


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(rtk.shutil, "which", lambda name: None)
    return tmp_path


def test_preferences_are_opt_in_and_do_not_expose_keys(isolated):
    before = improvements.status()
    assert before["preferences"] == {"brief": False, "rtk": False}
    after = improvements.configure({"brief": True})
    assert after["preferences"] == {"brief": True, "rtk": False}
    assert "api_key" not in json.dumps(after)
    text, warnings = improvements.launch_instructions("claude")
    assert "Responde breve" in text and "No comprimas archivos" in text and not warnings


def test_configure_writes_through_the_single_atomic_writer(isolated, monkeypatch):
    writes = []
    monkeypatch.setattr(state, "atomic_write", lambda path, text: writes.append((path, json.loads(text))))
    improvements.configure({"rtk": True})
    assert writes == [(str(isolated / "agent-improvements.json"), {"brief": False, "rtk": True})]


@pytest.mark.parametrize("data", [{}, {"brief": 1}, {"rtk": "true"}, {"command": "whoami"}])
def test_bad_config_does_not_change_preferences(isolated, data):
    with pytest.raises(ValueError):
        improvements.configure(data)
    assert not (isolated / "agent-improvements.json").exists()


def test_rtk_windows_does_not_claim_wsl_availability(isolated, monkeypatch):
    binary = isolated / "bin" / ("rtk.exe" if rtk.os.name == "nt" else "rtk")
    binary.parent.mkdir()
    binary.write_bytes(b"fixture")
    improvements.configure({"rtk": True})
    monkeypatch.setattr(rtk.subproc, "correr", lambda *args, **kwargs: (1, "", "no instalado"))
    text, warnings = improvements.launch_instructions("codex", "Ubuntu")
    assert not text and "RTK no esta instalado" in warnings[0]
    assert rtk.ruta() == str(binary)


def test_corrupt_preferences_are_visible(isolated):
    (isolated / "agent-improvements.json").write_text("{broken")
    with pytest.raises(ValueError):
        improvements.preferences()


@pytest.mark.parametrize("con_rg", [True, False])
def test_rtk_dice_si_falta_rg(isolated, monkeypatch, con_rg):
    # openSeec, 2026-10-30: «rtk rg» fallaba con «Binary 'rg' not found on PATH» y los frentes caían a la
    # herramienta nativa sin aviso
    binary = isolated / "bin" / ("rtk.exe" if rtk.os.name == "nt" else "rtk")
    binary.parent.mkdir()
    binary.write_bytes(b"fixture")
    monkeypatch.setattr(rtk.shutil, "which", lambda name: "C:/rg.exe" if con_rg and name == "rg" else None)
    improvements.configure({"rtk": True})
    text, _ = improvements.launch_instructions("claude", None)
    if con_rg:
        assert "rtk rg," in text and "no esta instalado" not in text
    else:
        assert "rtk grep (rg no esta instalado en esta PC" in text and "rtk rg," not in text
