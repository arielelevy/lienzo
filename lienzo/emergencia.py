"""Acceso de emergencia: el canal que queda cuando un par no responde por la LAN (decisión 24 de
Ariel, 2026-10-22).

Hay dos, y se usa el que esté: Tailscale (el cliente de Windows, anda en ariel) o Tailchrome (el
helper de la extensión, anda en ar-it33940, donde le quitaron el cliente). Cada PC anuncia los
suyos en la salud (`health.snapshot()["emergencia"]`); cuando un par se cae, la tira de PCs combina
los de esta PC con los últimos que anunció el par y dice qué hacer y dónde.

- `propia()`: `{"tailscale": IP 100.x o None, "tailchrome": bool}` de esta PC, cacheado.
- `canal(local, remoto, nombre)`: `{"canal": "tailscale"|"tailchrome"|None, "url", "texto"}`.
  `url` sólo cuando la acción es en esta PC (la página /tailchrome atiende sólo localhost).
"""

from __future__ import annotations

import threading
import time

import red
import tailchrome_native

CACHE_S = 60.0

_lock = threading.Lock()
_cache: tuple[float, dict | None] = (0.0, None)


def _tailchrome_instalado() -> bool:
    try:
        tailchrome_native.installed_helper()
    except OSError, ValueError, RuntimeError:
        return False
    return True


def propia(ahora: float | None = None) -> dict:
    """Los canales de esta PC. La piden la salud y /peers cada 15 s: se cachea `CACHE_S`."""
    global _cache
    t = time.time() if ahora is None else ahora
    with _lock:
        if _cache[1] is not None and t - _cache[0] < CACHE_S:
            return dict(_cache[1])
    datos = {"tailscale": red.tailscale_propia(), "tailchrome": _tailchrome_instalado()}
    with _lock:
        _cache = (t, datos)
    return dict(datos)


def _limpio(canales) -> dict:
    """Lo que anunció un par puede venir de otra versión o roto: sólo se cree lo que tiene forma."""
    if not isinstance(canales, dict):
        return {"tailscale": None, "tailchrome": False}
    ts = canales.get("tailscale")
    return {
        "tailscale": ts if isinstance(ts, str) and red.es_tailscale(ts) else None,
        "tailchrome": canales.get("tailchrome") is True,
    }


def canal(local: dict, remoto: dict | None, nombre: str) -> dict:
    """El canal de emergencia hacia `nombre`. Con Tailscale en las dos, directo; con el cliente de
    un lado y Tailchrome del otro, el puente se abre en la PC de la extensión hacia la IP 100.x de la
    otra. Dos PCs sólo con extensión no están cubiertas (README, «acceso de emergencia»)."""
    yo = _limpio(local)
    el = _limpio(remoto)
    # un par sin canales anunciados (salud de otra versión, o nunca la mandó) se trata como
    # desconocido: se ofrece el canal de esta PC, que es el que hay que tener de un lado
    conocido = bool(el["tailscale"] or el["tailchrome"])
    if yo["tailscale"] and (el["tailscale"] or not conocido):
        donde = f" ({el['tailscale']})" if el["tailscale"] else ""
        return {
            "canal": "tailscale",
            "url": None,
            "texto": f"Tailscale: prendelo en {nombre}{donde}; esta PC ya está en la tailnet ({yo['tailscale']})",
        }
    if yo["tailscale"] and el["tailchrome"]:
        return {
            "canal": "tailchrome",
            "url": None,
            "texto": f"Tailchrome: en {nombre} abrí /tailchrome en su tablero y conectá el puente a {yo['tailscale']}",
        }
    if yo["tailchrome"] and (el["tailscale"] or not conocido):
        hacia = f"{nombre} ({el['tailscale']})" if el["tailscale"] else nombre
        return {
            "canal": "tailchrome",
            "url": "/tailchrome",
            "texto": f"Tailchrome: abrí el puente en esta PC hacia {hacia}",
        }
    if el["tailscale"]:
        return {
            "canal": None,
            "url": None,
            "texto": f"sin canal de emergencia acá: {nombre} tiene Tailscale; instalalo o activá Tailchrome en esta PC",
        }
    return {"canal": None, "url": None, "texto": "sin canal de emergencia: instalá Tailscale en alguna de las dos PCs"}
