"""Comandos remotos nombrados y aprobados en config.json; sin shell ni argumentos del pedido."""

import os
import threading
from pathlib import Path

import state
import subproc

TIMEOUT_S = 50
OUTPUT_BYTES = 65536
_busy = threading.Semaphore(2)


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
        and not any(x == "-f" or x.startswith(("--force", "+")) for x in argv[2:])
    )


def run(request: dict, peer: str) -> tuple[int, dict]:
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
    argv = commands.get(name) if isinstance(commands, dict) else None
    if not permitted(argv):
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
        return 403, {"error": "cwd fuera de launch_roots"}
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
