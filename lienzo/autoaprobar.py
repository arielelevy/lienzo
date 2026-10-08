"""Auto-aprobar TODO (peligroso, a pedido de Ariel, 2026-10-04): con `auto_aprobar` prendido en
~/.lienzo/config.json, cada permiso que un agente de ESTA PC pida se aprueba solo, sin mirarlo.

Patron de proveedores, como las fuentes de temperatura de health.py: cada forma en que un agente pide
permiso es un `ProveedorPermisos` con `abiertos()` (que hay para contestar) y `aprobar()` (como se
contesta). Sumar un agente nuevo es sumar un proveedor, no tocar el bucle.

- PendientesDeHook: Claude Code, Codex y Pi piden por el hook PermissionRequest; el pedido queda en
  `state.pending` y se contesta con answer_pending.
- DialogoDeCoda: coda no tiene ese hook; su cartel «Approval Required» se ve en la terminal y se
  contesta con Enter (answer_coda_ask).
- DialogoDePermiso (2026-10-08): el permiso que la TUI dibuja como dialogo de opciones, sin hook
  («Would you like to run the following command?» de Codex, «Do you want to proceed?» de Claude,
  con «Yes, proceed (y)» y «No, ...»): el barrido de pantalla lo deja en `dialog` de la tarjeta y se
  contesta eligiendo la primera opcion «Yes» (answer_dialog). Medido: la tarjeta de Teorema (Codex)
  quedaba en «Espera que elijas en la terminal» con el auto-aprobar prendido.

Lo que NO aprueba: una pregunta con opciones (AskUserQuestion, o cualquier dialogo que no sea un
permiso: «Switch model?», la confianza en una carpeta), que pide elegir, no permitir. Cada
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
    # True si un «permitir» puede no hacer efecto y conviene repetirlo (un Enter tecleado en una
    # terminal); False si la respuesta es definitiva (el hook la lee de un archivo): se contesta una vez
    reintenta: bool = False

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
    reintenta = True

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


# como arranca la pregunta de un permiso en la TUI (Codex y Claude Code); una pregunta de verdad
# («Which library...?», «Switch model?», «Do you want to use this API key?») no empieza asi, y la
# confianza en una carpeta tampoco. Sin comodin «do you want to»: no todo lo que empieza asi es un permiso
PREGUNTAS_DE_PERMISO = (
    "would you like to run",
    "would you like to proceed",
    "do you want to proceed",
    "do you want to make",
    "do you want to create",
    "do you want to run",
    "do you want to read",
    "do you want to write",
    "do you want to edit",
    "do you want to fetch",
    "do you want to allow",
)


def opcion_de_permiso(dialog: dict | None) -> int | None:
    """La opcion que permite, si `dialog` es un permiso: la primera «Yes» o «Allow» que no sea
    «don't ask again» ni «Always» (eso ademas lo recordaria). Es un permiso si la pregunta empieza
    como una (PREGUNTAS_DE_PERMISO), dice «requires approval» (Kiro), las opciones son Allow/Deny o
    alguna ofrece «don't ask again»."""
    if not dialog:
        return None
    q = (dialog.get("question") or "").strip().lower()
    # la opcion «No, ...» puede no entrar en la pantalla (medido el 2026-10-08 en Teorema: el
    # parser vio solo «Yes, proceed (y)» y «Yes, and don't ask again ...»): no se la exige
    ops = [(o.get("n"), (o.get("text") or "").strip().lower()) for o in dialog.get("options") or []]
    allow_deny = any(t.startswith("allow") for _, t in ops) and any(t.startswith("deny") for _, t in ops)
    # «Yes, and don't ask again for ...» solo lo ofrece un permiso: alcanza aunque la pregunta no se
    # haya leido bien (un comando largo la deja lejos de las opciones, medido el 2026-10-08)
    ask_again = any("ask again" in t for _, t in ops)
    if not (q.startswith(PREGUNTAS_DE_PERMISO) or "requires approval" in q or allow_deny or ask_again):
        return None
    return next(
        (n for n, t in ops if t.startswith(("yes", "allow")) and "ask again" not in t and not t.startswith("always")),
        None,
    )


class DialogoDePermiso(ProveedorPermisos):
    nombre = "dialogo"
    reintenta = True  # se teclea en la consola: puede no hacer efecto

    def abiertos(self) -> list[Pedido]:
        with state.lock:
            tarjetas = [dict(s) for s in state.sessions.values()]
        out = []
        for s in tarjetas:
            d = s.get("dialog")
            n = s.get("needs") or {}
            if s.get("state") != "te_necesita" or n.get("kind") != "dialog" or s.get("pending_id"):
                continue
            if opcion_de_permiso(d) is None:
                continue
            out.append(
                Pedido(
                    # sin el detalle: la pantalla lo redibuja (otra linea envuelta, el spinner) y con el
                    # detalle en el id el mismo dialogo abierto se volvia a contestar a los 2 s
                    f"{s['session_id']}@{n.get('since') or ''}@{d.get('question')}",
                    s["session_id"],
                    s.get("agent") or "?",
                    f"{d.get('question')} {str(d.get('detail') or '')[:160]}",
                )
            )
        return out

    def aprobar(self, p: Pedido) -> tuple[int, dict]:
        s = state.sessions.get(p.session_id)
        if s is None:
            return 404, {"error": "la sesion ya no esta"}
        n = opcion_de_permiso(s.get("dialog"))
        if n is None:
            return 409, {"error": "el dialogo ya no es un permiso"}
        return ses.answer_dialog(s, n)


PROVEEDORES: list[ProveedorPermisos] = [PendientesDeHook(), DialogoDeCoda(), DialogoDePermiso()]
# pedido -> (cuando se intento, si la respuesta fue definitiva). Definitiva = 2xx o 4xx: se contesto,
# o el pedido ya no esta (404/409/410: contestado en otro lado o vencido). Un 5xx o una excepcion
# (disco lleno al escribir la respuesta) NO lo es: antes se marcaba antes de contestar, y un error
# de disco dejaba el pendiente de hook sin aprobar para siempre (plan de refactor 1.14, E16)
_intentados: dict[str, tuple[float, bool]] = {}


def prendido() -> bool:
    return bool(state.load_config().get(CLAVE))


def ronda(ahora: float | None = None) -> list[tuple[Pedido, int]]:
    """Una pasada: si esta prendido, aprueba todo lo abierto de todos los proveedores. Devuelve lo
    que contesto. Un proveedor que falla no corta a los demas."""
    if not prendido():
        return []
    ahora = time.monotonic() if ahora is None else ahora
    for k in [k for k, (t, _) in _intentados.items() if ahora - t > 3600]:
        del _intentados[k]
    hechos = []
    for prov in PROVEEDORES:
        try:
            pedidos = prov.abiertos()
        except Exception as e:
            state.log(f"auto-aprobar, proveedor {prov.nombre}: {type(e).__name__}: {e}")
            continue
        for p in pedidos:
            previo = _intentados.get(p.id)
            if previo is not None:
                cuando, definitivo = previo
                if ahora - cuando < REINTENTO_S:
                    continue  # un fallo se reintenta con espera, no cada 2 s
                if definitivo and not prov.reintenta:
                    # medido el 2026-10-04: un pendiente de hook ya contestado seguia en la lista (su
                    # sesion ya no estaba) y se aprobaba cada 20 s; uno de hook se contesta una vez
                    continue
            try:
                code, _ = prov.aprobar(p)
            except Exception as e:
                _intentados[p.id] = (ahora, False)
                state.log(f"auto-aprobar {p.session_id[:8]}: {type(e).__name__}: {e}; se reintenta")
                continue
            _intentados[p.id] = (ahora, code < 500)
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
