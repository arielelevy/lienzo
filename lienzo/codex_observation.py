"""Asociación de lectura para TUIs con daemon compartido; nunca autoriza queue.

El nombre completo del pie visible debe identificar un único hilo TUI en la misma
carpeta. No elegir por fecha, fragmentos del título ni proximidad del rollout.
"""

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import codex_status
import procinfo
import procs
import state
import subproc


def _footer(pid):
    # Sin lienzo-server.cmd, screen.py imprime en cp1252 y el «⚠» del pie lo rompe (2026-10-22).
    code, output, _ = subproc.correr(
        [sys.executable, str(Path(__file__).with_name("screen.py")), "--pid", str(pid), "--json"],
        timeout=5,
        env={"PYTHONIOENCODING": "utf-8"},
    )
    if code != 0:
        return None
    snapshot = json.loads(output)
    lines = snapshot.get("lines") or []
    if not snapshot.get("ok") or len(lines) < 2 or "? for shortcuts" not in lines[-1]:
        return None
    parts = lines[-2].strip().split(" · ", 2)
    if len(parts) != 3 or not os.path.isabs(parts[1]) or not parts[2] or any(c in parts[2] for c in ("…", "\n")):
        return None
    return parts[1], parts[2]


def observe(pid):
    if not procinfo._WIN or procinfo.process_agent(pid) != "codex":
        return None
    start = procs.creation_filetime(pid)
    if not start:
        return None
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    database = home / "state_5.sqlite"
    if not database.is_file():
        return None
    try:
        footer = _footer(pid)
        if not footer:
            return None
        cwd, name = footer
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.25)) as con:
            rows = con.execute(
                "SELECT id,cwd FROM threads WHERE name=? AND archived=0 AND originator IN (?,?)",
                (name, "codex-tui", "codex_cli_rs"),
            ).fetchall()
        candidates = [
            sid
            for sid, folder in rows
            if isinstance(folder, str) and os.path.isdir(folder) and os.path.samefile(folder, cwd)
        ]
        if len(candidates) != 1:
            return None
        sid = candidates[0]
        path = codex_status.rollout(sid, home)
        if not path or _footer(pid) != footer or procs.creation_filetime(pid) != start:
            return None
        return {
            "verified": False,
            "observed": True,
            "pid": pid,
            "process_start": start,
            "thread": sid,
            "path": path,
            "reason": "transcripción observada por nombre único del pie de la TUI; no autoriza queue",
        }
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error) as error:
        state.log(f"lectura del nombre Codex pid {pid}: {type(error).__name__}")
        return None
