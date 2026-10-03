"""Reglas del lienzo: "cuando termine" (on_stop) y "a las HH:MM" (at: una vez, o cada every_s
segundos con tope max_fires), la regla automatica "Continuar" ante un limite de uso con hora, el
disparo (fire_rule), el bucle de las programadas, la purga de las viejas y la vista de conexiones
de una sesion. Importa sessions.py para enviar y
registrar links; sessions.py lo llama por los ganchos on_turn_end / on_limit_notice, que se
rellenan al final de este modulo."""

from __future__ import annotations

import datetime as dt
import os
import secrets
import threading
import time
import traceback

import identity
import sessions as ses
import state
import transcripts
from sessions import add_link, find_session, send_to_session
from state import links, load_config, lock, now, rules, sessions, short


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


def full_reply(s: dict, cap: int = 6000) -> str:
    """Ultima respuesta completa, leida de la transcripcion (la tarjeta guarda 600 caracteres y una
    revision entera no entra ahi). Si no se puede leer, lo que tiene la tarjeta."""
    path = s.get("transcript_path")
    if path and os.path.exists(path):
        try:
            ts = transcripts.turns(s["agent"], path, 1, leaf_id=transcripts.leaf_of(s))["turns"]
            if ts and ts[-1].get("final"):
                return short(ts[-1]["final"], cap)
        except Exception as e:
            state.log(f"respuesta completa de {s['session_id'][:8]}: {e}")
    return s.get("last_reply") or ""


def render_template(tpl: str, s: dict | None) -> str:
    if not s:
        return tpl
    return (
        tpl.replace("{repo}", s.get("repo") or "")
        .replace("{agente}", s.get("agent") or "")
        .replace("{titulo}", s.get("title") or "")
        .replace("{pedido}", s.get("last_prompt") or "")
        .replace("{respuesta}", full_reply(s) if "{respuesta}" in tpl else "")
    )


ON_STOP_SETTLE_S = 15  # coda no tiene hooks: su "termino" sale de leer la pantalla y a veces es un hueco entre dos herramientas
ON_STOP_COOLDOWN_S = 30  # dos sesiones conectadas en ambos sentidos no se contestan en bucle
CONTINUE_TEXT = "Continuar"
CONTINUE_DELAY_S = 60
RETRY_DELAY_S = 10  # error de API: se reintenta en el acto, con diez segundos para cancelarlo
AT_NEAR_S = 120  # dos programadas a menos de 2 min son "la misma hora" (la UI guarda UTC, aca local)


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
        rules.add(rule, cap=500)
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


def fire_rule(rule: dict) -> None:
    with lock:
        src = sessions.get(rule.get("from") or "")
    dst = find_session(rule["to"])
    if dst is None:
        rules.remove(lambda r: r["id"] == rule["id"])
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
    text = render_template(rule.get("text") or "", src)
    code, res = send_to_session(dst, text, [])
    with lock:
        rule["fired"] = rule.get("fired", 0) + 1
        rule["last_fired"] = now()
        rule["last_result"] = "ok" if code == 200 else str(res.get("error"))
        exhausted = rule.get("repeat") and rule["fired"] >= int(rule.get("max_fires") or 1)
        if not rule.get("repeat") or exhausted:
            rule["enabled"] = False
            rule["disabled_at"] = now()
        elif periodic:
            advance_at(rule)
        rules.save()
    state.log(f"regla {rule['id']} ({rule['kind']}) -> {rule['to'][:8]}: {rule['last_result']}")
    if exhausted:
        state.log(f"regla {rule['id']} agotada ({rule['fired']}/{rule.get('max_fires')} disparos)")
    elif periodic:
        state.log(f"regla {rule['id']} ({rule['fired']}/{rule.get('max_fires')}) proximo disparo {rule['at']}")
    if code == 200 and src and src["session_id"] != dst["session_id"]:
        add_link(src["session_id"], dst["session_id"], text, kind="rule", rule_id=rule["id"])
    rules.publish()


def fire_on_stop(sid: str) -> None:
    """La sesion `sid` cerro un turno: disparar sus reglas 'cuando termine' (las que no esten
    enfriando, ver ON_STOP_COOLDOWN_S)."""
    with lock:
        s0 = sessions.get(sid)
        desde = s0.get("state_since") if s0 and s0.get("agent") == "coda" else None
    if desde is not None and ON_STOP_SETTLE_S:
        time.sleep(ON_STOP_SETTLE_S)
        with lock:
            s1 = sessions.get(sid)
            if not s1 or s1.get("state") != "termino" or s1.get("state_since") != desde:
                state.log(f"on_stop de {sid[:8]} no disparado: la tarjeta volvio a trabajar (cierre falso de coda)")
                return
    ahora = dt.datetime.now().astimezone()

    def suya(r: dict) -> bool:
        return bool(r.get("enabled")) and r.get("kind") == "on_stop" and r.get("from") == sid

    def enfriando(r: dict) -> bool:
        last = local_dt(r.get("last_fired")) if r.get("last_fired") else None
        return last is not None and (ahora - last).total_seconds() < ON_STOP_COOLDOWN_S

    with lock:
        s = sessions.get(sid)
        if s and any(suya(r) for r in rules.items):
            if s.get("last_error"):
                state.log(
                    f"on_stop de {sid[:8]} no disparado: el turno termino con error ({short(s['last_error'], 80)})"
                )
                return
            if (s.get("last_reply") or "").rstrip().endswith("?"):
                state.log(f"on_stop de {sid[:8]} no disparado: la respuesta termina en pregunta al usuario")
                return
        due = [r for r in rules.items if suya(r) and not enfriando(r)]
    for r in due:
        fire_rule(r)


def rules_loop() -> None:
    while True:
        try:
            t = dt.datetime.now().astimezone()
            due = []
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
            for r in due:
                fire_rule(r)
        except Exception:
            state.log(traceback.format_exc())
        time.sleep(5)


def purge_stale_xpc(known_remote, known_local) -> int:
    """Saca las reglas con destino en otra PC cuyo destino ya no existe en ningun lado. Solo se llama
    con los peers sincronizados (mirror.all_synced): antes, una tarjeta ajena que no se ve es una que
    todavia no llego. `known_local(sid)` y `known_remote(sid)` dicen si la tarjeta existe."""
    with lock:
        rotas = [r for r in rules.items if r.get("xpc") and not known_local(r["to"]) and not known_remote(r["to"])]
        if rotas:
            ids = {r["id"] for r in rotas}
            rules.items[:] = [r for r in rules.items if r["id"] not in ids]
            rules.save()
    if rotas:
        state.log(f"purgadas {len(rotas)} reglas con destino en otra PC que ya no existe")
    return len(rotas)


def purge_stale_at_rules(max_age_h: float = 24.0) -> None:
    """Al arrancar: sacar las reglas 'a las HH:MM' que ya dispararon o quedaron deshabilitadas
    hace mas de max_age_h horas. Las on_stop se conservan (viven con la sesion)."""
    limit = dt.datetime.now().astimezone() - dt.timedelta(hours=max_age_h)

    def stale(r: dict) -> bool:
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


# sessions.py no importa este modulo: se engancha aca
ses.on_turn_end = fire_on_stop
ses.on_limit_notice = ensure_continue_rule
ses.on_api_error = retry_after_api_error
