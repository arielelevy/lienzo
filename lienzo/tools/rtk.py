"""RTK: comprime la salida de comandos largos. Lienzo instala el binario (ops/preparar-mejoras.py, con
SHA-256 publicado) y, al lanzar, le indica al agente usarlo por ruta absoluta. No instala hooks."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import state
import subproc

from . import Tool

VERSION = "0.51.0"


def ruta(distro: str | None = None) -> str | None:
    """El RTK de Lienzo (`<LIENZO_HOME>/bin`) o el del PATH; en una distro de WSL, el de esa distro."""
    if distro:
        code, out, err = subproc.correr(
            ["wsl.exe", "-d", distro, "--exec", "bash", "-lc", "command -v rtk"], timeout=15
        )
        if code:
            return None
        path = out.strip()
        if not path.startswith("/") or "\n" in path:
            raise ValueError("RTK en WSL no devolvió una ruta absoluta")
        return path
    own = Path(state.LIENZO) / "bin" / ("rtk.exe" if os.name == "nt" else "rtk")
    return str(own) if own.is_file() else shutil.which("rtk")


def _instruccion(agent: str, distro: str | None) -> tuple[str | None, str | None]:
    path = ruta(distro)
    if not path:
        return None, "RTK no esta instalado en el entorno elegido; se lanza sin compresion"
    return (
        f"RTK disponible en {path}. Invocalo por esa ruta absoluta; no asumas que esta en PATH. Usa RTK explicitamente para salidas largas de comandos "
        "compatibles, por ejemplo rtk git status o rtk git diff. Conserva los codigos de salida. "
        "Ante un error recupera la salida original o ejecuta el comando diagnostico sin compresion. "
        "No filtres pruebas que requieren logs completos ni cambies hooks o permisos. "
        "En PowerShell una ruta ejecutable con espacios se invoca con el operador de llamada."
    ), None


def _estado(distro: str | None) -> dict:
    path = ruta(distro)
    return {"disponible": bool(path), "detalle": path or "no instalado"}


TOOL = Tool(
    id="rtk",
    nombre="RTK",
    tipo="mejora",
    origen="https://github.com/rtk-ai/rtk",
    descripcion="Comprime salidas largas de comandos; el agente lo invoca explícitamente.",
    version=VERSION,
    preferencia="rtk",
    modos=("general", "ingenieria-reversa"),
    instalar="py ops/preparar-mejoras.py",
    estado=_estado,
    instruccion=_instruccion,
)
