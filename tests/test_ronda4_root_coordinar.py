"""Regresión del lanzamiento observado al cambiar una tarjeta previa de ID."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "coordinar_ronda4_root", Path(__file__).parents[1] / "skills/lienzo/coordinar.py"
)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def test_lanzar_no_titula_ni_cablea_una_tarjeta_previa_que_adquiere_uuid(monkeypatch):
    old = {"session_id": "pid-10", "pid": 10, "pc": "pc", "agent": "codex", "cwd": "D:/Apps/lienzo"}
    renamed = dict(old, session_id="uuid-A")
    new = dict(old, session_id="pid-20", pid=20)
    snapshots = iter([[old], [renamed], [renamed, new]])
    monkeypatch.setattr(client, "sesiones", lambda: next(snapshots))
    monkeypatch.setattr(client, "lanzar", lambda *args: (200, {"ok": True}))
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)
    calls = []
    monkeypatch.setattr(client, "titular", lambda card, title: calls.append(("title", card["session_id"])))
    monkeypatch.setattr(client, "regla_informe", lambda card, text: calls.append(("rule", card["session_id"])))
    monkeypatch.setattr(client, "YO", "coordinadora")
    result = client.lanzar_y_titular("pc", "D:/Apps/lienzo", "encargo B", "codex", espera=2)
    assert result == new
    assert calls == [("title", "pid-20"), ("rule", "pid-20")]
