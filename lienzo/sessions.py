"""Registro de sesiones: tarjetas, estados (corriendo / te_necesita / termino / muerta), eventos de
los hooks, lectura de transcripciones, titulos, barrido de procesos, liveness, envio por inyeccion y
pantalla. Todo el estado vive en state.py. Las reglas ("cuando termine", "a las HH:MM") estan en
rules.py, que importa este modulo; para no cerrar el ciclo, este modulo las llama por dos ganchos que
rules.py rellena al importarse: on_turn_end(sid) y on_limit_notice(s)."""

from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
from copy import deepcopy

import backend
import captura
import claude_pipe_runtime
import codex_identity
import codex_queue
import conocimiento
import consulta
import hooks_eventos
import identity
import native_follow
import procs
import recientes
import restore
import screen
import state
import titulo_lanzado
import tmux
import transcripts

# las guess_* viven en agentes.py (modulo hoja); se reexportan aca con su nombre de siempre y las
# llamadas de este modulo pasan por estos nombres, que es lo que parchean las pruebas
# (monkeypatch.setattr(ses, "guess_transcript", ...)).
from agentes import (  # noqa: F401
    BIRTH_MARGIN_S,
    codex_desktop_threads,
    guess_claude,
    guess_codex,
    guess_pi,
    guess_transcript,
    perfil,
    transcript_home,
)
from state import (
    ADJUNTOS,
    ANSWERS,
    ATTACH_MAX_DAYS,
    DEAD_GRACE_S,
    DEAD_KEEP_S,
    HERE,
    LONG_TEXT,
    PENDING,
    PYTHON,
    STALE_SESSION_H,
    STATES,
    atomic_write,
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

# lo puro del texto de la tarjeta (titulos, adjuntos, preguntas, actividad del turno) vive en
# tarjeta_texto.py y se reexporta aca con su nombre de siempre
from tarjeta_texto import (  # noqa: F401
    _BIDI,
    ANSWER_MAX,
    ATTACH_WRAPPER,
    ATTACH_WRAPPER_SHELL,
    CD_PREFIX_RE,
    CMD_TOOLS,
    FILE_TOOLS,
    HEADING_RE,
    USELESS_TITLE_RE,
    USELESS_TITLE_WORDS,
    _titular,
    attachment_path,
    attachment_title,
    bad_title,
    choose_title,
    clean_prompt,
    first_question,
    is_question,
    prompt_mark,
    prompt_title,
    question_answers,
    questions_of,
    set_last_prompt,
    strip_control,
    title_from_prompt,
    tool_detail,
    tool_paths,
    turn_activity,
    turn_prompt,
    turn_say,
    typed_here,
    unwrap_attachment,
    using_tool,
)

last_sweep = 0.0

# Sólo presentación: nunca se persiste ni se calcula con el lock global tomado.
_envio_publico: dict[str, tuple[str, dict]] = {}
ENVIO_POLL_S = 5
ENVIO_POLL_MAX = 8
_envio_poll_at = -1e9
_envio_poll_cursor = 0


def _envio_firma(s: dict) -> str:
    campos = (
        "session_id",
        "agent",
        "pid",
        "transcript_path",
        "external",
        "stopped_by",
        "pending_id",
        "orphan",
        "no_console",
        "backend",
        "target",
        "distro",
        "alive",
        "envio_claude",
    )
    return json.dumps({k: s.get(k) for k in campos}, sort_keys=True, ensure_ascii=False)


def public_session(s: dict, *, calcular: bool = False) -> dict:
    """Recibe una copia local. Calcular sólo fuera del lock; eventos usan la última lectura válida.
    Las sesiones del espejo no pasan por acá: su PC dueña publica su capacidad."""
    firma = _envio_firma(s)
    sid = s["session_id"]
    if calcular:
        plan = puede_enviar(s)
        with lock:
            _envio_publico[sid] = (firma, dict(plan))
    else:
        cached = _envio_publico.get(sid)
        plan = (
            cached[1]
            if cached and cached[0] == firma
            else {
                "puede": False,
                "motivo": "capacidad de envío pendiente de comprobar",
                "transporte": None,
            }
        )
    view = {**s, "envio": dict(plan)}
    if perfil(s["agent"]).capabilities.get("terminalOnly"):
        # state sigue siendo el estado operativo del registro, no evidencia de un turno de agy.
        view["state_source"] = "unverified"
    # Sin rollout no existe un oráculo para distinguir recepción de falta de Enter.
    # Incluye avisos persistidos antes de que Codex moviera el escritor al daemon.
    if (
        s.get("agent") == "codex"
        and not s.get("transcript_path")
        and (s.get("needs") or {}).get("kind") == "sin_enviar"
    ):
        view["needs"] = {**s["needs"], "kind": "sin_transcripcion"}
    ext = s.get("external") or {}
    if ext.get("kind") == "claude-desktop":
        # Presentación derivada; cwd/identidad de memoria y título persistido quedan intactos.
        # Desktop se identifica por metadatos validados, nunca por el nombre scratch del cwd.
        if (s.get("repo") or "").startswith("scratch-"):
            view["repo"] = "Claude Desktop"
        if s.get("title_source") != "user" or not s.get("title"):
            view["title"] = ext.get("canal") or s.get("native_name") or "Sesión de Claude Desktop"
    return view


def refresh_envios() -> None:
    """A lo sumo 8 tarjetas por 5 s, rotativas. Sólo consulta; nunca encola ni reintenta.
    IO de capacidad/rollout fuera del lock. Una respuesta tardía no pisa otra tarjeta/envío."""
    global _envio_poll_at, _envio_poll_cursor
    tick = time.monotonic()
    with lock:
        if tick - _envio_poll_at < ENVIO_POLL_S:
            return
        _envio_poll_at = tick
        cards = list(sessions.values())
        vivos = set(sessions)
        for sid in list(_envio_publico):
            if sid not in vivos:
                del _envio_publico[sid]
        start = _envio_poll_cursor % len(cards) if cards else 0
        elegidas = (cards[start:] + cards[:start])[:ENVIO_POLL_MAX]
        _envio_poll_cursor = (start + len(elegidas)) % len(cards) if cards else 0
        work = [(s, deepcopy(s)) for s in elegidas]
        local_cards = [dict(s) for s in cards]
    try:
        claude_pipe_runtime.reap(local_cards)
        state.avisar_si_cambia("claude pipe cleanup", None)
    except Exception:
        state.avisar_si_cambia("claude pipe cleanup", traceback.format_exc())
    for card, snap in work:
        try:
            before = public_session(snap)["envio"]
            view = public_session(snap, calcular=True)
            field = "envio_claude" if snap.get("agent") == "claude" else "envio_codex"
            old = snap.get(field) or {}
            result = None
            # Expirado es terminal para el sondeo; confirmar() sigue disponible explícitamente.
            if (
                old.get("transporte") != "tecleo"
                and old.get("envio_id")
                and not old.get("confirmacion_final")
                and old.get("estado") in ("pendiente", "encolado", "sin_confirmacion")
            ):
                result = (claude_pipe_runtime.confirm if field == "envio_claude" else codex_queue.confirmar)(
                    old["envio_id"]
                )
                if result["estado"] == "desconocido" and time.time() - old.get("at", time.time()) > 600:
                    result = {
                        **old,
                        "estado": "sin_confirmacion",
                        "motivo": "confirmación no disponible tras reinicio; no se reintenta",
                    }
            with lock:
                if sessions.get(snap["session_id"]) is not card:
                    continue
                changed = False
                if result and result["estado"] != "desconocido" and card.get(field) == old:
                    final = result["estado"] == "entregado" or (
                        result["estado"] == "sin_confirmacion"
                        and time.time() - old.get("at", time.time()) > codex_queue.CONFIRM_LIMIT_S
                    )
                    updated = {**old, **result, "confirmacion_final": final}
                    if updated != old:
                        card[field] = updated
                        changed = True
                    import entregas_informes

                    reconciled = False
                    for rule in rules.items:
                        if rule.get("to") == snap["session_id"]:
                            reconciled |= entregas_informes.confirmar_envio(rule, old["envio_id"], result, now())
                    if reconciled:
                        rules.save(strict=True)
                        rules.publish()
                if hooks_eventos.stale_send_notice(card):
                    transcript_stat.pop(card["session_id"], None)
                if changed or (before != view["envio"] and _envio_firma(card) == _envio_firma(snap)):
                    touch(card)
            state.avisar_si_cambia(f"envio {snap['session_id']}", None)
        except Exception:
            state.avisar_si_cambia(f"envio {snap['session_id']}", traceback.format_exc())


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


def repo_coordinator(repo: str | None, local: list[dict], remote: list[dict]) -> dict | None:
    """La coordinadora del repo, independientemente de la PC donde corre."""
    if repo is None:
        return None
    return next(
        (o for o in (*local, *remote) if o.get("coordinator") and _repo_identity(o) == repo),
        None,
    )


SHELL_READERS = ("coda",)


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


# --- registro de sesiones -------------------------------------------------------


def save_session(s: dict) -> None:
    atomic_write(os.path.join(state.SESSIONS, f"{s['session_id']}.json"), json.dumps(s, ensure_ascii=False, indent=1))


def add_link(
    src: str | None, dst: str, text: str, kind: str = "send", rule_id: str | None = None, consulta: str | None = None
) -> None:
    """kind: send (inyeccion manual entre sesiones) | native (canal Claude<->Claude por SendMessage) |
    rule (nacido de una regla 'cuando termine' / 'a las HH:MM'; trae rule_id) | user (lo que el
    usuario escribio desde el SendBox del lienzo: from None, solo se ve en la pestana Conexiones) |
    consulta (una vuelta de una consulta entre investigadores, consulta.py; trae `consulta`)."""
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
    if consulta:
        link["consulta"] = consulta
    links.add(link)


def apply_repo(s: dict, cwd: str) -> None:
    """`repo` (para mostrar) y `repo_key` (identidad de la coordinadora: remote normalizado, o la
    carpeta si no hay remote) de un mismo cwd, siempre juntos: si se pisaran por separado quedan
    desincronizados y dos sesiones del mismo remote en carpetas distintas dejan de compartir
    coordinadora (plan multi-PC, §3.6)."""
    s["repo"] = repo_of(cwd)
    s["repo_key"] = identity.repo_key(cwd)


def cuotas_de_sesiones() -> dict:
    """{agente: "agotada hasta HH:MM"} por cada agente con una tarjeta viva de ESTA PC cuyo limite de
    uso sigue vigente (limit_until en el futuro), o «agotada» si su ultimo error es de cuota sin hora.
    Lo usa health.cuotas para la tira de PCs (pedido de Ariel, 2026-10-04: lo mismo que coda para
    claude, codex y pi)."""
    ahora = dt.datetime.now().astimezone()
    out: dict = {}
    with lock:
        tarjetas = [dict(s) for s in sessions.values() if s.get("alive")]
    for s in tarjetas:
        agente = s.get("agent")
        hasta = parse_ts(s.get("limit_until"))
        if hasta and hasta > ahora:
            previo = parse_ts((out.get(agente) or "").removeprefix("agotada hasta ")) if out.get(agente) else None
            if not previo or hasta > previo:
                out[agente] = f"agotada hasta {hasta.strftime('%H:%M')}"
        elif any(p in (s.get("last_error") or "").lower() for p in ("quota exceeded", "sin cuota", "usage limit")):
            out.setdefault(agente, "agotada")
    return out


def coda_viva() -> bool:
    """¿Hay una tarjeta viva de coda en ESTA PC? health muestra la cuota de coda solo entonces (bug 10,
    2026-10-04: «sin cuota: coda» en rojo sin que nadie usara coda)."""
    with lock:
        return any(s.get("alive") and s.get("agent") == "coda" for s in sessions.values())


def remotes_de_sesiones() -> list[str]:
    """El remote `origin` de cada repo con una tarjeta viva de ESTA PC, sin repetir: health prueba la
    credencial de git solo de esos (bug 9, 2026-10-04: la tira avisaba por un proyecto ya cerrado)."""
    with lock:
        cwds = {s.get("cwd") for s in sessions.values() if s.get("alive") and s.get("cwd")}
    return sorted({u for u in map(identity.origin_url, cwds) if u})


def repos_de_remote(url: str) -> list[str]:
    """Las carpetas de las tarjetas vivas de ESTA PC cuyo `origin` es `url`, ordenadas. health corre
    el `git ls-remote` en la primera (el config local del repo puede cambiar el credential helper,
    bug 2026-10-07) y fija la cuenta de GitHub en todas (una segunda copia o worktree del mismo repo
    tambien pushea)."""
    with lock:
        cwds = sorted({s.get("cwd") for s in sessions.values() if s.get("alive") and s.get("cwd")})
    return [c for c in cwds if identity.origin_url(c) == url]


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
        if muerta and not card.get("external") and not restore.ended_on_purpose(card):
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
# heredaban las dos. Desde el 2026-10-16 se guarda en sucesion.json (guardar_sucesion) y sobrevive a
# un reinicio del server; las reglas quedan estacionadas en rules.json (parked_to / parked_from, con
# el estado que tenian en parked_was_enabled) hasta que una sucesora las hereda o la purga de las
# estacionadas hace mas de SUCESION_MAX_S (rules.purge_stale_xpc) se las lleva.
SUCESION_MAX_S = 24 * 3600
DEAD_TARGETS: dict[str, dict] = {}
# old_sid -> {"new", "ts"}: quien sucedio a quien, para resolver un envio a un id viejo (404 con
# `sucesora`). Desde el 2026-10-16 las dos tablas se guardan en ~/.lienzo/sucesion.json: en OpenSyync,
# tras reiniciar la PC, las reglas se perdieron y hubo que recablear todo a mano.
SUCESORAS: dict[str, dict] = {}


def _sucesion_path() -> str:
    return os.path.join(state.LIENZO, "sucesion.json")


def guardar_sucesion() -> None:
    """Escribe DEAD_TARGETS y SUCESORAS, sin lo vencido. Con el lock tomado; nunca levanta."""
    ahora = time.time()
    for tabla, clave in ((DEAD_TARGETS, "since"), (SUCESORAS, "ts")):
        for k in [k for k, v in tabla.items() if ahora - float(v.get(clave) or 0) > SUCESION_MAX_S]:
            tabla.pop(k, None)
    try:
        state.atomic_write(
            _sucesion_path(), json.dumps({"muertas": DEAD_TARGETS, "sucesoras": SUCESORAS}, ensure_ascii=False)
        )
    except OSError as e:
        state.log(f"no se pudo guardar sucesion.json: {e}")


def cargar_sucesion() -> int:
    """Al arrancar: vuelve a la memoria la sucesion guardada. Devuelve cuantas muertas esperan."""
    d, err = state.leer_json(_sucesion_path())
    if err is not None or not isinstance(d, dict):
        return 0
    with lock:
        for tabla, clave in ((DEAD_TARGETS, "muertas"), (SUCESORAS, "sucesoras")):
            datos = d.get(clave)
            if isinstance(datos, dict):
                tabla.update({k: v for k, v in datos.items() if isinstance(k, str) and isinstance(v, dict)})
        guardar_sucesion()
        return len(DEAD_TARGETS)


def sucesora_de(sid: str) -> str | None:
    """La sesion que hoy ocupa el lugar de `sid` (siguiendo la cadena), o None."""
    vistos = set()
    with lock:
        while sid in SUCESORAS and sid not in vistos:
            vistos.add(sid)
            sid = SUCESORAS[sid].get("new") or sid
    return sid if vistos else None


def park_rules_from(sid: str) -> int:
    """Deshabilita y marca (parked_from) las reglas cuyo ORIGEN es `sid`: su «cuando termine» vuelve
    a andar si la sesion se restaura. Antes se borraban al morir la tarjeta."""
    with lock:
        suyas = [r for r in rules.items if r.get("from") == sid and not r.get("parked_from")]
        for r in suyas:
            if not r.get("parked_to"):  # la que ya esperaba al destino guarda su estado de antes
                r["parked_was_enabled"] = bool(r.get("enabled"))
            r["parked_from"], r["parked_since"], r["enabled"] = sid, now(), False
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
    return len(suyas)


def retake_rules_from(old: str, new: str) -> int:
    """Las reglas estacionadas con origen `old` pasan a salir de `new`, habilitadas."""
    with lock:
        suyas = [r for r in rules.items if r.get("parked_from") == old]
        for r in suyas:
            r["from"] = new
            r.pop("parked_from", None)
            r.pop("archived_at", None)
            r.pop("disabled_reason", None)
            if not r.get("parked_to"):  # con el destino tambien muerto, sigue esperando a la otra
                # vuelve como estaba: una de un solo disparo que ya salio, o apagada a mano, sigue apagada
                r["enabled"] = r.pop("parked_was_enabled", True)
                r.pop("parked_since", None)
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
        state.log(f"{len(suyas)} reglas de {old[:8]} ahora salen de {new[:8]}")
    return len(suyas)


def park_rules_to(sid: str) -> int:
    """Deshabilita y marca (parked_to) las reglas que avisan a `sid`. Devuelve cuantas."""
    with lock:
        suyas = [r for r in rules.items if r.get("to") == sid and not r.get("parked_to")]
        for r in suyas:
            if not r.get("parked_from"):
                r["parked_was_enabled"] = bool(r.get("enabled"))
            r["parked_to"], r["parked_since"], r["enabled"] = sid, now(), False
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
    return len(suyas)


def retarget_rules(old: str, new: str) -> int:
    """Las reglas que avisaban a `old` (estacionadas o no) pasan a avisar a `new`, habilitadas."""
    with lock:
        suyas = [
            r
            for r in rules.items
            if old in (r.get("to"), r.get("parked_to")) and (old != new or r.get("parked_to") == old)
        ]
        for r in suyas:
            r["to"] = new
            r.pop("to_pc", None)  # se vuelve a identificar con el snapshot del destino nuevo
            r.pop("parked_to", None)
            r.pop("archived_at", None)
            r.pop("disabled_reason", None)
            if not r.get("parked_from"):
                # la que sigue con el origen estacionado espera a su sucesora (retake_rules_from)
                r["enabled"] = r.pop("parked_was_enabled", True)
                r.pop("parked_since", None)
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
        state.log(f"{len(suyas)} reglas que avisaban a {old[:8]} ahora avisan a {new[:8]}")
    return len(suyas)


_norm_cwd = identity.norm_cwd


def _prioridad_sucesora(old: str, v: dict, s: dict, solo_titulo: bool = False) -> tuple | None:
    """Orden para elegir de quien es sucesora `s` (mayor gana), o None si no puede serlo. Con varios
    frentes del mismo agente en la misma carpeta (las rondas de OpenSyync) «la mas nueva» elegia mal:
    primero el mismo id (un resume que lo conserva), despues una restaurada desde el lienzo (la mas
    vieja primero: se relanzan de a una), despues el mismo titulo; la muerta mas nueva solo desempata.

    Sin ninguna de las tres no es sucesora: una sesion abierta a mano en la carpeta de un frente
    cerrado heredaba sus reglas y le mandaba informes vacios a la coordinadora (2026-10-22). El titulo
    cuenta solo si lo puso el lienzo (lanzada con ese titulo, o renombrada a el: set_title). Con
    `solo_titulo` (un renombre) solo vale el titulo: la restaurada espera a su proceso relanzado."""
    if v.get("agent") != s.get("agent") or _norm_cwd(v.get("cwd")) != _norm_cwd(s.get("cwd")):
        return None
    mismo_id = old == s["session_id"]
    restaurada = float(v.get("restaurada") or 0)
    mismo_titulo = bool(v.get("title")) and s.get("title_source") == "user" and v.get("title") == s.get("title")
    if not (mismo_titulo if solo_titulo else mismo_id or restaurada or mismo_titulo):
        return None
    return (mismo_id, restaurada > 0, -restaurada, mismo_titulo, float(v.get("since") or 0))


def sucesora_por_titulo(s: dict) -> bool:
    """¿Hay una muerta que `s` heredaria por su titulo? Con el lock. Barato: lo mira set_title antes de
    lanzar el hilo. Una provisoria del barrido (`pid-N`) no: al llegar su id real se da de baja y
    SUCESORAS y las otras PCs quedarian apuntando a un id que ya no existe."""
    if s["session_id"].startswith(("pid-", "tmux-")):
        return False
    return any(_prioridad_sucesora(old, v, s, solo_titulo=True) for old, v in DEAD_TARGETS.items())


def adoptar_por_titulo(sid: str, titulo: str) -> str | None:
    """El hilo de un renombre: si la tarjeta sigue con ese titulo (un segundo renombre rapido lo
    cancela), hereda de la muerta con el mismo titulo."""
    with lock:
        s = sessions.get(sid)
        copia = dict(s) if s is not None and s.get("title") == titulo and s.get("title_source") == "user" else None
    return adopt_dead_target(copia, solo_titulo=True) if copia else None


def adopt_dead_target(s: dict, solo_titulo: bool = False) -> str | None:
    """Si `s` (recien nacida) es la sucesora de una sesion que murio con reglas (mismo agente, misma
    carpeta, hace menos de SUCESION_MAX_S; ver _prioridad_sucesora), hereda sus reglas aca y en las
    otras PCs, las que le avisaban y las suyas, y su titulo. Devuelve el id viejo, o None."""
    ahora = time.time()
    # El barrido puede recuperar el mismo id sin un registro de sucesión vigente.
    retake_rules_from(s["session_id"], s["session_id"])
    with lock:
        parked_to = any(r.get("parked_to") == s["session_id"] for r in rules.items)
    if parked_to:
        retarget_rules(s["session_id"], s["session_id"])
    with lock:
        for k in [k for k, v in DEAD_TARGETS.items() if ahora - v["since"] > SUCESION_MAX_S]:
            DEAD_TARGETS.pop(k, None)
        candidatas = [
            (p, old)
            for old, v in DEAD_TARGETS.items()
            if (p := _prioridad_sucesora(old, v, s, solo_titulo)) is not None
        ]
        if not candidatas:
            return None
        old = max(candidatas)[1]
        # la elegida se reserva antes de soltar el lock: si otra sucesora ya se la llevo, esta no
        # hereda (con un pop a secas las dos seguian adelante y las dos re-apuntaban las reglas)
        muerta = DEAD_TARGETS.pop(old, None)
        if muerta is None:
            return None
        new = s["session_id"]
        if old != new:
            SUCESORAS[old] = {"new": new, "ts": ahora}
        guardar_sucesion()
        real = sessions.get(new)
        if real is not None and muerta.get("title") and real.get("title_source") != "user":
            real["title"], real["title_source"] = muerta["title"], "user"
            touch(real)
    retarget_rules(old, new)  # toma el lock por dentro; el forward a otras PCs, no
    retake_rules_from(old, new)
    if mirror:
        for pc in mirror.MIRROR.peer_ids():
            code, res = mirror.MIRROR.forward(pc, "POST", "/rules/retarget", {"old": old, "new": new})
            if code != 200:
                state.log(f"heredar reglas de {old[:8]} en {pc}: {code} {(res or {}).get('error')}")
    state.log(f"sesion {new[:8]} sucede a {old[:8]} ({muerta.get('title') or muerta.get('cwd')})")
    if old != new:
        with lock:
            vieja = sessions.get(old)
            sigue = vieja is not None and not vieja.get("alive")
        if sigue:  # la muerta conservada en el tablero (conservar_muerta) ya tiene quien la reemplace
            drop_session(old, f"sucedida por {new[:8]}")
    return old


def estacionar(card: dict) -> None:
    """Lo que deja una muerta para su sucesora: las reglas que le AVISABAN y las SUYAS quedan
    estacionadas y las hereda su sucesora real (un resume, un frente restaurado tras reiniciar la PC,
    o la coordinadora reabierta que el lienzo titula igual; ver _prioridad_sucesora), y queda en el
    registro de restaurables. Antes las suyas se borraban: al restaurar, ningun frente avisaba. Corre
    al borrar la tarjeta, o antes si la muerta se conserva en el tablero (conservar_muerta)."""
    sid = card["session_id"]
    n = park_rules_to(sid) + park_rules_from(sid)
    if n:
        with lock:
            DEAD_TARGETS[sid] = {
                "cwd": card.get("cwd"),
                "agent": card.get("agent"),
                "title": card.get("title") if card.get("title_source") == "user" else None,
                "since": time.time(),
            }
            guardar_sucesion()
        state.log(f"{n} reglas de y hacia {sid[:8]} quedan en espera de una sucesora")
    restore_on_drop(card, True)


def revivir_estacionada(s: dict) -> None:
    """La muerta volvio (un resume con el mismo id, o el barrido la vio viva): la marca de cerrada desde
    el tablero era de la vida anterior, y si se habia conservado recupera las reglas que estaciono
    (adopt_dead_target con el mismo id). Con el lock."""
    s["cerrada_a_mano"] = False
    if s.get("estacionada"):
        s["estacionada"] = False
        en_hilo(adopt_dead_target, dict(s))


def conservar_muerta(s: dict) -> bool:
    """Una muerta que se puede revivir (restaurar) queda en el tablero DEAD_KEEP_S, no DEAD_GRACE_S:
    tras un reinicio de la PC se ve que habia y se revive desde la tarjeta o la columna (pedido de
    Ariel, 2026-10-23). Las que terminaron a proposito (/exit, /clear, cerrada desde el tablero) no."""
    return (
        not s.get("external")
        and not s.get("cerrada_a_mano")
        and not restore.ended_on_purpose(s)
        and restore.eligible(s)
    )


def drop_session(sid: str, reason: str, muerta: bool = False) -> bool:
    """Borra la tarjeta. `reason` es solo para el log; `muerta` (el proceso desaparecio) es lo que
    decide si se recuerda para restaurar. False si no existia (no se toco nada, ni el registro)."""
    with lock:
        card = sessions.get(sid)
        if not forget_session(sid):
            return False
    links.remove(lambda l: sid in (l["from"], l["to"]))
    if muerta and card:
        if not card.get("estacionada"):
            estacionar(card)
    else:
        with lock:  # borrada a mano despues de estacionarse: no deja nada para una sucesora
            if DEAD_TARGETS.pop(sid, None) is not None:
                guardar_sucesion()
        with lock:
            for rule in rules.items:
                if sid in (rule.get("from"), rule.get("to")) and any(
                    informe.get("estado") != "integrado" for informe in rule.get("informes", [])
                ):
                    rule["enabled"] = False
            rules.save(strict=True)
        rules.remove(
            lambda r: (
                sid in (r.get("from"), r.get("to"))
                and not any(informe.get("estado") != "integrado" for informe in r.get("informes", []))
            )
        )
    state.log(f"tarjeta {sid[:8]} borrada ({reason})")
    if not (muerta and card and card.get("estacionada")):  # estacionar ya la recordo
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

    cambios = []
    for coll in (rules, links):
        anterior = [dict(item) for item in coll.items]
        n = 0
        for x in coll.items:
            for k in ("from", "to"):
                if x.get(k) == old_sid:
                    x[k] = new_sid
                    n += 1
        if n:
            cambios.append((coll, anterior, n))

    referencias = []
    for s in sessions.values():
        anterior = {k: s[k] for k in ("copycat_of", "stopped_by") if s.get(k) == old_sid}
        if anterior:
            referencias.append((s, anterior))
            s.update(dict.fromkeys(anterior, new_sid))
    guardados = []
    try:
        for coll, _, _ in cambios:
            coll.save(strict=True)
            guardados.append(coll)
        for s, _ in referencias:
            touch(s)
    except OSError:
        # Si falla la segunda lista, la primera ya pudo quedar en disco. Revertimos ambas en
        # memoria y compensamos la lista que alcanzó a guardarse para no dejar IDs mezclados.
        for coll, anterior, _ in cambios:
            coll.items[:] = anterior
        for s, anterior in referencias:
            s.update(anterior)
        for s, _ in referencias:
            try:
                touch(s)
            except OSError as e:
                state.log(f"no se pudo revertir referencias de {s['session_id'][:8]} tras fallo al re-apuntar: {e}")
        for coll in reversed(guardados):
            try:
                coll.save(strict=True)
            except OSError as e:
                state.log(f"no se pudo revertir {os.path.basename(coll.path)} tras fallo al re-apuntar: {e}")
        raise

    # las consultas abiertas tambien la nombran: sin esto la vigilancia da `old_sid` por muerta
    if consulta.reapuntar(old_sid, new_sid):
        state.log(f"consulta: {old_sid[:8]} sigue como {new_sid[:8]}")
    counts = {id(coll): n for coll, _, n in cambios}
    return counts.get(id(rules), 0), counts.get(id(links), 0)


def continue_session(old: dict, new: dict) -> bool:
    """La sesion nueva hereda el pid de la vieja y todo lo que la apuntaba: reglas y links donde la
    vieja era origen o destino pasan al sid nuevo, y la vieja se da de baja."""
    old_sid, new_sid = old["session_id"], new["session_id"]

    with lock:
        try:
            n_rules, n_links = repoint_refs(old_sid, new_sid)
        except OSError as e:
            state.log(f"sesion {old_sid[:8]} no continua como {new_sid[:8]}: no se guardaron reglas/enlaces: {e}")
            return False
        for k in ("pid", "agent_exe", "no_console", "external", "in_vscode", "coordinator", "pc"):
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
    return True


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
        "chrome": False,
        "cwd": None,
        "repo": "?",
        "repo_key": None,
        "branch": None,
        "title": None,
        "title_source": None,
        "copycat_of": None,
        "stopped_by": None,
        "sin_aviso": None,  # {a, desde, texto}: el proximo Stop no le avisa a `a` (un acuse, rules.fire_on_stop)
        "transcript_path": None,
        "transcript_bytes": None,
        "model": None,
        "screen_observation": None,
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
        "cerrada_a_mano": False,  # la cerro el tablero (kill_agent): su muerte no se avisa
        "estacionada": False,  # muerta conservada, con sus reglas en espera de una sucesora (estacionar)
        "end_reason": None,  # razon del SessionEnd (exit, logout, clear, other...); la usa restore.py
        "source": source,
        "hooked": source == "hook",
        "pending_id": None,
        "typing": False,
        "coordinator": False,
        "orphan": False,
        "in_vscode": False,
        "no_console": False,
        # ejecucion externa (un orquestador, `claude -p`): {"kind", "via", ...} o None. Se ve, no se le
        # escribe, no se la mata ni la mueven reglas: su control es el de quien la lanzo
        "external": None,
        # envio del lienzo esperando el UserPromptSubmit que lo confirma: {"at", "sin_consumo"} o None
        "envio_pendiente": None,
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


SALIDAS_A_PROPOSITO = ("/exit", "/quit", "exit", "quit")


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
    # conocimiento por proyecto (v5 §5.1): si la sesion trabajo un encargo, su nodo pasa a cerrada.
    # En hilo: se llama con el lock tomado y sesion_cerrada abre SQLite
    en_hilo(conocimiento.sesion_cerrada, s["session_id"])
    # un /exit o /quit es el pedido de cerrarse: el proceso que termina despues no murio a medias
    # (medido el 2026-10-04: cerrar cuatro codas con /exit mando cuatro avisos falsos de «murio»)
    salida = (s.get("last_prompt") or "").strip().lower() in SALIDAS_A_PROPOSITO
    # lo mismo un cierre pedido desde el tablero (POST /sessions/<sid>/kill, visto con U y X el 2026-10-22)
    if avisar and prev in ("corriendo", "te_necesita") and not salida and not s.get("cerrada_a_mano"):
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
        state.broadcast({"type": "session", "session": public_session(deepcopy(s))})
        captura.vista(s)  # la primera vez con carpeta: su proyecto y su sesion (anexo A de v5)
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


REFRESH_KEYS = (
    "needs",
    "envio_codex",
    "envio_pendiente",
    "sent_mark",
    "prompt_ts",
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
    hooks_eventos.confirmar_codex_desde_turno(s, t)
    if hooks_eventos.clear_stale_send_notice(s, t):
        set_state(s, "termino" if t.get("ended") else "corriendo")
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
        if not s.get("hooked"):
            entered = parse_ts(t.get("prompt_ts") if "prompt_ts" in t else t.get("ts_start"))
            previous = parse_ts(s.get("prompt_ts"))
            if (
                s.get("agent") == "codex"
                and not transcripts.is_system_prompt(p)
                and entered
                and (previous is None or entered > previous)
            ):
                s["prompt_ts"] = entered.isoformat()
            # sin hooks, el pedido sale de la transcripcion; el que tecleo el lienzo ya quedo como envio
            via = "lienzo" if s.get("sent_mark") and prompt_mark(p) == s["sent_mark"] else None
            captura.pedido(s, p, via, turno=t.get("id"))
    hooks_eventos.confirmar_codex_desde_turno(s, t)
    hooks_eventos.clear_stale_send_notice(s, t)
    if t.get("final") or not t.get("ended"):
        s["last_reply"] = turn_say(t) or s["last_reply"]
    if not turn_say(t) and (waiting := perfil(s["agent"]).waiting_text(t)):
        s["last_reply"] = waiting
    pregunta = perfil(s["agent"]).pregunta_al_terminar
    final = (t.get("final") or "").strip()
    turno = t.get("id") or t.get("ts_start") or f"final:{final[-200:]}"
    if (
        pregunta
        and (s.get("needs") or {}).get("kind") == "idle"
        and (not t.get("ended") or turno != s.get("pregunta_turno"))
    ):
        # otro turno (abierto, o ya cerrado entre dos lecturas): la pregunta se contesto, sin hook que lo diga
        set_state(s, "corriendo")
    if s["state"] != "muerta" and not s.get("needs"):
        set_state(s, "termino" if t.get("ended") else "corriendo")
        if (
            pregunta
            and s["state"] == "termino"
            and turno != s.get("pregunta_turno")
            and final.rstrip("*_ ").endswith("?")
        ):
            # una vez por turno: releer el mismo turno no la vuelve a pedir si ya se la saco
            s["pregunta_turno"] = turno
            set_needs(s, {"kind": "idle", "detail": short(final, 300), "where": "terminal"})


def _par_denegado(x: dict) -> list:
    # una denegacion de coda sale de su log y se identifica por su hora: el comando lo pone el
    # lienzo con el ultimo que vio, y despues de autorizarla ya no queda el anterior para comparar
    if x.get("fuente") == "coda" and x.get("at"):
        return [x.get("tool"), f"at:{x['at']}"]
    return [x.get("tool"), x.get("detalle") or ""]


def autorizar_denegado(s: dict) -> dict | None:
    """El humano autorizo desde el tablero lo que se le denego («Autorizar y que reintente»): la
    tarjeta lo anota y deja de mostrarlo. Sin esto, el aviso volvia en cada relectura del mismo turno,
    porque el mensaje de autorizacion entra en medio del turno y no hay pedido nuevo que lo limpie
    (medido el 2026-10-09 en ar-it33940). Vale hasta el proximo pedido (hook_prompt_submit), salvo el
    del propio mensaje de autorizacion: se llama ANTES de teclearlo y deja `autorizando`, porque su
    UserPromptSubmit puede llegar antes o despues que este llamado y en los dos casos borraba lo
    autorizado, y la relectura volvia a poner el aviso (medido el 2026-10-10 en chesstudia C).
    Devuelve lo que habia, para `deshacer_autorizacion` si el envio no entra; None si no habia aviso."""
    with lock:
        d = s.get("last_denied")
        if not d:
            return None
        antes = {"last_denied": d, "denied_ok": s.get("denied_ok")}
        ok = [list(p) for p in s.get("denied_ok") or []]
        for x in d.get("todas") or [d]:
            if _par_denegado(x) not in ok:
                ok.append(_par_denegado(x))
        s["denied_ok"] = ok[-32:]
        s["last_denied"] = None
        s["autorizando"] = True
        touch(s)
        return antes


def deshacer_autorizacion(s: dict, antes: dict) -> None:
    """El mensaje de autorizacion no entro: el aviso vuelve como estaba."""
    with lock:
        s.update(antes)
        s["autorizando"] = False
        touch(s)


def set_denied(s: dict, d: dict) -> None:
    ok = s.get("denied_ok") or []
    if ok:
        # lo ya autorizado no se vuelve a mostrar; lo nuevo del mismo turno, si
        todas = [x for x in d.get("todas") or [d] if _par_denegado(x) not in ok]
        if not todas:
            return
        if _par_denegado(d) in ok:
            d = {**d, **next((x for x in reversed(todas) if x.get("grave")), todas[-1])}
        d = {**d, "todas": todas, "n": len(todas)} if d.get("todas") else d
    """Marca en la tarjeta el ultimo permiso DENEGADO (por regla, politica o clasificador). Solo si
    es nuevo: la misma denegacion releida de la transcripcion no se vuelve a anunciar."""
    clave = (
        d.get("tool"),
        d.get("motivo") or d.get("cause"),
        d.get("detalle"),
        d.get("turno") or d.get("at"),
        d.get("n"),
    )
    prev = s.get("last_denied") or {}
    if (
        prev.get("tool"),
        prev.get("motivo") or prev.get("cause"),
        prev.get("detalle"),
        prev.get("turno") or prev.get("at"),
        prev.get("n"),
    ) == clave:
        return
    s["last_denied"] = {**d, "visto": now()}
    motivo = d.get("motivo") or d.get("cause") or "sin motivo"
    state.log(
        f"permiso DENEGADO a {s['session_id'][:8]}: {d.get('tool')} ({motivo})"
        + (f" {d['detalle']}" if d.get("detalle") else "")
    )
    # conocimiento por proyecto (v5 §5.1): un permiso denegado a una sesion que trabaja un encargo
    # queda como incidente `observado` en su ronda, una vez aunque llegue por el log de coda y por la
    # transcripcion (clave). En hilo: puede llamarse con el lock tomado
    clave = conocimiento.clave_permiso(s["session_id"], d.get("tool"), motivo, d.get("detalle"))
    if not conocimiento.visto(clave):
        en_hilo(
            _incidente,
            s["session_id"],
            f"permiso denegado: {d.get('tool')} ({motivo})"
            + (f": {short(d['detalle'], 200)}" if d.get("detalle") else ""),
            "permiso",
            {"tool": d.get("tool"), "motivo": motivo},
            clave,
        )


def _incidente(sid: str, texto: str, herramienta: str, datos: dict, clave: str | None = None) -> None:
    conocimiento.incidente_operativo(sid, texto, herramienta=herramienta, datos=datos, clave=clave)


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
        # la grave manda (la ultima grave), y la tarjeta ve todas: si no, un `rm -r` denegado quedaba
        # tapado por una denegacion inofensiva posterior y se autorizaba sin verlo (2026-10-04)
        principal = next((d for d in reversed(negadas) if d.get("grave")), negadas[-1])
        set_denied(
            s,
            {
                **principal,
                "n": len(negadas),
                "todas": negadas[-8:],
                "fuente": "transcript",
                "turno": t.get("id") or t.get("prompt_ts"),
            },
        )
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
        # conocimiento por proyecto (v5 §5.1): el error de API de una sesion con encargo es un
        # incidente de su ronda, una vez por turno (clave): apply_turn corre en cada refresco, y sin
        # mirar la clave antes lanzaria un hilo por refresco mientras el error siga en la tarjeta
        clave = f"incidente:api:{s['session_id']}:{t.get('id')}"
        if not conocimiento.visto(clave):
            en_hilo(
                _incidente,
                s["session_id"],
                f"error de API: {s['last_error']}",
                "api",
                {"error": s["last_error"], "turno": t.get("id")},
                clave,
            )


def model_of(agent: str, path: str) -> str | None:
    return perfil(agent).model(path, transcripts)


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
            heredar = sucesora_por_titulo(s)
        if heredar:
            # con el titulo de un frente muerto en esta carpeta pasa a ser su sucesora (_prioridad_sucesora)
            en_hilo(adoptar_por_titulo, s["session_id"], title)
        return
    with lock:
        s["title"] = s["title_source"] = None
    refresh_from_transcript(s)  # lee la transcripcion sin el lock y la aplica con el
    with lock:
        if s.get("title") is None:  # sin transcripcion: solo queda el pedido
            choose_title(s, None)


def set_coordinator(s: dict, on: bool) -> list[dict]:
    """Una coordinadora por repo: al elegirla se desmarcan las demas, incluso en otras PCs.
    Devuelve las tarjetas locales modificadas; cada peer publica sus propios cambios."""
    changed = []
    my_repo = _repo_identity(s)
    with lock:
        if on and my_repo is not None:
            for other in sessions.values():
                if other is s or not other.get("coordinator") or _repo_identity(other) != my_repo:
                    continue
                other["coordinator"] = False
                other.pop("coordinator_scope", None)
                changed.append(other)
        if bool(s.get("coordinator")) != on or "coordinator_scope" in s:
            s["coordinator"] = on
            s.pop("coordinator_scope", None)
            changed.append(s)
        for x in changed:
            touch(x)
    if on and my_repo is not None:
        for other in _mirror_sessions():
            if other.get("coordinator") and _repo_identity(other) == my_repo:
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


PENDING_HUERFANO_S = 120  # despues de expires_at: el hook ya lo hubiera borrado al vencer (hook.py, finally)


def purgar_huerfanos(found: dict) -> None:
    """Saca de `found` (y de disco, con su respuesta) los pedidos vencidos hace mas de
    PENDING_HUERFANO_S: el hook los borra al vencer, asi que uno que sigue ahi es de un hook que
    murio. Medido el 2026-10-15: tres de septiembre y octubre seguian en el tablero y el
    auto-aprobar los contestaba cada hora."""
    limite = dt.datetime.now().astimezone() - dt.timedelta(seconds=PENDING_HUERFANO_S)
    for rid, d in list(found.items()):
        vence = parse_ts(d.get("expires_at"))
        if vence is None or vence >= limite or not REQUEST_ID.fullmatch(str(rid)):
            continue
        del found[rid]
        for carpeta in (PENDING, ANSWERS):
            try:
                os.remove(os.path.join(carpeta, f"{rid}.json"))
            except FileNotFoundError:
                pass
        state.log(f"permiso {rid[:8]} vencido el {d.get('expires_at')} sin su hook: se borra ({d.get('tool_name')})")


def scan_pending_once() -> None:
    """Una vuelta de scan_pending. Un error se loguea cuando cambia (avisar_si_cambia), no cada
    0,5 s como antes, y deja los pendientes como estaban."""
    try:
        found = read_pending()
        purgar_huerfanos(found)
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


REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
TMUX_PANE = re.compile(r"%[0-9]{1,6}")  # el id de pane que exporta tmux: %0, %1, ...


def answer_pending(request_id: str, decision: str, reason: str = "", answers: object = None) -> tuple[int, dict]:
    # el id arma una ruta en ANSWERS: solo letras, digitos, guion y guion bajo (pentest 2026-09-07, I2)
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        return 400, {"ok": False, "error": "request_id invalido"}
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


def attach_transcript(s: dict, pi_session: tuple[str, str] | None = None, *, pi_guess: bool = False) -> None:
    """Tarjeta del barrido que todavia no tenia transcripcion (Codex crea el rollout recien en el
    primer turno, no al abrir): buscarla y, si aparece, tomar tambien el session_id real que trae,
    con lo que la tarjeta deja de llamarse `pid-N`. La busqueda va sin el lock; lo que escribe, con
    el lock y revalidando que la tarjeta siga siendo la misma."""
    if perfil(s["agent"]).identity_key is not None and not pi_session and not pi_guess:
        return
    cwd = s.get("cwd") or backend.cwd_of(s)
    sid, tpath = (
        pi_session
        if perfil(s["agent"]).identity_key is not None and pi_session
        else guess_transcript(s["agent"], cwd, s.get("started"), transcript_home(s))
    )
    if not tpath:
        return
    codex_proof = None
    if s["agent"] == "codex":
        probe_pid = s["pid"]
        codex_proof = codex_identity.transcript_identity(probe_pid)
        if not codex_proof["verified"] and not codex_proof.get("observed"):
            with lock:
                if sessions.get(s["session_id"]) is s and s.get("pid") == probe_pid:
                    previous = s.pop("codex_process_start", None)
                    reason = codex_proof["reason"]
                    if previous is not None or s.get("codex_identity_reason") != reason:
                        s["codex_identity_reason"] = reason
                        touch(s)
            return
        if (sid, tpath) != (codex_proof["thread"], codex_proof["path"]):
            return
    with lock:
        if codex_proof and s.get("pid") != probe_pid:
            return
        if s.get("hooked") and s["agent"] != "codex":
            return  # la extension tiene prioridad sobre el entorno de un comando anterior
        if sid and sid != s["session_id"] and sid in sessions:
            target = sessions[sid]
            if not codex_proof or target.get("agent") != "codex" or (target.get("pid") and backend.agent_alive(target)):
                return  # no robar el hilo de otro proceso vivo
            provisional = s
            hooks_eventos.claim_pid(target, {**s, "transcript_path": tpath})
            if target.get("pid") != probe_pid or sessions.get(provisional["session_id"]) is provisional:
                return  # no se pudo trasladar el cableado y retirar la provisoria
            for key in ("envio_codex", "envio_pendiente", "sent_mark"):
                if provisional.get(key) and not target.get(key):
                    target[key] = deepcopy(provisional[key])
            if not target.get("needs") and (provisional.get("needs") or {}).get("kind") == "sin_enviar":
                target["needs"] = deepcopy(provisional["needs"])
            s = target
        if sessions.get(s["session_id"]) is not s:
            return  # la borraron mientras buscabamos su transcripcion: no revivirla
        if sid and sid != s["session_id"] and sid not in sessions:
            viejo = s["session_id"]  # la tarjeta cambia de id: la de antes se olvida entera
            try:
                n_rules, n_links = repoint_refs(viejo, sid)
            except OSError as e:
                state.log(f"barrido: no cambio {viejo[:8]} a {sid[:8]}: no se guardaron reglas/enlaces: {e}")
                return
            if s["agent"] == "codex" and s.get("envio_codex") and s["envio_codex"].get("transporte") != "tecleo":
                s.setdefault("envios_codex_anteriores", {})[viejo] = s.pop("envio_codex")
            forget_session(viejo)
            state.broadcast({"type": "removed", "session_id": viejo})
            s["session_id"] = sid
            sessions[sid] = s
            if n_rules:
                rules.publish()
            if n_links:
                links.publish()
        if codex_proof and codex_proof["verified"]:
            s["codex_process_start"] = codex_proof["process_start"]
            s.pop("codex_identity_reason", None)
        elif codex_proof:
            s.pop("codex_process_start", None)
            s["codex_identity_reason"] = codex_proof["reason"]
        if codex_proof:
            s["codex_console_start"] = codex_proof["process_start"]
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
    codex_proof, adivinada = None, False
    if p["agent"] == "codex":
        codex_proof = codex_identity.transcript_identity(p["pid"])
        sid, tpath = (
            (codex_proof["thread"], codex_proof["path"])
            if codex_proof["verified"] or codex_proof.get("observed")
            else (None, None)
        )
    elif p["agent"] == "pi" and not p.get("pi_guess_allowed"):
        sid, tpath = p.get("pi_session") or (None, None)
    else:
        exacta = p.get("pi_session") or p.get("coda_session") or p.get("kiro_session")
        sid, tpath = exacta or guess_transcript(p["agent"], cwd, p.get("created"), transcript_home(p))
        adivinada = not exacta  # por carpeta y fecha: puede ser la de otra sesion
    with lock:
        s = sessions.get(sid) if sid else None
        if s is not None and adivinada and s.get("pid") not in (None, p["pid"]) and backend.agent_alive(s):
            # la transcripcion adivinada (la mas nueva de la carpeta) es de otra sesion viva: un
            # `claude -p` del mismo repo le pasaba su marca y la TUI de J quedo como «corrida
            # headless» con el /send en 409 (2026-10-22). Este proceso tiene su propia tarjeta
            state.log(f"barrido: {p['agent']} pid {p['pid']}: la transcripcion {sid[:8]} es de otra sesion viva")
            s, sid, tpath = None, None, None
        if s is not None:
            if codex_proof and s.get("pid") != p["pid"] and s.get("pid") and backend.agent_alive(s):
                state.log(f"barrido: hilo Codex {sid[:8]} observado en dos procesos; no se reasigna")
                return
            s["backend"] = p.get("backend")  # la fuente que la vio es la que la maneja
            if p.get("external"):
                s["external"] = p["external"]
            elif s.get("pid") != p["pid"] and (not s.get("pid") or not backend.agent_alive(s)):
                s["external"] = None  # otro proceso (vivo y personal) toma esta tarjeta: decide de cero
            s["no_console"] = bool(p.get("no_console") or s.get("external"))  # suelto (sin pane) = solo lectura
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
                revivir_estacionada(s)
                touch(s)
            if s.get("pid") == p["pid"] and bool(s.get("chrome")) != bool(p.get("chrome")):
                # la línea de comando es del proceso: también la tarjeta que ya existía antes del barrido
                s["chrome"] = bool(p.get("chrome"))
                touch(s)
            if codex_proof and codex_proof["verified"] and s.get("pid") == p["pid"]:
                s["codex_process_start"] = codex_proof["process_start"]
                s["transcript_path"] = codex_proof["path"]
                touch(s)
            if codex_proof and s.get("pid") == p["pid"]:
                s["codex_console_start"] = procs.creation_filetime(p["pid"])
            return
        s = new_session(sid or f"{'tmux' if p.get('backend') == 'tmux' else 'pid'}-{p['pid']}", p["agent"], "sweep")
        s.update(
            {
                "pid": p["pid"],
                "target": p.get("target"),
                "backend": p.get("backend"),
                "no_console": bool(p.get("no_console") or p.get("external")),
                "external": p.get("external"),
                "agent_exe": p["exe"],
                "chrome": bool(p.get("chrome")),
                "cwd": cwd,
                "transcript_path": tpath,
                "started": p.get("created") or now(),
                "in_vscode": p.get("in_vscode"),
                "orphan": p.get("orphan"),
            }
        )
        if codex_proof and codex_proof["verified"]:
            s["codex_process_start"] = codex_proof["process_start"]
        elif codex_proof:
            s["codex_identity_reason"] = codex_proof["reason"]
        if codex_proof:
            s["codex_console_start"] = procs.creation_filetime(p["pid"])
        apply_repo(s, cwd)
        if not tpath:
            s["title"] = "sesion sin transcripcion identificada"
        titulo_lanzado.aplicar(s)  # el titulo pedido en /sessions/launch, si nacio de uno
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
            if (s.get("source") == "sweep" or s["agent"] == "codex")
            and s.get("pid")
            and (not s.get("transcript_path") or perfil(s["agent"]).identity_key is not None)
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
        elif perfil(s["agent"]).identity_key is not None:
            # un /new o un resume en la TUI cambian la sesion del mismo proceso
            identity = observed.get(perfil(s["agent"]).identity_key)
            if identity and (
                identity != (s["session_id"], s.get("transcript_path"))
                or (s["agent"] == "codex" and not s.get("codex_process_start"))
            ):
                attach_transcript(s, identity)
        else:
            attach_transcript(s)
    for p in found:
        if backend.proc_key(p) not in known:
            adopt_process(p)
        elif (p.get("external") or {}).get("desktop"):
            marcar_desktop(p)
        else:
            limpiar_batch_antiguo(p)
    adopt_desktop_threads()


def limpiar_batch_antiguo(p: dict) -> None:
    """Repara sólo la marca genérica vieja, con comando interactivo comprobado del mismo proceso."""
    if p.get("agent") != "claude" or p.get("external") or backend.is_tmux(p):
        return
    marca = {"kind": "batch", "via": "comando"}
    with lock:
        antiguas = [
            s for s in sessions.values() if backend.proc_key(s) == backend.proc_key(p) and s.get("external") == marca
        ]
    if not antiguas:
        return
    comando = procs.procinfo.command_line(p["pid"])
    if not comando or procs.procinfo.claude_batch(procs.procinfo.command_args(comando)[1:]):
        return  # lectura fallida no demuestra que sea una TUI
    with lock:
        for s in antiguas:
            if backend.proc_key(s) != backend.proc_key(p) or s.get("external") != marca:
                continue
            s["external"], s["no_console"] = None, bool(p.get("no_console"))
            touch(s)
            state.log(f"{s['session_id'][:8]}: marca batch antigua limpiada; TUI interactiva (pid {p['pid']})")


def marcar_desktop(p: dict) -> None:
    """Una tarjeta que ya existia (de antes de reconocer las apps, o sin un hook desde entonces) y
    cuyo proceso el barrido ve como de la app de escritorio: pasa a solo lectura, y el nombre del
    canal se actualiza. No pisa la marca de un orquestador."""
    with lock:
        for s in sessions.values():
            ext = s.get("external") or {}
            # El registro validado del mismo proceso prevalece sobre el fallback -p.
            registered_desktop = (
                p["external"].get("kind") == "claude-desktop" and p["external"].get("via") == "registro"
            )
            generic_batch = ext.get("kind") == "batch" and ext.get("via") == "comando" and not ext.get("runner_pid")
            if backend.proc_key(s) != backend.proc_key(p) or (
                ext and not ext.get("desktop") and not (registered_desktop and generic_batch)
            ):
                continue
            if ext != p["external"] or not s.get("no_console"):
                s["external"], s["no_console"] = dict(p["external"]), True
                touch(s)
                state.log(f"{s['session_id'][:8]}: es de {p['external']['kind']} (pid {p['pid']}): solo lectura")


DESKTOP_THREAD_TTL_S = 2 * 3600  # un hilo de la app de Codex que no escribe su rollout en este tiempo deja de verse
CODEX_DESKTOP = {"kind": "codex-desktop", "via": "rollout", "desktop": True}


def es_hilo_desktop(s: dict) -> bool:
    """Tarjeta de un hilo de la app de Codex: sin proceso, la arma y la retira adopt_desktop_threads."""
    ext = s.get("external") or {}
    return ext.get("kind") == "codex-desktop" and ext.get("via") == "rollout"


def adopt_desktop_threads() -> None:
    """Los hilos de la app de escritorio de Codex como tarjetas de solo lectura. La app no tiene un
    proceso por hilo ni hooks (medido 2026-10-17: `[features] hooks = false` y un app-server
    compartido), asi que la tarjeta no tiene pid: estado, pedido y respuesta salen del rollout, que la
    liveness relee cuando crece. Se retira cuando su rollout lleva DESKTOP_THREAD_TTL_S sin escribirse.
    Mandarle un mensaje no se puede desde aca (seria por el app-server de la app: paso siguiente)."""
    hilos = codex_desktop_threads(time.time() - DESKTOP_THREAD_TTL_S)
    vigentes = {h["id"] for h in hilos}
    nuevas = []
    with lock:
        viejas = [sid for sid, s in sessions.items() if es_hilo_desktop(s) and sid not in vigentes]
        for h in hilos:
            if h["id"] in sessions:
                continue  # ya tiene tarjeta (la del hilo, o una TUI que lo retomo: esa manda)
            s = new_session(h["id"], "codex", "desktop")
            s.update(
                {
                    "no_console": True,
                    "external": dict(CODEX_DESKTOP),
                    "cwd": h["cwd"],
                    "transcript_path": h["path"],
                    "started": h["started"] or now(),
                }
            )
            apply_repo(s, h["cwd"])
            sessions[s["session_id"]] = s
            nuevas.append(s)
    for sid in viejas:
        drop_session(sid, f"hilo de Codex desktop sin actividad en {DESKTOP_THREAD_TTL_S // 3600} h")
    for s in nuevas:
        refresh_from_transcript(s)
        touch(s)
        state.log(f"codex desktop: hilo {s['session_id'][:8]} cwd={s['cwd']} (solo lectura, sin proceso)")


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
        revivir_estacionada(s)
        en_hilo(conocimiento.sesion_viva, s["session_id"])  # el nodo sesion vuelve a viva
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


def coda_mirar_fondo(s: dict) -> str | None:
    """(Con el lock.) El `coda_at` del permiso de fondo que hay que confirmar en la pantalla, o None.
    Un permiso de un subagente de fondo (`de_fondo`, ver _pedido_de_fondo) sigue figurando abierto en
    el log hasta el proximo evento de ese subagente, que puede tardar lo que tarde su comando: la
    pantalla es la que dice si el cartel sigue. Se mira como mucho cada CODA_PANTALLA_CADA_S."""
    n = s.get("needs") or {}
    if s.get("agent") != "coda" or s.get("state") != "te_necesita" or not n.get("de_fondo") or not s.get("pid"):
        return None
    ahora = time.time()
    if ahora - _pantalla_mirada.get(s["session_id"], 0) < CODA_PANTALLA_CADA_S:
        return None
    _pantalla_mirada[s["session_id"]] = ahora
    return n.get("coda_at")


def coda_fondo_en_pantalla(s: dict, coda_at: str) -> bool:
    """(Sin el lock.) Si el cartel de ese permiso de fondo ya no esta en la pantalla (se contesto aca o
    en la terminal), la tarjeta vuelve a termino sin disparar on_stop y ese pedido no se vuelve a
    levantar aunque el log lo siga mostrando. Devuelve si lo cerro."""
    if coda_ask_open("\n".join(read_screen(s).get("lines") or [])):
        return False
    with lock:
        n = s.get("needs") or {}
        if sessions.get(s["session_id"]) is not s or s.get("state") != "te_necesita" or n.get("coda_at") != coda_at:
            return False
        s["coda_fondo_hecho"] = coda_at
        s["state"], s["state_since"], s["needs"] = "termino", now(), None
        touch(s)
    state.log(f"{s['session_id'][:8]}: el permiso del subagente de fondo ya no está en la pantalla; vuelve a termino")
    return True


def coda_dialogo_en_pantalla(s: dict) -> bool:
    """(Sin el lock.) Si la pantalla de la coda muestra el cartel «Approval Required», la tarjeta pasa a
    te_necesita con el comando, para que se vea y el auto-aprobar lo tome. Es la red de abajo de las
    otras dos señales (el `ask` del log y propose_policy): medido el 2026-10-04, dos codas de la otra
    PC esperaron una hora un npm run build sin que el log mostrara el pedido. Devuelve si lo marco."""
    lineas = (read_screen(s).get("lines") or []) if s.get("pid") else []
    pantalla = "\n".join(lineas)
    if not coda_ask_open(pantalla):
        coda_compactacion_abortada(s, lineas)
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


CODA_COMPACTACION_ABORTADA = "Too few messages for compaction"


def _ultimo_mensaje_coda(lineas: list[str]) -> str:
    """El ultimo renglon con texto arriba de la caja vacia de coda («Ask anything...»), sin el panel de
    la derecha ni el borde «┃». Vacio si la caja tiene algo escrito (no muestra el placeholder)."""
    izq = [ln.split("│")[0].strip(" ┃▄█▀") for ln in lineas]
    caja = next((i for i in range(len(izq) - 1, -1, -1) if izq[i].startswith("Ask anything")), None)
    if caja is None:
        return ""
    return next((t for t in reversed(izq[:caja]) if t), "")


def coda_compactacion_abortada(s: dict, lineas: list[str]) -> bool:
    """(Sin el lock.) Un /compact con poca conversacion: coda muestra «Too few messages for compaction» y
    no manda PostCompact ni Stop (medido el 2026-10-10 con CODA 1.4.0; el PreCompact a veces si llega).
    Sin esto la tarjeta queda corriendo, y con la marca de compactacion el Stop del pedido siguiente
    tampoco la cierra. Solo cuenta si ese cartel es lo ultimo que dijo la coda: uno viejo, de un
    /compact anterior, no corta una compactacion de verdad. Vuelve a termino sin disparar on_stop:
    abortar un /compact no es terminar un trabajo."""
    if not _ultimo_mensaje_coda(lineas).startswith(CODA_COMPACTACION_ABORTADA):
        return False
    with lock:
        pidio = hooks_eventos.compacting(s) or (s.get("last_prompt") or "").strip() == "/compact"
        if sessions.get(s["session_id"]) is not s or not pidio or s.get("state") != "corriendo":
            return False
        s["compacting"] = None
        s["state"], s["state_since"] = "termino", now()
        touch(s)
    state.log(f"{s['session_id'][:8]}: coda abortó la compactación (pocos mensajes); la tarjeta vuelve a termino")
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
        if hooks_eventos.stale_send_notice(s):
            transcript_stat.pop(sid, None)  # reparar también tarjetas ya persistidas, sin crecimiento nuevo
        if (
            s["agent"] == "coda"
            and s.get("alive")
            and s.get("pid")
            and s["state"] in ("corriendo", "te_necesita", "termino")
        ):
            # tambien en termino: un workflow o un agente de fondo sigue pidiendo permisos con el turno
            # principal ya cerrado (ver coda_log_activity)
            changed = hooks_eventos.coda_log_activity(s) or changed
        mirar_pantalla = coda_mirar_pantalla(s)
        fondo = coda_mirar_fondo(s)
        dead_since = parse_ts(s["dead_since"]) if s["state"] == "muerta" else None
        edad = (dt.datetime.now().astimezone() - dead_since).total_seconds() if dead_since else 0
        if edad > DEAD_GRACE_S:
            if s.get("estacionada"):
                if edad > DEAD_KEEP_S:
                    drop_session(sid, f"muerta hace mas de {DEAD_KEEP_S // 3600} h", muerta=True)
                    return
            elif edad <= DEAD_KEEP_S and conservar_muerta(s):  # una vez: despues decide `estacionada`
                s["estacionada"] = True
                touch(s)
                en_hilo(estacionar, dict(s))  # escribe reglas y registro: fuera del lock
            else:
                drop_session(
                    sid, "muerta hace mas de 60 s" if edad <= DEAD_KEEP_S else "muerta hace mas de 24 h", muerta=True
                )
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
        else:
            changed = hooks_eventos.envio_sin_confirmar(s, time.time()) or changed
            if changed:
                touch(s)
    if mirar_pantalla:
        coda_dialogo_en_pantalla(s)  # un subproceso: sin el lock
    if fondo:
        coda_fondo_en_pantalla(s, fondo)  # idem
    if not crecio:
        return
    r = read_transcript(s)  # lo caro, sin el lock
    with lock:
        if sessions.get(sid) is not s:
            return  # la borraron (o la reemplazaron) mientras leiamos: no revivirla
        if r is not None and apply_transcript(s, r):
            changed = True
        changed = hooks_eventos.envio_sin_confirmar(s, time.time()) or changed
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
                if s.get("hooked")
                and s.get("alive")
                and not s.get("external")  # una corrida externa no se reabre en una terminal
                and restore.live_due(s.get("session_id"))
            ]
            # carpetas abiertas estos dias (recientes.py): con o sin hooks, con debounce adentro
            con_carpeta = recientes.campos(sessions.values())
        if vivas:
            restore.remember_live(vivas)
        if con_carpeta:
            recientes.recordar_tarjetas(con_carpeta)

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
            with lock:
                native_card = sessions.get(sid)
            if native_card is not None:
                native_follow.schedule(sys.modules[__name__], native_card)
            state.avisar_si_cambia(clave, None)
        except Exception:
            state.avisar_si_cambia(clave, f"{clave} fallo:\n{traceback.format_exc()}")
    refresh_envios()  # capacidades y confirmaciones sin IO bajo el lock global
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


# lo que una sesion puede juntar en ADJUNTOS/<sid>/ por /attach (pentest B5); la limpieza por antiguedad
# (ATTACH_MAX_DAYS) lo libera
ADJUNTOS_CUOTA = 200 * 2**20


def adjuntos_bytes(sid: str) -> int:
    """Bytes que ya ocupan los adjuntos de `sid`."""
    try:
        with os.scandir(os.path.join(ADJUNTOS, os.path.basename(sid))) as it:
            return sum(e.stat().st_size for e in it if e.is_file())
    except FileNotFoundError:
        return 0


def save_attachment(sid: str, name: str, data: bytes) -> str:
    safe = "".join(c for c in os.path.basename(name) if c.isalnum() or c in "._- ") or "adjunto"
    d = os.path.join(ADJUNTOS, sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6)}-{safe}")
    with open(path, "xb") as f:
        f.write(data)
    return path


def external_blocked(s: dict, accion: str = "escribirle") -> tuple[int, dict] | None:
    """409 si la tarjeta es una ejecucion externa: no se le teclea, ni se la interrumpe, ni se la
    mata desde el lienzo. Se controla desde quien la lanzo (o desde el plugin de ese orquestador)."""
    ext = s.get("external")
    if not ext:
        return None
    if ext.get("kind") == "batch":
        motivo = "es una corrida headless (claude -p): no tiene consola"
    elif ext.get("kind") == "claude-desktop":
        # medido 2026-10-17: su entrada es un pipe de la app (no se toca) y el canal nativo si le llega
        canal = f"«{ext['canal']}»" if ext.get("canal") else "su nombre en ListAgents"
        motivo = (
            "es una sesion de la app de escritorio (Claude Desktop): el lienzo no le teclea; "
            f"escribile por el canal nativo desde una sesion de Claude (SendMessage a {canal})"
        )
    elif ext.get("desktop"):
        motivo = "es un hilo de la app de escritorio (Codex desktop): se ve, pero el lienzo todavia no le escribe"
    else:
        motivo = f"es una ejecucion de {ext.get('kind')}: se controla desde su orquestador o su plugin"
    return 409, {"ok": False, "error": f"no se puede {accion}: {motivo}", "external": ext}


def send_blocked(s: dict) -> tuple[int, dict] | None:
    """Por que no se le puede escribir a esta sesion, o None si se puede."""
    if bloqueo := external_blocked(s):
        return bloqueo
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


def queue_blocked(s: dict) -> tuple[int, dict] | None:
    """Guardias de un envío por `codex queue`: las de toda tarjeta que no dependen de una consola (externa
    ajena, detenida, permiso o pregunta pendiente). Un hilo de la app de Codex sí pasa: no se le teclea, pero
    `codex queue` le escribe por su id de rollout (medido 2026-10-17). Claude Desktop y orquestadores, no."""
    ext = s.get("external") or {}
    if ext and not codex_queue.es_desktop(s):
        return external_blocked(s)
    if s.get("stopped_by"):
        return 409, {
            "ok": False,
            "error": "esa sesion esta detenida (stopped): no recibe mensajes hasta que la habilites desde su tarjeta",
        }
    if s.get("pending_id"):
        if is_question(pending.get(s["pending_id"]) or {}):
            return 409, {"ok": False, "error": "esa sesion te esta preguntando algo; elegi una opcion primero"}
        return 409, {"ok": False, "error": "hay un permiso pendiente; contestalo primero"}
    return None


def puede_enviar(s: dict) -> dict:
    """`{puede, motivo, transporte}` (contrato de D, revision-arquitectura-informe.md 12:1x): cómo se le escribe
    a la tarjeta. Codex CLI recibe por su consola; Desktop utiliza la cola por hilo.
    Claude Desktop → canal nativo
    (no lo envía el lienzo)."""
    if s.get("agent") == "claude":
        ext = s.get("external") or {}
        if not ext or ext.get("kind") == "claude-desktop":
            if s.get("stopped_by") or s.get("pending_id"):
                return {
                    "puede": False,
                    "motivo": "sesión detenida o con permiso/pregunta pendiente",
                    "transporte": "claude_pipe",
                }
            pipe = claude_pipe_runtime.availability(s)
            if (
                ext.get("kind") == "claude-desktop"
                or pipe["puede"]
                or (s.get("envio_claude") or {}).get("estado") in ("pendiente", "encolado", "sin_confirmacion")
            ):
                return pipe
    if s.get("agent") == "codex" and (codex_queue.es_desktop(s) or not s.get("external")):
        if bloqueo := queue_blocked(s):
            return {"puede": False, "motivo": bloqueo[1]["error"], "transporte": None}
        if not codex_queue.es_desktop(s):
            bloqueo = send_blocked(s)
            return (
                {"puede": False, "motivo": bloqueo[1]["error"], "transporte": None}
                if bloqueo
                else {"puede": True, "motivo": None, "transporte": "tecleo"}
            )
        plan = codex_queue.puede_enviar(s)
        return plan
    if (s.get("external") or {}).get("kind") == "claude-desktop":
        return {"puede": False, "motivo": external_blocked(s)[1]["error"], "transporte": "canal_nativo"}
    bloqueo = send_blocked(s)
    if bloqueo:
        return {"puede": False, "motivo": bloqueo[1]["error"], "transporte": None}
    return {"puede": True, "motivo": None, "transporte": "tecleo"}


def _under_adjuntos(path: str) -> bool:
    """El adjunto esta realmente bajo ~/.lienzo/adjuntos (hallazgo M5): las rutas llegan crudas del
    cliente, y sin esto un send podia hacerle leer al agente cualquier archivo del disco (una clave
    privada, auth.json). Todo adjunto legitimo sale de /attach, que escribe ahi."""
    try:
        root = os.path.realpath(ADJUNTOS)
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError, OSError:
        return False


def compose_send(
    sid: str, text: str, attachments: list[str], agent: str | None = None, wsl: bool = False
) -> tuple[str, str, list[str]]:
    """(lo que se tipea, lo que escribio el usuario, los adjuntos). Un mensaje largo o de varias
    lineas no se tipea: se guarda como .md y viaja como 'Leé el archivo adjunto...' (§6.5). Para un
    agente de SHELL_READERS el aviso le pide leerlo con el shell y no con su herramienta `read`."""
    attachments = [a for a in (attachments or []) if _under_adjuntos(a)]  # M5: confinar al buzon
    text = (text or "").replace("\r", "")
    orig = text.strip()  # lo que escribio el usuario: es lo que se cuenta y lo que muestra la tarjeta
    if agent == "codex" and any(ord(ch) > 0xFFFF for ch in text + "".join(attachments)):
        payload = "\n".join([text, *[f"Adjunto: {path}" for path in attachments]])
        attachments = [save_attachment(sid, "mensaje.md", payload.encode("utf-8"))]
        text = ATTACH_WRAPPER
    elif len(text) > LONG_TEXT or "\n" in orig:
        attachments = [save_attachment(sid, "mensaje.md", text.encode("utf-8"))] + list(attachments)
        text = ATTACH_WRAPPER_SHELL if agent in SHELL_READERS else ATTACH_WRAPPER
    parts = [strip_control(text).strip()] if text.strip() else []  # A4: sin teclas de control
    # un agente de WSL lee /mnt/c/..., no C:\...: la ruta se traduce solo en lo que se tipea
    parts += [f"Adjunto: {tmux.ruta_wsl(a) if wsl else a}" for a in attachments]
    return " ".join(parts), orig, attachments


def run_send(s: dict, final: str, enter: bool = True, key: str | None = None) -> tuple[int, dict]:
    """Teclea `final` en la consola del agente. En tmux es send-keys al pane; en Windows, el
    subproceso send.py por PID (un texto largo va por archivo: la linea de comando no lo aguanta).
    Sin `enter` solo se tipea (una opcion de un dialogo de la TUI se elige con la tecla del numero,
    sin confirmar); con `key="escape"` va esa tecla sola. (codigo, respuesta)."""
    if bloqueo := external_blocked(s):
        return bloqueo  # ultima barrera: ningun camino (dialogo, Esc, nativo) teclea en una externa
    sid, pid = s["session_id"], s["pid"]
    if backend.is_tmux(s):
        if not tmux.target_valid(s.get("target"), pid, s.get("distro")):
            return 409, {
                "ok": False,
                "error": "el pane cambió (¿tmux reinició?): no se envía, para no teclear en la terminal equivocada",
            }
        r = tmux.send(s.get("target"), final, enter=enter, key=key, distro=s.get("distro"))
        if not r.get("ok"):
            state.log(f"send {sid[:8]} fallo (pane {s.get('target')}): {r.get('error')}")
            return 500, r
        return 200, r
    tf = save_attachment(sid, ".send.txt", final.encode("utf-8")) if len(final) > 2000 else None
    cmd = [PYTHON, os.path.join(HERE, "send.py"), "--pid", str(pid)]
    if s.get("agent") == "codex":
        start = s.get("codex_console_start")
        if type(start) is not int or procs.creation_filetime(pid) != start:
            return 409, {
                "ok": False,
                "error": "el proceso Codex cambió o aún no se verificó: esperá el próximo barrido",
            }
        cmd += ["--expected-start", str(start)]
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
    de mas caeria en la caja de entrada. Un dialogo sin numeros (`teclas: flechas`) va con flechas y
    Enter, revalidando la pantalla (_elegir_con_flechas). Se acepta solo un numero que este en el dialogo leido, no
    texto libre: esto escribe en la consola de otro proceso."""
    if frenado := send_blocked(s):
        return frenado
    d = s.get("dialog") or {}
    opciones = [o.get("n") for o in d.get("options") or []]
    if choice not in opciones:
        return 409, {"ok": False, "error": f"esa sesion no esta mostrando la opcion {choice}"}
    if d.get("teclas") == "flechas":
        code, out = _elegir_con_flechas(s, d, choice)
    else:
        code, out = run_send(s, str(choice), enter=False)
    if code != 200:
        return code, out
    elegida = next((o.get("text") for o in d["options"] if o.get("n") == choice), str(choice))
    state.log(f"dialogo {s['session_id'][:8]}: {short(d.get('question') or '', 60)} -> {choice}. {short(elegida, 60)}")
    with lock:
        s["dialog"] = None  # el proximo barrido de pantalla (5 s) dira si quedo algo
        if (s.get("needs") or {}).get("kind") == "dialog":
            # sale ya de «te necesita»: esperar al barrido la dejaba 5 s mas en esa columna
            set_state(s, perfil(s["agent"]).after_dialog)
        touch(s)
    out["choice"] = choice
    out["text"] = elegida
    return 200, out


def _dialogo_en_pantalla(s: dict, visto: dict) -> tuple[dict | None, str | None]:
    """El dialogo que la consola muestra AHORA, o (None, motivo) si no es el que se vio en la tarjeta."""
    r = read_screen(s)
    if not r.get("ok"):
        return None, f"no pude leer la pantalla: {r.get('error')}"
    d = screen.dialog(r.get("lines") or [])
    if not d or [o["text"] for o in d["options"]] != [o.get("text") for o in visto.get("options") or []]:
        return None, "el dialogo ya no esta en la pantalla (¿se contesto en la terminal?)"
    if not perfil(s["agent"]).same_dialog(d, visto, lambda: read_transcript(s)):
        return None, "el permiso ya cambio o se resolvio; relee la tarjeta antes de elegir"
    return d, None


def _elegir_con_flechas(s: dict, visto: dict, choice: int) -> tuple[int, dict]:
    """Un dialogo sin numeros (el de confianza «Accessing workspace:»): el numero no elige nada. Se
    mueve el cursor con `choice - selected` flechas y, antes del Enter, se relee la pantalla para
    confirmar que el cursor quedo en la elegida: un Enter en otra opcion puede cerrar la sesion
    («No, exit»)."""
    d, motivo = _dialogo_en_pantalla(s, visto)
    if not d:
        return 409, {"ok": False, "error": motivo}
    paso = choice - d["selected"]
    for _ in range(abs(paso)):
        code, out = run_send(s, "", enter=False, key="down" if paso > 0 else "up")
        if code != 200:
            return code, out
    if paso:
        time.sleep(0.3)  # que la TUI redibuje antes de releer
        d, motivo = _dialogo_en_pantalla(s, visto)
        if not d:
            return 409, {"ok": False, "error": motivo}
        if d["selected"] != choice:
            return 409, {
                "ok": False,
                "error": f"el cursor quedo en la opcion {d['selected']}, no en la {choice}: no confirmo",
            }
    return run_send(s, "", enter=False, key="enter")


def coda_ask_open(pantalla: str) -> bool:
    """¿La pantalla de CODA muestra un permiso abierto? El titulo «Approval Required» se sale de la
    pantalla cuando el comando es largo (un heredoc que escribe un archivo): por eso tambien vale el
    pie del cartel, que siempre esta abajo («Enter confirm · Esc deny»). Tambien el dialogo de correr
    un workflow, con la opcion de correrlo ya marcada."""
    if "Approval Required" in pantalla or ("Enter confirm" in pantalla and "Esc deny" in pantalla):
        return True
    # el primer uso de un workflow (o despues de editarlo) pide su propio dialogo, con «1. Yes, run it» ya
    # marcado: el Enter lo corre. Sin esto el auto-aprobar lo daba por contestado sin teclear nada y la
    # coda quedaba esperando (medido el 2026-10-10 con el workflow sdd-olas)
    return "Run a dynamic workflow?" in pantalla and "> 1. Yes, run it" in pantalla


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
        # ya se contesto (en la terminal, o el log lo sigue mostrando mientras corre el comando):
        # se saca de la tarjeta en vez de dejar unos botones que no hacen nada (pedido de Ariel, 2026-10-10)
        with lock:
            if sessions.get(s["session_id"]) is s and (s.get("needs") or {}).get("coda_at") == coda_at:
                if abierto.get("de_fondo"):
                    s["coda_fondo_hecho"] = coda_at
                    s["state"], s["state_since"], s["needs"] = "termino", now(), None
                else:
                    set_state(s, "corriendo")
                touch(s)
        return 200, {"ok": True, "ya_no_estaba": True}
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


def dialogo_abierto(s: dict) -> tuple[int, dict] | None:
    """409 si la sesion muestra un dialogo de opciones de la TUI (el de confianza de una carpeta,
    «Switch model?»): un texto + Enter elegiria la opcion marcada (en el de confianza, «No, exit», y la
    sesion se cierra). Con el dialogo ya visto por el barrido alcanza con mirarlo; una sesion recien
    lanzada (sin hooks todavia) se mira en el momento, porque el dialogo de confianza aparece antes
    que cualquier hook y el barrido de pantalla pasa cada 5 s."""
    d = s.get("dialog")
    if d is None and (
        perfil(s["agent"]).capabilities["screen"] and (perfil(s["agent"]).live_dialog_with_hooks or not s.get("hooked"))
    ):
        r = read_screen(s)
        d = screen.dialog(r.get("lines") or []) if r.get("ok") else None
        if d:
            with lock:
                if sessions.get(s["session_id"]) is s:
                    s["dialog"] = d
                    touch(s)
    if not d:
        return None
    q = d.get("question") or "un dialogo de opciones"
    # en el de flechas la pregunta es «Accessing workspace:» y el «trust» esta en el detalle
    mira = f"{q} {d.get('detail') or ''}".lower()
    confianza = any(p in mira for p in ("trust", "confi", "accessing workspace"))
    motivo = "dialogo de confianza abierto" if confianza else "la sesion muestra un dialogo"
    return 409, {
        "ok": False,
        "code": "dialog_open",
        "error": f"{motivo} («{short(q, 80)}»): elegí una opción en la tarjeta antes de mandarle nada",
    }


def _opcion_remote_control(d: dict) -> int | None:
    """En el dialogo de /remote-control, la opcion que deja la sesion publicada: «Enable» si estaba
    apagado; si ya estaba prendido el mismo comando ofrece desconectar, y ahi se elige la que NO
    desconecta. None si el dialogo no es ese o no se reconoce ninguna."""
    if "remote control" not in (d.get("question") or "").lower():
        return None
    ops = [(o.get("n"), (o.get("text") or "").lower()) for o in d.get("options") or []]
    for n, t in ops:
        if t.startswith(("enable", "connect")):
            return n
    for n, t in ops:
        if not any(p in t for p in ("disconnect", "disable", "stop", "turn off")):
            return n
    return None


def _menu_remote_control_abierto(s: dict) -> bool:
    """El menu que abre /remote-control cuando ya estaba prendido (Disconnect / Show QR / Continue):
    va con flechas y screen.dialog no lo reconoce. Se cierra con Esc, que es «Continue»."""
    r = read_screen(s)
    texto = "\n".join((r.get("lines") or [])[-12:]) if r.get("ok") else ""
    return "Disconnect this session" in texto and "Esc to continue" in texto


def nombrar_nativo(s: dict, nombre: str, esperar_dialogo: float = 10.0) -> tuple[int, dict]:
    """Serializa pedidos manuales y automáticos sobre la misma consola."""
    with lock:
        if s.get("native_sync_busy"):
            return 409, {
                "ok": False,
                "code": "native_deferred",
                "error": "se está actualizando el nombre nativo; esperá a que termine",
            }
        s["native_sync_busy"] = True
    try:
        return _nombrar_nativo(s, nombre, esperar_dialogo)
    finally:
        with lock:
            s["native_sync_busy"] = False
            touch(s)


def _nombrar_nativo(s: dict, nombre: str, esperar_dialogo: float) -> tuple[int, dict]:
    """Deja una sesion de Claude Code visible en el canal nativo con `nombre`: teclea `/rename` y
    `/remote-control`, y contesta el dialogo de Remote Control desde aca (sin esto habia que ir a
    cada consola a darle Enable). Sin Remote Control, ListAgents de otra PC no la ve. Va por
    run_send y no por send_to_session: un comando con barra no dispara Stop, y la tarjeta quedaria
    «corriendo» para siempre. Solo con la sesion quieta: en una ocupada el comando queda encolado."""
    if s.get("agent") != "claude":
        return 409, {"ok": False, "error": "solo Claude Code tiene canal nativo"}
    if s.get("state") == "corriendo":
        return 409, {"ok": False, "code": "native_deferred", "error": "esta corriendo: se nombra cuando quede quieta"}
    if s.get("typing"):
        return 409, {
            "ok": False,
            "code": "native_deferred",
            "error": "está escribiendo: se nombra cuando la caja quede libre",
        }
    if frenado := send_blocked(s) or dialogo_abierto(s):
        return frenado
    if _menu_remote_control_abierto(s):  # quedo de una vez anterior: teclear encima lo eligiria
        run_send(s, "", enter=False, key="escape")
        time.sleep(1)
    for texto in (f"/rename {nombre}", "/remote-control"):
        if s.get("state") == "corriendo" or s.get("typing"):
            return 409, {
                "ok": False,
                "code": "native_deferred",
                "error": "empezó otro turno: se detuvo el cambio de nombre nativo",
            }
        code, out = run_send(s, texto)
        if code != 200:
            return code, out
        time.sleep(1.5)
    fin = time.time() + esperar_dialogo
    while time.time() < fin:
        r = read_screen(s)
        d = screen.dialog(r.get("lines") or []) if r.get("ok") else None
        n = _opcion_remote_control(d) if d else None
        if n is None and _menu_remote_control_abierto(s):
            # ya estaba publicada: Esc la deja como estaba, sin desconectar
            run_send(s, "", enter=False, key="escape")
            break
        if n is not None:
            with lock:
                s["dialog"] = d
            code, out = answer_dialog(s, n)
            if code != 200:
                return code, out
            break
        time.sleep(1)
    with lock:
        s["native_name"] = nombre
        touch(s)
    state.log(f"canal nativo {s['session_id'][:8]} -> {nombre}")
    return 200, {"ok": True, "native_name": nombre}


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
    with lock:
        if s.get("native_sync_busy"):
            return 409, {"ok": False, "error": "se está actualizando el nombre nativo; reintentá cuando termine"}
    if s.get("agent") in ("codex", "pi") and text.strip().lower() in ("/exit", "/quit"):
        return 400, {
            "ok": False,
            "error": "send no cierra esta sesión con /exit ni /quit. Usá la acción de cerrar del tablero o el comando en su terminal.",
        }
    if s.get("agent") == "claude" and puede_enviar(s).get("transporte") == "claude_pipe":
        return send_claude_pipe(s, text, attachments)
    if s.get("agent") == "codex":
        plan = puede_enviar(s)
        if plan["transporte"] == "codex_queue":
            return send_codex_queue(s, text, attachments)
        if not plan["puede"]:
            return 409, {"ok": False, "error": plan["motivo"], "envio": plan}
    if frenado := send_blocked(s):
        return frenado
    if frenado := dialogo_abierto(s):
        return frenado
    attachments_pedidos = list(attachments or [])
    console_receipt = None
    if s.get("agent") == "codex":
        digest = hashlib.sha256(json.dumps([text, attachments_pedidos], ensure_ascii=False).encode()).hexdigest()
        with lock:
            previous = s.get("envio_codex") or {}
            if (
                previous.get("transporte") == "tecleo"
                and previous.get("digest") == digest
                and (
                    previous.get("estado") in ("pendiente", "encolado", "sin_confirmacion")
                    or (previous.get("estado") == "entregado" and time.time() - previous["at"] < 60)
                )
            ):
                return 200, {"ok": True, "chars": len(text), **previous}
            if previous.get("transporte") == "tecleo" and previous.get("estado") == "pendiente":
                return 409, {"ok": False, "error": "hay un envío a la consola Codex en curso; esperá a que termine"}
            if previous and previous.get("transporte") != "tecleo":
                s.setdefault("envios_codex_anteriores", {})[previous.get("envio_id") or sid] = previous
            console_receipt = {
                "envio_id": secrets.token_hex(12),
                "at": time.time(),
                "estado": "pendiente",
                "transporte": "tecleo",
                "motivo": "esperando escritura en la consola de Codex",
                "digest": digest,
            }
            s["envio_codex"] = console_receipt
    final, orig, attachments = compose_send(
        sid, text, attachments, agent=s.get("agent"), wsl=backend.is_tmux(s) and tmux.VIA_WSL
    )
    if not final:
        if console_receipt is not None:
            console_receipt.update(estado="rechazado", motivo="texto vacio")
        return 400, {"ok": False, "error": "texto vacio"}
    with lock:
        mark_sent(s, final)  # antes de teclear: el hook del pedido puede llegar antes que este vuelva
        if console_receipt is not None:
            console_receipt["prompt_sha256"] = hashlib.sha256(final.encode()).hexdigest()
            touch(s)  # Persist the reservation before any console input.
    code, out = run_send(s, final)
    if code != 200:
        with lock:
            s["sent_mark"] = None  # no entro: lo que se tipee despues es del usuario
            if console_receipt is not None and console_receipt.get("estado") != "entregado":
                console_receipt.update(
                    estado="rechazado" if code == 409 else "sin_confirmacion", motivo=out.get("error")
                )
                touch(s)
        return code, out
    # la memoria del proyecto de la carpeta de `s` (anexo A de v5): el texto entero, no el envoltorio
    captura.envio(s, text, adjuntos=attachments_pedidos, **captura.origen_actual())
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
        confirmado = s.get("sent_mark") is None  # el UserPromptSubmit ya llego y consumio la marca
        if s.get("last_event") != "SessionEnd" and not confirmado:
            # tras SessionEnd la consola ya es de otra sesion (/clear, resume): lo que se tipea
            # llega a esa, y esta tarjeta no vuelve a 'corriendo' (la continua apply_event)
            s["stopped_by"] = None
            if s.get("hooked") or console_receipt is not None:
                # 'corriendo' lo pone el pedido que confirma el agente (hook_prompt_submit), no el fin
                # del tecleo: un Enter que la TUI tomo como salto de linea dejaba el texto en el
                # editor con la tarjeta 'corriendo' (2026-10-14). Sin confirmacion, aviso visible
                s["envio_pendiente"] = {"at": time.time(), "sin_consumo": bool(out.get("enter_sin_consumo"))}
            else:
                set_state(s, "corriendo")  # sin hooks no hay quien confirme: como antes
        touch(s)
        if console_receipt is not None:
            if console_receipt["estado"] == "pendiente":
                console_receipt.update(estado="encolado", motivo="escrito en la consola; espera confirmación de Codex")
            out.update(console_receipt)
    return 200, out


def _stale_send_result(previous: dict, result: dict) -> bool:
    same = previous.get("envio_id") == result.get("envio_id") and previous.get("at") == result.get("at")
    return previous.get("at", 0) > result["at"] or (same and previous.get("estado") == "entregado")


def send_codex_queue(s: dict, text: str, attachments: list[str]) -> tuple[int, dict]:
    """Envío a un hilo de Codex por `codex queue`: sin tecleo. Un texto de más de codex_queue.MAX_MESSAGE va
    como adjunto. «entregado» sólo si el texto ya está en el rollout del hilo; si no, «encolado»."""
    attachments_pedidos = [a for a in (attachments or []) if _under_adjuntos(a)]  # M5: confinar al buzon
    orig = (text or "").replace("\r", "").strip()
    if not orig and not attachments_pedidos:
        return 400, {"ok": False, "error": "texto vacio"}
    body = orig
    if not codex_queue.message_fits(s, "\n".join([body] + [f"Adjunto: {a}" for a in attachments_pedidos])):
        body = ATTACH_WRAPPER
        attachments_pedidos = [
            save_attachment(s["session_id"], "mensaje.md", orig.encode("utf-8")),
            *attachments_pedidos,
        ]
    final = "\n".join([body] + [f"Adjunto: {a}" for a in attachments_pedidos]).strip()
    res = codex_queue.enviar(s, final)
    result_at = res.get("at", time.time())
    res = {**res, "at": result_at}
    with lock:
        previous = s.get("envio_codex") or {}
        if sessions.get(s.get("session_id")) is s and not _stale_send_result(previous, res):
            s["envio_codex"] = {**res, "at": result_at}
            touch(s)
    if res["estado"] == "rechazado":
        return 409, {"ok": False, "error": res["motivo"], "envio": res}
    captura.envio(s, text, adjuntos=attachments_pedidos, **captura.origen_actual())
    with lock:
        current = s.get("envio_codex") or {}
        if (
            sessions.get(s.get("session_id")) is s
            and current.get("envio_id") == res.get("envio_id")
            and current.get("at") == result_at
        ):
            s["last_prompt"] = short(orig, 500) if orig else short(final, 500)
            s["prompt_via"] = "lienzo"
            touch(s)
    return 200, {"ok": True, "chars": len(orig), "transporte": "codex_queue", **res}


def send_claude_pipe(s: dict, text: str, attachments: list[str]) -> tuple[int, dict]:
    """Sólo bridge propio vivo; sin tecleo Desktop ni reenvío ante incertidumbre."""
    plan = puede_enviar(s)
    if not plan["puede"] or plan["transporte"] != "claude_pipe":
        return 409, {"error": plan["motivo"], "envio": plan}
    orig = (text or "").replace("\r", "").strip()
    files = [a for a in attachments or [] if _under_adjuntos(a)]
    final = "\n".join([orig] + [f"Adjunto: {a}" for a in files]).strip()
    if not final:
        return 400, {"error": "texto vacío"}
    if len(final.encode("utf-8")) > claude_pipe_runtime.MAX_TEXT:
        files = [save_attachment(s["session_id"], "mensaje.md", orig.encode("utf-8")), *files]
        final = "\n".join([ATTACH_WRAPPER] + [f"Adjunto: {a}" for a in files])
    result = claude_pipe_runtime.send(dict(s), final)
    result = {**result, "at": result.get("at", time.time())}
    with lock:
        old = s.get("envio_claude") or {}
        if sessions.get(s["session_id"]) is s and not _stale_send_result(old, result):
            s["envio_claude"] = dict(result)
            if result["estado"] != "rechazado":
                s["last_prompt"], s["prompt_via"] = short(orig, 500), "lienzo"
            touch(s)
    if result["estado"] == "rechazado":
        return 409, {"error": result["motivo"], "envio": result}
    captura.envio(s, text, adjuntos=files, **captura.origen_actual())
    return 200, {"ok": True, "chars": len(orig), **result}


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
    if coord := repo_coordinator(my_repo, locales, remotas):
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
        with captura.origen(de=s["session_id"], kind="aviso_detenida"):
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
    if stop:
        try:
            transfer_work_rules(origin["session_id"], target["session_id"])
        except (OSError, ValueError) as e:
            return {"interrupted": False, "handover_error": str(e)}
        if origin.get("coordinator"):
            set_coordinator(target, True)
            with lock:
                origin["coordinator"] = False
                touch(origin)
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


def transfer_work_rules(old: str, new: str) -> int:
    """Traslada reglas pendientes en ambas direcciones; conserva el historial de envíos."""
    import rules as rule_module

    with lock:
        before = [dict(r) for r in rules.items]
        after = [dict(r) for r in before]
        changed = 0
        for r in after:
            if not r.get("enabled") or old not in (r.get("from"), r.get("to")):
                continue
            for key in ("from", "to"):
                if r.get(key) == old:
                    r[key] = new
            if r.get("kind") == "on_stop" and r.get("from") == r.get("to"):
                raise ValueError("el traspaso crearía una regla hacia la misma sesión")
            changed += 1
        remote = _mirror_rules()
        for r in after:
            if r.get("enabled") and r.get("kind") == "on_stop" and rule_module.loop_conflict(r, after, remote):
                raise ValueError("el traspaso crearía un bucle de informes")
        if changed:
            rules.items[:] = after
            try:
                rules.save(strict=True)
            except OSError:
                rules.items[:] = before
                raise
    if changed:
        rules.publish()
    return changed


# --- pantalla (solo para las sugerencias de la TUI de Claude, DISENO §12) ------------------


def read_screen(s: dict) -> dict:
    """La pantalla del agente: capture-pane del pane en tmux, o el subproceso screen.py por PID en
    Windows (FreeConsole/AttachConsole no puede correr dentro del server)."""
    if backend.is_tmux(s):
        tgt = s.get("target")
        if not tmux.target_valid(tgt, s.get("pid"), s.get("distro")):
            return {"ok": False, "error": "el pane ya no es de esta sesión"}
        r = tmux.screen(tgt, scrollback=200, distro=s.get("distro"))
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


def _mismo_dialogo(antes: dict | None, ahora: dict) -> bool:
    """El mismo dialogo redibujado (otra linea envuelta en el detalle, el spinner): misma pregunta y
    mismas opciones. Otro dialogo que reemplaza al anterior sin pasar por «ninguno» no lo es."""
    if not antes:
        return False
    opciones = [[o.get("text") for o in d.get("options") or []] for d in (antes, ahora)]
    return antes.get("question") == ahora.get("question") and opciones[0] == opciones[1]


AUTO_DIALOGO_S = 15  # un permiso que el auto-aprobar no cerro en este tiempo pasa a «te necesita»


def autoaprobar_opcion(d: dict, agent: str | None) -> int | None:
    import autoaprobar  # importa este modulo: aca ya esta cargado

    return autoaprobar.opcion_de_permiso(d, agent)


def lo_contesta_el_auto_aprobar(s: dict, d: dict) -> bool:
    """Si el auto-aprobar va a contestar este dialogo: entonces la tarjeta no pasa a «te necesita».
    Medido el 2026-10-15: cada permiso de un codex la llevaba 5 s a esa columna, que se abria y se
    cerraba y corria el tablero (36 veces en una hora). Si no lo cierra en AUTO_DIALOGO_S, si pasa."""
    import autoaprobar  # importa este modulo: aca ya esta cargado

    if not autoaprobar.prendido():
        return False
    desde = parse_ts(s.get("dialog_at"))
    if desde and (dt.datetime.now().astimezone() - desde).total_seconds() > AUTO_DIALOGO_S:
        return False
    return autoaprobar.opcion_de_permiso(d, s.get("agent")) is not None


def antigravity_screen_observation(result: dict) -> dict:
    """Sólo el pie observado de agy 1.4.3; nunca texto de respuestas ni un ID canónico."""
    lines = [line.rstrip() for line in result.get("lines", []) if line.strip()]
    footer = lines[-1] if lines and result.get("ok") else ""
    model = re.fullmatch(
        r"(?:\? for shortcuts {2,}| {8,})(Gemini [A-Za-z0-9 .()-]{1,70}) · (low|medium|high|xhigh|max)", footer
    )
    return {
        "source": "screen",
        "observed_at": now(),
        "available": bool(result.get("ok")),
        "model_label": f"{model[1]} · {model[2]}" if model else None,
        "activity": "unverified",  # un prompt dibujado no confirma el fin de un turno
    }


def screen_once() -> None:
    """Una pasada de lectura de pantalla. read_screen es un subproceso de 183 ms por sesion: corre
    fuera del lock, y recien despues (con el lock, y si la tarjeta sigue siendo la misma) se decide
    que hacer con lo leido. El estado se relee ahi: en 183 ms la sesion pudo empezar a correr."""
    with lock:
        items = [
            s
            for s in sessions.values()
            if perfil(s["agent"]).capabilities["screen"] and s.get("pid") and s.get("alive") and not s.get("orphan")
        ]
    for s in items:
        r = read_screen(s)
        if s["agent"] == "antigravity":
            observation = antigravity_screen_observation(r)
            with lock:
                if sessions.get(s["session_id"]) is s:
                    previous = s.get("screen_observation") or {}
                    if any(
                        previous.get(key) != observation[key]
                        for key in ("source", "available", "model_label", "activity")
                    ):
                        # La hora corresponde a la muestra publicada, no a cada sondeo idéntico.
                        s["screen_observation"] = observation
                        touch(s)
        if not r.get("ok"):
            continue  # no leer la consola no demuestra que el permiso se haya cerrado
        area = r.get("area") if r.get("ok") else None
        dlg = r.get("dialog") if r.get("ok") else None
        if dlg and perfil(s["agent"]).persist_unhooked:
            perfil(s["agent"]).decorate_dialog(dlg, read_transcript(s) or {})
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
                if d and not _mismo_dialogo(s.get("dialog"), d):
                    s["dialog_at"] = now()  # cuando aparecio: identifica el dialogo para el auto-aprobar
                s["suggestion"] = sug
                s["typing"] = typing
                s["dialog"] = d
                touch(s)
            # el dialogo espera una eleccion: la tarjeta va a «te necesita» (se ve en la columna y
            # avisa), y vuelve cuando se cierra. Solo el auto-aprobar lo contesta, y solo si es un
            # permiso (autoaprobar.DialogoDePermiso, 2026-10-08); la confianza en una carpeta, el
            # cambio de modelo o una pregunta de verdad los decide el humano
            needs = s.get("needs") or {}
            if d and needs.get("kind") == "idle" and perfil(s["agent"]).pregunta_al_terminar:
                # la pregunta del fin de turno (Kiro) quedo atras: hay un dialogo en pantalla
                set_state(s, "corriendo")
                needs = {}
            if d and needs.get("kind") == "sin_enviar" and autoaprobar_opcion(d, s.get("agent")) is not None:
                # un permiso en pantalla prueba que el agente tomo el encargo: el aviso quedo viejo.
                # Medido el 2026-10-23: un codex sin hooks ni transcripcion lo arrastro 76 min y
                # tapo su permiso, que el auto-aprobar no contesto
                set_state(s, "corriendo")
                needs = {}
            if d and not needs and s["state"] in ("termino", "corriendo") and not lo_contesta_el_auto_aprobar(s, d):
                set_needs(s, {"kind": "dialog", "detail": short(d.get("question") or "", 300), "where": "terminal"})
                touch(s)
            elif not d and needs.get("kind") == "dialog":
                set_state(s, perfil(s["agent"]).after_dialog)
                touch(s)
            elif (
                not d
                and area
                and needs.get("kind") == "permission"
                and needs.get("where") == "terminal"
                and not s.get("pending_id")
                and (since := parse_ts(needs.get("since")))
                and (dt.datetime.now().astimezone() - since).total_seconds() > 10
            ):
                # Una caja de entrada reconocida prueba que volvio al prompt. La ausencia
                # de un dialogo, sola, tambien puede ser una pantalla truncada o una lectura rota.
                set_state(s, "termino")
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


def normalize_coordinators() -> None:
    """Migra marcas por PC y conserva una por repo, prefiriendo la marca general existente."""
    seen = set()
    for s in sorted(sessions.values(), key=lambda s: (s.get("coordinator_scope") == "pc", s["session_id"])):
        changed = "coordinator_scope" in s
        s.pop("coordinator_scope", None)
        repo = _repo_identity(s)
        if s.get("coordinator") and repo is not None:
            if repo in seen:
                s["coordinator"] = False
                changed = True
            else:
                seen.add(repo)
        if changed:
            save_session(s)


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
            if s.get("repo") == "?" and s.get("cwd"):
                # guardada con «?» (raiz de disco, antes de repo_of con ruta): se recalcula junto con repo_key
                apply_repo(s, s["cwd"])
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
    normalize_coordinators()
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


# --- compatibilidad con la particion (frente F, 2026-10-21) -----------------------------

# server.py todavia hace `from sessions import consume_events, coda_vivo_en_turno`, que salieron a
# hooks_eventos.py. Esto se va cuando server.py importe del modulo nuevo (lote de server del plan).
# Un monkeypatch sobre `sessions` no tendria efecto: tests/guardia_monkeypatch.py lo hace fallar.
_DE_HOOKS_EVENTOS = frozenset({"coda_vivo_en_turno", "consume_events"})


def __getattr__(nombre: str):
    if nombre in _DE_HOOKS_EVENTOS:
        return getattr(hooks_eventos, nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
