"""Fuentes de agentes, agregadas. Antes elegia UNA por plataforma; ahora suma varias, asi un mismo
board ve los dos mundos:

  Windows:  win32 (procesos de Windows, procs.py)  +  tmux via wsl.exe (panes de WSL, tmux.py)
  Mac/Linux: tmux nativo (tmux.py)

Cada tarjeta/evento lleva `backend` ("win32" | "tmux"); las funciones rutean por ese campo, y sin
campo caen al primario de la plataforma. El resto del server llama a `backend.*` sin saber cual es.
Sin ciclo de imports: no importa sessions ni state."""

from __future__ import annotations

import sys

import tmux as _t

IS_WINDOWS = sys.platform == "win32"
NAME = "win32" if IS_WINDOWS else "tmux"  # backend primario / default de la plataforma
_AGENT_COMMS = {"claude", "codex", "node"}  # claude/codex nativos, o corriendo sobre node

if IS_WINDOWS:
    import procs as _win
else:
    _win = None

HAS_TMUX = _t.available()  # hay fuente tmux: nativa en Unix, via wsl.exe en Windows


def is_tmux(d: dict) -> bool:
    """Esta tarjeta/evento va por la fuente tmux. El campo `backend` manda; sin campo, el default de
    la plataforma (win32 en Windows, tmux en Unix)."""
    b = d.get("backend")
    return b == "tmux" if b else NAME == "tmux"


def proc_key(d: dict) -> tuple[bool, str, int | None]:
    """Con que se identifica un proceso entre fuentes: el pid solo no alcanza, porque un pid de
    Windows y uno de WSL pueden tener el mismo numero y son procesos distintos; y dos distros de WSL
    tambien pueden tener el mismo numero (son maquinas distintas). Sin distro (un evento de hook, el
    tmux nativo) la clave cae en "", igual que una tarjeta sin distro."""
    return is_tmux(d), d.get("distro") or "", d.get("pid")


def _tarjeta_tmux(a: dict, distro: str | None) -> dict:
    """La tarjeta de un agente de la fuente tmux, con la forma de procs.sweep() mas `cwd`, `target`
    (el pane, o None si esta suelto) y `backend`. La distro va siempre que el agente venga de WSL
    (tambien la default —criterio 2.2—); nativo va sin distro (criterio 2.3)."""
    t = {
        "pid": a["pid"],
        "agent": a["agent"],
        "exe": a.get("command") or a["comm"],
        "created": None,
        "parent": "tmux",
        "grandparent": None,
        "in_vscode": False,
        "orphan": False,
        "cwd": a.get("cwd"),
        "target": a.get("target"),
        "no_console": a.get("target") is None,
        "backend": "tmux",
    }
    if distro:
        t["distro"] = distro
    return t


def _tmux_sweep() -> list[dict]:
    """Todos los agentes claude/codex (en tmux o sueltos), con la forma de procs.sweep() mas `cwd`,
    `target` (el pane, o None si esta suelto), `backend` y `distro` (siempre que el agente venga de
    WSL —tambien la default—; nativo va sin distro). Los panes se consultan una vez por distro (la
    misma forma de list_panes_todas, adentro de all_agents), asi el barrido ve los agentes de todas
    las distros, no solo los de la default. Con una sola distro (o nativo) es el camino de hoy: una
    sola llamada a all_agents, en serie. Los sueltos van en solo lectura (no_console): se ven y se
    leen, pero no se les escribe (no hay pane; ver docs/porting-linux-2026-09-08.md)."""
    ds = _t.distros()
    if len(ds) <= 1:
        distro = ds[0] if ds else None
        return [_tarjeta_tmux(a, distro) for a in _t.all_agents(distro)]
    out = []
    for d in ds:  # una distro que no corre devuelve [] (rc != 0) y no corta a las demas
        for a in _t.all_agents(distro=d):
            out.append(_tarjeta_tmux(a, d))
    return out


def sweep() -> list[dict]:
    """Agentes vivos de TODAS las fuentes. Windows: procesos de Windows + panes de WSL. Unix: tmux."""
    found = []
    if _win is not None:
        for p in _win.sweep():
            p["backend"] = "win32"
            found.append(p)
    if HAS_TMUX:
        found.extend(_tmux_sweep())
    return found


def fuentes_activas() -> list[str]:
    """Las fuentes que el barrido mira en esta PC: `win32` (procesos de Windows) y `tmux` (panes, nativo o
    por WSL). La salud las informa para saber de entrada por que una sesion no aparece."""
    return (["win32"] if _win is not None else []) + (["tmux"] if HAS_TMUX else [])


def _tmux_alive(pid, distro: str | None = None) -> bool:
    """Vivo Y sigue siendo un agente (no un pid reciclado): se re-mira la linea de comando, en la
    distro de la tarjeta (o la default)."""
    if not pid or not _t.pid_alive(int(pid), distro):
        return False
    cl = _t.cmdline(int(pid), distro).lower()
    return "claude" in cl or "codex" in cl or _t.comm(int(pid), distro) in _AGENT_COMMS


def agent_alive(d: dict) -> bool:
    if is_tmux(d):
        return _tmux_alive(d.get("pid"), d.get("distro"))
    return _win.agent_alive(d.get("pid"))


def is_tui(d: dict) -> bool:
    if is_tmux(d):
        return _t.pid_alive(d.get("pid"), d.get("distro"))
    return _win.is_tui(d.get("pid"))


def cwd_of(d: dict) -> str | None:
    if is_tmux(d):
        return d.get("cwd") or _t.cwd_of(d.get("pid"))
    return _win.cwd_of(d.get("pid"))
