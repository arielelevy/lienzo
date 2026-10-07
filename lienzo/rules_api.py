"""La API de reglas del lienzo: validar, dar de alta y editar reglas (POST /rules, PUT /rules/<id>),
funciones puras que devuelven (codigo, cuerpo) y no saben de HTTP. Las usan server.Handler (el
tablero) y server.PeerHandler (una regla que crea otra PC, plan §3.5).

Vivian en server.py (ola 2 del refactor, 2026-10-04): ~300 lineas que no eran del server. No van
a rules.py, que es el disparo y el bucle de las reglas, ni a restore.py, que sessions importa (y
esto mira el espejo y la identidad de la PC: seria un ciclo). server.py las reexporta mientras
las pruebas las importen de ahi."""

from __future__ import annotations

import datetime as dt
import math
import secrets

import identity
import mirror
import rules as rl
import state
from rules import at_near, local_dt
from state import lock, now, rules, sessions, short

MIN_EVERY_S = 60
MAX_FIRES = 50


def clamp_fires(value) -> int:
    """max_fires: cuantas veces puede disparar una regla, entre 1 y MAX_FIRES."""
    return max(1, min(int(value), MAX_FIRES))


def parse_every_s(v) -> tuple[int | None, str | None]:
    """Periodo de una regla 'at': (segundos, error). None sin error es un solo disparo."""
    malo = "every_s debe ser un entero en segundos"
    if v is None:
        return None, None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None, malo
    try:
        f = float(v)
    except ValueError:
        return None, malo
    if not math.isfinite(f) or f != int(f):
        return None, malo
    if int(f) < MIN_EVERY_S:
        return None, f"every_s debe ser al menos {MIN_EVERY_S} segundos"
    return int(f), None


def at_fields(d: dict, current: dict | None = None) -> tuple[dict | None, str | None]:
    """Campos de repeticion de una regla 'at' (POST o PUT): every_s (entero >= MIN_EVERY_S, o None
    = un solo disparo), max_fires (1..MAX_FIRES; 5 por defecto si es periodica), skip_busy (True por
    defecto si es periodica). `current` es la regla que se edita (PUT), para no pisar lo que no
    vino. Devuelve (campos, error)."""
    cur = current or {}
    every = cur.get("every_s")
    if "every_s" in d:
        every, err = parse_every_s(d["every_s"])
        if err:
            return None, err
    max_fires = cur.get("max_fires")
    if d.get("max_fires") is not None:
        try:
            max_fires = clamp_fires(d["max_fires"])
        except TypeError, ValueError, OverflowError:
            return None, "max_fires debe ser un numero"
    elif every and (max_fires or 1) <= 1:
        max_fires = 5  # pasa a periodica sin tope explicito: 5 disparos
    skip_busy = cur.get("skip_busy")
    if "skip_busy" in d:
        skip_busy = bool(d["skip_busy"])
    elif skip_busy is None:
        skip_busy = bool(every)
    return {
        "every_s": every,
        "max_fires": int(max_fires or 1),
        "skip_busy": bool(skip_busy),
        "repeat": bool(every),
    }, None


def parse_at(value) -> dt.datetime:
    """Hora de una regla `at`, siempre local: naive se asume local, aware (la UI manda UTC con Z) se
    convierte, asi todas las reglas guardan `at` con el mismo offset. Es rules.local_dt, que es de
    donde sale toda hora del lienzo, pero levantando ValueError: aca un `at` ilegible es un 400 al
    cliente, no una regla que se saltea en silencio."""
    at = local_dt(value)
    if at is None:
        raise ValueError(f"{value!r} no es una fecha ISO")
    return at


def find_enabled(pred) -> dict | None:
    """La primera regla habilitada que cumple `pred`, leyendo la lista con el lock tomado. Es el
    "¿ya hay una parecida?" de las tres validaciones que miran las reglas que ya existen."""
    with lock:
        return next((r for r in rules.items if r.get("enabled") and pred(r)), None)


def _known_session(sid: str | None) -> bool:
    """`sid` existe, local o en el espejo de algun peer (plan §3.5: el destino de una regla puede
    vivir en otra PC)."""
    if not sid:
        return False
    return sid in sessions or mirror.MIRROR.owner_of(sid) is not None


def _rule_target_pc(sid: str | None) -> str | None:
    """`pc_id` de quien tiene a `sid`, o None si es local (o no se conoce)."""
    if not sid or sid in sessions:
        return None
    return mirror.MIRROR.owner_of(sid)


def check_rule(d: dict) -> tuple[int, dict] | None:
    """Lo que se valida igual para las dos clases de regla: el kind y que las sesiones existan
    (local o en otra PC, plan §3.5). Devuelve el (codigo, cuerpo) del rechazo, o None si el pedido
    pasa."""
    if d.get("kind") not in ("on_stop", "at"):
        return 400, {"error": "kind debe ser on_stop o at"}
    if not _known_session(d.get("to")):
        return 404, {"error": "sesion destino desconocida"}
    if d["kind"] == "on_stop" and not _known_session(d.get("from")):
        return 404, {"error": "sesion origen desconocida"}
    return None


def check_remote_destination(d: dict, text: str) -> dict | None:
    """Si el destino ('to') vive en otra PC (plan §3.5): valida contra ella antes de guardar nada
    aca: `rules.check_at_destination` (duplicado o programada cercana, del lado del destino) y
    `rules.loop_lock` (la carrera A<->B, en la PC de menor pc_id). Devuelve el conflicto (dict para el 409) o None si no hay que frenar nada.
    """
    to_pc = _rule_target_pc(d.get("to"))
    if to_pc is None:
        return None
    from_pc = _rule_target_pc(d.get("from")) or identity.pc_id()
    rule_preview = {**d, "text": text, "pc": identity.pc_id()}
    return rl.check_at_destination(rule_preview) or rl.loop_lock(from_pc, to_pc, rule_preview)


def new_rule(d: dict, text: str, **extra) -> dict:
    """Los campos que toda regla nueva tiene iguales; `extra` agrega los propios de cada clase. El
    orden de las claves es el del cuerpo que devuelve /rules, asi que se arma en ese orden."""
    return {
        "id": secrets.token_hex(6),
        "kind": d["kind"],
        "from": d.get("from") or None,
        "to": d["to"],
        "text": text,
        "pc": identity.pc_id(),
        # destino en otra PC: al reiniciar, esa tarjeta todavia no esta en el espejo y la regla se
        # descartaba por "destino desconocido"; esta marca la salva hasta que el espejo se asiente
        **({"xpc": True, "to_pc": pc} if (pc := _rule_target_pc(d.get("to"))) else {}),
        **extra,
    }


def check_global_loop(d: dict) -> dict | None:
    """El bucle A<->B es global (plan §3.5): `rules.loop_conflict` mira la regla candidata contra
    las reglas locales y las del espejo, no solo contra `rules.items`."""
    if d.get("kind") != "on_stop":
        return None
    with lock:
        local_items = list(rules.items)
    return rl.loop_conflict(d, local_items, mirror.MIRROR.rules())


def create_on_stop(d: dict, text: str) -> tuple[int, dict]:
    """Regla on_stop nueva: se rechaza el bucle (ya hay una en sentido inverso, en cualquier PC de
    la federacion) y la conexion repetida (mismo origen, mismo destino y mismo texto)."""
    conflicto_global = check_global_loop(d)
    if conflicto_global:
        return 409, conflicto_global
    try:
        max_fires = clamp_fires(d.get("max_fires") or 1)
    except TypeError, ValueError, OverflowError:
        return 400, {"error": "max_fires debe ser un numero"}
    # los chequeos contra las reglas locales y el alta, bajo UN lock (revision 2026-10-04, S11):
    # con locks separados, dos POST iguales a la vez pasaban los dos el de duplicado. `lock` es
    # reentrante, asi que find_enabled y rules.add lo vuelven a tomar sin trabarse; adentro no hay
    # red (check_global_loop y check_remote_destination quedan afuera)
    with lock:
        return _alta_on_stop(d, text, max_fires)


def _alta_on_stop(d: dict, text: str, max_fires: int) -> tuple[int, dict]:
    inverse = find_enabled(
        lambda r: r.get("kind") == "on_stop" and r.get("from") == d["to"] and r.get("to") == d["from"]
    )
    if inverse:
        return 409, {
            "error": f"crearía un bucle {d['from'][:8]}↔{d['to'][:8]}: "
            f"ya existe la regla {inverse['id']} en sentido inverso"
        }
    dup = find_enabled(
        lambda r: (
            r.get("kind") == "on_stop"
            and r.get("to") == d["to"]
            and (r.get("from") or None) == (d.get("from") or None)
            and (r.get("text") or "").strip() == text.strip()
        )
    )
    if dup:
        return 409, {"error": "ya existe esa conexión", "rule_id": dup["id"]}
    rule = new_rule(
        d,
        text,
        at=None,
        repeat=bool(d.get("repeat")),
        max_fires=max_fires,
        fired=0,
        enabled=True,
        created=now(),
    )
    rules.add(rule, cap=500)
    state.log(f"regla nueva {rule['id']}: on_stop -> {rule['to'][:8]}")
    return 200, rule


def create_at(d: dict, text: str) -> tuple[int, dict]:
    """Regla at nueva: una programada, con repeticion o de un solo disparo."""
    try:
        at = parse_at(d.get("at"))
    except ValueError:
        return 400, {"error": "at debe ser una fecha ISO"}
    extra, err = at_fields(d)
    if err:
        return 400, {"error": err}
    with lock:  # el choque y el alta bajo un solo lock, como en create_on_stop (S11)
        return _alta_at(d, text, at, extra)


def _alta_at(d: dict, text: str, at: dt.datetime, extra: dict) -> tuple[int, dict]:
    # dos programadas a la misma consola en el mismo minuto se inyectan juntas ("Continuar" y
    # "continua" a las 01:01): choca cualquier `at` habilitada a +-2 min, periodica o no, sea cual
    # sea el texto; con "replace": true la nueva reemplaza a la existente
    clash = find_enabled(lambda r: r.get("kind") == "at" and r.get("to") == d["to"] and at_near(r, at))
    if clash:
        if d.get("replace") is not True:
            hhmm = parse_at(clash["at"]).strftime("%H:%M")
            return 409, {
                "error": f"ya hay una programada a las {hhmm} para esa sesión",
                "rule_id": clash["id"],
                "at": clash["at"],
                "text": clash.get("text") or "",
                "replace": True,
            }
        rules.remove(lambda r: r["id"] == clash["id"])
        state.log(
            f"regla {clash['id']} ({clash.get('at')} {short(clash.get('text') or '', 40)!r}) reemplazada por una nueva a la misma hora"
        )
    # de at_fields salen every_s, max_fires, skip_busy y repeat=bool(every_s)
    rule = new_rule(d, text, at=at.isoformat(timespec="seconds"), fired=0, enabled=True, created=now(), **extra)
    rules.add(rule, cap=500)
    cada = f" cada {rule['every_s']} s x{rule['max_fires']}" if rule.get("every_s") else ""
    state.log(f"regla nueva {rule['id']}: at -> {rule['to'][:8]} {rule['at']}{cada}")
    return 200, rule


def create_rule(d: dict) -> tuple[int, dict]:
    """POST /rules: valida lo comun, y si el destino es de otra PC la consulta antes de guardar
    nada (check_remote_destination), y deja el armado en la funcion de la clase que corresponda.
    Devuelve (codigo, cuerpo)."""
    rechazo = check_rule(d)
    if rechazo is not None:
        return rechazo
    if d["kind"] == "on_stop":
        origen = _rule_target_pc(d.get("from"))
        if origen is not None:
            if mirror.MIRROR.supports(origen, "rules.create") is False:
                return 502, {
                    "code": "unsupported_capability",
                    "error": "la otra PC no soporta rules.create; actualiza su lienzo",
                }
            # el Stop ocurre en la PC del origen, y es esa PC la que dispara la regla (plan §3.5):
            # guardarla aca no la dispararia nunca. Se crea alla, y aca se ve por el espejo.
            code, res = mirror.MIRROR.forward(origen, "POST", "/rules", d)
            if code == 404 and (res or {}).get("error") == "ruta desconocida":
                return 502, {
                    "error": "la otra PC tiene un lienzo viejo que no sabe crear reglas: git pull y reiniciarlo"
                }
            return code, res
    text = str(d.get("text") or "")
    conflicto = check_remote_destination(d, text)
    if conflicto:
        return 409, conflicto
    return create_on_stop(d, text) if d["kind"] == "on_stop" else create_at(d, text)


def edit_rule(rule_id: str, d: dict) -> tuple[int, dict]:
    """PUT /rules/<id>: edita una conexion pendiente (doble click en la flecha): texto, hora,
    repeticion. Una programada que ya disparo se puede reprogramar: vuelve a quedar vigente.
    Devuelve (codigo, cuerpo), como create_rule. Primero valida todo y despues escribe: un 400 a
    mitad de camino dejaria la regla editada por partes."""
    at = None
    if d.get("at") is not None:
        try:
            at = parse_at(d["at"])
        except ValueError:
            return 400, {"error": "at debe ser una fecha ISO"}
    if "text" in d and not isinstance(d["text"], str):
        return 400, {"error": "text debe ser un texto"}
    try:
        max_fires = clamp_fires(d["max_fires"]) if d.get("max_fires") is not None else None
    except TypeError, ValueError, OverflowError:
        return 400, {"error": "max_fires debe ser un numero"}
    with lock:
        r = next((x for x in rules.items if x["id"] == rule_id), None)
        if r is None:
            return 404, {"error": "conexion desconocida"}
        extra = None
        if r.get("kind") == "at":
            extra, err = at_fields(d, r)
            if err:
                return 400, {"error": err}
        # de aca en adelante no se rechaza nada mas: `extra` con algo adentro es la regla 'at' ya validada
        if "text" in d:
            r["text"] = d["text"]
        if extra is not None:
            r.update(extra)  # every_s (null = un disparo), max_fires, skip_busy, repeat
            if at is not None:
                r["at"] = at.isoformat(timespec="seconds")
                if not r.get("enabled"):
                    r["enabled"] = True
                    r["fired"] = 0
                    r.pop("disabled_at", None)
        if r.get("kind") == "on_stop":
            if "repeat" in d:
                r["repeat"] = bool(d["repeat"])
            if max_fires is not None:
                r["max_fires"] = max_fires
        rules.save()
    rules.publish()
    state.log(
        f"regla {r['id']} editada: {r['kind']} -> {r['to'][:8]} {r.get('at') or ''} {short(r.get('text') or '', 60)!r}"
    )
    return 200, r
