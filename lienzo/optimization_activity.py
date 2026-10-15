"""Señales locales sin capturar teclas, textos o ventanas del usuario."""

from __future__ import annotations

import ctypes
import datetime as dt
import math
import sys
import time

import health
import state

QUIET_SECONDS = 180
MAX_CPU = 35


def pending_active(pending, sessions, now=None) -> bool:
    moment = dt.datetime.now(dt.UTC) if now is None else now
    records = pending.values() if isinstance(pending, dict) else pending
    for permission in records:
        if not isinstance(permission, dict):
            return True
        session = sessions.get(permission.get("session_id"))
        if session is not None and (session.get("alive") is False or session.get("state") == "muerta"):
            continue
        expiry = permission.get("expires_at")
        try:
            deadline = dt.datetime.fromisoformat(expiry)
            if deadline.tzinfo is not None and deadline <= moment:
                continue
        except TypeError, ValueError:
            # Fecha desconocida no acredita vencimiento: conservar bloqueo en contexto vivo/incierto.
            deadline = None
        return True
    return False


def idle_seconds() -> float | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput()
    info.cbSize = ctypes.sizeof(info)
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
    user.GetLastInputInfo.restype = wintypes.BOOL
    kernel.GetTickCount.restype = wintypes.DWORD
    if not user.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((kernel.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def snapshot(last_ui: float) -> dict:
    idle = idle_seconds()
    with state.lock:
        live = [dict(s) for s in state.sessions.values() if s.get("alive") is not False and s.get("state") != "muerta"]
        pending = pending_active(state.pending, state.sessions)
    mem, _ = health._memoria()
    cpu = health._cpu_pct()
    return {
        "idle_seconds": idle,
        "ui_idle_seconds": time.monotonic() - last_ui,
        "cpu_pct": cpu,
        "mem_free_gb": mem,
        "pending": pending,
        "agents_busy": any(s.get("state") not in ("termino", "muerta") for s in live),
    }


def block_reason(signals: dict) -> str | None:
    for key in ("idle_seconds", "ui_idle_seconds", "cpu_pct", "mem_free_gb"):
        value = signals.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return f"señal desconocida: {key}"
    if signals.get("pending") is not False or signals.get("agents_busy") is not False:
        return "agentes trabajando o permisos pendientes"
    if min(signals["idle_seconds"], signals["ui_idle_seconds"]) < QUIET_SECONDS:
        return "actividad del usuario"
    if signals["cpu_pct"] > MAX_CPU or signals["mem_free_gb"] < health.RESERVA_GB:
        return "recursos insuficientes"
    return None


def cancellation_reason(last_ui: float) -> str | None:
    idle = idle_seconds()
    if idle is None or idle < QUIET_SECONDS or time.monotonic() - last_ui < QUIET_SECONDS:
        return "actividad del usuario o inactividad desconocida"
    with state.lock:
        if pending_active(state.pending, state.sessions) or any(
            s.get("alive") is not False and s.get("state") not in ("termino", "muerta") for s in state.sessions.values()
        ):
            return "agentes trabajando o permisos pendientes"
    return None
