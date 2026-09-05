#!/usr/bin/env python
"""lienzo-server: watcher de ~/.lienzo/events, registro de sesiones, cola de transcripciones,
liveness por PID, SSE y envio por inyeccion. Solo stdlib. Bind 127.0.0.1:7321.

    python server.py [--port 7321] [--no-sweep]
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth  # noqa: E402
import procs  # noqa: E402
import transcripts  # noqa: E402

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LIENZO = os.path.join(HOME, ".lienzo")
EVENTS = os.path.join(LIENZO, "events")
PENDING = os.path.join(LIENZO, "pending")
ANSWERS = os.path.join(LIENZO, "answers")
ADJUNTOS = os.path.join(LIENZO, "adjuntos")
SESSIONS = os.path.join(LIENZO, "sessions")
LOG = os.path.join(LIENZO, "lienzo.log")
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "web", "dist")                 # salida de `npm run build` (Vite + React)
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
        ".woff2": "font/woff2", ".map": "application/json"}
PYTHON = sys.executable

NEEDS_NOTIFICATIONS = {"permission_prompt", "idle_prompt", "agent_needs_input",
                       "elicitation_dialog", "elicitation_url_dialog"}
DEAD_GRACE_S = 60
ATTACH_MAX_DAYS = 30
LONG_TEXT = 500

CLOUDFLARED = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared", "cloudflared.exe")
remote_url: str | None = None
# alta desde el celular con un solo QR: token de 15 min que entrega passphrase + otpauth una vez
enroll: dict | None = None
ENROLL_S = 15 * 60

LINKS_FILE = os.path.join(LIENZO, "links.json")
RULES_FILE = os.path.join(LIENZO, "rules.json")

lock = threading.RLock()
sessions: dict[str, dict] = {}


class JsonList:
    """Lista persistida en un JSON y publicada por SSE: vinculos (reenvios hechos) y reglas
    (conexiones pendientes). Todo pasa por aca: agregar, filtrar, guardar, avisar."""

    def __init__(self, path: str, event: str):
        self.path = path
        self.event = event
        self.items: list[dict] = []

    def load(self, keep) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.items = [x for x in json.load(f) if keep(x)]
        except (OSError, ValueError):
            self.items = []

    def save(self) -> None:
        try:
            atomic_write(self.path, json.dumps(self.items, ensure_ascii=False, indent=1))
        except OSError:
            pass

    def snapshot(self) -> list[dict]:
        with lock:
            return list(self.items)

    def publish(self) -> None:
        broadcast({"type": self.event, self.event: self.snapshot()})

    def add(self, item: dict, cap: int = 200) -> None:
        with lock:
            self.items.append(item)
            del self.items[:-cap]
            self.save()
        self.publish()

    def remove(self, pred) -> None:
        with lock:
            n = len(self.items)
            self.items[:] = [x for x in self.items if not pred(x)]
            changed = n != len(self.items)
            if changed:
                self.save()
        if changed:
            self.publish()


links = JsonList(LINKS_FILE, "links")   # {id, from, to, ts, text}
rules = JsonList(RULES_FILE, "rules")   # {id, kind: on_stop|at, from, to, text, at, repeat, max_fires, fired, enabled}
pending: dict[str, dict] = {}
clients: list[queue.Queue] = []
transcript_stat: dict[str, tuple] = {}
last_sweep = 0.0


# --- utilidades ----------------------------------------------------------------

def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def short(s, n=300) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def broadcast(ev: dict) -> None:
    data = json.dumps(ev, ensure_ascii=False)
    with lock:
        dead = []
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            clients.remove(q)


def claude_slug(cwd: str) -> str:
    return cwd.replace(":", "-").replace("\\", "-").replace("/", "-")


def repo_of(cwd: str | None) -> str:
    return os.path.basename((cwd or "").rstrip("\\/")) or "?"


ATTACH_WRAPPER = "Leé el archivo adjunto y respondé:"


def unwrap_attachment(prompt: str) -> str:
    """Un texto largo viaja como 'Leé el archivo adjunto y respondé: Adjunto: <ruta>'. En la
    tarjeta se muestra el contenido del adjunto, no el envoltorio."""
    p = (prompt or "").strip()
    if not p.startswith(ATTACH_WRAPPER):
        return prompt
    for part in p.split("Adjunto: ")[1:]:
        path = part.strip().split(" Adjunto: ")[0].strip()
        if path.lower().endswith(".md") and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read(600)
            except OSError:
                pass
    return prompt


def tool_detail(tool_name: str | None, tool_input) -> str:
    if not isinstance(tool_input, dict):
        return short(str(tool_input or ""), 200)
    for k in ("command", "cmd", "file_path", "notebook_path", "url", "pattern", "description"):
        if tool_input.get(k):
            return short(str(tool_input[k]), 300)
    return short(json.dumps(tool_input, ensure_ascii=False), 300)


# --- registro de sesiones -------------------------------------------------------

def save_session(s: dict) -> None:
    atomic_write(os.path.join(SESSIONS, f"{s['session_id']}.json"), json.dumps(s, ensure_ascii=False, indent=1))


def add_link(src: str, dst: str, text: str, kind: str = "send") -> None:
    """kind: send (inyeccion) | native (canal Claude<->Claude por SendMessage)."""
    links.add({"id": secrets.token_hex(6), "from": src, "to": dst, "ts": now(), "text": short(text, 160), "kind": kind})


# --- reglas: "cuando termine" y "a una hora" ------------------------------------------

def render_template(tpl: str, s: dict | None) -> str:
    if not s:
        return tpl
    return (tpl.replace("{repo}", s.get("repo") or "").replace("{agente}", s.get("agent") or "")
            .replace("{titulo}", s.get("title") or "").replace("{pedido}", s.get("last_prompt") or "")
            .replace("{respuesta}", s.get("last_reply") or ""))


def fire_rule(rule: dict) -> None:
    with lock:
        src = sessions.get(rule.get("from") or "")
        dst = sessions.get(rule["to"])
    if dst is None:
        rules.remove(lambda r: r["id"] == rule["id"])
        return
    text = render_template(rule.get("text") or "", src)
    code, res = send_to_session(dst, text, [])
    with lock:
        rule["fired"] = rule.get("fired", 0) + 1
        rule["last_fired"] = now()
        rule["last_result"] = "ok" if code == 200 else str(res.get("error"))
        if not rule.get("repeat") or rule["fired"] >= int(rule.get("max_fires") or 1):
            rule["enabled"] = False
        rules.save()
    log(f"regla {rule['id']} ({rule['kind']}) -> {rule['to'][:8]}: {rule['last_result']}")
    if code == 200 and src and src["session_id"] != dst["session_id"]:
        add_link(src["session_id"], dst["session_id"], text)
    rules.publish()


def fire_on_stop(sid: str) -> None:
    """La sesion `sid` cerro un turno: disparar sus reglas 'cuando termine' (con enfriamiento
    de 30 s para que dos sesiones conectadas en ambos sentidos no se contesten en bucle)."""
    due = []
    with lock:
        for r in rules.items:
            if r.get("enabled") and r.get("kind") == "on_stop" and r.get("from") == sid:
                last = r.get("last_fired")
                if last:
                    try:
                        if (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(last)).total_seconds() < 30:
                            continue
                    except ValueError:
                        pass
                due.append(r)
    for r in due:
        fire_rule(r)


def rules_loop() -> None:
    while True:
        try:
            t = dt.datetime.now().astimezone()
            due = []
            with lock:
                for r in rules.items:
                    if r.get("enabled") and r.get("kind") == "at" and r.get("at"):
                        try:
                            if dt.datetime.fromisoformat(r["at"]) <= t:
                                due.append(r)
                        except ValueError:
                            r["enabled"] = False
            for r in due:
                fire_rule(r)
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        time.sleep(5)


def drop_session(sid: str, reason: str) -> None:
    with lock:
        s = sessions.pop(sid, None)
    if s is None:
        return
    links.remove(lambda l: sid in (l["from"], l["to"]))
    rules.remove(lambda r: sid in (r.get("from"), r["to"]))
    try:
        os.remove(os.path.join(SESSIONS, f"{sid}.json"))
    except OSError:
        pass
    log(f"tarjeta {sid[:8]} borrada ({reason})")
    broadcast({"type": "removed", "session_id": sid})


def new_session(sid: str, agent: str, source: str) -> dict:
    return {
        "session_id": sid, "agent": agent, "pid": None, "agent_exe": None, "cwd": None, "repo": "?",
        "branch": None, "title": None, "transcript_path": None,
        "state": "termino", "state_since": now(), "needs": None,
        "last_prompt": "", "last_reply": "", "started": now(),
        "last_event": None, "last_event_ts": None, "alive": True, "dead_since": None,
        "source": source, "hooked": source == "hook", "pending_id": None,
    }


def set_state(s: dict, state: str) -> None:
    prev = s["state"]
    if prev != state:
        s["state"] = state
        s["state_since"] = now()
        if state == "termino" and prev in ("corriendo", "te_necesita"):
            # cierre de turno: reglas "cuando termine" (en otro hilo, el envio tarda)
            threading.Thread(target=fire_on_stop, args=(s["session_id"],), daemon=True).start()
    if state != "te_necesita":
        s["needs"] = None


def touch(s: dict) -> None:
    save_session(s)
    broadcast({"type": "session", "session": s})


def refresh_from_transcript(s: dict, force_state: bool = False) -> bool:
    """Titulo, rama, ultimo pedido/respuesta desde la transcripcion. Si la sesion no tiene
    hooks (o force_state), tambien el estado corriendo/termino. Devuelve si cambio algo."""
    path = s.get("transcript_path")
    if not path or not os.path.exists(path):
        return False
    try:
        r = transcripts.turns(s["agent"], path, 1)
    except Exception as e:  # noqa: BLE001
        log(f"transcripcion {path}: {e}")
        return False
    meta, ts = r["meta"], r["turns"]
    before = json.dumps({k: s.get(k) for k in ("title", "branch", "last_prompt", "last_reply", "state", "cwd", "last_error")})
    if meta.get("title"):
        s["title"] = meta["title"]
    elif s["agent"] == "codex" and not s.get("title"):
        s["title"] = transcripts.codex_title(s["session_id"])
    if meta.get("branch"):
        s["branch"] = meta["branch"]
    if meta.get("cwd") and not s.get("cwd"):
        s["cwd"] = meta["cwd"]
        s["repo"] = repo_of(s["cwd"])
    if ts:
        t = ts[-1]
        hooked = s.get("hooked") and not force_state
        tools = [b for b in t["blocks"] if b["kind"] == "tool"]
        if hooked:
            # el pedido y la respuesta final ya vienen por hook (UserPromptSubmit / Stop);
            # de la transcripcion solo se toma "usando X" mientras corre
            if s["state"] == "corriendo" and not t.get("ended") and tools:
                s["last_reply"] = f"usando {tools[-1]['name']}"
        else:
            if t.get("prompt") and not t["prompt"].startswith("(turno anterior"):
                s["last_prompt"] = short(t["prompt"], 500)
            if t.get("final"):
                s["last_reply"] = short(t["final"], 600)
            elif not t.get("ended") and tools:
                s["last_reply"] = f"usando {tools[-1]['name']}"
            if s["state"] != "muerta" and not s.get("needs"):
                set_state(s, "termino" if t.get("ended") else "corriendo")
        # error del turno (Codex: limite de uso, abortado; Claude: no aplica hoy) va aparte, en rojo
        s["last_error"] = short(t.get("error") or "", 300) or None
        if s["last_error"] and not t.get("final"):
            s["last_reply"] = s["last_error"]
    after = json.dumps({k: s.get(k) for k in ("title", "branch", "last_prompt", "last_reply", "state", "cwd", "last_error")})
    return before != after


# --- eventos de hooks -------------------------------------------------------------

def apply_event(ev: dict) -> None:
    name = ev.get("hook_event_name") or "?"
    sid = ev.get("session_id")
    agent = ev.get("agent") or "claude"
    if not sid or ev.get("agent_id"):
        return  # sin sesion, o subagente
    with lock:
        s = sessions.get(sid)
        created = s is None
        if created:
            s = new_session(sid, agent, "hook")
            sessions[sid] = s
        s["hooked"] = True
        s["source"] = "hook"
        pid = ev.get("pid")
        if pid and procs.agent_alive(pid):
            if s.get("pid") != pid:
                # otra tarjeta (del barrido) con el mismo pid es la misma sesion
                for other_sid, other in list(sessions.items()):
                    if other_sid != sid and other.get("pid") == pid:
                        drop_session(other_sid, "duplicada por barrido")
            s["pid"] = pid
            s["agent_exe"] = ev.get("agent_exe")
            # el panel de Claude Code de VS Code y las apps de escritorio disparan hooks pero no
            # tienen consola: se ven y se leen, no se les escribe
            s["no_console"] = not procs.is_tui(pid)
        if ev.get("cwd") and (not s.get("cwd") or name == "SessionStart"):
            # el cwd de los hooks sigue al shell del agente (cambia con un cd de una tool);
            # el repo de la tarjeta se fija al arrancar y no baila
            s["cwd"] = ev["cwd"]
            s["repo"] = repo_of(ev["cwd"])
        if ev.get("transcript_path"):
            s["transcript_path"] = ev["transcript_path"]
        s["last_event"] = name
        s["last_event_ts"] = ev.get("host_ts") or now()
        s["alive"] = True
        s["dead_since"] = None

        if name == "SessionStart":
            if created:
                set_state(s, "termino")
        elif name == "UserPromptSubmit":
            set_state(s, "corriendo")
            if not transcripts.is_system_prompt(ev.get("prompt", "")):
                s["last_prompt"] = short(unwrap_attachment(ev.get("prompt", "")), 500)
            s["pending_id"] = None
        elif name == "Stop":
            set_state(s, "termino")
            if ev.get("last_assistant_message"):
                s["last_reply"] = short(ev["last_assistant_message"], 600)
            s["pending_id"] = None
        elif name == "Notification":
            nt = ev.get("notification_type") or ""
            if nt in NEEDS_NOTIFICATIONS:
                set_state(s, "te_necesita")
                s["needs"] = {"kind": "idle" if nt == "idle_prompt" else "permission" if nt == "permission_prompt" else nt,
                              "detail": short(ev.get("message", ""), 300), "where": "terminal"}
        elif name == "PermissionRequest":
            set_state(s, "te_necesita")
            s["needs"] = {"kind": "permission", "tool": ev.get("tool_name"),
                          "detail": tool_detail(ev.get("tool_name"), ev.get("tool_input")),
                          "tool_use_id": ev.get("tool_use_id"), "where": "lienzo"}
        elif name == "PermissionDecision":
            s["needs"] = None
            s["pending_id"] = None
            set_state(s, "corriendo")
        elif name == "PermissionTimeout":
            if s["state"] == "te_necesita" and s.get("needs"):
                s["needs"]["where"] = "terminal"
            s["pending_id"] = None
        elif name in ("PostToolUse",):
            if s["state"] == "te_necesita" and (s.get("needs") or {}).get("tool_use_id") == ev.get("tool_use_id"):
                set_state(s, "corriendo")
        elif name == "Interrupt":
            set_state(s, "termino")
        elif name == "SessionEnd":
            set_state(s, "muerta")
            s["alive"] = False
            s["dead_since"] = now()
        if created or name == "SessionStart":
            refresh_from_transcript(s)
        touch(s)


def consume_events() -> None:
    while True:
        try:
            names = sorted(os.listdir(EVENTS))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(EVENTS, n)
            if n.endswith(".tmp"):
                continue
            if not n.endswith(".json"):
                if n.startswith("bad-") and time.time() - os.path.getmtime(p) > 3600:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    ev = json.load(f)
                apply_event(ev)
            except Exception:  # noqa: BLE001
                log(f"evento {n} fallo:\n{traceback.format_exc()}")
            try:
                os.remove(p)
            except OSError:
                pass
        time.sleep(0.25)


# --- pendientes de permiso -----------------------------------------------------------

def scan_pending() -> None:
    while True:
        try:
            found = {}
            for n in os.listdir(PENDING):
                if not n.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(PENDING, n), encoding="utf-8") as f:
                        d = json.load(f)
                    found[d["request_id"]] = d
                except (OSError, ValueError, KeyError):
                    continue
            with lock:
                changed = set(found) != set(pending)
                pending.clear()
                pending.update(found)
                if changed:
                    for d in found.values():
                        s = sessions.get(d.get("session_id"))
                        if s is not None and s.get("pending_id") != d["request_id"]:
                            s["pending_id"] = d["request_id"]
                            touch(s)
                    for s in sessions.values():
                        if s.get("pending_id") and s["pending_id"] not in found:
                            s["pending_id"] = None
                            touch(s)
            if changed:
                broadcast({"type": "pending", "pending": public_pending()})
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        time.sleep(0.5)


def public_pending() -> list[dict]:
    with lock:
        return [{k: v for k, v in d.items() if k != "nonce"} for d in pending.values()]


def answer_pending(request_id: str, decision: str, reason: str = "") -> tuple[int, dict]:
    with lock:
        d = pending.get(request_id)
    if d is None:
        return 410, {"ok": False, "error": "el pedido ya vencio o fue contestado"}
    atomic_write(os.path.join(ANSWERS, f"{request_id}.json"),
                 json.dumps({"nonce": d["nonce"], "decision": decision, "reason": reason, "answered": now()}))
    log(f"permiso {request_id[:8]} -> {decision} ({d.get('tool_name')})")
    return 200, {"ok": True}


# --- liveness, barrido y transcripciones ----------------------------------------------

def guess_transcript(agent: str, cwd: str | None, created: str | None) -> tuple[str | None, str | None]:
    """(session_id, transcript_path) mas probable para un agente encontrado por barrido."""
    if not cwd:
        return None, None
    try:
        t0 = dt.datetime.fromisoformat(created).timestamp() - 120 if created else 0
    except ValueError:
        t0 = 0
    if agent == "claude":
        d = os.path.join(HOME, ".claude", "projects", claude_slug(cwd))
        cands = [p for p in glob.glob(os.path.join(d, "*.jsonl")) if os.path.getmtime(p) >= t0]
        if not cands:
            return None, None
        p = max(cands, key=os.path.getmtime)
        return os.path.splitext(os.path.basename(p))[0], p
    # codex: entre los rollouts de la TUI con el mismo cwd, el que arranco mas cerca (despues)
    # del nacimiento del proceso. "El mas nuevo" se equivoca si despues corrio un `codex exec`.
    cands = [p for p in glob.glob(os.path.join(HOME, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl"))
             if os.path.getmtime(p) >= t0]
    best, best_gap = None, None
    for p in cands:
        try:
            with open(p, "rb") as f:
                first = json.loads(f.readline().decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        pl = first.get("payload") or {}
        if (pl.get("cwd") or "").lower() != cwd.lower():
            continue
        if pl.get("originator") not in (None, "codex-tui", "codex_cli_rs"):
            continue  # Codex Desktop (importados), codex_exec, app-server: no son la TUI
        try:
            started = dt.datetime.fromisoformat((pl.get("timestamp") or first.get("timestamp")).replace("Z", "+00:00")).timestamp()
        except (AttributeError, ValueError):
            started = os.path.getmtime(p)
        gap = started - (t0 + 120)          # t0 ya tiene 120 s de margen
        if gap < -120:
            continue                        # arranco antes que el proceso: no es suyo
        if best_gap is None or abs(gap) < abs(best_gap):
            best, best_gap = (pl.get("id") or pl.get("session_id"), p), gap
    return best or (None, None)


def sweep_once() -> None:
    global last_sweep
    last_sweep = time.time()
    found = procs.sweep()
    with lock:
        known_pids = {s.get("pid") for s in sessions.values() if s.get("pid")}
        # tarjetas del barrido que todavia no tienen transcripcion: reintentar (Codex crea el
        # rollout recien en el primer turno, no al abrir)
        retry = [s for s in sessions.values() if s.get("source") == "sweep" and not s.get("transcript_path") and s.get("pid")]
    for s in retry:
        cwd = s.get("cwd") or procs.cwd_of(s["pid"])
        sid, tpath = guess_transcript(s["agent"], cwd, s.get("started"))
        if not tpath:
            continue
        with lock:
            if sid and sid != s["session_id"] and sid not in sessions:
                sessions.pop(s["session_id"], None)
                try:
                    os.remove(os.path.join(SESSIONS, f"{s['session_id']}.json"))
                except OSError:
                    pass
                broadcast({"type": "removed", "session_id": s["session_id"]})
                s["session_id"] = sid
                sessions[sid] = s
            s["transcript_path"] = tpath
            s["cwd"] = s.get("cwd") or cwd
            s["repo"] = repo_of(s["cwd"])
            s["title"] = None
            refresh_from_transcript(s)
            touch(s)
            log(f"barrido: pid {s['pid']} ahora con transcripcion {os.path.basename(tpath)}")
    for p in found:
        if p["pid"] in known_pids:
            continue
        cwd = procs.cwd_of(p["pid"])
        sid, tpath = guess_transcript(p["agent"], cwd, p.get("created"))
        with lock:
            if sid and sid in sessions:
                s = sessions[sid]
                if not s.get("pid") or not procs.agent_alive(s["pid"]):
                    s["pid"] = p["pid"]
                    s["agent_exe"] = p["exe"]
                    s["alive"] = True
                    s["dead_since"] = None
                    if s["state"] == "muerta":
                        set_state(s, "termino")
                    touch(s)
                continue
            s = new_session(sid or f"pid-{p['pid']}", p["agent"], "sweep")
            s.update({"pid": p["pid"], "agent_exe": p["exe"], "cwd": cwd, "repo": repo_of(cwd),
                      "transcript_path": tpath, "started": p.get("created") or now(),
                      "in_vscode": p.get("in_vscode"), "orphan": p.get("orphan")})
            if not tpath:
                s["title"] = "sesion sin transcripcion identificada"
            sessions[s["session_id"]] = s
            refresh_from_transcript(s)
            touch(s)
            log(f"barrido: {p['agent']} pid {p['pid']} cwd={cwd} sid={s['session_id'][:8]}")


def liveness_loop(sweep_every: float) -> None:
    while True:
        try:
            with lock:
                items = list(sessions.values())
            for s in items:
                changed = False
                alive = procs.agent_alive(s.get("pid")) if s.get("pid") else None
                if alive is False and s["alive"]:
                    s["alive"] = False
                    s["dead_since"] = now()
                    set_state(s, "muerta")
                    changed = True
                elif alive and not s["alive"]:
                    s["alive"] = True
                    s["dead_since"] = None
                    changed = True
                if s["state"] == "muerta" and s.get("dead_since"):
                    try:
                        dead_for = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(s["dead_since"])).total_seconds()
                    except ValueError:
                        dead_for = 0
                    if dead_for > DEAD_GRACE_S:
                        drop_session(s["session_id"], "muerta hace mas de 60 s")
                        continue
                # transcripcion: si crecio, avisar y refrescar la tarjeta
                tp = s.get("transcript_path")
                if tp and os.path.exists(tp):
                    st = os.stat(tp)
                    sig = (st.st_size, int(st.st_mtime))
                    if transcript_stat.get(s["session_id"]) != sig:
                        transcript_stat[s["session_id"]] = sig
                        if refresh_from_transcript(s):
                            changed = True
                        broadcast({"type": "transcript", "session_id": s["session_id"], "size": st.st_size})
                if changed:
                    touch(s)
            if sweep_every and time.time() - last_sweep > sweep_every:
                sweep_once()
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        time.sleep(2)


# --- envio ---------------------------------------------------------------------------

def save_attachment(sid: str, name: str, data: bytes) -> str:
    safe = "".join(c for c in os.path.basename(name) if c.isalnum() or c in "._- ") or "adjunto"
    d = os.path.join(ADJUNTOS, sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def send_to_session(s: dict, text: str, attachments: list[str]) -> tuple[int, dict]:
    if not s.get("pid") or not procs.agent_alive(s["pid"]):
        return 409, {"ok": False, "error": "la sesion no tiene un PID vivo"}
    if s.get("orphan"):
        return 409, {"ok": False, "error": "la sesion perdio su terminal (huerfana): no hay consola donde escribir"}
    if s.get("no_console"):
        return 409, {"ok": False, "error": "esta sesion no tiene consola (panel de VS Code o app de escritorio): no se le puede escribir"}
    if s.get("pending_id"):
        return 409, {"ok": False, "error": "hay un permiso pendiente; contestalo primero"}
    text = (text or "").replace("\r", "")
    if len(text) > LONG_TEXT or "\n" in text.strip():
        path = save_attachment(s["session_id"], "mensaje.md", text.encode("utf-8"))
        attachments = [path] + list(attachments)
        text = "Leé el archivo adjunto y respondé:"
    parts = [text.strip()] if text.strip() else []
    parts += [f"Adjunto: {a}" for a in attachments]
    final = " ".join(parts)
    if not final:
        return 400, {"ok": False, "error": "texto vacio"}
    tf = save_attachment(s["session_id"], ".send.txt", final.encode("utf-8")) if len(final) > 2000 else None
    cmd = [PYTHON, os.path.join(HERE, "send.py"), "--pid", str(s["pid"])]
    cmd += ["--text-file", tf] if tf else ["--text", final]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=0x00000008)  # DETACHED_PROCESS: sin consola propia
        out = json.loads(r.stdout.strip() or "{}")
    except subprocess.TimeoutExpired:
        return 500, {"ok": False, "error": "send.py no termino en 60 s"}
    except ValueError:
        return 500, {"ok": False, "error": f"send.py devolvio basura: {r.stdout[:200]} {r.stderr[:200]}"}
    finally:
        if tf:
            try:
                os.remove(tf)
            except OSError:
                pass
    log(f"send {s['session_id'][:8]} pid {s['pid']}: {out}")
    if out.get("ok"):
        s["last_prompt"] = short(final, 500)
        set_state(s, "corriendo")
        touch(s)
        return 200, out
    return 500, out


# --- pantalla (solo para las sugerencias de la TUI de Claude, DISENO §12) ------------------

def read_screen(pid: int) -> dict:
    """Subproceso: screen.py hace FreeConsole/AttachConsole y no puede correr dentro del server."""
    try:
        r = subprocess.run([PYTHON, os.path.join(HERE, "screen.py"), "--pid", str(pid), "--json"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                           creationflags=0x00000008)
        return json.loads(r.stdout.strip() or "{}")
    except (subprocess.TimeoutExpired, ValueError):
        return {"ok": False, "error": "screen.py no respondio"}


def screen_loop() -> None:
    """Cada 5 s, para las sesiones de Claude con terminal: que hay en la caja de entrada.
    Si no es placeholder ni texto que el usuario esta tipeando (eso no se distingue: se toma
    como sugerencia lo que aparece con la sesion en 'termino'), va a la tarjeta."""
    while True:
        try:
            with lock:
                items = [s for s in sessions.values()
                         if s.get("agent") == "claude" and s.get("pid") and s.get("alive") and not s.get("orphan")]
            for s in items:
                r = read_screen(s["pid"])
                area = r.get("area") if r.get("ok") else None
                sug = None
                # sugerencia: texto en la caja con la sesion ociosa (termino, o "te necesita" por idle);
                # medido: "❯ Guardá la revisión en docs/revision-backend.md" con la sesion en idle_prompt
                idle = s["state"] == "termino" or (s["state"] == "te_necesita" and (s.get("needs") or {}).get("kind") == "idle")
                if area and not area["placeholder"] and idle:
                    sug = short(area["input"], 300)
                if s.get("suggestion") != sug:
                    s["suggestion"] = sug
                    touch(s)
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        time.sleep(5)


# --- HTTP ------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "lienzo/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencio; el log propio alcanza
        pass

    def _json(self, code: int, obj, extra_headers: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        """JSON del cuerpo tolerante a clientes que mandan latin-1 (un curl desde Git Bash)."""
        raw = self._body()
        if not raw:
            return {}
        try:
            d = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            d = json.loads(raw.decode("cp1252", errors="replace"))
        return d if isinstance(d, dict) else {}

    # --- identidad del cliente ------------------------------------------------------
    def _client_ip(self) -> str:
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _via_tunnel(self) -> bool:
        return bool(self.headers.get("CF-Connecting-IP")) or self.headers.get("X-Forwarded-Proto") == "https"

    def _is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1") and not self._via_tunnel()

    def _authed(self) -> bool:
        """Decision del autor (2026-09-05): en la propia PC no se pide login. El server solo
        escucha en 127.0.0.1, asi que 'local' es una conexion sin cabeceras del tunel. Lo que
        entra por cloudflared trae CF-Connecting-IP y exige la cookie (passphrase + TOTP)."""
        if self._is_local() or not auth.configured():
            return True
        return auth.check(auth.parse_cookie(self.headers.get("Cookie")))

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Lienzo") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        ohost = origin.split("//", 1)[-1]
        host = self.headers.get("Host") or ""
        # el propio host, o el dev server de Vite en la misma maquina (localhost:5173)
        return ohost == host or ohost.split(":")[0] in ("localhost", "127.0.0.1")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = urllib.parse.parse_qs(u.query)
        try:
            if not parts:
                index = os.path.join(DIST, "index.html")
                if not os.path.exists(index):
                    return self._json(503, {"error": "falta el build de la UI: cd web && npm install && npm run build"})
                return self._file(index, "text/html; charset=utf-8")
            if parts[0] == "assets" and len(parts) == 2 and os.path.isdir(DIST):
                # estaticos del build de Vite; sin ".." posibles porque parts viene partido por "/"
                name = parts[1]
                if "\\" in name or name.startswith("."):
                    return self._json(404, {"error": "ruta invalida"})
                path = os.path.join(DIST, "assets", name)
                return self._file(path, MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
                                  cache="public, max-age=31536000, immutable")
            if parts == ["health"]:
                return self._json(200, {"ok": True, "sessions": len(sessions), "pending": len(pending), "ts": now()})
            if parts == ["auth"]:
                return self._json(200, {"configured": auth.configured(), "authenticated": self._authed(),
                                        "local": self._is_local(), "remote_url": remote_url, "mode": auth.mode()})
            if parts == ["totp"]:
                # volver a ver el QR de Authenticator (segundo telefono, o alta interrumpida): solo local
                if not self._is_local():
                    return self._json(403, {"error": "solo desde la PC"})
                cur = auth.current_otpauth(os.environ.get("USERNAME", "lienzo"))
                return self._json(200, cur) if cur else self._json(404, {"error": "sin acceso configurado"})
            if parts == ["enroll"]:
                # el token del QR es la credencial; vale 15 min desde el alta y se apaga solo
                global enroll
                tok = q.get("token", [""])[0]
                with lock:
                    e = enroll
                    if e and time.time() > e["expires"]:
                        enroll = e = None
                if not e or not tok or not secrets.compare_digest(tok, e["token"]):
                    log(f"enroll rechazado desde {self._client_ip()}")
                    return self._json(410, {"error": "el enlace de alta vencio o no es valido; rehacer desde la PC"})
                log(f"enroll entregado a {self._client_ip()}")
                return self._json(200, {"passphrase": e["passphrase"], "otpauth": e["otpauth"],
                                        "expires_in": int(e["expires"] - time.time())})
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["sessions"]:
                with lock:
                    return self._json(200, sorted(sessions.values(), key=lambda s: (s["repo"], s["started"])))
            if parts == ["pending"]:
                return self._json(200, public_pending())
            if parts == ["links"]:
                return self._json(200, links.snapshot())
            if parts == ["rules"]:
                return self._json(200, rules.snapshot())
            if parts == ["events"]:
                return self._sse()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "screen":
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if not s.get("pid") or s.get("orphan"):
                    return self._json(409, {"ok": False, "error": "sin consola que leer"})
                return self._json(200, read_screen(s["pid"]))
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] in ("turns", "digest"):
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if not s.get("transcript_path") or not os.path.exists(s["transcript_path"]):
                    return self._json(200, {"meta": {}, "turns": [], "has_more": False, "note": "sin transcripcion"})
                n = int(q.get("n", ["10"])[0])
                before = q.get("before", [None])[0]
                if parts[2] == "turns":
                    return self._json(200, transcripts.turns(s["agent"], s["transcript_path"], n, before))
                return self._json(200, transcripts.digest(s["agent"], s["transcript_path"], n))
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            return self._json(500, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo o el Origin no es propio"})
        try:
            if parts == ["login"]:
                d = self._json_body()
                ok, motivo, token = auth.login(str(d.get("passphrase", "")), str(d.get("code", "")),
                                               self._client_ip(), self.headers.get("User-Agent", ""))
                if not ok:
                    log(f"login fallido desde {self._client_ip()}: {motivo}")
                    # hacia afuera un solo mensaje, salvo el bloqueo, que conviene que se vea
                    msg = motivo if motivo.startswith("bloqueado") or "no configurado" in motivo else "codigo incorrecto"
                    return self._json(401, {"ok": False, "error": msg})
                log(f"login ok desde {self._client_ip()}")
                return self._json(200, {"ok": True}, {"Set-Cookie": auth.cookie_header(token, secure=self._via_tunnel())})
            if parts == ["logout"]:
                auth.logout(auth.parse_cookie(self.headers.get("Cookie")))
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{auth.COOKIE}=; Path=/; Max-Age=0"})
            if parts == ["setup"]:
                # alta del acceso remoto: solo desde la propia PC y solo una vez
                if not self._is_local():
                    return self._json(403, {"error": "el alta se hace desde la PC"})
                if auth.configured():
                    return self._json(409, {"error": "ya esta configurado; borrar ~/.lienzo/auth.json para rehacerlo"})
                d = self._json_body()
                res = auth.setup(account=os.environ.get("USERNAME", "lienzo"),
                                 mode="full" if d.get("mode") == "full" else "code")
                global enroll
                with lock:
                    enroll = {"token": secrets.token_urlsafe(24), "passphrase": res["passphrase"],
                              "otpauth": res["otpauth"], "expires": time.time() + ENROLL_S}
                    res["enroll_token"] = enroll["token"]
                    res["enroll_expires_s"] = ENROLL_S
                log("acceso remoto configurado (passphrase + TOTP); enlace de alta valido 15 min")
                return self._json(200, res)
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["rescan"]:
                threading.Thread(target=sweep_once, daemon=True).start()
                return self._json(202, {"ok": True})
            if parts == ["rules"]:
                d = self._json_body()
                kind = d.get("kind")
                if kind not in ("on_stop", "at"):
                    return self._json(400, {"error": "kind debe ser on_stop o at"})
                if d.get("to") not in sessions:
                    return self._json(404, {"error": "sesion destino desconocida"})
                if kind == "on_stop" and d.get("from") not in sessions:
                    return self._json(404, {"error": "sesion origen desconocida"})
                at = None
                if kind == "at":
                    try:
                        at = dt.datetime.fromisoformat(str(d.get("at")))
                        if at.tzinfo is None:
                            at = at.astimezone()
                    except ValueError:
                        return self._json(400, {"error": "at debe ser una fecha ISO"})
                rule = {"id": secrets.token_hex(6), "kind": kind, "from": d.get("from") or None, "to": d["to"],
                        "text": str(d.get("text") or ""), "at": at.isoformat(timespec="seconds") if at else None,
                        "repeat": bool(d.get("repeat")), "max_fires": max(1, min(int(d.get("max_fires") or 1), 50)),
                        "fired": 0, "enabled": True, "created": now()}
                rules.add(rule, cap=500)
                log(f"regla nueva {rule['id']}: {kind} -> {rule['to'][:8]} {rule.get('at') or ''}")
                return self._json(200, rule)
            if len(parts) == 2 and parts[0] == "pending":
                d = self._json_body()
                if d.get("decision") not in ("allow", "deny"):
                    return self._json(400, {"error": "decision debe ser allow o deny"})
                code, res = answer_pending(parts[1], d["decision"], d.get("reason", ""))
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "sessions":
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if parts[2] == "send":
                    d = self._json_body()
                    code, res = send_to_session(s, d.get("text", ""), list(d.get("attachments") or []))
                    src, link_to = d.get("from"), d.get("link_to")
                    kind = "native" if d.get("native") else "send"
                    if code == 200 and link_to and link_to in sessions and link_to != s["session_id"]:
                        # canal nativo: se le habla a A para que abra conversacion con B; la flecha es A -> B
                        add_link(s["session_id"], link_to, d.get("text", ""), kind)
                    elif code == 200 and src and src in sessions and src != s["session_id"]:
                        add_link(src, s["session_id"], d.get("text", ""), kind)
                    return self._json(code, res)
                if parts[2] == "attach":
                    name = urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin")
                    data = self._body()
                    if not data:
                        return self._json(400, {"error": "cuerpo vacio"})
                    path = save_attachment(s["session_id"], name, data)
                    return self._json(200, {"path": path, "bytes": len(data)})
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            return self._json(500, {"error": str(e)})

    def do_DELETE(self):
        parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p]
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo"})
        if not self._authed():
            return self._json(401, {"error": "hace falta iniciar sesion"})
        if len(parts) == 2 and parts[0] == "sessions":
            drop_session(parts[1], "borrada desde la UI")
            return self._json(200, {"ok": True})
        if len(parts) == 2 and parts[0] in ("links", "rules"):
            log(f"{parts[0][:-1]} {parts[1]} borrada desde la UI ({self._client_ip()})")
            (links if parts[0] == "links" else rules).remove(lambda x: x["id"] == parts[1])
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "ruta desconocida"})

    def _file(self, path: str, ctype: str, cache: str = "no-store") -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._json(404, {"error": f"no encuentro {path}"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _sse(self) -> None:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with lock:
            clients.append(q)
            snapshot = {"type": "snapshot", "sessions": list(sessions.values()), "pending": public_pending(),
                        "links": links.snapshot(), "rules": rules.snapshot()}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        # chunked explicito: sin esto, cloudflared (y cualquier proxy HTTP/1.1) no sabe donde
        # termina la respuesta y la retiene entera; el navegador directo la toleraba igual
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(payload: bytes) -> None:
            self.wfile.write(f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n")
            self.wfile.flush()

        try:
            chunk(f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n".encode("utf-8"))
            while True:
                try:
                    data = q.get(timeout=15)
                    chunk(f"data: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    # evento real, no comentario: el navegador lo cuenta como "el stream sigue vivo"
                    chunk(b'data: {"type": "ping"}\n\n')
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)


# --- arranque ---------------------------------------------------------------------------

def load_sessions() -> None:
    for p in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                s = json.load(f)
            s.setdefault("hooked", s.get("source") == "hook")
            s.setdefault("pending_id", None)
            if not procs.agent_alive(s.get("pid")):
                # sesion de una corrida anterior sin proceso: se muestra muerta y se va sola
                s["alive"] = False
                s["dead_since"] = s.get("dead_since") or now()
                s["state"] = "muerta"
            sessions[s["session_id"]] = s
        except (OSError, ValueError, KeyError):
            continue


def clean_attachments() -> None:
    cutoff = time.time() - ATTACH_MAX_DAYS * 86400
    for p in glob.glob(os.path.join(ADJUNTOS, "*", "*")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass


def tunnel_loop(port: int) -> None:
    """Camino A (§7.6.2): cloudflared publica 127.0.0.1:<port> en una URL https de trycloudflare.
    Solo se levanta si hay login configurado; sin auth.json no se expone nada."""
    global remote_url
    import re
    if not os.path.exists(CLOUDFLARED):
        log(f"--remote: no encuentro {CLOUDFLARED} (winget install Cloudflare.cloudflared)")
        return
    if not auth.configured():
        log("--remote: esperando el alta del acceso (boton 'Acceso remoto' en la UI) para levantar el tunel")
        while not auth.configured():
            time.sleep(3)
    while True:
        remote_url = None
        try:
            # --protocol http2: con QUIC el SSE (/events) llegaba con cabeceras pero sin cuerpo
            p = subprocess.Popen([CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate",
                                  "--protocol", "http2"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", creationflags=0x08000000)  # CREATE_NO_WINDOW
        except OSError as e:
            log(f"--remote: cloudflared no arranca: {e}")
            return
        for line in p.stderr or []:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and remote_url != m.group(0):
                remote_url = m.group(0)
                log(f"tunel: {remote_url}")
            elif any(k in line for k in ("ERR", "error", "Registered", "Connection")):
                log(f"cloudflared: {line.strip()[:200]}")
        p.wait()
        log(f"cloudflared termino (codigo {p.returncode}); reintento en 10 s")
        time.sleep(10)


def main() -> int:
    ap = argparse.ArgumentParser(prog="lienzo-server")
    ap.add_argument("--port", type=int, default=7321)
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--sweep-every", type=float, default=30.0)
    ap.add_argument("--remote", action="store_true", help="publicar por cloudflared (exige login configurado)")
    a = ap.parse_args()
    for d in (EVENTS, PENDING, ANSWERS, ADJUNTOS, SESSIONS):
        os.makedirs(d, exist_ok=True)
    load_sessions()
    links.load(lambda l: l.get("from") in sessions and l.get("to") in sessions)
    rules.load(lambda r: r.get("to") in sessions and (not r.get("from") or r["from"] in sessions))
    clean_attachments()
    if not a.no_sweep:
        sweep_once()
    threading.Thread(target=consume_events, daemon=True).start()
    threading.Thread(target=scan_pending, daemon=True).start()
    threading.Thread(target=liveness_loop, args=(0 if a.no_sweep else a.sweep_every,), daemon=True).start()
    threading.Thread(target=screen_loop, daemon=True).start()
    threading.Thread(target=rules_loop, daemon=True).start()
    if a.remote:
        threading.Thread(target=tunnel_loop, args=(a.port,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    log(f"lienzo-server en http://127.0.0.1:{a.port}  sesiones={len(sessions)}  login={'si' if auth.configured() else 'no'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
