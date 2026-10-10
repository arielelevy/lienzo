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

import logging
import os
import subprocess
import sys
import threading
import time

try:
    from . import subproc
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import subproc

# En Windows, la fuente tmux corre DENTRO de WSL: los comandos se prefijan con `wsl.exe` (distro por
# defecto) para manejar el tmux de WSL desde el board de Windows. En Mac/Linux el prefijo es vacio
# (tmux nativo). Asi el mismo modulo sirve de "fuente tmux nativa" y de "fuente wsl-tmux".
_PREFIX: list[str] = ["wsl.exe"] if sys.platform == "win32" else []
_VIA_WSL = bool(_PREFIX)
VIA_WSL = _VIA_WSL


def _argv(distro: str | None = None) -> list[str]:
    """El prefijo de un comando, armado por pedido: [] nativo (Mac/Linux); ["wsl.exe"] via WSL con la
    distro por defecto; ["wsl.exe", "-d", distro] si se pide una distro. En nativo no hay wsl.exe, asi
    que una distro pedida se ignora (en Mac/Linux el codigo de distros queda inactivo)."""
    base = list(_PREFIX)
    if distro and base:
        return [*base, "-d", distro]
    return base


def ruta_wsl(path: str) -> str:
    r"""`C:\x\y` como la ve un agente de WSL (`/mnt/c/x/y`), sin llamar a wslpath: los adjuntos viven en
    el disco de Windows, que WSL monta en /mnt/<letra>. Una ruta que no es de unidad queda igual."""
    if len(path) > 2 and path[1] == ":" and path[0].isalpha() and path[2] in "\\/":
        return f"/mnt/{path[0].lower()}/" + path[3:].replace("\\", "/")
    return path


def _tmux(*args: str, stdin: str | None = None, distro: str | None = None) -> subprocess.CompletedProcess:
    """Un comando de tmux, en la distro pedida (o la default si no hay). Nunca levanta TimeoutExpired
    ni OSError (revision 2026-10-04, 0.5): va por subproc.correr, que mata el arbol al vencer y
    devuelve un codigo distinto de cero; antes un tmux colgado (o un wsl.exe trabado) le tiraba la
    excepcion a quien llamara, y `list_panes` o `send` no la atrapaban."""
    argv = [*_argv(distro), "tmux", *args]
    rc, out, err = subproc.correr(argv, entrada=stdin, timeout=15)
    return subprocess.CompletedProcess(argv, rc, out, err)


def available() -> bool:
    """Hay un tmux utilizable (binario presente y un server al que hablarle no hace falta todavia)."""
    try:
        return _tmux("-V").returncode == 0
    except OSError, subprocess.SubprocessError:
        return False


DISTROS_TTL_S = 60.0
# La salida de `wsl.exe -l -q` sin distros instaladas trae solo el placeholder, que no es una distro.
_PLACEHOLDER_DISTROS = "Windows Subsystem for Linux"
_distros_cache: dict | None = None  # {"ts": float, "vals": list[str]}, protegida por _distros_lock
_distros_lock = threading.Lock()


def distros() -> list[str]:
    """Las distros de WSL instaladas, parseando `wsl.exe -l -q` (directo, sin _PREFIX delante: con el
    prefijo seria `wsl.exe wsl.exe`). La salida es UTF-16: si el texto trae \\x00 se re-decodifica.
    Nunca levanta: ante binario ausente, error o lista vacia devuelve []. En Mac/Linux no hay WSL:
    devuelve [] sin llamar a wsl.exe. Caché en memoria con TTL (las distros instaladas no cambian con
    el server vivo), asi el barrido no corre `wsl.exe -l -q` por cada agente."""
    global _distros_cache
    if not _VIA_WSL:
        return []
    with _distros_lock:
        if _distros_cache is not None and time.monotonic() - _distros_cache["ts"] < DISTROS_TTL_S:
            return list(_distros_cache["vals"])
    rc, out, _err = subproc.correr(["wsl.exe", "-l", "-q"], timeout=15)
    vals: list[str] = []
    if rc == 0:
        text = out
        if "\x00" in text:
            text = out.encode("utf-8", "surrogateescape").decode("utf-16-le", "replace")
        vals = [line.strip() for line in text.splitlines() if line.strip() and line.strip() != _PLACEHOLDER_DISTROS]
    else:
        logging.getLogger(__name__).info("wsl.exe -l -q no contesto (rc %s): sin distros", rc)
    with _distros_lock:
        _distros_cache = {"ts": time.monotonic(), "vals": vals}
    return list(vals)


def en_distro(distro: str, programa: str) -> bool:
    """¿`programa` esta en el PATH de esa distro (shell de login, como lo veria una terminal)? Para
    lanzar adentro de WSL el binario de Linux, no el .exe de Windows. Nunca levanta."""
    if not _VIA_WSL or not programa.replace("-", "").replace("_", "").isalnum():
        return False
    rc, _out, _err = subproc.correr([*_argv(distro), "bash", "-lc", f"command -v {programa}"], timeout=15)
    return rc == 0


def invalidar_distros() -> None:
    """Fuerza el re-parseo de `wsl.exe -l -q` en la próxima consulta (ante una verdad vencida)."""
    global _distros_cache
    with _distros_lock:
        _distros_cache = None


# La home UNC se cachea por distro (dict {distro: home_unc}, con "" como clave de la default),
# protegida por lock: las distros instaladas no cambian con el server vivo, y una llamada a
# wsl.exe por transcripcion seria desperdicio. None cacheado = la distro no contesto.
_unc_home_cache: dict[str, str | None] = {}
_unc_home_lock = threading.Lock()


def wsl_unc_home(distro: str | None = None) -> str | None:
    """La home de la distro pedida (o la default) vista desde Windows por UNC:
    \\\\wsl.localhost\\\\<distro>\\\\home\\\\<user>. Con esto el server de Windows lee las
    transcripciones .jsonl de los agentes de WSL (que viven en la home de WSL). None si no se corre
    via wsl.exe, o si la distro no contesto. Caché por distro: la llamada sin argumento conserva el
    comportamiento de hoy (la home de la distro default)."""
    if not _VIA_WSL:
        return None
    clave = distro or ""
    with _unc_home_lock:
        if clave in _unc_home_cache:
            return _unc_home_cache[clave]
    try:
        r = subprocess.run(
            [*_argv(distro), "bash", "-lc", 'printf "%s\\n%s" "$WSL_DISTRO_NAME" "$HOME"'],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        home = None
    else:
        lines = r.stdout.splitlines()
        if r.returncode != 0 or len(lines) < 2 or not lines[0].strip() or not lines[1].startswith("/"):
            home = None
        else:
            home = rf"\\wsl.localhost\{lines[0].strip()}" + lines[1].strip().replace("/", "\\")
    with _unc_home_lock:
        _unc_home_cache[clave] = home
    return home


def list_panes(distro: str | None = None) -> list[dict]:
    """Todos los panes de todos los clientes de la distro pedida (o la default): (target=pane_id,
    pane_pid, cmd, cwd del pane)."""
    fmt = "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}"
    r = _tmux("list-panes", "-a", "-F", fmt, distro=distro)
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


def list_panes_todas() -> list[dict]:
    """Todos los panes de TODAS las distros de WSL descubiertas: una llamada por distro y los
    resultados unidos, asi el barrido ve los agentes de todas (no solo los de la default). Con 0 o
    1 distro es el camino de hoy: `list_panes()` directo, en serie, sin `-d`. Con mas de una, un
    hilo por distro (misma forma que `fan_out` de server.py). Una distro que no corre o falla
    devuelve [] (rc != 0 por subproc.correr, que nunca levanta) y no corta a las demas."""
    ds = distros()
    if len(ds) <= 1:
        return list_panes()
    out: list[dict] = []

    def una(distro: str) -> None:
        try:
            out.extend(list_panes(distro))
        except Exception:  # una distro rota es un bug, que no corte a las demas
            logging.getLogger(__name__).info("list_panes de %s fallo; distro salteada", distro)

    hilos = [threading.Thread(target=una, args=(d,), daemon=True) for d in ds]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return out


def _ps_all(distro: str | None = None) -> dict[int, tuple[int, str, str]]:
    """Foto de los procesos de la distro pedida (o la default): pid -> (ppid, comm, command). `ps -axo`
    con cabeceras vacias es la sintaxis que comparten Linux y macOS (BSD): una sola llamada, sin
    /proc, asi el descubrimiento corre igual en los dos. En Windows no se llama (el backend es win32)."""
    try:
        r = subprocess.run(
            [*_argv(distro), "ps", "-axo", "pid=,ppid=,comm=,command="],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return {}
    snap: dict[int, tuple[int, str, str]] = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            command = parts[3] if len(parts) > 3 else parts[2]
            snap[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2]), command)
    return snap


def _descendants(
    root: int, snap: dict[int, tuple[int, str, str]] | None = None, distro: str | None = None
) -> list[int]:
    """Todos los pids bajo `root` (incluido). El agente suele ser hijo del shell del pane."""
    snap = _ps_all(distro) if snap is None else snap
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


def pid_alive(pid: int | None, distro: str | None = None) -> bool:
    """El proceso existe en la distro pedida (o la default). Nativo (Mac/Linux): `os.kill(pid, 0)`,
    barato. Via WSL desde Windows: os.kill miraria un pid de Windows, no el de WSL, asi que se
    chequea contra la foto de `ps`."""
    if not pid:
        return False
    if _VIA_WSL:
        return int(pid) in _ps_all(distro)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, aunque no sea nuestro
    except OSError, ValueError:
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


def cmdline(pid: int | None, distro: str | None = None) -> str:
    """La linea de comando completa (para distinguir claude de codex cuando ambos corren sobre node)."""
    return _ps_all(distro).get(int(pid), (0, "", ""))[2] if pid else ""


def comm(pid: int | None, distro: str | None = None) -> str:
    return _ps_all(distro).get(int(pid), (0, "", ""))[1] if pid else ""


def pane_pid(target: str, distro: str | None = None) -> int | None:
    """El pane_pid actual de `target`, o None si el pane ya no existe. Sale de list_panes (que ya
    trae pane_pid por pane): mas robusto que `display-message #{pane_pid}`, que via wsl.exe volvia
    vacio."""
    if not target:
        return None
    for p in list_panes(distro):
        if p["target"] == target:
            return p["pane_pid"]
    return None


def target_valid(target: str, pid: int | None, distro: str | None = None) -> bool:
    """El agente `pid` corre AHORA dentro del pane `target`, consultado en la distro pedida (o la
    default). Defensa contra el pane_id reciclado (hallazgo del plan): si tmux reinicio, `%0` puede
    apuntar a otro pane —otro repo, otra persona— y escribir ahi seria teclear en la terminal
    equivocada. ~15 ms, se paga por envio."""
    if not target or not pid:
        return False
    pp = pane_pid(target, distro)
    if pp is None:
        return False
    return int(pid) == pp or int(pid) in _descendants(pp, distro=distro)


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


def _wsl_run(*args: str, distro: str | None = None) -> subprocess.CompletedProcess | None:
    """Un comando cualquiera dentro de WSL (readlink, etc.), con el prefijo wsl.exe y la distro pedida."""
    argv = [*_argv(distro), *args]
    rc, out, err = subproc.correr(argv, timeout=15)
    return None if rc == subproc.NO_ARRANCO else subprocess.CompletedProcess(argv, rc, out, err)


def proc_cwd(pid: int | None, distro: str | None = None) -> str:
    """cwd de un proceso cualquiera (este o no en un pane), en la distro pedida (o la default).
    Portable: readlink /proc en Linux/WSL, lsof en Mac. Para los agentes sueltos, que no tienen pane
    del que sacar el cwd."""
    if not pid:
        return ""
    if _VIA_WSL:
        r = _wsl_run("readlink", f"/proc/{int(pid)}/cwd", distro=distro)
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
    except OSError, subprocess.SubprocessError, StopIteration:
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


def all_agents(distro: str | None = None) -> list[dict]:
    """TODOS los agentes claude/codex de la maquina (Mac/Linux) o de la distro de WSL pedida (o la
    default), esten o no en tmux. Los que corren en un pane traen `target` (se les puede escribir);
    los sueltos, target None (solo lectura, como las apps de escritorio en Windows). Una sola foto de
    `ps` mas los panes."""
    snap = _ps_all(distro)
    pid_pane: dict[int, tuple[str, str]] = {}
    for p in list_panes(distro):
        if p["pane_pid"] is not None:
            for q in _descendants(p["pane_pid"], snap, distro):
                pid_pane[q] = (p["target"], p["cwd"])
    out = []
    for pid, (_ppid, comm, cmd) in snap.items():
        if not _is_agent(comm, cmd):
            continue
        pane = pid_pane.get(pid)
        target, cwd = (pane[0], pane[1]) if pane else (None, proc_cwd(pid, distro))
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


# las teclas sueltas que acepta send.py, con su nombre en tmux
_KEYS = {"escape": "Escape", "up": "Up", "down": "Down", "enter": "Enter"}


def send(target: str, text: str, enter: bool = True, key: str | None = None, distro: str | None = None) -> dict:
    """Teclea `text` literal en el pane y, salvo enter=False, un Enter aparte. Con `key` (las de
    send.py: escape, up, down, enter) va esa tecla sola, sin texto ni Enter. El filtrado de caracteres de control
    (hallazgo A4) ya vino hecho en compose_send, que es agnostico del backend."""
    if key:
        if key not in _KEYS:
            return {"ok": False, "target": target, "error": f"tecla desconocida: {key!r}"}
        r = _tmux("send-keys", "-t", target, _KEYS[key], distro=distro)
        if r.returncode != 0:
            return {"ok": False, "target": target, "error": r.stderr.strip() or "send-keys fallo"}
        return {"ok": True, "target": target, "key": key}
    r = _tmux("send-keys", "-t", target, "-l", "--", text, distro=distro) if text else None
    if r is not None and r.returncode != 0:
        return {"ok": False, "target": target, "error": r.stderr.strip() or "send-keys fallo"}
    if enter:
        r2 = _tmux("send-keys", "-t", target, "Enter", distro=distro)
        if r2.returncode != 0:
            return {"ok": False, "target": target, "error": r2.stderr.strip() or "Enter fallo"}
    return {"ok": True, "target": target, "chars": len(text), "enter": 1 if enter else 0}


def screen(target: str, scrollback: int = 0, distro: str | None = None) -> dict:
    """El texto visible del pane, y `scrollback` lineas hacia atras si es > 0."""
    args = ["capture-pane", "-p", "-t", target]
    if scrollback > 0:
        args += ["-S", f"-{scrollback}"]
    r = _tmux(*args, distro=distro)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip() or "capture-pane fallo"}
    return {"ok": True, "text": r.stdout}
