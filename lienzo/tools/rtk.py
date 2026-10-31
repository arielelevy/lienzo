"""RTK: compacta lecturas, búsquedas y salidas largas de los agentes. Lienzo instala el binario
(ops/preparar-mejoras.py, con SHA-256 publicado) y, al lanzar, le indica al agente usarlo por ruta
absoluta. No instala hooks."""

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


def hay_rg(distro: str | None = None) -> bool:
    """`rtk rg` corre el `rg` del sistema: sin él falla («Binary 'rg' not found on PATH»)."""
    if distro:
        code, _, _ = subproc.correr(["wsl.exe", "-d", distro, "--exec", "bash", "-lc", "command -v rg"], timeout=15)
        return not code
    return shutil.which("rg") is not None


def _instruccion(agent: str, distro: str | None) -> tuple[str | None, str | None]:
    path = ruta(distro)
    if not path:
        return None, "RTK no esta instalado en el entorno elegido; se lanza sin compresion"
    # sin rg en la PC, rtk rg falla y el agente caia a la herramienta nativa sin decirlo (openSeec, 2026-10-30)
    busqueda = "rtk rg" if hay_rg(distro) else "rtk grep (rg no esta instalado en esta PC: rtk rg falla)"
    return (
        f"RTK disponible en {path}. Invocalo por esa ruta absoluta; no asumas que esta en PATH. Usa RTK explicitamente para lecturas y busquedas con rtk read, {busqueda}, rtk find, rtk git y rtk recall, cuando sean compatibles. Tambien para salidas largas de comandos "
        "compatibles, por ejemplo rtk git status o rtk git diff. Conserva los codigos de salida. "
        "Ante un error recupera la salida original o ejecuta el comando diagnostico sin compresion. "
        "No filtres pruebas que requieren logs completos ni cambies hooks o permisos. "
        "En PowerShell una ruta ejecutable con espacios se invoca con el operador de llamada."
    ), None


def _estado(distro: str | None) -> dict:
    path = ruta(distro)
    detalle = (path + ("" if hay_rg(distro) else "; sin rg: rtk rg falla, usar rtk grep")) if path else "no instalado"
    return {"disponible": bool(path), "detalle": detalle}


TOOL = Tool(
    id="rtk",
    nombre="RTK",
    tipo="mejora",
    origen="https://github.com/rtk-ai/rtk",
    descripcion="Compacta lecturas, búsquedas y salidas largas; el agente lo invoca explícitamente.",
    version=VERSION,
    preferencia="rtk",
    modos=("general", "ingenieria-reversa"),
    instalar="py ops/preparar-mejoras.py",
    estado=_estado,
    instruccion=_instruccion,
)
