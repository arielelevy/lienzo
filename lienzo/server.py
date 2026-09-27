#!/usr/bin/env python
"""lienzo-server: watcher de ~/.lienzo/events, registro de sesiones, cola de transcripciones,
liveness por PID, SSE y envio por inyeccion. Solo stdlib. Bind 127.0.0.1:7321.

    python server.py [--port 7321] [--no-sweep]
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import ipaddress
import json
import math
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth
import beacon
import federation
import health
import identity
import launch
import mirror
import pairing
import rules as rl
import transcripts
from rules import at_near, connections_of, local_dt, purge_stale_at_rules, rules_loop
from sessions import (
    add_link,
    answer_coda_ask,
    answer_dialog,
    answer_pending,
    clean_attachments,
    consume_events,
    drop_session,
    hand_over,
    interrupt_session,
    liveness_loop,
    load_sessions,
    public_pending,
    read_screen,
    save_attachment,
    scan_pending,
    screen_loop,
    send_to_session,
    set_coordinator,
    set_stopped,
    set_title,
    sweep_once,
    touch,
)
from state import (
    ADJUNTOS,
    ANSWERS,
    DIST,
    DOCS,
    DOCS_IMG,
    EVENTS,
    LIENZO,
    MIME,
    PENDING,
    SESSIONS,
    STALE_SESSION_H,
    UI_CONFIG_KEYS,
    clients,
    is_disconnect,
    links,
    lock,
    log,
    now,
    pending,
    public_config,
    rules,
    sessions,
    set_config_key,
    short,
)

# --- federacion entre PCs (plan-multi-pc-2026-09-26.md, ronda 2) ----------------------------

PEERS_FILE = os.path.join(LIENZO, "peers.json")
_peer_nonces = federation.NonceCache()
# solo el tablero (navegador): recibe ademas de lo local (via `clients`) el espejo de los peers.
# Un peer que se conecta a /peer/events NO se registra aca: solo ve la verdad local de esta PC, ni
# siquiera lo que esta PC espeja de un tercero (evita amplificar en una malla de 3 o 4 PCs).
ui_clients: list = []


CLOUDFLARED = os.path.join(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared", "cloudflared.exe"
)
remote_url: str | None = None
# alta desde el celular con un solo QR: token de 15 min que entrega passphrase + otpauth una vez
enroll: dict | None = None
ENROLL_S = 15 * 60

# Techos del cuerpo del pedido (hallazgo A3 del pentest): se rechaza con 413 antes de leer un byte,
# asi un cuerpo gigante y sin autenticar no puede inflar la memoria. /attach sube archivos e
# imagenes, por eso tiene su propio techo, mas alto.
MAX_BODY = 8 * 1024 * 1024
MAX_ATTACH = 64 * 1024 * 1024

# --- HTTP ------------------------------------------------------------------------------


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
    try:
        max_fires = clamp_fires(d.get("max_fires") or 1)
    except TypeError, ValueError, OverflowError:
        return 400, {"error": "max_fires debe ser un numero"}
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
    log(f"regla nueva {rule['id']}: on_stop -> {rule['to'][:8]}")
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
        log(
            f"regla {clash['id']} ({clash.get('at')} {short(clash.get('text') or '', 40)!r}) reemplazada por una nueva a la misma hora"
        )
    # de at_fields salen every_s, max_fires, skip_busy y repeat=bool(every_s)
    rule = new_rule(d, text, at=at.isoformat(timespec="seconds"), fired=0, enabled=True, created=now(), **extra)
    rules.add(rule, cap=500)
    cada = f" cada {rule['every_s']} s x{rule['max_fires']}" if rule.get("every_s") else ""
    log(f"regla nueva {rule['id']}: at -> {rule['to'][:8]} {rule['at']}{cada}")
    return 200, rule


def create_rule(d: dict) -> tuple[int, dict]:
    """POST /rules: valida lo comun, y si el destino es de otra PC la consulta antes de guardar
    nada (check_remote_destination), y deja el armado en la funcion de la clase que corresponda.
    Devuelve (codigo, cuerpo)."""
    rechazo = check_rule(d)
    if rechazo is not None:
        return rechazo
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
    log(f"regla {r['id']} editada: {r['kind']} -> {r['to'][:8]} {r.get('at') or ''} {short(r.get('text') or '', 60)!r}")
    return 200, r


# --- federacion: snapshot local, firma de peers, enrutado y espejo (plan §3.1-§3.4) -------------


def _local_state() -> dict:
    """sesiones, pendientes, links y reglas de ESTA PC nada mas: lo que sirve /peer/snapshot y lo
    que arranca /peer/events. Nunca lo que esta PC espeja de otra (evitaria una malla de 3+ PCs
    reenviando lo mismo en circulo)."""
    with lock:
        return {
            "sessions": list(sessions.values()),
            "pending": public_pending(),
            "links": links.snapshot(),
            "rules": rules.snapshot(),
        }


def _peer_key(pc_id: str) -> bytes | None:
    k = (federation.get_peer(PEERS_FILE, pc_id) or {}).get("key")
    if not isinstance(k, str):
        return None
    try:
        return bytes.fromhex(k)
    except ValueError:
        return None


def verify_peer_request(headers, method: str, path: str, body: bytes) -> str | None:
    """`pc_id` del peer verificado, o None (headers incompletos, peer desconocido, firma que no
    calza, fuera de ventana o nonce repetido: `federation.verify` ya cubre las cuatro)."""
    claimed = headers.get("X-Lienzo-Peer") or ""
    ts_raw = headers.get("X-Lienzo-Ts")
    nonce = headers.get("X-Lienzo-Nonce")
    sig = headers.get("X-Lienzo-Sig")
    if not claimed or not ts_raw or not nonce or not sig:
        return None
    key = _peer_key(claimed)
    if key is None:
        return None
    try:
        ts = float(ts_raw)
    except ValueError:
        return None
    return claimed if federation.verify(key, method, path, body, ts, nonce, sig, _peer_nonces) else None


def _connect_peer_from_record(peer: dict) -> None:
    """Arranca (o reemplaza) el espejo de un peer recien emparejado, de cualquiera de los dos
    lados (quien ofrecio la frase, u_pairing.accept_, o quien la pego, _pairing.join_): los dos
    devuelven un dict con el mismo schema de peers.json ({pc_id, name, color, ip, port, key hex})."""
    try:
        key_raw = peer.get("key")
        key = bytes.fromhex(key_raw) if isinstance(key_raw, str) else key_raw
        host = peer.get("ip") or peer.get("host")
        port = int(peer["port"])
        pc_id = peer["pc_id"]
        if not key or not host:
            raise ValueError("falta key o ip/host")
    except (KeyError, TypeError, ValueError) as e:
        log(f"peer {peer.get('pc_id')}: registro invalido, no se conecta el espejo ({e})")
        return
    mirror.MIRROR.connect(
        pc_id, {"name": peer.get("name"), "color": peer.get("color")}, host, port, key, identity.pc_id()
    )
    log(f"espejo conectado: {peer.get('name') or pc_id} ({host}:{port})")


def _connect_stored_peer(pc_id: str) -> None:
    """Como _connect_peer_from_record, pero busca el registro ya guardado en peers.json: es lo que
    usa PeerHandler._pair, porque pairing.accept() no devuelve el peer entero (le contesta a quien
    se emparejo con su propio pc_info, no con el ajeno)."""
    peer = federation.get_peer(PEERS_FILE, pc_id)
    if peer is not None:
        _connect_peer_from_record(peer)


def _route_session(sid: str) -> tuple[dict | None, str | None]:
    """(tarjeta local, None) si `sid` es de esta PC; (None, pc_id) si es de otra PC conocida por el
    espejo; (None, None) si no se conoce en ningun lado (404 de siempre)."""
    with lock:
        s = sessions.get(sid)
    if s is not None:
        return s, None
    return None, mirror.MIRROR.owner_of(sid)


def _pending_owner(request_id: str) -> str | None:
    with lock:
        if request_id in pending:
            return None
    return next((p.get("pc") for p in mirror.MIRROR.pending() if p.get("request_id") == request_id), None)


def session_view_response(s: dict, view: str, query: dict) -> tuple[int, dict]:
    """Las cuatro vistas de una tarjeta (SESSION_VIEWS): screen, connections, turns, digest. La usan
    Handler._session_view (local) y PeerHandler (pedida por otra PC bajo demanda, §3.3)."""
    if view == "connections":
        return 200, connections_of(s["session_id"])
    if view == "screen":
        if not s.get("pid") or s.get("orphan"):
            return 409, {"ok": False, "error": "sin consola que leer"}
        return 200, read_screen(s["pid"])
    if not s.get("transcript_path") or not os.path.exists(s["transcript_path"]):
        note = "sin transcripcion"
        if s["agent"] == "pi" and not s.get("hooked"):
            note = "Pi detectado sin extension activa: ejecutá /reload en esa terminal tras instalar con py -3.14 install.py --pi-only"
        elif s["agent"] == "pi" and not s.get("transcript_path"):
            note = "Pi todavía no guardó una transcripción (primer turno pendiente o --no-session)"
        return 200, {"meta": {}, "turns": [], "has_more": False, "note": note}
    try:
        n = int((query.get("n") or ["10"])[0])
    except ValueError:
        return 400, {"error": "n debe ser un numero"}
    if view == "turns":
        before = (query.get("before") or [None])[0]
        return 200, transcripts.turns(s["agent"], s["transcript_path"], n, before, leaf_id=transcripts.leaf_of(s))
    return 200, transcripts.digest(s["agent"], s["transcript_path"], n, leaf_id=transcripts.leaf_of(s))


def _push_to_ui_clients(payload: str) -> None:
    with lock:
        dead = []
        for q in ui_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            ui_clients.remove(q)


def _with_mirror(local: dict) -> dict:
    """Lo local (de `_local_state`) con lo espejado de las otras PCs agregado en las cuatro listas:
    es lo que ve el tablero. El espejo no necesita el lock: mirror.py tiene el suyo."""
    return {
        "sessions": local["sessions"] + mirror.MIRROR.sessions(),
        "pending": local["pending"] + mirror.MIRROR.pending(),
        "links": local["links"] + mirror.MIRROR.links(),
        "rules": local["rules"] + mirror.MIRROR.rules(),
    }


def broadcast_mirror_snapshot() -> None:
    """El espejo cambio (un peer mando un evento, se cayo o volvio): se reemite un snapshot
    completo (local + espejo) solo a los clientes del tablero, para que una tarjeta remota se vea
    en vivo sin esperar el proximo `/sessions`. Es `mirror.MIRROR.on_change`."""
    with lock:
        local = _local_state()
    _push_to_ui_clients(
        json.dumps(
            {
                "type": "snapshot",
                **_with_mirror(local),
                "build": build_id(),
            },
            ensure_ascii=False,
        )
    )


def _stream_sse(handler: BaseHTTPRequestHandler, initial_json: str, extra_client_lists: list[list]) -> None:
    """Bucle SSE compartido por `/events` (tablero) y `/peer/events` (otro PC): un chunk inicial con
    el snapshot que ya arma cada llamador, despues cada mensaje que llegue a la cola propia (que se
    registra en `clients`, la verdad local, y ademas en `extra_client_lists`), y un ping cada 15 s
    si no llego nada. Extraido de lo que antes era Handler._sse, sin cambiar el formato del wire."""
    q: queue.Queue = queue.Queue(maxsize=1000)
    with lock:
        clients.append(q)
        for lst in extra_client_lists:
            lst.append(q)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    # chunked explicito: sin esto, cloudflared (y cualquier proxy HTTP/1.1) no sabe donde termina
    # la respuesta y la retiene entera; el navegador directo la toleraba igual
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()

    def chunk(payload: bytes) -> None:
        handler.wfile.write(f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n")
        handler.wfile.flush()

    try:
        chunk(f"data: {initial_json}\n\n".encode())
        while True:
            try:
                data = q.get(timeout=15)
                chunk(f"data: {data}\n\n".encode())
            except queue.Empty:
                chunk(f'data: {{"type": "ping", "build": "{build_id()}"}}\n\n'.encode())
    except BrokenPipeError, ConnectionError, OSError:
        pass
    finally:
        with lock:
            if q in clients:
                clients.remove(q)
            for lst in extra_client_lists:
                if q in lst:
                    lst.remove(q)


class QuietServer(ThreadingHTTPServer):
    """socketserver imprime un traceback entero en stderr cada vez que el navegador cierra una
    conexion keep-alive mientras se lee la proxima peticion (WinError 10053). Eso no es un error
    nuestro: se calla. Cualquier otra excepcion va al log propio, en una linea en consola.

    En Windows SO_REUSEADDR deja que un segundo server escuche el mismo puerto sin error: los dos
    quedan vivos y se reparten los eventos (visto el 2026-09-25, uno de la vispera sin soporte de
    CODA se comia los UserPromptSubmit). Se pide el puerto en exclusiva."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if e is not None and is_disconnect(e):
            return
        log(traceback.format_exc())


# Las vistas de una tarjeta, /sessions/<id>/<vista>: las atiende _session_view con una sola busqueda.
SESSION_VIEWS = ("screen", "connections", "turns", "digest")


class RequestError(ValueError):
    """Pedido invalido: respuesta al cliente, no un error interno con traceback."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "lienzo/0.1"
    protocol_version = "HTTP/1.1"
    # cierra un socket que no manda nada en 30 s (slow-loris, hallazgo A3 del pentest): un cuerpo
    # declarado y no enviado retenia el hilo para siempre. El SSE escribe un latido cada 15 s, asi
    # que las conexiones /events largas no lo alcanzan.
    timeout = 30

    def log_message(self, fmt, *args):  # silencio; el log propio alcanza
        pass

    def _server_error(self, e: BaseException) -> None:
        """Final de todos los do_*: si el navegador cerro la conexion a mitad de la respuesta no hay
        a quien contestar. Cualquier otra excepcion va entera al log con un id corto, y al cliente le
        llega ese id y nada mas: str(e) podia llevar rutas y nombres de la maquina, y por el tunel
        eso sale hacia afuera. El id esta en las dos puntas para poder cruzarlas."""
        if is_disconnect(e):
            return
        if isinstance(e, RequestError):
            return self._json(e.status, {"error": str(e)})
        eid = secrets.token_hex(4)
        log(f"error {eid} en {self.command} {self.path}:\n{traceback.format_exc()}")
        # el id va tambien dentro de `error`: la UI muestra ese campo tal cual, asi se ve sin tocar web/
        return self._json(500, {"error": f"error interno del lienzo ({eid})", "error_id": eid})

    def _json(self, code: int, obj, extra_headers: dict | None = None) -> None:
        return self._send_json(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), extra_headers)

    def _send_json(self, code: int, body: bytes, extra_headers: dict | None = None) -> None:
        """Cuerpo JSON ya serializado. Lo que se arma con el lock tomado se escribe con esto sin el:
        el write al socket tarda lo que tarde el cliente en leer (por el tunel, un celular), y con el
        lock tomado eso frena los hooks y todo lo demas."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> list[str]:
        """Primera linea de cada do_*, antes de decidir nada. Lee el cuerpo: si queda sin leer en el
        socket (un 403 o un 404 tempranos), el siguiente request de la misma conexion keep-alive lo
        toma como linea de pedido y contesta 501. Y parte la ruta: devuelve los tramos de la URL, que
        es con lo que cada handler elige, y deja la query en `self.query`."""
        u = urllib.parse.urlparse(self.path)
        self.query = urllib.parse.parse_qs(u.query)
        self.query_string = u.query  # para reenviar una vista remota (§3.3) con los mismos n/before
        parts = [p for p in u.path.split("/") if p]
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0].strip() if len(lengths) == 1 else "0"
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1 or not re.fullmatch(r"[0-9]{1,20}", length):
            self.close_connection = True
            raise RequestError("Content-Length invalido o Transfer-Encoding no soportado")
        n = int(length)
        cap = MAX_ATTACH if (len(parts) == 3 and parts[0] == "sessions" and parts[2] == "attach") else MAX_BODY
        if n > cap:
            self.close_connection = True
            raise RequestError("cuerpo demasiado grande", 413)
        self.raw = self.rfile.read(n) if n else b""
        if len(self.raw) != n:
            self.close_connection = True
            raise RequestError("cuerpo incompleto")
        return parts

    def _prepare(self, *, write: bool = False, authenticated: bool = False) -> list[str] | None:
        """Mismos limites, Host y CSRF para todos los metodos; None si ya se rechazo."""
        try:
            parts = self._route()
            if not self._host_ok():
                raise RequestError("Host no valido")
            if write and not self._csrf_ok():
                raise RequestError("falta X-Lienzo o el Origin no es propio", 403)
            if authenticated and not self._authed():
                raise RequestError("hace falta iniciar sesion", 401)
            return parts
        except Exception as e:
            self._server_error(e)
            return None

    def _host_ok(self) -> bool:
        """Valida el Host de cada pedido (hallazgo C1: sin esto un reencuadre DNS le entrega el
        lienzo entero a cualquier pagina web que la victima abra). Acepta solo los nombres locales
        y, si el tunel esta arriba, exactamente el host de remote_url. Cualquier otro Host: afuera.
        Con esto _csrf_ok queda parado sobre un Host ya de confianza."""
        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0].strip("[]") if host else ""
        if hostname in ("127.0.0.1", "localhost", "::1"):
            return True
        # Una IP literal de la LAN: el tablero abierto desde el celular con --host 0.0.0.0. **No
        # debilita el hallazgo C1**: el reencuadre de DNS necesita un NOMBRE que el atacante pueda
        # volver a resolver contra 192.168.x.x, y aca se exige que el Host sea la direccion escrita
        # a mano. Un nombre que no sea localhost sigue afuera.
        try:
            if ipaddress.ip_address(hostname).is_private:
                return True
        except ValueError:
            pass
        if remote_url:
            rh = (urllib.parse.urlparse(remote_url).hostname or "").lower()
            if rh and hostname == rh:
                return True
        return False

    def _session(self, sid: str) -> dict | None:
        """La tarjeta pedida, o None con el 404 ya contestado. Es el arranque de toda ruta
        /sessions/<id>/..., que si no repite la busqueda con el lock y el mismo mensaje de error."""
        with lock:
            s = sessions.get(sid)
        if s is None:
            self._json(404, {"error": "sesion desconocida"})
        return s

    def _json_body(self) -> dict:
        """JSON del cuerpo tolerante a clientes que mandan latin-1 (un curl desde Git Bash)."""
        raw = self.raw
        if not raw:
            return {}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        try:
            d = json.loads(text)
        except ValueError as e:
            raise RequestError("JSON invalido") from e
        if not isinstance(d, dict):
            raise RequestError("el cuerpo debe ser un objeto JSON")
        return d

    # --- identidad del cliente ------------------------------------------------------
    def _client_ip(self) -> str:
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _via_tunnel(self) -> bool:
        return bool(self.headers.get("CF-Connecting-IP")) or self.headers.get("X-Forwarded-Proto") == "https"

    def _is_local(self) -> bool:
        """La propia PC y la LAN de casa. Lo que entra por el tunel nunca, aunque mienta la IP.

        Decision de Ariel del 2026-09-18: con `--host 0.0.0.0` el tablero se abre desde el celular
        de la LAN **sin login**. La red de casa se trata como la propia maquina; lo que llega por
        cloudflared trae `CF-Connecting-IP` o `X-Forwarded-Proto`, cae en `_via_tunnel` y sigue
        exigiendo la cookie de passphrase + TOTP.

        Quien este en la LAN maneja las terminales: la puerta la da la red, no una credencial.
        """
        if self._via_tunnel():
            return False
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return ip.is_loopback or ip.is_private or ip.is_link_local

    def _authed(self) -> bool:
        """Decision del autor (2026-09-05): en la propia PC no se pide login. El server solo
        escucha en 127.0.0.1, asi que 'local' es una conexion sin cabeceras del tunel. Lo que
        entra por cloudflared trae CF-Connecting-IP y exige la cookie (passphrase + TOTP).
        Hallazgo A2: cae CERRADA. Si auth.json desaparece con el tunel arriba, lo remoto pasa a
        exigir cookie igual (auth.check da False sin sesiones), no queda abierto. El alta (/setup,
        /enroll, /login) sigue saliendo por su lista blanca de rutas, antes de este chequeo."""
        return self._is_local() or auth.check(auth.parse_cookie(self.headers.get("Cookie")))

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Lienzo") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        ohost = origin.split("//", 1)[-1].lower()
        host = (self.headers.get("Host") or "").lower()
        # el propio host, o el dev server de Vite en la misma maquina (hallazgo A1: puerto fijo
        # 5173, no cualquier puerto de localhost)
        return ohost == host or ohost in ("localhost:5173", "127.0.0.1:5173")

    def do_GET(self):
        parts = self._prepare()
        if parts is None:
            return
        try:
            if not parts or parts == ["docs"]:
                # /docs es la misma pagina: el front mira la ruta y muestra la referencia
                index = os.path.join(DIST, "index.html")
                if not os.path.exists(index):
                    return self._json(503, {"error": "falta el build de la UI: cd web && npm install && npm run build"})
                return self._file(index, "text/html; charset=utf-8")
            if parts[0] == "assets" and len(parts) == 2 and os.path.isdir(DIST):
                return self._asset(parts[1])
            if parts == ["favicon.svg"] and os.path.isdir(DIST):
                # el icono de la pestaña: vive en la raiz del build, no en assets/
                return self._file(os.path.join(DIST, "favicon.svg"), "image/svg+xml", cache="public, max-age=86400")
            if parts == ["health"]:
                return self._json(200, {"ok": True, "sessions": len(sessions), "pending": len(pending), "ts": now()})
            if parts == ["auth"]:
                return self._json(
                    200,
                    {
                        "configured": auth.configured(),
                        "authenticated": self._authed(),
                        "local": self._is_local(),
                        "remote_url": remote_url,
                        "mode": auth.mode(),
                    },
                )
            if parts == ["totp"]:
                # volver a ver el QR de Authenticator (segundo telefono, o alta interrumpida): solo local
                if not self._is_local():
                    return self._json(403, {"error": "solo desde la PC"})
                cur = auth.current_otpauth(os.environ.get("USERNAME", "lienzo"))
                return self._json(200, cur) if cur else self._json(404, {"error": "sin acceso configurado"})
            if parts == ["enroll"]:
                return self._enroll()
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["sessions"]:
                # serializar con el lock (es CPU pura) y escribir afuera: es el cuerpo mas grande
                # que manda el server, y antes se escribia al socket con el lock tomado. El espejo
                # (sesiones de otras PCs, plan §3.3) se agrega afuera: mirror.py tiene su propio lock
                with lock:
                    local = sorted(sessions.values(), key=lambda s: (s["repo"], s["started"]))
                tablero = json.dumps(local + mirror.MIRROR.sessions(), ensure_ascii=False).encode("utf-8")
                return self._send_json(200, tablero)
            if len(parts) == 2 and parts[0] == "docs" and parts[1] in DOCS:
                return self._file(DOCS[parts[1]], "text/markdown; charset=utf-8")
            if len(parts) == 3 and parts[:2] == ["docs", "img"]:
                return self._doc_img(parts[2])
            if parts == ["peers"]:
                return self._get_peers()
            if parts == ["peers", "lan"]:
                return self._get_peers_lan()
            if parts == ["pending"]:
                return self._json(200, public_pending() + mirror.MIRROR.pending())
            if parts == ["links"]:
                return self._json(200, links.snapshot())
            if parts == ["rules"]:
                return self._json(200, rules.snapshot())
            if parts == ["config"]:
                return self._json(200, public_config())
            # el sello del bundle servido: el tablero lo consulta cada 30 s y se recarga cuando
            # cambia (ver `build_id`). Ruta propia y no el latido del SSE porque el latido sale
            # solo cuando la cola esta en silencio 15 s, y con el tablero activo casi nunca lo esta
            if parts == ["build"]:
                return self._json(200, {"build": build_id()})
            if parts == ["events"]:
                return self._sse()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] in SESSION_VIEWS:
                return self._session_view(parts[1], parts[2])
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _asset(self, name: str) -> None:
        """Un estatico del build de Vite. Sin ".." posibles: el nombre sale de partir la ruta por
        "/", y de ahi no puede venir un separador de Windows ni un archivo oculto."""
        if "\\" in name or name.startswith("."):
            return self._json(404, {"error": "ruta invalida"})
        return self._file(
            os.path.join(DIST, "assets", name),
            MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
            cache="public, max-age=31536000, immutable",
        )

    def _doc_img(self, name: str) -> None:
        """Una imagen de docs/img, las que el README enlaza como `docs/img/x.png`. Mismo resguardo
        que `_asset`, y solo tipos de imagen: esa carpeta no sirve otra cosa"""
        ext = os.path.splitext(name)[1].lower()
        if "\\" in name or name.startswith(".") or ext not in (".png", ".svg"):
            return self._json(404, {"error": "ruta invalida"})
        return self._file(os.path.join(DOCS_IMG, name), MIME[ext], cache="public, max-age=3600")

    def _enroll(self) -> None:
        """GET /enroll?token=...: entrega passphrase y otpauth una sola vez, para el alta desde el
        celular con un QR. El token es la credencial; vale 15 min desde el alta y se apaga solo."""
        global enroll
        tok = self.query.get("token", [""])[0]
        with lock:
            e = enroll
            if e and time.time() > e["expires"]:
                enroll = e = None
            if e and tok and secrets.compare_digest(tok, e["token"]):
                enroll = None  # validar y consumir bajo el mismo lock: canje unico
            else:
                e = None
        if e is None:
            log(f"enroll rechazado desde {self._client_ip()}")
            return self._json(410, {"error": "el enlace de alta vencio o no es valido; rehacer desde la PC"})
        log(f"enroll entregado a {self._client_ip()} (token consumido)")
        return self._json(
            200,
            {"passphrase": e["passphrase"], "otpauth": e["otpauth"], "expires_in": int(e["expires"] - time.time())},
        )

    def _session_view(self, sid: str, view: str) -> None:
        """Las cuatro vistas de una tarjeta (SESSION_VIEWS). Una vista que no este en la lista no
        llega hasta aca: sigue cayendo en el 404 de ruta desconocida de do_GET, no en el de sesion
        desconocida. `sid` de otra PC (plan §3.3, "bajo demanda"): se pide a su dueña y se devuelve
        tal cual."""
        s, owner = _route_session(sid)
        if s is None and owner is None:
            return self._json(404, {"error": "sesion desconocida"})
        if owner is not None:
            path = f"/sessions/{sid}/{view}" + (f"?{self.query_string}" if self.query_string else "")
            code, res = mirror.MIRROR.forward(owner, "GET", path)
            return self._json(code, res)
        code, res = session_view_response(s, view, self.query)
        return self._json(code, res)

    def do_POST(self):
        parts = self._prepare(write=True)
        if parts is None:
            return
        try:
            if parts == ["login"]:
                return self._login()
            if parts == ["logout"]:
                auth.logout(auth.parse_cookie(self.headers.get("Cookie")))
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{auth.COOKIE}=; Path=/; Max-Age=0"})
            if parts == ["setup"]:
                return self._setup()
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["rescan"]:
                threading.Thread(target=sweep_once, daemon=True).start()
                return self._json(202, {"ok": True})
            if parts == ["rules"]:
                code, res = create_rule(self._json_body())
                return self._json(code, res)
            if parts == ["peers", "offer"]:
                return self._peers_offer()
            if parts == ["peers", "join"]:
                return self._peers_join()
            if parts == ["sessions", "launch"]:
                return self._launch()
            if len(parts) == 2 and parts[0] == "pending":
                d = self._json_body()
                if d.get("decision") not in ("allow", "deny"):
                    return self._json(400, {"error": "decision debe ser allow o deny"})
                owner = _pending_owner(parts[1])
                if owner is not None:
                    code, res = mirror.MIRROR.forward(owner, "POST", f"/pending/{parts[1]}", d)
                    return self._json(code, res)
                code, res = answer_pending(parts[1], d["decision"], d.get("reason", ""), d.get("answers"))
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "sessions":
                sid, action = parts[1], parts[2]
                if action not in ("send", "interrupt", "approve", "dialog", "attach"):
                    return self._json(404, {"error": "ruta desconocida"})
                s, owner = _route_session(sid)
                if s is None and owner is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if owner is not None:
                    return self._forward_session_post(owner, sid, action)
                if action == "send":
                    return self._send(s)
                if action == "interrupt":
                    code, res = interrupt_session(s)
                    return self._json(code, res)
                if action == "approve":
                    d = self._json_body()
                    if d.get("decision") not in ("allow", "deny"):
                        return self._json(400, {"error": "decision debe ser allow o deny"})
                    code, res = answer_coda_ask(s, d["decision"])
                    return self._json(code, res)
                if action == "dialog":
                    d = self._json_body()
                    if not isinstance(d.get("choice"), int) or isinstance(d.get("choice"), bool):
                        return self._json(400, {"error": "choice debe ser el numero de la opcion"})
                    code, res = answer_dialog(s, d["choice"])
                    return self._json(code, res)
                if action == "attach":
                    name = urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin")
                    data = self.raw
                    if not data:
                        return self._json(400, {"error": "cuerpo vacio"})
                    path = save_attachment(s["session_id"], name, data)
                    return self._json(200, {"path": path, "bytes": len(data)})
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _forward_session_post(self, pc: str, sid: str, action: str) -> None:
        """Reenvia send/interrupt/approve/dialog/attach a la PC dueña (plan §3.4) y devuelve su
        respuesta tal cual. `attach` viaja como base64 adentro del JSON (no hay transporte binario
        en federation.HTTPTransport.request todavia): mas trafico, pero sin agregar otro camino."""
        if action == "attach":
            name = urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin")
            if not self.raw:
                return self._json(400, {"error": "cuerpo vacio"})
            body = {"filename": name, "data_b64": base64.b64encode(self.raw).decode("ascii")}
        else:
            body = self._json_body()
        code, res = mirror.MIRROR.forward(pc, "POST", f"/sessions/{sid}/{action}", body)
        return self._json(code, res)

    def _login(self) -> None:
        """POST /login: passphrase mas codigo TOTP a cambio de la cookie. Hacia afuera va un solo
        mensaje de error, salvo el bloqueo por intentos, que conviene que se vea."""
        d = self._json_body()
        ok, motivo, token = auth.login(
            str(d.get("passphrase", "")), str(d.get("code", "")), self._client_ip(), self.headers.get("User-Agent", "")
        )
        if not ok:
            log(f"login fallido desde {self._client_ip()}: {motivo}")
            msg = motivo if motivo.startswith("bloqueado") or "no configurado" in motivo else "codigo incorrecto"
            return self._json(401, {"ok": False, "error": msg})
        log(f"login ok desde {self._client_ip()}")
        return self._json(200, {"ok": True}, {"Set-Cookie": auth.cookie_header(token, secure=self._via_tunnel())})

    def _setup(self) -> None:
        """POST /setup: alta del acceso remoto, solo desde la propia PC y solo una vez. Deja armado
        el enlace de alta, un token de 15 min que el celular canjea una sola vez por /enroll."""
        if not self._is_local():
            return self._json(403, {"error": "el alta se hace desde la PC"})
        if auth.configured():
            return self._json(409, {"error": "ya esta configurado; borrar ~/.lienzo/auth.json para rehacerlo"})
        d = self._json_body()
        res = auth.setup(
            account=os.environ.get("USERNAME", "lienzo"), mode="full" if d.get("mode") == "full" else "code"
        )
        global enroll
        with lock:
            enroll = {
                "token": secrets.token_urlsafe(24),
                "passphrase": res["passphrase"],
                "otpauth": res["otpauth"],
                "expires": time.time() + ENROLL_S,
            }
            res["enroll_token"] = enroll["token"]
            res["enroll_expires_s"] = ENROLL_S
        log("acceso remoto configurado (passphrase + TOTP); enlace de alta valido 15 min")
        return self._json(200, res)

    def _send(self, s: dict) -> None:
        """POST /sessions/<id>/send: inyecta el texto en la consola y, solo si entro, deja la flecha
        en el historial. Quien queda de cada lado depende de como se pidio el envio."""
        d = self._json_body()
        text, attachments = d.get("text", ""), d.get("attachments") or []
        if (
            not isinstance(text, str)
            or not isinstance(attachments, list)
            or any(not isinstance(a, str) for a in attachments)
        ):
            raise RequestError("text debe ser texto y attachments una lista de rutas")
        if d.get("native"):
            # el canal nativo (Claude a Claude por SendMessage) no cruza PCs: ListAgents es de la
            # propia maquina y no hay forma de resolver un nombre corto contra una sesion remota
            otro = d.get("link_to") or d.get("from")
            if otro and mirror.MIRROR.owner_of(otro) is not None:
                return self._json(409, {"error": "el canal nativo no cruza PCs"})
        code, res = send_to_session(s, text, attachments)
        if code == 200:
            sid, text = s["session_id"], d.get("text", "")
            src, link_to = d.get("from"), d.get("link_to")
            kind = "native" if d.get("native") else "send"
            if link_to and link_to in sessions and link_to != sid:
                # canal nativo: se le habla a A para que abra conversacion con B; la flecha es A -> B
                add_link(sid, link_to, text, kind)
            elif src and src in sessions and src != sid:
                add_link(src, sid, text, kind)
                if d.get("copycat") is True:
                    # pegar trabajo: la copia hereda el titulo; el origen se detiene salvo "Duplicar"
                    res.update(hand_over(s, sessions[src], stop=d.get("stop_origin") is not False))
            elif not src and not link_to:
                # lo que el usuario escribio desde el lienzo: queda en el historial de la sesion
                # (pestana Conexiones) como 'recibido de vos'; sin flecha
                add_link(None, sid, text, "user")
        return self._json(code, res)

    def do_PUT(self):
        parts = self._prepare(write=True, authenticated=True)
        if parts is None:
            return
        try:
            if parts == ["config"]:
                return self._put_config()
            if parts == ["peers", "self"]:
                return self._put_peer_self()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "title":
                return self._put_title(parts[1])
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "coordinator":
                return self._put_coordinator(parts[1])
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "stopped":
                return self._put_stopped(parts[1])
            if len(parts) == 2 and parts[0] == "rules":
                code, res = edit_rule(parts[1], self._json_body())
                return self._json(code, res)
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _put_peer_self(self) -> None:
        """PUT /peers/self {name}: renombra esta PC (identity.set_name); el pc_id no cambia."""
        name = self._json_body().get("name")
        if not isinstance(name, str) or not name.strip():
            return self._json(400, {"error": "name es obligatorio"})
        try:
            info = identity.set_name(name)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        return self._json(200, info)

    def _put_config(self) -> None:
        """PUT /config: solo las claves de UI_CONFIG_KEYS (auto_continue, auto_retry) y solo como bool; el
        resto de config.json (ejemplos, wait) es de hook.py y no se toca. Se valida todo el cuerpo
        antes de escribir nada: media tanda aplicada seria peor que ninguna."""
        d = self._json_body()
        if not d or [k for k in d if k not in UI_CONFIG_KEYS]:
            return self._json(400, {"error": f"solo se puede cambiar {', '.join(UI_CONFIG_KEYS)}"})
        for k, v in d.items():
            if not isinstance(v, bool):
                return self._json(400, {"error": f"{k} debe ser true o false"})
        for k, v in d.items():
            set_config_key(k, v)
            log(f"config: {k} = {v} (desde la UI, {self._client_ip()})")
        return self._json(200, public_config())

    def _put_title(self, sid: str) -> None:
        """PUT /sessions/<id>/title: titulo a mano. Vacio vuelve a la logica automatica. `sid` de
        otra PC (plan §3.4): se valida el cuerpo igual, y recien despues se reenvia."""
        title = self._json_body().get("title")
        if title is not None and not isinstance(title, str):
            return self._json(400, {"error": "title debe ser un texto"})
        s, owner = _route_session(sid)
        if s is None and owner is None:
            return self._json(404, {"error": "sesion desconocida"})
        if owner is not None:
            code, res = mirror.MIRROR.forward(owner, "PUT", f"/sessions/{sid}/title", {"title": title})
            return self._json(code, res)
        set_title(s, title or "")  # toma el lock por dentro; leer la transcripcion, no
        with lock:
            touch(s)
        log(f"titulo de {sid[:8]} -> {s['title']!r} ({s.get('title_source')})")
        return self._json(200, {"ok": True, "title": s["title"], "title_source": s.get("title_source")})

    def _put_stopped(self, sid: str) -> None:
        """PUT /sessions/<id>/stopped: la llave. {on: true} la detiene (Esc si corre, aviso a sus
        conectadas, no recibe nada); {on: false} la habilita."""
        on = self._json_body().get("on")
        if not isinstance(on, bool):
            return self._json(400, {"error": "on debe ser true o false"})
        s, owner = _route_session(sid)
        if s is None and owner is None:
            return self._json(404, {"error": "sesion desconocida"})
        if owner is not None:
            code, res = mirror.MIRROR.forward(owner, "PUT", f"/sessions/{sid}/stopped", {"on": on})
            return self._json(code, res)
        res = set_stopped(s, on)
        return self._json(200, {"ok": True, "stopped_by": s.get("stopped_by"), **res})

    def _put_coordinator(self, sid: str) -> None:
        """PUT /sessions/<id>/coordinator: marca la coordinadora del repo (a lo sumo una en toda la
        federacion). `scope: "pc"` la separa solo para esta PC (plan §3.6)."""
        d = self._json_body()
        on = d.get("on")
        if not isinstance(on, bool):
            return self._json(400, {"error": "on debe ser true o false"})
        scope = d.get("scope")
        s, owner = _route_session(sid)
        if s is None and owner is None:
            return self._json(404, {"error": "sesion desconocida"})
        if owner is not None:
            code, res = mirror.MIRROR.forward(owner, "PUT", f"/sessions/{sid}/coordinator", d)
            return self._json(code, res)
        changed = set_coordinator(s, on, scope=scope)
        log(
            f"coordinadora de {s.get('repo')}: {sid[:8]} -> {on} "
            f"({', '.join(x['session_id'][:8] for x in changed) or 'sin cambios'})"
        )
        return self._json(200, {"ok": True, "coordinator": bool(s.get("coordinator"))})

    def _get_peers(self) -> None:
        """GET /peers: la propia PC primero (`local: true`), despues cada peer emparejado. Sin
        peers, un array de un solo elemento (la propia): el front colapsa la tira con menos de dos."""
        info = identity.pc_info()
        local_row = {**info, "alive": True, "last_seen": now(), "local": True, "health": health.snapshot()}
        return self._json(200, [local_row] + mirror.MIRROR.peers_status())

    def _get_peers_lan(self) -> None:
        """GET /peers/lan: las PCs de la LAN con el lienzo corriendo que todavia no estan
        emparejadas, por su anuncio sin firma del beacon (`{pc_id, name, ip, port, last_seen}`).
        Sirven para mostrarlas y precargar la IP al emparejar; hablarles sigue pidiendo la frase."""
        emparejadas = {p.get("pc_id") for p in federation.list_peers(PEERS_FILE)}
        lan = [
            {**d, "last_seen": mirror.iso(d["last_seen"])} for d in beacon.discovered() if d["pc_id"] not in emparejadas
        ]
        return self._json(200, lan)

    def _peers_offer(self) -> None:
        d = self._json_body()
        ttl = d.get("ttl_s")
        try:
            ttl = int(ttl) if ttl is not None else pairing.OFFER_TTL_S
        except TypeError, ValueError:
            return self._json(400, {"error": "ttl_s debe ser un numero"})
        return self._json(200, pairing.offer(ttl_s=ttl))

    def _peers_join(self) -> None:
        d = self._json_body()
        phrase, host, port = d.get("phrase"), d.get("host"), d.get("port")
        if not isinstance(phrase, str) or not phrase.strip() or not isinstance(host, str) or not host.strip():
            return self._json(400, {"error": "phrase y host son obligatorios"})
        if not isinstance(port, int) or isinstance(port, bool):
            return self._json(400, {"error": "port debe ser un numero"})
        try:
            peer = pairing.join(phrase, host, port)
        except pairing.PairingError as e:
            return self._json(400, {"error": str(e)})
        except federation.PeerLimitError as e:
            return self._json(409, {"error": str(e)})
        _connect_peer_from_record(peer)
        log(f"peer emparejado: {peer.get('name') or peer.get('pc_id')} ({host}:{port})")
        return self._json(200, peer)

    def _launch(self) -> None:
        """POST /sessions/launch {pc, cwd, title, agent}: local con launch.launch (frente B), o
        reenviada a la PC `pc` por /peer/launch."""
        d = self._json_body()
        cwd, agent = d.get("cwd"), d.get("agent")
        title = d.get("title") or ""
        pc = d.get("pc")
        if not isinstance(cwd, str) or not cwd.strip() or not isinstance(agent, str) or not isinstance(title, str):
            return self._json(400, {"error": "cwd y agent son obligatorios"})
        if pc and pc != identity.pc_id():
            code, res = mirror.MIRROR.forward(pc, "POST", "/launch", {"cwd": cwd, "title": title, "agent": agent})
            return self._json(code, res)
        res = launch.launch(cwd, title, agent)
        return self._json(200 if res.get("ok") else 400, res)

    def do_DELETE(self):
        parts = self._prepare(write=True, authenticated=True)
        if parts is None:
            return
        try:
            if len(parts) == 2 and parts[0] == "sessions":
                sid = parts[1]
                _, owner = _route_session(sid)
                if owner is not None:
                    code, res = mirror.MIRROR.forward(owner, "DELETE", f"/sessions/{sid}")
                    return self._json(code, res)
                # sid local o de nadie: borrar una tarjeta que no existe es un no-op idempotente
                # (200 igual), como siempre fue; no hay 404 que devolver aca
                drop_session(sid, "borrada desde la UI")
                return self._json(200, {"ok": True})
            if len(parts) == 2 and parts[0] == "peers":
                return self._delete_peer(parts[1])
            if len(parts) == 2 and parts[0] in ("links", "rules"):
                log(f"{parts[0][:-1]} {parts[1]} borrada desde la UI ({self._client_ip()})")
                (links if parts[0] == "links" else rules).remove(lambda x: x["id"] == parts[1])
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _delete_peer(self, pc_id: str) -> None:
        """DELETE /peers/<pc_id>: revocar. Corta el espejo y lo saca de peers.json; el peer, del
        otro lado, se entera cuando le deja de contestar (no hay aviso activo)."""
        mirror.MIRROR.disconnect(pc_id)
        removed = federation.remove_peer(PEERS_FILE, pc_id)
        log(f"peer {pc_id} revocado" + ("" if removed else " (no estaba emparejado)"))
        return self._json(200, {"ok": True})

    def _file(self, path: str, ctype: str, cache: str = "no-store") -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            # hallazgo M3: la ruta absoluta (letra de unidad, arbol del repo) va solo al log, no al
            # cliente, que por el tunel podria ser un anonimo. Mismo criterio que _server_error.
            log(f"404 estatico: {path}")
            return self._json(404, {"error": "no encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _sse(self) -> None:
        # serializar con el lock tomado: `sessions.values()` son los dicts vivos, y armar el JSON
        # afuera podia leer una tarjeta a medio escribir (o reventar si el dict cambia de tamaño).
        # El espejo (sesiones de otras PCs) no necesita el lock: mirror.py tiene el suyo.
        with lock:
            local = _local_state()
        snapshot = json.dumps(
            {
                "type": "snapshot",
                **_with_mirror(local),
                "build": build_id(),
            },
            ensure_ascii=False,
        )
        # `ui_clients`: ademas de la verdad local (`clients`, como siempre) este stream recibe el
        # snapshot repetido cada vez que el espejo cambia (broadcast_mirror_snapshot); un peer que
        # se conecta a /peer/events NO se registra ahi (ver PeerHandler._peer_events).
        _stream_sse(self, snapshot, [ui_clients])


# --- listener de peers: --peer-port, solo /peer/* (plan §3.2, §3.3, §3.4) -----------------------


class PeerHandler(BaseHTTPRequestHandler):
    """El segundo listener, bind a la IP de LAN: solo atiende /peer/*, todo firmado salvo
    GET /peer/hello y POST /peer/pair (que son, justamente, como se consigue la clave para firmar
    lo demas). Ejecuta los mismos comandos que Handler pero siempre sobre la sesion LOCAL de esta
    PC: es lo que Handler reenvia cuando `owner_of(sid)` da otra PC, y lo que mirror.py lee para
    armar el espejo."""

    server_version = "lienzo-peer/0.1"
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, fmt, *args):
        pass

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _parts_and_body(self) -> tuple[list[str], bytes] | None:
        """Ruta partida y cuerpo leido, con los mismos limites que Handler._route (Content-Length
        exacto, sin Transfer-Encoding, techo MAX_ATTACH en /attach). None (ya contestado) si algo
        no cierra."""
        u = urllib.parse.urlparse(self.path)
        self.query = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0].strip() if len(lengths) == 1 else "0"
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1 or not re.fullmatch(r"[0-9]{1,20}", length):
            self.close_connection = True
            self._json(400, {"error": "Content-Length invalido o Transfer-Encoding no soportado"})
            return None
        n = int(length)
        cap = MAX_ATTACH if parts[-1:] == ["attach"] else MAX_BODY
        if n > cap:
            self.close_connection = True
            self._json(413, {"error": "cuerpo demasiado grande"})
            return None
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:
            self.close_connection = True
            self._json(400, {"error": "cuerpo incompleto"})
            return None
        return parts, raw

    def _body_json(self, raw: bytes) -> dict:
        if not raw:
            return {}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        try:
            d = json.loads(text)
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}

    def _dispatch(self, method: str) -> None:
        got = self._parts_and_body()
        if got is None:
            return
        parts, raw = got
        if not parts or parts[0] != "peer":
            return self._json(404, {"error": "ruta desconocida"})
        rest = parts[1:]
        path = urllib.parse.urlparse(self.path).path
        sin_firma = (method == "GET" and rest == ["hello"]) or (method == "POST" and rest == ["pair"])
        pc_id = None
        if not sin_firma:
            pc_id = verify_peer_request(self.headers, method, path, raw)
            if pc_id is None:
                return self._json(401, {"error": "firma invalida"})
        try:
            self._route(method, rest, raw, pc_id)
        except Exception:
            eid = secrets.token_hex(4)
            log(f"error {eid} en peer {method} {self.path}:\n{traceback.format_exc()}")
            self._json(500, {"error": f"error interno del lienzo ({eid})"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _route(self, method: str, rest: list[str], raw: bytes, pc_id: str | None) -> None:
        log(f"peer {method} /peer/{'/'.join(rest)}" + (f" de {pc_id}" if pc_id else ""))
        if method == "GET" and rest == ["hello"]:
            info = identity.pc_info()
            return self._json(200, {"pc_id": info["pc_id"], "name": info["name"]})
        if method == "POST" and rest == ["pair"]:
            return self._pair(raw)
        if method == "GET" and rest == ["snapshot"]:
            return self._json(200, _local_state())
        if method == "GET" and rest == ["health"]:
            return self._json(200, health.snapshot())
        if method == "GET" and rest == ["events"]:
            return self._events()
        if method == "POST" and rest == ["launch"]:
            return self._launch(raw)
        if method == "POST" and rest == ["rules", "lock"]:
            return self._rules_lock(raw)
        if method == "POST" and rest == ["rules", "check"]:
            return self._rules_check(raw)
        if len(rest) == 3 and rest[0] == "sessions" and method == "GET" and rest[2] in SESSION_VIEWS:
            return self._session_view(rest[1], rest[2])
        if len(rest) == 3 and rest[0] == "sessions" and method == "POST":
            return self._session_post(rest[1], rest[2], raw)
        if len(rest) == 3 and rest[0] == "sessions" and method == "PUT":
            return self._session_put(rest[1], rest[2], raw)
        if len(rest) == 2 and rest[0] == "sessions" and method == "DELETE":
            drop_session(rest[1], "borrada desde otra PC")
            return self._json(200, {"ok": True})
        if len(rest) == 2 and rest[0] == "pending" and method == "POST":
            d = self._body_json(raw)
            if d.get("decision") not in ("allow", "deny"):
                return self._json(400, {"error": "decision debe ser allow o deny"})
            code, res = answer_pending(rest[1], d["decision"], d.get("reason", ""), d.get("answers"))
            return self._json(code, res)
        return self._json(404, {"error": "ruta desconocida"})

    def _pair(self, raw: bytes) -> None:
        body = self._body_json(raw)
        try:
            res = pairing.accept(body)
        except pairing.PairingError as e:
            return self._json(400, {"error": str(e)})
        _connect_stored_peer(str(body.get("pc_id") or ""))
        return self._json(200, res)

    def _launch(self, raw: bytes) -> None:
        d = self._body_json(raw)
        cwd, agent, title = d.get("cwd"), d.get("agent"), d.get("title") or ""
        if not isinstance(cwd, str) or not cwd.strip() or not isinstance(agent, str):
            return self._json(400, {"error": "cwd y agent son obligatorios"})
        res = launch.launch(cwd, title, agent)
        return self._json(200 if res.get("ok") else 400, res)

    def _rules_lock(self, raw: bytes) -> None:
        """POST /peer/rules/lock: el lock liviano de la carrera A<->B (plan §3.5), del lado de la
        PC de menor pc_id."""
        code, res = rl.handle_peer_lock(self._body_json(raw))
        return self._json(code, res)

    def _rules_check(self, raw: bytes) -> None:
        """POST /peer/rules/check: duplicado/clash del lado del destino de una regla remota (plan
        §3.5)."""
        code, res = rl.handle_peer_check(self._body_json(raw))
        return self._json(code, res)

    def _session_view(self, sid: str, view: str) -> None:
        with lock:
            s = sessions.get(sid)
        if s is None:
            return self._json(404, {"error": "sesion desconocida"})
        code, res = session_view_response(s, view, self.query)
        return self._json(code, res)

    def _session_post(self, sid: str, action: str, raw: bytes) -> None:
        with lock:
            s = sessions.get(sid)
        if s is None:
            return self._json(404, {"error": "sesion desconocida"})
        if action == "send":
            d = self._body_json(raw)
            text, attachments = d.get("text", ""), d.get("attachments") or []
            if (
                not isinstance(text, str)
                or not isinstance(attachments, list)
                or any(not isinstance(a, str) for a in attachments)
            ):
                return self._json(400, {"error": "text debe ser texto y attachments una lista de rutas"})
            code, res = send_to_session(s, text, attachments)
            return self._json(code, res)
        if action == "interrupt":
            code, res = interrupt_session(s)
            return self._json(code, res)
        if action == "approve":
            d = self._body_json(raw)
            if d.get("decision") not in ("allow", "deny"):
                return self._json(400, {"error": "decision debe ser allow o deny"})
            code, res = answer_coda_ask(s, d["decision"])
            return self._json(code, res)
        if action == "dialog":
            d = self._body_json(raw)
            if not isinstance(d.get("choice"), int) or isinstance(d.get("choice"), bool):
                return self._json(400, {"error": "choice debe ser el numero de la opcion"})
            code, res = answer_dialog(s, d["choice"])
            return self._json(code, res)
        if action == "attach":
            d = self._body_json(raw)
            name = d.get("filename") or "adjunto.bin"
            data_b64 = d.get("data_b64")
            if not isinstance(data_b64, str) or not data_b64:
                return self._json(400, {"error": "cuerpo vacio"})
            try:
                data = base64.b64decode(data_b64, validate=True)
            except ValueError, binascii.Error:
                return self._json(400, {"error": "adjunto invalido"})
            path = save_attachment(s["session_id"], name, data)
            return self._json(200, {"path": path, "bytes": len(data)})
        return self._json(404, {"error": "ruta desconocida"})

    def _session_put(self, sid: str, action: str, raw: bytes) -> None:
        with lock:
            s = sessions.get(sid)
        if s is None:
            return self._json(404, {"error": "sesion desconocida"})
        d = self._body_json(raw)
        if action == "title":
            title = d.get("title")
            if title is not None and not isinstance(title, str):
                return self._json(400, {"error": "title debe ser un texto"})
            set_title(s, title or "")
            with lock:
                touch(s)
            return self._json(200, {"ok": True, "title": s["title"], "title_source": s.get("title_source")})
        if action == "stopped":
            on = d.get("on")
            if not isinstance(on, bool):
                return self._json(400, {"error": "on debe ser true o false"})
            res = set_stopped(s, on)
            return self._json(200, {"ok": True, "stopped_by": s.get("stopped_by"), **res})
        if action == "coordinator":
            on = d.get("on")
            if not isinstance(on, bool):
                return self._json(400, {"error": "on debe ser true o false"})
            scope = d.get("scope")
            set_coordinator(s, on, scope=scope)
            return self._json(200, {"ok": True, "coordinator": bool(s.get("coordinator"))})
        return self._json(404, {"error": "ruta desconocida"})

    def _events(self) -> None:
        snapshot = json.dumps({"type": "snapshot", "build": build_id(), **_local_state()}, ensure_ascii=False)
        _stream_sse(self, snapshot, [])


def _lan_ip() -> str:
    """La IP de LAN de esta PC (nunca localhost, para que --peer-host tenga un default util): abre
    un socket UDP hacia una IP publica sin mandar nada (no hace falta que responda) y lee con que
    IP local hubiera salido. Con cualquier error, 127.0.0.1: el listener de peers no serviria de
    mucho asi, pero no revienta el arranque."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def build_id() -> str:
    """Sello del bundle que hay en web/dist. Viaja en cada latido del SSE para que un tablero
    abierto se entere de que hay una version nueva: el lienzo es una pagina sola y no se recarga
    sola, asi que despues de un `npm run build` seguia corriendo el bundle viejo y los cambios
    parecian no haberse aplicado. Vite reescribe index.html en cada build, asi que su mtime y su
    tamano alcanzan; sin build todavia, cadena vacia y el front no hace nada."""
    try:
        st = os.stat(os.path.join(DIST, "index.html"))
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return ""


def tunnel_loop(port: int) -> None:
    """Camino A (§7.6.2): cloudflared publica 127.0.0.1:<port> en una URL https de trycloudflare.
    Solo se levanta si hay login configurado; sin auth.json no se expone nada."""
    global remote_url
    if not os.path.exists(CLOUDFLARED):
        log(f"--remote: no encuentro {CLOUDFLARED} (winget install Cloudflare.cloudflared)")
        return
    if not auth.configured():
        log("--remote: esperando el alta del acceso (boton 'Acceso remoto' en la UI) para levantar el tunel")
        while not auth.configured():
            time.sleep(3)
    while True:
        remote_url = None
        try:
            # --protocol http2: con QUIC el SSE (/events) llegaba con cabeceras pero sin cuerpo
            p = subprocess.Popen(
                [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate", "--protocol", "http2"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000,
            )  # CREATE_NO_WINDOW
        except OSError as e:
            log(f"--remote: cloudflared no arranca: {e}")
            return
        for line in p.stderr or []:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and remote_url != m.group(0):
                remote_url = m.group(0)
                log(f"tunel: {remote_url}")
            elif any(k in line for k in ("ERR", "error", "Registered", "Connection")):
                log(f"cloudflared: {line.strip()[:200]}")
        p.wait()
        log(f"cloudflared termino (codigo {p.returncode}); reintento en 10 s")
        time.sleep(10)


def _beacon_sync_loop(stop_event: threading.Event, beacon) -> None:
    """Cada beacon visto que cambio de IP (DHCP) se guarda en peers.json y el espejo se reconecta
    con la IP nueva (plan §3.2, "el beacon la actualiza sola"). Corre cada 5 s; barato: solo mira
    lo que beacon.py ya junto, no manda nada por si mismo."""
    while not stop_event.wait(5.0):
        try:
            vistos = beacon.seen()
        except Exception as e:
            log(f"beacon: fallo al leer lo visto: {e}")
            continue
        for pc_id, info in vistos.items():
            ip = info.get("ip") if isinstance(info, dict) else None
            if not ip:
                continue
            peer = federation.get_peer(PEERS_FILE, pc_id)
            if peer is None or peer.get("ip") == ip:
                continue
            federation.update_peer_ip(PEERS_FILE, pc_id, ip)
            _connect_peer_from_record({**peer, "ip": ip})
            log(f"peer {peer.get('name') or pc_id}: IP actualizada por beacon a {ip}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="lienzo-server")
    ap.add_argument("--port", type=int, default=7321)
    ap.add_argument(
        "--host",
        default="127.0.0.1",
        help="interfaz donde escuchar. 0.0.0.0 permite controlar las terminales desde la LAN sin login; "
        "el tunel siempre exige autenticacion",
    )
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--sweep-every", type=float, default=30.0)
    ap.add_argument("--remote", action="store_true", help="publicar por cloudflared (exige login configurado)")
    ap.add_argument("--peer-port", type=int, default=7322, help="listener de peers (plan multi-PC §3.2)")
    ap.add_argument("--peer-host", default=None, help="IP de LAN del listener de peers; por defecto se autodetecta")
    ap.add_argument("--peers", action="store_true", help="arranca el listener de peers aunque peers.json este vacio")
    a = ap.parse_args()
    for d in (EVENTS, PENDING, ANSWERS, ADJUNTOS, SESSIONS):
        os.makedirs(d, exist_ok=True)
    # el puerto antes que los hilos: un segundo server no llega a consumir eventos
    try:
        srv = QuietServer((a.host, a.port), Handler)
    except OSError as e:
        log(f"no se pudo tomar {a.host}:{a.port} ({e}): ya hay un lienzo-server corriendo?")
        return 1
    purged, retitled = load_sessions()
    links.load(lambda l: l.get("to") in sessions and (not l.get("from") or l["from"] in sessions))
    rules.load(lambda r: r.get("to") in sessions and (not r.get("from") or r["from"] in sessions))
    purge_stale_at_rules()
    clean_attachments()
    if not a.no_sweep:
        sweep_once()
    threading.Thread(target=consume_events, daemon=True).start()
    threading.Thread(target=scan_pending, daemon=True).start()
    threading.Thread(target=liveness_loop, args=(0 if a.no_sweep else a.sweep_every,), daemon=True).start()
    threading.Thread(target=screen_loop, daemon=True).start()
    threading.Thread(target=rules_loop, daemon=True).start()
    if a.remote:
        threading.Thread(target=tunnel_loop, args=(a.port,), daemon=True).start()

    # --- federacion (plan multi-PC, ronda 2): listener de peers, espejo y beacon ----------------
    mirror.MIRROR.on_change = broadcast_mirror_snapshot
    peers_guardados = federation.list_peers(PEERS_FILE)
    peer_srv = None
    if a.peers or peers_guardados:
        peer_host = a.peer_host or _lan_ip()
        try:
            peer_srv = QuietServer((peer_host, a.peer_port), PeerHandler)
        except OSError as e:
            log(f"listener de peers: no se pudo tomar {peer_host}:{a.peer_port} ({e})")
        else:
            peer_srv.daemon_threads = True
            threading.Thread(target=peer_srv.serve_forever, daemon=True).start()
            log(f"listener de peers en http://{peer_host}:{a.peer_port}")
    for peer in peers_guardados:
        _connect_peer_from_record(peer)
    if peer_srv is not None:
        stop_beacon = threading.Event()
        beacon.start(a.peer_port, stop_beacon)
        threading.Thread(target=_beacon_sync_loop, args=(stop_beacon, beacon), daemon=True).start()

    srv.daemon_threads = True
    with lock:
        n_alive = sum(1 for s in sessions.values() if s.get("alive"))
        n_rules = sum(1 for r in rules.items if r.get("enabled"))
        n_links = len(links.items)
    log(
        f"lienzo-server en http://{a.host}:{a.port}  sesiones={len(sessions)} (vivas={n_alive}, purgadas={purged}"
        f" de mas de {STALE_SESSION_H} h, retituladas={retitled})  reglas_activas={n_rules}  links={n_links}"
        f"  login={'si' if auth.configured() else 'no'}  peers={len(peers_guardados)}"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
