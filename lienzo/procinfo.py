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

AGENTS = {"claude.exe": "claude", "codex.exe": "codex"}


class _PBI(ctypes.Structure):
    """PROCESS_BASIC_INFORMATION."""
    _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


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


def agent_of(exe: str | None) -> str | None:
    """'claude' | 'codex' | None. Tolera el binario renombrado por el auto-update
    (claude.exe.old.<ts>), que sigue corriendo con ese nombre de imagen."""
    name = os.path.basename(exe or "").lower()
    for k, v in AGENTS.items():
        if name == k or name.startswith(k + "."):
            return v
    return None
