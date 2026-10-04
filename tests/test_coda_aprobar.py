"""Los dos caminos para que un permiso de coda no quede esperando sin que nadie lo vea (medido el
2026-10-04: dos codas de la otra PC esperaron una hora un npm run build):
1) con auto-aprobar prendido, el hook PreToolUse de coda contesta `allow` y el cartel ni aparece;
2) si igual aparece (auto-aprobar apagado, hook viejo), la pantalla delata el cartel y la tarjeta
   pasa a te_necesita con el comando."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import sessions as ses
import state as st


def _hook(tmp_path, cfg, evento):
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = {**os.environ, "LIENZO_HOME": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "lienzo", "hook.py"), "coda"],
        input=json.dumps(evento),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return r.stdout.strip()


def test_hook_de_coda_aprueba_solo_con_auto_aprobar_prendido(tmp_path):
    ev = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "bash",
        "tool_input": {"command": "npm run build"},
    }
    salida = json.loads(_hook(tmp_path, {"auto_aprobar": True}, ev))
    assert salida["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _hook(tmp_path, {"auto_aprobar": False}, ev) == ""
    otro = {**ev, "hook_event_name": "Stop"}
    assert _hook(tmp_path, {"auto_aprobar": True}, otro) == ""


def test_el_cartel_en_pantalla_pone_la_coda_en_te_necesita(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    s = {
        "session_id": "f" * 36,
        "agent": "coda",
        "pid": 1,
        "state": "corriendo",
        "state_since": "2000-01-01T00:00:00-03:00",
        "needs": None,
        "last_event_ts": "2000-01-01T00:00:00-03:00",
    }
    monkeypatch.setitem(st.sessions, s["session_id"], s)
    monkeypatch.setattr(ses, "_pantalla_mirada", {})
    assert ses.coda_mirar_pantalla(s) is True
    assert ses.coda_mirar_pantalla(s) is False  # no se vuelve a mirar enseguida
    pantalla = [
        "┃ ⚠  Approval Required",
        "   cd D:/apps/lienzo/web && npm run build",
        "  ask by command policy",
        "  ❯ Yes",
        "    No",
        "  ↑↓ move · Enter confirm · Esc deny",
    ]
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": pantalla})
    assert ses.coda_dialogo_en_pantalla(s) is True
    n = s["needs"]
    assert s["state"] == "te_necesita" and n["where"] == "terminal" and n["coda_at"].startswith("screen:")
    assert "npm run build" in n["detail"]
    # la proxima herramienta la libera
    ses.coda_tool(s, {"tool_name": "bash", "tool_input": {"command": "ls"}, "host_ts": "t"})
    assert s["state"] == "corriendo" and s["needs"] is None
