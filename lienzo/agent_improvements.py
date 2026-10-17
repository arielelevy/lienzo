"""Preferencias de esta PC; instrucciones adicionales, nunca permisos ni hooks. Que tools hay y que
inyecta cada una al lanzar vive en el catalogo (lienzo/tools/)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import plugins
import state
import tools

LOCK = threading.Lock()
DEFAULTS = {"brief": False, "rtk": False}


def preferences() -> dict:
    path = Path(state.LIENZO) / "agent-improvements.json"
    if not path.exists():
        return dict(DEFAULTS)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != set(DEFAULTS) or any(type(v) is not bool for v in data.values()):
        raise ValueError("preferencias de mejoras invalidas")
    return data


def configure(data: dict) -> dict:
    if not data or set(data) - set(DEFAULTS) or any(type(v) is not bool for v in data.values()):
        raise ValueError("solo brief y rtk, como true o false")
    with LOCK:
        merged = preferences() | data
        root = Path(state.LIENZO)
        root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(merged, stream)
            os.replace(name, root / "agent-improvements.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return status()


def status() -> dict:
    return {
        "preferences": preferences(),
        "tools": tools.resumen(),
        "plugins": plugins.resumen(),
        "scope": "esta PC; nuevas sesiones lanzadas desde Lienzo",
    }


def launch_instructions(agent: str, distro: str | None = None, modo: str = "general") -> tuple[str, list[str]]:
    """Las instrucciones de las tools del modo para un lanzamiento: (texto, avisos)."""
    return tools.instrucciones(agent, distro, preferences(), modo)
