"""Backend tmux para Mac / Linux / WSL: escribir en la consola de otro proceso y leer su pantalla
sin nada de Win32. Un pane de tmux se maneja con `send-keys` y `capture-pane`, y el direccionamiento
pasa de PID a pane_id (%0, %1, ...). La condicion es que los agentes arranquen adentro de tmux.

Es el equivalente de send.py + screen.py + la parte de descubrimiento de procs.py, pero por tmux:
  send      -> tmux send-keys -t <pane> -l -- <texto> ; luego Enter
  screen    -> tmux capture-pane -p -t <pane> [-S -N]   (incluye scrollback, que Windows no tiene)
  discover  -> tmux list-panes -a  +  una foto de `ps` para ubicar el agente en el arbol del pane

Solo stdlib, y **portable Mac + Linux**: la inspeccion de procesos va por `ps -axo` (sintaxis BSD que
los dos aceptan) y `os.kill(pid, 0)`, no por /proc (que no existe en macOS). El cwd sale del pane
(pane_current_path). En Windows este modulo se importa pero no se usa: el server elige el backend por
plataforma."""

from __future__ import annotations

import functools
import os
import subprocess
import sys

# En Windows, la fuente tmux corre DENTRO de WSL: los comandos se prefijan con `wsl.exe` (distro por
# defecto) para manejar el tmux de WSL desde el board de Windows. En Mac/Linux el prefijo es vacio
# (tmux nativo). Asi el mismo modulo sirve de "fuente tmux nativa" y de "fuente wsl-tmux".
_PREFIX: list[str] = ["wsl.exe"] if sys.platform == "win32" else []
_VIA_WSL = bool(_PREFIX)


def _tmux(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*_PREFIX, "tmux", *args],
        capture_output=True,
        text=True,
        input=stdin,
        timeout=15,
        encoding="utf-8",
        errors="replace",
    )


def available() -> bool:
    """Hay un tmux utilizable (binario presente y un server al que hablarle no hace falta todavia)."""
    try:
        return _tmux("-V").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@functools.lru_cache(maxsize=1)
def wsl_unc_home() -> str | None:
    """La home de WSL vista desde Windows por UNC: \\wsl.localhost\\<distro>\\home\\<user>. Con esto el
    server de Windows lee las transcripciones .jsonl de los agentes de WSL (que viven en la home de
    WSL). None si no se corre via wsl.exe, o si no se pudo averiguar."""
    if not _VIA_WSL:
        return None
    try:
        r = subprocess.run(
            [*_PREFIX, "bash", "-lc", 'printf "%s\\n%s" "$WSL_DISTRO_NAME" "$HOME"'],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) < 2 or not lines[0].strip() or not lines[1].startswith("/"):
        return None
    return rf"\\wsl.localhost\{lines[0].strip()}" + lines[1].strip().replace("/", "\\")


def list_panes() -> list[dict]:
    """Todos los panes de todos los clientes: (target=pane_id, pane_pid, cmd, cwd del pane)."""
    fmt = "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}"
    r = _tmux("list-panes", "-a", "-F", fmt)
    out: list[dict] = []
    if r.returncode != 0:
        return out
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            out.append(
                {
                    "target": parts[0],
                    "pane_pid": int(parts[1]) if parts[1].isdigit() else None,
                    "cmd": parts[2],
                    "cwd": parts[3],
                }
            )
    return out


def _ps_all() -> dict[int, tuple[int, str, str]]:
    """Foto de los procesos: pid -> (ppid, comm, command). `ps -axo` con cabeceras vacias es la
    sintaxis que comparten Linux y macOS (BSD): una sola llamada, sin /proc, asi el descubrimiento
    corre igual en los dos. En Windows no se llama (el backend es win32)."""
    try:
        r = subprocess.run(
            [*_PREFIX, "ps", "-axo", "pid=,ppid=,comm=,command="],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    snap: dict[int, tuple[int, str, str]] = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            command = parts[3] if len(parts) > 3 else parts[2]
            snap[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2]), command)
    return snap


def _descendants(root: int, snap: dict[int, tuple[int, str, str]] | None = None) -> list[int]:
    """Todos los pids bajo `root` (incluido). El agente suele ser hijo del shell del pane."""
    snap = _ps_all() if snap is None else snap
    children: dict[int, list[int]] = {}
    for pid, (ppid, _c, _cmd) in snap.items():
        children.setdefault(ppid, []).append(pid)
    seen, stack = [root], [root]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in seen:
                seen.append(c)
                stack.append(c)
    return seen


def pid_alive(pid: int | None) -> bool:
    """El proceso existe. Nativo (Mac/Linux): `os.kill(pid, 0)`, barato. Via WSL desde Windows:
    os.kill miraria un pid de Windows, no el de WSL, asi que se chequea contra la foto de `ps`."""
    if not pid:
        return False
    if _VIA_WSL:
        return int(pid) in _ps_all()
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, aunque no sea nuestro
    except (OSError, ValueError):
        return False


def cwd_of(pid: int | None) -> str:
    """El cwd de un proceso, via el pane que lo contiene (pane_current_path). Portable: a nivel
    proceso no hay una via barata en los dos SO (/proc es solo Linux, lsof es caro en Mac), y para
    lo que se usa alcanza el del pane."""
    if not pid:
        return ""
    snap = _ps_all()
    for p in list_panes():
        if p["pane_pid"] is not None and int(pid) in _descendants(p["pane_pid"], snap):
            return p["cwd"]
    return ""


def cmdline(pid: int | None) -> str:
    """La linea de comando completa (para distinguir claude de codex cuando ambos corren sobre node)."""
    return _ps_all().get(int(pid), (0, "", ""))[2] if pid else ""


def comm(pid: int | None) -> str:
    return _ps_all().get(int(pid), (0, "", ""))[1] if pid else ""


def pane_pid(target: str) -> int | None:
    """El pane_pid actual de `target`, o None si el pane ya no existe. Sale de list_panes (que ya
    trae pane_pid por pane): mas robusto que `display-message #{pane_pid}`, que via wsl.exe volvia
    vacio."""
    if not target:
        return None
    for p in list_panes():
        if p["target"] == target:
            return p["pane_pid"]
    return None


def target_valid(target: str, pid: int | None) -> bool:
    """El agente `pid` corre AHORA dentro del pane `target`. Defensa contra el pane_id reciclado
    (hallazgo del plan): si tmux reinicio, `%0` puede apuntar a otro pane —otro repo, otra
    persona— y escribir ahi seria teclear en la terminal equivocada. ~15 ms, se paga por envio."""
    if not target or not pid:
        return False
    pp = pane_pid(target)
    if pp is None:
        return False
    return int(pid) == pp or int(pid) in _descendants(pp)


def find_agent_panes(names: set[str]) -> list[dict]:
    """Panes cuyo arbol de procesos tiene un agente (comm que empieza con alguno de `names`, p.ej.
    claude / codex / node). Devuelve (target, pid del agente, cwd = el del pane, comm, command). Una
    sola foto de `ps`, sin /proc; el cwd es pane_current_path, que sirve en Mac y Linux."""
    snap = _ps_all()
    res: list[dict] = []
    for p in list_panes():
        if p["pane_pid"] is None:
            continue
        for q in _descendants(p["pane_pid"], snap):
            info = snap.get(q)
            if not info:
                continue
            c = info[1]
            if c and any(c == n or c.startswith(n) for n in names):
                res.append({"target": p["target"], "pid": q, "cwd": p["cwd"], "cmd": c, "command": info[2]})
                break
    return res


def _wsl_run(*args: str) -> subprocess.CompletedProcess | None:
    """Un comando cualquiera dentro de WSL (readlink, etc.), con el prefijo wsl.exe."""
    try:
        return subprocess.run(
            [*_PREFIX, *args], capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError):
        return None


def proc_cwd(pid: int | None) -> str:
    """cwd de un proceso cualquiera (este o no en un pane). Portable: readlink /proc en Linux/WSL,
    lsof en Mac. Para los agentes sueltos, que no tienen pane del que sacar el cwd."""
    if not pid:
        return ""
    if _VIA_WSL:
        r = _wsl_run("readlink", f"/proc/{int(pid)}/cwd")
        return r.stdout.strip() if r and r.returncode == 0 else ""
    try:
        return os.readlink(f"/proc/{int(pid)}/cwd")  # Linux nativo
    except OSError:
        pass
    try:  # macOS: no hay /proc, se pregunta con lsof
        r = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fn", "-p", str(int(pid))], capture_output=True, text=True, timeout=10
        )
        return next((ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n")), "")
    except (OSError, subprocess.SubprocessError, StopIteration):
        return ""


def _is_agent(comm: str, cmd: str) -> bool:
    """El proceso es un agente (claude/codex nativo, o el CLI corriendo sobre node). No cuenta un
    `node` cualquiera —los MCP servers son node— salvo que la linea de comando sea la del CLI."""
    if comm in ("claude", "codex"):
        return True
    if comm == "node":
        low = cmd.lower()
        return "claude-code" in low or "codex" in low or "claude/cli" in low
    return False


def all_agents() -> list[dict]:
    """TODOS los agentes claude/codex de la maquina (Mac/Linux) o de WSL, esten o no en tmux. Los que
    corren en un pane traen `target` (se les puede escribir); los sueltos, target None (solo lectura,
    como las apps de escritorio en Windows). Una sola foto de `ps` mas los panes."""
    snap = _ps_all()
    pid_pane: dict[int, tuple[str, str]] = {}
    for p in list_panes():
        if p["pane_pid"] is not None:
            for q in _descendants(p["pane_pid"], snap):
                pid_pane[q] = (p["target"], p["cwd"])
    out = []
    for pid, (_ppid, comm, cmd) in snap.items():
        if not _is_agent(comm, cmd):
            continue
        pane = pid_pane.get(pid)
        target, cwd = (pane[0], pane[1]) if pane else (None, proc_cwd(pid))
        out.append(
            {
                "pid": pid,
                "agent": "codex" if "codex" in (comm + " " + cmd).lower() else "claude",
                "comm": comm,
                "command": cmd,
                "cwd": cwd,
                "target": target,
            }
        )
    return out


def send(target: str, text: str, enter: bool = True) -> dict:
    """Teclea `text` literal en el pane y, salvo enter=False, un Enter aparte. El filtrado de
    caracteres de control (hallazgo A4) ya vino hecho en compose_send, que es agnostico del backend."""
    r = _tmux("send-keys", "-t", target, "-l", "--", text)
    if r.returncode != 0:
        return {"ok": False, "target": target, "error": r.stderr.strip() or "send-keys fallo"}
    if enter:
        r2 = _tmux("send-keys", "-t", target, "Enter")
        if r2.returncode != 0:
            return {"ok": False, "target": target, "error": r2.stderr.strip() or "Enter fallo"}
    return {"ok": True, "target": target, "chars": len(text), "enter": 1 if enter else 0}


def screen(target: str, scrollback: int = 0) -> dict:
    """El texto visible del pane, y `scrollback` lineas hacia atras si es > 0."""
    args = ["capture-pane", "-p", "-t", target]
    if scrollback > 0:
        args += ["-S", f"-{scrollback}"]
    r = _tmux(*args)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip() or "capture-pane fallo"}
    return {"ok": True, "text": r.stdout}
