"""Regresiones tras la integración: persistir metadatos sin repetir el I/O del handler."""

import json

import pytest
import server
import sessions as ses
import state


@pytest.mark.parametrize("on", [False, True])
def test_mismo_rol_persiste_preferencia_y_propuesta_en_sessions(tmp_path, monkeypatch, on):
    carpeta = tmp_path / "sessions"
    carpeta.mkdir()
    monkeypatch.setattr(state, "SESSIONS", str(carpeta))
    monkeypatch.setattr(state, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "_mirror_sessions", list)
    s = ses.new_session("regresion-coordinadora", "claude", "hook")
    s.update(
        repo="r",
        coordinator=on,
        coordinator_declined=on,
        coordinator_proposal={"kind": "role", "title": "r | coordinadora", "reason": "candidata"},
    )
    monkeypatch.setattr(ses, "sessions", {s["session_id"]: s})
    code, out = server.accion_coordinator(s, {"on": on})
    assert code == 200 and out["coordinator"] is on
    guardada = json.loads((carpeta / "regresion-coordinadora.json").read_text(encoding="utf-8"))
    assert guardada["coordinator"] is on and guardada["coordinator_declined"] is (not on)
    if on:
        assert guardada["coordinator_proposal"]["kind"] == "title"
    else:
        assert "coordinator_proposal" not in guardada
