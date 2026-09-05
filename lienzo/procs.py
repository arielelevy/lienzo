"""Procesos: liveness por PID (ctypes) y barrido de respaldo de agentes en VS Code (CIM).

Regla de identificacion (DISENO.es.md §2.1): claude.exe / codex.exe cuyo padre es un shell
y cuyo abuelo es Code.exe. Se excluyen por ruta la app de escritorio de Claude
(WindowsApps\\Claude_...), el codex.exe de la extension de VS Code y el de la app de
escritorio de Codex (ambos `app-server`), y el claude.exe de la extension de VS Code
(\\.vscode\\extensions\\anthropic.claude-code-...\\native-binary\\).
"""
from __future__ import annotations

import json
import os
import subprocess

try:
    from . import procinfo
except ImportError:  # corriendo como script (python lienzo/hook.py) o con lienzo/ en sys.path
    import procinfo

# re-export: el resto del codigo (server, send, screen, tests) sigue usando procs.alive, etc.
AGENTS, agent_of, alive, image_path, proc_info = (procinfo.AGENTS, procinfo.agent_of, procinfo.alive,
                                                  procinfo.image_path, procinfo.proc_info)


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
        raw = procinfo.read_memory(h, pbi.PebBaseAddress + 0x20, 8)          # PEB64.ProcessParameters
        if not raw:
            return None
        params = int.from_bytes(raw, "little")
        raw = procinfo.read_memory(h, params + 0x38, 16)                      # CurrentDirectory.DosPath (UNICODE_STRING)
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
    return alive(pid) and agent_of(image_path(int(pid))) is not None


def is_impostor(exe: str | None, cmdline: str | None) -> bool:
    e = (exe or "").lower()
    c = (cmdline or "").lower()
    if "\\windowsapps\\claude_" in e:
        return True
    if "\\.vscode\\extensions\\" in e:
        return True
    if "app-server" in c:
        return True
    if "--type=" in c:  # electron renderer/utility/gpu
        return True
    return False


def is_tui(pid: int, cmdline: str | None = None) -> bool:
    """Algo a lo que tiene sentido inyectarle teclas: un agente que no es impostor."""
    exe = image_path(pid)
    if not exe or not agent_of(exe):
        return False
    return not is_impostor(exe, cmdline)


_PS = r"""
$ErrorActionPreference='SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine, CreationDate
$byId = @{}; foreach ($p in $all) { $byId[$p.ProcessId] = $p }
$out = @()
foreach ($a in ($all | Where-Object { $_.Name -like 'claude.exe*' -or $_.Name -like 'codex.exe*' })) {
  $par = $byId[$a.ParentProcessId]; $gp = if ($par) { $byId[$par.ParentProcessId] } else { $null }
  $out += [pscustomobject]@{
    pid = $a.ProcessId; exe = $a.ExecutablePath; cmd = $a.CommandLine
    created = if ($a.CreationDate) { $a.CreationDate.ToString('o') } else { $null }
    parent = if ($par) { $par.Name } else { $null }; parent_pid = $a.ParentProcessId
    grandparent = if ($gp) { $gp.Name } else { $null }; grandparent_cmd = if ($gp) { $gp.CommandLine } else { $null }
  }
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""


def sweep() -> list[dict]:
    """Barrido de respaldo: agentes interactivos vivos. Lento (~1 s), usar poco."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                           capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
        rows = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    if isinstance(rows, dict):
        rows = [rows]
    found = []
    for p in rows:
        exe = p.get("exe") or ""
        agent = agent_of(exe)
        if not agent or is_impostor(exe, p.get("cmd")):
            continue
        parent = (p.get("parent") or "").lower()
        gp = (p.get("grandparent") or "").lower()
        in_vscode = parent in SHELLS and gp == "code.exe"
        found.append({
            "pid": p["pid"], "agent": agent, "exe": exe, "created": p.get("created"),
            "parent": p.get("parent"), "grandparent": p.get("grandparent"),
            "in_vscode": in_vscode, "orphan": p.get("parent") is None,
        })
    return found


if __name__ == "__main__":
    for p in sweep():
        print(p)
