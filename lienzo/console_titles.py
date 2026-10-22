"""Sincronizar proyecto y encargo de la tarjeta con el título de su consola local."""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback

import backend
import state
import subproc
import tmux
from work_titles import project_title

INTERVAL_S = 30
_start_lock = threading.Lock()
_started = False
_attempted: dict[str, tuple] = {}


def native_title(card: dict, title: str) -> dict:
    if backend.is_tmux(card):
        target = card.get("target")
        if not tmux.target_valid(target, card.get("pid"), card.get("distro")):
            return {"ok": False, "error": "el pane ya no pertenece a esta sesión"}
        before = tmux._tmux("display-message", "-p", "-t", target, "#{window_name}", distro=card.get("distro"))
        if before.returncode:
            return {"ok": False, "error": before.stderr.strip()}
        if before.stdout.rstrip("\r\n") == title:
            return {"ok": True, "changed": False}
        result = tmux._tmux("rename-window", "-t", target, title, distro=card.get("distro"))
        return {"ok": result.returncode == 0, "changed": result.returncode == 0, "error": result.stderr.strip()}
    if sys.platform != "win32":
        return {"ok": False, "error": "consola sin backend de título compatible"}
    rc, out, err = subproc.correr(
        [
            state.PYTHON,
            os.path.join(state.HERE, "console_title.py"),
            "--pid",
            str(card["pid"]),
            "--agent",
            card["agent"],
            "--title",
            title,
        ],
        timeout=10,
        max_output=4000,
    )
    try:
        result = json.loads(out)
    except ValueError:
        return {"ok": False, "error": err.strip() or f"helper de títulos: salida inválida (código {rc})"}
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        return {"ok": False, "error": "helper de títulos: respuesta inválida"}
    if rc and result["ok"]:
        return {"ok": False, "error": f"helper de títulos terminó con código {rc}: {err.strip()}"}
    return result


def sync_once(*, force: bool = False) -> None:
    import sessions

    with state.lock:
        cards = [
            dict(s)
            for s in state.sessions.values()
            if s.get("alive") and s.get("pid") and not s.get("no_console") and not s.get("orphan")
        ]
        active_ids = {card["session_id"] for card in cards}
        for sid in list(_attempted):
            if sid not in active_ids:
                del _attempted[sid]
    for card in cards:
        title = state.short(project_title(card), 120)
        if not title:
            continue
        with state.lock:
            current = state.sessions.get(card["session_id"])
            if current is None or current.get("pid") != card["pid"] or current.get("title") != card.get("title"):
                continue
            if current.get("title") != title:
                current["title"] = title
                sessions.touch(current)
            signature = (card["pid"], title, card.get("agent"), card.get("target"), card.get("distro"))
            if not force and _attempted.get(card["session_id"]) == signature:
                continue
            # Reserva durante el helper; sólo los fallos se conservan para no repetirlos cada ciclo.
            _attempted[card["session_id"]] = signature
        result = native_title(card, title)
        if result.get("ok"):
            with state.lock:
                _attempted.pop(card["session_id"], None)
            # Un éxito no se cachea: CODA/Codex/Kiro pueden pisar el título sin cambiar la tarjeta.
            # El helper lee primero y sólo escribe cuando difiere (también en tmux).
        error = None if result.get("ok") else result.get("error") or "no se pudo cambiar el título de la consola"
        state.avisar_si_cambia(f"título de consola {card['session_id'][:8]}", error)
        if result.get("changed"):
            state.log(f"consola {card['agent']} pid {card['pid']}: {title}")


def loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            sync_once()
        except Exception:
            state.log(f"sincronizar títulos de consola:\n{traceback.format_exc()}")
        stop.wait(INTERVAL_S)


def start() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=loop, args=(threading.Event(),), name="console-titles", daemon=True).start()
