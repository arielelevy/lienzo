"""Sincronizar proyecto y encargo de la tarjeta con el título de su consola local."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback

import backend
import state
import subproc
import tmux
from tarjeta_texto import strip_control

INTERVAL_S = 30
_start_lock = threading.Lock()
_started = False
_NAMED_WORK = re.compile(r"^.+?\s+-\s+(?:encargo\b|coordinador[ae]?\b)", re.IGNORECASE)


def project_title(card: dict) -> str:
    title = strip_control(str(card.get("title") or "")).strip()
    project = strip_control(str(card.get("repo") or "")).strip()
    if not project:
        return title
    if not title:
        return project
    if title.casefold() == project.casefold() or title.casefold().startswith(project.casefold() + " - "):
        return title
    if _NAMED_WORK.match(title):
        return title  # nombres explícitos: chesstudia - encargo B, aunque la carpeta sea chess
    return project[0].upper() + project[1:] + " - " + title


def native_title(card: dict, title: str) -> dict:
    if backend.is_tmux(card):
        target = card.get("target")
        if not tmux.target_valid(target, card.get("pid"), card.get("distro")):
            return {"ok": False, "error": "el pane ya no pertenece a esta sesión"}
        result = tmux._tmux("rename-window", "-t", target, title, distro=card.get("distro"))
        return {"ok": result.returncode == 0, "error": result.stderr.strip()}
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


def sync_once() -> None:
    import sessions

    with state.lock:
        cards = [
            dict(s)
            for s in state.sessions.values()
            if s.get("alive") and s.get("pid") and not s.get("no_console") and not s.get("orphan")
        ]
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
        result = native_title(card, title)
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
