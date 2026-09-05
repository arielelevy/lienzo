"""Procesos: liveness por PID (ctypes) y barrido de respaldo de agentes en VS Code (CIM).

Regla de identificacion (DISENO.es.md §2.1): claude.exe / codex.exe cuyo padre es un shell
y cuyo abuelo es Code.exe. Se excluyen por ruta la app de escritorio de Claude
(WindowsApps\\Claude_...), el codex.exe de la extension de VS Code y el de la app de
escritorio de Codex (ambos `app-server`), y el claude.exe de la extension de VS Code
(\\.vscode\\extensions\\anthropic.claude-code-...\\native-binary\\).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_nt = ctypes.WinDLL("ntdll")
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
STILL_ACTIVE = 259
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k32.ReadProcessMemory.restype = wt.BOOL
_nt.NtQueryInformationProcess.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG)]


class _PBI(ctypes.Structure):
    _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


def cwd_of(pid: int) -> str | None:
    """Directorio actual de otro proceso (x64) leyendo PEB->ProcessParameters->CurrentDirectory.
    Sin psutil. Devuelve None si no se puede leer."""
    h = _k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
    if not h:
        return None
    try:
        pbi = _PBI()
        ret = wt.ULONG(0)
        if _nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret)) != 0:
            return None
        if not pbi.PebBaseAddress:
            return None

        def read(addr: int, n: int) -> bytes | None:
            buf = ctypes.create_string_buffer(n)
            got = ctypes.c_size_t(0)
            if not _k32.ReadProcessMemory(h, addr, buf, n, ctypes.byref(got)) or got.value != n:
                return None
            return buf.raw

        raw = read(pbi.PebBaseAddress + 0x20, 8)          # PEB64.ProcessParameters
        if not raw:
            return None
        params = int.from_bytes(raw, "little")
        raw = read(params + 0x38, 16)                      # CurrentDirectory.DosPath (UNICODE_STRING)
        if not raw:
            return None
        length = int.from_bytes(raw[0:2], "little")
        buffer = int.from_bytes(raw[8:16], "little")
        if not length or not buffer or length > 4096:
            return None
        raw = read(buffer, length)
        if not raw:
            return None
        return raw.decode("utf-16-le", errors="replace").rstrip("\\") or None
    finally:
        _k32.CloseHandle(h)

SHELLS = {"powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe", "wsl.exe", "nu.exe"}
AGENTS = {"claude.exe": "claude", "codex.exe": "codex"}


def agent_of(exe: str | None) -> str | None:
    """'claude' | 'codex' | None. Tolera el binario renombrado por el auto-update
    (claude.exe.old.<ts>), que sigue corriendo con ese nombre de imagen."""
    name = os.path.basename(exe or "").lower()
    for k, v in AGENTS.items():
        if name == k or name.startswith(k + "."):
            return v
    return None


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wt.DWORD(0)
        return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        _k32.CloseHandle(h)


def image_path(pid: int) -> str | None:
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        return buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
    finally:
        _k32.CloseHandle(h)


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
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine, CreationDate
$byId = @{}; foreach ($p in $all) { $byId[$p.ProcessId] = $p }
$out = @()
foreach ($a in ($all | Where-Object { $_.Name -in @('claude.exe','codex.exe') })) {
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
