"""Descubrimiento de lectura por /status en una consola Codex libre y vacía.

El UUID lo publica la propia TUI. No acredita queue ni ejecuta un turno del modelo.
La consulta de consola corre aislada para no adjuntar el servidor a una terminal.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import procinfo
import procs

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_cache = {}
_running = set()
_lock = threading.Lock()


def request_scan():
    """El botón Buscar sesiones permite otro intento, sin duplicar consultas en curso."""
    with _lock:
        for key in list(_cache):
            if key not in _running:
                del _cache[key]


def idle(snapshot):
    import screen

    lines = snapshot.get("lines") or []
    text = "\n".join(lines)
    # input_area es el parser de Claude: sin sus bordes trataría un borrador
    # Codex como vacío. Exigimos la caja y el footer observados en Codex 0.163.
    prompt = len(lines) - 4
    empty = (
        prompt >= 0 and lines[prompt].strip() in ("›", "› Ask Codex to do anything") and not lines[prompt + 1].strip()
    )
    return bool(
        snapshot.get("ok")
        and empty
        and not screen.dialog(lines)
        and not re.search(r"esc to interrupt|Queued follow-up inputs|Waiting for|Working \(", text, re.IGNORECASE)
        and any("? for shortcuts" in line for line in lines[-3:])
    )


def session_from_status(lines):
    # Sólo el bloque más reciente del comando local, con su cabecera completa.
    starts = [i for i, line in enumerate(lines) if line.strip() in ("/status", "› /status")]
    if not starts:
        return None
    block = "\n".join(lines[starts[-1] + 1 :])
    if not all(label in block for label in (">_ OpenAI Codex", "Model:", "Directory:", "Permissions:")):
        return None
    ids = re.findall(r"^\s*Session:\s*(" + UUID + r")\s*$", block, re.MULTILINE)
    return ids[0] if len(ids) == 1 else None


def query_console(pid, start):
    import screen
    import send

    if procinfo.process_agent(pid) != "codex" or procs.creation_filetime(pid) != start:
        return None
    before = screen.read_screen(pid)
    if not idle(before):
        return None
    time.sleep(0.1)
    again = screen.read_screen(pid)
    if not idle(again) or again.get("lines") != before.get("lines"):
        return None
    result = send.inject(pid, "/status", expected_start=start)
    if not result.get("ok"):
        return None
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        after = screen.read_screen(pid)
        if procs.creation_filetime(pid) != start:
            return None
        sid = session_from_status(after.get("lines") or [])
        if sid and after.get("lines") != before.get("lines") and idle(after):
            return sid
        time.sleep(0.1)
    return None


def rollout(thread, home=None):
    if not isinstance(thread, str) or not re.fullmatch(UUID, thread):
        return None
    base = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        # El UUID viene de la terminal, no de carpeta, mtime o proximidad.
        # La base SQLite puede no contener todavía un hilo que ya escribe JSONL.
        paths = list((base / "sessions").glob(f"**/rollout-*{thread}.jsonl"))
        if len(paths) != 1:
            return None
        path = paths[0]
        if not path.resolve().is_relative_to((base / "sessions").resolve()):
            return None
        with path.open(encoding="utf-8") as f:
            header = json.loads(f.readline(65536))
        payload = header.get("payload") or {}
        if (
            header.get("type") == "session_meta"
            and payload.get("id") == thread
            and payload.get("originator") in ("codex-tui", "codex_cli_rs")
        ):
            return str(path)
    except OSError, ValueError, AttributeError:
        pass
    return None


def discover(pid):
    if not procinfo._WIN or procinfo.process_agent(pid) != "codex":
        return None
    start = procs.creation_filetime(pid)
    if not start:
        return None
    key = (pid, start)
    tick = time.monotonic()
    with _lock:
        previous = _cache.get(key)
        if previous:
            # La prueba vence, el permiso de teclear no se renueva con el tiempo.
            return previous[1] if tick - previous[0] < 60 else None
        # No dos consultas simultáneas sobre la misma consola.
        _cache[key] = (tick, None)
        _running.add(key)
        # Sólo retirar otras encarnaciones del mismo PID: purgar por edad
        # permitiría volver a teclear en una CLI que sigue abierta.
        for old in list(_cache):
            if old[0] == pid and old != key and old not in _running:
                del _cache[old]
    try:
        result = subprocess.run(
            [sys.executable, __file__, "--pid", str(pid), "--start", str(start)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=0x00000008,  # DETACHED_PROCESS, igual que screen.py/send.py
        )
        sid = json.loads(result.stdout).get("thread") if result.returncode == 0 else None
        path = rollout(sid) if isinstance(sid, str) and re.fullmatch(UUID, sid) else None
        proof = (
            {
                "verified": False,
                "observed": True,
                "pid": pid,
                "process_start": start,
                "thread": sid,
                "path": path,
                "reason": "transcripción identificada por /status de la TUI",
            }
            if path and procs.creation_filetime(pid) == start
            else None
        )
    except OSError, ValueError, AttributeError, subprocess.TimeoutExpired:
        proof = None
    with _lock:
        _cache[key] = (time.monotonic(), proof)
        _running.discard(key)
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--start", type=int, required=True)
    args = parser.parse_args()
    try:
        result = query_console(args.pid, args.start)
    except Exception:
        result = None
    print(json.dumps({"thread": result}))
