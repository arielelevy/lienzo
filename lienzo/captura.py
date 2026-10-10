"""Captura automatica del conocimiento por proyecto (anexo A de docs/propuesta-memoria-2026-10-08/v5.md,
pedido de Ariel del 2026-10-09): todo lo que pasa por el lienzo queda en la memoria del proyecto de su
carpeta, sin que nadie registre el proyecto, abra una ronda ni entregue un informe.

- La primera vez que el lienzo ve una tarjeta con carpeta (hook, barrido, lanzamiento, envio) el
  proyecto de esa carpeta se crea solo (`conocimiento.proyecto_de_carpeta`) y la sesion queda como
  nodo `sesion`; desde ahi los adaptadores de cierre, permisos y errores la ven.
- Cada pedido, respuesta final, envio entre sesiones y disparo de regla queda como captura `observado`
  con sesion, agente, modelo, pc y hora. Una respuesta final con bloque ```conocimiento``` es ademas un
  informe, que se incorpora igual que una entrega (`conocimiento.informe_capturado`).
- Nada de esto llega a `vigente`: las capturas no tienen transiciones y los nodos del bloque nacen en
  el estado inicial de su tipo.

Los llamadores (sessions, rules, server) tienen el lock de las tarjetas tomado: aca solo se encola una
copia y un hilo propio escribe en SQLite. La cola existe solo con `arrancar()` (lo llama el server);
sin ella `encolar` no hace nada, asi que las pruebas de otros modulos no escriben bases. Las pruebas de
este modulo llaman `procesar` directo.

Lo que no se guarda: adjuntos (solo su nombre), secretos con forma conocida (se tapan antes de
encolar), carpetas temporales del sistema (pruebas y lanzamientos de prueba) y pedidos que tecleo el
propio lienzo (ya quedaron como envio, con el texto entero y sin el envoltorio del adjunto).
"""

from __future__ import annotations

import hashlib
import os
import queue
import re
import tempfile
import threading
import time
import traceback

import conocimiento as k
import identity
import state

COLA_MAX = 5000
TAPADO = "[secreto tapado por el lienzo]"

# formas conocidas de secretos: se tapan antes de encolar. Las de clave=valor conservan la clave
_SECRETOS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"(?i)(?<=\bbearer )[A-Za-z0-9._~+/=-]{20,}"),
)
_CLAVE_VALOR = re.compile(
    r"(?i)\b(password|passwd|pwd|contrase(?:ñ|n)a|secret|client_secret|api[_-]?key|access[_-]?token|"
    r"accountkey|sharedaccesskey)(\s*[:=]\s*)(\"[^\"\s]{6,}\"|'[^'\s]{6,}'|[^\s;,'\"]{6,})"
)

_cola: queue.Queue | None = None
_lock = threading.Lock()
_vistas: set[str] = set()  # session_id ya registrados en este proceso (bajo _lock)
_proyectos: dict[tuple[str, str], str | None] = {}  # (pc, cwd normalizado) -> proyecto (bajo _lock)
_ultimo_turno: dict[str, str] = {}  # session_id -> ultimo turno de pedido visto (bajo _lock)
_llena_avisada = False


def tapar(texto: str) -> tuple[str, bool]:
    """El texto con los secretos de forma conocida tapados, y si tapo algo."""
    if not texto:
        return texto, False
    out = texto
    for r in _SECRETOS:
        out = r.sub(TAPADO, out)
    out = _CLAVE_VALOR.sub(lambda m: f"{m.group(1)}{m.group(2)}{TAPADO}", out)
    return out, out != texto


def temporal(cwd: str | None) -> bool:
    """La carpeta esta bajo la temporal del sistema: pruebas y lanzamientos de prueba, no proyectos."""
    if not cwd:
        return False
    try:
        tmp = os.path.realpath(tempfile.gettempdir())
        return os.path.commonpath([os.path.realpath(cwd), tmp]) == tmp
    except ValueError, OSError:
        return False


def tarjeta_de(s: dict) -> dict:
    """Lo que la captura necesita de una tarjeta, copiado (el hilo no toca la tarjeta viva)."""
    return {
        "session_id": s.get("session_id"),
        "agent": s.get("agent"),
        "model": s.get("model"),
        "pc": s.get("pc") or identity.pc_id(),
        "cwd": s.get("cwd"),
    }


# --- cola -------------------------------------------------------------------------------------


def arrancar() -> None:
    """La cola y su hilo. Solo el server la arranca; dos llamadas no abren dos hilos."""
    global _cola
    with _lock:
        if _cola is not None:
            return
        _cola = queue.Queue(maxsize=COLA_MAX)
    threading.Thread(target=_trabajar, name="captura", daemon=True).start()


def encolar(ev: dict) -> None:
    global _llena_avisada
    c = _cola
    if c is None:
        return
    try:
        c.put_nowait(ev)
    except queue.Full:
        if not _llena_avisada:
            _llena_avisada = True
            state.log(f"captura: la cola llego a {COLA_MAX}; se pierden capturas hasta que baje")


def _trabajar() -> None:
    global _llena_avisada
    while True:
        ev = _cola.get()
        try:
            procesar(ev)
        except Exception:
            state.log(
                f"captura: {ev.get('tipo')} de {str(ev.get('tarjeta', {}).get('session_id'))[:8]}:\n{traceback.format_exc()}"
            )
        finally:
            if _cola.qsize() < COLA_MAX // 2:
                _llena_avisada = False


def esperar(timeout: float = 5.0) -> bool:
    """Hasta que la cola se vacie (para pruebas y para medir). True si se vacio."""
    fin = time.monotonic() + timeout
    while _cola is not None and not _cola.empty() and time.monotonic() < fin:
        time.sleep(0.02)
    return _cola is None or _cola.empty()


_contexto = threading.local()


class origen:
    """`with captura.origen(de=..., kind=..., clase="regla", rule_id=...):` alrededor de un
    `send_to_session`: el envio que se capture adentro lleva ese origen. Por hilo, asi la firma de
    send_to_session no cambia."""

    def __init__(self, **meta):
        self.meta = {kk: v for kk, v in meta.items() if v is not None}

    def __enter__(self):
        self.antes = getattr(_contexto, "meta", None)
        _contexto.meta = self.meta
        return self

    def __exit__(self, *exc):
        _contexto.meta = self.antes
        return False


def origen_actual() -> dict:
    return dict(getattr(_contexto, "meta", None) or {})


# --- lo que llaman sessions, rules y server (con el lock de tarjetas tomado: solo encolan) --------


def vista(s: dict) -> None:
    """La tarjeta se toco (touch): la primera vez que tiene carpeta, su proyecto y su sesion."""
    sid = s.get("session_id")
    if not sid or not s.get("cwd"):
        return
    with _lock:
        if sid in _vistas:
            return
        _vistas.add(sid)
    encolar({"tipo": "vista", "tarjeta": tarjeta_de(s)})


def _evento(tipo: str, s: dict, texto: str, clave: str, origen: dict) -> None:
    if not isinstance(texto, str) or not texto.strip():
        return
    limpio, tapado = tapar(texto)
    encolar(
        {
            "tipo": tipo,
            "tarjeta": tarjeta_de(s),
            "texto": limpio,
            "redactado": tapado,
            "clave": clave,
            "origen": origen,
        }
    )


def _h(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:16]


def pedido(s: dict, texto: str, via: str | None, turno: str | None = None) -> None:
    """Un pedido que entro a la sesion: tipeado en la terminal, mensaje de otra sesion por el canal
    nativo, o leido de la transcripcion (agentes sin hooks). Lo que tecleo el lienzo (`via ==
    'lienzo'`) no: ya quedo como envio con el texto entero."""
    sid = s.get("session_id") or ""
    if turno:
        # la transcripcion se relee en cada refresco y trae el mismo turno: una vez por turno
        with _lock:
            if _ultimo_turno.get(sid) == turno:
                return
            _ultimo_turno[sid] = turno
    if via == "lienzo":
        return
    clave = f"pedido:{sid}:{turno}" if turno else f"pedido:{sid}:{_h(texto)}:{s.get('last_event_ts') or ''}"
    _evento("pedido", s, texto, clave, {"via": via})


def respuesta(s: dict) -> None:
    """La respuesta final del turno que acaba de cerrar (rules.fire_on_stop, fuera del lock)."""
    texto = s.get("last_reply") or ""
    sid = s.get("session_id") or ""
    clave = f"respuesta:{sid}:{s.get('state_since') or ''}:{_h(texto)}"
    origen = {"error": s["last_error"]} if s.get("last_error") else {}
    _evento("respuesta", s, texto, clave, origen)


def envio(dst: dict, texto: str, *, de: str | None = None, clase: str = "envio", **meta) -> None:
    """Lo que el lienzo tecleo en la consola de `dst`: un envio del tablero o de otra sesion (`de`), un
    aviso automatico, o el disparo de una regla (`clase='regla'`, con rule_id). Queda en el proyecto
    de la carpeta de `dst`, con el texto entero y los adjuntos solo por nombre."""
    adjuntos = [os.path.basename(a) for a in meta.pop("adjuntos", None) or [] if isinstance(a, str)]
    origen = {"de": de, **{kk: v for kk, v in meta.items() if v is not None}}
    if adjuntos:
        origen["adjuntos"] = adjuntos
    sid = dst.get("session_id") or ""
    clave = f"{clase}:{sid}:{_h(texto)}:{time.time_ns()}"
    _evento(clase, dst, texto, clave, {kk: v for kk, v in origen.items() if v is not None})


# --- el hilo: de un evento a la base del proyecto -----------------------------------------------


def proyecto_de(tarjeta: dict) -> str | None:
    """El proyecto de la carpeta de la tarjeta (creado si hace falta), o None (sin carpeta o temporal)."""
    cwd = tarjeta.get("cwd")
    if not cwd or temporal(cwd):
        return None
    pc = tarjeta.get("pc") or identity.pc_id()
    clave = (pc, k.norm_cwd(cwd))
    with _lock:
        if clave in _proyectos:
            return _proyectos[clave]
    url = identity.origin_url(cwd)
    remote = identity._normalize_remote(url) if url else None
    pid = k.proyecto_de_carpeta(cwd, pc, remote)
    with _lock:
        _proyectos[clave] = pid
    return pid


def procesar(ev: dict) -> dict | None:
    """Escribe un evento de la cola. Devuelve la captura (o la sesion, para `vista`), o None si no
    correspondia (sin proyecto, repetida)."""
    tarjeta = ev.get("tarjeta") or {}
    pid = proyecto_de(tarjeta)
    if pid is None:
        return None
    if ev["tipo"] == "vista":
        return k.registrar_sesion(pid, tarjeta)
    cap = k.capturar(
        pid,
        ev["tipo"],
        ev.get("texto") or "",
        tarjeta,
        origen=ev.get("origen"),
        clave=ev.get("clave"),
        redactado=bool(ev.get("redactado")),
    )
    if cap is not None and ev["tipo"] == "respuesta" and k.extraer_bloque(ev.get("texto") or "") is not None:
        try:
            with k._abrir(pid) as con:
                ronda = k._ronda_de_sesion(con, pid, tarjeta["session_id"])
            inf = k.informe_capturado(
                pid, tarjeta["session_id"], ev["texto"].strip(), ronda=ronda, origen={"captura": cap["id"]}
            )
            if inf is not None:
                cap["informe"] = inf["id"]
        except k.Rechazo as e:
            state.log(f"captura: informe de {tarjeta['session_id'][:8]} no entro: {e}")
    return cap


def olvidar() -> None:
    """Para las pruebas: sin sesiones vistas ni proyectos resueltos."""
    with _lock:
        _vistas.clear()
        _proyectos.clear()
        _ultimo_turno.clear()
