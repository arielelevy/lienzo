"""En qué perfiles de Chrome de esta PC está instalada la extensión Claude in Chrome. La lee el diálogo de
lanzar para que, al darle Chrome a una sesión Claude (`--chrome`), se sepa en qué perfil va a trabajar.
Sólo metadatos: `Local State` (nombre y cuenta del perfil) y si existe la carpeta de la extensión; nunca
se abre nada de la sesión del perfil. La extensión no dice en cuál está conectada: esto es dónde está."""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
from datetime import UTC, datetime

import procinfo
import procs

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


# --- la extensión conectada ahora -------------------------------------------------------------
# Chrome lanza un host nativo por cada conexión de la extensión, con el origen en la línea de
# comando: el de Claude Desktop (chrome-native-host.exe) o el de Claude Code (chrome-native-host.bat
# -> claude.exe). Medido el 2026-10-21: «chrome-native-host.exe chrome-extension://fcoe.../
# --parent-window=0», hijo de un cmd.exe hijo de chrome.exe. El chat no se lee: sólo que está.
ORIGEN = f"chrome-extension://{EXTENSION_ID}/"
_HOSTS = {"chrome-native-host.exe": "desktop", "claude.exe": "code"}
_TTL_CONEXION = 15.0
_cache_conexion: tuple[float, list[dict]] | None = None


def _pids() -> list[int]:
    arr = (ctypes.c_ulong * 8192)()
    needed = ctypes.c_ulong()
    if not ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    return [arr[i] for i in range(needed.value // ctypes.sizeof(ctypes.c_ulong)) if arr[i]]


def conexiones() -> list[dict]:
    """`[{pid, host, desde}]` de los hosts nativos vivos de la extensión: `host` es "desktop" o
    "code" y `desde` la hora de creación en ISO UTC. [] fuera de Windows o si no se puede leer.
    La línea de comando se lee sólo de los procesos con nombre de host (no de los ~400)."""
    if sys.platform != "win32":
        return []
    salida = []
    for pid in _pids():
        host = _HOSTS.get(os.path.basename(procinfo.image_path(pid) or "").lower())
        if not host or ORIGEN not in (procinfo.command_line(pid) or ""):
            continue
        ft = procs.creation_filetime(pid)
        desde = (
            datetime.fromtimestamp((ft - 116444736000000000) / 1e7, UTC).isoformat(timespec="seconds")
            if ft
            else None
        )
        salida.append({"pid": pid, "host": host, "desde": desde})
    return sorted(salida, key=lambda c: c["desde"] or "")


def conexiones_cacheadas() -> list[dict]:
    global _cache_conexion
    ahora = time.monotonic()
    if _cache_conexion is None or ahora - _cache_conexion[0] > _TTL_CONEXION:
        try:
            _cache_conexion = (ahora, conexiones())
        except OSError:  # la salud nunca se cae por esto
            _cache_conexion = (ahora, [])
    return _cache_conexion[1]
