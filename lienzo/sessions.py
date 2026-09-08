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

import backend
import state
import tmux
import transcripts
from state import (
    ADJUNTOS,
    ANSWERS,
    ATTACH_MAX_DAYS,
    DEAD_GRACE_S,
    EVENTS,
    HERE,
    HOME,
    LONG_TEXT,
    NEEDS_NOTIFICATIONS,
    PENDING,
    PYTHON,
    STALE_SESSION_H,
    STATES,
    atomic_write,
    claude_slug,
    links,
    lock,
    now,
    parse_ts,
    pending,
    repo_of,
    rules,
    sessions,
    short,
    transcript_stat,
)

last_sweep = 0.0

# ganchos que rellena rules.py: cierre de turno (reglas "cuando termine") y aviso de limite de uso
# con hora (regla automatica "Continuar"). Sin rules.py cargado no pasa nada.
on_turn_end = lambda sid: None
on_limit_notice = lambda s: None


ATTACH_WRAPPER = "Leé el archivo adjunto y respondé:"


def attachment_path(prompt: str) -> str | None:
    """Ruta del .md que viaja en 'Leé el archivo adjunto y respondé: Adjunto: <ruta>', si existe."""
    p = (prompt or "").strip()
    if not p.startswith(ATTACH_WRAPPER):
        return None
    for part in p.split("Adjunto: ")[1:]:
        path = part.strip()
        if path.lower().endswith(".md") and os.path.isfile(path):
            return path
    return None


def unwrap_attachment(prompt: str) -> str:
    """Un texto largo viaja como 'Leé el archivo adjunto y respondé: Adjunto: <ruta>'. En la
    tarjeta se muestra el contenido del adjunto, no el envoltorio."""
    path = attachment_path(prompt)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read(600)
        except OSError:
            pass
    return prompt


HEADING_RE = re.compile(r"^#{1,6}\s*(.*?)\s*#*\s*$")


def attachment_title(s: dict) -> str | None:
    """Pedido que llego como adjunto: el titulo es el primer encabezado markdown del .md (sin los
    '#'), o su primera linea no vacia. Le gana al ai-title, que para estos pedidos no sirve
    ('Mensaje 20260906'). La ruta queda en last_attachment (o en el envoltorio de una tarjeta
    vieja que todavia lo tenga en last_prompt)."""
    path = s.get("last_attachment") or attachment_path(s.get("last_prompt") or "")
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read(4000).splitlines()]
    except OSError:
        return None
    heading = next((m.group(1) for l in lines if (m := HEADING_RE.match(l)) and m.group(1)), None)
    if heading:
        return short(heading, 60)
    first = next((l for l in lines if l), "")
    # la cabecera de un informe recibido ("Mensaje de X (claude) sobre '…':") no es titulo: si el
    # adjunto empieza asi, no hay titulo que sacar de el
    return None if not first or bad_title(first) else short(first, 60)


def set_last_prompt(s: dict, raw: str) -> None:
    """Guarda el ultimo pedido tal como se muestra y, si llego como adjunto, la ruta del .md."""
    s["last_prompt"] = short(clean_prompt(raw), 500)
    s["last_attachment"] = attachment_path(raw)


USELESS_TITLE_WORDS = ("adjunto", "archivo")
# "Mensaje de lienzo (claude) sobre '…':" es la cabecera de un informe que otra sesion le mando a esta:
# tampoco sirve de titulo (la coordinadora se llamaria como el ultimo informe recibido)
USELESS_TITLE_RE = re.compile(r"^(mensaje(\s+\d+|\s+del\b.*|\s+de\s+.*\bsobre\b.*)?|encargo)$")


def bad_title(title) -> bool:
    """Titulos que no dicen nada: vacio, el XML de un mensaje entre sesiones, o el ai-title que
    Claude arma cuando el pedido llego como adjunto ('Leer archivo adjunto', 'Archivo adjunto
    análisis', 'Mensaje', 'Mensaje 20260906', 'Mensaje del 20260905', 'Encargo')."""
    t = " ".join((title or "").strip().lower().split())
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
    at = attachment_title(s)
    if at:
        return at
    p = (s.get("last_prompt") or "").strip()
    if not p or p.startswith((ATTACH_WRAPPER, "<")):
        return None
    first = next((l.strip() for l in p.splitlines() if l.strip()), "")
    m = HEADING_RE.match(first)
    if m and m.group(1):
        first = m.group(1)  # tarjeta vieja: el contenido del .md ya esta en last_prompt
    return short(first, 60) if first else None


def choose_title(s: dict, transcript_title: str | None) -> None:
    """Regla unica del titulo automatico. El puesto a mano (title_source 'user') no se toca.
    Gana el ai-title / thread_name de la transcripcion, salvo que sea inutil (bad_title) y haya
    un pedido del que sacar la primera linea: el caso de los pedidos que llegan como adjunto."""
    if s.get("title_source") == "user":
        return
    lp = s.get("last_prompt") or ""
    if lp.startswith(ATTACH_WRAPPER) or "<cross-session-message" in lp:
        set_last_prompt(s, lp)  # tarjetas viejas: limpiar con el parser actual
    at = attachment_title(s)
    if at:
        s["title"], s["title_source"] = at, "prompt"  # el pedido llego como adjunto: su encabezado manda
        return
    pt = prompt_title(s)
    cur, src = s.get("title"), s.get("title_source")
    if transcript_title is None and src == "transcript" and not bad_title(cur):
        return  # el ai-title quedo fuera de la cola leida: se conserva el que ya teniamos
    if transcript_title and (not bad_title(transcript_title) or not pt):
        s["title"], s["title_source"] = transcript_title, "transcript"
    elif pt:
        s["title"], s["title_source"] = pt, "prompt"
    elif bad_title(cur):
        s["title"], s["title_source"] = None, None


def tool_detail(tool_input) -> str:
    """Una linea que describa lo que la herramienta va a hacer, para el pedido de permiso."""
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
    ref = parse_ts(turn.get("ts_end")) or parse_ts(turn.get("ts_start"))
    at = transcripts.limit_reset(err, ref)
    return at.astimezone().isoformat(timespec="seconds") if at else None


def forget_session(sid: str) -> bool:
    """Saca la tarjeta de memoria y de disco; devuelve si existia. No toca links ni reglas ni avisa
    al front: eso lo pone cada quien. La usan el borrado de verdad (drop_session, que si borra sus
    conexiones) y el cambio de id de una tarjeta del barrido, que se las queda. Con el lock tomado."""
    if sessions.pop(sid, None) is None:
        return False
    # la firma (tamaño, mtime) de su transcripcion no le sirve a nadie mas: si queda, es una
    # entrada por cada tarjeta que existio desde que arranco el server, sin techo
    transcript_stat.pop(sid, None)
    try:
        os.remove(os.path.join(state.SESSIONS, f"{sid}.json"))
    except OSError:
        pass
    return True


def drop_session(sid: str, reason: str) -> None:
    with lock:
        if not forget_session(sid):
            return
    links.remove(lambda l: sid in (l["from"], l["to"]))
    rules.remove(lambda r: sid in (r.get("from"), r["to"]))
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

    def repoint(coll) -> int:
        """Las dos puntas de cada regla / link que nombraban a la vieja pasan al sid nuevo."""
        n = 0
        for x in coll.items:
            for k in ("from", "to"):
                if x.get(k) == old_sid:
                    x[k] = new_sid
                    n += 1
        if n:
            coll.save()
        return n

    with lock:
        n_rules, n_links = repoint(rules), repoint(links)
        for k in ("pid", "agent_exe", "no_console", "in_vscode", "coordinator"):
            if old.get(k) is not None:
                new[k] = old[k]
        if not new.get("cwd") and old.get("cwd"):
            new["cwd"], new["repo"] = old["cwd"], old.get("repo") or repo_of(old["cwd"])
        drop_session(old_sid, "continuada")  # las reglas y links ya no la nombran: no borra nada
    state.log(
        f"sesion {old_sid[:8]} continua como {new_sid[:8]} (pid {new.get('pid')}; "
        f"{n_rules} reglas y {n_links} links re-apuntados)"
    )
    if n_rules:
        rules.publish()
    if n_links:
        links.publish()


def new_session(sid: str, agent: str, source: str) -> dict:
    """Forma canonica de una tarjeta: TODO campo que la UI puede leer existe desde el arranque y con
    su tipo. Un campo que a veces esta y a veces no es lo que despues rompe el front: medido, de 6
    tarjetas reales `orphan` venia bool en 1 (las del barrido) y ausente en 5 (las de hooks), y lo
    mismo `in_vscode`, `no_console`, `suggestion` y `continue_scheduled_for`. Los `None` de aca son
    "todavia no se sabe" y son parte del tipo (`string | null` en web/src/types.ts); lo que no vale
    es la ausencia. load_sessions rellena con esto las tarjetas guardadas por versiones viejas."""
    return {
        "session_id": sid,
        "agent": agent,
        "pid": None,
        "target": None,  # backend tmux: el pane (%0, %1, ...) donde escribir/leer. None en Windows.
        "backend": None,  # "win32" | "tmux": que fuente maneja esta tarjeta. None = primario de la plataforma.
        "agent_exe": None,
        "cwd": None,
        "repo": "?",
        "branch": None,
        "title": None,
        "title_source": None,
        "transcript_path": None,
        "state": "termino",
        "state_since": now(),
        "needs": None,
        "last_prompt": "",
        "last_reply": "",
        "last_error": None,
        "started": now(),
        "last_event": None,
        "last_event_ts": None,
        "alive": True,
        "dead_since": None,
        "source": source,
        "hooked": source == "hook",
        "pending_id": None,
        "typing": False,
        "coordinator": False,
        "orphan": False,
        "in_vscode": False,
        "no_console": False,
        "suggestion": None,
        "limit_until": None,
        "continue_scheduled_for": None,
        "tool_count": 0,
        "last_files": [],
        "last_cmd": None,
        "tool_errors": 0,
    }


def set_state(s: dict, new: str) -> None:
    """Cambia el estado de la tarjeta (el parametro no se llama `state` para no tapar el modulo)."""
    if new not in STATES:
        state.log(f"estado invalido {new!r} para {s.get('session_id', '?')[:8]}: ignorado")
        return
    prev = s.get("state")
    if prev not in STATES:
        prev = None  # tarjeta con estado roto: se toma el nuevo sin disparar cierre de turno
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


STALE_STOP_S = 5.0  # timeout de los hooks: un Stop de otro pedido mas viejo que esto ya no es "tardio"


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


# nombres en minuscula de los dos agentes: Claude escribe con Edit/Write/Read/NotebookEdit y corre
# con Bash/PowerShell; Codex escribe con apply_patch, mira imagenes con view_image y corre con shell
FILE_TOOLS = ("edit", "write", "read", "notebookedit", "multiedit", "apply_patch", "update_file", "view_image")


CD_PREFIX_RE = re.compile(r'^\s*cd\s+(?:"[^"]*"|\S+)\s*(?:&&|;)\s*')
CMD_TOOLS = ("bash", "powershell", "shell", "run_terminal_cmd", "exec")


def tool_paths(inp: dict) -> list[str]:
    """Las rutas que toca una herramienta, en las formas que usan los dos agentes: `file_path` /
    `notebook_path` / `path` traen una sola (Claude, y view_image de Codex), y `paths` trae varias
    como [{path, type}] (apply_patch de Codex, que puede tocar varios archivos en un mismo bloque:
    medido, 53 bloques en ~/.codex, y por esta forma la tarjeta de Codex no mostraba ningun archivo)."""
    una = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if una:
        return [str(una)]
    return [str(p.get("path") or "" if isinstance(p, dict) else p) for p in (inp.get("paths") or [])]


def turn_activity(t: dict) -> dict:
    """Lo que la sesion viene haciendo en el turno, para la tarjeta: cuantas herramientas lleva, los
    ultimos archivos distintos que toco (del mas nuevo al mas viejo), el ultimo comando que corrio y
    cuantas herramientas volvieron con error. Sale de los bloques que ya tiene la transcripcion, en
    una sola pasada de atras para adelante; las claves son las de la tarjeta."""
    n = errors = 0
    files: list[str] = []
    cmd: str | None = None
    for b in reversed(t.get("blocks", [])):
        if b.get("kind") != "tool":
            continue
        n += 1
        errors += bool((b.get("result") or {}).get("is_error"))
        name = (b.get("name") or "").lower()
        inp = b.get("input") or {}
        if cmd is None and name in CMD_TOOLS:
            raw = str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " ")
            # el "cd <ruta larga> &&" del principio no dice nada y se come la linea entera
            raw = CD_PREFIX_RE.sub("", raw).strip()
            if raw:
                cmd = short(raw, 120)
        if name in FILE_TOOLS:
            for ruta in tool_paths(inp):
                if len(files) >= 3:
                    break
                base = os.path.basename(ruta.replace("\\", "/").rstrip("/"))
                if base and base not in files:
                    files.append(base)
    return {"tool_count": n, "last_files": files, "last_cmd": cmd, "tool_errors": errors}


def using_tool(t: dict) -> str | None:
    """ "usando Bash": la herramienta mas reciente del turno, para la tarjeta mientras corre."""
    b = next((b for b in reversed(t.get("blocks", [])) if b.get("kind") == "tool"), None)
    return f"usando {b['name']}" if b else None


def turn_prompt(t: dict) -> str | None:
    """Pedido del turno, o None si quedo fuera de la cola leida ("(turno anterior...")."""
    p = t.get("prompt")
    return p if p and not p.startswith("(turno anterior") else None


def turn_say(t: dict) -> str | None:
    """Lo que la sesion viene diciendo, para la tarjeta: el ultimo texto que escribio el agente en el
    turno. Mientras corre es el comentario entre dos herramientas ("Ahora parto refresh en dos:");
    cuando el turno cierra es la respuesta final. Si todavia no escribio nada, el nombre de la
    herramienta que esta usando. `transcripts` ya mantiene `final` = ultimo bloque de texto no vacio,
    y el pensamiento (kind "thinking") nunca pasa por ahi: a la tarjeta no va (el toggle
    "Pensamiento" del menu es para la conversacion). Lo de "que herramienta" es turn_activity.

    Va entero. Estaba recortado a 600 caracteres y la tarjeta no lo notaba --el CSS la corta en 6
    lineas de todos modos-- pero si lo notaban el boton de copiar de la tarjeta (copiaba media
    respuesta), la caja de reenviar y el freno del on_stop, que mira si la respuesta termina en
    pregunta: con el recorte terminaba en "…" y nunca frenaba. Medido el 2026-09-07 sobre 124
    turnos: 86 finales pasan de 600 caracteres (mediana 1125, maximo 7863) y el snapshot de
    /sessions pasa de 7,3 a 11,3 KB con cuatro sesiones abiertas."""
    return (t.get("final") or "").strip() or using_tool(t)


REFRESH_KEYS = (
    "title",
    "branch",
    "last_prompt",
    "last_reply",
    "state",
    "cwd",
    "last_error",
    "limit_until",
    "continue_scheduled_for",
    "tool_count",
    "last_files",
    "last_cmd",
    "tool_errors",
)


def apply_turn_hooked(s: dict, t: dict) -> None:
    """Sesion con hooks: el pedido y la respuesta final ya vinieron por UserPromptSubmit / Stop. De
    la transcripcion se toma lo que el agente viene diciendo mientras corre, y el estado solo
    cuando los hooks lo dejaron al reves (Stop tardio de un pedido encolado, evento perdido)."""
    want = transcript_state(s, t)
    if want:
        if want == "corriendo" and (p := turn_prompt(t)):
            set_last_prompt(s, p)
        state.log(
            f"{s['session_id'][:8]}: la transcripcion dice {want} y los hooks {s['state']} "
            f"(ultimo evento {s.get('last_event')}); corregido"
        )
        set_state(s, want)
    if s["state"] == "corriendo" and not t.get("ended"):
        s["last_reply"] = turn_say(t) or s["last_reply"]


def apply_turn_unhooked(s: dict, t: dict) -> None:
    """Sesion sin hooks (o refresco forzado): la transcripcion es la unica fuente, y de ella sale
    tambien el reparto corriendo/termino. `muerta` la dicta la liveness y `te_necesita` los hooks:
    ninguno de los dos se pisa desde aca."""
    if p := turn_prompt(t):
        set_last_prompt(s, p)
    if t.get("final") or not t.get("ended"):
        s["last_reply"] = turn_say(t) or s["last_reply"]
    if s["state"] != "muerta" and not s.get("needs"):
        set_state(s, "termino" if t.get("ended") else "corriendo")


def apply_turn(s: dict, t: dict, force_state: bool) -> None:
    """Vuelca el ultimo turno de la transcripcion a la tarjeta: actividad de adentro, pedido y
    respuesta, estado (solo si la sesion no tiene hooks, o force_state) y el error del turno."""
    # lo que pasa adentro, para la tarjeta: cuanto lleva hecho y sobre que archivos
    s.update(turn_activity(t))
    if s.get("hooked") and not force_state:
        apply_turn_hooked(s, t)
    else:
        apply_turn_unhooked(s, t)
    # error del turno (Codex: limite de uso, abortado; Claude: no aplica hoy) va aparte, en rojo
    s["last_error"] = short(t.get("error") or "", 300) or None
    if s["last_error"] and not t.get("final"):
        s["last_reply"] = s["last_error"]
    # limite de uso con hora de vuelta: la tarjeta ofrece programar "Continuar" y, con
    # auto_continue en config.json, queda programado solo (un disparo por aviso)
    s["limit_until"] = limit_until_of(t)
    if s["limit_until"]:
        on_limit_notice(s)


def read_transcript(s: dict) -> dict | None:
    """Lee y parsea la transcripcion, y de paso resuelve el titulo que trae. Es lo caro del refresco
    (medido: 22 ms de mediana y 48 ms el peor caso sobre 2 MB de cola), asi que corre SIN el lock:
    solo lee de la tarjeta, no le escribe nada. None si no hay transcripcion o no se pudo leer."""
    path = s.get("transcript_path")
    if not path or not os.path.exists(path):
        return None
    try:
        r = transcripts.turns(s["agent"], path, 1)
    except Exception as e:
        state.log(f"transcripcion {path}: {e}")
        return None
    # titulo de la transcripcion: ai-title de Claude, o thread_name del indice de Codex (solo se
    # busca si el que hay no sirve); la regla de que gana esta en choose_title, despues del turno
    tt = r["meta"].get("title")
    if (
        not tt
        and s["agent"] == "codex"
        and s.get("title_source") != "user"
        and (bad_title(s.get("title")) or s.get("title_source") != "transcript")
    ):
        tt = transcripts.codex_title(s["session_id"])
    r["title"] = tt
    return r


def apply_transcript(s: dict, r: dict, force_state: bool = False) -> bool:
    """Vuelca a la tarjeta lo que read_transcript ya parseo. Escribe en el dict: va CON el lock
    tomado. Devuelve si cambio algo."""
    meta, ts = r["meta"], r["turns"]
    before = json.dumps({k: s.get(k) for k in REFRESH_KEYS})
    if meta.get("branch"):
        s["branch"] = meta["branch"]
    if meta.get("cwd") and not s.get("cwd"):
        s["cwd"] = meta["cwd"]
        s["repo"] = repo_of(s["cwd"])
    if ts:
        apply_turn(s, ts[-1], force_state)
    choose_title(s, r["title"])
    return before != json.dumps({k: s.get(k) for k in REFRESH_KEYS})


def refresh_from_transcript(s: dict, force_state: bool = False) -> bool:
    """Titulo, rama, ultimo pedido/respuesta desde la transcripcion. Si la sesion no tiene
    hooks (o force_state), tambien el estado corriendo/termino. Devuelve si cambio algo.
    Lee sin el lock y aplica con el lock; el bucle de liveness usa las dos mitades por separado."""
    r = read_transcript(s)
    if r is None:
        return False
    with lock:
        return apply_transcript(s, r, force_state)


def set_title(s: dict, title: str) -> None:
    """Titulo puesto por el usuario desde la UI. Vacio: vuelve a la logica automatica
    (ai-title / thread_name de la transcripcion, o la primera linea del ultimo pedido)."""
    if title := short(title, 120):
        with lock:
            s["title"], s["title_source"] = title, "user"
        return
    with lock:
        s["title"] = s["title_source"] = None
    refresh_from_transcript(s)  # lee la transcripcion sin el lock y la aplica con el
    with lock:
        if s.get("title") is None:  # sin transcripcion: solo queda el pedido
            choose_title(s, None)


def set_coordinator(s: dict, on: bool) -> list[dict]:
    """Marca (o desmarca) la coordinadora del repo: a lo sumo una por repo, asi que al prender una
    se apagan las demas del mismo repo. Devuelve las sesiones que cambiaron (ya guardadas y
    publicadas)."""
    changed = []
    with lock:
        if on:
            for other in sessions.values():
                if other is not s and other.get("coordinator") and other.get("repo") == s.get("repo"):
                    other["coordinator"] = False
                    changed.append(other)
        if bool(s.get("coordinator")) != on:
            s["coordinator"] = on
            changed.append(s)
        for x in changed:
            touch(x)
    return changed


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
        except Exception as e:
            state.log(f"transcripcion {path}: {e}")
    if not tt and s.get("agent") == "codex":
        tt = transcripts.codex_title(s["session_id"])
    choose_title(s, tt)
    return s.get("title") != before


# --- eventos de hooks -------------------------------------------------------------


def claim_pid(s: dict, ev: dict) -> None:
    """El evento trae un pid vivo: la tarjeta se lo queda, salvo que ya sea de otra. Otra tarjeta con
    el mismo pid: si es un placeholder del barrido (source sweep o id "pid-N") es la misma sesion y
    se reemplaza; si es una sesion con hooks que termino (SessionEnd por /clear o resume) o dejo de
    emitir y esta trae su propia transcripcion, el proceso siguio con otro session_id y esta la
    continua (hereda pid, reglas y links); si es una sesion real que sigue viva, el pid ya tiene
    duena y este evento no se lo lleva (una prueba manual del hook con otro session_id no debe
    borrar la sesion real ni sus reglas). Se llama con el lock tomado."""
    pid, sid = ev["pid"], s["session_id"]
    owner = None
    if s.get("pid") != pid:
        for other_sid, other in list(sessions.items()):
            if other_sid != sid and other.get("pid") == pid:
                if other.get("source") == "sweep" or other_sid.startswith("pid-"):
                    drop_session(other_sid, "duplicada por barrido")
                elif continues_session(other, ev):
                    continue_session(other, s)
                else:
                    owner = other_sid
        if owner:
            state.log(
                f"pid {pid} ya pertenece a {owner[:8]}; evento {ev.get('hook_event_name') or '?'} de {sid[:8]} no lo toma"
            )
    if not owner:
        s["pid"] = pid
        s["agent_exe"] = ev.get("agent_exe")
        # el panel de Claude Code de VS Code y las apps de escritorio disparan hooks pero no
        # tienen consola: se ven y se leen, no se les escribe
        s["no_console"] = not backend.is_tui(s)


def title_from_prompt(s: dict) -> None:
    """Sin ai-title todavia (o con uno inutil): la tarjeta se titula con la primera linea del
    pedido. Un ai-title que sirva lo pisa despues (refresh_from_transcript), salvo que el pedido
    haya llegado como adjunto: ahi manda su encabezado."""
    if s.get("title_source") == "user":
        return
    if not (s.get("last_attachment") or bad_title(s.get("title")) or s.get("title_source") == "prompt"):
        return
    if first := prompt_title(s):
        s["title"], s["title_source"] = first, "prompt"


def hook_prompt_submit(s: dict, ev: dict) -> None:
    set_state(s, "corriendo")
    # pedido en curso: con esto se reconoce un Stop tardio del pedido anterior (stale_stop)
    s["prompt_id"] = ev.get("prompt_id")
    s["prompt_ts"] = s["last_event_ts"]
    if not transcripts.is_system_prompt(ev.get("prompt", "")):
        set_last_prompt(s, ev.get("prompt", ""))
        title_from_prompt(s)
    s["pending_id"] = None
    s["typing"] = False  # lo que habia en la caja ya se mando; screen_loop lo confirma en 5 s


def hook_stop(s: dict, ev: dict) -> None:
    if stale_stop(s, ev):
        state.log(
            f"Stop tardio de {s['session_id'][:8]} (pedido {str(ev.get('prompt_id'))[:8]}, ya corre "
            f"{str(s.get('prompt_id'))[:8]}): la tarjeta sigue corriendo"
        )
    else:
        set_state(s, "termino")
        if ev.get("last_assistant_message"):
            # entero, igual que turn_say: el recorte se lo hace la tarjeta por CSS
            s["last_reply"] = (ev["last_assistant_message"] or "").strip()
    s["pending_id"] = None


def hook_notification(s: dict, ev: dict) -> None:
    nt = ev.get("notification_type") or ""
    if nt == "idle_prompt" and s.get("last_prompt") and not (s.get("last_reply") or "").rstrip().endswith("?"):
        # termino con un informe que no pregunta nada: no "te necesita", solo termino. La
        # tarjeta libre (sin pedido) si pasa a te_necesita/idle, para ofrecer "Darle trabajo"
        state.log(f"{s['session_id'][:8]}: idle_prompt sin pregunta al final; la tarjeta queda en {s['state']}")
        return
    if nt not in NEEDS_NOTIFICATIONS:
        return
    set_state(s, "te_necesita")
    s["needs"] = {
        "kind": "idle" if nt == "idle_prompt" else "permission" if nt == "permission_prompt" else nt,
        "detail": short(ev.get("message", ""), 300),
        "where": "terminal",
    }


def apply_hook(s: dict, ev: dict, name: str, created: bool) -> None:
    """Lo propio de cada evento de hook sobre una tarjeta que apply_event ya puso al dia (pid, cwd,
    transcripcion, ultimo evento). Se llama con el lock tomado."""
    if name == "SessionStart":
        if created:
            set_state(s, "termino")
    elif name == "UserPromptSubmit":
        hook_prompt_submit(s, ev)
    elif name == "Stop":
        hook_stop(s, ev)
    elif name == "Notification":
        hook_notification(s, ev)
    elif name == "PermissionRequest":
        set_state(s, "te_necesita")
        s["needs"] = {
            "kind": "permission",
            "tool": ev.get("tool_name"),
            "detail": tool_detail(ev.get("tool_input")),
            "tool_use_id": ev.get("tool_use_id"),
            "where": "lienzo",
        }
    elif name == "PermissionDecision":
        s["pending_id"] = None
        set_state(s, "corriendo")  # set_state ya limpia `needs` al salir de te_necesita
    elif name == "PermissionTimeout":
        if s["state"] == "te_necesita" and s.get("needs"):
            s["needs"]["where"] = "terminal"
        s["pending_id"] = None
    elif name == "PostToolUse":
        if s["state"] == "te_necesita" and (s.get("needs") or {}).get("tool_use_id") == ev.get("tool_use_id"):
            set_state(s, "corriendo")
    elif name == "Interrupt":
        set_state(s, "termino")
    elif name == "SessionEnd":
        set_state(s, "muerta")
        s["alive"] = False
        s["dead_since"] = now()


def apply_event(ev: dict) -> None:
    name = ev.get("hook_event_name") or "?"
    sid = ev.get("session_id")
    if not sid or ev.get("agent_id"):
        return  # sin sesion, o subagente
    with lock:
        s = sessions.get(sid)
        created = s is None
        if created:
            s = new_session(sid, ev.get("agent") or "claude", "hook")
            sessions[sid] = s
        s["hooked"] = True
        s["source"] = "hook"
        if s.get("state") not in STATES:
            s["state"], s["state_since"] = "termino", now()
        if ev.get("pid") and backend.agent_alive(ev):
            claim_pid(s, ev)
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
        apply_hook(s, ev, name, created)
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
                try:
                    # bad-*.txt: lo que un hook no pudo parsear. El getmtime iba fuera del try y un
                    # archivo que desaparecia entre el listdir y esta linea mataba el hilo entero
                    if n.startswith("bad-") and time.time() - os.path.getmtime(p) > 3600:
                        os.remove(p)
                except OSError:
                    pass
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    ev = json.load(f)
                apply_event(ev)
            except Exception:
                state.log(f"evento {n} fallo:\n{traceback.format_exc()}")
            try:
                os.remove(p)
            except OSError:
                pass
        time.sleep(0.25)


# --- pendientes de permiso -----------------------------------------------------------


def read_pending() -> dict:
    """Los pedidos de permiso que hay ahora en ~/.lienzo/pending, por request_id. Un archivo a
    medio escribir (el hook lo escribe con atomic_write, pero igual) se saltea, no rompe la vuelta."""
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
    return found


def mark_pending(found: dict) -> None:
    """Le pone a cada tarjeta el permiso que la esta esperando, y se lo saca a la que ya no tiene
    ninguno: es lo que prende el boton de contestar en la tarjeta. Con el lock tomado."""
    for d in found.values():
        s = sessions.get(d.get("session_id"))
        if s is not None and s.get("pending_id") != d["request_id"]:
            s["pending_id"] = d["request_id"]
            touch(s)
    for s in sessions.values():
        if s.get("pending_id") and s["pending_id"] not in found:
            s["pending_id"] = None
            touch(s)


def scan_pending() -> None:
    """Cada medio segundo: que permisos estan esperando respuesta. El hook los deja en disco y se
    los lleva el mismo al contestar o al vencer, asi que el directorio es la verdad."""
    while True:
        try:
            found = read_pending()
            with lock:
                changed = set(found) != set(pending)
                pending.clear()
                pending.update(found)
                if changed:
                    mark_pending(found)
            if changed:
                state.broadcast({"type": "pending", "pending": public_pending()})
        except Exception:
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
    atomic_write(
        os.path.join(ANSWERS, f"{request_id}.json"),
        json.dumps({"nonce": d["nonce"], "decision": decision, "reason": reason, "answered": now()}),
    )
    state.log(f"permiso {request_id[:8]} -> {decision} ({d.get('tool_name')})")
    return 200, {"ok": True}


# --- liveness, barrido y transcripciones ----------------------------------------------


BIRTH_MARGIN_S = 120  # margen a los dos lados del nacimiento del proceso, que el barrido fecha grueso


def transcript_home(d: dict) -> str:
    """La base donde viven las transcripciones de este agente. Los de WSL vistos desde Windows estan
    en la home de WSL, que se lee por UNC (\\wsl.localhost\\...); el resto, en la home local."""
    if d.get("backend") == "tmux" and tmux._VIA_WSL:
        return tmux.wsl_unc_home() or HOME
    return HOME


def guess_claude(cwd: str, t0: float, home: str = HOME) -> tuple[str | None, str | None]:
    """Claude guarda una transcripcion por sesion en un directorio por cwd, y el nombre del archivo
    ES el session_id: alcanza con la mas nueva que siga viva despues de `t0`."""
    d = os.path.join(home, ".claude", "projects", claude_slug(cwd))
    cands = [p for p in glob.glob(os.path.join(d, "*.jsonl")) if os.path.getmtime(p) >= t0]
    if not cands:
        return None, None
    p = max(cands, key=os.path.getmtime)
    return os.path.splitext(os.path.basename(p))[0], p


def guess_codex(cwd: str, t0: float, home: str = HOME) -> tuple[str | None, str | None]:
    """Codex mezcla todos los rollouts en un arbol por fecha, asi que hay que abrirlos: entre los
    de la TUI con el mismo cwd, gana el que arranco mas cerca del nacimiento del proceso. "El mas
    nuevo" se equivoca si despues de abrir la TUI corrio un `codex exec` en el mismo directorio."""
    nacio = t0 + BIRTH_MARGIN_S  # t0 ya viene con el margen restado
    best, best_gap = None, None
    for p in glob.glob(os.path.join(home, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl")):
        if os.path.getmtime(p) < t0:
            continue
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
        birth = parse_ts(pl.get("timestamp") or first.get("timestamp"))
        gap = (birth.timestamp() if birth else os.path.getmtime(p)) - nacio
        if gap < -BIRTH_MARGIN_S:
            continue  # arranco antes que el proceso: no es suyo
        if best_gap is None or abs(gap) < abs(best_gap):
            best, best_gap = (pl.get("id") or pl.get("session_id"), p), gap
    return best or (None, None)


def guess_transcript(
    agent: str, cwd: str | None, created: str | None, home: str = HOME
) -> tuple[str | None, str | None]:
    """(session_id, transcript_path) mas probable para un agente encontrado por barrido: el barrido
    solo sabe pid y cwd, y de ahi hay que deducir de que sesion se trata. `created` es el
    nacimiento del proceso, con BIRTH_MARGIN_S de margen porque las dos fechas no son la misma
    (el rollout se crea un rato despues de abrir la TUI). `home` es la base de las transcripciones
    (la home de WSL por UNC para los agentes de WSL)."""
    if not cwd:
        return None, None
    born = parse_ts(created)
    t0 = born.timestamp() - BIRTH_MARGIN_S if born else 0
    return guess_claude(cwd, t0, home) if agent == "claude" else guess_codex(cwd, t0, home)


def attach_transcript(s: dict) -> None:
    """Tarjeta del barrido que todavia no tenia transcripcion (Codex crea el rollout recien en el
    primer turno, no al abrir): buscarla y, si aparece, tomar tambien el session_id real que trae,
    con lo que la tarjeta deja de llamarse `pid-N`. La busqueda va sin el lock; lo que escribe, con
    el lock y revalidando que la tarjeta siga siendo la misma."""
    cwd = s.get("cwd") or backend.cwd_of(s)
    sid, tpath = guess_transcript(s["agent"], cwd, s.get("started"), transcript_home(s))
    if not tpath:
        return
    with lock:
        if sessions.get(s["session_id"]) is not s:
            return  # la borraron mientras buscabamos su transcripcion: no revivirla
        if sid and sid != s["session_id"] and sid not in sessions:
            viejo = s["session_id"]  # la tarjeta cambia de id: la de antes se olvida entera
            forget_session(viejo)
            state.broadcast({"type": "removed", "session_id": viejo})
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


def adopt_process(p: dict) -> None:
    """Agente vivo que ninguna tarjeta reclama: si su transcripcion ya tiene tarjeta, esa recupera
    el pid (venia de una corrida anterior); si no, se abre una nueva."""
    cwd = p.get("cwd") or backend.cwd_of(p)  # en tmux el cwd viene del pane; en win32, del backend
    sid, tpath = guess_transcript(p["agent"], cwd, p.get("created"), transcript_home(p))
    with lock:
        s = sessions.get(sid) if sid else None
        if s is not None:
            s["backend"] = p.get("backend")  # la fuente que la vio es la que la maneja
            if p.get("target"):
                s["target"] = p["target"]  # en tmux el pane manda, aunque el pid siga vivo. No-op en Windows.
            if not s.get("pid") or not backend.agent_alive(s):
                s.update(
                    {
                        "pid": p["pid"],
                        "target": p.get("target"),
                        "agent_exe": p["exe"],
                        "alive": True,
                        "dead_since": None,
                    }
                )
                if s["state"] == "muerta":
                    set_state(s, "termino")
                touch(s)
            return
        s = new_session(sid or f"{p.get('backend') or 'win'}-{p['pid']}", p["agent"], "sweep")
        s.update(
            {
                "pid": p["pid"],
                "target": p.get("target"),
                "backend": p.get("backend"),
                "agent_exe": p["exe"],
                "cwd": cwd,
                "repo": repo_of(cwd),
                "transcript_path": tpath,
                "started": p.get("created") or now(),
                "in_vscode": p.get("in_vscode"),
                "orphan": p.get("orphan"),
            }
        )
        if not tpath:
            s["title"] = "sesion sin transcripcion identificada"
        sessions[s["session_id"]] = s
        refresh_from_transcript(s)
        touch(s)
        state.log(f"barrido: {p['agent']} pid {p['pid']} cwd={cwd} sid={s['session_id'][:8]}")


def sweep_once() -> None:
    """Barrido de respaldo: los agentes vivos que los hooks no reportaron."""
    global last_sweep
    last_sweep = time.time()
    found = backend.sweep()
    with lock:
        known_pids = {s.get("pid") for s in sessions.values() if s.get("pid")}
        sin_transcripcion = [
            s for s in sessions.values() if s.get("source") == "sweep" and not s.get("transcript_path") and s.get("pid")
        ]
    for s in sin_transcripcion:
        attach_transcript(s)
    for p in found:
        if p["pid"] not in known_pids:
            adopt_process(p)


def refresh_alive(s: dict) -> bool:
    """Pone `alive` / `dead_since` (y el estado `muerta`) al dia con el proceso. Devuelve si cambio
    algo. Una tarjeta sin pid no se toca: nunca se supo de ningun proceso suyo."""
    if not s.get("pid"):
        return False
    if backend.agent_alive(s):
        if s["alive"]:
            return False
        s["alive"] = True
        s["dead_since"] = None
        return True
    if not s["alive"]:
        return False
    s["alive"] = False
    s["dead_since"] = now()
    set_state(s, "muerta")
    return True


def check_liveness(sid: str) -> None:
    """Un paso de liveness sobre una tarjeta: proceso vivo, purga de las muertas, y refresco si la
    transcripcion crecio. Lo unico caro (leer y parsear la transcripcion) corre sin el lock; todo lo
    que escribe en el dict de la tarjeta va con el lock tomado."""
    with lock:
        s = sessions.get(sid)
        if s is None:
            return
        changed = refresh_alive(s)
        dead_since = parse_ts(s["dead_since"]) if s["state"] == "muerta" else None
        if dead_since and (dt.datetime.now().astimezone() - dead_since).total_seconds() > DEAD_GRACE_S:
            drop_session(sid, "muerta hace mas de 60 s")
            return
        # transcripcion: el stat es barato (14 us) y va aca; leerla, no
        tp = s.get("transcript_path")
        st = os.stat(tp) if tp and os.path.exists(tp) else None
        sig = (st.st_size, int(st.st_mtime)) if st else None
        crecio = sig is not None and transcript_stat.get(sid) != sig
        if crecio:
            transcript_stat[sid] = sig
        elif changed:
            touch(s)
    if not crecio:
        return
    r = read_transcript(s)  # lo caro, sin el lock
    with lock:
        if sessions.get(sid) is not s:
            return  # la borraron (o la reemplazaron) mientras leiamos: no revivirla
        if r is not None and apply_transcript(s, r):
            changed = True
        if changed:
            touch(s)
    state.broadcast({"type": "transcript", "session_id": sid, "size": st.st_size})


def liveness_loop(sweep_every: float) -> None:
    while True:
        try:
            with lock:
                sids = list(sessions)
            for sid in sids:
                check_liveness(sid)
            if sweep_every and time.time() - last_sweep > sweep_every:
                sweep_once()
        except Exception:
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


def send_blocked(s: dict) -> tuple[int, dict] | None:
    """Por que no se le puede escribir a esta sesion, o None si se puede."""
    if not s.get("pid") or not backend.agent_alive(s):
        return 409, {"ok": False, "error": "la sesion no tiene un PID vivo"}
    if s.get("orphan"):
        return 409, {"ok": False, "error": "la sesion perdio su terminal (huerfana): no hay consola donde escribir"}
    if s.get("no_console"):
        return 409, {
            "ok": False,
            "error": "esta sesion no tiene consola (panel de VS Code o app de escritorio): no se le puede escribir",
        }
    if s.get("pending_id"):
        return 409, {"ok": False, "error": "hay un permiso pendiente; contestalo primero"}
    return None


_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))


def strip_control(s: str) -> str:
    """Saca los caracteres de control y los overrides de direccion Unicode (hallazgo A4 del
    pentest): en la consola destino no llegan como caracteres, se teclean como teclas reales
    (ESC, Tab, Backspace, Ctrl-C) o alteran el orden visible del texto. El texto normal no los
    tiene, y lo largo o multilinea viaja como adjunto .md, no por aca."""
    return "".join(ch for ch in s if ord(ch) >= 0x20 and ord(ch) != 0x7F and ord(ch) not in _BIDI)


def _under_adjuntos(path: str) -> bool:
    """El adjunto esta realmente bajo ~/.lienzo/adjuntos (hallazgo M5): las rutas llegan crudas del
    cliente, y sin esto un send podia hacerle leer al agente cualquier archivo del disco (una clave
    privada, auth.json). Todo adjunto legitimo sale de /attach, que escribe ahi."""
    try:
        root = os.path.realpath(ADJUNTOS)
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except (ValueError, OSError):
        return False


def compose_send(sid: str, text: str, attachments: list[str]) -> tuple[str, str, list[str]]:
    """(lo que se tipea, lo que escribio el usuario, los adjuntos). Un mensaje largo o de varias
    lineas no se tipea: se guarda como .md y viaja como 'Leé el archivo adjunto...' (§6.5)."""
    attachments = [a for a in (attachments or []) if _under_adjuntos(a)]  # M5: confinar al buzon
    text = (text or "").replace("\r", "")
    orig = text.strip()  # lo que escribio el usuario: es lo que se cuenta y lo que muestra la tarjeta
    if len(text) > LONG_TEXT or "\n" in orig:
        attachments = [save_attachment(sid, "mensaje.md", text.encode("utf-8"))] + list(attachments)
        text = ATTACH_WRAPPER
    parts = [strip_control(text).strip()] if text.strip() else []  # A4: sin teclas de control
    parts += [f"Adjunto: {a}" for a in attachments]
    return " ".join(parts), orig, attachments


def run_send(s: dict, final: str) -> tuple[int, dict]:
    """Teclea `final` en la consola del agente. En tmux es send-keys al pane; en Windows, el
    subproceso send.py por PID (un texto largo va por archivo: la linea de comando no lo aguanta).
    (codigo, respuesta)."""
    if backend.is_tmux(s):
        if not tmux.target_valid(s.get("target"), s.get("pid")):
            return 409, {
                "ok": False,
                "error": "el pane cambió (¿tmux reinició?): no se envía, para no teclear en la terminal equivocada",
            }
        r = tmux.send(s.get("target"), final, enter=True)
        return (200, r) if r.get("ok") else (500, r)
    sid, pid = s["session_id"], s["pid"]
    tf = save_attachment(sid, ".send.txt", final.encode("utf-8")) if len(final) > 2000 else None
    cmd = [PYTHON, os.path.join(HERE, "send.py"), "--pid", str(pid)]
    cmd += ["--text-file", tf] if tf else ["--text", final]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=0x00000008,
        )  # DETACHED_PROCESS: sin consola propia
        return 200, json.loads(r.stdout.strip() or "{}")
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


def send_to_session(s: dict, text: str, attachments: list[str]) -> tuple[int, dict]:
    """Inyecta texto en la consola de la sesion y deja la tarjeta corriendo. El subproceso (hasta
    60 s) y la lectura del adjunto van fuera del lock; solo la tarjeta se toca con el lock."""
    if frenado := send_blocked(s):
        return frenado
    sid = s["session_id"]
    final, orig, attachments = compose_send(sid, text, attachments)
    if not final:
        return 400, {"ok": False, "error": "texto vacio"}
    code, out = run_send(s, final)
    if code == 200 and not out.get("ok"):
        state.log(f"send {sid[:8]} fallo (pid {s['pid']}): {out.get('error') or out}")
        code = 500
    if code != 200:
        return code, out
    state.log(
        f"send {sid[:8]}: {len(orig) if orig else out.get('chars')} caracteres"
        + (" (como adjunto)" if attachments else "")
        + f", pid {s['pid']}"
    )
    if orig:
        # send.py cuenta lo tipeado en la consola, que con un mensaje largo es el envoltorio
        # 'Leé el archivo adjunto...' (143); el toast y la tarjeta hablan del mensaje real
        out["chars"] = len(orig)
    # clean_prompt lee el adjunto del disco: fuera del lock, como el subproceso de arriba
    nuevo = short(orig, 500) if orig else short(clean_prompt(final), 500)
    with lock:
        s["last_prompt"] = nuevo
        if s.get("last_event") != "SessionEnd":
            # tras SessionEnd la consola ya es de otra sesion (/clear, resume): lo que se tipea
            # llega a esa, y esta tarjeta no vuelve a 'corriendo' (la continua apply_event)
            set_state(s, "corriendo")
        touch(s)
    return 200, out


# --- pantalla (solo para las sugerencias de la TUI de Claude, DISENO §12) ------------------


def read_screen(s: dict) -> dict:
    """La pantalla del agente: capture-pane del pane en tmux, o el subproceso screen.py por PID en
    Windows (FreeConsole/AttachConsole no puede correr dentro del server)."""
    if backend.is_tmux(s):
        tgt = s.get("target")
        if not tmux.target_valid(tgt, s.get("pid")):
            return {"ok": False, "error": "el pane ya no es de esta sesión"}
        return tmux.screen(tgt, scrollback=200)
    try:
        r = subprocess.run(
            [PYTHON, os.path.join(HERE, "screen.py"), "--pid", str(s["pid"]), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=0x00000008,
        )
        return json.loads(r.stdout.strip() or "{}")
    except (subprocess.TimeoutExpired, ValueError):
        return {"ok": False, "error": "screen.py no respondio"}


def screen_once() -> None:
    """Una pasada de lectura de pantalla. read_screen es un subproceso de 183 ms por sesion: corre
    fuera del lock, y recien despues (con el lock, y si la tarjeta sigue siendo la misma) se decide
    que hacer con lo leido. El estado se relee ahi: en 183 ms la sesion pudo empezar a correr."""
    with lock:
        items = [
            s
            for s in sessions.values()
            if s.get("agent") == "claude" and s.get("pid") and s.get("alive") and not s.get("orphan")
        ]
    for s in items:
        r = read_screen(s)
        area = r.get("area") if r.get("ok") else None
        escrito = bool(area and not area["placeholder"])
        with lock:
            if sessions.get(s["session_id"]) is not s:
                continue  # la borraron (o la reemplazaron) mientras leiamos: no revivirla
            # medido: "❯ Guardá la revisión en docs/revision-backend.md" con la sesion en idle_prompt
            idle = s["state"] == "termino" or (
                s["state"] == "te_necesita" and (s.get("needs") or {}).get("kind") == "idle"
            )
            sug = short(area["input"], 300) if escrito and idle else None
            typing = escrito and not idle
            if s.get("suggestion") != sug or bool(s.get("typing")) != typing:
                s["suggestion"] = sug
                s["typing"] = typing
                touch(s)


def screen_loop() -> None:
    """Cada 5 s, para las sesiones de Claude con terminal: que hay en la caja de entrada.
    Con la sesion ociosa (termino, o "te necesita" por idle) el texto es una sugerencia de Claude
    y va a la tarjeta; con la sesion ocupada (corriendo, o te_necesita por permiso) es alguien
    tipeando y solo se marca `typing`, para que el lienzo no le escriba encima."""
    while True:
        try:
            screen_once()
        except Exception:
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
            # tarjeta guardada por una version vieja: completar con la forma canonica, para que
            # /sessions no devuelva un campo presente en unas y ausente en otras
            for k, v in new_session(s["session_id"], s.get("agent") or "claude", s.get("source") or "hook").items():
                s.setdefault(k, v)
            if s.get("state") not in STATES:
                s["state"], s["state_since"] = "termino", s.get("state_since") or now()
            if not backend.agent_alive(s):
                ref = parse_ts(s.get("last_event_ts") or s.get("started"))
                if ref is None or ref < limit:
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
