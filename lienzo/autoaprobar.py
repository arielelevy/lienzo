"""Auto-aprobar TODO (peligroso, a pedido de Ariel, 2026-10-04): con `auto_aprobar` prendido en
~/.lienzo/config.json, cada permiso que un agente de ESTA PC pida se aprueba solo, sin mirarlo.

Patron de proveedores, como las fuentes de temperatura de health.py: cada forma en que un agente pide
permiso es un `ProveedorPermisos` con `abiertos()` (que hay para contestar) y `aprobar()` (como se
contesta). Sumar un agente nuevo es sumar un proveedor, no tocar el bucle.

- PendientesDeHook: Claude Code, Codex y Pi piden por el hook PermissionRequest; el pedido queda en
  `state.pending` y se contesta con answer_pending.
- DialogoDeCoda: coda no tiene ese hook; su cartel «Approval Required» se ve en la terminal y se
  contesta con Enter (answer_coda_ask).

Lo que NO aprueba: una pregunta con opciones (AskUserQuestion), que pide elegir, no permitir. Cada
aprobacion queda en el log con «AUTO-APROBADO», para poder ver despues que paso.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import sessions as ses
import state

CLAVE = "auto_aprobar"
CADA_S = 2.0
REINTENTO_S = 20.0  # el mismo pedido no se vuelve a contestar antes de esto (Enter que todavia no hizo efecto)


@dataclass(frozen=True)
class Pedido:
    id: str  # unico por pedido: el request_id del hook, o sesion+momento del cartel de coda
    session_id: str
    agente: str
    que: str  # herramienta y detalle, para el log


class ProveedorPermisos(ABC):
    nombre: str

    @abstractmethod
    def abiertos(self) -> list[Pedido]:
        """Los permisos que esperan respuesta ahora."""

    @abstractmethod
    def aprobar(self, p: Pedido) -> tuple[int, dict]:
        """Contesta «permitir»; devuelve (code, respuesta) como las rutas del server."""


class PendientesDeHook(ProveedorPermisos):
    nombre = "hook"

    def abiertos(self) -> list[Pedido]:
        with state.lock:
            items = list(state.pending.values())
        out = []
        for d in items:
            if ses.is_question(d):
                continue  # pide elegir una opcion, no permitir
            inp = d.get("tool_input") or {}
            detalle = inp.get("command") or inp.get("file_path") or inp.get("url") or ""
            sesion = state.sessions.get(d.get("session_id") or "") or {}
            out.append(
                Pedido(
                    d["request_id"],
                    d.get("session_id") or "",
                    sesion.get("agent") or "?",
                    f"{d.get('tool_name')} {str(detalle)[:160]}",
                )
            )
        return out

    def aprobar(self, p: Pedido) -> tuple[int, dict]:
        return ses.answer_pending(p.id, "allow", "auto-aprobado desde el lienzo")


class DialogoDeCoda(ProveedorPermisos):
    nombre = "coda"

    def abiertos(self) -> list[Pedido]:
        with state.lock:
            tarjetas = [dict(s) for s in state.sessions.values()]
        out = []
        for s in tarjetas:
            n = s.get("needs") or {}
            if s.get("agent") != "coda" or s.get("state") != "te_necesita" or n.get("kind") != "permission":
                continue
            if not n.get("coda_at") or n.get("where") != "terminal":
                continue
            out.append(
                Pedido(
                    f"{s['session_id']}@{n['coda_at']}",
                    s["session_id"],
                    "coda",
                    f"{n.get('tool')} {s.get('last_cmd') or ''}",
                )
            )
        return out

    def aprobar(self, p: Pedido) -> tuple[int, dict]:
        s = state.sessions.get(p.session_id)
        if s is None:
            return 404, {"error": "la sesion ya no esta"}
        return ses.answer_coda_ask(s, "allow")


PROVEEDORES: list[ProveedorPermisos] = [PendientesDeHook(), DialogoDeCoda()]
_intentados: dict[str, float] = {}


def prendido() -> bool:
    return bool(state.load_config().get(CLAVE))


def ronda(ahora: float | None = None) -> list[tuple[Pedido, int]]:
    """Una pasada: si esta prendido, aprueba todo lo abierto de todos los proveedores. Devuelve lo
    que contesto. Un proveedor que falla no corta a los demas."""
    if not prendido():
        return []
    ahora = time.monotonic() if ahora is None else ahora
    for k in [k for k, t in _intentados.items() if ahora - t > 10 * REINTENTO_S]:
        del _intentados[k]
    hechos = []
    for prov in PROVEEDORES:
        try:
            pedidos = prov.abiertos()
        except Exception as e:
            state.log(f"auto-aprobar, proveedor {prov.nombre}: {type(e).__name__}: {e}")
            continue
        for p in pedidos:
            if ahora - _intentados.get(p.id, -1e9) < REINTENTO_S:
                continue
            _intentados[p.id] = ahora
            try:
                code, _ = prov.aprobar(p)
            except Exception as e:
                state.log(f"auto-aprobar {p.session_id[:8]}: {type(e).__name__}: {e}")
                continue
            state.log(f"AUTO-APROBADO ({prov.nombre}) {p.agente} {p.session_id[:8]}: {p.que} -> {code}")
            hechos.append((p, code))
    return hechos


def loop() -> None:
    while True:
        try:
            ronda()
        except Exception as e:
            state.log(f"auto-aprobar: {type(e).__name__}: {e}")
        time.sleep(CADA_S)


def arrancar() -> threading.Thread:
    t = threading.Thread(target=loop, name="autoaprobar", daemon=True)
    t.start()
    return t
