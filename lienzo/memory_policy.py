"""Qué carpetas locales pueden generar memoria automática; no altera las tarjetas del tablero."""

from __future__ import annotations

import os
import tempfile

import state


def _normal(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _physical(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _debajo(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False  # unidades distintas no son una relación de descendencia


def _launch_roots() -> list[str]:
    roots = state.load_config().get("launch_roots")
    if not isinstance(roots, list):
        return []
    return [r for r in roots if isinstance(r, str) and r.strip()]


def _descartables() -> list[str]:
    """Carpetas de trabajo descartables además de los temporales del sistema: las de la app de escritorio de
    Claude, una por conversación (de ahí salieron los 4 `scratch-*` sin remote del 2026-10-17), y las que se
    sumen en `memoria_excluir` de config.json."""
    out = []
    if os.environ.get("APPDATA"):
        out.append(os.path.join(os.environ["APPDATA"], "Claude", "scratch-workspaces"))
    extra = state.load_config().get("memoria_excluir")
    if isinstance(extra, list):
        out += [r for r in extra if isinstance(r, str) and r.strip()]
    return out


def excluida(cwd: str | None) -> bool:
    """TEMP, TMP, gettempdir y las carpetas descartables (`_descartables`), salvo un destino físico bajo
    launch_roots. Configuración sin caché propia."""
    if not cwd:
        return False
    try:
        logical, physical = _normal(cwd), _physical(cwd)
        roots = [r for r in (os.environ.get("TEMP"), os.environ.get("TMP"), tempfile.gettempdir()) if r]
        roots += _descartables()
        temporal = any(_debajo(logical, _normal(r)) or _debajo(physical, _physical(r)) for r in roots)
        if not temporal:
            return False
        return not any(_debajo(physical, _physical(r)) for r in _launch_roots())
    except (OSError, ValueError) as e:
        state.log(f"memoria: carpeta no evaluable, se excluye ({type(e).__name__})")
        return True
