"""Registro de sesiones: tarjetas, estados (corriendo / te_necesita / termino / muerta), eventos de
los hooks, lectura de transcripciones, titulos, barrido de procesos, liveness, envio por inyeccion y
pantalla. Todo el estado vive en state.py. Las reglas ("cuando termine", "a las HH:MM") estan en
rules.py, que importa este modulo; para no cerrar el ciclo, este modulo las llama por dos ganchos que
rules.py rellena al importarse: on_turn_end(sid) y on_limit_notice(s)."""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import secrets
import subprocess
import threading
import time
import traceback

import procs
import state
import transcripts
from state import (ADJUNTOS, ANSWERS, ATTACH_MAX_DAYS, DEAD_GRACE_S, EVENTS, HERE, HOME, LONG_TEXT, NEEDS_NOTIFICATIONS,
                   PENDING, PYTHON, STALE_SESSION_H, STATES, atomic_write, claude_slug, links, lock, now, parse_ts,
                   pending, repo_of, rules, sessions, short, transcript_stat)

last_sweep = 0.0

# ganchos que rellena rules.py: cierre de turno (reglas "cuando termine") y aviso de limite de uso
# con hora (regla automatica "Continuar"). Sin rules.py cargado no pasa nada.
on_turn_end = lambda sid: None          # noqa: E731
on_limit_notice = lambda s: None        # noqa: E731


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


USELESS_TITLE_WORDS = ("adjunto", "archivo")
USELESS_TITLE_RE = re.compile(r"^mensaje del \d{6,8}$")


def bad_title(title) -> bool:
    """Titulos que no dicen nada: vacio, el XML de un mensaje entre sesiones, o el ai-title que
    Claude arma cuando el pedido llego como adjunto ('Leer archivo adjunto', 'Archivo adjunto
    análisis', 'Mensaje del 20260905')."""
    t = (title or "").strip().lower()
    return not t or t.startswith("<") or any(w in t for w in USELESS_TITLE_WORDS) or bool(USELESS_TITLE_RE.match(t))


def clean_prompt(prompt: str) -> str:
    """Pedido tal como se muestra: mensaje entre sesiones sin el XML ('de lienzo-b7: ...'),
    adjunto desenvuelto (contenido del .md en vez de 'Leé el archivo adjunto...')."""
    pm = transcripts.peer_message(prompt or "")
    if pm:
        return f"de {pm[0]}: {pm[1]}"
    return unwrap_attachment(prompt)


def prompt_title(s: dict) -> str | None:
    """Primera linea del ultimo pedido, si sirve de titulo (no el envoltorio del adjunto ni XML)."""
    p = (s.get("last_prompt") or "").strip()
    if not p or p.startswith(ATTACH_WRAPPER) or p.startswith("<"):
        return None
    first = next((l.strip() for l in p.splitlines() if l.strip()), "")
    return short(first, 60) if first else None


def choose_title(s: dict, transcript_title: str | None) -> None:
    """Regla unica del titulo automatico. El puesto a mano (title_source 'user') no se toca.
    Gana el ai-title / thread_name de la transcripcion, salvo que sea inutil (bad_title) y haya
    un pedido del que sacar la primera linea: el caso de los pedidos que llegan como adjunto."""
    if s.get("title_source") == "user":
        return
    lp = s.get("last_prompt") or ""
    if lp.startswith(ATTACH_WRAPPER) or "<cross-session-message" in lp:
        s["last_prompt"] = short(clean_prompt(lp), 500)   # tarjetas viejas: limpiar con el parser actual
    pt = prompt_title(s)
    cur, src = s.get("title"), s.get("title_source")
    if transcript_title is None and src == "transcript" and not bad_title(cur):
        return   # el ai-title quedo fuera de la cola leida: se conserva el que ya teniamos
    if transcript_title and (not bad_title(transcript_title) or not pt):
        s["title"], s["title_source"] = transcript_title, "transcript"
    elif pt:
        s["title"], s["title_source"] = pt, "prompt"
    elif bad_title(cur):
        s["title"], s["title_source"] = None, None


def tool_detail(tool_name: str | None, tool_input) -> str:
    if not isinstance(tool_input, dict):
        return short(str(tool_input or ""), 200)
    for k in ("command", "cmd", "file_path", "notebook_path", "url", "pattern", "description"):
        if tool_input.get(k):
            return short(str(tool_input[k]), 300)
    return short(json.dumps(tool_input, ensure_ascii=False), 300)


# --- registro de sesiones -------------------------------------------------------

def save_session(s: dict) -> None:
    atomic_write(os.path.join(state.SESSIONS, f"{s['session_id']}.json"), json.dumps(s, ensure_ascii=False, indent=1))


def add_link(src: str | None, dst: str, text: str, kind: str = "send", rule_id: str | None = None) -> None:
    """kind: send (inyeccion manual entre sesiones) | native (canal Claude<->Claude por SendMessage) |
    rule (nacido de una regla 'cuando termine' / 'a las HH:MM'; trae rule_id) | user (lo que el
    usuario escribio desde el SendBox del lienzo: from None, solo se ve en la pestana Conexiones)."""
    link = {"id": secrets.token_hex(6), "from": src, "to": dst, "ts": now(), "text": short(text, 160), "kind": kind}
    if rule_id:
        link["rule_id"] = rule_id
    links.add(link)

def limit_until_of(turn: dict) -> str | None:
    """Si el turno termino con un aviso de limite de uso con hora ("try again at 7:57 PM"),
    esa hora en ISO local; la referencia es cuando se escribio el aviso, no ahora."""
    err = turn.get("error")
    if not err:
        return None
    ref = None
    for k in ("ts_end", "ts_start"):
        raw = turn.get(k)
        if not raw:
            continue
        try:
            ref = dt.datetime.fromisoformat(str(raw))
            break
        except ValueError:
            continue
    if ref is not None and ref.tzinfo is None:
        ref = ref.replace(tzinfo=dt.timezone.utc)
    at = transcripts.limit_reset(err, ref)
    return at.astimezone().isoformat(timespec="seconds") if at else None

def drop_session(sid: str, reason: str) -> None:
    with lock:
        s = sessions.pop(sid, None)
    if s is None:
        return
    links.remove(lambda l: sid in (l["from"], l["to"]))
    rules.remove(lambda r: sid in (r.get("from"), r["to"]))
    try:
        os.remove(os.path.join(state.SESSIONS, f"{sid}.json"))
    except OSError:
        pass
    state.log(f"tarjeta {sid[:8]} borrada ({reason})")
    state.broadcast({"type": "removed", "session_id": sid})

def continues_session(old: dict, ev: dict) -> bool:
    """El mismo proceso de Claude Code (mismo pid, misma consola) cambio de session_id: /clear o
    resume disparan SessionEnd de la vieja y SessionStart de la nueva. Medido el 2026-09-05: la
    tarjeta 7bb119b6 (pid 26356) recibio SessionEnd a las 20:32 y desde las 20:53 los eventos de
    43e4160d con ese pid se rechazaban; la nueva quedo sin pid, la vieja 'corriendo' para siempre y
    su regla on_stop nunca disparo. Se reconoce porque la duena tuvo SessionEnd, o porque la nueva
    trae una transcripcion propia que existe y la duena no emitio nada desde entonces. Lo que NO es
    continuacion: una prueba manual del hook con un session_id inventado y el pid de una sesion
    real, que sigue viva, sin SessionEnd y sin transcripcion propia."""
    if old.get("last_event") == "SessionEnd":
        return True
    tp = ev.get("transcript_path")
    if not tp or tp == old.get("transcript_path") or not os.path.isfile(tp):
        return False
    t_old, t_new = parse_ts(old.get("last_event_ts")), parse_ts(ev.get("host_ts"))
    return t_old is None or (t_new is not None and t_new > t_old)


def continue_session(old: dict, new: dict) -> None:
    """La sesion nueva hereda el pid de la vieja y todo lo que la apuntaba: reglas y links donde la
    vieja era origen o destino pasan al sid nuevo, y la vieja se da de baja."""
    old_sid, new_sid = old["session_id"], new["session_id"]
    with lock:
        n_rules = n_links = 0
        for r in rules.items:
            for k in ("from", "to"):
                if r.get(k) == old_sid:
                    r[k] = new_sid
                    n_rules += 1
        for l in links.items:
            for k in ("from", "to"):
                if l.get(k) == old_sid:
                    l[k] = new_sid
                    n_links += 1
        if n_rules:
            rules.save()
        if n_links:
            links.save()
        for k in ("pid", "agent_exe", "no_console", "in_vscode"):
            if old.get(k) is not None:
                new[k] = old[k]
        if not new.get("cwd") and old.get("cwd"):
            new["cwd"], new["repo"] = old["cwd"], old.get("repo") or repo_of(old["cwd"])
        drop_session(old_sid, "continuada")     # las reglas y links ya no la nombran: no borra nada
    state.log(f"sesion {old_sid[:8]} continua como {new_sid[:8]} (pid {new.get('pid')}; "
        f"{n_rules} reglas y {n_links} links re-apuntados)")
    if n_rules:
        rules.publish()
    if n_links:
        links.publish()


def new_session(sid: str, agent: str, source: str) -> dict:
    return {
        "session_id": sid, "agent": agent, "pid": None, "agent_exe": None, "cwd": None, "repo": "?",
        "branch": None, "title": None, "transcript_path": None,
        "state": "termino", "state_since": now(), "needs": None,
        "last_prompt": "", "last_reply": "", "started": now(),
        "last_event": None, "last_event_ts": None, "alive": True, "dead_since": None,
        "source": source, "hooked": source == "hook", "pending_id": None,
        "typing": False,
    }


def set_state(s: dict, new: str) -> None:
    """Cambia el estado de la tarjeta (el parametro no se llama `state` para no tapar el modulo)."""
    if new not in STATES:
        state.log(f"estado invalido {new!r} para {s.get('session_id', '?')[:8]}: ignorado")
        return
    prev = s.get("state")
    if prev not in STATES:
        prev = None       # tarjeta con estado roto: se toma el nuevo sin disparar cierre de turno
    if prev != new:
        s["state"] = new
        s["state_since"] = now()
        if new == "termino" and prev in ("corriendo", "te_necesita"):
            # cierre de turno: reglas "cuando termine" (en otro hilo, el envio tarda)
            threading.Thread(target=on_turn_end, args=(s["session_id"],), daemon=True).start()
    if new != "te_necesita":
        s["needs"] = None


def touch(s: dict) -> None:
    save_session(s)
    state.broadcast({"type": "session", "session": s})

STALE_STOP_S = 5.0     # timeout de los hooks: un Stop de otro pedido mas viejo que esto ya no es "tardio"


def stale_stop(s: dict, ev: dict) -> bool:
    """Un Stop que llega despues del UserPromptSubmit del pedido siguiente. Pasa con los pedidos que
    quedan encolados mientras el agente corre: al cerrar el turno, Claude Code escribe turn_duration
    y 60 ms despues arranca el pedido encolado (medido en 599a7e3e, 23:41:53.135 y .195 UTC); los
    dos hooks son async y corren a la vez, asi que el evento Stop del turno viejo puede quedar
    escrito despues del UserPromptSubmit del nuevo. Aplicarlo dejaba la tarjeta en 'termino'
    durante todo un turno de 13 minutos. Se reconoce por el prompt_id (distinto del pedido en
    curso) y por la cercania en el tiempo con ese pedido."""
    pid_ev, pid_cur = ev.get("prompt_id"), s.get("prompt_id")
    if not pid_ev or not pid_cur or pid_ev == pid_cur:
        return False
    t_ev, t_cur = parse_ts(ev.get("host_ts")), parse_ts(s.get("prompt_ts"))
    if t_ev is None or t_cur is None:
        return False
    return abs((t_ev - t_cur).total_seconds()) <= STALE_STOP_S


def transcript_state(s: dict, t: dict) -> str | None:
    """Estado que dicta el ultimo turno de la transcripcion cuando contradice al de los hooks, o None
    si no hay que tocar nada. Solo entre corriendo y termino (te_necesita y muerta son de los hooks
    y de la liveness), y solo si la actividad de la transcripcion es posterior al cambio de estado
    con 2 s de margen: asi un Stop que se perdio (o llego al reves, ver stale_stop) se corrige en la
    siguiente lectura, y la lectura que cae entre el texto final y el turn_duration no hace ruido."""
    if s["state"] not in ("corriendo", "termino") or s.get("needs"):
        return None
    want = "termino" if t.get("ended") else "corriendo"
    if want == s["state"]:
        return None
    last, since = parse_ts(t.get("ts_end") or t.get("ts_start")), parse_ts(s.get("state_since"))
    if last is None or since is None or (last - since).total_seconds() < 2.0:
        return None
    return want


def refresh_from_transcript(s: dict, force_state: bool = False) -> bool:
    """Titulo, rama, ultimo pedido/respuesta desde la transcripcion. Si la sesion no tiene
    hooks (o force_state), tambien el estado corriendo/termino. Devuelve si cambio algo."""
    path = s.get("transcript_path")
    if not path or not os.path.exists(path):
        return False
    try:
        r = transcripts.turns(s["agent"], path, 1)
    except Exception as e:  # noqa: BLE001
        state.log(f"transcripcion {path}: {e}")
        return False
    meta, ts = r["meta"], r["turns"]
    before = json.dumps({k: s.get(k) for k in ("title", "branch", "last_prompt", "last_reply", "state", "cwd", "last_error", "limit_until", "continue_scheduled_for")})
    # titulo de la transcripcion: ai-title de Claude, o thread_name del indice de Codex (solo se
    # busca si el que hay no sirve); la regla de que gana esta en choose_title, despues del turno
    tt = meta.get("title")
    if not tt and s["agent"] == "codex" and s.get("title_source") != "user" and (
            bad_title(s.get("title")) or s.get("title_source") != "transcript"):
        tt = transcripts.codex_title(s["session_id"])
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
            # el pedido y la respuesta final ya vienen por hook (UserPromptSubmit / Stop); de la
            # transcripcion se toma "usando X" mientras corre, y el estado solo cuando los hooks
            # lo dejaron al reves (Stop tardio de un pedido encolado, evento perdido)
            want = transcript_state(s, t)
            if want:
                if want == "corriendo" and t.get("prompt") and not t["prompt"].startswith("(turno anterior"):
                    s["last_prompt"] = short(clean_prompt(t["prompt"]), 500)
                state.log(f"{s['session_id'][:8]}: la transcripcion dice {want} y los hooks {s['state']} "
                    f"(ultimo evento {s.get('last_event')}); corregido")
                set_state(s, want)
            if s["state"] == "corriendo" and not t.get("ended") and tools:
                s["last_reply"] = f"usando {tools[-1]['name']}"
        else:
            if t.get("prompt") and not t["prompt"].startswith("(turno anterior"):
                s["last_prompt"] = short(clean_prompt(t["prompt"]), 500)
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
        # limite de uso con hora de vuelta: la tarjeta ofrece programar "Continuar" y, con
        # auto_continue en config.json, queda programado solo (un disparo por aviso)
        s["limit_until"] = limit_until_of(t)
        if s["limit_until"]:
            on_limit_notice(s)
    choose_title(s, tt)
    after = json.dumps({k: s.get(k) for k in ("title", "branch", "last_prompt", "last_reply", "state", "cwd", "last_error", "limit_until", "continue_scheduled_for")})
    return before != after


def set_title(s: dict, title: str) -> None:
    """Titulo puesto por el usuario desde la UI. Vacio: vuelve a la logica automatica
    (ai-title / thread_name de la transcripcion, o la primera linea del ultimo pedido)."""
    title = short(title, 120)
    if title:
        s["title"] = title
        s["title_source"] = "user"
        return
    s["title"] = None
    s["title_source"] = None
    refresh_from_transcript(s)
    if s.get("title") is None:      # sin transcripcion: solo queda el pedido
        choose_title(s, None)


def recalc_title(s: dict) -> bool:
    """Al arrancar: titulo y pedido con la regla actual (tarjetas viejas con el XML de un mensaje
    entre sesiones, o con el ai-title 'Leer archivo adjunto'). Devuelve si cambio el titulo."""
    if s.get("title_source") == "user":
        return False
    before = s.get("title")
    tt = None
    path = s.get("transcript_path")
    if path and os.path.exists(path):
        try:
            tt = transcripts.turns(s["agent"], path, 1)["meta"].get("title")
        except Exception as e:  # noqa: BLE001
            state.log(f"transcripcion {path}: {e}")
    if not tt and s.get("agent") == "codex":
        tt = transcripts.codex_title(s["session_id"])
    choose_title(s, tt)
    return s.get("title") != before

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
        if s.get("state") not in STATES:
            s["state"], s["state_since"] = "termino", now()
        pid = ev.get("pid")
        if pid and procs.agent_alive(pid):
            owner = None
            if s.get("pid") != pid:
                # otra tarjeta con el mismo pid: si es un placeholder del barrido (source sweep o
                # id "pid-N") es la misma sesion y se reemplaza; si es una sesion con hooks que
                # termino (SessionEnd por /clear o resume) o dejo de emitir y esta trae su propia
                # transcripcion, el proceso siguio con otro session_id y esta la continua (hereda
                # pid, reglas y links); si es una sesion real que sigue viva, el pid ya tiene
                # duena y este evento no se lo lleva (una prueba manual del hook con otro
                # session_id no debe borrar la sesion real ni sus reglas)
                for other_sid, other in list(sessions.items()):
                    if other_sid != sid and other.get("pid") == pid:
                        if other.get("source") == "sweep" or other_sid.startswith("pid-"):
                            drop_session(other_sid, "duplicada por barrido")
                        elif continues_session(other, ev):
                            continue_session(other, s)
                        else:
                            owner = other_sid
                if owner:
                    state.log(f"pid {pid} ya pertenece a {owner[:8]}; evento {name} de {sid[:8]} no lo toma")
            if not owner:
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
            # pedido en curso: con esto se reconoce un Stop tardio del pedido anterior (stale_stop)
            s["prompt_id"] = ev.get("prompt_id")
            s["prompt_ts"] = s["last_event_ts"]
            if not transcripts.is_system_prompt(ev.get("prompt", "")):
                s["last_prompt"] = short(clean_prompt(ev.get("prompt", "")), 500)
                # sin ai-title todavia (o con uno inutil): la tarjeta se titula con la primera linea
                # del pedido; un ai-title que sirva lo pisa despues (refresh_from_transcript)
                first = prompt_title(s)
                if first and s.get("title_source") != "user" and (bad_title(s.get("title")) or s.get("title_source") == "prompt"):
                    s["title"] = first
                    s["title_source"] = "prompt"
            s["pending_id"] = None
            s["typing"] = False   # lo que habia en la caja ya se mando; screen_loop lo confirma en 5 s
        elif name == "Stop":
            if stale_stop(s, ev):
                state.log(f"Stop tardio de {sid[:8]} (pedido {str(ev.get('prompt_id'))[:8]}, ya corre "
                    f"{str(s.get('prompt_id'))[:8]}): la tarjeta sigue corriendo")
            else:
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
                state.log(f"evento {n} fallo:\n{traceback.format_exc()}")
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
                state.broadcast({"type": "pending", "pending": public_pending()})
        except Exception:  # noqa: BLE001
            state.log(traceback.format_exc())
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
    state.log(f"permiso {request_id[:8]} -> {decision} ({d.get('tool_name')})")
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
                    os.remove(os.path.join(state.SESSIONS, f"{s['session_id']}.json"))
                except OSError:
                    pass
                state.broadcast({"type": "removed", "session_id": s["session_id"]})
                s["session_id"] = sid
                sessions[sid] = s
            s["transcript_path"] = tpath
            s["cwd"] = s.get("cwd") or cwd
            s["repo"] = repo_of(s["cwd"])
            if s.get("title_source") != "user":
                s["title"] = None
            refresh_from_transcript(s)
            touch(s)
            state.log(f"barrido: pid {s['pid']} ahora con transcripcion {os.path.basename(tpath)}")
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
            state.log(f"barrido: {p['agent']} pid {p['pid']} cwd={cwd} sid={s['session_id'][:8]}")


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
                        state.broadcast({"type": "transcript", "session_id": s["session_id"], "size": st.st_size})
                if changed:
                    touch(s)
            if sweep_every and time.time() - last_sweep > sweep_every:
                sweep_once()
        except Exception:  # noqa: BLE001
            state.log(traceback.format_exc())
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
    orig = text.strip()      # lo que escribio el usuario: es lo que se cuenta y lo que muestra la tarjeta
    if len(text) > LONG_TEXT or "\n" in orig:
        path = save_attachment(s["session_id"], "mensaje.md", text.encode("utf-8"))
        attachments = [path] + list(attachments)
        text = ATTACH_WRAPPER
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
    state.log(f"send {s['session_id'][:8]} pid {s['pid']}: {out}")
    if out.get("ok"):
        if orig:
            # send.py cuenta lo tipeado en la consola, que con un mensaje largo es el envoltorio
            # 'Leé el archivo adjunto...' (143); el toast y la tarjeta hablan del mensaje real
            out["chars"] = len(orig)
        s["last_prompt"] = short(orig, 500) if orig else short(clean_prompt(final), 500)
        if s.get("last_event") != "SessionEnd":
            # tras SessionEnd la consola ya es de otra sesion (/clear, resume): lo que se tipea
            # llega a esa, y esta tarjeta no vuelve a 'corriendo' (la continua apply_event)
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
    Con la sesion ociosa (termino, o "te necesita" por idle) el texto es una sugerencia de Claude
    y va a la tarjeta; con la sesion ocupada (corriendo, o te_necesita por permiso) es alguien
    tipeando y solo se marca `typing`, para que el lienzo no le escriba encima."""
    while True:
        try:
            with lock:
                items = [s for s in sessions.values()
                         if s.get("agent") == "claude" and s.get("pid") and s.get("alive") and not s.get("orphan")]
            for s in items:
                r = read_screen(s["pid"])
                area = r.get("area") if r.get("ok") else None
                sug, typing = None, False
                # medido: "❯ Guardá la revisión en docs/revision-backend.md" con la sesion en idle_prompt
                idle = s["state"] == "termino" or (s["state"] == "te_necesita" and (s.get("needs") or {}).get("kind") == "idle")
                if area and not area["placeholder"]:
                    if idle:
                        sug = short(area["input"], 300)
                    else:
                        typing = True
                if s.get("suggestion") != sug or bool(s.get("typing")) != typing:
                    s["suggestion"] = sug
                    s["typing"] = typing
                    touch(s)
        except Exception:  # noqa: BLE001
            state.log(traceback.format_exc())
        time.sleep(5)

# --- arranque ---------------------------------------------------------------------------

def load_sessions() -> tuple[int, int]:
    """Carga sessions/*.json. Devuelve (purgadas, retituladas): purga las sin proceso vivo y sin
    eventos (o arranque) hace mas de STALE_SESSION_H horas (las demas sin proceso quedan 'muerta'
    y se van solas a los 60 s), y recalcula el titulo de las que quedan con la regla actual."""
    limit = dt.datetime.now().astimezone() - dt.timedelta(hours=STALE_SESSION_H)
    purged = 0
    for p in glob.glob(os.path.join(state.SESSIONS, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                s = json.load(f)
            s.setdefault("hooked", s.get("source") == "hook")
            s.setdefault("pending_id", None)
            s.setdefault("typing", False)
            if s.get("state") not in STATES:
                s["state"], s["state_since"] = "termino", s.get("state_since") or now()
            if not procs.agent_alive(s.get("pid")):
                ref = s.get("last_event_ts") or s.get("started")
                try:
                    stale = not ref or dt.datetime.fromisoformat(ref) < limit
                except ValueError:
                    stale = True
                if stale:
                    os.remove(p)
                    purged += 1
                    continue
                # sesion de una corrida anterior sin proceso: se muestra muerta y se va sola
                s["alive"] = False
                s["dead_since"] = s.get("dead_since") or now()
                s["state"] = "muerta"
            sessions[s["session_id"]] = s
        except (OSError, ValueError, KeyError):
            continue
    retitled = 0
    for s in list(sessions.values()):
        if recalc_title(s):
            retitled += 1
            save_session(s)
    return purged, retitled


def clean_attachments() -> None:
    cutoff = time.time() - ATTACH_MAX_DAYS * 86400
    for p in glob.glob(os.path.join(ADJUNTOS, "*", "*")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass
