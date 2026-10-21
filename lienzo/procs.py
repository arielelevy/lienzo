"""Procesos: liveness por PID (ctypes) y barrido de respaldo de agentes en VS Code (CIM).

Regla de identificacion (DISENO.es.md §2.1): claude.exe / codex.exe / pi.exe / coda.exe cuyo padre es un shell
y cuyo abuelo es Code.exe. Se excluyen por ruta la app de escritorio de Claude
(WindowsApps\\Claude_...), el codex.exe de la extension de VS Code y el de la app de
escritorio de Codex (ambos `app-server`), y el claude.exe de la extension de VS Code
(\\.vscode\\extensions\\anthropic.claude-code-...\\native-binary\\).
"""

from __future__ import annotations

import ctypes
import json
import os

try:
    from . import agentes, coda, kiro, procinfo, subproc
except ImportError:  # corriendo como script (python lienzo/hook.py) o con lienzo/ en sys.path
    import agentes
    import coda
    import kiro
    import procinfo
    import subproc

# re-export: el resto del codigo (server, send, screen, tests) sigue usando procs.alive, etc.
AGENTS, agent_of, alive, image_path, proc_info = (
    procinfo.AGENTS,
    procinfo.agent_of,
    procinfo.alive,
    procinfo.image_path,
    procinfo.proc_info,
)


def cwd_of(pid: int) -> str | None:
    """Directorio actual de otro proceso (x64) leyendo PEB->ProcessParameters->CurrentDirectory.
    Sin psutil. Devuelve None si no se puede leer."""
    h = procinfo.open_process(pid, procinfo.PROCESS_QUERY_INFORMATION | procinfo.PROCESS_VM_READ)
    if not h:
        return None
    try:
        pbi = procinfo.basic_info(h)
        if pbi is None or not pbi.PebBaseAddress:
            return None
        raw = procinfo.read_memory(h, pbi.PebBaseAddress + 0x20, 8)  # PEB64.ProcessParameters
        if not raw:
            return None
        params = int.from_bytes(raw, "little")
        raw = procinfo.read_memory(h, params + 0x38, 16)  # CurrentDirectory.DosPath (UNICODE_STRING)
        if not raw:
            return None
        length = int.from_bytes(raw[0:2], "little")
        buffer = int.from_bytes(raw[8:16], "little")
        if not length or not buffer or length > 4096:
            return None
        raw = procinfo.read_memory(h, buffer, length)
        if not raw:
            return None
        cwd = raw.decode("utf-16-le", errors="replace")
        return (cwd.rstrip("\\") if len(cwd) > 3 else cwd) or None  # "C:\" se queda como esta
    finally:
        procinfo.close_handle(h)


SHELLS = {"powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe", "wsl.exe", "nu.exe"}


def agent_alive(pid: int | None) -> bool:
    """Vivo Y sigue siendo un agente: un PID reciclado por otro programa no cuenta."""
    return alive(pid) and procinfo.process_agent(int(pid)) is not None


def is_impostor(exe: str | None, cmdline: str | None) -> bool:
    e = (exe or "").lower()
    c = (cmdline or "").lower()
    if "\\windowsapps\\claude_" in e:
        return True
    if "\\.vscode\\extensions\\" in e:
        return True
    if "app-server" in c:
        return True
    return "--type=" in c  # electron renderer/utility/gpu


def is_tui(pid: int) -> bool:
    """Algo a lo que tiene sentido inyectarle teclas: un agente que no es impostor ni una corrida
    externa (un orquestador, `claude -p`). Con un pid a mano solo se tiene la ruta del ejecutable, que es
    la que descarta la app de escritorio y las extensiones; el barrido, que si lee la linea de
    comando, llama a is_impostor directamente."""
    exe = image_path(pid)
    if not exe or not procinfo.process_agent(pid):
        return False
    return not is_impostor(exe, None) and external_origin(pid) is None


EXTERNAL_HOPS = 6  # claude.exe <- (cmd/bun) <- lanzador: alcanza con margen


def desktop_app(exe: str | None) -> str | None:
    """"claude-desktop" / "codex-desktop" si el ejecutable es de una app de escritorio. El motor de
    Claude Desktop no esta bajo WindowsApps: corre desde su carpeta de datos, que el hook ve con la ruta
    real del paquete (medido 2026-09-14: ...\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude\\
    claude-code\\2.1.260\\claude.exe) y otros con la virtualizada (%APPDATA%\\Claude\\claude-code\\...).
    La app de Claude y la de Codex (Electron) si estan bajo WindowsApps."""
    e = (exe or "").lower().replace("/", "\\")
    if "\\roaming\\claude\\claude-code\\" in e or "\\windowsapps\\claude_" in e:
        return "claude-desktop"
    if "\\windowsapps\\openai.codex_" in e or "\\packages\\openai.codex_" in e:
        return "codex-desktop"
    return None


def creation_filetime(pid: int | None) -> int | None:
    """Hora de creacion del proceso como FILETIME (100 ns desde 1601), la que Claude Code guarda como
    `procStart` en su registro de sesiones: distingue un pid reciclado. None fuera de Windows o sin acceso."""
    if not pid or not procinfo._WIN:
        return None
    h = procinfo.open_process(int(pid))
    if not h:
        return None
    try:
        tiempos = [ctypes.c_ulonglong() for _ in range(4)]  # creacion, salida, kernel, usuario
        ok = ctypes.windll.kernel32.GetProcessTimes(h, *(ctypes.byref(t) for t in tiempos))
        return tiempos[0].value if ok else None
    finally:
        procinfo.close_handle(h)


def desktop_por_registro(pid: int | None) -> dict | None:
    """La marca de Claude Desktop segun el registro de Claude Code (`~/.claude/sessions/<pid>.json`,
    medido 2026-10-17): `entrypoint: claude-desktop` es la señal exacta, y `name` es el nombre con que
    la sesion figura en el canal nativo. Solo si el registro es de ESTE proceso (procStart)."""
    reg = agentes.claude_registro(pid, creation_filetime(pid)) if pid else None
    if not reg or reg.get("entrypoint") != "claude-desktop":
        return None
    return {**_desktop("claude-desktop", "registro"), "canal": reg.get("name")}


def _desktop(kind: str, via: str) -> dict:
    """La marca de una sesion de app de escritorio: va en `external` porque se trata igual que una
    corrida externa (se ve, no se le teclea, ni se la mata, ni la mueven reglas)."""
    return {"kind": kind, "via": via, "desktop": True}


def _claude_cmd_batch(exe: str | None, cmdline: str | None) -> bool:
    name = os.path.basename(exe or "").lower()
    if not (name == "claude.exe" or name.startswith("claude.exe.")) or not cmdline:
        return False
    return procinfo.claude_batch(procinfo.command_args(cmdline)[1:])


def external_origin(pid: int | None) -> dict | None:
    """Si el agente `pid` es una ejecucion externa, de que tipo: `{"kind": <tipo>, "runner_pid": N,
    "via": "proceso"}` si un ancestro es un lanzador de EXTERNAL_RUNNERS, `{"kind": "batch", "via":
    "comando"}` si es un `claude -p` suelto; `{"kind": "claude-desktop" | "codex-desktop", "desktop": True}` si es
    el motor de una app de escritorio. None si es una sesion personal (o no se pudo leer: no se adivina). Una
    ejecucion externa se ve en el tablero, pero no se le teclea, ni se la mata, ni la mueven reglas."""
    if not pid:
        return None
    if reg := desktop_por_registro(int(pid)):
        return reg  # la señal exacta, con el nombre del canal nativo
    hop, exe0 = int(pid), image_path(int(pid))
    if kind := desktop_app(exe0):
        return _desktop(kind, "ruta")
    for _ in range(EXTERNAL_HOPS):
        parent, _exe = proc_info(hop)
        if not parent or parent == hop:
            break
        parent_exe = proc_info(parent)[1]
        if kind := desktop_app(parent_exe):
            return _desktop(kind, "proceso")  # un motor de la app fuera de su carpeta: lo delata el padre
        if tipo := procinfo.external_runner(parent_exe):
            return {"kind": tipo, "runner_pid": parent, "via": "proceso"}
        hop = parent
    if _claude_cmd_batch(exe0, procinfo.command_line(int(pid))):
        return {"kind": "batch", "via": "comando"}
    return None


def external_of_row(p: dict) -> dict | None:
    """Lo mismo que external_origin para una fila del barrido, con lo que el barrido ya leyo por CIM
    (padre, abuelo y linea de comando): sin abrir el proceso otra vez. Del padre y el abuelo el barrido
    solo trae el nombre. El registro de Claude se valida contra PID/FILETIME antes de las heurísticas."""
    if (
        p.get("pid")
        and agent_of(p.get("exe") or "", p.get("cmd")) == "claude"
        and (reg := desktop_por_registro(p["pid"]))
    ):
        return reg
    for k in ("exe", "parent_exe"):
        if kind := desktop_app(p.get(k)):
            return _desktop(kind, "ruta" if k == "exe" else "proceso")
    for k in ("parent", "grandparent"):
        if tipo := procinfo.external_runner(p.get(k)):
            return {"kind": tipo, "runner_pid": None, "via": "proceso"}
    if _claude_cmd_batch(p.get("exe"), p.get("cmd")):
        return {"kind": "batch", "via": "comando"}
    return None


_PS = r"""
$ErrorActionPreference='SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine, CreationDate
$byId = @{}; foreach ($p in $all) { $byId[$p.ProcessId] = $p }
$out = @()
foreach ($a in ($all | Where-Object { $_.Name -like 'claude.exe*' -or $_.Name -like 'codex.exe*' -or $_.Name -eq 'node.exe' -or $_.Name -eq 'pi.exe' -or $_.Name -eq 'coda.exe' -or $_.Name -eq 'kiro-cli.exe' -or $_.Name -like 'agy.exe*' })) {
  $par = $byId[$a.ParentProcessId]; $gp = if ($par) { $byId[$par.ParentProcessId] } else { $null }
  $out += [pscustomobject]@{
    pid = $a.ProcessId; exe = $a.ExecutablePath; cmd = $a.CommandLine
    created = if ($a.CreationDate) { $a.CreationDate.ToString('o') } else { $null }
    parent = if ($par) { $par.Name } else { $null }; parent_pid = $a.ParentProcessId; parent_exe = if ($par) { $par.ExecutablePath } else { $null }
    grandparent = if ($gp) { $gp.Name } else { $null }; grandparent_cmd = if ($gp) { $gp.CommandLine } else { $null }
    children = @($all | Where-Object { $_.ParentProcessId -eq $a.ProcessId -and $_.Name -in @('bash.exe', 'pwsh.exe', 'powershell.exe', 'cmd.exe') } | ForEach-Object { $_.ProcessId })
  }
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""


def pi_session_from_children(pid: int, children: list[int]) -> tuple[str, str] | None:
    """Identidad exacta publicada por Pi en sus shells; no buscar por cwd/mtime.

    Dos hijos con distintas sesiones pueden quedar vivos durante un cambio de sesion:
    no elegir ninguno en ese caso. La extension siempre tiene prioridad.
    """
    candidates = set()
    for child in children:
        env = procinfo.pi_session_environment(child, pid)
        sid, path = env.get("PI_SESSION_ID"), env.get("PI_SESSION_FILE")
        if not sid or not path or not os.path.isabs(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                header = json.loads(f.readline(65536))
        except OSError, ValueError:
            continue
        if isinstance(header, dict) and header.get("type") == "session" and header.get("id") == sid:
            candidates.add((sid, os.path.normcase(os.path.abspath(path))))
    return next(iter(candidates)) if len(candidates) == 1 else None


def sweep() -> list[dict]:
    """Barrido de respaldo: agentes interactivos vivos. Lento (~1 s), usar poco."""
    # subproc.correr: salida a archivo y el arbol muerto al vencer (revision 2026-10-04, 0.5). Un
    # powershell trabado ya no deja colgado el barrido ni le tira TimeoutExpired.
    rc, out, _err = subproc.correr(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], timeout=20)
    if rc in (subproc.VENCIDO, subproc.NO_ARRANCO):
        return []
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    found = []
    for p in rows:
        exe = p.get("exe") or ""
        agent = agent_of(exe, p.get("cmd"))
        if not agent or is_impostor(exe, p.get("cmd")):
            continue
        parent = (p.get("parent") or "").lower()
        gp = (p.get("grandparent") or "").lower()
        in_vscode = parent in SHELLS and gp == "code.exe"
        found.append(
            {
                "pid": p["pid"],
                "agent": agent,
                "exe": exe,
                "created": p.get("created"),
                "parent": p.get("parent"),
                "grandparent": p.get("grandparent"),
                "in_vscode": in_vscode,
                "orphan": p.get("parent") is None,
                # nació con acceso al Chrome real (Lanzar CLI con el tilde): la tarjeta lo marca
                "chrome": "--chrome" in procinfo.command_args(p.get("cmd") or "")[1:],
                # el registro de Claude Code (si es de este proceso) antes que la ruta y los padres
                "external": external_of_row(p),
                **(
                    {
                        agentes.perfil(agent).identity_key: agentes.perfil(agent).identity(
                            p, {"pi": pi_session_from_children, "coda": coda.identity, "kiro": kiro.identity}
                        )
                    }
                    if agentes.perfil(agent).identity_key
                    else {}
                ),
            }
        )
    return found


if __name__ == "__main__":
    for p in sweep():
        print(p)
