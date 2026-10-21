"""En qué perfiles de Chrome de esta PC está instalada la extensión Claude in Chrome. La lee el diálogo de
lanzar para que, al darle Chrome a una sesión Claude (`--chrome`), se sepa en qué perfil va a trabajar.
Sólo metadatos: `Local State` (nombre y cuenta del perfil) y si existe la carpeta de la extensión; nunca
se abre nada de la sesión del perfil. La extensión no dice en cuál está conectada: esto es dónde está."""

from __future__ import annotations

import json
import os
import re
import sys
import time

# el id que autoriza el host nativo de Claude Code (com.anthropic.claude_code_browser_extension.json)
EXTENSION_ID = "fcoeoabgfenejglbffodgkkbkcdhcgfn"
_PERFIL_RE = re.compile(r"Default|Profile \d+")
_TTL = 60.0
_cache: tuple[float, list[dict]] | None = None


def user_data_dir() -> str | None:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return os.path.join(local, "Google", "Chrome", "User Data") if local else None
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    return os.path.expanduser("~/.config/google-chrome")


def perfiles(root: str | None = None) -> list[dict]:
    """`[{id, name, cuenta}]` de los perfiles con la extensión; [] sin Chrome o si no se puede leer."""
    root = root or user_data_dir()
    if not root:
        return []
    try:
        with open(os.path.join(root, "Local State"), encoding="utf-8") as f:
            cache = json.load(f).get("profile", {}).get("info_cache")
    except OSError, ValueError, AttributeError:
        return []
    if not isinstance(cache, dict):
        return []
    salida = []
    for pid, valor in sorted(cache.items()):
        if not _PERFIL_RE.fullmatch(pid) or not isinstance(valor, dict):
            continue
        if not os.path.isdir(os.path.join(root, pid, "Extensions", EXTENSION_ID)):
            continue
        nombre = valor.get("name") if isinstance(valor.get("name"), str) else pid
        cuenta = valor.get("user_name") if isinstance(valor.get("user_name"), str) else ""
        salida.append({"id": pid, "name": nombre, "cuenta": cuenta})
    return salida


def perfiles_cacheados() -> list[dict]:
    global _cache
    ahora = time.monotonic()
    if _cache is None or ahora - _cache[0] > _TTL:
        _cache = (ahora, perfiles())
    return _cache[1]
