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

import datetime as dt
import json
import os
import secrets
import sys
import time
import uuid

T0 = time.perf_counter()

try:
    from . import procinfo
except ImportError:  # corriendo como script (python lienzo/hook.py) o con lienzo/ en sys.path
    import procinfo

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LIENZO = os.path.join(HOME, ".lienzo")
EVENTS = os.path.join(LIENZO, "events")
PENDING = os.path.join(LIENZO, "pending")
ANSWERS = os.path.join(LIENZO, "answers")


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


# --- cadena de procesos (procinfo, ctypes sin psutil) -----------------------


def find_agent_pid(max_hops: int = 8):
    """Sube por los padres hasta encontrar claude.exe o codex.exe (o el renombrado
    claude.exe.old.<ts> que deja el auto-update)."""
    pid = os.getpid()
    chain = []
    for _ in range(max_hops):
        parent, exe = procinfo.proc_info(pid)
        name = os.path.basename(exe).lower() if exe else "?"
        chain.append(f"{name}({pid})")
        if procinfo.agent_of(exe):
            return pid, exe, chain
        if not parent or parent == pid:
            break
        pid = parent
    return None, None, chain


# --- decision de permisos ----------------------------------------------------


def decision_json(decision: str, reason: str = "") -> dict:
    """Forma del JSON de salida: hookSpecificOutput.decision.behavior. Los dos agentes la comparten
    (verificado en T6 contra la doc); si alguna vez difieren, aca se parte por agente."""
    body = {"behavior": decision}
    if decision == "deny":
        body["message"] = reason or "Denegado desde el lienzo"
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": body}}


def wait_for_answer(agent: str, data: dict, wait_s: float) -> dict | None:
    """Deja el pedido en ~/.lienzo/pending y espera la respuesta del lienzo hasta wait_s segundos.
    Devuelve el JSON de la decision, o None si vencio (abstenerse: decide la consola)."""
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
                if (
                    isinstance(ans, dict)
                    and secrets.compare_digest(str(ans.get("nonce", "")), nonce)
                    and ans.get("decision") in ("allow", "deny")
                ):
                    result = decision_json(ans["decision"], ans.get("reason", ""))
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


def read_event() -> tuple[dict | None, str]:
    """(evento, crudo) de stdin. Si no es un objeto JSON queda el crudo en bad-<nanos>.txt y el
    evento es None: el hook devuelve 0 igual, que romper al agente no es una opcion."""
    # los agentes escriben UTF-8; sys.stdin en Windows decodifica con cp1252 y rompe los acentos
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            # el mismo camino que un JSON roto. Por eso ValueError y no TypeError, que no se atrapa
            raise ValueError("no es un objeto")  # noqa: TRY004
    except ValueError:
        try:
            atomic_write(os.path.join(EVENTS, f"bad-{time.time_ns()}.txt"), raw)
        except OSError:
            pass
        return None, raw
    return data, raw


def save_example(cfg: dict, agent: str, event: str, raw: str) -> None:
    """Copia cruda del primer evento de cada tipo en <ejemplos>/<agente>/<evento>.json, para tener
    a mano la forma real de cada hook. Solo si config.json trae "ejemplos" (el instalador lo apunta
    a la carpeta ejemplos/ del repo), y solo la primera vez de cada evento."""
    ej = cfg.get("ejemplos")
    if not ej:
        return
    try:
        d = os.path.join(ej, agent)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{event}.json")
        if not os.path.exists(p):
            atomic_write(p, raw)
    except OSError:
        pass


def event_path(sid: str, event: str) -> str:
    """Donde va un evento: <nanos>-<sid>-<evento>.json, con todo lo que no sea alfanumerico fuera
    (el sid y el nombre del evento vienen del agente y terminan en un nombre de archivo)."""
    safe_event = "".join(c for c in event if c.isalnum() or c in "-_")
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:64] or "nosid"
    return os.path.join(EVENTS, f"{time.time_ns()}-{safe_sid}-{safe_event}.json")


def answer_permission(agent: str, data: dict, cfg: dict, sid: str) -> None:
    """PermissionRequest: esperar la decision del lienzo hasta LIENZO_WAIT (o `wait` de
    config.json, 60 s), imprimirla si llego, y dejar el evento de cierre para que el server saque
    el pendiente de la tarjeta, haya contestado o se haya vencido."""
    try:
        wait_s = float(os.environ.get("LIENZO_WAIT") or cfg.get("wait") or 60)
    except ValueError:
        wait_s = 60.0
    out = wait_for_answer(agent, data, wait_s)
    if out is not None:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()
    done = "PermissionDecision" if out is not None else "PermissionTimeout"
    ev = {"hook_event_name": done, "session_id": sid, "agent": agent, "tool_use_id": data.get("tool_use_id")}
    if out is not None:
        ev["decision"] = out["hookSpecificOutput"]["decision"]["behavior"]
    ev["host_ts"] = now_iso()
    try:
        atomic_write(event_path(sid, done), json.dumps(ev, ensure_ascii=False))
    except OSError:
        pass


def main() -> int:
    agent = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    os.makedirs(EVENTS, exist_ok=True)
    data, raw = read_event()
    if data is None:
        return 0
    event = data.get("hook_event_name") or "unknown"
    sid = str(data.get("session_id") or "nosid")
    pid, exe, chain = find_agent_pid()
    cfg = load_config()
    save_example(cfg, agent, event, raw)
    data.update(
        {
            "agent": agent,
            "pid": pid,
            "agent_exe": exe,
            "proc_chain": chain,
            "host_ts": now_iso(),
            "hook_ms": round((time.perf_counter() - T0) * 1000, 1),
        }
    )
    atomic_write(event_path(sid, event), json.dumps(data, ensure_ascii=False))
    if event == "PermissionRequest":
        answer_permission(agent, data, cfg, sid)
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
