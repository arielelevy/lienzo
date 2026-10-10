"""Capacidades del servidor publicadas en la salud autenticada de cada PC."""

import os

import state
import tmux

VERSION = 1
CAPABILITIES = (
    "rules.create",
    "rules.retarget",
    "sessions.actions",
    "snapshot",
    "restore",
    "secrets",
    "xfer",
    "run.named",
    "browser.remote",
    "browser.window",
    "browser.stream",
    "memoria.replica",
)


CARPETAS_MAX = 300  # tope de carpetas de proyecto que viajan en la salud (una raiz como D:/apps puede tener muchas)


def carpetas_de_proyecto(roots: list[str]) -> list[str]:
    """Los proyectos que existen en disco dentro de `launch_roots`, para que el dialogo de lanzar los ofrezca
    tengan o no sesiones abiertas (pedido de Ariel, 2026-10-10: «mientras la carpeta exista, que me muestre
    el proyecto»). Una raiz que es un repo (tiene .git) es un proyecto; una que agrupa varios (D:/apps)
    ofrece cada repo de adentro, un nivel. Una raiz que no existe no ofrece nada: lanzar ahi da 400."""
    out: list[str] = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        if os.path.exists(os.path.join(r, ".git")):
            out.append(r.replace("\\", "/"))
            continue
        try:
            with os.scandir(r) as it:
                hijas = sorted(
                    e.path
                    for e in it
                    if e.is_dir(follow_symlinks=False) and os.path.exists(os.path.join(e.path, ".git"))
                )
        except OSError:
            continue
        out += [h.replace("\\", "/") for h in hijas]
        if len(out) >= CARPETAS_MAX:
            return out[:CARPETAS_MAX]
    return out


def info() -> dict:
    cfg = state.load_config()
    roots = cfg.get("launch_roots")
    roots = [r for r in roots if isinstance(r, str)] if isinstance(roots, list) else []
    return {
        "protocol_version": VERSION,
        "capabilities": list(CAPABILITIES),
        "launch_roots": roots,
        "carpetas": carpetas_de_proyecto(roots),
        # las distros de WSL de esta PC: el dialogo de lanzar las lee de la salud de cada PC (GET /peers);
        # [] fuera de Windows con WSL. Cacheadas 60 s en tmux.distros
        "distros_wsl": tmux.distros(),
    }
