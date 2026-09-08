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


def _agent_of(a: dict) -> str:
    """claude vs codex: el comm suele ser 'node', asi que se mira la linea de comando completa."""
    cl = (a.get("command", "") + " " + a.get("cmd", "")).lower()
    return "codex" if "codex" in cl else "claude"


def _tmux_sweep() -> list[dict]:
    """Panes con un agente, con la forma de procs.sweep() mas `cwd`, `target` (el pane) y backend."""
    out = []
    for a in _t.find_agent_panes(_AGENT_COMMS):
        out.append(
            {
                "pid": a["pid"],
                "agent": _agent_of(a),
                "exe": a.get("command") or a["cmd"],
                "created": None,
                "parent": "tmux",
                "grandparent": None,
                "in_vscode": False,
                "orphan": False,
                "cwd": a.get("cwd"),
                "target": a["target"],
                "backend": "tmux",
            }
        )
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


def _tmux_alive(pid) -> bool:
    """Vivo Y sigue siendo un agente (no un pid reciclado): se re-mira la linea de comando."""
    if not pid or not _t.pid_alive(int(pid)):
        return False
    cl = _t.cmdline(int(pid)).lower()
    return "claude" in cl or "codex" in cl or _t.comm(int(pid)) in _AGENT_COMMS


def agent_alive(d: dict) -> bool:
    if is_tmux(d):
        return _tmux_alive(d.get("pid"))
    return _win.agent_alive(d.get("pid"))


def is_tui(d: dict) -> bool:
    if is_tmux(d):
        return _t.pid_alive(d.get("pid"))
    return _win.is_tui(d.get("pid"))


def cwd_of(d: dict) -> str | None:
    if is_tmux(d):
        return d.get("cwd") or _t.cwd_of(d.get("pid"))
    return _win.cwd_of(d.get("pid"))
