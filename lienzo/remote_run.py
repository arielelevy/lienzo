"""Consultas Git para peers emparejados y comandos locales nombrados; sin shell.

Cada pedido, ejecutado o no, deja una línea en remote_run.jsonl (decisión 10 de Ariel, 2026-10-22):
quién, qué nombre, en qué carpeta, código, duración y tamaño de la salida. No el argv (sale de
config.json y puede llevar una URL con credencial) ni la salida misma."""

import os
import threading
import time
from pathlib import Path

import bitacora
import state
import subproc

TIMEOUT_S = 50
OUTPUT_BYTES = 65536
READ_ONLY_COMMANDS = {
    "status": ["git", "--no-optional-locks", "status", "--short", "--branch"],
    "log": ["git", "--no-pager", "log", "-1", "--format=%H %s"],
}
# opciones largas de git que fuerzan, corren otro programa o escriben un archivo. Git acepta cualquier
# abreviatura sin ambigüedad (--forc, --upload-pac), así que se niega todo prefijo de estas
_OPCIONES_NEGADAS = (
    "force",
    "force-with-lease",
    "force-if-includes",
    "upload-pack",
    "receive-pack",
    "exec",
    "output",
    "strategy",
)
_busy = threading.Semaphore(2)


def _negada(arg: str) -> bool:
    """El refspec +rama, un prefijo de _OPCIONES_NEGADAS o un grupo de opciones cortas con f (-f, -fu).
    Lo corto es estricto a propósito: `-mfix` también cae; el mensaje va aparte (`-m`, `fix`)."""
    if arg.startswith("+"):
        return True
    if arg.startswith("--"):
        nombre = arg[2:].split("=", 1)[0]
        return bool(nombre) and any(o.startswith(nombre) for o in _OPCIONES_NEGADAS)
    return arg.startswith("-") and "f" in arg[1:]


def permitted(argv) -> bool:
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x and "\x00" not in x for x in argv):
        return False
    tool = Path(argv[0]).name.lower().removesuffix(".exe")
    if tool in ("py", "python", "python3"):
        return len(argv) >= 3 and argv[1] == "-m" and argv[2] in ("pytest", "ruff")
    if tool in ("pytest", "ruff", "cr-rate"):
        return True
    return (
        tool == "git"
        and len(argv) >= 2
        and argv[1] in ("status", "fetch", "log", "cherry-pick", "tag", "push")
        and not any(_negada(x) for x in argv[2:])
    )


def run(request: dict, peer: str) -> tuple[int, dict]:
    inicio = time.monotonic()
    code, res = 500, {"error": "error interno"}  # si _run explota, la línea igual queda
    try:
        code, res = _run(request, peer)
    finally:
        _anotar(request, peer, code, res, inicio)
    return code, res


def _anotar(request: dict, peer: str, code: int, res: dict, inicio: float) -> None:
    name, cwd = request.get("command"), request.get("cwd")
    bitacora.anexar(
        bitacora.RUN,
        {
            "peer": bitacora.corto(peer, 64),
            "comando": bitacora.corto(name, 64) if isinstance(name, str) else None,
            "cwd": bitacora.corto(cwd, 300) if isinstance(cwd, str) else None,
            "codigo": code,
            "exit_code": res.get("exit_code"),
            "duracion_s": round(time.monotonic() - inicio, 3),
            "stdout_caracteres": len(res.get("stdout") or ""),
            "stderr_caracteres": len(res.get("stderr") or ""),
            "motivo": bitacora.corto(res.get("error")),
        },
    )


def _run(request: dict, peer: str) -> tuple[int, dict]:
    if not peer:
        return 403, {"error": "solo una PC emparejada puede ejecutar comandos"}
    name, cwd = request.get("command"), request.get("cwd")
    if (
        not isinstance(name, str)
        or not isinstance(cwd, str)
        or not cwd.strip()
        or "\x00" in cwd
        or set(request) - {"command", "cwd"}
    ):
        return 400, {"error": "se espera command (nombre configurado) y cwd, sin argumentos adicionales"}
    cfg = state.load_config()
    commands = cfg.get("run_allowlist")
    if isinstance(commands, dict) and name in commands:
        argv = commands[name]
        allowed_command = permitted(argv)
    else:
        argv = READ_ONLY_COMMANDS.get(name)
        allowed_command = argv is not None
    if not allowed_command:
        return 403, {"error": "comando no permitido en esta PC", "code": "command_not_allowed"}
    roots = cfg.get("launch_roots")
    try:
        folder = Path(cwd).resolve()
        allowed = isinstance(roots, list) and any(
            folder.is_relative_to(Path(root).resolve()) for root in roots if isinstance(root, str) and root.strip()
        )
    except (OSError, ValueError) as exc:
        state.log(f"run rechazado: ruta invalida ({type(exc).__name__})")
        return 400, {"error": "ruta invalida"}
    if not allowed or not folder.is_dir():
        import launch  # aca y no arriba: el modulo no necesita launch salvo para este mensaje

        return 403, {k: launch.FUERA_DE_RAICES[k] for k in ("error", "pista")}
    if not _busy.acquire(blocking=False):
        return 409, {"error": "esta PC ya ejecuta dos comandos remotos"}
    try:
        code, out, err = subproc.correr(
            argv,
            cwd=os.fspath(folder),
            timeout=TIMEOUT_S,
            max_output=OUTPUT_BYTES,
            sin_prompts=True,
        )
        state.log(f"run {name!r} de {peer}: exit={code}")
        return 200, {"ok": code == 0, "exit_code": code, "stdout": out, "stderr": err}
    finally:
        _busy.release()
