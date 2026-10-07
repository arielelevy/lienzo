"""Cierre forzado de una CLI Windows identificada; el handle evita reciclar el PID al matarla."""

import ctypes
import ctypes.wintypes as wt

import backend
import procinfo
import state
import subproc


def created_at(handle) -> float | None:
    kernel = procinfo._k32
    kernel.GetProcessTimes.argtypes = [wt.HANDLE, *([ctypes.POINTER(wt.FILETIME)] * 4)]
    times = [wt.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    return ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10_000_000 - 11644473600


def close(card: dict, confirm: str) -> tuple[int, dict]:
    if confirm != card["session_id"]:
        return 400, {"error": "falta confirmar el cierre de esta sesion"}
    if backend.is_tmux(card):
        return 409, {"error": "el cierre forzado por proceso requiere el backend Windows"}
    pid = card.get("pid")
    handle = procinfo.open_process(pid)
    if not handle:
        return 409, {"error": "el proceso ya no existe o no se puede identificar"}
    try:
        started = state.parse_ts(card.get("started"))
        birth = created_at(handle)
        if started is None or birth is None or birth > started.timestamp() + 0.01:
            return 409, {"error": "el PID cambio desde que se registro la tarjeta; no se cierra"}
        if procinfo.process_agent(pid) != card.get("agent"):
            return 409, {"error": "el proceso ya no corresponde a esta CLI"}
        rc, _, err = subproc.correr(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=10)
        state.log(f"cierre forzado de {card['session_id'][:8]}: exit={rc}")
        return (200, {"ok": True}) if rc == 0 else (409, {"error": err or "no se pudo cerrar el proceso"})
    finally:
        procinfo.close_handle(handle)
