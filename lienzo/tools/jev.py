"""Jev: el juez de mejoras (modelo de typesafe por OpenRouter Decisions). La integracion vive en
lienzo/jev.py y lienzo/agent_suggestions.py; aca se declara de donde sale y si esta PC puede usarlo."""

from __future__ import annotations

from . import Tool


def _estado(distro: str | None) -> dict:
    import jev
    import jev_credentials

    disponible = jev_credentials.available()
    return {
        "disponible": disponible,
        "detalle": f"modelo {jev.MODEL}" if disponible else "falta la credencial (py ops/importar-jev.py)",
    }


TOOL = Tool(
    id="jev",
    nombre="Jev",
    tipo="evaluacion",
    origen="https://openrouter.ai/typesafe/jev-1.13",
    descripcion="Juzga las métricas visibles de una sesión y propone una mejora; cada consulta es paga y se autoriza.",
    version="typesafe/jev-1.13",
    costo="pago",
    instalar="py ops/importar-jev.py --distro <distro>",
    estado=_estado,
)
