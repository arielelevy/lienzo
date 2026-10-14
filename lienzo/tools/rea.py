"""REA (Reverse Engineer Anything): herramienta de trabajo para ingenieria reversa. No es una mejora de
los agentes: solo se inyecta en un lanzamiento en modo "ingenieria-reversa", y solo si esta instalada."""

from __future__ import annotations

import os
import shutil

from . import Tool

ORIGEN = "https://github.com/morluto/rea"


def ubicar() -> str | None:
    """El CLI `rea` del PATH, o el de un checkout compilado en REA_HOME."""
    if exe := shutil.which("rea"):
        return exe
    home = os.environ.get("REA_HOME")
    if home and os.path.isfile(os.path.join(home, "scripts", "rea.mjs")) and os.path.isdir(os.path.join(home, "dist")):
        return f"node {os.path.join(home, 'scripts', 'rea.mjs')}"
    return None


def _estado(distro: str | None) -> dict:
    if distro:
        return {"disponible": False, "detalle": "REA en WSL no verificada"}
    exe = ubicar()
    return {"disponible": bool(exe), "detalle": exe or "no instalada (ver su README: rea setup)"}


def _instruccion(agent: str, distro: str | None) -> tuple[str | None, str | None]:
    if distro:
        return None, "REA en WSL no verificada; no se inyecta la instalación de Windows"
    exe = ubicar()
    if not exe:
        return None, "REA no esta instalada en esta PC; se lanza el modo ingenieria reversa sin ella"
    return (
        f"Trabajo de ingenieria reversa: REA esta disponible ({exe}). Distingue observaciones, derivaciones, "
        "inferencias y desconocidos, y conserva la evidencia de cada afirmacion. No modifiques binarios ni guardes "
        "bases de IDA/Ghidra adjuntas."
    ), None


TOOL = Tool(
    id="rea",
    nombre="REA",
    tipo="trabajo",
    origen=ORIGEN,
    descripcion="Ingeniería reversa con evidencia (Ghidra, IDA, Hopper); solo en el modo ingeniería reversa.",
    modos=("ingenieria-reversa",),
    instalar="clonar el repo, npm ci, npm run build:cached y rea setup (o REA_HOME al checkout compilado)",
    estado=_estado,
    instruccion=_instruccion,
)
