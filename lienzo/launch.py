"""Lanzar una sesion nueva en esta PC (plan multi-PC §3.7): escribe un .cmd que hace chcp, pone el
titulo, entra al cwd y llama al ejecutable del agente por ruta absoluta, y lo abre con
explorer.exe, que desacopla el entorno --el mismo truco del skill `lienzo`: un `claude` hijo
lanzado directo desde una sesion de Claude Code hereda CLAUDECODE y compania, se cree anidado y se
apaga solo sin decir nada--. Restringido a `launch_roots` (config.json) y a los cuatro agentes
conocidos; el titulo se sanea antes de escribirlo, nunca se interpreta como comando.

En Mac/Linux/WSL no hay .cmd ni explorer.exe: la sesion se abre adentro de tmux (`tmux new-session
-d`), porque fuera de tmux el lienzo la ve pero no le puede escribir (un PTY es de quien lo creo). El
mismo desacople del entorno lo hace `env -u` con las variables de Claude Code."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys

import state
from agentes import AGENTES

WINDOWS = sys.platform == "win32"

# los ejecutables salen del registro de agentes (agentes.py); el nombre queda porque lo leen otros
AGENT_EXES = {nombre: p.exe for nombre, p in AGENTES.items()}
# las que hacen que un `claude` hijo se crea anidado y se apague solo (ver el docstring)
_CLAUDE_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT")

# en un .cmd, & | < > ^ % reinterpretan la linea (separan comandos o expanden variables) y " cierra
# la comilla del titulo antes de tiempo; fuera, el titulo nunca se interpreta como comando
_UNSAFE_TITLE_RE = re.compile(r'[&|<>^%"\r\n]')

# retomar una sesion (restore.py): claude y codex por id, pi y coda "la ultima de esta carpeta" (sin
# id), segun el registro de agentes. El id se interpola en la linea del .cmd, asi que solo entra si
# es [0-9a-fA-F-]{8,40}
_RESUME_ID_RE = re.compile(r"[0-9a-fA-F-]{8,40}")


def _resume_args(agent: str, resume: str | None) -> list[str]:
    """Argumentos para retomar, o [] si no se puede (sin pedido, o un id que no es de verdad para
    un agente que retoma por id). Cada elemento es seguro de escribir tal cual en el .cmd."""
    p = AGENTES.get(agent)
    if not resume or p is None:
        return []
    if p.retomar_ultima:
        return list(p.retomar_ultima)
    if p.retomar_por_id and isinstance(resume, str) and _RESUME_ID_RE.fullmatch(resume):
        return [*p.retomar_por_id, resume]
    return []


# elegir el modelo al lanzar: los que el registro marca con acepta_modelo (coda, claude y codex) lo
# reciben con --model. El id entra en la linea del .cmd, asi que solo pasa [A-Za-z0-9._/:@-] (sin
# espacios ni nada que reinterprete el .cmd)
_MODEL_RE = re.compile(r"[A-Za-z0-9._/:@-]{1,80}")


def _model_args(agent: str, model: str | None) -> list[str]:
    """`--model <id>` si el agente lo soporta y el id es valido; [] si no."""
    p = AGENTES.get(agent)
    if isinstance(model, str) and p is not None and p.acepta_modelo and _MODEL_RE.fullmatch(model):
        return ["--model", model]
    return []


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


def _cuota_coda() -> str | None:
    try:
        import health

        return health.coda_cuota(esperar=True)
    except Exception:  # no poder medir no frena un lanzamiento
        return None


def launch(cwd: str, title: str, agent: str, resume: str | None = None, model: str | None = None) -> dict:
    """Escribe el .cmd en `<LIENZO_HOME>/launch/` y lo lanza con explorer.exe. Rechaza (sin tocar
    disco ni proceso) un `cwd` fuera de `launch_roots` y un `agent` desconocido. Devuelve
    `{ok, cmd_path}`; buscar la tarjeta nueva lo hace despues el server (rescan de por medio).
    Con `resume` (el session_id a retomar) agrega el retomar del agente; si el id no es valido para
    un agente que retoma por id (p. ej. `pid-123`) lanza sin retomar y lo dice: `resumed: false`."""
    exe_name = AGENT_EXES.get(agent)
    if exe_name is None:
        return {"ok": False, "error": f"agente desconocido: {agent!r}"}
    if agent == "coda" and _cuota_coda() == "agotada":
        # abriria una terminal que falla en el primer turno (medido el 2026-10-04)
        return {
            "ok": False,
            "code": 409,
            "error": "coda no tiene cuota en esta PC («Quota exceeded»): lanzá en otra PC u otro agente",
        }
    if not _cwd_allowed(cwd, _allowed_roots()):
        return {"ok": False, "error": "cwd fuera de launch_roots"}
    if not WINDOWS:
        exe_name = exe_name.removesuffix(".exe")
    exe_path = _exe_path(exe_name)
    if exe_path is None:
        return {"ok": False, "error": f"no encuentro {exe_name} en esta PC"}
    resume_args = _resume_args(agent, resume)
    model_args = _model_args(agent, model)
    extra = [*resume_args, *model_args]
    res = _launch_cmd(cwd, title, exe_path, extra) if WINDOWS else _launch_tmux(cwd, title, exe_path, extra)
    if resume is not None:
        res["resumed"] = bool(resume_args)
    if model is not None:
        res["model_applied"] = bool(model_args)
    return res


def _launch_cmd(cwd: str, title: str, exe_path: str, extra: list[str]) -> dict:
    """Windows: un .cmd en `<LIENZO_HOME>/launch/` que explorer.exe abre en una consola nueva."""
    launch_dir = os.path.join(state.LIENZO, "launch")
    os.makedirs(launch_dir, exist_ok=True)
    cmd_path = os.path.join(launch_dir, f"{secrets.token_hex(6)}.cmd")
    cuerpo = (
        "@echo off\r\n"
        "chcp 1252 >nul\r\n"
        f"title {_sanitize_title(title)}\r\n"
        f'cd /d "{cwd}"\r\n'
        f'"{exe_path}"{"".join(" " + a for a in extra)}\r\n'
    )
    with open(cmd_path, "w", encoding="cp1252", errors="replace", newline="") as f:
        f.write(cuerpo)
    subprocess.Popen(["explorer.exe", cmd_path])
    return {"ok": True, "cmd_path": cmd_path}


def _launch_tmux(cwd: str, title: str, exe_path: str, extra: list[str] | None = None) -> dict:
    """Mac/Linux/WSL: una sesion de tmux nueva y suelta (-d) con el agente adentro, en `cwd`, con el
    titulo como nombre de ventana. Va como lista de argumentos, sin shell: ni el titulo ni el cwd se
    interpretan. El barrido la encuentra despues por el pane, como a cualquier agente en tmux."""
    nombre = f"lienzo-{secrets.token_hex(3)}"
    unset = [a for v in _CLAUDE_ENV for a in ("-u", v)]
    argv = ["tmux", "new-session", "-d", "-s", nombre, "-n", _sanitize_title(title), "-c", cwd]
    argv += ["env", *unset, exe_path, *(extra or [])]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "error": f"no se pudo abrir tmux: {e}"}
    return {"ok": True, "tmux_session": nombre}
