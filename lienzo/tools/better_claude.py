"""Ficha de Better Claude en Lienzo: sólo Commit. Image Preview y Sub Meter se usan en Claude Code pero no
son parte de Lienzo (Ariel, 2026-10-17). Sólo inspecciona instalación y activación locales.

No instalan, cambian settings/hooks ni ejecutan comandos del plugin.
Una instalación Windows no acredita disponibilidad en WSL o en un agente distinto.
"""

from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path

from . import Tool

MARKETPLACE = "better-claude"
ORIGEN = "https://github.com/midudev/better-claude/tree/main/plugins/"


def _home() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def _json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"no se pudo verificar {path.name}: {type(error).__name__}") from error
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} debe ser un objeto")
    return data


def _user_records(key: str) -> list[dict]:
    registry = _json(_home() / "plugins/installed_plugins.json")
    installed = registry.get("plugins", {})
    if not isinstance(installed, dict) or not isinstance(installed.get(key, []), list):
        raise TypeError("registro de plugins inválido")
    records = installed.get(key, [])
    if any(not isinstance(record, dict) for record in records):
        raise TypeError("entrada de plugin inválida")
    return [r for r in records if r.get("scope") == "user"]


def _record_problem(name: str, record: dict) -> str | None:
    """Por qué un registro no acredita la instalación, o None si la acredita."""
    location = record.get("installPath")
    if not isinstance(location, str) or not Path(location).is_absolute():
        return "installPath debe ser una ruta absoluta"
    manifest = Path(location) / ".claude-plugin/plugin.json"
    if not manifest.is_file():
        return "archivos del plugin ausentes"
    try:
        data = _json(manifest)
    except (TypeError, ValueError) as error:
        return str(error)
    if data.get("name") != name:
        return "manifiesto no coincide con el plugin registrado"
    return None


def _installation(name: str, records: list[dict]) -> dict | None:
    """El primer registro válido. Uno viejo no tapa a otro válido; sin ninguno, un registro inválido
    se informa como error y uno con archivos ausentes como no instalado."""
    problems = []
    for record in records:
        problem = _record_problem(name, record)
        if problem is None:
            return record
        problems.append(problem)
    invalid = [p for p in problems if p != "archivos del plugin ausentes"]
    if invalid:
        raise ValueError(invalid[0])
    return None


def _estado(name: str, distro: str | None) -> dict:
    if distro:
        return {"disponible": False, "detalle": "plugin de Claude Code en WSL no verificado"}
    key = f"{name}@{MARKETPLACE}"
    user = _user_records(key)
    if not user:
        return {
            "disponible": False,
            "instalado": False,
            "detalle": "sin instalación de usuario verificada; instalaciones de proyecto requieren su contexto",
        }
    record = _installation(name, user)
    if record is None:
        return {"disponible": False, "instalado": False, "detalle": "registro presente, archivos del plugin ausentes"}
    version = record.get("version") if isinstance(record.get("version"), str) else None
    enabled = _json(_home() / "settings.json").get("enabledPlugins", {})
    if not isinstance(enabled, dict):
        raise TypeError("enabledPlugins inválido")
    active = enabled.get(key) is True
    return {
        "disponible": active,
        "instalado": True,
        "version_instalada": version,
        "detalle": (
            "instalado y habilitado para Claude Code; sesión nueva/reinicio y compatibilidad del mod por verificar"
            if active
            else "instalado; habilitación de usuario no verificada"
        ),
    }


def _tool(name, title, kind, description, limits, *, cost="gratis"):
    return Tool(
        id=name,
        nombre=title,
        tipo=kind,
        formato="plugin-claude",
        compatible_con=("claude",),
        origen=ORIGEN + name,
        descripcion=description,
        costo=cost,
        instalar=f"claude plugin marketplace add midudev/better-claude; claude plugin install {name}@better-claude --scope user",
        estado=partial(_estado, name),
        limitaciones=limits,
    )


TOOLS = (
    _tool(
        "commit",
        "Commit",
        "trabajo",
        "Comando /commit de Claude Code: agrupa cambios y permite elegir commit, commit/push o rama nueva; usa un modelo de la cuenta (Haiku 5.5 según el autor).",
        (
            "En modo no interactivo, el comportamiento documentado hace commit y push; Lienzo no lo ejecuta automáticamente.",
            "La opción de rama nueva también hace push; con commit + push publica la rama actual, main incluida.",
            "No sustituye pruebas, review ni auditoría; requiere decidir qué cambios publicar.",
            "El plugin es gratuito; su modelo consume cuota o saldo de la cuenta de Claude.",
        ),
    ),
)
