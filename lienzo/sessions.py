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
import coda
import identity
import restore
import screen
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


def en_hilo(fn, *args) -> threading.Thread:
    """Corre `fn(*args)` en un hilo daemon y, si levanta, manda el traceback a lienzo.log. Es la
    UNICA forma en que este modulo lanza hilos de trabajo (cierre de turno, sucesion, aviso de
    muerta, aviso de detenida): un Thread suelto que levantaba moria con el traceback en stderr,
    que con el server corriendo de fondo no lee nadie (plan de refactor 1.1, E6). Devuelve el hilo
    para que una prueba pueda esperarlo. (Los argumentos de Thread van como target/args/daemon y
    nada mas: test_rules_federadas reemplaza threading.Thread por uno sincrono con esa firma.)"""
    t = threading.Thread(target=_correr_logueando, args=(fn, args), daemon=True)
    t.start()
    return t


def _correr_logueando(fn, args: tuple) -> None:
    try:
        fn(*args)
    except Exception:
        state.log(f"hilo {getattr(fn, '__name__', '?')} fallo:\n{traceback.format_exc()}")


def _gancho_sin_cablear(nombre: str):
    """Valor por defecto de un gancho que rellena rules.py: no hace nada, pero lo dice una vez en el
    log. Antes era una lambda muda, y si rules.py no se importaba (un arranque roto a medias, una
    prueba) las reglas «cuando termine» dejaban de disparar sin ningun rastro."""
    avisado = [False]

    def gancho(*_args) -> None:
        if not avisado[0]:
            avisado[0] = True
            state.log(f"gancho {nombre} sin cablear (rules.py no se cargo): el evento se descarta")

    return gancho


# ganchos que rellena rules.py: cierre de turno (reglas "cuando termine"), aviso de limite de uso
# con hora y turno muerto por un error de API (las dos reglas automaticas "Continuar"). Sin
# rules.py cargado no pasa nada (salvo el aviso en el log, una vez por gancho).
on_turn_end = _gancho_sin_cablear("on_turn_end")
on_limit_notice = _gancho_sin_cablear("on_limit_notice")
on_died_working = _gancho_sin_cablear("on_died_working")  # rules.py: avisar que murio con un encargo a medias
on_api_error = _gancho_sin_cablear("on_api_error")


# --- mirror (frente C, plan multi-PC §3.3-3.6): sesiones y reglas de otra PC -------------------
#
# mirror.py todavia no existe en este arbol (o esta ronda se corre sin el, o un test lo reemplaza
# por sys.modules): sin el, toda sesion es local, exactamente el comportamiento de antes de la
# federacion. `mirror.MIRROR` es el singleton que define (owner_of, forward, rules, sessions); los
# tests de este frente lo stubean con monkeypatch.setattr(ses, "mirror", ...), no inventando mas
# metodos de los que ya pacto el encargo comun.
try:
    import mirror
except ImportError:
    mirror = None


def _mirror_owner(sid: str) -> str | None:
    """pc_id de la PC dueña de `sid` si es remota; None si es local, desconocida o sin mirror."""
    return mirror.MIRROR.owner_of(sid) if mirror else None


def _mirror_forward(pc_id: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Request firmado a `pc_id` por /peer/<path>. Sin mirror enchufado: 503, igual que un peer
    caido (nadie deberia llamar esto sin haber visto antes un owner_of que no sea None)."""
    if not mirror:
        return 503, {"ok": False, "error": "mirror no disponible"}
    return mirror.MIRROR.forward(pc_id, method, path, body)


def _mirror_sessions() -> list[dict]:
    return mirror.MIRROR.sessions() if mirror else []


def _mirror_rules() -> list[dict]:
    return mirror.MIRROR.rules() if mirror else []


def _mirror_session(sid: str) -> dict | None:
    return next((o for o in _mirror_sessions() if o.get("session_id") == sid), None)


def find_session(sid: str) -> dict | None:
    """La tarjeta de `sid`: local si esta en memoria, si no la espejada de otra PC (mirror.py). La
    usa rules.py para decidir (destino ocupado, detenido) sin pedirsela por red a su dueña."""
    return sessions.get(sid) or _mirror_session(sid)


def _repo_identity(s: dict) -> str | None:
    """Identidad de repo para agrupar coordinadoras: `repo_key` (remote normalizado) y, mientras
    no se resuelva, su respaldo `repo` (nombre de carpeta). None solo si ninguno de los dos esta
    resuelto, y None nunca hace match con otro None: antes, dos sesiones con repo_key sin resolver
    (None) contaban por accidente como el mismo repo."""
    return s.get("repo_key") or s.get("repo") or None


def repo_coordinator(repo: str | None, pc: str | None, local: list[dict], remote: list[dict]) -> dict | None:
    """La coordinadora de `repo` tal como la ve una sesion de la PC `pc` (plan multi-PC §3.6):
    primero la separada (`coordinator_scope` "pc") de esa misma PC si existe, si no la federada
    (cualquier otro scope), este en `local` o en `remote` (mirror.py, frente C). None si `repo` no
    se pudo resolver, o si no hay ninguna coordinadora de ese repo en ningun lado."""
    if repo is None:
        return None
    scoped = next(
        (
            o
            for o in local
            if o.get("coordinator")
            and o.get("coordinator_scope") == "pc"
            and o.get("pc") == pc
            and _repo_identity(o) == repo
        ),
        None,
    )
    if scoped:
        return scoped
    return next(
        (
            o
            for o in (*local, *remote)
            if o.get("coordinator") and o.get("coordinator_scope") != "pc" and _repo_identity(o) == repo
        ),
        None,
    )


ATTACH_WRAPPER = "Leé el archivo adjunto y respondé:"
# la herramienta `read` de coda se traba (medido el 2026-10-02: 4 sesiones, Qwen y GLM, mas de una hora
# en «usando read»), y su shell anda: a coda se le pide leer el adjunto con el shell. Empieza igual que
# ATTACH_WRAPPER, asi que lo que detecta el mensaje envuelto (prefijo) lo sigue reconociendo. Ademas
# se le pide ejecutar: coda resumia el encargo largo y quedaba esperando un segundo «arranca» (medido
# el 2026-10-03 con las sesiones 3 y 4 del curso).
ATTACH_WRAPPER_SHELL = (
    ATTACH_WRAPPER
    + " (NO uses la herramienta read: leelo con el shell, con type). Despues EJECUTA lo que pide, sin resumirmelo"
    " ni pedir confirmacion: solo paras si algo te frena o la decision es del humano."
)
SHELL_READERS = ("coda",)


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


def set_last_prompt(s: dict, raw: str, via: str | None = None) -> None:
    """Guarda el ultimo pedido tal como se muestra y, si llego como adjunto, la ruta del .md.
    `via` es de donde vino (prompt_via); solo el hook lo sabe. Sin `via`, un pedido que no cambio
    conserva el origen que ya tenia --la transcripcion repite el mismo pedido-- y uno nuevo queda
    sin origen, que es como se comportaba todo antes de que existiera la marca."""
    nuevo = short(clean_prompt(raw), 500)
    if via is not None:
        s["prompt_via"] = via
    elif nuevo != s.get("last_prompt"):
        s["prompt_via"] = None
    s["last_prompt"] = nuevo
    s["last_attachment"] = attachment_path(raw)


def prompt_mark(text: str) -> str:
    """Huella de un pedido, para reconocerlo cuando vuelve por el hook: espacios colapsados y los
    primeros 120 caracteres."""
    return " ".join((text or "").split())[:120]


def mark_sent(s: dict, final: str) -> None:
    """El lienzo esta por teclear `final` en la consola: deja su huella antes de teclear (despues
    es tarde, el hook puede llegar primero) para que el UserPromptSubmit que venga se reconozca
    como encargo y no como algo tipeado en la terminal."""
    s["sent_mark"] = prompt_mark(final)


def prompt_origin(s: dict, raw: str) -> str:
    """De donde vino el pedido que llego por UserPromptSubmit, y consume la marca del envio:
    'lienzo' si es el que el tablero acaba de teclear (encargo del coordinador, regla, o la caja
    de la tarjeta), 'peer' si es un mensaje de otra sesion por el canal nativo, 'terminal' si lo
    tipeo el usuario en la consola."""
    mark, s["sent_mark"] = s.get("sent_mark"), None
    if mark and prompt_mark(raw) == mark:
        return "lienzo"
    return "peer" if transcripts.peer_message(raw or "") else "terminal"


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


def typed_here(s: dict) -> bool:
    """El ultimo pedido lo tipeo el usuario en su terminal y la tarjeta ya tiene un nombre que
    sirve: no se la renombra. El nombre de la tarjeta lo pone el encargo --el que manda la
    coordinadora, o el que se escribe desde el tablero--, no cada cosa que se tipea mientras se
    trabaja. Si todavia no tiene nombre, lo tipeado sirve igual: poner uno no es cambiarlo."""
    return s.get("prompt_via") == "terminal" and not bad_title(s.get("title"))


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
    pt = None if typed_here(s) else prompt_title(s)
    cur, src = s.get("title"), s.get("title_source")
    if transcript_title is None and src == "transcript" and not bad_title(cur):
        return  # el ai-title quedo fuera de la cola leida: se conserva el que ya teniamos
    if transcript_title and (not bad_title(transcript_title) or not pt):
        s["title"], s["title_source"] = transcript_title, "transcript"
    elif pt:
        s["title"], s["title_source"] = pt, "prompt"
    elif bad_title(cur):
        s["title"], s["title_source"] = None, None


def is_question(d: dict) -> bool:
    """El pendiente no es un permiso sino una pregunta con opciones. AskUserQuestion viene por
    PermissionRequest igual que todo lo demas, pero Permitir/Denegar no le sirve a nadie: permitir
    devuelve la pregunta al selector de la terminal y denegar la cancela."""
    return d.get("tool_name") == "AskUserQuestion" and isinstance(d.get("tool_input"), dict)


def questions_of(d: dict) -> list[dict]:
    """Las preguntas de un AskUserQuestion, cada una con su texto y sus opciones."""
    if not is_question(d):
        return []
    return [q for q in (d["tool_input"].get("questions") or []) if isinstance(q, dict) and q.get("question")]


def first_question(d: dict) -> str:
    """La primera pregunta, para la linea de la tarjeta. Con mas de una se avisa cuantas faltan."""
    qs = questions_of(d)
    if not qs:
        return ""
    resto = f" (+{len(qs) - 1})" if len(qs) > 1 else ""
    return short(str(qs[0]["question"]), 300) + resto


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
    link = {
        "id": secrets.token_hex(6),
        "from": src,
        "to": dst,
        "ts": now(),
        "text": short(text, 160),
        "kind": kind,
        "pc": identity.pc_id(),
    }
    if rule_id:
        link["rule_id"] = rule_id
    links.add(link)


def apply_repo(s: dict, cwd: str) -> None:
    """`repo` (para mostrar) y `repo_key` (identidad de la coordinadora: remote normalizado, o la
    carpeta si no hay remote) de un mismo cwd, siempre juntos: si se pisaran por separado quedan
    desincronizados y dos sesiones del mismo remote en carpetas distintas dejan de compartir
    coordinadora (plan multi-PC, §3.6)."""
    s["repo"] = repo_of(cwd)
    s["repo_key"] = identity.repo_key(cwd)


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


def restore_guard(fn) -> None:
    """Corre `fn` (una operacion sobre el registro de restaurables) sin dejar que levante: el
    registro es accesorio y no puede romper el borrado ni el liveness. Loguea el traceback."""
    try:
        fn()
    except Exception:
        state.log(f"restaurar: {traceback.format_exc()}")


def restore_on_drop(card: dict, muerta: bool) -> None:
    """Registro de sesiones restaurables (restore.py) al borrar una tarjeta. Murio el proceso
    (`muerta`, que es lo que deja un reinicio de PC): se recuerda, salvo que haya terminado a
    proposito (/exit, logout). Cualquier otro borrado (a mano, continuada tras un /clear, duplicada
    por barrido) la olvida: ya no hay nada que restaurar. Nunca levanta."""

    def work() -> None:
        if muerta and not restore.ended_on_purpose(card):
            restore.remember(card, ended=True)
        else:
            restore.forget(card["session_id"])

    restore_guard(work)


# Sucesion: una sesion que muere siendo destino de reglas deja sus datos aca hasta SUCESION_MAX_S; una
# sesion nueva del mismo agente en la misma carpeta las hereda. Medido el 2026-10-03: la coordinadora
# del gestor se cerro y se reabrio con otro id, y se borraron los avisos de todas las codas del curso.
#
# Se lee y se escribe SOLO con state.lock tomado (plan de refactor 1.3, E2): la escriben drop_session
# (liveness, borrado) y la consumen los hilos de adopt_dead_target, y dos sucesoras que nacian juntas
# heredaban las dos. Vive en memoria: la sucesion NO sobrevive a un reinicio del server. Las reglas
# quedan estacionadas en rules.json (parked_to) pero, reiniciado el server, ya no hay quien las
# reasigne solas: quedan deshabilitadas hasta un POST /rules/retarget a mano, o hasta que la purga
# de las estacionadas hace mas de SUCESION_MAX_S (rules.purge_stale_xpc) se las lleva.
SUCESION_MAX_S = 24 * 3600
DEAD_TARGETS: dict[str, dict] = {}


def park_rules_to(sid: str) -> int:
    """Deshabilita y marca (parked_to) las reglas que avisan a `sid`. Devuelve cuantas."""
    with lock:
        suyas = [r for r in rules.items if r.get("to") == sid and not r.get("parked_to")]
        for r in suyas:
            r["parked_to"], r["parked_since"], r["enabled"] = sid, now(), False
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
    return len(suyas)


def retarget_rules(old: str, new: str) -> int:
    """Las reglas que avisaban a `old` (estacionadas o no) pasan a avisar a `new`, habilitadas."""
    with lock:
        suyas = [r for r in rules.items if old in (r.get("to"), r.get("parked_to"))]
        for r in suyas:
            r["to"], r["enabled"] = new, True
            r.pop("parked_to", None)
            r.pop("parked_since", None)
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
        state.log(f"{len(suyas)} reglas que avisaban a {old[:8]} ahora avisan a {new[:8]}")
    return len(suyas)


def _norm_cwd(c: str | None) -> str:
    return (c or "").replace("\\", "/").rstrip("/").lower()


def adopt_dead_target(s: dict) -> str | None:
    """Si `s` (recien nacida) es la sucesora de una sesion que murio siendo destino de reglas (mismo
    agente, misma carpeta, hace menos de SUCESION_MAX_S), hereda sus reglas aca y en las otras PCs.
    Devuelve el id viejo, o None."""
    ahora = time.time()
    with lock:
        for k in [k for k, v in DEAD_TARGETS.items() if ahora - v["since"] > SUCESION_MAX_S]:
            DEAD_TARGETS.pop(k, None)
        candidatas = [
            (v["since"], old)
            for old, v in DEAD_TARGETS.items()
            if v.get("agent") == s.get("agent")
            and _norm_cwd(v.get("cwd")) == _norm_cwd(s.get("cwd"))
            and old != s["session_id"]
        ]
        if not candidatas:
            return None
        old = max(candidatas)[1]
        # la elegida se reserva antes de soltar el lock: si otra sucesora ya se la llevo, esta no
        # hereda (con un pop a secas las dos seguian adelante y las dos re-apuntaban las reglas)
        if DEAD_TARGETS.pop(old, None) is None:
            return None
    retarget_rules(old, s["session_id"])  # toma el lock por dentro; el forward a otras PCs, no
    if mirror:
        for pc in mirror.MIRROR.peer_ids():
            code, res = mirror.MIRROR.forward(pc, "POST", "/rules/retarget", {"old": old, "new": s["session_id"]})
            if code != 200:
                state.log(f"heredar reglas de {old[:8]} en {pc}: {code} {(res or {}).get('error')}")
    return old


def drop_session(sid: str, reason: str, muerta: bool = False) -> bool:
    """Borra la tarjeta. `reason` es solo para el log; `muerta` (el proceso desaparecio) es lo que
    decide si se recuerda para restaurar. False si no existia (no se toco nada, ni el registro)."""
    with lock:
        card = sessions.get(sid)
        if not forget_session(sid):
            return False
    links.remove(lambda l: sid in (l["from"], l["to"]))
    rules.remove(lambda r: r.get("from") == sid)  # las suyas mueren con ella
    if muerta and card:
        # las que le AVISABAN quedan estacionadas: si vuelve a abrirse una sesion igual en esa
        # carpeta (la coordinadora que se cerro y se reabrio), las hereda (adopt_dead_target)
        n = park_rules_to(sid)
        if n:
            with lock:
                DEAD_TARGETS[sid] = {"cwd": card.get("cwd"), "agent": card.get("agent"), "since": time.time()}
            state.log(f"{n} reglas que avisaban a {sid[:8]} quedan en espera de una sucesora")
    else:
        rules.remove(lambda r: r["to"] == sid)
    state.log(f"tarjeta {sid[:8]} borrada ({reason})")
    restore_on_drop(card, muerta)
    state.broadcast({"type": "removed", "session_id": sid})
    return True


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


def repoint_refs(old_sid: str, new_sid: str) -> tuple[int, int]:
    """Las dos puntas de cada regla y de cada link que nombraban a `old_sid` pasan a `new_sid`.
    Devuelve (reglas, links) re-apuntados. Se llama con el lock tomado."""

    def repoint(coll) -> int:
        n = 0
        for x in coll.items:
            for k in ("from", "to"):
                if x.get(k) == old_sid:
                    x[k] = new_sid
                    n += 1
        if n:
            coll.save()
        return n

    return repoint(rules), repoint(links)


def continue_session(old: dict, new: dict) -> None:
    """La sesion nueva hereda el pid de la vieja y todo lo que la apuntaba: reglas y links donde la
    vieja era origen o destino pasan al sid nuevo, y la vieja se da de baja."""
    old_sid, new_sid = old["session_id"], new["session_id"]

    with lock:
        n_rules, n_links = repoint_refs(old_sid, new_sid)
        for k in ("pid", "agent_exe", "no_console", "in_vscode", "coordinator", "coordinator_scope", "pc"):
            if old.get(k) is not None:
                new[k] = old[k]
        if not new.get("cwd") and old.get("cwd"):
            new["cwd"] = old["cwd"]
            new["repo"] = old.get("repo") or repo_of(old["cwd"])
            new["repo_key"] = old.get("repo_key") or identity.repo_key(old["cwd"])
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
        "pc": identity.pc_id(),
        "pid": None,
        "target": None,  # backend tmux: el pane (%0, %1, ...) donde escribir/leer. None en Windows.
        "backend": None,  # "win32" | "tmux": que fuente maneja esta tarjeta. None = primario de la plataforma.
        "agent_exe": None,
        "cwd": None,
        "repo": "?",
        "repo_key": None,
        "branch": None,
        "title": None,
        "title_source": None,
        "copycat_of": None,
        "stopped_by": None,
        "transcript_path": None,
        "transcript_bytes": None,
        "model": None,
        "state": "termino",
        "state_since": now(),
        "needs": None,
        "last_prompt": "",
        "prompt_via": None,
        "sent_mark": None,
        "last_reply": "",
        "last_error": None,
        "started": now(),
        "last_event": None,
        "last_event_ts": None,
        "alive": True,
        "dead_since": None,
        "end_reason": None,  # razon del SessionEnd (exit, logout, clear, other...); la usa restore.py
        "source": source,
        "hooked": source == "hook",
        "pending_id": None,
        "typing": False,
        "coordinator": False,
        "coordinator_scope": None,
        "orphan": False,
        "in_vscode": False,
        "no_console": False,
        "suggestion": None,
        "dialog": None,
        "limit_until": None,
        "continue_scheduled_for": None,
        "retryable": False,
        "retry_done_for": None,
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
        if cierra_turno(s, prev, new):
            # reglas "cuando termine" (en otro hilo, el envio tarda)
            en_hilo(on_turn_end, s["session_id"])
    if new != "te_necesita":
        s["needs"] = None


def cierra_turno(s: dict, prev: str | None, new: str) -> bool:
    """¿Esta transicion cierra un turno de trabajo (y dispara las reglas «cuando termine»)? Solo de
    corriendo o te_necesita a termino. Pi sin hooks no: su stopReason cierra una respuesta del
    modelo, no la corrida del agente (reintento, seguimiento), y sin la extension no hay
    agent_settled que diga que de verdad termino."""
    return new == "termino" and prev in ("corriendo", "te_necesita") and (s.get("agent") != "pi" or s.get("hooked"))


def marcar_muerta(s: dict, avisar: bool) -> None:
    """La tarjeta pasa a muerta: estado, `alive` y `dead_since` juntos, siempre por aca. Con el lock
    tomado. `avisar` (explicito en cada llamada) dice si, muriendo con un encargo a medias
    (corriendo / te_necesita), se le avisa a la coordinadora (on_died_working, rules.py). Las formas
    de morir (plan de refactor 1.7, E9):

    - el proceso desaparecio (refresh_alive): avisar=True, es la unica muerte inesperada;
    - SessionEnd (apply_hook): avisar=False, es /exit, logout o /clear, a proposito;
    - evento con el pid ya muerto (apply_event): avisar=False. El evento quedo en la cola con el
      server apagado, o el agente lo escribio justo antes de cerrarse: prueba que la sesion
      existio, no que muriera trabajando ahora, y avisar al arrancar el server repetiria avisos
      viejos;
    - al cargar del disco (load_sessions) escribe el estado directo, a proposito: una tarjeta de la
      corrida anterior no cierra ningun turno ni avisa nada."""
    prev = s.get("state")
    s["alive"] = False
    s["dead_since"] = s.get("dead_since") or now()
    set_state(s, "muerta")
    if avisar and prev in ("corriendo", "te_necesita"):
        en_hilo(on_died_working, s["session_id"], prev)


def set_needs(s: dict, needs: dict) -> None:
    """Pone a la tarjeta en "te necesita" con lo que espera. `since` es la hora del aviso, no la del
    estado: en una misma tanda de te_necesita se encadenan varios (tres preguntas seguidas el
    2026-09-08) y `state_since` se queda en el primero, que es la marca contra la que mide
    needs_answered para saber si la transcripcion siguio despues."""
    set_state(s, "te_necesita")
    s["needs"] = {**needs, "since": now()}


def touch(s: dict) -> bool:
    """Guarda la tarjeta y la publica, solo si sigue siendo LA tarjeta de su id en el registro;
    devuelve si lo hizo. La guarda vive aca y no en cada llamador (plan de refactor 1.2, E1/S10):
    despues de un envio de hasta 60 s, un touch sobre una tarjeta que se borro mientras tanto le
    rehacia el archivo en disco y resucitaba en el proximo arranque, y sobre una reemplazada (mismo
    id, otro dict) pisaba a la nueva. Todo lo que crea tarjetas (apply_event, adopt_process,
    attach_transcript) las inserta en `sessions` antes del primer touch; load_sessions usa
    save_session directo. Toma el lock (reentrante): vale igual llamado con o sin el."""
    with lock:
        if sessions.get(s.get("session_id")) is not s:
            return False
        save_session(s)
        state.broadcast({"type": "session", "session": s})
    return True


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
    "last_denied",
    "title",
    "branch",
    "last_prompt",
    "last_reply",
    "state",
    "cwd",
    "last_error",
    "limit_until",
    "continue_scheduled_for",
    "retryable",
    "tool_count",
    "last_files",
    "last_cmd",
    "tool_errors",
    "model",
    "transcript_bytes",
)


def needs_answered(s: dict, t: dict) -> bool:
    """La transcripcion dice que el permiso (o la pregunta) que tiene frenada a la tarjeta ya se
    contesto, casi siempre en la terminal. Mientras uno esta abierto Claude no escribe una sola
    linea --medido el 2026-09-08 en 6024f728: entre el tool_use del AskUserQuestion (20:50:14.002Z)
    y su tool_result (20:54:22.166Z) no hay ninguna otra linea-- y el tool_use ya estaba escrito
    0,4 s antes de que llegara el PermissionRequest, asi que actividad posterior al aviso solo
    puede ser el desenlace.

    Es la unica salida cuando se contesta en la terminal: el hook sigue esperando su respuesta y a
    los 60 s manda un PermissionTimeout, que solo dice donde hay que contestar. Con AskUserQuestion
    no hay ninguna otra, porque su PermissionRequest trae tool_use_id null y no habria con que
    emparejar un PostToolUse (que ademas no esta registrado). La tarjeta se quedaba en "te
    necesita" hasta el Stop del turno: 19 minutos el 2026-09-08 en esa misma sesion, que habia
    contestado a los 4 segundos y siguio trabajando."""
    needs = s.get("needs") or {}
    if s["state"] != "te_necesita" or needs.get("kind") not in ("permission", "question"):
        return False  # idle no frena nada: lo cierra el UserPromptSubmit
    aviso, ultimo = parse_ts(needs.get("since")), parse_ts(t.get("ts_end"))
    # el mismo margen de 2 s que transcript_state, y por lo mismo: la lectura que cae entre el
    # tool_use y el hook que lo anuncia no es actividad posterior
    return aviso is not None and ultimo is not None and (ultimo - aviso).total_seconds() > 2.0


def drop_pending(s: dict) -> None:
    """Le saca a la tarjeta el pedido que tenia abierto: ya se contesto en otro lado y los botones
    del lienzo no contestan nada. El hook borra el archivo cuando termina de esperar, hasta 60 s
    despues; borrarlo aca es lo que apaga los botones ahora (`read_pending` mira el directorio, que
    es la verdad). Con el lock tomado."""
    rid = s.get("pending_id")
    if not rid:
        return
    s["pending_id"] = None
    try:
        os.remove(os.path.join(PENDING, rid + ".json"))
    except OSError:
        pass


def apply_turn_hooked(s: dict, t: dict) -> None:
    """Sesion con hooks: el pedido y la respuesta final ya vinieron por UserPromptSubmit / Stop. De
    la transcripcion se toma lo que el agente viene diciendo mientras corre, y el estado solo
    cuando los hooks lo dejaron al reves (Stop tardio de un pedido encolado, evento perdido, o un
    permiso contestado en la terminal, que no deja hook de cierre)."""
    if s.get("agent") != "pi" and needs_answered(s, t):
        state.log(
            f"{s['session_id'][:8]}: la transcripcion siguio despues del aviso "
            f"({(s.get('needs') or {}).get('kind')}); se contesto en la terminal, la tarjeta vuelve a corriendo"
        )
        set_state(s, "corriendo")  # set_state limpia `needs` al salir de te_necesita
        drop_pending(s)
    # Pi's stopReason ends a model response, not necessarily the agent run (retry/follow-up).
    # Only agent_settled may close a hooked Pi turn and trigger forwarding rules.
    want = None if s.get("agent") == "pi" else transcript_state(s, t)
    if s.get("agent") == "coda" and s["state"] == "corriendo" and not s.get("last_prompt") and (p := turn_prompt(t)):
        set_last_prompt(s, p)  # el UserPromptSubmit no llego: el pedido esta en la base desde que arranco
    if want:
        if want == "corriendo" and (p := turn_prompt(t)):
            set_last_prompt(s, p)
        state.log(
            f"{s['session_id'][:8]}: la transcripcion dice {want} y los hooks {s['state']} "
            f"(ultimo evento {s.get('last_event')}); corregido"
        )
        set_state(s, want)
    if s["state"] == "corriendo" and (not t.get("ended") or s.get("agent") == "pi"):
        s["last_reply"] = turn_say(t) or s["last_reply"]
    elif s.get("agent") == "coda" and t.get("ended") and t.get("final"):
        # el Stop de CODA no trae la respuesta: llega con el turno, que CODA guarda al cerrarlo
        s["last_reply"] = turn_say(t)


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


def set_denied(s: dict, d: dict) -> None:
    """Marca en la tarjeta el ultimo permiso DENEGADO (por regla, politica o clasificador). Solo si
    es nuevo: la misma denegacion releida de la transcripcion no se vuelve a anunciar."""
    clave = (d.get("tool"), d.get("motivo") or d.get("cause"), d.get("detalle"), d.get("turno") or d.get("at"))
    prev = s.get("last_denied") or {}
    if (
        prev.get("tool"),
        prev.get("motivo") or prev.get("cause"),
        prev.get("detalle"),
        prev.get("turno") or prev.get("at"),
    ) == clave:
        return
    s["last_denied"] = {**d, "visto": now()}
    state.log(
        f"permiso DENEGADO a {s['session_id'][:8]}: {d.get('tool')} ({d.get('motivo') or d.get('cause') or 'sin motivo'})"
        + (f" {d['detalle']}" if d.get("detalle") else "")
    )


def apply_turn(s: dict, t: dict, force_state: bool) -> None:
    """Vuelca el ultimo turno de la transcripcion a la tarjeta: actividad de adentro, pedido y
    respuesta, estado (solo si la sesion no tiene hooks, o force_state) y el error del turno."""
    # lo que pasa adentro, para la tarjeta: cuanto lleva hecho y sobre que archivos. Un turno abierto
    # de CODA en la base es solo el pedido (el resto se guarda al cerrar): la actividad la llevan
    # coda_tool y coda_log_activity, y releerlo la pondria en cero
    if not (s.get("agent") == "coda" and not t.get("ended")):
        s.update(turn_activity(t))
    if s.get("hooked") and not force_state:
        apply_turn_hooked(s, t)
    else:
        apply_turn_unhooked(s, t)
    if negadas := transcripts.denials(t):
        set_denied(s, {**negadas[-1], "fuente": "transcript", "turno": t.get("id") or t.get("prompt_ts")})
    # error del turno (Codex: limite de uso, abortado; Claude: no aplica hoy) va aparte, en rojo
    s["last_error"] = short(t.get("error") or "", 300) or None
    if s["last_error"] and not t.get("final"):
        s["last_reply"] = s["last_error"]
    # limite de uso con hora de vuelta: la tarjeta ofrece programar "Continuar" y, con
    # auto_continue en config.json, queda programado solo (un disparo por aviso)
    s["limit_until"] = limit_until_of(t)
    if s["limit_until"]:
        on_limit_notice(s)
    # el turno murio por un error de API ("API Error: The response stopped arriving"): no hay hora
    # que esperar, lo unico que falta es volver a pedirlo. La tarjeta ofrece "Reintentar" y, con
    # auto_retry en config.json, se manda solo una vez por error
    s["retryable"] = bool(
        s["last_error"]
        and not s["limit_until"]
        and t.get("ended")
        and transcripts.retryable_error(t.get("error"))
        and not (s.get("agent") == "pi" and (not s.get("hooked") or s["state"] != "termino"))
    )
    if s["retryable"]:
        on_api_error(s, f"{t.get('id')}:{s['last_error']}")


def model_of(agent: str, path: str) -> str | None:
    """Modelo de la ultima respuesta del asistente, leido de la cola de la transcripcion con las
    utilidades ya publicas de transcripts.py (tail_lines, iter_json): no duplica su parser (que no
    expone este campo, y unificar los dos formatos ya se probo y no vale la pena, ver el comentario
    de transcripts.py sobre parse_claude/parse_codex). Claude y Pi lo traen en message.model de
    cada linea de asistente; Codex lo trae en turn_context.payload.model, vigente hasta el proximo
    turn_context. CODA no lo guarda en su base: None."""
    if agent == "coda" or not path:
        return None
    try:
        lines, _ = transcripts.tail_lines(path)
    except OSError:
        return None
    model = None
    for d in transcripts.iter_json(lines):
        if agent == "codex":
            if d.get("type") == "turn_context":
                model = (d.get("payload") or {}).get("model") or model
            continue
        msg = d.get("message")
        if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("model"):
            model = msg["model"]
    return model


def read_transcript(s: dict) -> dict | None:
    """Lee y parsea la transcripcion, y de paso resuelve el titulo que trae. Es lo caro del refresco
    (medido: 22 ms de mediana y 48 ms el peor caso sobre 2 MB de cola), asi que corre SIN el lock:
    solo lee de la tarjeta, no le escribe nada. None si no hay transcripcion o no se pudo leer."""
    path = s.get("transcript_path")
    if not path or not os.path.exists(path):
        return None
    try:
        r = transcripts.turns(s["agent"], path, 1, leaf_id=transcripts.leaf_of(s))
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
        apply_repo(s, s["cwd"])
    if ts:
        apply_turn(s, ts[-1], force_state)
    choose_title(s, r["title"])
    if path := s.get("transcript_path"):
        s["model"] = model_of(s["agent"], path) or s.get("model")
        try:
            s["transcript_bytes"] = os.path.getsize(path)  # stat, no lee el contenido
        except OSError:
            pass
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


def set_coordinator(s: dict, on: bool, scope: str | None = None) -> list[dict]:
    """Marca (o desmarca) la coordinadora del repo (plan multi-PC §3.6). Por defecto (`scope`
    None: federada), a lo sumo una **en toda la federacion**: prender una apaga las demas del
    mismo repo, sean de esta PC o de otra (via mirror.forward a su `/sessions/<sid>/coordinator
    {on: false}`, frente C). Con `scope: "pc"` la ★ vale solo para esta PC: apaga solo a otra
    "pc" del mismo repo en esta PC, y convive con la federada (ninguna de las dos apaga a la
    otra). La identidad de repo es `_repo_identity` (repo_key con respaldo en `repo`, sin
    matchear dos sin resolver): dos carpetas con el mismo nombre pero remotes distintos son repos
    distintos, y el mismo remote clonado en carpetas o PCs distintas comparte coordinadora.
    Devuelve las sesiones LOCALES que cambiaron (ya guardadas y publicadas); lo apagado por
    forward en otra PC lo publica su propio server, no esta."""
    changed = []
    my_repo = _repo_identity(s)
    with lock:
        if on and my_repo is not None:
            for other in sessions.values():
                if other is s or not other.get("coordinator") or _repo_identity(other) != my_repo:
                    continue
                if scope == "pc":
                    if other.get("coordinator_scope") != "pc":
                        continue  # la federada convive con la nueva separada de esta PC
                elif other.get("coordinator_scope") == "pc":
                    continue  # la separada de otra PC convive con la nueva federada
                other["coordinator"], other["coordinator_scope"] = False, None
                changed.append(other)
        want_scope = scope if on else None
        if bool(s.get("coordinator")) != on or s.get("coordinator_scope") != want_scope:
            s["coordinator"], s["coordinator_scope"] = on, want_scope
            changed.append(s)
        for x in changed:
            touch(x)
    if on and scope != "pc" and my_repo is not None:
        for other in _mirror_sessions():
            if other.get("coordinator") and other.get("coordinator_scope") != "pc" and _repo_identity(other) == my_repo:
                code, res = _mirror_forward(
                    other["pc"], "PUT", f"/sessions/{other['session_id']}/coordinator", {"on": False}
                )
                if code != 200:
                    state.log(
                        f"apagar coordinadora remota {other['session_id'][:8]} en {other.get('pc')}: {res.get('error')}"
                    )
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
            tt = transcripts.turns(s["agent"], path, 1, leaf_id=transcripts.leaf_of(s))["meta"].get("title")
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
            if other_sid != sid and backend.proc_key(other) == backend.proc_key(ev):
                if other.get("source") == "sweep" or other_sid.startswith("pid-"):
                    # el placeholder del barrido es la misma sesion: lo que lo nombraba (una regla de
                    # cableado hecha al lanzarla, un link) pasa al sid real antes de darlo de baja
                    if any(repoint_refs(other_sid, sid)):
                        rules.publish()
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
    if s.get("title_source") == "user" or typed_here(s):
        return
    if not (s.get("last_attachment") or bad_title(s.get("title")) or s.get("title_source") == "prompt"):
        return
    if first := prompt_title(s):
        s["title"], s["title_source"] = first, "prompt"


def hook_prompt_submit(s: dict, ev: dict) -> None:
    set_state(s, "corriendo")
    s["stopped_by"] = None  # volvio a trabajar: la marca de detenida ya no cuenta
    s["last_denied"] = None  # pedido nuevo: lo denegado antes ya se resolvio o se descarto
    # pedido en curso: con esto se reconoce un Stop tardio del pedido anterior (stale_stop)
    s["prompt_id"] = ev.get("prompt_id")
    s["prompt_ts"] = s["last_event_ts"]
    if not transcripts.is_system_prompt(raw := ev.get("prompt", "")):
        set_last_prompt(s, raw, prompt_origin(s, raw))
        title_from_prompt(s)
    s["pending_id"] = None
    s["typing"] = False  # lo que habia en la caja ya se mando; screen_loop lo confirma en 5 s
    if s["agent"] == "coda":
        # turno nuevo: sin esto quedan los contadores del anterior (ver apply_turn)
        s.update({"tool_count": 0, "last_files": [], "last_cmd": None, "tool_errors": 0})


COMPACTING_MAX_S = 600  # si PostCompact no llega (coda se cae), la marca vence sola


def compacting(s: dict) -> bool:
    """La sesion esta compactando contexto (PreCompact sin PostCompact todavia)."""
    t = s.get("compacting")
    return bool(t) and time.time() - t < COMPACTING_MAX_S


def hook_stop(s: dict, ev: dict) -> None:
    if stale_stop(s, ev):
        state.log(
            f"Stop tardio de {s['session_id'][:8]} (pedido {str(ev.get('prompt_id'))[:8]}, ya corre "
            f"{str(s.get('prompt_id'))[:8]}): la tarjeta sigue corriendo"
        )
    elif compacting(s):
        state.log(f"Stop de {s['session_id'][:8]} durante una compactacion: la tarjeta sigue corriendo")
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
    set_needs(
        s,
        {
            "kind": "idle" if nt == "idle_prompt" else "permission" if nt == "permission_prompt" else nt,
            "detail": short(ev.get("message", ""), 300),
            "where": "terminal",
        },
    )


def coda_tool(s: dict, ev: dict, sub: bool = False) -> None:
    """PreToolUse de CODA: la herramienta que va a correr, a la tarjeta. Es la unica señal de
    avance durante el turno, porque CODA escribe el turno en su base recien al cerrarlo; al
    cerrarse, la transcripcion rehace estos contadores con el turno entero (turn_activity)."""
    tool = str(ev.get("tool_name") or "?")
    name = tool.lower()
    inp = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    if ev.get("auto_aprobado"):
        cmd = inp.get("command") or inp.get("cmd") or inp.get("file_path") or ""
        state.log(f"AUTO-APROBADO (hook coda) {s['session_id'][:8]}: {tool} {short(str(cmd), 160)}")
    s["tool_count"] = (s.get("tool_count") or 0) + 1
    if (s.get("needs") or {}).get("via") in ("tool", "screen"):
        # la herramienta que habia abierto el dialogo ya se contesto: corre otra
        set_state(s, "corriendo")
    if name in CMD_TOOLS:
        raw = str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " ")
        raw = CD_PREFIX_RE.sub("", raw).strip()
        if raw:
            s["last_cmd"] = short(raw, 120)
    if name in FILE_TOOLS:
        for ruta in tool_paths(inp):
            base = os.path.basename(ruta.replace("\\", "/").rstrip("/"))
            if base:
                s["last_files"] = [base, *[f for f in s.get("last_files") or [] if f != base]][:3]
    at, since = parse_ts(ev.get("host_ts")), parse_ts(s.get("state_since"))
    if s["state"] == "termino" and at and since and at > since:
        # una herramienta despues del cierre es un turno en curso: pasa cuando el UserPromptSubmit
        # no llego, y la base no lo corrige porque CODA no la toca hasta cerrar el turno. La
        # comparacion deja afuera un PreToolUse del turno anterior que llega despues del Stop
        set_state(s, "corriendo")
    if s["state"] == "corriendo":
        s["last_reply"] = f"usando {tool}" + (" (subagente)" if sub else "")
    if name in CODA_DIALOG_TOOLS and not sub:
        # estas herramientas abren SIEMPRE un dialogo «Approval Required» y no dejan un `ask` en el
        # log de coda: sin esto la tarjeta seguia en corriendo y nadie veia el pedido (medido el
        # 2026-10-04: propose_policy de una regla permanente para git reset --hard)
        detalle = short(json.dumps(inp, ensure_ascii=False), 300) if inp else ""
        set_needs(
            s,
            {
                "kind": "permission",
                "tool": tool,
                "detail": f"{CODA_DIALOG_TOOLS[name]} {detalle}".strip(),
                "where": "terminal",
                "via": "tool",
            },
        )
        s["needs"]["coda_at"] = f"tool:{ev.get('host_ts') or now()}"


# herramientas de coda que siempre piden aprobacion en su terminal, con lo que piden
CODA_DIALOG_TOOLS = {"propose_policy": "propone una regla de permisos permanente:"}

CODA_SENT_RETRY_S = (
    20  # tras contestar, si el permiso sigue abierto pasado este tiempo, la tarjeta vuelve a mostrar los botones
)
CODA_ASK_CAUSES = {
    "command-policy": "comando que pide confirmación",
    "unresolved-command": "comando que no pudo verificar",
}


def coda_log_activity(s: dict) -> bool:
    """Lo que dice el log de CODA (coda.activity), con el lock tomado; devuelve si cambio algo.

    Para toda tarjeta de CODA viva: el pedido de permiso abierto la pone en te_necesita, y al
    contestarse la devuelve a corriendo. Sin hooks, ademas, cuantas herramientas lleva el turno y
    cual corre (el comando y los archivos los da coda_tool, con hooks)."""
    act = coda.activity(s["pid"])
    if not act:
        return False
    before = (s["state"], s.get("needs"), s.get("tool_count"), s.get("last_reply"))
    if act["running"] and s["state"] == "termino":
        # el log muestra herramientas del turno abierto despues del cierre: se perdio el
        # UserPromptSubmit y la sesion quedo esperando (un permiso, por ejemplo) sin otro evento
        last, since = parse_ts(act.get("last_at")), parse_ts(s.get("state_since"))
        if last and since and last > since:
            set_state(s, "corriendo")
    if den := act.get("denied"):
        set_denied(
            s,
            {
                "tool": den["tool"],
                "motivo": CODA_ASK_CAUSES.get(den.get("cause") or "", den.get("cause") or ""),
                "detalle": s.get("last_cmd") or "",
                "at": den.get("at"),
                "fuente": "coda",
                "sub": den.get("sub"),
            },
        )
    ask = act.get("asking") if act["running"] else None
    needs = s.get("needs") or {}
    if ask and s["state"] in ("corriendo", "te_necesita"):
        detail = CODA_ASK_CAUSES.get(ask["cause"] or "", ask["cause"] or "")
        detail = " · ".join(x for x in (detail, "de un subagente" if ask["sub"] else "") if x)
        if needs.get("kind") != "permission" or needs.get("coda_at") != ask["at"]:
            set_needs(s, {"kind": "permission", "tool": ask["tool"], "detail": detail, "where": "terminal"})
            s["needs"]["coda_at"] = ask["at"]
        elif needs.get("where") == "enviado" and time.time() - (needs.get("sent_ts") or 0) > CODA_SENT_RETRY_S:
            # el Enter/Esc no resolvio el permiso (sigue abierto en el log): se devuelven los botones
            s["needs"] = {**needs, "where": "terminal"}
    elif s["state"] == "te_necesita" and needs.get("coda_at") and needs.get("via") not in ("tool", "screen"):
        # (el dialogo de una herramienta como propose_policy no figura en el log: lo cierra el
        # proximo PreToolUse o el fin del turno, no la ausencia de un `ask`)
        set_state(s, "corriendo" if act["running"] else "termino")
    if not s.get("hooked") and act["running"] and act["last_tool"]:
        s["tool_count"] = act["tools"]
        if s["state"] == "corriendo":
            s["last_reply"] = f"usando {act['last_tool']}" + (" (subagente)" if act["sub"] else "")
    return before != (s["state"], s.get("needs"), s.get("tool_count"), s.get("last_reply")) or bool(
        act.get("denied")
        and (s.get("last_denied") or {}).get("at") == act["denied"].get("at")
        and (s.get("last_denied") or {}).get("visto", "") >= (s.get("state_since") or "")
    )


def apply_hook(s: dict, ev: dict, name: str, created: bool) -> None:
    """Lo propio de cada evento de hook sobre una tarjeta que apply_event ya puso al dia (pid, cwd,
    transcripcion, ultimo evento). Se llama con el lock tomado."""
    if name == "SessionStart":
        if s["agent"] == "pi":
            set_state(s, "termino" if ev.get("pi_idle", True) else "corriendo")
        elif created:
            set_state(s, "termino")
    elif name == "PiBusy" and s["agent"] == "pi":
        set_state(s, "corriendo")
    elif name == "PiPromptStart" and s["agent"] == "pi":
        set_needs(s, {"kind": "pi_dialog", "detail": short(ev.get("message", ""), 300), "where": "terminal"})
    elif name == "PiPromptEnd" and s["agent"] == "pi":
        # Closing an idle dialog is not completion of a job: do not fire on_stop.
        if (s.get("needs") or {}).get("kind") == "pi_dialog":
            s["state"], s["state_since"], s["needs"] = ("termino" if ev.get("pi_idle") else "corriendo"), now(), None
    elif name == "UserPromptSubmit":
        hook_prompt_submit(s, ev)
    elif name == "Stop":
        hook_stop(s, ev)
    elif name == "Notification":
        hook_notification(s, ev)
    elif name == "PermissionRequest":
        pregunta = is_question(ev)
        set_needs(
            s,
            {
                # una pregunta con opciones no es un permiso: la tarjeta la muestra distinto
                "kind": "question" if pregunta else "permission",
                "tool": ev.get("tool_name"),
                "detail": first_question(ev) if pregunta else tool_detail(ev.get("tool_input")),
                "tool_use_id": ev.get("tool_use_id"),
                "where": "lienzo",
            },
        )
    elif name == "PermissionDecision":
        s["pending_id"] = None
        set_state(s, "corriendo")  # set_state ya limpia `needs` al salir de te_necesita
    elif name == "PermissionTimeout":
        if s["state"] == "te_necesita" and s.get("needs"):
            s["needs"]["where"] = "terminal"
        s["pending_id"] = None
    elif name == "PostToolUse":
        # con el id en null no hay con que emparejar y cualquier PostToolUse limpiaria el aviso:
        # AskUserQuestion pide permiso con tool_use_id null (medido el 2026-09-08), y su cierre lo
        # trae igual el PermissionDecision / PermissionTimeout
        tuid = (s.get("needs") or {}).get("tool_use_id")
        if s["state"] == "te_necesita" and tuid and tuid == ev.get("tool_use_id"):
            set_state(s, "corriendo")
    elif name == "PreToolUse" and s["agent"] == "coda":
        coda_tool(s, ev)
    elif name in ("PreCompact", "PostCompact") and s["agent"] == "coda":
        s["compacting"] = time.time() if name == "PreCompact" else None
    elif name == "Interrupt":
        set_state(s, "termino")
    elif name == "SessionEnd":
        marcar_muerta(s, avisar=False)  # /exit, logout o /clear: a proposito, no se avisa


def apply_event(ev: dict) -> None:
    name = ev.get("hook_event_name") or "?"
    sid = ev.get("session_id")
    if not sid or ev.get("agent_id"):
        return  # sin sesion, o subagente
    if ev.get("agent") == "coda" and coda.is_root(sid, ev.get("transcript_path") or None) is False:
        # subagente de CODA: corre en el mismo proceso con sesion propia en la base. No es una
        # tarjeta, pero lo que hace es trabajo de la madre y se ve en la de ella
        madre = coda.parent_of(sid, ev.get("transcript_path") or None)
        if name == "PreToolUse" and madre:
            with lock:
                s = sessions.get(madre)
                if s is not None and s["state"] != "muerta":
                    coda_tool(s, ev, sub=True)
                    touch(s)
        return
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
        # el evento trae el pid de un proceso que ya termino: quedo en la cola mientras el server
        # estaba apagado, o el agente lo escribio justo antes de cerrarse. Prueba que la sesion
        # existio, no que siga viva: sin esto la tarjeta nacia viva y sin pid, y refresh_alive no
        # toca las tarjetas sin pid, asi que no se moria nunca
        ev_pid_dead = bool(ev.get("pid")) and not backend.agent_alive(ev)
        if ev.get("pid") and not ev_pid_dead:
            claim_pid(s, ev)
        if ev.get("cwd") and (not s.get("cwd") or name == "SessionStart"):
            # el cwd de los hooks sigue al shell del agente (cambia con un cd de una tool);
            # el repo de la tarjeta se fija al arrancar y no baila
            s["cwd"] = ev["cwd"]
            apply_repo(s, ev["cwd"])
        if ev.get("transcript_path") or (s["agent"] == "pi" and "transcript_path" in ev):
            s["transcript_path"] = ev["transcript_path"]
        if s["agent"] == "pi":
            if "pi_leaf_id" in ev:
                s["pi_leaf_id"] = ev["pi_leaf_id"]
            if "pi_title" in ev and s.get("title_source") != "user":
                choose_title(s, ev["pi_title"])
        s["last_event"] = name
        s["last_event_ts"] = ev.get("host_ts") or now()
        if name == "SessionEnd":
            s["end_reason"] = ev.get("reason") if isinstance(ev.get("reason"), str) else None
        elif name == "SessionStart":
            s["end_reason"] = None
        s["alive"] = True
        s["dead_since"] = None
        apply_hook(s, ev, name, created)
        if created and DEAD_TARGETS:
            en_hilo(adopt_dead_target, dict(s))
        if ev_pid_dead and not (s.get("pid") and backend.agent_alive(s)):
            marcar_muerta(s, avisar=False)  # un evento viejo no dice que muriera trabajando ahora
        if created or name in ("SessionStart", "PiTree", "PiMetadata") or (s["agent"] == "pi" and name == "Stop"):
            r = read_transcript(s)
            if r is not None:
                apply_transcript(s, r)
            if s["agent"] == "pi" and name in ("SessionStart", "PiTree"):
                ts = r["turns"] if r else []
                s["last_prompt"] = (turn_prompt(ts[-1]) or "") if ts else ""
                s["last_reply"] = (ts[-1].get("final") or "") if ts else ""
                state.broadcast({"type": "transcript", "session_id": sid, "size": 0})
        touch(s)


# Eventos ya aplicados cuyo archivo Windows no dejo borrar (antivirus, indexador con el archivo
# abierto): sin esto la vuelta siguiente lo releia y lo volvia a aplicar cada 0,25 s (plan de
# refactor 1.6, E8). Se reintenta el borrado en cada vuelta y al lograrlo el nombre sale del set.
# Acotado: los nombres llevan la hora, y uno que lleva tanto sin poder borrarse es basura igual.
_aplicados: dict[str, None] = {}
APLICADOS_MAX = 1000


def _borrar_evento(n: str, p: str) -> None:
    try:
        os.remove(p)
    except FileNotFoundError:
        _aplicados.pop(n, None)
    except OSError as e:
        if n not in _aplicados:
            state.log(f"evento {n}: aplicado pero no se pudo borrar ({e}); no se vuelve a aplicar")
            _aplicados[n] = None
            while len(_aplicados) > APLICADOS_MAX:
                _aplicados.pop(next(iter(_aplicados)))
    else:
        _aplicados.pop(n, None)


def consume_events() -> None:
    while True:
        consume_once()
        time.sleep(0.25)


def consume_once() -> None:
    """Una vuelta sobre ~/.lienzo/events: aplica cada evento y borra su archivo."""
    try:
        names = sorted(os.listdir(EVENTS))
        state.avisar_si_cambia("events", None)
    except OSError as e:
        # sin carpeta de eventos no llega ningun hook: antes no se decia (plan de refactor 1.15)
        state.avisar_si_cambia("events", f"no se puede leer {EVENTS}: {e}; no llegan eventos de los hooks")
        names = []
    for n in names:
        p = os.path.join(EVENTS, n)
        if n.endswith(".tmp"):
            continue
        if n in _aplicados:
            _borrar_evento(n, p)  # ya aplicado: solo falta que Windows lo suelte
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
        _borrar_evento(n, p)  # aplicado o fallido, no se vuelve a intentar (como antes)


# --- pendientes de permiso -----------------------------------------------------------


def read_pending() -> dict:
    """Los pedidos de permiso que hay ahora en ~/.lienzo/pending, por request_id. Un archivo a
    medio escribir (el hook lo escribe con atomic_write, pero igual) se saltea, no rompe la vuelta,
    y se avisa una vez por archivo (se lee cada 0,5 s). Si no se puede listar el directorio levanta:
    no poder leer no es «no hay ninguno», y scan_pending conserva lo que tenia."""
    found = {}
    for n in os.listdir(PENDING):
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(PENDING, n), encoding="utf-8") as f:
                d = json.load(f)
            found[d["request_id"]] = d
        except FileNotFoundError:
            continue  # contestado o vencido entre el listdir y el open
        except (OSError, ValueError, KeyError, TypeError) as e:
            state.avisar_si_cambia(f"pending {n}", f"pending {n} ilegible, se saltea: {type(e).__name__}: {e}")
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
        scan_pending_once()
        time.sleep(0.5)


def scan_pending_once() -> None:
    """Una vuelta de scan_pending. Un error se loguea cuando cambia (avisar_si_cambia), no cada
    0,5 s como antes, y deja los pendientes como estaban."""
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
        state.avisar_si_cambia("scan_pending", None)
    except Exception:
        state.avisar_si_cambia("scan_pending", f"pendientes de permiso:\n{traceback.format_exc()}")


def public_pending() -> list[dict]:
    with lock:
        return [{k: v for k, v in d.items() if k != "nonce"} for d in pending.values()]


ANSWER_MAX = 2000  # techo de cada respuesta; una opcion es corta y el texto libre no es un ensayo


def question_answers(d: dict, answers: object) -> dict:
    """Lo que se le puede contestar a un AskUserQuestion: solo las preguntas que el pedido trae y
    solo texto. Lo que no coincide se descarta sin romper (el hook igual revalida antes de armar
    el updatedInput). El valor puede ser una opcion, varias separadas por coma (multiSelect) o
    texto libre, que es el "Other" del selector de la terminal."""
    if not isinstance(answers, dict):
        return {}
    preguntas = {q["question"] for q in questions_of(d)}
    return {
        k: strip_control(str(v))[:ANSWER_MAX]
        for k, v in answers.items()
        if k in preguntas and isinstance(v, str) and v.strip()
    }


def answer_pending(request_id: str, decision: str, reason: str = "", answers: object = None) -> tuple[int, dict]:
    with lock:
        d = pending.get(request_id)
    if d is None:
        return 410, {"ok": False, "error": "el pedido ya vencio o fue contestado"}
    body = {"nonce": d["nonce"], "decision": decision, "reason": reason, "answered": now()}
    elegido = question_answers(d, answers) if decision == "allow" else {}
    if elegido:
        body["answers"] = elegido
    atomic_write(os.path.join(ANSWERS, f"{request_id}.json"), json.dumps(body, ensure_ascii=False))
    if elegido:
        state.log(f"pregunta {request_id[:8]} contestada: {short(' | '.join(elegido.values()), 200)}")
    else:
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
    cands = [(m, p) for p in glob.glob(os.path.join(d, "*.jsonl")) if (m := _mtime(p)) is not None and m >= t0]
    if not cands:
        return None, None
    p = max(cands, key=lambda c: c[0])[1]
    return os.path.splitext(os.path.basename(p))[0], p


def _mtime(path: str) -> float | None:
    """getmtime que no levanta: entre el glob y el stat una transcripcion puede borrarse (un /clear,
    una limpieza), y el OSError cortaba el barrido entero (plan de refactor 1.5)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def guess_codex(cwd: str, t0: float, home: str = HOME) -> tuple[str | None, str | None]:
    """Codex mezcla todos los rollouts en un arbol por fecha, asi que hay que abrirlos: entre los
    de la TUI con el mismo cwd, gana el que arranco mas cerca del nacimiento del proceso. "El mas
    nuevo" se equivoca si despues de abrir la TUI corrio un `codex exec` en el mismo directorio."""
    nacio = t0 + BIRTH_MARGIN_S  # t0 ya viene con el margen restado
    best, best_gap = None, None
    for p in glob.glob(os.path.join(home, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl")):
        mtime = _mtime(p)
        if mtime is None or mtime < t0:
            continue
        try:
            with open(p, "rb") as f:
                first = json.loads(f.readline().decode("utf-8", errors="replace"))
        except OSError, ValueError:
            continue
        pl = first.get("payload") or {}
        if (pl.get("cwd") or "").lower() != cwd.lower():
            continue
        if pl.get("originator") not in (None, "codex-tui", "codex_cli_rs"):
            continue  # Codex Desktop (importados), codex_exec, app-server: no son la TUI
        birth = parse_ts(pl.get("timestamp") or first.get("timestamp"))
        gap = (birth.timestamp() if birth else mtime) - nacio
        if gap < -BIRTH_MARGIN_S:
            continue  # arranco antes que el proceso: no es suyo
        if best_gap is None or abs(gap) < abs(best_gap):
            best, best_gap = (pl.get("id") or pl.get("session_id"), p), gap
    return best or (None, None)


def guess_pi(cwd: str, born: float) -> tuple[str | None, str | None]:
    """Respaldo para una unica Pi en el proyecto, sin extension ni shell hijo observable.

    Pi puede reanudar un archivo anterior al proceso: importa su actividad, no el nombre
    ni la fecha de creacion. Verificar cwd e id de la cabecera, y actividad posterior al
    nacimiento. El llamador excluye proyectos compartidos por varias TUIs de Pi.
    """
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent")
    slug = "--" + re.sub(r"[\\/:]", "-", re.sub(r"^[\\/]", "", cwd)) + "--"
    folder = os.environ.get("PI_CODING_AGENT_SESSION_DIR") or os.path.join(agent_dir, "sessions", slug)
    candidates = []
    for path in glob.glob(os.path.join(folder, "*.jsonl")):
        try:
            modified = os.path.getmtime(path)
            if modified < born:
                continue
            with open(path, encoding="utf-8") as f:
                header = json.loads(f.readline(65536))
            if not isinstance(header, dict) or header.get("type") != "session":
                continue
            if not isinstance(header.get("id"), str) or not header["id"]:
                continue
            if not isinstance(header.get("cwd"), str) or os.path.normcase(header["cwd"]) != os.path.normcase(cwd):
                continue
            candidates.append((modified, header["id"], path))
        except OSError, ValueError:
            continue
    candidates.sort(reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
        return None, None
    return candidates[0][1], candidates[0][2]


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
    if agent == "pi":
        return guess_pi(cwd, born.timestamp()) if born else (None, None)
    if agent == "coda":
        return None, None  # la identidad de CODA viene exacta del log (coda.identity), no se adivina
    t0 = born.timestamp() - BIRTH_MARGIN_S if born else 0
    return guess_claude(cwd, t0, home) if agent == "claude" else guess_codex(cwd, t0, home)


def attach_transcript(s: dict, pi_session: tuple[str, str] | None = None, *, pi_guess: bool = False) -> None:
    """Tarjeta del barrido que todavia no tenia transcripcion (Codex crea el rollout recien en el
    primer turno, no al abrir): buscarla y, si aparece, tomar tambien el session_id real que trae,
    con lo que la tarjeta deja de llamarse `pid-N`. La busqueda va sin el lock; lo que escribe, con
    el lock y revalidando que la tarjeta siga siendo la misma."""
    if s["agent"] in ("pi", "coda") and not pi_session and not pi_guess:
        return
    cwd = s.get("cwd") or backend.cwd_of(s)
    sid, tpath = (
        pi_session
        if s["agent"] in ("pi", "coda") and pi_session
        else guess_transcript(s["agent"], cwd, s.get("started"), transcript_home(s))
    )
    if not tpath:
        return
    with lock:
        if s.get("hooked"):
            return  # la extension tiene prioridad sobre el entorno de un comando anterior
        if sid and sid != s["session_id"] and sid in sessions:
            return  # no vincular un archivo cuya sesion ya tiene otra tarjeta
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
        apply_repo(s, s["cwd"])
        if s.get("title_source") != "user":
            s["title"] = None
        refresh_from_transcript(s)
        touch(s)
        state.log(f"barrido: pid {s['pid']} ahora con transcripcion {os.path.basename(tpath)}")


def adopt_process(p: dict) -> None:
    """Agente vivo que ninguna tarjeta reclama: si su transcripcion ya tiene tarjeta, esa recupera
    el pid (venia de una corrida anterior); si no, se abre una nueva."""
    cwd = p.get("cwd") or backend.cwd_of(p)  # en tmux el cwd viene del pane; en win32, del backend
    if p["agent"] == "pi" and not p.get("pi_guess_allowed"):
        sid, tpath = p.get("pi_session") or (None, None)
    else:
        sid, tpath = (
            p.get("pi_session")
            or p.get("coda_session")
            or guess_transcript(p["agent"], cwd, p.get("created"), transcript_home(p))
        )
    with lock:
        s = sessions.get(sid) if sid else None
        if s is not None:
            s["backend"] = p.get("backend")  # la fuente que la vio es la que la maneja
            s["no_console"] = bool(p.get("no_console"))  # suelto (sin pane) = solo lectura
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
        s = new_session(sid or f"{'tmux' if p.get('backend') == 'tmux' else 'pid'}-{p['pid']}", p["agent"], "sweep")
        s.update(
            {
                "pid": p["pid"],
                "target": p.get("target"),
                "backend": p.get("backend"),
                "no_console": bool(p.get("no_console")),
                "agent_exe": p["exe"],
                "cwd": cwd,
                "transcript_path": tpath,
                "started": p.get("created") or now(),
                "in_vscode": p.get("in_vscode"),
                "orphan": p.get("orphan"),
            }
        )
        apply_repo(s, cwd)
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
    pi_cwds = {p["pid"]: os.path.normcase(backend.cwd_of(p) or "") for p in found if p["agent"] == "pi"}
    for p in found:
        cwd = pi_cwds.get(p["pid"])
        p["pi_guess_allowed"] = bool(cwd) and list(pi_cwds.values()).count(cwd) == 1
    with lock:
        known = {backend.proc_key(s) for s in sessions.values() if s.get("pid")}
        sin_transcripcion = [
            s
            for s in sessions.values()
            if s.get("source") == "sweep"
            and s.get("pid")
            and (not s.get("transcript_path") or s["agent"] in ("pi", "coda"))
        ]
    found_by_key = {backend.proc_key(p): p for p in found}
    for s in sin_transcripcion:
        observed = found_by_key.get(backend.proc_key(s), {})
        identity = observed.get("pi_session")
        if s["agent"] == "pi":
            if identity:
                if identity != (s["session_id"], s.get("transcript_path")):
                    attach_transcript(s, identity)
            elif not s.get("transcript_path") and observed.get("pi_guess_allowed"):
                attach_transcript(s, pi_guess=True)
        elif s["agent"] == "coda":
            # un /new o un resume en la TUI cambian la sesion del mismo proceso
            identity = observed.get("coda_session")
            if identity and identity != (s["session_id"], s.get("transcript_path")):
                attach_transcript(s, identity)
        else:
            attach_transcript(s)
    for p in found:
        if backend.proc_key(p) not in known:
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
    s["dead_since"] = None  # la muerte es de ahora (marcar_muerta conserva una hora ya puesta)
    # si murio con un encargo a medias, la coordinadora no recibe un Stop: se le avisa aparte
    marcar_muerta(s, avisar=True)
    return True


CODA_PANTALLA_QUIETA_S = 8  # una coda «corriendo» sin herramientas nuevas hace esto: puede estar en un cartel
CODA_PANTALLA_CADA_S = 10  # y la pantalla se mira como mucho cada tanto (es un subproceso)
_pantalla_mirada: dict[str, float] = {}


def coda_mirar_pantalla(s: dict) -> bool:
    """(Con el lock.) ¿Toca mirar la pantalla de esta coda en busca de un cartel de permiso? Sí si
    figura corriendo, sin nada pedido, quieta hace CODA_PANTALLA_QUIETA_S y no se miro hace poco."""
    if s.get("agent") != "coda" or s.get("state") != "corriendo" or s.get("needs") or not s.get("pid"):
        return False
    quieta = parse_ts(s.get("last_event_ts") or s.get("state_since"))
    ahora = time.time()
    if quieta and (dt.datetime.now().astimezone() - quieta).total_seconds() < CODA_PANTALLA_QUIETA_S:
        return False
    if ahora - _pantalla_mirada.get(s["session_id"], 0) < CODA_PANTALLA_CADA_S:
        return False
    _pantalla_mirada[s["session_id"]] = ahora
    return True


def coda_dialogo_en_pantalla(s: dict) -> bool:
    """(Sin el lock.) Si la pantalla de la coda muestra el cartel «Approval Required», la tarjeta pasa a
    te_necesita con el comando, para que se vea y el auto-aprobar lo tome. Es la red de abajo de las
    otras dos señales (el `ask` del log y propose_policy): medido el 2026-10-04, dos codas de la otra
    PC esperaron una hora un npm run build sin que el log mostrara el pedido. Devuelve si lo marco."""
    lineas = (read_screen(s).get("lines") or []) if s.get("pid") else []
    pantalla = "\n".join(lineas)
    if not coda_ask_open(pantalla):
        return False
    try:
        import pantalla_coda

        cmd = pantalla_coda.comando_visible(lineas) or ""
        clave = pantalla_coda.huella_comando(cmd) if cmd else "?"
    except Exception:  # el formato del cartel cambio: igual se marca, sin el comando
        cmd, clave = "", "?"
    with lock:
        if sessions.get(s["session_id"]) is not s or s.get("state") != "corriendo" or s.get("needs"):
            return False
        set_needs(
            s,
            {
                "kind": "permission",
                "tool": "bash",
                "detail": short(cmd, 300) or "pide aprobación en su terminal",
                "where": "terminal",
                "via": "screen",
            },
        )
        s["needs"]["coda_at"] = f"screen:{clave}"
        touch(s)
    state.log(
        f"{s['session_id'][:8]}: coda espera una aprobación en su terminal ({short(cmd, 80) or 'sin comando visible'})"
    )
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
        if s["agent"] == "coda" and s.get("alive") and s.get("pid") and s["state"] in ("corriendo", "te_necesita"):
            changed = coda_log_activity(s) or changed
        mirar_pantalla = coda_mirar_pantalla(s)
        dead_since = parse_ts(s["dead_since"]) if s["state"] == "muerta" else None
        if dead_since and (dt.datetime.now().astimezone() - dead_since).total_seconds() > DEAD_GRACE_S:
            drop_session(sid, "muerta hace mas de 60 s", muerta=True)
            return
        # transcripcion: el stat es barato (14 us) y va aca; leerla, no
        tp = s.get("transcript_path")
        try:
            st = os.stat(tp) if tp else None
        except OSError:
            st = None  # no existe (todavia, o ya no): igual que antes con el exists, sin la carrera

        sig = (st.st_size, int(st.st_mtime)) if st else None
        if st and s["agent"] == "coda":
            # base en WAL: lo nuevo va al -wal y la base cambia recien en el checkpoint
            try:
                wal = os.stat(tp + "-wal")
                sig += (wal.st_size, wal.st_mtime_ns)
            except OSError:
                pass  # sin -wal (CODA cerrado y base checkpointeada): alcanza con la base
        crecio = sig is not None and transcript_stat.get(sid) != sig
        if crecio:
            transcript_stat[sid] = sig
        elif changed:
            touch(s)
    if mirar_pantalla:
        coda_dialogo_en_pantalla(s)  # un subproceso: sin el lock
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


def remember_live_cards() -> None:
    """Las tarjetas vivas con hooks pasan al registro de restaurables (restore.py), con debounce
    adentro: un reinicio brusco no deja que el server vea la muerte. Nunca levanta."""

    def work() -> None:
        with lock:
            vivas = [
                dict(s)
                for s in sessions.values()
                if s.get("hooked") and s.get("alive") and restore.live_due(s.get("session_id"))
            ]
        if vivas:
            restore.remember_live(vivas)

    restore_guard(work)


def liveness_pass(sweep_every: float) -> None:
    """Una pasada de liveness: cada tarjeta, el registro de restaurables y, si toca, el barrido.
    Cada tarjeta y el barrido van con su propio try (plan de refactor 1.5, E7): antes un solo try
    envolvia todo, y una tarjeta que levantaba dejaba sin revisar a las que venian despues, sin
    registro de vivas y sin barrido, cada 2 s y para siempre. El error de una tarjeta se loguea
    cuando cambia (avisar_si_cambia), no en cada vuelta."""
    with lock:
        sids = list(sessions)
    for sid in sids:
        clave = f"liveness {sid[:8]}"
        try:
            check_liveness(sid)
            state.avisar_si_cambia(clave, None)
        except Exception:
            state.avisar_si_cambia(clave, f"{clave} fallo:\n{traceback.format_exc()}")
    remember_live_cards()  # nunca levanta (restore_guard)
    if sweep_every and time.time() - last_sweep > sweep_every:
        try:
            sweep_once()
            state.avisar_si_cambia("barrido", None)
        except Exception:
            state.avisar_si_cambia("barrido", f"barrido fallo:\n{traceback.format_exc()}")


def liveness_loop(sweep_every: float) -> None:
    while True:
        try:
            liveness_pass(sweep_every)
        except Exception:
            state.log(traceback.format_exc())
        time.sleep(2)


# --- envio ---------------------------------------------------------------------------


def save_attachment(sid: str, name: str, data: bytes) -> str:
    safe = "".join(c for c in os.path.basename(name) if c.isalnum() or c in "._- ") or "adjunto"
    d = os.path.join(ADJUNTOS, sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6)}-{safe}")
    with open(path, "xb") as f:
        f.write(data)
    return path


def send_blocked(s: dict) -> tuple[int, dict] | None:
    """Por que no se le puede escribir a esta sesion, o None si se puede."""
    if not s.get("pid") or not backend.agent_alive(s):
        return 409, {"ok": False, "error": "la sesion no tiene un PID vivo"}
    if s.get("orphan"):
        return 409, {"ok": False, "error": "la sesion perdio su terminal (huerfana): no hay consola donde escribir"}
    if s.get("stopped_by"):
        return 409, {
            "ok": False,
            "error": "esa sesion esta detenida (stopped): no recibe mensajes hasta que la habilites desde su tarjeta",
        }
    if s.get("no_console") and backend.is_tmux(s):
        return 409, {
            "ok": False,
            "error": "esta sesion corre fuera de tmux: se ve, pero no se le puede escribir (abrila con lienzo-new.sh)",
        }
    if s.get("no_console"):
        return 409, {
            "ok": False,
            "error": "esta sesion no tiene consola (panel de VS Code o app de escritorio): no se le puede escribir",
        }
    if s.get("agent") == "pi" and (s.get("needs") or {}).get("kind") == "pi_dialog":
        return 409, {"ok": False, "error": "Pi espera una respuesta en su terminal; cerrá ese dialogo primero"}
    if s.get("pending_id"):
        # el mismo pendiente puede ser un permiso o una pregunta con opciones: el mensaje lo dice
        if is_question(pending.get(s["pending_id"]) or {}):
            return 409, {"ok": False, "error": "esa sesion te esta preguntando algo; elegi una opcion primero"}
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
    except ValueError, OSError:
        return False


def compose_send(sid: str, text: str, attachments: list[str], agent: str | None = None) -> tuple[str, str, list[str]]:
    """(lo que se tipea, lo que escribio el usuario, los adjuntos). Un mensaje largo o de varias
    lineas no se tipea: se guarda como .md y viaja como 'Leé el archivo adjunto...' (§6.5). Para un
    agente de SHELL_READERS el aviso le pide leerlo con el shell y no con su herramienta `read`."""
    attachments = [a for a in (attachments or []) if _under_adjuntos(a)]  # M5: confinar al buzon
    text = (text or "").replace("\r", "")
    orig = text.strip()  # lo que escribio el usuario: es lo que se cuenta y lo que muestra la tarjeta
    if len(text) > LONG_TEXT or "\n" in orig:
        attachments = [save_attachment(sid, "mensaje.md", text.encode("utf-8"))] + list(attachments)
        text = ATTACH_WRAPPER_SHELL if agent in SHELL_READERS else ATTACH_WRAPPER
    parts = [strip_control(text).strip()] if text.strip() else []  # A4: sin teclas de control
    parts += [f"Adjunto: {a}" for a in attachments]
    return " ".join(parts), orig, attachments


def run_send(s: dict, final: str, enter: bool = True, key: str | None = None) -> tuple[int, dict]:
    """Teclea `final` en la consola del agente. En tmux es send-keys al pane; en Windows, el
    subproceso send.py por PID (un texto largo va por archivo: la linea de comando no lo aguanta).
    Sin `enter` solo se tipea (una opcion de un dialogo de la TUI se elige con la tecla del numero,
    sin confirmar); con `key="escape"` va esa tecla sola. (codigo, respuesta)."""
    sid, pid = s["session_id"], s["pid"]
    if backend.is_tmux(s):
        if not tmux.target_valid(s.get("target"), pid):
            return 409, {
                "ok": False,
                "error": "el pane cambió (¿tmux reinició?): no se envía, para no teclear en la terminal equivocada",
            }
        r = tmux.send(s.get("target"), final, enter=enter, key=key)
        if not r.get("ok"):
            state.log(f"send {sid[:8]} fallo (pane {s.get('target')}): {r.get('error')}")
            return 500, r
        return 200, r
    tf = save_attachment(sid, ".send.txt", final.encode("utf-8")) if len(final) > 2000 else None
    cmd = [PYTHON, os.path.join(HERE, "send.py"), "--pid", str(pid)]
    cmd += ["--text-file", tf] if tf else ["--text", final]
    if not enter:
        cmd.append("--no-enter")
    if key:
        cmd += ["--key", key]
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
        out = json.loads(r.stdout)
        if not isinstance(out, dict) or not isinstance(out.get("ok"), bool):
            raise TypeError("respuesta sin ok booleano")
        if r.returncode or not out["ok"]:
            state.log(f"send {sid[:8]} fallo (pid {pid}, codigo {r.returncode}): {out}")
            return 500, {**out, "ok": False, "error": out.get("error") or "send.py no pudo enviar"}
        return 200, out
    except subprocess.TimeoutExpired:
        return 500, {"ok": False, "error": "send.py no termino en 60 s"}
    except ValueError, TypeError:
        state.log(f"send {sid[:8]}: respuesta invalida: {r.stdout[:200]} {r.stderr[:200]}")
        return 500, {"ok": False, "error": "send.py devolvio una respuesta invalida"}
    except OSError as e:
        state.log(f"send {sid[:8]}: no se pudo ejecutar send.py: {e}")
        return 500, {"ok": False, "error": "no se pudo ejecutar send.py"}
    finally:
        if tf:
            try:
                os.remove(tf)
            except OSError:
                pass


def answer_dialog(s: dict, choice: int) -> tuple[int, dict]:
    """Elegir una opcion del dialogo de la TUI que la tarjeta esta mostrando. Se teclea el numero
    y nada mas: en los menus de Claude Code la tecla del numero elige y confirma de una, y un Enter
    de mas caeria en la caja de entrada. Se acepta solo un numero que este en el dialogo leido, no
    texto libre: esto escribe en la consola de otro proceso."""
    if frenado := send_blocked(s):
        return frenado
    d = s.get("dialog") or {}
    opciones = [o.get("n") for o in d.get("options") or []]
    if choice not in opciones:
        return 409, {"ok": False, "error": f"esa sesion no esta mostrando la opcion {choice}"}
    code, out = run_send(s, str(choice), enter=False)
    if code != 200:
        return code, out
    elegida = next((o.get("text") for o in d["options"] if o.get("n") == choice), str(choice))
    state.log(f"dialogo {s['session_id'][:8]}: {short(d.get('question') or '', 60)} -> {choice}. {short(elegida, 60)}")
    with lock:
        s["dialog"] = None  # el proximo barrido de pantalla (5 s) dira si quedo algo
        touch(s)
    out["choice"] = choice
    out["text"] = elegida
    return 200, out


def coda_ask_open(pantalla: str) -> bool:
    """¿La pantalla de CODA muestra un permiso abierto? El titulo «Approval Required» se sale de la
    pantalla cuando el comando es largo (un heredoc que escribe un archivo): por eso tambien vale el
    pie del cartel, que siempre esta abajo («Enter confirm · Esc deny»)."""
    return "Approval Required" in pantalla or ("Enter confirm" in pantalla and "Esc deny" in pantalla)


def answer_coda_ask(s: dict, decision: str) -> tuple[int, dict]:
    """Contestar desde la tarjeta el permiso que CODA pide en su terminal, con teclas: Enter para
    permitir, Esc para denegar. Antes de teclear se confirma en la pantalla que el dialogo sigue
    abierto: si ya se contesto en la terminal, un Enter caeria en la caja.

    Queda una ventana que esto NO cierra: entre read_screen (un subproceso, ~180 ms) y run_send el
    cartel pudo cerrarse y abrirse otro, y el Enter contesta al nuevo sin haberlo mirado. Cerrarla
    es el punto 0.2 del plan (aprobar contra el hash del comando que se vio). Lo que si se revalida,
    bajo el lock y despues del envio, es que el permiso siga siendo el mismo (coda_at) antes de
    marcarlo «enviado»: si en el medio llego otro, ese conserva sus botones."""
    if frenado := send_blocked(s):
        return frenado
    with lock:
        abierto = dict(s.get("needs") or {})
    coda_at = abierto.get("coda_at")
    if s.get("agent") != "coda" or not coda_at:
        return 409, {"ok": False, "error": "esa sesion no tiene un permiso de CODA abierto"}
    pantalla = "\n".join(read_screen(s).get("lines") or [])
    if not coda_ask_open(pantalla):
        return 409, {"ok": False, "error": "el dialogo de permiso ya no esta en la terminal"}
    if decision == "allow":
        code, out = run_send(s, "", enter=True)
    else:
        code, out = run_send(s, "", enter=False, key="escape")
    if code != 200:
        return code, out
    with lock:
        needs = s.get("needs") or {}
        mismo = sessions.get(s["session_id"]) is s and needs.get("coda_at") == coda_at
        if mismo:
            # coda_log_activity la devuelve a corriendo en cuanto la sesion vuelva a escribir en el log
            s["needs"] = {**needs, "where": "enviado", "sent_ts": time.time()}
            touch(s)
    state.log(
        f"permiso CODA {s['session_id'][:8]} -> {decision} ({abierto.get('tool')}) desde el lienzo"
        + ("" if mismo else "; mientras tanto el permiso cambio: el nuevo conserva sus botones")
    )
    return 200, out


def interrupt_session(s: dict) -> tuple[int, dict]:
    """Un Esc en la terminal de una sesion que esta corriendo: el turno se corta y la sesion queda
    esperando, con su contexto entero. Es lo que se hace al pegarle su trabajo a otra tarjeta para
    que no lo hagan las dos. Solo si esta corriendo: en una sesion quieta un Esc borra lo que haya en
    la caja, y a un permiso pendiente se le contesta, no se lo interrumpe."""
    if frenado := send_blocked(s):
        return frenado
    if s.get("state") != "corriendo":
        return 409, {"ok": False, "error": "esa sesion no esta corriendo: no hay nada que detener"}
    code, out = run_send(s, "", enter=False, key="escape")
    if code != 200:
        return code, out
    state.log(f"interrumpida {s['session_id'][:8]} (Esc): {short(s.get('last_prompt') or '', 60)}")
    with lock:
        touch(s)  # el estado lo dice la transcripcion (Interrupt) o el barrido, no se adivina aca
    return 200, out


def send_to_session(s: dict, text: str, attachments: list[str]) -> tuple[int, dict]:
    """Inyecta texto en la consola de la sesion y deja la tarjeta corriendo. Si `s` es de otra PC
    (mirror.owner_of, frente C, plan multi-PC §3.4), en cambio se reenvia con mirror.forward: la
    consola es de la PC dueña, no de esta, y send_blocked (que mira pid local) no aplica aca --lo
    hace el send_to_session del otro lado, con su propia tarjeta--. El subproceso (hasta 60 s) y
    la lectura del adjunto van fuera del lock; solo la tarjeta se toca con el lock."""
    sid = s["session_id"]
    owner = _mirror_owner(sid)
    if owner is not None:
        return _mirror_forward(owner, "POST", f"/sessions/{sid}/send", {"text": text, "attachments": attachments})
    if frenado := send_blocked(s):
        return frenado
    final, orig, attachments = compose_send(sid, text, attachments, agent=s.get("agent"))
    if not final:
        return 400, {"ok": False, "error": "texto vacio"}
    with lock:
        mark_sent(s, final)  # antes de teclear: el hook del pedido puede llegar antes que este vuelva
    code, out = run_send(s, final)
    if code != 200:
        with lock:
            s["sent_mark"] = None  # no entro: lo que se tipee despues es del usuario
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
        s["prompt_via"] = "lienzo"  # encargo: este si titula la tarjeta
        if s.get("last_event") != "SessionEnd":
            # tras SessionEnd la consola ya es de otra sesion (/clear, resume): lo que se tipea
            # llega a esa, y esta tarjeta no vuelve a 'corriendo' (la continua apply_event)
            set_state(s, "corriendo")
            s["stopped_by"] = None
        touch(s)
    return 200, out


def _name(s: dict) -> str:
    t = (s.get("title") or "").strip()
    return f"{s.get('repo')} · {t}" if t else f"{s.get('repo')} · {s['session_id'][:8]}"


def _notify_async(fn) -> None:
    """El aviso a las conectadas teclea en varias consolas (hasta 60 s cada una): fuera del pedido
    HTTP. Los tests lo reemplazan por una llamada directa."""
    en_hilo(fn)


def stopped_recipients(s: dict) -> list[dict]:
    """A quien avisar que `s` quedo detenida: la coordinadora de su repo (repo_coordinator: la
    separada de esta PC si hay, si no la federada, este donde este) y toda sesion, local o
    remota (mirror.py, frente C), que tenga una regla vigente con ella (la que le iba a mandar
    algo y la que esperaba su informe: una regla on_stop con `to` en otra PC vive alla, no aca).
    Sin la propia, sin la copia que se llevo su trabajo, sin repetir."""
    sid = s["session_id"]
    skip = {sid, s.get("stopped_by")}
    my_repo = _repo_identity(s)
    with lock:
        locales = list(sessions.values())
        reglas = list(state.rules.items)
    remotas = _mirror_sessions()
    local_by_id = {o["session_id"]: o for o in locales}
    remote_by_id = {o["session_id"]: o for o in remotas}
    out: dict[str, dict] = {}
    if coord := repo_coordinator(my_repo, s.get("pc"), locales, remotas):
        out[coord["session_id"]] = coord
    for r in reglas + _mirror_rules():
        if not r.get("enabled") or sid not in (r.get("from"), r.get("to")):
            continue
        other = r.get("to") if r.get("from") == sid else r.get("from")
        if other and (found := local_by_id.get(other) or remote_by_id.get(other)):
            out[other] = found
    return [o for k, o in out.items() if k not in skip]


def notify_stopped(s: dict, recipients: list[dict]) -> None:
    """Un renglon en la terminal de cada conectada: que no le manden nada ni cuenten con sus
    conexiones hasta que la habiliten. Con la copia nombrada si la hubo."""
    by = s.get("stopped_by")
    copia = sessions.get(by) if by and by != "user" else None
    motivo = f"su trabajo siguio en {_name(copia)} (copycat)" if copia else "la detuvieron desde el tablero"
    text = (
        f"Aviso del lienzo: la sesion {_name(s)} quedo detenida (stopped): {motivo}. No le mandes nada "
        "ni cuentes con sus conexiones hasta que la habiliten desde el tablero; lo que le llegue rebota."
    )
    for r in recipients:
        code, out = send_to_session(r, text, [])
        if code == 200:
            add_link(None, r["session_id"], text, "user")
        else:
            state.log(f"aviso de detenida a {r['session_id'][:8]} no salio: {out.get('error')}")


def set_stopped(s: dict, on: bool, by: str = "user") -> dict:
    """La llave stopped de una tarjeta. Prendida: un Esc si estaba corriendo, la marca (con quien la
    detuvo: la copia que se llevo el trabajo, o "user" desde el tablero), y el aviso a las
    conectadas. Mientras esta prendida send_blocked rechaza todo y las reglas hacia ella se saltean.
    Apagada: vuelve a recibir. Un pedido nuevo en su terminal tambien la apaga (hook_prompt_submit)."""
    if not on:
        with lock:
            s["stopped_by"] = None
            touch(s)
        state.log(f"habilitada {s['session_id'][:8]}: vuelve a recibir")
        return {"interrupted": False, "notified": []}
    with lock:
        # la marca va ANTES del Esc y en el mismo tramo con lock que la pregunta (plan de refactor
        # 1.4, E4): antes se miraba afuera y se marcaba despues de un envio de hasta 60 s, y dos
        # pedidos juntos mandaban dos Esc y avisaban dos veces. Si se puede interrumpir se decide
        # aca mismo, antes de marcar: con la marca puesta send_blocked ya dice que no.
        if s.get("stopped_by"):
            return {"interrupted": False, "notified": [], "already": True}
        hay_que_cortar = s.get("state") == "corriendo" and not send_blocked(s)
        s["stopped_by"] = by
        touch(s)
    interrupted = False
    if hay_que_cortar:
        code, out = run_send(s, "", enter=False, key="escape")
        interrupted = code == 200
        if not interrupted:
            state.log(f"detener: no pude interrumpir {s['session_id'][:8]} (pid {s['pid']}): {out}")
    recipients = stopped_recipients(s)
    if recipients:
        _notify_async(lambda: notify_stopped(s, recipients))
    state.log(
        f"detenida {s['session_id'][:8]} por {by[:8]}: "
        + ("interrumpida (Esc)" if interrupted else "no corria")
        + f"; avisadas {len(recipients)}"
    )
    return {"interrupted": interrupted, "notified": [_name(r) for r in recipients]}


def hand_over(target: dict, origin: dict, stop: bool = True) -> dict:
    """Despues de pegarle a `target` el trabajo de `origin`: la copia hereda el titulo con la marca
    copycat y queda apuntando a su origen. Con `stop` (lo normal) el origen pasa a stopped
    (set_stopped: Esc si corria, aviso a sus conectadas, no recibe nada mas); sin `stop`
    ("Duplicar") las dos siguen y el origen no se toca. Devuelve {interrupted} para el toast."""
    with lock:
        target["copycat_of"] = origin["session_id"]
    res = set_stopped(origin, True, by=target["session_id"]) if stop else {"interrupted": False}
    if title := (origin.get("title") or "").strip():
        set_title(target, title if title.endswith(" · copycat") else f"{title} · copycat")
    with lock:
        touch(target)
    state.log(
        f"traspaso {origin['session_id'][:8]} -> {target['session_id'][:8]}: "
        + ("origen detenida" if stop else "duplicada, el origen sigue")
    )
    return {"interrupted": bool(res.get("interrupted"))}


# --- pantalla (solo para las sugerencias de la TUI de Claude, DISENO §12) ------------------


def read_screen(s: dict) -> dict:
    """La pantalla del agente: capture-pane del pane en tmux, o el subproceso screen.py por PID en
    Windows (FreeConsole/AttachConsole no puede correr dentro del server)."""
    if backend.is_tmux(s):
        tgt = s.get("target")
        if not tmux.target_valid(tgt, s.get("pid")):
            return {"ok": False, "error": "el pane ya no es de esta sesión"}
        r = tmux.screen(tgt, scrollback=200)
        if r.get("ok"):
            r["lines"] = r.pop("text").splitlines()
            r["area"] = screen.input_area(r["lines"])
            r["dialog"] = screen.dialog(r["lines"])
        return r
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
        out = json.loads(r.stdout.strip() or "{}")
        state.avisar_si_cambia("screen.py", None)
        return out
    except subprocess.TimeoutExpired, ValueError:
        return {"ok": False, "error": "screen.py no respondio"}
    except OSError as e:
        # no se pudo ni lanzar el subproceso: antes levantaba, y screen_loop logueaba el traceback
        # cada 5 s por tarjeta, y contestar un permiso de coda daba 500 (plan de refactor 1.15)
        state.avisar_si_cambia("screen.py", f"no se pudo ejecutar screen.py: {e}")
        return {"ok": False, "error": "no se pudo ejecutar screen.py"}


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
        dlg = r.get("dialog") if r.get("ok") else None
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
            # un dialogo de opciones de la TUI ("Switch model?") no dispara ningun hook: sin esto
            # la sesion se queda esperando una tecla que nadie va a apretar. Si ademas hay un
            # pendiente de verdad (un permiso), manda ese: la tarjeta ya lo muestra
            d = None if s.get("pending_id") else dlg
            if s.get("suggestion") != sug or bool(s.get("typing")) != typing or s.get("dialog") != d:
                s["suggestion"] = sug
                s["typing"] = typing
                s["dialog"] = d
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


def restore_on_start(cards: list[dict]) -> None:
    """Al arrancar, las tarjetas guardadas cuyo proceso ya no existe: el server estuvo apagado (o la
    PC se reinicio) y no vio la muerte. Se dejan en el registro de restaurables, que es lo que la
    purga (o los 60 s de gracia) se iba a llevar, salvo las que terminaron a proposito (esas se
    olvidan). Una sola lectura y escritura del registro para todas."""

    def work() -> None:
        nuevas = []
        for card in cards:
            if restore.ended_on_purpose(card):
                restore.forget(card["session_id"])
            elif restore.eligible(card):
                nuevas.append(card)
        if nuevas:
            restore._store(nuevas, True)

    restore_guard(work)


def load_sessions() -> tuple[int, int]:
    """Carga sessions/*.json. Devuelve (purgadas, retituladas): purga las sin proceso vivo y sin
    eventos (o arranque) hace mas de STALE_SESSION_H horas (las demas sin proceso quedan 'muerta'
    y se van solas a los 60 s), y recalcula el titulo de las que quedan con la regla actual."""
    limit = dt.datetime.now().astimezone() - dt.timedelta(hours=STALE_SESSION_H)
    purged = 0
    sin_proceso: list[dict] = []
    for p in glob.glob(os.path.join(state.SESSIONS, "*.json")):
        try:
            # antes un JSON roto o sin session_id se salteaba sin log y quedaba en disco para siempre
            # (plan de refactor 1.15, E15): el roto se aparta (.corrupto-<ts>), lo demas se loguea
            s, err = state.leer_json(p)
            if err is not None or not isinstance(s, dict) or not isinstance(s.get("session_id"), str):
                if err is None:
                    state.log(f"tarjeta {os.path.basename(p)} sin session_id: no se carga")
                elif err == "ilegible":
                    state.log(f"tarjeta {os.path.basename(p)} no se pudo leer: no se carga")
                continue
            # tarjeta guardada por una version vieja: completar con la forma canonica, para que
            # /sessions no devuelva un campo presente en unas y ausente en otras
            for k, v in new_session(s["session_id"], s.get("agent") or "claude", s.get("source") or "hook").items():
                s.setdefault(k, v)
            if not s.get("repo_key") and s.get("cwd"):
                # tarjeta vieja (plan multi-PC F0): repo_key no estaba, pero el cwd ya alcanza
                # para calcularlo, a diferencia de pc (constante) que ya vino con el setdefault
                s["repo_key"] = identity.repo_key(s["cwd"])
            if s.get("state") not in STATES:
                s["state"], s["state_since"] = "termino", s.get("state_since") or now()
            if not backend.agent_alive(s):
                sin_proceso.append(dict(s))
                ref = parse_ts(s.get("last_event_ts") or s.get("started"))
                if ref is None or ref < limit:
                    os.remove(p)
                    purged += 1
                    continue
                # sesion de una corrida anterior sin proceso: se muestra muerta y se va sola. Va
                # directo y no por marcar_muerta/set_state, a proposito: no cierra turno ni avisa
                s["alive"] = False
                s["dead_since"] = s.get("dead_since") or now()
                s["state"] = "muerta"
            sessions[s["session_id"]] = s
        except OSError, ValueError, KeyError:
            state.log(f"tarjeta {os.path.basename(p)} no se pudo cargar:\n{traceback.format_exc()}")
            continue
    restore_on_start(sin_proceso)
    remember_live_cards()
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
