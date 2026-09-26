"""Lanzar una sesion nueva en esta PC (plan multi-PC §3.7): escribe un .cmd que hace chcp, pone el
titulo, entra al cwd y llama al ejecutable del agente por ruta absoluta, y lo abre con
explorer.exe, que desacopla el entorno --el mismo truco del skill `lienzo`: un `claude` hijo
lanzado directo desde una sesion de Claude Code hereda CLAUDECODE y compania, se cree anidado y se
apaga solo sin decir nada--. Restringido a `launch_roots` (config.json) y a los cuatro agentes
conocidos; el titulo se sanea antes de escribirlo, nunca se interpreta como comando."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess

import state

AGENT_EXES = {
    "claude": "claude.exe",
    "codex": "codex.exe",
    "pi": "pi.exe",
    "coda": "coda.exe",
}

# en un .cmd, & | < > ^ % reinterpretan la linea (separan comandos o expanden variables) y " cierra
# la comilla del titulo antes de tiempo; fuera, el titulo nunca se interpreta como comando
_UNSAFE_TITLE_RE = re.compile(r'[&|<>^%"\r\n]')


def _sanitize_title(title: str) -> str:
    limpio = _UNSAFE_TITLE_RE.sub(" ", (title or "").strip())
    return state.short(" ".join(limpio.split()), 120) or "lienzo"


def _allowed_roots() -> list[str]:
    """`launch_roots` de config.json, normalizadas para comparar con `cwd`. Vacia o ausente:
    ninguna (§3.7: "vacía = no se lanza nada"), no todas."""
    roots = state.load_config().get("launch_roots")
    if not isinstance(roots, list):
        return []
    return [os.path.normcase(os.path.normpath(r)) for r in roots if isinstance(r, str) and r.strip()]


# aparte para que los tests no tengan que crear cada carpeta que prueban
_existe = os.path.isdir


def _cwd_allowed(cwd: str, roots: list[str]) -> bool:
    # % expande variables adentro del .cmd aunque vaya entre comillas, y " las cierra
    if not cwd or not roots or any(c in cwd for c in '"%\r\n') or not _existe(cwd):
        return False
    norm = os.path.normcase(os.path.normpath(cwd))
    return any(norm == root or norm.startswith(root + os.sep) for root in roots)


def _exe_path(exe_name: str) -> str | None:
    """Por ruta absoluta, porque el PATH no se hereda entero por explorer.exe: primero donde lo deja
    el instalador de Claude Code (~/.local/bin), despues el PATH de este server."""
    propio = os.path.join(state.HOME, ".local", "bin", exe_name)
    return propio if os.path.isfile(propio) else shutil.which(exe_name)


def launch(cwd: str, title: str, agent: str) -> dict:
    """Escribe el .cmd en `<LIENZO_HOME>/launch/` y lo lanza con explorer.exe. Rechaza (sin tocar
    disco ni proceso) un `cwd` fuera de `launch_roots` y un `agent` desconocido. Devuelve
    `{ok, cmd_path}`; buscar la tarjeta nueva lo hace despues el server (rescan de por medio)."""
    exe_name = AGENT_EXES.get(agent)
    if exe_name is None:
        return {"ok": False, "error": f"agente desconocido: {agent!r}"}
    if not _cwd_allowed(cwd, _allowed_roots()):
        return {"ok": False, "error": "cwd fuera de launch_roots"}
    exe_path = _exe_path(exe_name)
    if exe_path is None:
        return {"ok": False, "error": f"no encuentro {exe_name} en esta PC"}
    launch_dir = os.path.join(state.LIENZO, "launch")
    os.makedirs(launch_dir, exist_ok=True)
    cmd_path = os.path.join(launch_dir, f"{secrets.token_hex(6)}.cmd")
    cuerpo = (
        "@echo off\r\n"
        "chcp 1252 >nul\r\n"
        f"title {_sanitize_title(title)}\r\n"
        f'cd /d "{cwd}"\r\n'
        f'"{exe_path}"\r\n'
    )
    with open(cmd_path, "w", encoding="cp1252", errors="replace", newline="") as f:
        f.write(cuerpo)
    subprocess.Popen(["explorer.exe", cmd_path])
    return {"ok": True, "cmd_path": cmd_path}
