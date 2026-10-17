"""In-memory Claude connections. Credentials remain in the bridge and its own child."""

import hashlib
import json
import os
import re
import threading
import time
import uuid

import agentes
import procinfo
import procs
from claude_pipe import MAX_TEXT, ClaudePipeBridge
from claude_pipe_bootstrap import ClaudePipeBootstrap

CONFIRM_LIMIT_S = 600
HEARTBEAT_CLOSE_GRACE_S = 30
REPEAT_AFTER_S = 60
TAIL_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 128
MAX_RECORDS = 10000
MAX_SESSION_RECORDS = 1000
_lock = threading.RLock()
_lifecycle = threading.RLock()
_entries = {}
_records = {}
_latest = {}


def _owner(card):
    if card.get("agent") != "claude" or not card.get("alive") or not card.get("pid"):
        return None
    external = card.get("external") or {}
    if external and external.get("kind") != "claude-desktop":
        return None
    pid = card["pid"]
    start = procs.creation_filetime(pid)
    if start is None:
        return None
    record = agentes.claude_registro(pid, start) if procinfo.alive(pid) else None
    if record and record.get("sessionId") == card.get("session_id"):
        return pid, start
    return None


def _compatibility(owner):
    record = agentes.claude_registro(*owner)
    if not record or type(record.get("peerProtocol")) is not int or record["peerProtocol"] != 1:
        return "protocolo Claude desconocido o incompatible: se requiere peerProtocol entero 1"
    version = record.get("version")
    if not isinstance(version, str) or len(version) > 32 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        return "versión Claude desconocida o inválida"
    if tuple(map(int, version.split("."))) < (2, 1, 234):
        return "versión Claude anterior al mínimo Windows 2.1.234"
    return None


def _public(record):
    return {key: record.get(key) for key in ("estado", "motivo", "referencia", "envio_id", "transporte", "at")}


def _connection_expired(entry):
    bridge = entry["bridge"]
    if bridge.registered.is_set():
        return time.monotonic() - bridge.last_poll >= HEARTBEAT_CLOSE_GRACE_S
    return time.time() >= entry["expires_at"]


def _bootstrap_failed(entry):
    return (
        entry["bootstrap"].closed
        and entry["bootstrap"].result != "transferred"
        and not entry["bridge"].registered.is_set()
    )


def _prepare(session_id):
    sid = str(uuid.UUID(session_id))
    with _lifecycle, _lock:
        previous = _entries.get(sid)
        if previous:
            if previous.get("closing"):
                raise ValueError("el enlace Claude se está cerrando")
            return previous
        if len(_entries) >= MAX_ENTRIES:
            raise ValueError("límite de enlaces Claude alcanzado; cerrá los enlaces sin uso")
        bridge = ClaudePipeBridge(sid)
        try:
            bootstrap = ClaudePipeBootstrap(bridge, timeout=120)
        except Exception:
            bridge.close()
            raise
        entry = {"bridge": bridge, "bootstrap": bootstrap, "expires_at": time.time() + 120, "owner": None}
        _entries[sid] = entry
        return entry


def prepare_launch(session_id):
    """Only public hook settings: safe to put in this launch's command file."""
    entry = _prepare(session_id)
    return {
        "session_id": str(uuid.UUID(session_id)),
        "hook_settings": entry["bootstrap"].hook_settings(),
        "expires_at": entry["expires_at"],
    }


def register(card, *, reconnect=False):
    owner = _owner(card)
    if owner is None:
        raise ValueError("no se pudo verificar el proceso de esta sesión Claude")
    reason = _compatibility(owner)
    if reason:
        raise ValueError(reason)
    with _lifecycle:
        if reconnect:
            with _lock:
                previous = _entries.get(card["session_id"])
                if previous and previous["owner"] not in (None, owner):
                    raise ValueError("el proceso de la sesión cambió: cerrá el enlace anterior")
            if previous and not previous["bridge"].available:
                _close(card["session_id"], expected=previous)
        entry = _prepare(card["session_id"])
        with _lock:
            if _owner(card) != owner:
                raise ValueError("el proceso Claude cambió durante el registro")
            if entry["owner"] is not None and entry["owner"] != owner:
                raise ValueError("el proceso de la sesión cambió: cerrá el enlace anterior")
            if _connection_expired(entry) or _bootstrap_failed(entry):
                raise ValueError(
                    "bootstrap Claude finalizado sin conexión vigente; cerrá el enlace y registrá de nuevo"
                )
            entry["owner"] = owner
        return {
            "session_id": card["session_id"],
            "command": entry["bootstrap"].command(powershell=True),
            "expires_at": entry["expires_at"],
            "connected": entry["bridge"].available,
        }


def availability(card):
    if card.get("stopped_by") or card.get("pending_id"):
        return {
            "puede": False,
            "motivo": "sesión detenida o con un permiso/pregunta pendiente",
            "transporte": "claude_pipe",
        }
    with _lock:
        entry = _entries.get(card.get("session_id"))
    reason = "falta conectar el adaptador de esta sesión Claude"
    if entry:
        owner = _owner(card)
        incompatible = _compatibility(owner) if owner else None
        if owner is None or (entry["owner"] is not None and entry["owner"] != owner):
            reason = "el proceso Claude del enlace ya no es el vigente"
        elif incompatible:
            reason = incompatible
        elif entry.get("closing"):
            reason = "el enlace Claude se está cerrando"
        elif entry["bridge"].available:
            with _lock:
                if (
                    _entries.get(card.get("session_id")) is not entry
                    or entry.get("closing")
                    or (entry["owner"] is not None and entry["owner"] != owner)
                ):
                    return {"puede": False, "motivo": "el enlace Claude se cerró", "transporte": "claude_pipe"}
                entry["owner"] = owner
            return {"puede": True, "motivo": None, "transporte": "claude_pipe"}
        else:
            reason = "el adaptador Claude no está conectado o dejó de responder"
    return {"puede": False, "motivo": reason, "transporte": "claude_pipe"}


def _delivered(record):
    try:
        with open(record["transcript"], "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            offset = max(0, size - TAIL_BYTES)
            stream.seek(offset)
            lines = stream.read(TAIL_BYTES).decode("utf-8", errors="replace").splitlines()
            if offset:
                lines = lines[1:]  # Never parse a fragment of a truncated first record.
    except (OSError, TypeError) as error:
        return False, f"no se pudo comprobar el transcript ({type(error).__name__})"
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue  # The live file can end in a partial JSON line.
        if not isinstance(row, dict):
            continue
        origin = row.get("origin") or {}
        if (
            row.get("type") == "user"
            and row.get("sessionId") == record["session_id"]
            and isinstance(origin, dict)
            and origin.get("kind") == "peer"
            and origin.get("msg_id") == record["envio_id"]
        ):
            return True, None
    return False, None


def confirm(envio_id):
    with _lock:
        original = _records.get(envio_id)
        if original is None:
            return _rejected("envío Claude no registrado", envio_id, estado="desconocido")
        record = dict(original)
    if record["estado"] in ("entregado", "rechazado"):
        return _public(record)
    delivered, error = _delivered(record)
    with _lock:
        if original["estado"] == "entregado":
            return _public(original)
        if delivered:
            original.update(estado="entregado", motivo=None)
        elif time.time() - record["at"] >= CONFIRM_LIMIT_S:
            original.update(estado="sin_confirmacion", motivo="no se confirmó la entrega a Claude; no se reintenta")
        elif error:
            original["motivo"] = error
        return _public(original)


def send(card, text, contexto=None):
    plan = availability(card)
    if not plan["puede"]:
        return _rejected(plan["motivo"])
    try:
        encoded = text.encode("utf-8") if isinstance(text, str) else b""
    except UnicodeEncodeError:
        return _rejected("texto Claude no válido en UTF-8")
    if not encoded or len(encoded) > MAX_TEXT:
        return _rejected("texto vacío o mayor al límite UTF-8 de Claude")
    sid = card["session_id"]
    digest = hashlib.sha256(encoded).hexdigest()
    explicit = (contexto or {}).get("envio_id")
    with _lock:
        key = str(uuid.UUID(explicit)) if explicit else _latest.get((sid, digest))
        prior = _records.get(key)
        if prior:
            if prior["session_id"] != sid or prior["digest"] != digest:
                raise ValueError("envio_id ya usado para otro destino o texto")
            if explicit or prior["estado"] != "entregado" or time.time() - prior["at"] < REPEAT_AFTER_S:
                return _public(prior)
        key = str(uuid.uuid4()) if not explicit else key
        entry = _entries.get(sid)
        if entry is None:
            return _rejected("el enlace Claude se cerró antes del envío")
        # Revalidate the exact entry after the initial capability check, before reserving.
        owner = _owner(card)
        if owner is None or entry["owner"] != owner or entry.get("closing") or not entry["bridge"].available:
            return _rejected("el proceso o enlace Claude cambió antes del envío")
        reason = _compatibility(owner)
        if reason:
            return _rejected(reason)
        if (
            len(_records) >= MAX_RECORDS
            or sum(r["session_id"] == sid for r in _records.values()) >= MAX_SESSION_RECORDS
        ):
            return _rejected("límite de reservas Claude alcanzado; no se descartan UUID ni se reintenta")
        record = {
            "envio_id": key,
            "session_id": sid,
            "digest": digest,
            "transcript": card.get("transcript_path"),
            "estado": "pendiente",
            "motivo": "esperando escritura y confirmación de Claude",
            "referencia": key,
            "transporte": "claude_pipe",
            "at": time.time(),
        }
        _records[key] = record
        _latest[sid, digest] = key
    try:
        result = entry["bridge"].send(text, key, timeout=5)
        status = result.get("status")
    except OSError, RuntimeError, TimeoutError, ValueError:
        status = "unknown"  # A failure after reservation never authorizes a second write.
    with _lock:
        if record["estado"] != "entregado":
            record["estado"] = "encolado" if status == "pipe_written" else "sin_confirmacion"
            record["motivo"] = (
                "escrito al pipe; falta comprobar entrega en el transcript"
                if status == "pipe_written"
                else "resultado incierto del adaptador Claude; no se reintenta"
            )
    return confirm(key)


def _rejected(reason, envio_id=None, estado="rechazado"):
    return {
        "estado": estado,
        "motivo": reason,
        "envio_id": envio_id,
        "referencia": envio_id,
        "transporte": "claude_pipe",
        "at": time.time(),
    }


def _close(session_id, expected=None):
    with _lifecycle:
        with _lock:
            entry = _entries.get(session_id)
            if entry is None or (expected is not None and entry is not expected):
                return
            entry["closing"] = True
        # Keep the entry reserved until both writers/listeners are closed.
        try:
            entry["bootstrap"].close()
        finally:
            entry["bridge"].close()
        with _lock:
            _entries.pop(session_id)


def close(session_id):
    _close(session_id)


def reap(cards):
    """Call outside the sessions lock, with a snapshot of locally owned cards."""
    current = {card["session_id"]: card for card in cards}
    with _lock:
        entries = list(_entries.items())
    for sid, entry in entries:
        card = current.get(sid)
        gone = card is not None and _owner(card) != entry["owner"] and entry["owner"] is not None
        if (
            _connection_expired(entry)
            or gone
            or _bootstrap_failed(entry)
            or (card is None and entry["owner"] is not None)
        ):
            _close(sid, expected=entry)


def close_all():
    with _lock:
        entries = list(_entries.items())
    errors = []
    for sid, entry in entries:
        try:
            _close(sid, expected=entry)
        except (OSError, RuntimeError, TimeoutError) as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("no se pudieron cerrar todos los enlaces Claude", errors)
