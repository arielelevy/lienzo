"""Identidad exacta de Kiro V3 a partir del lock de su motor y su proceso padre."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

try:
    from . import procinfo
except ImportError:
    import procinfo

_errors: OrderedDict[str, str] = OrderedDict()
_error_lock = threading.Lock()


def _diagnose(path: Path, problem: str | None) -> None:
    """Solo cambios de error, sin contenidos privados ni crecimiento ilimitado."""
    key = str(path)
    with _error_lock:
        previous = _errors.pop(key, None)
        if problem:
            _errors[key] = problem
            if problem != previous:
                logging.getLogger(__name__).warning("Kiro %s: %s", path.name, problem)
        elif previous:
            logging.getLogger(__name__).info("Kiro %s: lectura recuperada", path.name)
        while len(_errors) > 256:
            _errors.popitem(last=False)


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("se esperaba un objeto JSON")
    except FileNotFoundError:
        _diagnose(path, None)  # rotacion o archivo todavia no publicado
        return {}
    except (OSError, ValueError, TypeError) as exc:
        _diagnose(path, f"lectura invalida ({type(exc).__name__})")
        return {}
    _diagnose(path, None)
    return value


def read_metadata(transcript: str) -> dict:
    return read_object(Path(transcript).with_name("session.json"))


def identity(pid: int, home: str | None = None) -> tuple[str, str] | None:
    base = Path(home or os.environ.get("USERPROFILE") or os.path.expanduser("~")) / ".kiro" / "sessions"
    matches = set()
    for lock in base.glob("*/sess_*/.lock"):
        try:
            engine = read_object(lock).get("pid")
            if not isinstance(engine, int) or engine <= 0:
                continue
            parent, exe = procinfo.proc_info(engine)
            if parent != pid or not exe or "kiro-cli" not in exe.lower().replace("\\", "/"):
                continue
            folder = lock.parent
            meta = read_object(folder / "session.json")
            transcript = folder / "messages.jsonl"
            if meta.get("id") == folder.name and transcript.is_file():
                matches.add((meta["id"], str(transcript)))
        except OSError, ValueError, TypeError:
            continue
    return next(iter(matches)) if len(matches) == 1 else None
