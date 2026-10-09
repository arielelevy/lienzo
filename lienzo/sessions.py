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
import secrets
import subprocess
import threading
import time
import traceback

import backend
import coda
import conocimiento
import identity
import recientes
import restore
import screen
import state
import tmux
import transcripts

# las guess_* viven en agentes.py (modulo hoja); se reexportan aca con su nombre de siempre y las
# llamadas de este modulo pasan por estos nombres, que es lo que parchean las pruebas
# (monkeypatch.setattr(ses, "guess_transcript", ...)).
from agentes import (  # noqa: F401
    BIRTH_MARGIN_S,
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
    EVENTS,
    HERE,
    LONG_TEXT,
    NEEDS_NOTIFICATIONS,
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
            r.pop("to_pc", None)  # se vuelve a identificar con el snapshot del destino nuevo
            r.pop("parked_to", None)
            r.pop("parked_since", None)
        if suyas:
            rules.save()
    if suyas:
        rules.publish()
        state.log(f"{len(suyas)} reglas que avisaban a {old[:8]} ahora avisan a {new[:8]}")
    return len(suyas)


_norm_cwd = identity.norm_cwd


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

    guardados = []
    try:
        for coll, _, _ in cambios:
            coll.save(strict=True)
            guardados.append(coll)
    except OSError:
        # Si falla la segunda lista, la primera ya pudo quedar en disco. Revertimos ambas en
        # memoria y compensamos la lista que alcanzó a guardarse para no dejar IDs mezclados.
        for coll, anterior, _ in cambios:
            coll.items[:] = anterior
        for coll in reversed(guardados):
            try:
                coll.save(strict=True)
            except OSError as e:
                state.log(f"no se pudo revertir {os.path.basename(coll.path)} tras fallo al re-apuntar: {e}")
        raise

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
        for k in ("pid", "agent_exe", "no_console", "in_vscode", "coordinator", "pc"):
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
    if avisar and prev in ("corriendo", "te_necesita") and not salida:
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
    if not turn_say(t) and (waiting := perfil(s["agent"]).waiting_text(t)):
        s["last_reply"] = waiting
    if s["state"] != "muerta" and not s.get("needs"):
        set_state(s, "termino" if t.get("ended") else "corriendo")


def _par_denegado(x: dict) -> list:
    # una denegacion de coda sale de su log y se identifica por su hora: el comando lo pone el
    # lienzo con el ultimo que vio, y despues de autorizarla ya no queda el anterior para comparar
    if x.get("fuente") == "coda" and x.get("at"):
        return [x.get("tool"), f"at:{x['at']}"]
    return [x.get("tool"), x.get("detalle") or ""]


def autorizar_denegado(s: dict) -> None:
    """El humano autorizo desde el tablero lo que se le denego («Autorizar y que reintente»): la
    tarjeta lo anota y deja de mostrarlo. Sin esto, el aviso volvia en cada relectura del mismo turno,
    porque el mensaje de autorizacion entra en medio del turno y no hay pedido nuevo que lo limpie
    (medido el 2026-10-09 en ar-it33940). Vale hasta el proximo pedido (hook_prompt_submit)."""
    with lock:
        d = s.get("last_denied")
        if not d:
            return
        ok = [list(p) for p in s.get("denied_ok") or []]
        for x in d.get("todas") or [d]:
            if _par_denegado(x) not in ok:
                ok.append(_par_denegado(x))
        s["denied_ok"] = ok[-32:]
        s["last_denied"] = None
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


# --- eventos de hooks -------------------------------------------------------------


def heredar_de_provisoria(prov: dict, s: dict) -> None:
    """La tarjeta real hereda de la provisoria (`pid-N` del barrido) lo que se le puso a mano antes de
    que llegara el primer hook: el titulo del usuario y la marca de coordinadora. Medido el
    2026-10-04: lanzar_y_titular titulaba la provisoria y, al pasar al id real, el titulo se perdia y
    salia del primer mensaje («Bien el diagnostico. Reintenta…» en vez de «encargo F»)."""
    if prov.get("title_source") == "user" and s.get("title_source") != "user":
        s["title"], s["title_source"] = prov.get("title"), "user"
    for k in ("coordinator", "copycat_of"):
        if prov.get(k) and not s.get(k):
            s[k] = prov[k]


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
                    try:
                        n_rules, n_links = repoint_refs(other_sid, sid)
                    except OSError as e:
                        owner = other_sid
                        state.log(
                            f"pid {pid}: no reemplazo {other_sid[:8]} por {sid[:8]}: no se guardaron reglas/enlaces: {e}"
                        )
                    else:
                        if n_rules:
                            rules.publish()
                        if n_links:
                            links.publish()
                        heredar_de_provisoria(other, s)
                        drop_session(other_sid, "duplicada por barrido")
                elif continues_session(other, ev):
                    if not continue_session(other, s):
                        owner = other_sid
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


def hook_prompt_submit(s: dict, ev: dict) -> None:
    set_state(s, "corriendo")
    s["stopped_by"] = None  # volvio a trabajar: la marca de detenida ya no cuenta
    s["last_denied"] = None  # pedido nuevo: lo denegado antes ya se resolvio o se descarto
    s["denied_ok"] = None  # y lo autorizado tambien: una denegacion en el turno nuevo es nueva
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
    reason = ev.get("stop_reason")
    s["stop_reason"] = reason
    if stale_stop(s, ev):
        state.log(
            f"Stop tardio de {s['session_id'][:8]} (pedido {str(ev.get('prompt_id'))[:8]}, ya corre "
            f"{str(s.get('prompt_id'))[:8]}): la tarjeta sigue corriendo"
        )
    elif compacting(s):
        state.log(f"Stop de {s['session_id'][:8]} durante una compactacion: la tarjeta sigue corriendo")
    elif not perfil(s["agent"]).stop_is_final(reason):
        state.log(f"Stop de {s['session_id'][:8]} con motivo {reason!r}: se espera el final de la transcripcion")
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


# lo que CODA corre en el turno abierto, por sesion: su base guarda el turno recien al cerrarlo, y sin
# esto el panel mostraba el pedido solo, sin nada en vivo (2026-10-09). En memoria y fuera de la
# tarjeta, que viaja entera por el SSE; GET .../digest lo suma al turno abierto (coda_vivo_en_turno)
CODA_VIVO: dict[str, list[dict]] = {}
CODA_VIVO_MAX = 300


def _coda_vivo_anotar(sid: str, tool: str, name: str, inp: dict, sub: bool, ts: str) -> None:
    paso: dict = {"tool": tool, "ts": ts, "sub": sub}
    if name in CMD_TOOLS:
        paso["cmd"] = short(str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " "), 300)
    if name in FILE_TOOLS:
        paso["files"] = tool_paths(inp)
    if name in CODA_ASK_TOOLS:
        paso["pregunta"] = short(str(inp.get("question") or inp.get("prompt") or inp.get("message") or ""), 300)
    lista = CODA_VIVO.setdefault(sid, [])
    lista.append(paso)
    del lista[:-CODA_VIVO_MAX]


def coda_vivo_en_turno(sid: str, turno: dict) -> dict:
    """El turno abierto de CODA (tal como lo da transcripts.digest: el pedido solo) con las
    herramientas que el hook vio desde que empezo. Un turno cerrado vuelve igual: ahi manda la base."""
    if turno.get("ended"):
        return turno
    desde = parse_ts(turno.get("ts_start"))
    pasos = [p for p in CODA_VIVO.get(sid) or [] if not desde or (parse_ts(p["ts"]) or desde) >= desde]
    if not pasos:
        return turno
    archivos = list(dict.fromkeys(f for p in pasos for f in p.get("files") or []))
    return {
        **turno,
        "tools": max(turno.get("tools") or 0, len(pasos)),
        "commands": [p["cmd"] for p in pasos if p.get("cmd")][-50:],
        "files": archivos[-50:],
        "questions": [p["pregunta"] for p in pasos if p.get("pregunta")],
        "subagents": max(turno.get("subagents") or 0, int(any(p["sub"] for p in pasos))),
        "says": [*(turno.get("says") or []), f"en vivo: {len(pasos)} herramientas, la última {pasos[-1]['tool']}"],
    }


def coda_tool(s: dict, ev: dict, sub: bool = False) -> None:
    """PreToolUse de CODA: la herramienta que va a correr, a la tarjeta. Es la unica señal de
    avance durante el turno, porque CODA escribe el turno en su base recien al cerrarlo; al
    cerrarse, la transcripcion rehace estos contadores con el turno entero (turn_activity)."""
    tool = str(ev.get("tool_name") or "?")
    name = tool.lower()
    inp = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    _coda_vivo_anotar(s["session_id"], tool, name, inp, sub, ev.get("host_ts") or now())
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
    if name in CODA_ASK_TOOLS and not sub:
        # ask_user es una PREGUNTA, no un permiso: con auto-aprobar prendido el hook la deja pasar
        # (la herramienta tiene que correr para preguntar) y nadie marcaba la tarjeta; CODA la
        # preguntaba en su terminal y el tablero seguia en corriendo (medido el 2026-10-09 en
        # ar-it33940: dos ask_user AUTO-APROBADOS sin «te necesita»)
        pregunta = inp.get("question") or inp.get("prompt") or inp.get("message") or ""
        detalle = (
            short(str(pregunta).strip(), 300)
            if pregunta
            else short(json.dumps(inp, ensure_ascii=False), 300)
            if inp
            else ""
        )
        set_needs(s, {"kind": "question", "tool": tool, "detail": detalle, "where": "terminal", "via": "tool"})
        s["needs"]["coda_at"] = f"tool:{ev.get('host_ts') or now()}"
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
# herramientas de coda que le preguntan algo al usuario en su terminal (no un permiso)
CODA_ASK_TOOLS = frozenset({"ask_user", "askuser", "ask_user_question"})

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
    if act.get("error") and s.get("last_error") != act["error"]:
        s["last_error"] = act["error"]  # «coda sin cuota»: la tarjeta lo dice en rojo en vez de «termino»
    elif not act.get("error") and (s.get("last_error") or "").startswith("coda sin cuota"):
        # el log ya no dice que falte cuota (un turno nuevo, o siguio trabajando): antes el aviso
        # quedaba para siempre aunque coda trabajara (medido el 2026-10-09 en ar-it33940)
        s["last_error"] = None
    den = act.get("denied")
    pedido, cuando = parse_ts(s.get("prompt_ts")), parse_ts((den or {}).get("at"))
    if den and pedido and cuando and cuando < pedido:
        # del turno anterior: el log todavia no tiene el «prompt started» del pedido nuevo, que ya
        # borro la marca. Sin esto volvia enseguida y el boton «Autorizar» no se iba (2026-10-04)
        den = None
    if den:
        # la misma denegacion (mismo `at`) conserva el comando que se denego: last_cmd avanza con
        # cada comando que coda si aprueba, y con el detalle nuevo set_denied la volvia a anunciar
        # como DENEGADO en todos los comandos que seguian en el turno (2026-10-09, sesion a1209581
        # de ar-it33940)
        prev = s.get("last_denied") or {}
        detalle = prev.get("detalle") if prev.get("fuente") == "coda" and prev.get("at") == den.get("at") else None
        set_denied(
            s,
            {
                "tool": den["tool"],
                "motivo": CODA_ASK_CAUSES.get(den.get("cause") or "", den.get("cause") or ""),
                "detalle": detalle if detalle is not None else s.get("last_cmd") or "",
                "at": den.get("at"),
                "fuente": "coda",
                "sub": den.get("sub"),
            },
        )
    ask = act.get("asking") if act["running"] else None
    needs = s.get("needs") or {}
    if (
        act["running"]
        and not ask
        and not needs
        and s["state"] == "corriendo"
        and s.get("last_event") == "PreToolUse"
        and (s.get("last_reply") or "") in {f"usando {t}" for t in CODA_ASK_TOOLS}
    ):
        # la pregunta quedo abierta sin que coda_tool la marcara: llego antes de que el server la
        # conociera (un reinicio con el codigo nuevo, medido el 2026-10-09 en ar-it33940) o se perdio
        # su PreToolUse. Ninguna herramienta corrio despues: coda esta esperando la respuesta
        set_needs(
            s,
            {
                "kind": "question",
                "tool": s["last_reply"][len("usando ") :],
                "detail": "",
                "where": "terminal",
                "via": "tool",
            },
        )
        s["needs"]["coda_at"] = f"tool:{s.get('last_event_ts') or now()}"
        needs = s["needs"]
    if ask and s["state"] in ("corriendo", "te_necesita"):
        detail = CODA_ASK_CAUSES.get(ask["cause"] or "", ask["cause"] or "")
        detail = " · ".join(x for x in (detail, "de un subagente" if ask["sub"] else "") if x)
        if needs.get("kind") != "permission" or needs.get("coda_at") != ask["at"]:
            previa = needs if needs.get("kind") == "question" else None
            set_needs(s, {"kind": "permission", "tool": ask["tool"], "detail": detail, "where": "terminal"})
            s["needs"]["coda_at"] = ask["at"]
            if previa is not None and str(ask.get("tool") or "").lower() in CODA_ASK_TOOLS:
                # sin auto-aprobar, ask_user pide permiso antes de preguntar: se guarda la pregunta
                # para volver a ella cuando el permiso se conteste (ver el elif de abajo)
                s["needs"]["pregunta"] = previa
        elif needs.get("where") == "enviado" and time.time() - (needs.get("sent_ts") or 0) > CODA_SENT_RETRY_S:
            # el Enter/Esc no resolvio el permiso (sigue abierto en el log): se devuelven los botones
            s["needs"] = {**needs, "where": "terminal"}
    elif s["state"] == "te_necesita" and isinstance(needs.get("pregunta"), dict) and act["running"]:
        # el permiso de ask_user se contesto: ahora CODA muestra la pregunta en su terminal
        set_needs(s, needs["pregunta"])
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
        if not s["alive"] and not created and not ev_pid_dead:
            # dada por muerta y volvio (claude --resume conserva el session_id): el conocimiento por
            # proyecto vuelve su nodo sesion a viva. Con el pid del evento muerto no: marcar_muerta viene
            # unas lineas abajo y los dos hilos correrian a ver quien escribe ultimo
            en_hilo(conocimiento.sesion_viva, s["session_id"])
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
    with lock:
        if s.get("hooked"):
            return  # la extension tiene prioridad sobre el entorno de un comando anterior
        if sid and sid != s["session_id"] and sid in sessions:
            return  # no vincular un archivo cuya sesion ya tiene otra tarjeta
        if sessions.get(s["session_id"]) is not s:
            return  # la borraron mientras buscabamos su transcripcion: no revivirla
        if sid and sid != s["session_id"] and sid not in sessions:
            viejo = s["session_id"]  # la tarjeta cambia de id: la de antes se olvida entera
            try:
                n_rules, n_links = repoint_refs(viejo, sid)
            except OSError as e:
                state.log(f"barrido: no cambio {viejo[:8]} a {sid[:8]}: no se guardaron reglas/enlaces: {e}")
                return
            forget_session(viejo)
            state.broadcast({"type": "removed", "session_id": viejo})
            s["session_id"] = sid
            sessions[sid] = s
            if n_rules:
                rules.publish()
            if n_links:
                links.publish()
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
            or p.get("kiro_session")
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
    """Deja una sesion de Claude Code visible en el canal nativo con `nombre`: teclea `/rename` y
    `/remote-control`, y contesta el dialogo de Remote Control desde aca (sin esto habia que ir a
    cada consola a darle Enable). Sin Remote Control, ListAgents de otra PC no la ve. Va por
    run_send y no por send_to_session: un comando con barra no dispara Stop, y la tarjeta quedaria
    «corriendo» para siempre. Solo con la sesion quieta: en una ocupada el comando queda encolado."""
    if s.get("agent") != "claude":
        return 409, {"ok": False, "error": "solo Claude Code tiene canal nativo"}
    if s.get("state") == "corriendo":
        return 409, {"ok": False, "error": "esta corriendo: se nombra cuando quede quieta"}
    if frenado := send_blocked(s) or dialogo_abierto(s):
        return frenado
    if _menu_remote_control_abierto(s):  # quedo de una vez anterior: teclear encima lo eligiria
        run_send(s, "", enter=False, key="escape")
        time.sleep(1)
    for texto in (f"/rename {nombre}", "/remote-control"):
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
    if frenado := send_blocked(s):
        return frenado
    if frenado := dialogo_abierto(s):
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
            if perfil(s["agent"]).capabilities["screen"] and s.get("pid") and s.get("alive") and not s.get("orphan")
        ]
    for s in items:
        r = read_screen(s)
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
                s["suggestion"] = sug
                s["typing"] = typing
                s["dialog"] = d
                touch(s)
            # el dialogo espera una eleccion: la tarjeta va a «te necesita» (se ve en la columna y
            # avisa), y vuelve cuando se cierra. Solo el auto-aprobar lo contesta, y solo si es un
            # permiso (autoaprobar.DialogoDePermiso, 2026-10-08); la confianza en una carpeta, el
            # cambio de modelo o una pregunta de verdad los decide el humano
            needs = s.get("needs") or {}
            if d and not needs and s["state"] in ("termino", "corriendo"):
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
