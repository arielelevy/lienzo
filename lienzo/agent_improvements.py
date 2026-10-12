"""Preferencias de esta PC; instrucciones adicionales, nunca permisos ni hooks."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

import state
import tmux

LOCK = threading.Lock()
DEFAULTS = {"brief": False, "rtk": False}
BRIEF = (
    "Responde breve y en el idioma del usuario. Primero el resultado; despues solo lo necesario. "
    "Una idea por frase. Conserva negaciones, numeros, rutas, comandos y errores exactos. "
    "La brevedad no reduce el trabajo, las pruebas, la revision, la seguridad ni la accesibilidad. "
    "Respeta las instrucciones del usuario y del proyecto. No comprimas archivos ni uses un proxy Caveman."
)


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


def rtk_path(distro: str | None = None) -> str | None:
    if distro:
        return "rtk" if tmux.en_distro(distro, "rtk") else None
    own = Path(state.LIENZO) / "bin" / ("rtk.exe" if os.name == "nt" else "rtk")
    return str(own) if own.is_file() else shutil.which("rtk")


def status() -> dict:
    import jev_credentials

    return {
        "preferences": preferences(), "rtk": {"available": bool(rtk_path())},
        "brief": {"available": True, "mode": "instrucciones breves, sin proxy"},
        "jev": {"available": jev_credentials.available(), "model": "typesafe/jev-1.13"},
        "scope": "esta PC; nuevas sesiones lanzadas desde Lienzo",
    }


def launch_instructions(agent: str, distro: str | None = None) -> tuple[str, list[str]]:
    pref = preferences()
    text, warnings = [], []
    if pref["brief"]:
        text.append(BRIEF)
    if pref["rtk"]:
        path = rtk_path(distro)
        if path:
            text.append(
                f"RTK disponible en {path}. Invocalo por esa ruta absoluta; no asumas que esta en PATH. Usa RTK explicitamente para salidas largas de comandos "
                "compatibles, por ejemplo rtk git status o rtk git diff. Conserva los codigos de salida. "
                "Ante un error recupera la salida original o ejecuta el comando diagnostico sin compresion. "
                "No filtres pruebas que requieren logs completos ni cambies hooks o permisos. "
                "En PowerShell una ruta ejecutable con espacios se invoca con el operador de llamada."
            )
        else:
            warnings.append("RTK no esta instalado en el entorno elegido; se lanza sin compresion")
    if text and agent not in ("claude", "codex", "pi", "coda"):
        warnings.append(f"{agent} no admite estas mejoras verificadas; se lanza sin instrucciones adicionales")
        text = []
    return " ".join(text), warnings
