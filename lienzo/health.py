"""Salud de la PC: memoria, CPU y temperatura de Windows, sin dependencias nuevas.

Memoria por GlobalMemoryStatusEx; CPU por dos muestras de GetSystemTimes (la primera llamada no
tiene con que comparar y da None: el modulo guarda la muestra anterior); temperatura por WMI
(\\_TZ.THRM, deciKelvin) via un powershell corto, cara y por eso cacheada 30 s. `snapshot()` nunca
levanta: un fallo de cualquier pieza deja ese campo en None y no interrumpe a las demas.

No se conecta a server.py todavia (eso es la ronda 2, GET /peer/health).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import datetime as dt
import subprocess
import time

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GB = 1024**3
TEMP_TTL_S = 30


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD),
        ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


_k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
_k32.GlobalMemoryStatusEx.restype = wt.BOOL
_k32.GetSystemTimes.argtypes = [ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME), ctypes.POINTER(wt.FILETIME)]
_k32.GetSystemTimes.restype = wt.BOOL


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def _memoria() -> tuple[float | None, float | None]:
    """(libre, total) en GB, o (None, None) si GlobalMemoryStatusEx falla."""
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    if not _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None, None
    return m.ullAvailPhys / GB, m.ullTotalPhys / GB


def _filetime_to_int(ft: wt.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


# Muestra anterior de GetSystemTimes (ocioso, kernel, usuario), para el delta entre dos llamadas.
# Vive a nivel de modulo: es la unica forma de medir CPU sin una libreria como psutil.
_ultima_muestra: tuple[int, int, int] | None = None


def _cpu_pct() -> float | None:
    """% de CPU usado desde la ultima llamada. La primera no tiene con que comparar: None."""
    global _ultima_muestra
    idle, kernel, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    ahora = (_filetime_to_int(idle), _filetime_to_int(kernel), _filetime_to_int(user))
    anterior = _ultima_muestra
    _ultima_muestra = ahora
    if anterior is None:
        return None
    idle_d = ahora[0] - anterior[0]
    # kernel incluye el tiempo ocioso; el total ocupado es (kernel + user) - idle
    total_d = (ahora[1] - anterior[1]) + (ahora[2] - anterior[2])
    if total_d <= 0:
        return None
    return max(0.0, min(100.0, round(100 * (1 - idle_d / total_d), 1)))


# El sensor bueno es \_TZ.THRM (\_TZ.TZ01 da 20 °C fijo, medido el 2026-09-26 en el skill lienzo).
_TEMP_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation |
  Where-Object { $_.Name -eq '\_TZ.THRM' } |
  Select-Object -First 1 -ExpandProperty HighPrecisionTemperature
"""

# (valor o None, momento de la medicion en time.monotonic()); cara (~1s de powershell), cacheada
_temp_cache: tuple[float | None, float] | None = None


def _temp_c() -> float | None:
    global _temp_cache
    ahora = time.monotonic()
    if _temp_cache is not None and ahora - _temp_cache[1] < TEMP_TTL_S:
        return _temp_cache[0]
    valor = None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _TEMP_PS],
            capture_output=True,
            # sin stdin propio, un proceso sin consola heredable (el server lanzado desde otro
            # lado) hace fallar el DuplicateHandle con WinError 50 y la temperatura queda en None
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        salida = (r.stdout or "").strip()
        if salida:
            # HighPrecisionTemperature esta en deciKelvin
            valor = round(float(salida.splitlines()[0]) / 10 - 273.15, 1)
    except OSError, ValueError, subprocess.TimeoutExpired:
        valor = None
    _temp_cache = (valor, ahora)
    return valor


def snapshot() -> dict:
    """Memoria, CPU y temperatura de esta PC, ahora mismo. Nunca levanta una excepcion."""
    try:
        mem_free_gb, mem_total_gb = _memoria()
    except OSError:
        mem_free_gb = mem_total_gb = None
    try:
        cpu_pct = _cpu_pct()
    except OSError:
        cpu_pct = None
    try:
        temp_c = _temp_c()
    except OSError:
        temp_c = None
    return {
        "mem_free_gb": round(mem_free_gb, 2) if mem_free_gb is not None else None,
        "mem_total_gb": round(mem_total_gb, 2) if mem_total_gb is not None else None,
        "cpu_pct": cpu_pct,
        "temp_c": temp_c,
        "ts": _now(),
    }
