"""Consultas minimas de procesos Windows con ctypes: padre, ruta del ejecutable, liveness.

Lo comparten hook.py (que corre en cada evento y tiene que arrancar rapido) y procs.py.
Por eso aca no hay subprocess, json ni nada pesado: solo ctypes y os.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_nt = ctypes.WinDLL("ntdll")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
STILL_ACTIVE = 259

_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k32.ReadProcessMemory.restype = wt.BOOL
_nt.NtQueryInformationProcess.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG)]

AGENTS = {"claude.exe": "claude", "codex.exe": "codex", "pi.exe": "pi"}

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.CommandLineToArgvW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(wt.LPWSTR)
_k32.LocalFree.argtypes = [wt.HLOCAL]


def command_args(command: str) -> list[str]:
    """Argumentos Windows, sin confundir rutas con espacios ni texto del prompt."""
    count = ctypes.c_int()
    argv = _shell32.CommandLineToArgvW(command, ctypes.byref(count)) if command else None
    if not argv:
        return []
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        _k32.LocalFree(argv)


def pi_interactive(args: list[str]) -> bool:
    """Excluye print, RPC, JSON y comandos administrativos; -- termina las opciones."""
    options = args[: args.index("--")] if "--" in args else args
    if args and args[0] in ("install", "remove", "uninstall", "update", "list", "config"):
        return False
    return not any(
        a in ("-p", "--print", "--mode", "--export", "--help", "-h", "--version", "-v", "--list-models")
        or a.startswith(("--mode=", "--export=", "--list-models="))
        for a in options
    )


class _PBI(ctypes.Structure):
    """PROCESS_BASIC_INFORMATION."""

    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
    ]


def open_process(pid: int | None, access: int = PROCESS_QUERY_LIMITED_INFORMATION):
    """HANDLE o None. El que abre cierra con close_handle."""
    if not pid:
        return None
    return _k32.OpenProcess(access, False, int(pid)) or None


def close_handle(h) -> None:
    _k32.CloseHandle(h)


def basic_info(h) -> _PBI | None:
    """NtQueryInformationProcess(ProcessBasicInformation) sobre un handle abierto."""
    pbi = _PBI()
    ret = wt.ULONG(0)
    if _nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret)) != 0:
        return None
    return pbi


def image_of(h) -> str | None:
    """Ruta completa del ejecutable de un handle abierto."""
    size = wt.DWORD(1024)
    buf = ctypes.create_unicode_buffer(size.value)
    return buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None


def read_memory(h, addr: int, n: int) -> bytes | None:
    """n bytes de la memoria del proceso, o None si no se pudo leer todo."""
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t(0)
    if not _k32.ReadProcessMemory(h, addr, buf, n, ctypes.byref(got)) or got.value != n:
        return None
    return buf.raw


def proc_info(pid: int | None) -> tuple[int | None, str | None]:
    """(parent_pid, ruta_del_ejecutable) o (None, None)."""
    h = open_process(pid)
    if not h:
        return None, None
    try:
        pbi = basic_info(h)
        parent = int(pbi.InheritedFromUniqueProcessId or 0) if pbi is not None else None
        return parent, image_of(h)
    finally:
        close_handle(h)


def image_path(pid: int | None) -> str | None:
    h = open_process(pid)
    if not h:
        return None
    try:
        return image_of(h)
    finally:
        close_handle(h)


def alive(pid: int | None) -> bool:
    """El PID existe y no termino. No distingue un PID reciclado: ver agent_alive en procs."""
    h = open_process(pid)
    if not h:
        return False
    try:
        code = wt.DWORD(0)
        return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        close_handle(h)


def command_line(pid: int) -> str | None:
    """CommandLine del PEB x64. Sin CIM por cada chequeo de liveness."""
    h = open_process(pid, PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)
    if not h:
        return None
    try:
        pbi = basic_info(h)
        raw = read_memory(h, pbi.PebBaseAddress + 0x20, 8) if pbi and pbi.PebBaseAddress else None
        params = int.from_bytes(raw, "little") if raw else 0
        raw = read_memory(h, params + 0x70, 16) if params else None
        if not raw:
            return None
        length, addr = int.from_bytes(raw[:2], "little"), int.from_bytes(raw[8:], "little")
        data = read_memory(h, addr, length) if addr and 0 < length <= 65534 else None
        return data.decode("utf-16-le", errors="replace") if data else None
    finally:
        close_handle(h)


def pi_session_environment(pid: int, parent_pid: int) -> dict[str, str]:
    """Solo PI_SESSION_ID/FILE de un hijo directo; nunca devuelve credenciales del entorno.

    Pi inyecta estas variables al lanzar sus herramientas de shell. No leer el entorno del
    propio agente: podria haber heredado la identidad de otro Pi que lo lanzo.
    """
    h = open_process(pid, PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)
    if not h:
        return {}
    try:
        pbi = basic_info(h)
        if not pbi or not pbi.PebBaseAddress or pbi.InheritedFromUniqueProcessId != parent_pid:
            return {}
        raw = read_memory(h, pbi.PebBaseAddress + 0x20, 8)
        params = int.from_bytes(raw, "little") if raw else 0
        raw = read_memory(h, params + 0x80, 8) if params else None  # PEB64.Environment
        address = int.from_bytes(raw, "little") if raw else 0
        if not address:
            return {}
        data = b""
        while len(data) < 256 * 1024:
            start = address + len(data)
            block = read_memory(h, start, min(4096 - start % 4096, 256 * 1024 - len(data)))
            if not block:
                return {}
            data += block
            text = data[: len(data) // 2 * 2].decode("utf-16-le", errors="replace")
            if "\0\0" not in text:
                continue
            values = {}
            for entry in text.split("\0\0", 1)[0].split("\0"):
                key, sep, value = entry.partition("=")
                if sep and key in ("PI_SESSION_ID", "PI_SESSION_FILE"):
                    values[key] = value
            return values
        return {}
    finally:
        close_handle(h)


def agent_of(exe: str | None, cmdline: str | None = None) -> str | None:
    """Claude / Codex / Pi. Node solo cuenta si ejecuta la CLI interactiva de Pi.
    Tolera el binario renombrado por el auto-update
    (claude.exe.old.<ts>), que sigue corriendo con ese nombre de imagen."""
    name = os.path.basename(exe or "").lower()
    if name == "node.exe":
        args = command_args(cmdline or "")
        entry = args[1].replace("\\", "/").lower() if len(args) > 1 else ""
        if any(
            entry.endswith(f"/{scope}/pi-coding-agent/dist/{script}")
            for scope in ("@earendil-works", "@mariozechner")
            for script in ("cli.js", "bundle/cli.js")
        ):
            return "pi" if pi_interactive(args[2:]) else None
        return None
    for k, v in AGENTS.items():
        if name == k or name.startswith(k + "."):
            if v == "pi" and cmdline and not pi_interactive(command_args(cmdline)[1:]):
                return None
            return v
    return None


def process_agent(pid: int) -> str | None:
    exe = image_path(pid)
    cmdline = command_line(pid) if os.path.basename(exe or "").lower() in ("node.exe", "pi.exe") else None
    return agent_of(exe, cmdline)
