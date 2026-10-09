"""Carpetas abiertas estos dias: una entrada por (PC, carpeta) con la ultima vez que el tablero vio una
sesion viva ahi, para que «Lanzar CLI» las ofrezca abajo, grisadas, debajo de las carpetas de
`launch_roots`. Vive en `~/.lienzo/recientes.json`, con escritura atomica y poda sola (14 dias,
tope 60). A diferencia de restaurar.json no guarda sesiones sino carpetas: una que termino con
/exit tambien cuenta como «abierta estos dias».

Se alimenta de las tarjetas que pasan por el tablero, locales (sessions.remember_live_cards, cada
pasada de liveness) y espejadas (mirror._apply_event): el registro no distingue de donde vino,
guarda `pc` para que el dialogo filtre por la PC elegida. Con debounce en memoria: una entrada ya
vista hace menos de `DEBOUNCE_S` no se reescribe.

No importa sessions.py ni mirror.py (ellos lo importan)."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time

import atomico
import identity
import state

MAX_AGE_DAYS = 14
MAX_ENTRIES = 60
DEBOUNCE_S = 600.0  # cada cuanto se vuelve a mirar el disco por una misma carpeta

_lock = threading.RLock()
_last_seen: dict[str, float] = {}  # clave -> time.monotonic() de la ultima escritura


def path() -> str:
    return os.path.join(state.LIENZO, "recientes.json")


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _clave(pc: str, cwd: str) -> str:
    return f"{pc}|{os.path.normcase(os.path.normpath(cwd))}"


def _ts(e: dict) -> dt.datetime:
    return state.parse_ts(e.get("last")) or dt.datetime.min.replace(tzinfo=dt.UTC)


def _read() -> list[dict]:
    try:
        with open(path(), encoding="utf-8") as f:
            d = json.load(f)
    except OSError, ValueError:
        return []
    if not isinstance(d, list):
        return []
    return [
        e
        for e in d
        if isinstance(e, dict) and isinstance(e.get("cwd"), str) and e["cwd"] and isinstance(e.get("pc"), str)
    ]


def _prune(items: list[dict]) -> list[dict]:
    """Sin las de mas de 14 dias y con tope de 60 (las mas nuevas), la mas nueva primero."""
    limite = _now() - dt.timedelta(days=MAX_AGE_DAYS)
    vivas = [e for e in items if _ts(e) >= limite]
    vivas.sort(key=_ts, reverse=True)
    return vivas[:MAX_ENTRIES]


def _write(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    atomico.atomic_write(path(), json.dumps(items, ensure_ascii=False, indent=1))


def campos(cards) -> list[dict]:
    """De las tarjetas, solo las vivas con carpeta y solo lo que usa el registro: se llama con el
    lock del tablero o del espejo tomado, y copiar la tarjeta entera ahi era gasto puro."""
    return [
        {"cwd": s.get("cwd"), "pc": s.get("pc"), "repo": s.get("repo"), "alive": True}
        for s in cards
        if s.get("alive") and s.get("cwd")
    ]


def recordar_tarjetas(cards, pc: str | None = None) -> int:
    """Las tarjetas VIVAS con carpeta pasan al registro (una entrada por PC y carpeta, `last` de
    ahora). Las sin `pc` son de `pc` (la PC del espejo que las trajo) o, sin el, de esta PC.
    Devuelve cuantas entradas escribio; con todas dentro del debounce no toca el disco. Nunca
    levanta: perder un reciente no vale un hilo caido."""
    try:
        return _recordar(cards, pc)
    except Exception as e:
        state.avisar_si_cambia("recientes", f"recientes fallo: {e!r}")
        return 0


def _recordar(cards, pc_defecto: str | None) -> int:
    ahora = time.monotonic()
    nuevas: dict[str, dict] = {}
    local = pc_defecto
    for s in cards:
        cwd = s.get("cwd")
        if not s.get("alive") or not isinstance(cwd, str) or not cwd:
            continue
        pc = s.get("pc")
        if not isinstance(pc, str) or not pc:
            if local is None:
                local = identity.pc_id()
            pc = local
        k = _clave(pc, cwd)
        if k in nuevas or ahora - _last_seen.get(k, -1e9) < DEBOUNCE_S:
            continue  # la misma carpeta dos veces en la pasada: la primera escritura vale
        nuevas[k] = {"cwd": cwd, "repo": s.get("repo") or os.path.basename(cwd.rstrip("/\\")), "pc": pc}
    if not nuevas:
        return 0
    hoy = _now()
    marca = hoy.isoformat(timespec="milliseconds")
    with _lock:
        actuales = _read()
        for e in actuales:
            k = _clave(e["pc"], e["cwd"])
            # el dialogo muestra el dia, no la hora: una entrada ya marcada hoy no se reescribe
            if k in nuevas and _ts(e).astimezone().date() == hoy.date() and e.get("repo") == nuevas[k]["repo"]:
                del nuevas[k]
                _last_seen[k] = ahora
        if nuevas:
            items = [e for e in actuales if _clave(e["pc"], e["cwd"]) not in nuevas]
            items.extend({**e, "last": marca} for e in nuevas.values())
            _write(_prune(items))
    for k in nuevas:
        _last_seen[k] = ahora
    return len(nuevas)


def listar(pc: str | None = None) -> list[dict]:
    """Las carpetas abiertas estos dias, la mas nueva primero (`{cwd, repo, pc, last}`); con `pc`,
    solo las de esa PC. Poda en memoria lo viejo."""
    with _lock:
        items = _prune(_read())
    return [e for e in items if pc is None or e["pc"] == pc]


def olvidar_todo() -> None:
    """Para tests: vacia el debounce en memoria."""
    _last_seen.clear()
