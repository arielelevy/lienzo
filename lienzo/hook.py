#!/usr/bin/env python
"""lienzo-hook: recibe el JSON de un hook (Claude Code o Codex) por stdin y deja un
evento en ~/.lienzo/events. Sin dependencias fuera de stdlib. Nunca sale con codigo 2.

Uso (lo registra settings.json / hooks.json):
    python hook.py claude
    python hook.py codex

Para PermissionRequest ademas escribe ~/.lienzo/pending/<request_id>.json y espera
~/.lienzo/answers/<request_id>.json hasta LIENZO_WAIT segundos (60). Si llega con el
nonce correcto imprime la decision en stdout; si no, sale 0 sin stdout (abstenerse).
"""
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import secrets
import sys
import time
import uuid

T0 = time.perf_counter()

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LIENZO = os.path.join(HOME, ".lienzo")
EVENTS = os.path.join(LIENZO, "events")
PENDING = os.path.join(LIENZO, "pending")
ANSWERS = os.path.join(LIENZO, "answers")
AGENT_EXES = ("claude.exe", "codex.exe")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_config() -> dict:
    try:
        with open(os.path.join(LIENZO, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# --- cadena de procesos con ctypes (sin psutil) -----------------------------

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_nt = ctypes.WinDLL("ntdll")
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _PBI(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
    ]


_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_nt.NtQueryInformationProcess.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG)]


def proc_info(pid: int):
    """(parent_pid, ruta_del_ejecutable) o (None, None)."""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, None
    try:
        pbi = _PBI()
        ret = wt.ULONG(0)
        status = _nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret))
        parent = int(pbi.InheritedFromUniqueProcessId or 0) if status == 0 else None
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        exe = buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        return parent, exe
    finally:
        _k32.CloseHandle(h)


def find_agent_pid(max_hops: int = 8):
    """Sube por los padres hasta encontrar claude.exe o codex.exe."""
    pid = os.getpid()
    chain = []
    for _ in range(max_hops):
        parent, exe = proc_info(pid)
        name = os.path.basename(exe).lower() if exe else "?"
        chain.append(f"{name}({pid})")
        # el auto-update renombra el binario a claude.exe.old.<ts> y el proceso sigue con ese nombre
        if any(name == a or name.startswith(a + ".") for a in AGENT_EXES):
            return pid, exe, chain
        if not parent or parent == pid:
            break
        pid = parent
    return None, None, chain


# --- decision de permisos ----------------------------------------------------

def decision_json(agent: str, decision: str, reason: str = "") -> dict:
    """Forma del JSON de salida por agente. Claude: hookSpecificOutput.decision.behavior.
    Codex: misma forma (verificado en T6 contra la doc; ajustar aca si difiere)."""
    body = {"behavior": decision}
    if decision == "deny":
        body["message"] = reason or "Denegado desde el lienzo"
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": body}}


def wait_for_answer(agent: str, data: dict, wait_s: float) -> dict | None:
    request_id = str(uuid.uuid4())
    nonce = secrets.token_hex(32)
    created = dt.datetime.now().astimezone()
    pending = {
        "request_id": request_id,
        "nonce": nonce,
        "session_id": data.get("session_id"),
        "agent": agent,
        "tool_name": data.get("tool_name"),
        "tool_input": data.get("tool_input"),
        "tool_use_id": data.get("tool_use_id"),
        "cwd": data.get("cwd"),
        "created": created.isoformat(timespec="milliseconds"),
        "expires_at": (created + dt.timedelta(seconds=wait_s)).isoformat(timespec="milliseconds"),
    }
    ppath = os.path.join(PENDING, request_id + ".json")
    apath = os.path.join(ANSWERS, request_id + ".json")
    os.makedirs(PENDING, exist_ok=True)
    os.makedirs(ANSWERS, exist_ok=True)
    atomic_write(ppath, json.dumps(pending, ensure_ascii=False))
    deadline = time.monotonic() + wait_s
    result = None
    try:
        while time.monotonic() < deadline:
            if os.path.exists(apath):
                try:
                    with open(apath, encoding="utf-8") as f:
                        ans = json.load(f)
                except (OSError, ValueError):
                    ans = None
                if isinstance(ans, dict) and secrets.compare_digest(str(ans.get("nonce", "")), nonce) \
                        and ans.get("decision") in ("allow", "deny"):
                    result = decision_json(agent, ans["decision"], ans.get("reason", ""))
                break
            time.sleep(0.25)
    finally:
        for p in (ppath, apath):
            try:
                os.remove(p)
            except OSError:
                pass
    return result


# --- main --------------------------------------------------------------------

def main() -> int:
    agent = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    os.makedirs(EVENTS, exist_ok=True)
    # los agentes escriben UTF-8; sys.stdin en Windows decodifica con cp1252 y rompe los acentos
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("no es un objeto")
    except ValueError:
        try:
            atomic_write(os.path.join(EVENTS, f"bad-{time.time_ns()}.txt"), raw)
        except OSError:
            pass
        return 0

    event = data.get("hook_event_name") or "unknown"
    sid = str(data.get("session_id") or "nosid")
    pid, exe, chain = find_agent_pid()
    cfg = load_config()

    # copia cruda para D:\Apps\lienzo\ejemplos\<agent>\<evento>.json (solo la primera vez)
    ej = cfg.get("ejemplos")
    if ej:
        try:
            d = os.path.join(ej, agent)
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, f"{event}.json")
            if not os.path.exists(p):
                atomic_write(p, raw)
        except OSError:
            pass

    data.update({
        "agent": agent,
        "pid": pid,
        "agent_exe": exe,
        "proc_chain": chain,
        "host_ts": now_iso(),
        "hook_ms": round((time.perf_counter() - T0) * 1000, 1),
    })
    safe_event = "".join(c for c in event if c.isalnum() or c in "-_")
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:64] or "nosid"
    name = f"{time.time_ns()}-{safe_sid}-{safe_event}.json"
    atomic_write(os.path.join(EVENTS, name), json.dumps(data, ensure_ascii=False))

    if event != "PermissionRequest":
        return 0

    try:
        wait_s = float(os.environ.get("LIENZO_WAIT") or cfg.get("wait") or 60)
    except ValueError:
        wait_s = 60.0
    out = wait_for_answer(agent, data, wait_s)
    if out is not None:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()
        # registrar la decision como evento para que el server cierre el pending
        try:
            atomic_write(os.path.join(EVENTS, f"{time.time_ns()}-{sid}-PermissionDecision.json"),
                         json.dumps({"hook_event_name": "PermissionDecision", "session_id": sid, "agent": agent,
                                     "tool_use_id": data.get("tool_use_id"),
                                     "decision": out["hookSpecificOutput"]["decision"]["behavior"],
                                     "host_ts": now_iso()}, ensure_ascii=False))
        except OSError:
            pass
    else:
        try:
            atomic_write(os.path.join(EVENTS, f"{time.time_ns()}-{sid}-PermissionTimeout.json"),
                         json.dumps({"hook_event_name": "PermissionTimeout", "session_id": sid, "agent": agent,
                                     "tool_use_id": data.get("tool_use_id"), "host_ts": now_iso()}, ensure_ascii=False))
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # jamas romper al agente
        try:
            atomic_write(os.path.join(EVENTS, f"bad-{time.time_ns()}.txt"), f"{type(e).__name__}: {e}")
        except OSError:
            pass
        sys.exit(0)
