"""Reglas del lienzo: "cuando termine" (on_stop) y "a las HH:MM" (at: una vez, o cada every_s
segundos con tope max_fires), la regla automatica "Continuar" ante un limite de uso con hora, el
disparo (fire_rule), el bucle de las programadas, la purga de las viejas y la vista de conexiones
de una sesion. Importa sessions.py para enviar y
registrar links; sessions.py lo llama por los ganchos on_turn_end / on_limit_notice, que se
rellenan al final de este modulo."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import threading
import time
import traceback

import captura
import conocimiento
import consulta
import entregas_informes as informes
import hooks_eventos
import identity
import rondas
import sessions as ses
import state
import transcripts
from agentes import AGENTES
from sessions import add_link, find_session, send_to_session
from state import links, load_config, lock, now, rules, sessions, short


def on_stop_source_error(source: dict | None) -> tuple[int, dict] | None:
    """No conocer el perfil del origen no acredita un fin de turno (API y migración)."""
    agent = (source or {}).get("agent")
    profile = AGENTES.get(agent) if isinstance(agent, str) else None
    if profile is None:
        return 409, {"code": "unverified_on_stop_source", "error": "no se pudo verificar el agente origen de on_stop"}
    if profile.capabilities.get("terminalOnly"):
        return 409, {
            "code": "unsupported_on_stop",
            "error": "el agente origen no confirma fin de turno; on_stop no está disponible",
        }
    return None


def local_dt(value) -> dt.datetime | None:
    """ISO a datetime en hora local, o None si no parsea. Todas las horas de una regla (`at`,
    `created`, `last_fired`, `disabled_at`) las escribe este modulo o server.parse_at ya con
    offset; lo que llegue sin zona (un rules.json editado a mano) se asume local, no UTC, que es
    lo que quiso decir quien lo escribio. (state.parse_ts hace lo contrario: es para los hooks y
    las transcripciones, que hablan UTC.)"""
    try:
        d = dt.datetime.fromisoformat(str(value))
    except TypeError, ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def session_name(sid: str | None) -> str:
    """Nombre corto para mostrar: 'repo · titulo' (o lo que haya)."""
    s = sessions.get(sid or "")
    if s is None:
        return (sid or "?")[:8]
    repo, title = s.get("repo") or "?", (s.get("title") or "").strip()
    return f"{repo} · {short(title, 60)}" if title else repo


def connections_of(sid: str) -> dict:
    """Vinculos y reglas donde `sid` es origen o destino, con la otra punta resuelta a nombre,
    ordenados del mas nuevo al mas viejo."""

    def decorate(x: dict) -> dict:
        out = dict(x)
        out["direction"] = "out" if x.get("from") == sid else "in"
        other = x.get("to") if out["direction"] == "out" else x.get("from")
        if other:
            name = session_name(other)
        else:
            name = "vos (lienzo)" if x.get("kind") == "user" else "(hora fija)"
        out["other"] = {"session_id": other, "name": name}
        return out

    def newest_first(coll: list[dict], ts_key: str) -> list[dict]:
        # fecha descendente; a igual fecha (mismo milisegundo), el agregado despues va primero
        order = sorted(enumerate(coll), key=lambda ix: (ix[1].get(ts_key) or "", ix[0]), reverse=True)
        return [decorate(x) for _, x in order]

    with lock:
        ls = newest_first([l for l in links.items if sid in (l.get("from"), l.get("to"))], "ts")
        rs = newest_first([r for r in rules.items if sid in (r.get("from"), r.get("to"))], "created")
    return {"links": ls, "rules": rs}


def retirar_regla(rule_id: str) -> bool:
    """Desactiva sin borrar informes pendientes; True si quedó conservada."""
    with lock:
        rule = next((r for r in rules.items if r["id"] == rule_id), None)
        if rule is not None and informes.pendientes(rule):
            anterior = dict(rule)
            rule["enabled"] = False
            rule["disabled_reason"] = "borrado rechazado: hay informes pendientes de integrar"
            try:
                rules.save(strict=True)
            except Exception:
                rule.clear()
                rule.update(anterior)
                raise
            rules.publish()
            return True
        rules.remove(lambda r: r["id"] == rule_id)
        return False


def reconciliar_cableado() -> None:
    """Recupera ids vivos y archiva orígenes sin proceso ni opción de restaurar."""
    restaurables = {s["session_id"] for s in ses.restore.restorables()}
    with lock:
        vivos = {sid for sid, s in sessions.items() if s.get("alive")}
    for sid in vivos:
        ses.retake_rules_from(sid, sid)
        with lock:
            parked_to = any(r.get("parked_to") == sid for r in rules.items)
        if parked_to:
            ses.retarget_rules(sid, sid)
    changed = False
    with lock:
        for r in rules.items:
            origin = r.get("from")
            if (
                origin
                and origin not in vivos
                and origin not in restaurables
                and origin not in sessions
                and not r.get("archived_at")
            ):
                if not r.get("parked_from"):
                    if not r.get("parked_to"):
                        r["parked_was_enabled"] = bool(r.get("enabled"))
                    r["parked_from"] = origin
                    r["parked_since"] = now()
                r.update(enabled=False, archived_at=now(), disabled_reason="origen muerto y no restaurable")
                changed = True
        if changed:
            rules.save()
    if changed:
        rules.publish()


def agregar_regla(rule: dict, cap: int = 500) -> None:
    """Recorta sólo reglas sin informes pendientes; la retención prevalece sobre el cupo."""
    with lock:
        previous = list(rules.items)
        excess = max(0, len(previous) + 1 - cap)
        retained = []
        for existing in previous:
            if excess and not informes.pendientes(existing) and not existing.get("archived_at"):
                excess -= 1
            else:
                retained.append(existing)
        rules.items[:] = [*retained, rule]
        try:
            rules.save(strict=True)
        except Exception:
            rules.items[:] = previous
            raise
    rules.publish()


def full_reply(s: dict, cap: int = 6000) -> str:
    """Ultima respuesta completa: la mas larga entre la de la transcripcion y la de la tarjeta.

    La tarjeta trae la del hook Stop (`last_assistant_message`, entera), que es la verdad del turno que
    cerro; la transcripcion sirve cuando el hook no la trae. Antes ganaba siempre la transcripcion, y
    Claude Code escribe la linea de la respuesta final DESPUES de disparar el Stop: leida en ese instante,
    el «final» del turno era el ultimo texto intermedio (medido el 2026-10-10 en la consulta
    c-20261010-4f8afd: se guardo «Estoy corriendo CP-SAT…», 168 caracteres, en vez de la respuesta de
    4.805, y lo mismo le pasaba a {respuesta} de las reglas)."""
    tarjeta = s.get("last_reply") or ""
    path = s.get("transcript_path")
    if path and os.path.exists(path):
        try:
            ts = transcripts.turns(s["agent"], path, 1, leaf_id=transcripts.leaf_of(s))["turns"]
            final = ts[-1].get("final") if ts else None
            if final and len(final) >= len(tarjeta):
                return short(final, cap)
        except Exception as e:
            state.log(f"respuesta completa de {s['session_id'][:8]}: {e}")
    return short(tarjeta, cap) if tarjeta else ""


def render_template(tpl: str, s: dict | None, respuesta: str | None = None) -> str:
    """`respuesta`: la del turno que se avisa, ya recortada, si ya se leyo (la foto de la espera)."""
    if not s:
        return tpl.replace("{respuesta}", respuesta) if respuesta is not None else tpl
    if "{respuesta}" in tpl and respuesta is None:
        respuesta = full_reply(s)
    return (
        tpl.replace("{repo}", s.get("repo") or "")
        .replace("{agente}", s.get("agent") or "")
        .replace("{titulo}", s.get("title") or "")
        .replace("{pedido}", s.get("last_prompt") or "")
        .replace("{respuesta}", respuesta or "")
    )


SOLO_SI_MAX = 64
REPLY_CAP = 6000  # lo que lleva {respuesta}
FILTRO_CAP = 200_000  # el marcador se busca en la respuesta entera: el recorte guarda el principio


def huella(texto: str, pedido: str = "") -> str:
    """Hash corto de un turno: su respuesta y el pedido que la origino. Dos avisos con la misma huella
    son el mismo aviso (un Stop doble, una espera sin turno nuevo); el mismo «Listo.» a otra tarea, no."""
    if not texto:
        return ""
    return hashlib.sha256(f"{pedido}\x00{texto}".encode("utf-8", "replace")).hexdigest()[:16]


def turno_de(s: dict) -> dict:
    """{completa, huella} del ultimo turno de la sesion: la respuesta sin el recorte de {respuesta}."""
    completa = full_reply(s, FILTRO_CAP)
    return {"completa": completa, "huella": huella(completa, str(s.get("prompt_id") or s.get("last_prompt") or ""))}


def filtrada(r: dict, completa: str | None, h: str, espera: bool = True) -> str | None:
    """Por que una on_stop NO avisa este turno, o None si avisa (pedido de Ariel, 2026-10-16: en
    OpenSyync la coordinadora gastaba un turno por cada aviso repetido o sin novedad):
    - `solo_si`: la respuesta entera (`completa`) no trae el marcador (p. ej. "ESTADO:"): es un turno
      intermedio. `completa` None: ya se filtro (la foto de una espera) y no se mira de nuevo;
    - la huella es la de lo ultimo que entrego esta regla (`last_hash`), salvo `dedupe: false`, o la
      de lo que ya esta en espera (`espera`: al recibir el Stop, no al entregar). Sin huella (respuesta
      vacia) no se compara."""
    marca = r.get("solo_si")
    if marca and completa is not None and marca not in completa:
        return f"salteado: la respuesta no trae «{marca}» (turno intermedio)"
    if r.get("dedupe", True) and h:
        if r.get("last_hash") == h:
            return "salteado: misma respuesta que la ya entregada"
        if espera and (r.get("deferred") or {}).get("huella") == h:
            return "salteado: misma respuesta que la que ya está en espera"
    return None


ON_STOP_SETTLE_S = (
    15  # el Stop de una coda a veces llega en un hueco (compactacion, entre herramientas) y sigue trabajando
)
SIN_AVISO_MAX_S = 1800  # un sin_aviso que nadie consumio no calla un turno de horas despues


def normal_acuse(texto: str) -> str:
    """El texto de un acuse como se compara con el pedido del turno: espacios colapsados, 200 caracteres."""
    return " ".join((texto or "").split())[:200]


ON_STOP_COOLDOWN_S = 30  # dos sesiones conectadas en ambos sentidos no se contestan en bucle
# Una on_stop repetida no tiene tope total salvo que lo pida (limit="total"): se limita por frecuencia.
# Medido en OpenSyync (2026-10-14): 7 reglas con max_fires=30 llegaron a 30 en una sesion larga, se
# apagaron solas y la coordinadora dejo de recibir entregas sin aviso. El tope total cortaba avisos
# para siempre; la ventana solo los demora y los agrupa.
ON_STOP_RATE_MAX = 10  # disparos por ventana, por regla
ON_STOP_RATE_WINDOW_S = 600
RATE_MAX_TOPE, RATE_WINDOW_MIN_S, RATE_WINDOW_MAX_S = 60, 60, 86400
CONTINUE_TEXT = "Continuar"
CONTINUE_DELAY_S = 60
RETRY_DELAY_S = 10  # error de API: se reintenta en el acto, con diez segundos para cancelarlo
AT_NEAR_S = 120  # dos programadas a menos de 2 min son "la misma hora" (la UI guarda UTC, aca local)


def tope_total(r: dict) -> bool:
    """La regla se apaga al llegar a max_fires: una 'at', una on_stop de una sola vez, o una on_stop
    repetida que lo pidio explicito (`limit: "total"`). Las demas on_stop repetidas (tambien las
    viejas sin `limit`, que tenian el tope por defecto de quien las creo) se limitan por frecuencia."""
    return r.get("kind") != "on_stop" or not r.get("repeat") or r.get("limit") == "total"


def ventana(r: dict) -> tuple[int, int]:
    """(disparos, segundos) del limite por frecuencia de una on_stop repetida."""
    try:
        n = min(max(int(r.get("rate_max") or ON_STOP_RATE_MAX), 1), RATE_MAX_TOPE)
        w = min(max(int(r.get("rate_window_s") or ON_STOP_RATE_WINDOW_S), RATE_WINDOW_MIN_S), RATE_WINDOW_MAX_S)
    except TypeError, ValueError:
        n, w = ON_STOP_RATE_MAX, ON_STOP_RATE_WINDOW_S
    return n, w


def _recientes(r: dict, ahora: dt.datetime) -> list[dt.datetime]:
    _, w = ventana(r)
    out = [d for d in (local_dt(x) for x in r.get("recent_fires") or []) if d is not None]
    return sorted(d for d in out if (ahora - d).total_seconds() < w)


def proximo_permitido(r: dict, ahora: dt.datetime) -> tuple[dt.datetime | None, str]:
    """(cuando puede volver a disparar, motivo); None = ya. El enfriamiento corta los ida y vuelta
    inmediatos; la ventana corta el bucle largo sin apagar la regla."""
    cands: list[tuple[dt.datetime, str]] = []
    last = local_dt(r.get("last_fired")) if r.get("last_fired") else None
    if last is not None and (ahora - last).total_seconds() < ON_STOP_COOLDOWN_S:
        cands.append((last + dt.timedelta(seconds=ON_STOP_COOLDOWN_S), f"enfriamiento de {ON_STOP_COOLDOWN_S} s"))
    if not tope_total(r):
        n, w = ventana(r)
        rec = _recientes(r, ahora)
        if len(rec) >= n:
            cands.append((rec[-n] + dt.timedelta(seconds=w), f"limite de {n} cada {w // 60} min"))
    return max(cands, key=lambda c: c[0]) if cands else (None, "")


def _diferir(r: dict, hasta: dt.datetime, motivo: str, foto: dict | None = None) -> None:
    """Un Stop que no puede salir ahora queda en espera, visible en la regla: nunca se descarta
    callado. Con solo_si, cada informe sale en orden; las reglas sin marcador conservan
    su agrupacion historica. Todos los informes quedan persistidos. Con el lock."""
    if foto is not None and foto.get("huella"):
        informes.conservar(r, foto, now())
    prev = r.get("deferred") or {}
    queue = list(prev.get("queue") or [])
    if not queue and prev.get("respuesta") is not None:
        queue.append({"texto": prev["respuesta"], "huella": prev.get("huella") or ""})
    if foto is not None and not any(x["huella"] == foto["huella"] for x in queue):
        queue.append(dict(foto))
    n = int(prev.get("count") or 0) + 1
    r["deferred"] = {"since": prev.get("since") or now(), "count": n, "until": hasta.isoformat(timespec="seconds")}
    if queue and r.get("solo_si"):
        r["deferred"]["queue"] = queue
    if foto is not None:
        r["deferred"].update(respuesta=foto["texto"], huella=foto["huella"])
    elif prev.get("respuesta") is not None:
        r["deferred"].update(respuesta=prev["respuesta"], huella=prev.get("huella"))
    r["last_result"] = f"limitada ({motivo}): {n} aviso(s) en espera, sale a las {hasta.strftime('%H:%M:%S')}"


def at_near(r: dict, at: dt.datetime) -> bool:
    """La regla `r` (kind at) cae a menos de AT_NEAR_S segundos de `at`."""
    ref = local_dt(r.get("at"))
    return ref is not None and abs((ref - at).total_seconds()) <= AT_NEAR_S


def ensure_continue_rule(s: dict) -> None:
    """Una sesion avisa limite de uso con hora de vuelta: dejar programado "Continuar" un minuto
    despues, una sola vez por aviso. Solo con "auto_continue": true en ~/.lienzo/config.json
    (decision del autor: nada automatico sin tope; aca el tope es una regla de un disparo)."""
    until = s.get("limit_until")
    if not until or not load_config().get("auto_continue"):
        return
    if s.get("continue_scheduled_for") == until:
        return  # este aviso ya se atendio; si el usuario borro la regla, no se vuelve a crear
    hasta = local_dt(until)
    if hasta is None:
        return
    at = hasta + dt.timedelta(seconds=CONTINUE_DELAY_S)
    if at < dt.datetime.now().astimezone() - dt.timedelta(minutes=5):
        return  # aviso viejo: el cupo ya volvio, no hay nada que programar
    with lock:
        s["continue_scheduled_for"] = until
    schedule_continue(s, at, f"sin cupo hasta {until}")


def schedule_continue(s: dict, at: dt.datetime, motivo: str) -> None:
    """Deja programado "Continuar" para `s` a las `at`, una sola vez, si no hay ya una a esa hora.
    Con el lock; no envia nada (lo hace rules_loop, que corre cada 5 s)."""
    if s.get("external"):
        return  # a una ejecucion externa no se le escribe "Continuar": la retoma quien la lanzo
    at_iso = at.isoformat(timespec="seconds")
    with lock:
        for r in rules.items:
            if r.get("kind") == "at" and r.get("to") == s["session_id"] and at_near(r, at):
                return  # ya esta (manual o automatica, vigente o ya disparada)
        rule = {
            "id": secrets.token_hex(6),
            "kind": "at",
            "from": None,
            "to": s["session_id"],
            "text": CONTINUE_TEXT,
            "at": at_iso,
            "repeat": False,
            "max_fires": 1,
            "fired": 0,
            "enabled": True,
            "created": now(),
            "auto": True,
            "pc": identity.pc_id(),
        }
        agregar_regla(rule)
    state.log(
        f"regla automatica {rule['id']}: {s['agent']} {s['session_id'][:8]} {motivo}; '{CONTINUE_TEXT}' a las {at_iso}"
    )


def retry_after_api_error(s: dict, sig: str) -> None:
    """El turno murio con un error de API que se arregla reintentando ("API Error: The response
    stopped arriving"): mandar "Continuar" en el acto, una sola vez por error. Solo con
    "auto_retry": true en ~/.lienzo/config.json (mismo criterio que auto_continue: nada automatico
    sin tope; aca el tope es un reintento por aviso). El envio no se hace desde aca --apply_turn
    corre con el lock tomado y send_to_session puede tardar un minuto--: se deja una regla `at`
    para dentro de RETRY_DELAY_S segundos, que ademas le da al usuario tiempo de quitarla."""
    if not load_config().get("auto_retry"):
        return
    with lock:
        if s.get("retry_done_for") == sig:
            return  # este error ya se reintento; si el usuario borro la regla, no vuelve
        s["retry_done_for"] = sig
    schedule_continue(
        s,
        dt.datetime.now().astimezone() + dt.timedelta(seconds=RETRY_DELAY_S),
        f"error de API ({short(sig.split(':', 1)[-1], 80)})",
    )


def advance_at(rule: dict, ref: dt.datetime | None = None) -> None:
    """Regla 'at' periodica: correr `at` un periodo (every_s). Si aun asi queda en el pasado (el
    server estuvo caido), saltar los periodos perdidos hasta el primero futuro, sin disparar los
    que no se hicieron. Se guarda en hora local con segundos, como el resto."""
    every = int(rule["every_s"])
    ref = ref or dt.datetime.now().astimezone()
    at = (local_dt(rule.get("at")) or ref) + dt.timedelta(seconds=every)
    if at <= ref:
        missed = int((ref - at).total_seconds() // every) + 1
        at += dt.timedelta(seconds=missed * every)
    rule["at"] = at.isoformat(timespec="seconds")


def loop_conflict(rule: dict, local_rules: list[dict], remote_rules: list[dict]) -> dict | None:
    """La regla on_stop en sentido inverso (`to` -> `from`), ya habilitada en esta PC o en
    cualquier otra de la federacion, si existe: crearia un bucle A<->B que se contesta solo hasta
    agotar el cupo (plan multi-PC §3.5). Pura -- quien llama (server.create_on_stop, frente C, o
    _reserve_local de aca abajo) le pasa lo local y lo espejado (mirror.rules()) sin que este
    modulo dependa de mirror.py."""
    return next(
        (
            r
            for r in local_rules + remote_rules
            if r.get("enabled")
            and r.get("kind") == "on_stop"
            and r.get("from") == rule.get("to")
            and r.get("to") == rule.get("from")
        ),
        None,
    )


# --- lock de la PC de menor pc_id: la carrera de crear la regla inversa a la vez (plan §3.5) ----

_LOOP_LOCK_TTL_S = 10  # tiempo que dura una reserva sin confirmar: alcanza de sobra para que quien
# la pidio guarde la regla (rules.add tarda microsegundos); mas que eso y ya no vale la pena seguir
# bloqueando por una reserva que quiza nunca se confirma (la sesion desistio, o se cayo)
_loop_lock_guard = threading.Lock()
_reservations: dict[tuple[str | None, str | None], float] = {}


def _reserve_local(rule: dict) -> dict | None:
    """Con el lock de esta PC tomado (ella es la de menor pc_id para el par, o no hay para donde
    coordinar): `loop_conflict` contra lo local y lo espejado y, si no hay bucle, reserva el par
    (from, to) unos segundos para que la creacion concurrente de la inversa -- que todavia no esta
    guardada en ningun `rules.items` ni espejo, es la carrera que este lock existe para resolver --
    tambien la vea. Las reservas vencidas (`_LOOP_LOCK_TTL_S`) no cuentan, para no quedar
    bloqueado para siempre si quien la pidio nunca la confirma."""
    ahora = time.monotonic()
    clave, inverso = (rule.get("from"), rule.get("to")), (rule.get("to"), rule.get("from"))
    with _loop_lock_guard:
        for k, ts in list(_reservations.items()):
            if ahora - ts > _LOOP_LOCK_TTL_S:
                del _reservations[k]
        if inverso in _reservations:
            de, a = str(rule.get("from"))[:8], str(rule.get("to"))[:8]
            return {"error": f"crearía un bucle {de}↔{a}: otra PC está creando la inversa ahora mismo"}
        conflict = loop_conflict(rule, list(rules.items), ses._mirror_rules())
        if conflict is None:
            _reservations[clave] = ahora
        return conflict


def loop_lock(from_pc: str | None, to_pc: str | None, rule: dict) -> dict | None:
    """Chequea (y reserva) que crear `rule` (on_stop `from` -> `to`) no cierre un bucle A<->B,
    resolviendo la carrera de crearla a la vez en las dos PCs (plan multi-PC §3.5): siempre arbitra
    la PC de menor `pc_id` entre `from_pc` y `to_pc`. Si esta PC lo es (o no hay con quien
    coordinar: alguna de las dos puntas sin PC conocida, o la misma PC en las dos), chequea y
    reserva local (`_reserve_local`); si no, le pide lo mismo a la que sí lo es por
    `mirror.forward(menor, "POST", "/rules/lock", ...)` (frente C la engancha en
    `POST /peer/rules/lock` -> `handle_peer_lock`, abajo)."""
    if from_pc and to_pc and from_pc != to_pc:
        menor = min(from_pc, to_pc)
        if menor != from_pc:
            code, res = ses._mirror_forward(menor, "POST", "/rules/lock", {"rule": rule})
            if code != 200:
                return {"error": (res or {}).get("error") or f"no pude coordinar el chequeo con {menor}"}
            return res.get("conflict")
    return _reserve_local(rule)


def handle_peer_lock(req: dict) -> tuple[int, dict]:
    """Lado receptor de `POST /peer/rules/lock`: esta PC es la de menor `pc_id` para el par y
    arbitra con el mismo lock y la misma reserva que usa `loop_lock` cuando lo resuelve local."""
    rule = req.get("rule")
    if not isinstance(rule, dict):
        return 400, {"error": "rule debe ser un objeto"}
    return 200, {"conflict": _reserve_local(rule)}


# --- regla repetida y "a la misma hora": las decide la PC dueña del destino (plan §3.5) ---------


def _rule_clash(rule: dict, existing: list[dict]) -> dict | None:
    """`rule` (todavia sin crear) choca con alguna de `existing`: mismo destino y, segun el kind,
    mismo origen y texto (on_stop: "ya existe esa conexión") o a menos de AT_NEAR_S segundos (at:
    "ya hay una programada"). None si no choca con ninguna. Mismo dict de rechazo (con `rule_id`,
    y en el caso `at` tambien `replace`) que ya devolvia server.py antes de esta ronda."""
    to = rule.get("to")
    if rule.get("kind") == "on_stop":
        texto = (rule.get("text") or "").strip()
        dup = next(
            (
                r
                for r in existing
                if r.get("enabled")
                and r.get("kind") == "on_stop"
                and r.get("to") == to
                and (r.get("from") or None) == (rule.get("from") or None)
                and (r.get("text") or "").strip() == texto
            ),
            None,
        )
        return {"error": "ya existe esa conexión", "rule_id": dup["id"]} if dup else None
    if rule.get("kind") == "at":
        at = local_dt(rule.get("at"))
        if at is None:
            return None
        clash = next(
            (
                r
                for r in existing
                if r.get("enabled") and r.get("kind") == "at" and r.get("to") == to and at_near(r, at)
            ),
            None,
        )
        if clash is None:
            return None
        hhmm = local_dt(clash["at"]).strftime("%H:%M")
        return {
            "error": f"ya hay una programada a las {hhmm} para esa sesión",
            "rule_id": clash["id"],
            "at": clash["at"],
            "text": clash.get("text") or "",
            "replace": True,
        }
    return None


def check_at_destination(rule: dict) -> dict | None:
    """La regla repetida (on_stop) y la programada a menos de 2 min (at) las decide la PC dueña
    del destino (plan multi-PC §3.5): si `to` es de otra PC (`mirror.owner_of`), se le pide por
    `mirror.forward(..., "POST", "/rules/check", ...)` (frente C la engancha en
    `POST /peer/rules/check` -> `handle_peer_check`, abajo); si es local, se resuelve aca mismo
    contra lo local y lo espejado (una regla que apunta a esta sesion puede vivir en cualquier PC,
    la que sea dueña de su `from`)."""
    owner = ses._mirror_owner(rule.get("to") or "")
    if owner is not None:
        code, res = ses._mirror_forward(owner, "POST", "/rules/check", {"rule": rule})
        if code != 200:
            return {"error": (res or {}).get("error") or f"no pude consultar a {owner}"}
        return res.get("conflict")
    return _rule_clash(rule, list(rules.items) + ses._mirror_rules())


def handle_peer_check(req: dict) -> tuple[int, dict]:
    """Lado receptor de `POST /peer/rules/check`: esta PC es la dueña del destino."""
    rule = req.get("rule")
    if not isinstance(rule, dict):
        return 400, {"error": "rule debe ser un objeto"}
    return 200, {"conflict": _rule_clash(rule, list(rules.items) + ses._mirror_rules())}


def _espejo_incompleto() -> bool:
    """Hay PCs conectadas y alguna todavia no mando su snapshot: una tarjeta que no se ve puede ser
    una que todavia no llego. Sin federacion (o con un espejo que no sabe decirlo) es False."""
    m = getattr(getattr(ses, "mirror", None), "MIRROR", None)
    try:
        return m is not None and bool(m.peer_ids()) and not m.all_synced()
    except AttributeError:
        return False


def fire_rule(rule: dict, agrupados: int = 0) -> None:
    """Dispara `rule`. `agrupados` > 0: es la entrega diferida de una on_stop limitada, y el texto
    lo dice (cuantos avisos junta: va el del ultimo turno). Una on_stop avisa la foto del turno que
    le reservaron (`_fotos`: la de la espera o la que leyo fire_on_stop); sin foto, el ultimo turno."""
    with lock:
        src = sessions.get(rule.get("from") or "")
        foto = _fotos.pop(rule["id"], None)
    dst = find_session(rule["to"])
    if dst is None:
        # antes se borraba aca mismo y sin log: al arrancar, con el espejo vacio, una regla hacia
        # otra PC desaparecia sin rastro (revision 2026-10-04, B10). Si el destino puede estar en
        # una PC que todavia no se ve, se espera (rules_loop reintenta cada 5 s; on_stop, en el
        # proximo Stop); las de otra PC que de verdad ya no existen las estaciona purge_stale_xpc,
        # que corre con los peers sincronizados
        if rule.get("xpc") or _espejo_incompleto():
            motivo = "en espera: el destino todavia no se ve (otra PC sin conectar o sin sincronizar)"
            if rule.get("last_result") != motivo:
                with lock:
                    rule["last_result"] = motivo
                state.log(f"regla {rule['id']} ({rule.get('kind')}) -> {rule['to'][:8]}: {motivo}")
            return
        if rule.get("informes"):
            with lock:
                rule["last_result"] = "en espera: destino desconocido; informes conservados"
                rules.save()
            return
        rules.remove(lambda r: r["id"] == rule["id"])
        state.log(f"regla {rule['id']} ({rule.get('kind')}) -> {rule['to'][:8]}: borrada, el destino ya no existe")
        return
    periodic = rule.get("kind") == "at" and bool(rule.get("every_s"))
    if dst.get("stopped_by") and (periodic or rule.get("kind") == "on_stop"):
        # destino detenido (stopped): no se le manda ni se gasta el disparo; la 'at' de una sola
        # vez sigue abajo y queda con el 409 como resultado, si no se reintentaria cada vuelta
        with lock:
            if periodic:
                advance_at(rule)
            rule["last_result"] = "salteado: destino detenido (stopped)"
            rules.save()
        state.log(f"regla {rule['id']} ({rule['kind']}) -> {rule['to'][:8]}: salteado, destino detenido")
        rules.publish()
        return
    if periodic and rule.get("skip_busy", True) and dst.get("state") == "corriendo":
        # el destino esta trabajando: este disparo no cuenta, se pasa al periodo siguiente
        with lock:
            advance_at(rule)
            rule["last_result"] = "salteado: destino ocupado"
            rules.save()
        state.log(
            f"regla {rule['id']} (at cada {rule['every_s']} s) -> {rule['to'][:8]}: "
            f"salteado, destino ocupado; proximo {rule['at']}"
        )
        rules.publish()
        return
    on_stop = rule.get("kind") == "on_stop"
    respuesta = h = None
    if on_stop and (src is not None or foto is not None):
        if foto is not None:  # ya paso el marcador al cerrar el turno: solo se mira si se repite
            respuesta, h, completa = short(foto["texto"], REPLY_CAP), foto["huella"], None
        else:
            t = turno_de(src)
            respuesta, h, completa = short(t["completa"], REPLY_CAP), t["huella"], t["completa"]
        motivo = filtrada(rule, completa, h, espera=False)
        if motivo:
            # el mismo aviso otra vez (un Stop doble, una diferida sin turno nuevo) o un turno sin
            # el marcador: no se manda ni se gasta el disparo, y queda dicho en la regla y el log
            with lock:
                rule["last_result"] = motivo
                rules.save()
            state.log(f"regla {rule['id']} (on_stop) -> {rule['to'][:8]}: {motivo}")
            rules.publish()
            return
    text = render_template(rule.get("text") or "", src, respuesta)
    if agrupados:
        if rule.get("solo_si"):
            cuantos = f"informe demorado; {agrupados} aviso(s) en la espera"
        else:
            cuantos = (
                "un aviso demorado" if agrupados == 1 else f"{agrupados} avisos agrupados (va el del ultimo turno)"
            )
        text = f"[lienzo: {cuantos} por el limite de frecuencia de la regla {rule['id']}]" + chr(10) + text
    informe = None
    if on_stop and h:
        with lock:
            informe = informes.conservar(rule, {"texto": foto["texto"] if foto else completa, "huella": h}, now())
            if informe["intentos"] or informe["estado"] != "pendiente":
                return  # un reinicio no autoriza duplicar un envio incierto
            informe["intentos"] += 1
            informe["intento_at"] = now()
            try:
                if rules.save() is False:
                    raise OSError("no se pudo conservar el informe antes del envio")
            except Exception:
                informe["intentos"] -= 1
                informe.pop("intento_at", None)
                raise
        text = text.replace("{informe_id}", h).replace("{regla_id}", rule["id"])
    with captura.origen(clase="regla", de=src["session_id"] if src else None, rule_id=rule["id"], kind=rule["kind"]):
        code, res = send_to_session(dst, text, [])
    with lock:
        if informe is not None:
            informes.resultado(informe, code, res, now())
        rule["fired"] = rule.get("fired", 0) + 1
        rule["last_fired"] = now()
        rule["last_result"] = "ok" if code == 200 else str(res.get("error"))
        if code == 200 and res.get("estado"):
            rule["last_envio"] = {k: res.get(k) for k in ("estado", "motivo", "envio_id", "transporte", "at")}
            if res["estado"] != "entregado":
                rule["last_result"] = (
                    f"{res['estado']}: {res.get('motivo') or 'entrega sin confirmar; no se reintenta'}"
                )
        if on_stop and code == 200 and h:
            rule["last_hash"] = h
        if rule.get("kind") == "on_stop":
            ahora = dt.datetime.now().astimezone()
            recientes = [d.isoformat(timespec="seconds") for d in _recientes(rule, ahora)]
            rule["recent_fires"] = [*recientes, rule["last_fired"]][-RATE_MAX_TOPE:]
        exhausted = tope_total(rule) and rule.get("repeat") and rule["fired"] >= int(rule.get("max_fires") or 1)
        if not rule.get("repeat") or exhausted:
            rule["enabled"] = False
            rule["disabled_at"] = now()
            rule["disabled_reason"] = "tope total alcanzado" if exhausted else "regla de un solo disparo ejecutada"
        elif periodic:
            advance_at(rule)
        rules.save()
    state.log(f"regla {rule['id']} ({rule['kind']}) -> {rule['to'][:8]}: {rule['last_result']}")
    if exhausted:
        state.log(f"regla {rule['id']} agotada ({rule['fired']}/{rule.get('max_fires')} disparos, tope total)")
    elif periodic:
        state.log(f"regla {rule['id']} ({rule['fired']}/{rule.get('max_fires')}) proximo disparo {rule['at']}")
    if code == 200 and src and src["session_id"] != dst["session_id"]:
        add_link(src["session_id"], dst["session_id"], text, kind="rule", rule_id=rule["id"])
    rules.publish()


_on_stop_en_vuelo: set[str] = set()  # ids de reglas on_stop con un envio en curso; bajo `lock`
_fotos: dict[str, dict] = {}  # rule_id -> {texto, huella} del turno a avisar, reservada con la regla; bajo `lock`


def fire_on_stop(sid: str) -> None:
    """La sesion `sid` cerro un turno: disparar sus reglas 'cuando termine' (las que no esten
    enfriando, ver ON_STOP_COOLDOWN_S). La sesion queda reservada desde ya, tambien durante el
    asentamiento de coda: la reconciliacion no evalua el mismo turno en paralelo."""
    with lock:
        _evaluando[sid] = _evaluando.get(sid, 0) + 1
    try:
        _fire_on_stop(sid)
    finally:
        with lock:
            n = _evaluando.get(sid, 1) - 1
            if n > 0:
                _evaluando[sid] = n
            else:
                _evaluando.pop(sid, None)


def _fire_on_stop(sid: str) -> None:
    with lock:
        s0 = sessions.get(sid)
        desde = s0.get("state_since") if s0 and s0.get("agent") == "coda" else None
    if desde is not None and ON_STOP_SETTLE_S:
        time.sleep(ON_STOP_SETTLE_S)
        with lock:
            s1 = sessions.get(sid)
            if not s1 or s1.get("state") != "termino" or s1.get("state_since") != desde:
                state.log(f"on_stop de {sid[:8]} no disparado: la tarjeta volvio a trabajar (Stop intermedio de coda)")
                return
    with lock:
        cerrada = dict(sessions.get(sid) or {})
        _marcar_visto(sid, cerrada)
    _evaluar_on_stop(sid, cerrada)


def _evaluar_on_stop(sid: str, cerrada: dict) -> None:
    if cerrada:
        captura.respuesta(cerrada)  # la respuesta final queda en la memoria del proyecto (anexo A de v5)
        try:
            if consulta.espera(sid):
                # una vuelta de una consulta entre investigadores: la respuesta entera, sin el recorte de {respuesta}
                consulta.turno_cerrado(cerrada, full_reply(cerrada, consulta.TEXTO_MAX))
        except Exception:
            state.log(f"consulta, cierre de turno de {sid[:8]}:\n{traceback.format_exc()}")
    if cerrada.get("external"):
        # una ejecucion externa (un orquestador, un claude -p) no dispara reglas: su avance lo decide quien la
        # lanzo, y un "cuando termine" encadenaria envios sobre una corrida ajena
        state.log(f"on_stop de {sid[:8]} no disparado: es una ejecucion externa ({cerrada['external'].get('kind')})")
        return
    ahora = dt.datetime.now().astimezone()

    def suya(r: dict) -> bool:
        return bool(r.get("enabled")) and r.get("kind") == "on_stop" and r.get("from") == sid

    with lock:
        hay = any(suya(r) for r in rules.items)
    # la respuesta del turno, leida una vez y afuera del lock (puede leer la transcripcion): con ella
    # se filtra (marcador, repetida) antes de diferir y se saca la foto de la espera
    turno = turno_de(cerrada) if hay and cerrada else {"completa": "", "huella": ""}
    foto = {"texto": turno["completa"], "huella": turno["huella"]}
    with lock:
        s = sessions.get(sid)
        if s and any(suya(r) for r in rules.items):
            if hooks_eventos.compacting(s):
                state.log(f"on_stop de {sid[:8]} no disparado: la sesion esta compactando")
                return
            if s.get("last_error"):
                state.log(
                    f"on_stop de {sid[:8]} no disparado: el turno termino con error ({short(s['last_error'], 80)})"
                )
                return
            if (s.get("last_reply") or "").rstrip().endswith("?"):
                state.log(f"on_stop de {sid[:8]} no disparado: la respuesta termina en pregunta al usuario")
                return
        due, diferidas, salteadas = [], [], []
        # un envio con sin_aviso (un acuse): calla SOLO el turno que ese acuse empezo, el que tiene su
        # texto como pedido. Un acuse que llego en medio de otro turno no calla ese turno (que puede ser
        # la entrega), y uno que nunca fue su propio turno vence a los SIN_AVISO_MAX_S
        callar = (s or {}).get("sin_aviso") or {}
        if callar and time.time() - float(callar.get("desde") or 0) > SIN_AVISO_MAX_S:
            s["sin_aviso"], callar = None, {}
        elif callar and normal_acuse(s.get("last_prompt") or "") != callar.get("texto"):
            callar = {}  # otro turno: el pedido de silencio sigue esperando el suyo
        elif callar:
            s["sin_aviso"] = None
        for r in rules.items:
            if not suya(r):
                continue
            foto_regla = (
                {**foto, "huella": foto["huella"] + "-" + secrets.token_hex(6)} if r.get("dedupe") is False else foto
            )
            if callar and r.get("to") == callar.get("a"):
                r["last_result"] = "salteado: el turno respondía un envío sin_aviso"
                salteadas.append(r)
                continue
            filtro = filtrada(r, turno["completa"], turno["huella"])
            if filtro:
                r["last_result"] = filtro
                salteadas.append(r)
                continue
            if foto.get("huella"):
                informes.conservar(r, foto_regla, now())
                if rules.save() is False:
                    raise OSError("no se pudo conservar el informe del turno")
            if r["id"] in _on_stop_en_vuelo:
                # ya hay un envio de esta regla en curso: este turno espera su turno, no se pierde
                _diferir(r, ahora + dt.timedelta(seconds=ON_STOP_COOLDOWN_S), "envio anterior en curso", foto_regla)
                diferidas.append(r)
                continue
            hasta, motivo = proximo_permitido(r, ahora)
            if hasta is None and not r.get("deferred"):
                due.append(r)
                _fotos[r["id"]] = foto_regla
            else:
                # limitada, o ya habia avisos en espera: este se suma y sale todo junto (rules_loop)
                _diferir(r, hasta or ahora, motivo or "en espera", foto_regla)
                diferidas.append(r)
        if diferidas or salteadas:
            rules.save()
        # reservar bajo el lock ANTES de enviar: el enfriamiento sale de `last_fired`, que
        # fire_rule escribe recien despues de un envio de hasta 60 s; en ese hueco un segundo Stop
        # veia la regla fria y la disparaba otra vez (revision 2026-10-04, B11)
        for r in due:
            _on_stop_en_vuelo.add(r["id"])
    for r in diferidas + salteadas:
        state.log(f"on_stop de {sid[:8]}, regla {r['id']}: {r['last_result']}")
    if diferidas or salteadas:
        rules.publish()
    for r in due:
        try:
            fire_rule(r)
        except Exception:
            # una regla rota no se lleva puestas a las demas del mismo Stop, y queda en el log
            # (sessions.en_hilo atraparia la primera, pero cortando el resto; plan 1.1)
            state.log(f"on_stop de {sid[:8]}, regla {r['id']}:\n{traceback.format_exc()}")
        finally:
            with lock:
                _on_stop_en_vuelo.discard(r["id"])
                _fotos.pop(r["id"], None)


# --- reconciliacion: un turno cerrado que ninguna on_stop evaluo -------------------------------
# Medido el 2026-10-16 (regla 2054b0dd7f28): una <task-notification> reabrio el trabajo de A sin
# UserPromptSubmit; la transcripcion lo dio por terminado con la respuesta anterior (salteada por
# solo_si) y el Stop real, con «ESTADO:», ya no cambio el estado: set_state no vio transicion y la
# regla nunca evaluo la entrega. Sin depender de esa transicion, rules_loop compara el turno que
# muestra la tarjeta con el ultimo que cada regla evaluo y, si cambio y se quedo quieto, lo evalua.
RECONCILIA_S = 10  # el turno nuevo tiene que estar quieto este rato antes de evaluarlo
_evaluando: dict[str, int] = {}  # evaluaciones en curso por sesion (Stop y reconciliacion): no se cruzan
_pendientes: dict[str, tuple[str, float]] = {}  # sid -> (clave vista, desde cuando), sin evaluar


def clave_turno(s: dict) -> str:
    """Identidad barata del turno que muestra la tarjeta: su pedido y su respuesta. No lee la
    transcripcion; la evaluacion (turno_de) si, y solo cuando esta clave cambia."""
    pedido = str(s.get("prompt_id") or s.get("last_prompt") or "")
    return huella(s.get("last_reply") or "", pedido) or f"vacio:{pedido}"


def _marcar_visto(sid: str, s: dict) -> None:
    """Con el lock tomado: las on_stop de `sid` evaluaron (o descartaron) el turno de `s`. Queda en
    disco: tras un reinicio no se reevalua lo ya visto."""
    clave = clave_turno(s) if s else ""
    cambio = False
    for r in rules.items:
        if r.get("kind") == "on_stop" and r.get("from") == sid and r.get("turno_visto") != clave:
            r["turno_visto"], cambio = clave, True
    _pendientes.pop(sid, None)
    if cambio:
        rules.save()


def reconciliable(s: dict | None) -> bool:
    """La carrera Stop/transcripcion es de las sesiones de Claude con hooks: su respuesta la trae el
    Stop. Las demas cierran turno desde la transcripcion (sin hooks) o con su propio asentamiento
    (coda), y su `last_reply` cambia con cada lectura: reconciliarlas reevaluaria turnos viejos."""
    return bool(s) and s.get("agent") == "claude" and bool(s.get("hooked")) and not s.get("external")


def reconciliar(ahora: float | None = None) -> list[str]:
    """Sesiones en `termino` cuyo turno ninguna on_stop evaluo, quieto hace RECONCILIA_S: se evaluan
    con fire_on_stop, que aplica los mismos filtros, la dedupe y el enfriamiento. Una regla sin
    marca toma como visto el turno que encuentra (asi un despliegue no reevalua lo ya entregado);
    mientras la sesion corre, esa marca es la del turno en curso, y su cierre si se evalua.
    Devuelve las sesiones que se mandaron a evaluar."""
    ahora = time.time() if ahora is None else ahora
    listas, marcadas = [], False
    with lock:
        origenes = {r.get("from") for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop"}
        for sid in origenes:
            s = sessions.get(sid)
            if not reconciliable(s) or sid in _evaluando:
                _pendientes.pop(sid, None)
                continue
            clave = clave_turno(s)
            suyas = [r for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop" and r.get("from") == sid]
            for r in suyas:
                if "turno_visto" not in r:
                    r["turno_visto"], marcadas = clave, True
            if s.get("state") != "termino" or all(r["turno_visto"] == clave for r in suyas):
                _pendientes.pop(sid, None)
                continue
            vista, desde = _pendientes.get(sid, (None, ahora))
            if vista != clave:
                _pendientes[sid] = (clave, ahora)
            elif ahora - desde >= RECONCILIA_S:
                listas.append(sid)
                _evaluando[sid] = _evaluando.get(sid, 0) + 1  # reservada hasta que termine su evaluacion
                _pendientes.pop(sid, None)
        if marcadas:
            rules.save()
    for sid in listas:
        state.log(f"on_stop de {sid[:8]}: turno cerrado sin evaluar (Stop sin transicion); se evalua ahora")
        _lanzar(sid)
    return listas


def _lanzar(sid: str) -> None:
    """La evaluacion va en otro hilo: fire_on_stop puede enviar (hasta 60 s)."""
    threading.Thread(target=_reconciliar_una, args=(sid,), name=f"reconcilia-{sid[:8]}", daemon=True).start()


def _reconciliar_una(sid: str) -> None:
    try:
        fire_on_stop(sid)
    except Exception:
        state.log(f"reconciliacion on_stop de {sid[:8]}:\n{traceback.format_exc()}")
    finally:
        with lock:  # suelta la reserva que tomo reconciliar
            n = _evaluando.get(sid, 1) - 1
            if n > 0:
                _evaluando[sid] = n
            else:
                _evaluando.pop(sid, None)


def aviso_muerta(sid: str, prev: str) -> None:
    """La sesion `sid` murio (desaparecio su proceso) mientras estaba {prev}: con un encargo a medias.
    No hubo Stop, asi que sus reglas «cuando termine» nunca dispararian: se avisa a cada destino de
    esas reglas, una vez, con lo necesario para restaurarla (medido el 2026-10-03: una coda de la
    sesion 4 del curso murio sin contestar y nadie se entero)."""
    with lock:
        s = dict(sessions.get(sid) or {})
        destinos = {
            r["to"] for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop" and r.get("from") == sid
        }
    # conocimiento por proyecto (v5 §5.1): la muerte con un encargo a medias es un incidente de la
    # ronda, haya o no a quien avisar. Ya corre en un hilo (en_hilo desde marcar_muerta)
    conocimiento.incidente_operativo(
        sid, f"murio sin terminar su encargo (estaba {prev})", herramienta="sesion", datos={"estado": prev}
    )
    if not s or not destinos:
        return
    titulo = s.get("title") or s.get("repo") or sid[:8]
    pedido = short(s.get("last_prompt") or "", 160)
    texto = (
        f"[aviso automático] «{titulo}» ({sid[:8]}) murió sin terminar su encargo (estaba {prev}"
        + (f"; último pedido: {pedido}" if pedido else "")
        + f"). Restaurala con su contexto: coordinar.restaurar(session_id='{sid}', pc='{s.get('pc') or ''}')"
        " y pedile que retome."
    )
    for to in destinos:
        try:
            dst = find_session(to)
            if dst is None:
                state.log(f"aviso de muerte de {sid[:8]} -> {to[:8]}: el destino no se ve, no se avisa")
                continue
            with captura.origen(de=sid, kind="aviso_muerta"):
                code, res = send_to_session(dst, texto, [])
        except Exception:
            # un destino roto no deja sin aviso a los demas, y queda en el log (plan 1.1)
            state.log(f"aviso de muerte de {sid[:8]} -> {to[:8]}:\n{traceback.format_exc()}")
            continue
        state.log(f"aviso de muerte de {sid[:8]} -> {to[:8]}: {'ok' if code == 200 else res.get('error')}")


def aviso_sin_avance(sid: str, desde: str) -> None:
    """La sesion `sid` sigue «corriendo» pero no avanza desde `desde` (sessions.sin_avance): se avisa a
    cada destino de sus reglas «cuando termine», como aviso_muerta, para que alguien mire su pantalla."""
    with lock:
        s = dict(sessions.get(sid) or {})
        destinos = {
            r["to"] for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop" and r.get("from") == sid
        }
    titulo = s.get("title") or s.get("repo") or sid[:8]
    minutos = state.SIN_AVANCE_S // 60
    state.log(f"{sid[:8]} «{titulo}»: corriendo sin avance desde {desde} (mas de {minutos} min)")
    if not s or not destinos:
        return
    texto = (
        f"[aviso automático] «{titulo}» ({sid[:8]}) lleva más de {minutos} min «corriendo» sin ningún avance "
        "(ni eventos, ni herramientas, ni transcripción). Puede estar trabada en un diálogo: mirá su pantalla "
        f"(GET /sessions/{sid}/screen, pc='{s.get('pc') or ''}') y preguntale o destrabala."
    )
    for to in destinos:
        try:
            dst = find_session(to)
            if dst is None:
                continue
            with captura.origen(de=sid, kind="aviso_sin_avance"):
                code, res = send_to_session(dst, texto, [])
        except Exception:
            state.log(f"aviso sin avance de {sid[:8]} -> {to[:8]}:\n{traceback.format_exc()}")
            continue
        state.log(f"aviso sin avance de {sid[:8]} -> {to[:8]}: {'ok' if code == 200 else res.get('error')}")


def entregas_diferidas(ahora: dt.datetime) -> list[tuple[dict, int]]:
    """Las on_stop con avisos en espera que ya pueden salir: [(regla, cuantos)]. Las reserva en
    _on_stop_en_vuelo bajo el lock (como fire_on_stop) y les consume la espera al reservarlas. Si
    el limite sigue (la ventana no se libero), corre la hora y siguen esperando, sin perderse."""
    listas: list[tuple[dict, int]] = []
    cambio = False
    with lock:
        for r in rules.items:
            d = r.get("deferred")
            if not (d and r.get("enabled") and r.get("kind") == "on_stop") or r["id"] in _on_stop_en_vuelo:
                continue
            hasta = local_dt(d.get("until"))
            if hasta is not None and hasta > ahora:
                continue
            nuevo, motivo = proximo_permitido(r, ahora)
            if nuevo is not None:
                d["until"] = nuevo.isoformat(timespec="seconds")
                r["last_result"] = (
                    f"limitada ({motivo}): {d.get('count')} aviso(s) en espera, sale a las {nuevo.strftime('%H:%M:%S')}"
                )
                cambio = True
                continue
            # la espera se consume al reservar: un Stop que llegue durante este envio abre otra
            _on_stop_en_vuelo.add(r["id"])
            cantidad = int(d.get("count") or 1)
            queue = list(d.get("queue") or [])
            if queue:
                primera = queue.pop(0)
                _fotos[r["id"]] = primera
                if queue:
                    d["queue"], d["count"] = queue, len(queue)
                    d["until"] = (ahora + dt.timedelta(seconds=ON_STOP_COOLDOWN_S)).isoformat()
                    r["deferred"] = d
                else:
                    r["deferred"] = None
            else:
                r["deferred"] = None
            if not queue and r["id"] not in _fotos and d.get("respuesta") is not None:
                _fotos[r["id"]] = {"texto": d["respuesta"], "huella": d.get("huella") or ""}
            listas.append((r, cantidad))
            cambio = True
        if cambio:
            rules.save()
    if cambio:
        rules.publish()
    return listas


def recuperar_informes() -> list[dict]:
    """Recupera fotos conservadas sin intento; los envios inciertos requieren conciliacion.

    No crea reglas ni despierta por acuses. Conserva limites, destino y reserva por regla.
    """
    listas = []
    with lock:
        for r in rules.items:
            if not r.get("enabled") or r.get("kind") != "on_stop":
                continue
            if r.get("deferred") or r["id"] in _on_stop_en_vuelo:
                continue
            if proximo_permitido(r, dt.datetime.now().astimezone())[0] is not None:
                continue
            informe = next((x for x in r.get("informes", []) if x["estado"] == "pendiente" and not x["intentos"]), None)
            if informe is not None:
                _on_stop_en_vuelo.add(r["id"])
                _fotos[r["id"]] = {"texto": informe["respuesta"], "huella": informe["id"]}
                listas.append(r)
    return listas


def _reservar_recordatorio(r: dict, informe: dict, t: dt.datetime):
    """Reserva durable antes del transporte; un fallo incierto nunca se reintenta solo."""
    with lock:
        entrega = local_dt(informe.get("entregado_at"))
        dst = find_session(r.get("to"))
        if (
            informe.get("estado") != "entregado"
            or informe.get("recordatorio_at")
            or entrega is None
            or (t - entrega).total_seconds() < state.INFORME_SIN_ACUSE_S
            or not dst
            or dst.get("state") != "termino"
            or dst.get("stopped_by")
        ):
            return None
        silencio = dst.get("sin_aviso") or {}
        if silencio and time.time() - float(silencio.get("desde") or 0) <= SIN_AVISO_MAX_S:
            return None  # no pisar el silencio de otro aviso todavía sin consumir
        for regla in rules.items:
            for previo in regla.get("informes", []):
                reservado = local_dt(previo.get("recordatorio_at"))
                destino = previo.get("recordatorio_destino")
                if destino == r["to"] and reservado is not None and (t - reservado).total_seconds() <= SIN_AVISO_MAX_S:
                    return None
        texto = (
            f"[informe sin acuse] {session_name(r.get('from'))} ({r.get('from')}) entregó {informe['id']}. "
            "Integralo y verificá, o comunicá el bloqueo concreto. "
            f"Acusá con POST /rules/{r['id']}/informes/{informe['id']}/acuse "
            f'{{"session_id":"{r["to"]}","estado":"recibido"}}; después estado="integrado" al verificar.'
        )
        informe["recordatorio_at"] = t.isoformat()
        informe["recordatorio_destino"] = r["to"]
        try:
            if rules.save(strict=True) is False:
                raise OSError("no se pudo conservar el recordatorio antes del envio")
        except Exception:
            informe.pop("recordatorio_at", None)
            informe.pop("recordatorio_destino", None)
            raise
        return dst, texto


def recordar_informes(t: dt.datetime) -> None:
    """Un intento por informe, incluso en reglas agotadas; nunca acusa ni integra por el agente."""
    with lock:
        pendientes = [(r, i) for r in rules.items for i in r.get("informes", [])]
    destinos = set()
    for r, informe in pendientes:
        if r.get("to") in destinos:
            continue
        try:
            reservado = _reservar_recordatorio(r, informe, t)
        except Exception:
            state.log(f"reserva de recordatorio {informe['id']}:\n{traceback.format_exc()}")
            rules.publish()
            continue
        if reservado is None:
            continue
        dst, texto = reservado
        destinos.add(r["to"])
        state.log(f"recordatorio informe {informe['id']}, regla {r['id']} -> {r['to']}: reservado sin_aviso")
        try:
            import preguntas

            if preguntas.enviar is None:
                raise RuntimeError("el enrutador de consultas no está instalado")
            code, res = preguntas.enviar(
                dst["session_id"], {"text": texto, "from": r["from"], "sin_aviso": True}
            )
            with lock:
                informe["recordatorio_resultado"] = {"codigo": code, **res}
                rules.save(strict=True)
            state.log(f"recordatorio informe {informe['id']}: {code} {res}")
        except Exception:
            state.log(f"recordatorio informe {informe['id']}:\n{traceback.format_exc()}")
        rules.publish()


def recordatorios_loop(stop=None) -> None:
    """El transporte de recordatorios nunca ocupa el planificador de reglas."""
    stop = stop if stop is not None else threading.Event()
    while not stop.is_set():
        try:
            recordar_informes(dt.datetime.now().astimezone())
        except Exception:
            state.log(traceback.format_exc())
        stop.wait(5)


def rules_loop() -> None:
    while True:
        try:
            reconciliar_cableado()
            # primero y aparte: un envio lento o una regla rota de abajo no la posterga
            reconciliar()  # turnos cerrados que ninguna on_stop evaluo (un Stop sin transicion)
        except Exception:
            state.log(traceback.format_exc())
        try:
            t = dt.datetime.now().astimezone()
            due = []
            diferidas = entregas_diferidas(t)
            with lock:
                for r in rules.items:
                    if not (r.get("enabled") and r.get("kind") == "at" and r.get("at")):
                        continue
                    at = local_dt(r["at"])
                    if at is None:  # hora ilegible: la regla no se puede disparar nunca
                        r["enabled"] = False
                        r["disabled_at"] = now()
                    elif at <= t:
                        due.append(r)
            diferidas.extend((r, 0) for r in recuperar_informes())
            for r, n in diferidas:
                try:
                    fire_rule(r, agrupados=n)
                except Exception:
                    state.log(f"regla {r.get('id')}, entrega diferida:" + chr(10) + traceback.format_exc())
                finally:
                    with lock:
                        _on_stop_en_vuelo.discard(r["id"])
                        _fotos.pop(r["id"], None)
            for r in due:
                try:
                    fire_rule(r)
                except Exception:
                    # una regla rota no frena a las demas vencidas (antes cortaba la pasada entera,
                    # y en cada vuelta otra vez, si la rota seguia vencida)
                    state.log(f"regla {r.get('id')}:\n{traceback.format_exc()}")
            rondas.revisar()  # avisos coordinados y turnos: confirma, vence y pasa el turno
        except Exception:
            state.log(traceback.format_exc())
        time.sleep(5)


def purge_stale_xpc(known_remote, known_local, *, peer_id: str | None = None) -> int:
    """Saca las reglas con destino en otra PC cuyo destino ya no existe en ningun lado. Solo se llama
    con los peers sincronizados (mirror.all_synced): antes, una tarjeta ajena que no se ve es una que
    todavia no llego. `known_local(sid)` y `known_remote(sid)` dicen si la tarjeta existe."""
    limite = dt.datetime.now().astimezone() - dt.timedelta(seconds=ses.SUCESION_MAX_S)
    with lock:
        rotas = [
            r
            for r in rules.items
            if r.get("xpc")
            and (peer_id is None or r.get("to_pc") == peer_id)
            and not r.get("parked_to")
            and not known_local(r["to"])
            and not known_remote(r["to"])
        ]
        # el destino desaparecio: en vez de borrarlas se estacionan, por si la PC del destino avisa
        # que hay una sucesora (POST /peer/rules/retarget); las que nadie heredo en 24 h se van
        for r in rotas:
            r["parked_to"], r["parked_since"], r["enabled"] = r["to"], now(), False
        viejas = {
            r["id"]
            for r in rules.items
            if r.get("parked_since")
            and (local_dt(r["parked_since"]) or limite) < limite
            and not r.get("archived_at")
            and not any(x.get("estado") != "integrado" for x in r.get("informes", []))
        }
        if viejas:
            rules.items[:] = [r for r in rules.items if r["id"] not in viejas]
        if rotas or viejas:
            rules.save()
    if rotas:
        state.log(f"{len(rotas)} reglas con destino en otra PC que ya no existe: en espera de una sucesora")
    return len(rotas)


def purge_stale_at_rules(max_age_h: float = 24.0) -> None:
    """Al arrancar: sacar las reglas 'a las HH:MM' que ya dispararon o quedaron deshabilitadas
    hace mas de max_age_h horas. Las on_stop se conservan (viven con la sesion)."""
    limit = dt.datetime.now().astimezone() - dt.timedelta(hours=max_age_h)

    def stale(r: dict) -> bool:
        if informes.pendientes(r) or r.get("archived_at"):
            return False
        if r.get("kind") != "at" or r.get("enabled"):
            return False
        ref = local_dt(r.get("disabled_at") or r.get("last_fired") or r.get("created"))
        return ref is None or ref < limit

    with lock:
        n = sum(1 for r in rules.items if stale(r))
        if n:
            rules.items[:] = [r for r in rules.items if not stale(r)]
            rules.save()
    if n:
        state.log(f"purgadas {n} reglas 'at' viejas (disparadas o deshabilitadas hace mas de {max_age_h:g} h)")


def _startup_federation_reason() -> str | None:
    """El arranque aún no conectó peers: un espejo vacío no prueba ausencia de inversas."""
    try:
        with open(os.path.join(state.LIENZO, "peers.json"), encoding="utf-8") as stream:
            peers = json.load(stream)
    except FileNotFoundError:
        peers = {}
    except OSError, ValueError:
        return "no se pudo verificar peers.json; rehabilitá explícitamente después de verificar la federación"
    if not isinstance(peers, dict) or peers or ses._mirror_sessions() or ses._mirror_rules():
        return "topología remota sin acreditar al arrancar; rehabilitá explícitamente cuando esté disponible"
    return None


def reactivar_agotadas_por_tope_viejo() -> int:
    """Al arrancar: prende las on_stop repetidas que apago el tope total de antes (2026-10-14), ahora
    limitadas por frecuencia. Se reconocen porque se apagaron en su ultimo disparo (`disabled_at` a
    menos de un segundo de `last_fired`: son dos now() seguidos) con `fired` >= `max_fires`; antes
    habia que editarlas a mano con `limit:"rate"`."""

    def agotada(r: dict) -> bool:
        apagada, disparo = local_dt(r.get("disabled_at")), local_dt(r.get("last_fired"))
        return (
            r.get("kind") == "on_stop"
            and bool(r.get("repeat"))
            and not r.get("enabled")
            and not tope_total(r)
            and not r.get("parked_since")
            and not r.get("archived_at")
            and apagada is not None
            and disparo is not None
            and abs((apagada - disparo).total_seconds()) < 1
            and int(r.get("fired") or 0) >= int(r.get("max_fires") or 1)
        )

    federation_reason = _startup_federation_reason()  # lectura de disco fuera del lock, sin red
    ids, bloqueadas = [], []
    changed = False
    with lock:
        for r in rules.items:
            if not agotada(r):
                continue
            source_error = on_stop_source_error(find_session(r.get("from")))
            existentes = [x for x in list(rules.items) + ses._mirror_rules() if x.get("id") != r["id"]]
            conflicto = loop_conflict(r, existentes, []) or _rule_clash(r, existentes)
            reason = source_error[1]["error"] if source_error else None
            if not reason and conflicto:
                reason = conflicto.get("error") or "hay una regla inversa habilitada"
            if not reason and (
                r.get("xpc") or r.get("to_pc") or r.get("from") not in sessions or r.get("to") not in sessions
            ):
                reason = "las puntas locales no están acreditadas; rehabilitá explícitamente después de verificarlas"
            reason = reason or federation_reason
            if reason:
                resultado = "No rehabilitada al arrancar: " + reason
                changed |= r.get("disabled_reason") != reason or r.get("last_result") != resultado
                r["disabled_reason"], r["last_result"] = reason, resultado
                bloqueadas.append(r["id"])
                continue
            # El commit se hace con el mismo lock y cada candidata ve las habilitadas del lote.
            r["enabled"] = True
            r.pop("disabled_at", None)
            r.pop("disabled_reason", None)
            ids.append(r["id"])
            changed = True
        if changed:
            rules.save()
    if ids:
        state.log(f"{len(ids)} reglas on_stop agotadas por el tope viejo, prendidas de nuevo: {', '.join(ids)}")
    if bloqueadas:
        state.log(
            f"{len(bloqueadas)} reglas agotadas siguen deshabilitadas por validación de arranque: {', '.join(bloqueadas)}"
        )
    return len(ids)


# sessions.py no importa este modulo: se engancha aca
ses.on_turn_end = fire_on_stop
ses.on_limit_notice = ensure_continue_rule
ses.on_died_working = aviso_muerta
ses.on_sin_avance = aviso_sin_avance
ses.on_api_error = retry_after_api_error
