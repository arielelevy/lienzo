"""Pruebas agenticas: runner de pruebas en cinco roles (repo aparte). Lienzo trae su config en
`pruebas-agenticas/pruebas-agenticas.json`; el runner sale del plugin instalado."""

from __future__ import annotations

import json
import os

from . import Tool

# donde lo buscan los clientes: el checkout local y la cache de plugins de Codex
UBICACIONES = (
    os.environ.get("PRUEBAS_AGENTICAS_PLUGIN") or "",
    "D:/Apps/pruebas-agenticas",
    os.path.join(os.path.expanduser("~"), ".codex", "plugins", "cache", "pruebas-agenticas", "pruebas-agenticas"),
)


def ubicar() -> tuple[str, str] | None:
    """(carpeta del plugin, version) del primer plugin.json legible, o None."""
    for base in UBICACIONES:
        if not base or not os.path.isdir(base):
            continue
        candidatos = [base] + sorted((os.path.join(base, d) for d in os.listdir(base)), reverse=True)
        for c in candidatos:
            try:
                with open(os.path.join(c, "plugin.json"), encoding="utf-8") as f:
                    return c, str(json.load(f).get("version") or "?")
            except OSError, ValueError:
                continue
    return None


def _estado(distro: str | None) -> dict:
    hallado = ubicar()
    if not hallado:
        return {"disponible": False, "detalle": "plugin no encontrado"}
    return {"disponible": True, "detalle": f"{hallado[0]} (v{hallado[1]})"}


TOOL = Tool(
    id="pruebas-agenticas",
    nombre="Pruebas agénticas",
    tipo="pruebas",
    origen="D:/Apps/pruebas-agenticas",
    descripcion="Runner de pruebas en cinco roles (Explorer → Detective) con mutación y compuerta; obligatorio al cambiar código.",
    estado=_estado,
)
