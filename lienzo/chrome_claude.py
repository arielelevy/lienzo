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


# --- las extensiones conectadas ahora ---------------------------------------------------------
# Chrome lanza un host nativo por cada conexión de una extensión, con el origen en la línea de
# comando. Claude: el de Claude Desktop (chrome-native-host.exe) o el de Claude Code
# (chrome-native-host.bat -> claude.exe). Codex: la extensión «ChatGPT» con el host del plugin de
# Codex (~/.codex/plugins/.../extension-host.exe, com.openai.codexextension). Medido el 2026-10-21:
# «<host>.exe chrome-extension://<id>/ --parent-window=0», hijo de un cmd.exe hijo de chrome.exe.
# El chat no se lee: sólo que está.
ORIGEN = f"chrome-extension://{EXTENSION_ID}/"
# nombre del ejecutable -> (agente, por donde, orígenes que valen)
_HOSTS = {
    "chrome-native-host.exe": ("claude", "desktop", (ORIGEN,)),
    "claude.exe": ("claude", "code", (ORIGEN,)),
    "extension-host.exe": (
        "codex",
        "codex",
        (
            "chrome-extension://hehggadaopoacecdllhhajmbjkdcmajg/",
            "chrome-extension://odlomjlbamekndcpllcnffbgeohgkmjh/",
        ),
    ),
}
_TTL_CONEXION = 15.0
_cache_conexion: tuple[float, list[dict]] | None = None


def _pids() -> list[int]:
    arr = (ctypes.c_ulong * 8192)()
    needed = ctypes.c_ulong()
    if not ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    return [arr[i] for i in range(needed.value // ctypes.sizeof(ctypes.c_ulong)) if arr[i]]


def conexiones() -> list[dict]:
    """`[{agent, host, pids, desde}]`: una por agente y por donde se conecta, con los hosts
    nativos vivos de su extensión. `host` es "desktop" o "code" (Claude) o "codex", y `desde` la
    creación del más viejo en ISO UTC. Codex abre más de un host a la vez y es una sola extensión.
    [] fuera de Windows. La línea de comando se lee sólo de los procesos con nombre de host."""
    if sys.platform != "win32":
        return []
    grupos: dict[tuple[str, str], dict] = {}
    for pid in _pids():
        conocido = _HOSTS.get(os.path.basename(procinfo.image_path(pid) or "").lower())
        if not conocido:
            continue
        agent, host, origenes = conocido
        cmd = procinfo.command_line(pid) or ""
        if not any(o in cmd for o in origenes):
            continue
        ft = procs.creation_filetime(pid)
        desde = (
            datetime.fromtimestamp((ft - 116444736000000000) / 1e7, UTC).isoformat(timespec="seconds") if ft else None
        )
        g = grupos.setdefault((agent, host), {"agent": agent, "host": host, "pids": [], "desde": desde})
        g["pids"].append(pid)
        if desde and (not g["desde"] or desde < g["desde"]):
            g["desde"] = desde
    return sorted(grupos.values(), key=lambda c: (c["agent"], c["host"]))


def conexiones_cacheadas() -> list[dict]:
    global _cache_conexion
    ahora = time.monotonic()
    if _cache_conexion is None or ahora - _cache_conexion[0] > _TTL_CONEXION:
        try:
            _cache_conexion = (ahora, conexiones())
        except OSError:  # la salud nunca se cae por esto
            _cache_conexion = (ahora, [])
    return _cache_conexion[1]
