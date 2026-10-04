"""Restaurar sesiones tras un reinicio de PC: cuando la PC se reinicia mueren todos los agentes y el
lienzo borra las tarjetas muertas a los 60 s; sin este registro no queda donde estaba cada sesion
ni como relanzarla. Aca vive `~/.lienzo/restaurar.json`: una entrada por sesion que se puede
retomar (`{session_id, agent, cwd, title, repo, pc, saved_at, ended_at}`), con escritura atomica y
lock como el resto del estado, y poda sola (7 dias, tope 200).

Cuando se recuerda una tarjeta (lo decide sessions.py, esto solo guarda):
- las VIVAS con hooks, de forma incremental y con debounce (`remember_live`): un reinicio brusco
  no deja que el server vea la muerte, asi que el registro tiene que existir de antes;
- las MUERTAS al borrarse (`ended_at` puesto).
Una sesion que termino a proposito (`/exit`, logout; ver `ended_on_purpose`) no se recuerda, y si ya
estaba guardada se olvida. Una relanzada o borrada a mano tambien se olvida (`forget`).

Este modulo no importa sessions.py (sessions.py lo importa a el)."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time

import identity
import launch
import state

MAX_AGE_DAYS = 7
MAX_ENTRIES = 200
LIVE_DEBOUNCE_S = 30.0
REFRESH_SAVED_S = 300.0  # una entrada sin cambios no se reescribe antes de esto

# claude y codex retoman por id: tiene que ser un UUID de verdad (el `pid-NNN` de una tarjeta del
# barrido no sirve). pi y coda retoman "la ultima de esta carpeta": alcanza con el cwd
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_BY_ID = ("claude", "codex")

# razones de SessionEnd que NO son una salida a proposito: "other" es lo que deja cerrar la
# ventana o apagar la PC; sin razon (hook viejo o evento perdido) tampoco hay prueba de salida
# Razones de SessionEnd que son salida voluntaria (lista blanca): una razon nueva que Claude Code
# agregue cuenta como muerte a restaurar, que es el error barato (antes era lista negra y una razon
# nueva hacia perder la sesion sin avisar).
ON_PURPOSE = frozenset({"exit", "logout", "prompt_input_exit", "clear", "resume", "bypass_permissions_disabled"})

_lock = threading.RLock()
_last_live: dict[str, float] = {}


def path() -> str:
    return os.path.join(state.LIENZO, "restaurar.json")


def _clock() -> float:
    return time.monotonic()


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _iso(d: dt.datetime) -> str:
    return d.isoformat(timespec="milliseconds")


def valid_id(agent: str, sid) -> bool:
    if not isinstance(sid, str) or not sid:
        return False
    return bool(_UUID_RE.fullmatch(sid)) if agent in _BY_ID else True


def ended_on_purpose(card: dict) -> bool:
    """La tarjeta termino con un SessionEnd cuya razon indica salida voluntaria: `exit`, `logout`,
    `prompt_input_exit` (/exit), y tambien `clear` y `resume` (la sesion sigue en otro id) o
    `bypass_permissions_disabled`. Solo `other` (ventana cerrada, apagado) o la falta de razon se
    consideran muerte a restaurar. Sin SessionEnd (el proceso desaparecio, un reinicio) tampoco."""
    if card.get("last_event") != "SessionEnd":
        return False
    return card.get("end_reason") in ON_PURPOSE


def eligible(card: dict) -> bool:
    agent, cwd = card.get("agent"), card.get("cwd")
    if agent not in launch.AGENT_EXES or not isinstance(cwd, str) or not cwd:
        return False
    if not os.path.isdir(cwd):
        return False
    return valid_id(agent, card.get("session_id"))


# --- archivo ---------------------------------------------------------------------------------


def _read() -> list[dict]:
    try:
        with open(path(), encoding="utf-8") as f:
            d = json.load(f)
    except OSError, ValueError:
        return []
    if not isinstance(d, list):
        return []
    return [e for e in d if isinstance(e, dict) and isinstance(e.get("session_id"), str) and e.get("agent")]


def _ts(e: dict) -> dt.datetime:
    return state.parse_ts(e.get("ended_at") or e.get("saved_at")) or dt.datetime.min.replace(tzinfo=dt.UTC)


def _prune(items: list[dict]) -> list[dict]:
    """Sin las de mas de 7 dias y con un tope de 200 (las mas nuevas), la mas nueva primero."""
    limit = _now() - dt.timedelta(days=MAX_AGE_DAYS)
    vivas = [e for e in items if _ts(e) >= limit]
    vivas.sort(key=_ts, reverse=True)
    return vivas[:MAX_ENTRIES]


def _write(items: list[dict]) -> None:
    try:
        os.makedirs(state.LIENZO, exist_ok=True)
        state.atomic_write(path(), json.dumps(items, ensure_ascii=False, indent=1))
    except OSError as e:
        state.log(f"no se pudo guardar restaurar.json: {e}")


def _entry(card: dict, ended: bool) -> dict:
    now = _now()
    return {
        "session_id": card["session_id"],
        "agent": card["agent"],
        "cwd": card["cwd"],
        "title": card.get("title") or None,
        "repo": card.get("repo") or os.path.basename(card["cwd"].rstrip("\\/")) or "?",
        "pc": card.get("pc") or identity.pc_id(),
        "saved_at": _iso(now),
        "ended_at": _iso(now) if ended else None,
    }


def _same(a: dict, b: dict) -> bool:
    keys = ("session_id", "agent", "cwd", "title", "repo", "pc", "ended_at")
    return all(a.get(k) == b.get(k) for k in keys)


def _replaces(e: dict, new: dict) -> bool:
    """Misma sesion: mismo id; o, para pi/coda con un id que no es de verdad (`pid-NNN`, que cambia en
    cada arranque), mismo agente en la misma carpeta (retoman la ultima de esa carpeta)."""
    if e["session_id"] == new["session_id"]:
        return True
    return (
        new["agent"] not in _BY_ID
        and e.get("agent") == new["agent"]
        and os.path.normcase(os.path.normpath(e.get("cwd") or "")) == os.path.normcase(os.path.normpath(new["cwd"]))
        and (new["session_id"].startswith("pid-") or e["session_id"].startswith("pid-"))
    )


def _store(cards: list[dict], ended: bool) -> int:
    """Una lectura y una escritura para varias tarjetas. Devuelve cuantas se escribieron."""
    with _lock:
        items = _read()
        changed = 0
        for card in cards:
            prev = next((e for e in items if _replaces(e, card)), None)
            new = _entry(card, ended)
            if prev is not None and not ended and prev.get("ended_at") is None and _same(prev, new):
                # sin cambios: no se reescribe, salvo para refrescar saved_at de vez en cuando
                age = (_now() - (state.parse_ts(prev.get("saved_at")) or _now())).total_seconds()
                if age < REFRESH_SAVED_S:
                    continue
            items = [e for e in items if e is not prev]
            items.append(new)
            changed += 1
        if changed:
            _write(_prune(items))
        return changed


# --- API ---------------------------------------------------------------------------------------


def remember(card: dict, ended: bool = True) -> bool:
    """Guarda (o actualiza) la sesion de `card`. `ended` pone `ended_at` (la muerte se vio);
    sin el queda como "viva la ultima vez que se miro". False si no corresponde: agente
    desconocido, sin cwd o cwd que no es una carpeta, o sin un session_id de verdad."""
    if not eligible(card) or ended_on_purpose(card):
        return False
    return _store([card], ended) > 0


def live_due(session_id) -> bool:
    """True si `remember_live` miraria hoy esta sesion (paso el debounce). No marca nada."""
    return _clock() - _last_live.get(session_id, -1e9) >= LIVE_DEBOUNCE_S


def remember_live(cards) -> int:
    """Las tarjetas VIVAS con hooks, de forma incremental: cada sesion se mira a lo sumo cada
    `LIVE_DEBOUNCE_S` segundos y una entrada sin cambios no se reescribe. Devuelve cuantas escribio."""
    ahora = _clock()
    listas = []
    for c in cards:
        sid = c.get("session_id")
        if not c.get("hooked") or not c.get("alive") or c.get("state") == "muerta":
            continue
        # el debounce va antes de `eligible` (que toca el disco): una tarjeta que casi siempre se
        # descarta no tiene que costar un isdir cada 2 s
        if ahora - _last_live.get(sid, -1e9) < LIVE_DEBOUNCE_S:
            continue
        _last_live[sid] = ahora
        if not eligible(c) or ended_on_purpose(c):
            continue
        listas.append(c)
    for sid in [k for k, t in _last_live.items() if ahora - t > 3600]:
        del _last_live[sid]
    return _store(listas, False) if listas else 0


def restorables(live=()) -> list[dict]:
    """Las restaurables de esta PC, la mas nueva primero. `live`: ids de tarjetas que hoy estan
    vivas, que no hay nada que restaurar. Poda en memoria lo viejo."""
    excluir = set(live)
    with _lock:
        items = _prune(_read())
    return [dict(e) for e in items if e["session_id"] not in excluir]


def forget(session_id: str) -> bool:
    _last_live.pop(session_id, None)
    with _lock:
        items = _read()
        rest = [e for e in items if e["session_id"] != session_id]
        if len(rest) == len(items):
            return False
        _write(_prune(rest))
        return True
