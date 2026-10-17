"""La integración existente de Anatomy, como tool de documentación visual."""

from __future__ import annotations

import os
from pathlib import Path

import state

from . import Tool


def _estado(distro: str | None) -> dict:
    if distro:
        return {"disponible": False, "detalle": "Anatomy en WSL no verificada"}
    explicit = os.environ.get("ANATOMY_DIR")
    candidates = (
        [Path(explicit)]
        if explicit
        else [Path.home() / ".claude/skills/anatomy", Path.home() / ".agents/skills/anatomy"]
    )
    kit_files = ("SKILL.md", "kit/iso-kit.mjs", "kit/tube.mjs", "kit/lathe.mjs")
    kit = next((p for p in candidates if all((p / f).is_file() for f in kit_files)), None)
    integration = Path(state.ROOT) / "skills/lienzo-infografias/build.mjs"
    ready = kit is not None and integration.is_file()
    detail = (
        f"kit {kit}; integración {integration}" if ready else "falta el kit Anatomy o la integración de infografías"
    )
    return {"disponible": ready, "detalle": detail + "; no acredita render ni verificación visual"}


TOOL = Tool(
    id="anatomy",
    nombre="Anatomy",
    tipo="documentacion",
    formato="skill",
    origen="https://github.com/wheresryan22/anatomy",
    descripcion="Figuras SVG para explicar Lienzo y documentar sus mecanismos; reutiliza skills/lienzo-infografias.",
    estado=_estado,
    limitaciones=("La documentación visual no sustituye pruebas, review ni auditoría.",),
)
