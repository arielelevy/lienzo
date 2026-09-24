"""CODA: donde guarda las cosas y que sesion tiene cada proceso.

Todas las sesiones van a una base local (CODA_HOME la mueve). La tarjeta usa esa base como
transcript_path y su session_id como clave dentro de ella. La identidad de un proceso sale del
log local de CODA, sin adivinar por cwd ni por fecha.

Solo stdlib.
"""

from __future__ import annotations

import json
import os
import sqlite3

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LOG_TAIL_BYTES = 1024 * 1024


def home() -> str:
    return os.environ.get("CODA_HOME") or os.path.join(HOME, ".coda")


def db_path() -> str:
    return os.path.join(home(), "coda.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    """Solo lectura: CODA es el unico que escribe su base."""
    uri = "file:" + (path or db_path()).replace("\\", "/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2)


def is_root(sid: str, path: str | None = None) -> bool | None:
    """La sesion es la de la TUI (True), un subagente (False) o no esta en la base (None)."""
    try:
        with connect(path) as c:
            row = c.execute("select relationship from sessions where id = ?", (sid,)).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else row[0] == "root"


def parent_of(sid: str, path: str | None = None) -> str | None:
    """La sesion madre de un subagente, o None."""
    try:
        with connect(path) as c:
            row = c.execute("select parent_session_id from sessions where id = ?", (sid,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _log_lines(path: str) -> list[str]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > LOG_TAIL_BYTES:
                f.seek(size - LOG_TAIL_BYTES)
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").split("\n")
    return lines[1:] if size > LOG_TAIL_BYTES else lines


def session_of_pid(pid: int) -> str | None:
    """La ultima sesion de la TUI que el proceso `pid` escribio en el log: una sesion nueva en el
    mismo proceso gana. Si el log actual no dice nada de este pid, se mira el anterior."""
    logs = os.path.join(home(), "logs")
    for name in ("coda.log", "coda.log.1"):
        found = None
        for line in _log_lines(os.path.join(logs, name)):
            if str(pid) not in line or '"sessionId"' not in line:
                continue  # filtro barato antes de parsear; el pid se compara exacto abajo
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("pid") == pid and d.get("clientName") == "cli" and isinstance(d.get("sessionId"), str):
                found = d["sessionId"]
        if found:
            return found
    return None


def activity(pid: int) -> dict | None:
    """Lo que el proceso viene haciendo en el turno en curso, leido del log: cuantas herramientas
    lleva y cual corre. Sirve para una sesion sin hooks.

    `asking` es el pedido de permiso abierto, o None. Se da por contestado cuando la misma sesion
    vuelve a escribir, o cuando cierra el turno. Vale tambien para una sesion con hooks.
    None si el log no dice nada de ese pid."""
    act = None
    asks: dict[str, dict] = {}  # sessionId -> pedido abierto (la TUI o un subagente)
    for line in _log_lines(os.path.join(home(), "logs", "coda.log")):
        if str(pid) not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("pid") != pid:
            continue
        msg, cli, sid = d.get("msg"), d.get("clientName") == "cli", d.get("sessionId")
        asks.pop(sid, None)  # la sesion siguio: lo que tenia abierto ya se contesto
        if msg == "prompt started" and cli:
            act = {"running": True, "tools": 0, "last_tool": None, "sub": False}
            asks.clear()
        elif msg == "prompt complete" and cli and act:
            act["running"] = False
            asks.clear()
        elif msg == "authorization.decision" and act and isinstance(d.get("toolName"), str):
            act["tools"] += 1
            act["last_tool"] = d["toolName"]
            act["sub"] = not cli
            if d.get("decision") == "ask" and sid:
                asks[sid] = {"tool": d["toolName"], "cause": d.get("askCause"), "sub": not cli, "at": d.get("time")}
    if act:
        act["asking"] = next(reversed(asks.values()), None)
    return act


def identity(pid: int) -> tuple[str, str] | None:
    """(session_id, transcript_path) del proceso, o None. La sesion tiene que existir en la base
    y no ser un subagente."""
    sid = session_of_pid(pid)
    if not sid or is_root(sid) is not True:
        return None
    return sid, db_path()
