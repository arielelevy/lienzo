"""Reglas del lienzo: "cuando termine" (on_stop) y "a las HH:MM" (at), la regla automatica
"Continuar" ante un limite de uso con hora, el disparo (fire_rule), el bucle de las programadas, la
purga de las viejas y la vista de conexiones de una sesion. Importa sessions.py para enviar y
registrar links; sessions.py lo llama por los ganchos on_turn_end / on_limit_notice, que se
rellenan al final de este modulo."""
from __future__ import annotations

import datetime as dt
import os
import secrets
import time
import traceback

import sessions as ses
import state
import transcripts
from sessions import add_link, send_to_session
from state import links, load_config, lock, now, rules, sessions, short


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
    def decorate(x: dict, ts_key: str) -> dict:
        out = dict(x)
        out["direction"] = "out" if x.get("from") == sid else "in"
        other = x.get("to") if out["direction"] == "out" else x.get("from")
        if other:
            name = session_name(other)
        else:
            name = "vos (lienzo)" if x.get("kind") == "user" else "(hora fija)"
        out["other"] = {"session_id": other, "name": name}
        out["_ts"] = x.get(ts_key) or ""
        return out

    with lock:
        ls = [decorate(l, "ts") for l in links.items if sid in (l.get("from"), l.get("to"))]
        rs = [decorate(r, "created") for r in rules.items if sid in (r.get("from"), r.get("to"))]
    for coll in (ls, rs):
        # fecha descendente; a igual fecha (mismo milisegundo), el agregado despues va primero
        order = sorted(enumerate(coll), key=lambda ix: (ix[1]["_ts"], ix[0]), reverse=True)
        coll[:] = [x for _, x in order]
        for x in coll:
            del x["_ts"]
    return {"links": ls, "rules": rs}

def full_reply(s: dict, cap: int = 6000) -> str:
    """Ultima respuesta completa, leida de la transcripcion (la tarjeta guarda 600 caracteres y una
    revision entera no entra ahi). Si no se puede leer, lo que tiene la tarjeta."""
    path = s.get("transcript_path")
    if path and os.path.exists(path):
        try:
            ts = transcripts.turns(s["agent"], path, 1)["turns"]
            if ts and ts[-1].get("final"):
                return short(ts[-1]["final"], cap)
        except Exception as e:  # noqa: BLE001
            state.log(f"respuesta completa de {s['session_id'][:8]}: {e}")
    return s.get("last_reply") or ""


def render_template(tpl: str, s: dict | None) -> str:
    if not s:
        return tpl
    return (tpl.replace("{repo}", s.get("repo") or "").replace("{agente}", s.get("agent") or "")
            .replace("{titulo}", s.get("title") or "").replace("{pedido}", s.get("last_prompt") or "")
            .replace("{respuesta}", full_reply(s) if "{respuesta}" in tpl else ""))

CONTINUE_TEXT = "Continuar"
CONTINUE_DELAY_S = 60


def ensure_continue_rule(s: dict) -> None:
    """Una sesion avisa limite de uso con hora de vuelta: dejar programado "Continuar" un minuto
    despues, una sola vez por aviso. Solo con "auto_continue": true en ~/.lienzo/config.json
    (decision del autor: nada automatico sin tope; aca el tope es una regla de un disparo)."""
    until = s.get("limit_until")
    if not until or not load_config().get("auto_continue"):
        return
    if s.get("continue_scheduled_for") == until:
        return  # este aviso ya se atendio; si el usuario borro la regla, no se vuelve a crear
    try:
        at = dt.datetime.fromisoformat(until) + dt.timedelta(seconds=CONTINUE_DELAY_S)
    except ValueError:
        return
    if at < dt.datetime.now().astimezone() - dt.timedelta(minutes=5):
        return  # aviso viejo: el cupo ya volvio, no hay nada que programar
    at_iso = at.isoformat(timespec="seconds")

    def near(r: dict) -> bool:
        # mismo instante aunque el offset difiera (la UI guarda UTC, aca local): +-2 min
        try:
            return abs((dt.datetime.fromisoformat(r["at"]) - at).total_seconds()) <= 120
        except (KeyError, TypeError, ValueError):
            return False

    with lock:
        s["continue_scheduled_for"] = until
        for r in rules.items:
            if r.get("kind") == "at" and r.get("to") == s["session_id"] and near(r):
                return  # ya esta (manual o automatica, vigente o ya disparada)
        rule = {"id": secrets.token_hex(6), "kind": "at", "from": None, "to": s["session_id"],
                "text": CONTINUE_TEXT, "at": at_iso, "repeat": False, "max_fires": 1, "fired": 0,
                "enabled": True, "created": now(), "auto": True}
        rules.add(rule, cap=500)
    state.log(f"regla automatica {rule['id']}: {s['agent']} {s['session_id'][:8]} sin cupo hasta {until}; "
        f"'{CONTINUE_TEXT}' a las {at_iso}")


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
        exhausted = rule.get("repeat") and rule["fired"] >= int(rule.get("max_fires") or 1)
        if not rule.get("repeat") or exhausted:
            rule["enabled"] = False
            rule["disabled_at"] = now()
        rules.save()
    state.log(f"regla {rule['id']} ({rule['kind']}) -> {rule['to'][:8]}: {rule['last_result']}")
    if exhausted:
        state.log(f"regla {rule['id']} agotada ({rule['fired']}/{rule.get('max_fires')} disparos)")
    if code == 200 and src and src["session_id"] != dst["session_id"]:
        add_link(src["session_id"], dst["session_id"], text, kind="rule", rule_id=rule["id"])
    rules.publish()


def fire_on_stop(sid: str) -> None:
    """La sesion `sid` cerro un turno: disparar sus reglas 'cuando termine' (con enfriamiento
    de 30 s para que dos sesiones conectadas en ambos sentidos no se contesten en bucle)."""
    due = []
    with lock:
        s = sessions.get(sid)
        has_rules = any(r.get("enabled") and r.get("kind") == "on_stop" and r.get("from") == sid for r in rules.items)
        if s and has_rules:
            if s.get("last_error"):
                state.log(f"on_stop de {sid[:8]} no disparado: el turno termino con error ({short(s['last_error'], 80)})")
                return
            if (s.get("last_reply") or "").rstrip().endswith("?"):
                state.log(f"on_stop de {sid[:8]} no disparado: la respuesta termina en pregunta al usuario")
                return
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
                            r["disabled_at"] = now()
            for r in due:
                fire_rule(r)
        except Exception:  # noqa: BLE001
            state.log(traceback.format_exc())
        time.sleep(5)


def purge_stale_at_rules(max_age_h: float = 24.0) -> None:
    """Al arrancar: sacar las reglas 'a las HH:MM' que ya dispararon o quedaron deshabilitadas
    hace mas de max_age_h horas. Las on_stop se conservan (viven con la sesion)."""
    limit = dt.datetime.now().astimezone() - dt.timedelta(hours=max_age_h)

    def stale(r: dict) -> bool:
        if r.get("kind") != "at" or r.get("enabled"):
            return False
        ref = r.get("disabled_at") or r.get("last_fired") or r.get("created")
        if not ref:
            return True
        try:
            return dt.datetime.fromisoformat(ref) < limit
        except ValueError:
            return True

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
