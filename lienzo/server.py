#!/usr/bin/env python
"""lienzo-server: watcher de ~/.lienzo/events, registro de sesiones, cola de transcripciones,
liveness por PID, SSE y envio por inyeccion. Solo stdlib. Bind 127.0.0.1:7321.

    python server.py [--port 7321] [--no-sweep]
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
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
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth
import autoaprobar
import beacon
import browser_api
import federation
import health
import identity
import kill_agent
import launch
import mirror
import pairing
import pantalla_coda
import red
import remote_run
import restore
import rules as rl
import secretos
import state
import transcripts
import xfer
from beacon import DISCOVERED_TTL_S as BEACON_TTL_S
from rules import connections_of, purge_stale_at_rules, rules_loop

# la API de reglas (validar, alta y edicion) vive en rules_api.py; se reexporta lo que las pruebas
# todavia toman de `server` (find_enabled, at_fields, check_rule)
from rules_api import _known_session, at_fields, check_rule, create_rule, edit_rule, find_enabled  # noqa: F401
from sessions import (
    add_link,
    answer_coda_ask,
    answer_dialog,
    answer_pending,
    clean_attachments,
    coda_viva,
    consume_events,
    cuotas_de_sesiones,
    drop_session,
    hand_over,
    interrupt_session,
    liveness_loop,
    load_sessions,
    nombrar_nativo,
    public_pending,
    read_screen,
    remotes_de_sesiones,
    repo_de_remote,
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
from sessions import retarget_rules as ses_retarget_rules
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
    load_config,
    lock,
    log,
    now,
    pending,
    public_config,
    rules,
    sessions,
    set_config_key,
)

# --- federacion entre PCs (plan-multi-pc-2026-09-26.md, ronda 2) ----------------------------

PEERS_FILE = os.path.join(LIENZO, "peers.json")
PEER_SOCKET_TIMEOUT_S = 60.0  # una conexion de un par que no lee ni escribe en este tiempo se corta
RED_CADA_S = 10.0  # cada cuanto se mira si cambio la IP de LAN o la de Tailscale
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

# Las rutas que no piden login (revision 2026-10-04, 0.7): Handler._prepare las consulta ANTES de
# leer el cuerpo, asi un anonimo por el tunel recibe 401 sin que se lea un byte. Son las mismas
# que do_GET/do_POST atienden antes de su `if not self._authed()`; si se agrega una ahi, va aca
# tambien (y si no, cae del lado seguro: pide login). PUT y DELETE no tienen ninguna.
RUTAS_PUBLICAS = {
    ("GET", ()),  # la pagina
    ("GET", ("docs",)),  # la misma pagina, el front muestra la referencia
    ("GET", ("chrome",)),  # la vista remota conserva el login de App
    ("GET", ("favicon.svg",)),
    ("GET", ("health",)),
    ("GET", ("auth",)),
    ("GET", ("totp",)),  # se niega solo fuera de la PC
    ("GET", ("enroll",)),  # el token del alta es la credencial
    ("POST", ("login",)),
    ("POST", ("logout",)),
    ("POST", ("setup",)),  # se niega solo fuera de la PC
}
PREFIJOS_PUBLICOS = {("GET", "assets")}  # los estaticos del build: /assets/<nombre>


def es_publica(method: str, parts: list[str]) -> bool:
    if (method, tuple(parts)) in RUTAS_PUBLICAS:
        return True
    return len(parts) == 2 and (method, parts[0]) in PREFIJOS_PUBLICOS


def max_body(method: str, parts: list[str]) -> int:
    """El techo del cuerpo de un pedido: /attach sube archivos e imagenes y tiene el suyo."""
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "attach":
        return MAX_ATTACH
    return MAX_BODY


# --- HTTP ------------------------------------------------------------------------------


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


def _sin_firma(method: str, rest: list[str]) -> bool:
    """Las dos rutas del listener de peers que no van firmadas: son como se consigue la clave."""
    return (method == "GET" and rest == ["hello"]) or (method == "POST" and rest == ["pair"])


AVISO_401_S = 60.0  # el mismo motivo de la misma PC se loguea a lo sumo una vez por minuto
_avisos_401: dict[tuple[str, str], float] = {}
_avisos_401_lock = threading.Lock()


def _avisar_401(quien: str, motivo: str) -> None:
    """Loguea por que se rechazo un pedido de peer, con limite de frecuencia: un peer con el reloj
    corrido reintenta cada pocos segundos y llenaria el log con la misma linea."""
    ahora = time.monotonic()
    clave = (quien, motivo)
    with _avisos_401_lock:
        if ahora - _avisos_401.get(clave, -AVISO_401_S) < AVISO_401_S:
            return
        _avisos_401[clave] = ahora
        if len(_avisos_401) > 256:  # no crece sin limite con pc_id inventados
            _avisos_401.clear()
    log(f"peer {quien}: 401 ({motivo})")


def verify_peer_request(headers, method: str, path: str, body: bytes) -> str | None:
    """`pc_id` del peer verificado, o None (headers incompletos, peer desconocido, firma que no
    calza, fuera de ventana o nonce repetido: `federation.verify_motivo` cubre las cuatro).

    El motivo de cada rechazo va al log con limite de frecuencia (revision 2026-10-04, 1.8): un 401
    que decia solo «firma invalida» no distinguia reloj corrido, replay o clave distinta, que se
    arreglan distinto. Al cliente le sigue llegando «firma invalida» (federation le suma su pista)."""
    claimed = headers.get("X-Lienzo-Peer") or ""
    ts_raw = headers.get("X-Lienzo-Ts")
    nonce = headers.get("X-Lienzo-Nonce")
    sig = headers.get("X-Lienzo-Sig")
    if not claimed or not ts_raw or not nonce or not sig:
        _avisar_401(claimed or "?", "faltan headers de firma")
        return None
    key = _peer_key(claimed)
    if key is None:
        _avisar_401(claimed, "PC no emparejada")
        return None
    try:
        ts = float(ts_raw)
    except ValueError:
        _avisar_401(claimed, "X-Lienzo-Ts no es un numero")
        return None
    ok, motivo = federation.verify_motivo(key, method, path, body, ts, nonce, sig, _peer_nonces)
    if not ok:
        _avisar_401(claimed, motivo)
        return None
    return claimed


# La IP con la que el espejo esta conectado a cada peer, la que se le paso a mirror.connect. El
# beacon compara contra esto y no contra peers.json: beacon.py escribe la IP nueva en peers.json
# ANTES de que _beacon_sync_loop la mire, asi que esa comparacion siempre daba igual y el espejo
# seguia colgado de la IP vieja (segunda revision 2026-10-04).
_ip_conectada: dict[str, str] = {}
_ip_conectada_lock = threading.Lock()


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
    with _ip_conectada_lock:
        _ip_conectada[pc_id] = host
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


def fan_out(
    method: str, path: str, body: dict | None = None, *, pcs: list[str] | None = None
) -> tuple[dict[str, dict], dict[str, str]]:
    """Manda el mismo pedido a varias PCs (todas las conectadas, o `pcs`) a la vez y devuelve
    (ok, fallaron): {pc_id: cuerpo} de las que contestaron 200 y {pc_id: motivo} del resto.

    Revision 2026-10-04 (S14): retarget, auto-aprobar y restaurables repetian el mismo bucle y
    cada uno escondia las fallas a su manera (un 200 igual, un log, nada). Con esto el llamador
    tiene las fallas en la mano y las pone en la respuesta. En paralelo: una PC caida tarda lo que
    tarde su timeout, y antes eso se sumaba por cada PC."""
    destinos = mirror.MIRROR.peer_ids() if pcs is None else list(pcs)
    ok: dict[str, dict] = {}
    fallaron: dict[str, str] = {}

    def uno(pc: str) -> None:
        try:
            code, res = mirror.MIRROR.forward(pc, method, path, body)
        except Exception as e:  # forward ya convierte la red en 503; esto es un bug, que no corte a las demas
            log(f"fan_out {method} {path} a {pc}:\n{traceback.format_exc()}")
            code, res = 0, {"error": f"{type(e).__name__}"}
        if code == 200:
            ok[pc] = res if isinstance(res, dict) else {"body": res}
        else:
            motivo = (res or {}).get("error") if isinstance(res, dict) else None
            fallaron[pc] = str(motivo or f"HTTP {code}")

    hilos = [threading.Thread(target=uno, args=(pc,), daemon=True) for pc in destinos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return ok, fallaron


# auto-aprobar que no llego a una PC (caida o con error): {pc_id: valor que se quiso poner}. Se le
# vuelve a mandar cuando esa PC esta viva (reintentar_config_peers, cada CONFIG_REINTENTO_S): sin
# esto, una PC caida cuando se apago auto-aprobar quedaba prendida para siempre (revision
# 2026-10-04, 0.3). En disco porque el server se reinicia solo con cada cambio de codigo, y un
# pendiente en memoria se perdia justo en el caso que importa.
CONFIG_PENDIENTE_FILE = os.path.join(LIENZO, "config_pendiente.json")
CONFIG_REINTENTO_S = 5.0
_config_pendiente_lock = threading.Lock()  # tambien serializa las propagaciones: llegan en orden


def _leer_config_pendiente() -> dict[str, bool]:
    try:
        with open(CONFIG_PENDIENTE_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log(f"config pendiente para otras PCs ilegible ({type(e).__name__}: {e}); se descarta")
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, bool)} if isinstance(d, dict) else {}


def _guardar_config_pendiente(d: dict[str, bool]) -> None:
    try:
        tmp = CONFIG_PENDIENTE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, CONFIG_PENDIENTE_FILE)
    except OSError as e:
        log(f"no se pudo guardar el auto-aprobar pendiente para otras PCs: {e}")


def propagar_auto_aprobar(valor: bool, pcs: list[str] | None = None) -> dict[str, str]:
    """Pone auto-aprobar en `valor` en las otras PCs (todas, o `pcs`). Devuelve {pc_id: "ok" | motivo};
    las que fallaron quedan pendientes con ese valor y las que contestaron dejan de estarlo."""
    with _config_pendiente_lock:
        ok, fallaron = fan_out("PUT", "/config", {autoaprobar.CLAVE: valor}, pcs=pcs)
        pend = _leer_config_pendiente()
        for pc in ok:
            pend.pop(pc, None)
        for pc, motivo in fallaron.items():
            pend[pc] = valor
            log(f"auto-aprobar = {valor} no llego a {pc} ({motivo}); se reintenta cuando conteste")
        _guardar_config_pendiente(pend)
    return {**{pc: "ok" for pc in ok}, **fallaron}


def olvidar_config_pendiente(pc: str) -> None:
    """`pc` acaba de cambiar auto-aprobar por su cuenta (PUT /peer/config): su valor es mas nuevo que
    el pendiente de aca, que ya no se le manda."""
    with _config_pendiente_lock:
        pend = _leer_config_pendiente()
        if pend.pop(pc, None) is not None:
            _guardar_config_pendiente(pend)


def reintentar_config_peers() -> None:
    """Manda el auto-aprobar pendiente a las PCs que hoy estan vivas (recien conectadas, o que
    volvieron)."""
    vivos = {p["pc_id"] for p in mirror.MIRROR.peers_status() if p.get("alive")}
    with _config_pendiente_lock:
        pend = {pc: v for pc, v in _leer_config_pendiente().items() if pc in vivos}
    for valor in (False, True):
        pcs = [pc for pc, v in pend.items() if v is valor]
        if pcs:
            res = propagar_auto_aprobar(valor, pcs)
            log(f"auto-aprobar pendiente = {valor} reenviado: {res}")


def config_peers_loop(stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    while not stop_event.wait(CONFIG_REINTENTO_S):
        try:
            reintentar_config_peers()
        except Exception:
            log(f"reintento de auto-aprobar en otras PCs:\n{traceback.format_exc()}")


def registrar_envio(sid: str, d: dict) -> dict | None:
    """Despues de un envio que entro (200) a la tarjeta `sid`, deja la flecha en el historial segun
    como se pidio, y devuelve la tarjeta de origen si es local (para copycat), o None.

    Las tarjetas se leen con el lock tomado (revision 2026-10-04, S9): antes se miraba
    `src in sessions` sin el lock y despues `sessions[src]`; si el origen se borraba en el medio
    (el envio tarda hasta 60 s), KeyError y 500 con el texto ya tecleado. `sid` puede ser de
    otra PC (0.11): el origen o el destino del canal nativo valen si se conocen aca o en el espejo."""
    text = d.get("text", "") if isinstance(d.get("text"), str) else ""
    src, link_to = d.get("from"), d.get("link_to")
    kind = "native" if d.get("native") else "send"
    with lock:
        src_s = sessions.get(src) if isinstance(src, str) else None
        link_to_local = isinstance(link_to, str) and link_to in sessions
    if link_to and link_to != sid and (link_to_local or _known_session(link_to)):
        # canal nativo: se le habla a A para que abra conversacion con B; la flecha es A -> B
        add_link(sid, link_to, text, kind)
        return None
    if src and src != sid and (src_s is not None or _known_session(src)):
        add_link(src, sid, text, kind)
        return src_s
    if not src and not link_to:
        # lo que el usuario escribio desde el lienzo: queda en el historial de la sesion
        # (pestana Conexiones) como 'recibido de vos'; sin flecha
        add_link(None, sid, text, "user")
    return None


def huella_de_pantalla(lineas: list[str]) -> str | None:
    """La huella del comando del cartel de coda en `lineas`: la misma cuenta que arma el aprobador
    del skill (las dos salen de pantalla_coda), o None si no hay cartel."""
    return pantalla_coda.huella(lineas)


def aprobar_coda(s: dict, d: dict) -> tuple[int, dict]:
    """POST /sessions/<id>/approve, local o pedido por otra PC. `d` ya paso validar_approve.

    Con `expect` (sha256 hex del comando visible compacto, ver pantalla_coda.huella) se lee la
    pantalla y solo se teclea si el cartel sigue mostrando ESE comando; si no, 409. Antes el
    aprobador del skill miraba la pantalla, decidia y despues pedia aprobar: si en el medio el
    cartel cambio, el Enter aprobaba un comando que nadie habia juzgado (revision 2026-10-04,
    0.2). Sin `expect`, como siempre (el boton de la tarjeta).

    Esto ACHICA la ventana pero no la cierra: entre esta lectura y la tecla de answer_coda_ask
    (que vuelve a leer la pantalla) el cartel todavia puede cambiar. Cerrarla del todo pide que
    la misma lectura que confirma el dialogo sea la que se compara, adentro de sessions."""
    expect = d.get("expect")
    if expect is not None:  # su forma ya la miro validar_approve
        if not s.get("pid") or s.get("orphan"):
            return 409, {"ok": False, "error": "sin consola que leer"}
        actual = huella_de_pantalla(read_screen(s).get("lines") or [])
        if actual != expect:
            return 409, {"ok": False, "error": "el comando en pantalla cambió", "code": "expect_mismatch"}
    return answer_coda_ask(s, d["decision"])


def session_view_response(s: dict, view: str, query: dict) -> tuple[int, dict]:
    """Las cuatro vistas de una tarjeta (SESSION_VIEWS): screen, connections, turns, digest. La usan
    Handler._session_view (local) y PeerHandler (pedida por otra PC bajo demanda, §3.3)."""
    if view == "connections":
        return 200, connections_of(s["session_id"])
    if view == "screen":
        if not s.get("pid") or s.get("orphan"):
            return 409, {"ok": False, "error": "sin consola que leer"}
        return 200, read_screen(s)
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


def snapshot_json(*, con_espejo: bool) -> str:
    """El primer mensaje de un SSE y el que se reemite cuando cambia el espejo: `{"type":
    "snapshot", sessions, pending, links, rules, build}`. Con `con_espejo` (el tablero) lleva
    ademas lo de las otras PCs; sin el (lo que lee otra PC por /peer/events) solo lo de esta, para
    no reenviar en circulo en una malla de 3+ PCs.

    `_local_state` serializa con el lock tomado: `sessions.values()` son los dicts vivos, y armar
    el JSON afuera podia leer una tarjeta a medio escribir (o reventar si el dict cambia de
    tamaño). El espejo no necesita el lock: mirror.py tiene el suyo."""
    local = _local_state()
    estado = _with_mirror(local) if con_espejo else local
    return json.dumps({"type": "snapshot", **estado, "build": build_id()}, ensure_ascii=False)


def broadcast_mirror_snapshot() -> None:
    """El espejo cambio (un peer mando un evento, se cayo o volvio): se reemite un snapshot
    completo (local + espejo) solo a los clientes del tablero, para que una tarjeta remota se vea
    en vivo sin esperar el proximo `/sessions`. Es `mirror.MIRROR.on_change`."""
    _push_to_ui_clients(snapshot_json(con_espejo=True))


def reconcile_peer_rules(pc: str, remote_ids: set[str]) -> None:
    """Un peer sincronizado alcanza para conciliar sus reglas; otro apagado no lo frena."""
    with lock:
        changed = False
        for rule in rules.items:
            if rule.get("xpc") and rule.get("to") in remote_ids and rule.get("to_pc") != pc:
                rule["to_pc"] = pc
                changed = True
        if changed:
            rules.save()
        rl.purge_stale_xpc(
            known_remote=lambda sid: sid in remote_ids,
            known_local=lambda sid: sid in sessions,
            peer_id=pc,
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


# --- restaurar sesiones tras un reinicio (restore.py) --------------------------------------

RESTORE_GAP_S = 2.0  # entre un relanzado y el siguiente: no hundir la memoria con N agentes de golpe
_restore_busy = threading.Lock()


def restorables_local() -> list[dict]:
    """Las restaurables de esta PC: sin las que hoy tienen una tarjeta viva con ese id."""
    with lock:
        vivas = {sid for sid, s in sessions.items() if s.get("alive") and s.get("state") != "muerta"}
    pc = identity.pc_id()
    return [{**e, "pc": pc} for e in restore.restorables(live=vivas)]


def restorables_all() -> list[dict]:
    """Las restaurables de todas las PCs, sin decir cuales no contestaron (restorables_con_fallas)."""
    return restorables_con_fallas()[0]


def restorables_con_fallas() -> tuple[list[dict], list[str]]:
    """(restaurables, unreachable): de esta PC y de cada peer vivo (GET /peer/restaurables), cada
    una con su `pc`, y los pc_id que no se pudieron consultar (caidos o con error). Antes una PC
    que no contestaba simplemente no aparecia, igual que una sin nada para restaurar (S14)."""
    out = restorables_local()
    vivos, caidos = [], []
    for peer in mirror.MIRROR.peers_status():
        (vivos if peer.get("alive") else caidos).append(peer["pc_id"])
    ok, fallaron = fan_out("GET", "/restaurables", pcs=vivos)
    for pc, res in ok.items():
        out += [{**e, "pc": pc} for e in res.get("restaurables") or [] if isinstance(e, dict)]
    for pc, motivo in fallaron.items():
        log(f"restaurables de {pc}: {motivo}")
    orden = sorted(out, key=lambda e: str(e.get("ended_at") or e.get("saved_at") or ""), reverse=True)
    return orden, sorted(caidos + list(fallaron))


def restore_capacity(n: int) -> tuple[int, dict]:
    """(cuantos entran, snapshot) con la memoria libre de ahora, por la regla de health
    (agentes_que_entran). Sin dato de memoria entran todos (no se bloquea a ciegas)."""
    snap = health.snapshot()
    fit = health.agentes_que_entran(snap.get("mem_free_gb"))
    return (n if fit is None else min(n, fit)), snap


def restore_local(d: dict) -> tuple[int, dict]:
    """Relanza en ESTA PC una sesion (`session_id`) o todas (`all: true`), una por una con
    RESTORE_GAP_S entre cada una. Las relanzadas se olvidan del registro. `all` respeta la memoria:
    si no entran todas se rechaza diciendo cuantas si, o, con `limit_by_memory: true`, se relanzan
    solo esas."""
    sid, todas = d.get("session_id"), d.get("all") is True
    if todas == (sid is not None) or (sid is not None and (not isinstance(sid, str) or not sid)):
        return 400, {"error": "hace falta session_id, o all: true"}
    if not _restore_busy.acquire(blocking=False):
        return 409, {"error": "ya hay una restauracion en curso en esta PC"}
    try:
        items = restorables_local()
        extra = {}
        if todas:
            n = len(items)
            fit, snap = restore_capacity(n)
            if fit < n:
                msg = (
                    f"memoria libre {snap.get('mem_free_gb')} GB: de {n} sesiones entran {fit} "
                    f"(hacen falta {health.RESERVA_GB} GB + {health.GB_POR_AGENTE} GB por cada una)"
                )
                if d.get("limit_by_memory") is not True or fit == 0:
                    return 409, {"error": msg, "restorable": n, "fit": fit, "mem_free_gb": snap.get("mem_free_gb")}
                extra = {"skipped": [e["session_id"] for e in items[fit:]], "note": msg}
                items = items[:fit]
        else:
            items = [e for e in items if e["session_id"] == sid]
            if not items:
                return 404, {"error": "no hay una sesion restaurable con ese id"}
        restored, failed = [], []
        for i, e in enumerate(items):
            if i:
                time.sleep(RESTORE_GAP_S)
            try:
                res = launch.launch(e["cwd"], e.get("title") or e.get("repo") or "", e["agent"], resume=e["session_id"])
            except Exception:
                # el texto de la excepcion puede llevar rutas y nombres de la maquina, y esta
                # respuesta sale por el tunel: al cliente un id, al log el traceback con ese id
                # (revision 2026-10-04, S13; el mismo criterio que Handler._server_error)
                eid = secrets.token_hex(4)
                log(f"error {eid} al restaurar {e['session_id'][:8]}:\n{traceback.format_exc()}")
                res = {"ok": False, "error": f"error interno al relanzar ({eid})"}
            if res.get("ok"):
                restore.forget(e["session_id"])
                restored.append(
                    {"session_id": e["session_id"], "agent": e["agent"], "cwd": e["cwd"], "resumed": res.get("resumed")}
                )
                log(f"restaurar: {e['agent']} {e['session_id'][:8]} en {e['cwd']}")
            else:
                failed.append({"session_id": e["session_id"], "error": res.get("error") or "no se pudo lanzar"})
        return (400 if failed and not restored else 200), {"restored": restored, "failed": failed, **extra}
    finally:
        _restore_busy.release()


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


class NotAnObject(ValueError):
    """El cuerpo es JSON valido pero no un objeto."""


def no_session() -> dict:
    """Cuerpo del 404 de una tarjeta que no existe. `code` es el contrato (mirror.forward lo usa
    para detectar tarjetas fantasma); `error` es el texto para la persona."""
    return {"error": "sesion desconocida", "code": "unknown_session"}


def validate_launch(d: dict) -> tuple[str, str, str] | None:
    """(cwd, agent, title) de un pedido de lanzamiento, o None si no es valido: cwd str no vacio,
    agent str, title str (o ausente)."""
    cwd, agent, title = d.get("cwd"), d.get("agent"), d.get("title") or ""
    if not isinstance(cwd, str) or not cwd.strip() or not isinstance(agent, str) or not isinstance(title, str):
        return None
    return cwd, agent, title


def decode_json_body(raw: bytes) -> dict:
    """JSON del cuerpo tolerante a clientes que mandan latin-1 (un curl desde Git Bash). Cuerpo vacio:
    {}. Levanta ValueError si no es JSON o no es un objeto; cada llamador decide que hacer."""
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    d = json.loads(text)
    if not isinstance(d, dict):
        raise NotAnObject("el cuerpo debe ser un objeto JSON")
    return d


# --- acciones de tarjeta: una tabla para el tablero y para las otras PCs (ola 2) ---------------
#
# Antes cada accion estaba dos veces, en Handler y en PeerHandler, y las copias se separaron: las
# PUT validaban antes de buscar la tarjeta en un lado y despues en el otro, y PeerHandler buscaba
# la tarjeta antes de mirar si la accion existia (una accion que esa PC no conoce, sobre una
# tarjeta que ya no esta, daba unknown_session y no «ruta desconocida»). Ahora cada accion se
# define una vez y el orden es uno solo, el de `atender_accion`: validar el cuerpo -> ubicar la
# tarjeta (aca o en la PC duena) -> ejecutar o reenviar. Lo que distingue a los dos listeners es
# como llega el cuerpo (cada uno lo decodifica antes) y que solo el tablero reenvia.


def _rechazo(msg: str) -> tuple[int, dict]:
    return 400, {"error": msg}


def validar_title(d: dict) -> tuple[int, dict] | None:
    title = d.get("title")
    return _rechazo("title debe ser un texto") if title is not None and not isinstance(title, str) else None


def validar_on(d: dict) -> tuple[int, dict] | None:
    """La llave (stopped) y la coordinadora: `on` booleano."""
    return None if isinstance(d.get("on"), bool) else _rechazo("on debe ser true o false")


def accion_title(s: dict, d: dict) -> tuple[int, dict]:
    """PUT /sessions/<id>/title: titulo a mano. Vacio vuelve a la logica automatica."""
    set_title(s, d.get("title") or "")  # toma el lock por dentro; leer la transcripcion, no
    if not touch(s):
        # la borraron (o reemplazaron) mientras se leia la transcripcion: touch ya no la guarda
        # ni la publica, y contestar 200 diria que el titulo quedo (revision 2026-10-04, S10)
        return 404, no_session()
    log(f"titulo de {s['session_id'][:8]} -> {s['title']!r} ({s.get('title_source')})")
    return 200, {"ok": True, "title": s["title"], "title_source": s.get("title_source")}


def accion_stopped(s: dict, d: dict) -> tuple[int, dict]:
    """PUT /sessions/<id>/stopped: la llave. {on: true} la detiene (Esc si corre, aviso a sus
    conectadas, no recibe nada); {on: false} la habilita."""
    res = set_stopped(s, d["on"])
    return 200, {"ok": True, "stopped_by": s.get("stopped_by"), **res}


def accion_coordinator(s: dict, d: dict) -> tuple[int, dict]:
    """PUT /sessions/<id>/coordinator: una coordinadora del repo en toda la federacion."""
    changed = set_coordinator(s, d["on"])
    log(
        f"coordinadora de {s.get('repo')}: {s['session_id'][:8]} -> {d['on']} "
        f"({', '.join(x['session_id'][:8] for x in changed) or 'sin cambios'})"
    )
    return 200, {"ok": True, "coordinator": bool(s.get("coordinator"))}


def validar_coordinator(d: dict) -> tuple[int, dict] | None:
    if "scope" in d:
        return _rechazo("la coordinadora es del repo; no admite scope por PC")
    return validar_on(d)


def validar_send(d: dict) -> tuple[int, dict] | None:
    text, attachments = d.get("text", ""), d.get("attachments") or []
    if (
        not isinstance(text, str)
        or not isinstance(attachments, list)
        or any(not isinstance(a, str) for a in attachments)
    ):
        return _rechazo("text debe ser texto y attachments una lista de rutas")
    return None


def validar_decision(d: dict) -> tuple[int, dict] | None:
    """approve y /pending: allow o deny."""
    return None if d.get("decision") in ("allow", "deny") else _rechazo("decision debe ser allow o deny")


def validar_approve(d: dict) -> tuple[int, dict] | None:
    """La decision y, si viene, la forma de `expect` (la huella se compara en aprobar_coda, con la
    pantalla delante)."""
    rechazo = validar_decision(d)
    if rechazo is not None:
        return rechazo
    expect = d.get("expect")
    if expect is not None and (not isinstance(expect, str) or not re.fullmatch(r"[0-9a-f]{64}", expect)):
        return _rechazo("expect debe ser el sha256 hex del comando")
    return None


def validar_dialog(d: dict) -> tuple[int, dict] | None:
    choice = d.get("choice")
    ok = isinstance(choice, int) and not isinstance(choice, bool)
    return None if ok else _rechazo("choice debe ser el numero de la opcion")


def sin_validar(d: dict) -> None:
    return None


def accion_send(s: dict, d: dict) -> tuple[int, dict]:
    """POST /sessions/<id>/send: inyecta el texto en la consola. La flecha y copycat son del
    tablero (envio_del_tablero): la PC duena solo teclea."""
    return send_to_session(s, d.get("text", ""), d.get("attachments") or [])


def validar_native(d: dict) -> tuple[int, dict] | None:
    name = d.get("name")
    return _rechazo("name debe ser un texto") if name is not None and not isinstance(name, str) else None


def accion_native(s: dict, d: dict) -> tuple[int, dict]:
    """POST /sessions/<id>/native {name?}: la deja en el canal nativo (ListAgents y SendMessage, de
    esta PC y de las otras con la misma cuenta) con ese nombre, o el que sale de su titulo. Corre en
    la PC duena: teclea /rename y /remote-control y contesta el dialogo."""
    nombre = launch.nombre_corto(d.get("name") or s.get("title") or s.get("repo") or "")
    if not nombre:
        return 400, {"error": "sin titulo no hay de donde sacar un nombre: pasá name"}
    return nombrar_nativo(s, nombre)


def accion_interrupt(s: dict, d: dict) -> tuple[int, dict]:
    return interrupt_session(s)


def accion_kill(s: dict, d: dict) -> tuple[int, dict]:
    return kill_agent.close(s, d.get("confirm"))


def accion_approve(s: dict, d: dict) -> tuple[int, dict]:
    return aprobar_coda(s, d)


def accion_dialog(s: dict, d: dict) -> tuple[int, dict]:
    return answer_dialog(s, d["choice"])


def validar_attach(d: dict) -> tuple[int, dict] | None:
    """`d` es {filename, data} ya decodificado (crudo en el tablero, base64 entre PCs)."""
    return None if d.get("data") else _rechazo("cuerpo vacio")


def accion_attach(s: dict, d: dict) -> tuple[int, dict]:
    """POST /sessions/<id>/attach: guarda el archivo en ADJUNTOS/<sid>/ y devuelve su ruta, que
    despues viaja en `attachments` de un envio."""
    path = save_attachment(s["session_id"], d["filename"], d["data"])
    return 200, {"path": path, "bytes": len(d["data"])}


def reenvio_attach(d: dict) -> dict:
    """El adjunto entre PCs viaja como base64 adentro del JSON: no hay transporte binario en
    federation.HTTPTransport.request. Mas trafico, pero sin otro camino."""
    return {"filename": d["filename"], "data_b64": base64.b64encode(d["data"]).decode("ascii")}


def envio_del_tablero(sid: str, s: dict | None, d: dict, res: dict) -> None:
    """Despues de un envio del tablero que entro (200), local o reenviado: la flecha la deja la PC
    que envia, porque la duena no sabe de from/link_to (revision 2026-10-04, 0.11). Pegar trabajo
    (copycat) usa hand_over local o acciones reenviadas a la PC de cada tarjeta."""
    src_s = registrar_envio(sid, d)
    if s is not None and src_s is not None and d.get("copycat") is True:
        # pegar trabajo: la copia hereda el titulo; el origen se detiene salvo "Duplicar"
        res.update(hand_over(s, src_s, stop=d.get("stop_origin") is not False))
    elif d.get("copycat") is True:
        remote_hand_over(sid, src_s, d, res)


def remote_hand_over(sid: str, origin: dict | None, d: dict, res: dict) -> None:
    """El texto ya llego: un fallo de metadatos se informa sin volver a enviarlo."""
    origin = origin or next((s for s in mirror.MIRROR.sessions() if s["session_id"] == d.get("from")), None)
    if origin is None:
        res["handover_error"] = "el origen desaparecio; no se pudo terminar el traspaso"
        return
    payload = {"from": origin["session_id"], "title": origin.get("title") or origin.get("repo") or ""}
    code, out = atender_accion("PUT", sid, "copycat", payload, desde_tablero=True)
    if code != 200:
        res["handover_error"] = out.get("error") or "no se pudo titular el destino"
        return
    if d.get("stop_origin") is not False:
        code, out = atender_accion("PUT", origin["session_id"], "stopped", {"on": True}, desde_tablero=True)
        if code != 200:
            res["handover_error"] = out.get("error") or "no se pudo detener el origen"
            return
        res.update(out)


def validar_copycat(d: dict) -> tuple[int, dict] | None:
    if not isinstance(d.get("from"), str) or not d["from"] or not isinstance(d.get("title"), str):
        return _rechazo("copycat requiere from y title como texto")
    return None


def accion_copycat(s: dict, d: dict) -> tuple[int, dict]:
    with lock:
        s["copycat_of"] = d["from"]
        title = d["title"]
        set_title(s, title if title.endswith(" · copycat") else title + " · copycat")
        touch(s)
    return 200, {"ok": True}


@dataclass(frozen=True)
class AccionSesion:
    """Una accion sobre una tarjeta: `/sessions/<id>/<nombre>` en el tablero y
    `/peer/sessions/<id>/<nombre>` entre PCs.

    `validar(d)` da el rechazo (codigo, cuerpo) o None; `ejecutar(s, d)` es `accion_<nombre>`,
    sobre la tarjeta local y con `d` ya validado; `reenvio(d)` es el cuerpo que viaja a la PC duena
    (el formato de /peer/*, que no cambia); `cuerpo` dice como se lee el pedido: "json", "nada"
    (no se lee) o "adjunto" (crudo al tablero, en base64 entre PCs: ver los dos decodificadores);
    `antes_local_tablero` y `despues_tablero` son lo que solo hace el tablero."""

    validar: Callable[[dict], tuple[int, dict] | None]
    ejecutar: Callable[[dict, dict], tuple[int, dict]]
    reenvio: Callable[[dict], dict] = dict
    cuerpo: str = "json"
    # solo cuando lo pide el tablero: un rechazo antes de ejecutar en una tarjeta local, y lo que
    # se hace despues de un 200 (local o reenviado). Hoy, el canal nativo, la flecha y copycat.
    antes_local_tablero: Callable[[dict], tuple[int, dict] | None] | None = None
    despues_tablero: Callable[[str, dict | None, dict, dict], None] | None = None


ACCIONES_SESION: dict[tuple[str, str], AccionSesion] = {
    ("PUT", "copycat"): AccionSesion(validar_copycat, accion_copycat),
    ("POST", "kill"): AccionSesion(sin_validar, accion_kill),
    ("POST", "send"): AccionSesion(validar_send, accion_send, despues_tablero=envio_del_tablero),
    ("POST", "native"): AccionSesion(validar_native, accion_native),
    ("POST", "interrupt"): AccionSesion(sin_validar, accion_interrupt, reenvio=lambda d: {}, cuerpo="nada"),
    ("POST", "approve"): AccionSesion(validar_approve, accion_approve),
    ("POST", "dialog"): AccionSesion(validar_dialog, accion_dialog),
    ("POST", "attach"): AccionSesion(validar_attach, accion_attach, reenvio=reenvio_attach, cuerpo="adjunto"),
    ("PUT", "title"): AccionSesion(validar_title, accion_title, reenvio=lambda d: {"title": d.get("title")}),
    ("PUT", "stopped"): AccionSesion(validar_on, accion_stopped, reenvio=lambda d: {"on": d["on"]}),
    ("PUT", "coordinator"): AccionSesion(validar_coordinator, accion_coordinator),
}


def atender_accion(metodo: str, sid: str, nombre: str, d: dict, *, desde_tablero: bool) -> tuple[int, dict]:
    """La accion `nombre` sobre la tarjeta `sid`, con el cuerpo ya decodificado, en el orden fijo:
    validar -> ubicar -> ejecutar o reenviar. Desde el tablero una tarjeta de otra PC se le pide a
    su duena, y corren los pasos propios del tablero; lo que pide otra PC solo vale para la tarjeta
    local: reenviar de nuevo armaria rebotes en una malla de 3+ PCs."""
    a = ACCIONES_SESION[(metodo, nombre)]
    rechazo = a.validar(d)
    if rechazo is not None:
        return rechazo
    if desde_tablero:
        s, owner = _route_session(sid)
    else:
        with lock:
            s = sessions.get(sid)
        owner = None
    if owner is not None:
        code, res = mirror.MIRROR.forward(owner, metodo, f"/sessions/{sid}/{nombre}", a.reenvio(d))
    elif s is None:
        return 404, no_session()
    else:
        rechazo = a.antes_local_tablero(d) if desde_tablero and a.antes_local_tablero else None
        if rechazo is not None:
            return rechazo
        code, res = a.ejecutar(s, d)
    if desde_tablero and a.despues_tablero and code == 200:
        a.despues_tablero(sid, s, d, res)
    return code, res


# Las acciones que no son de una tarjeta pero tambien estaban en los dos listeners: un pedido de
# permiso, lanzar, reapuntar reglas y restaurar. Mismo orden (validar -> ubicar la PC -> ejecutar o
# reenviar) y mismo criterio: solo el tablero reenvia; lo que pide otra PC se hace aca.


def accion_pending(request_id: str, d: dict, *, desde_tablero: bool) -> tuple[int, dict]:
    """POST /pending/<id>: contesta un pedido de permiso (o pregunta). Desde el tablero, el de otra
    PC se reenvia a la suya."""
    rechazo = validar_decision(d)
    if rechazo is not None:
        return rechazo
    owner = _pending_owner(request_id) if desde_tablero else None
    if owner is not None:
        return mirror.MIRROR.forward(owner, "POST", f"/pending/{request_id}", d)
    return answer_pending(request_id, d["decision"], d.get("reason", ""), d.get("answers"))


def accion_launch(d: dict, *, desde_tablero: bool) -> tuple[int, dict]:
    """POST /sessions/launch {pc, cwd, title, agent, model?} en el tablero (local con launch.launch,
    o reenviada a la PC `pc` por /peer/launch) y POST /peer/launch (siempre local)."""
    valid = validate_launch(d)
    if valid is None:
        return 400, {"error": "cwd y agent son obligatorios"}
    cwd, agent, title = valid
    model = d.get("model") if isinstance(d.get("model"), str) else None
    pc = d.get("pc")
    if desde_tablero and pc and pc != identity.pc_id():
        cuerpo = {"cwd": cwd, "title": title, "agent": agent, **({"model": model} if model else {})}
        return mirror.MIRROR.forward(pc, "POST", "/launch", cuerpo)
    res = launch.launch(cwd, title, agent, model=model)
    if res.get("ok"):
        return 200, res
    # launch dice su codigo cuando no es un pedido mal hecho (409: coda sin cuota en esta PC)
    codigo = res.pop("code", None)
    return (codigo if isinstance(codigo, int) and 400 <= codigo < 600 else 400), res


def accion_retarget(d: dict, *, desde_tablero: bool) -> tuple[int, dict]:
    """POST /rules/retarget {old, new}: las reglas que avisaban a `old` pasan a `new`. Desde el
    tablero, aca y en las otras PCs; lo que pide otra PC, solo aca."""
    if not isinstance(d.get("old"), str) or not isinstance(d.get("new"), str):
        return 400, {"error": "hace falta old y new"}
    n = ses_retarget_rules(d["old"], d["new"])
    if not desde_tablero:
        return 200, {"ok": True, "n": n}
    ok, fallaron = fan_out("POST", "/rules/retarget", d)
    n += sum(int(res.get("n") or 0) for res in ok.values())
    # las PCs que no contestaron: sus reglas siguen apuntando a `old` (S14)
    return 200, {"ok": True, "n": n, "unreachable": sorted(fallaron)}


def accion_restaurar(d: dict, *, desde_tablero: bool) -> tuple[int, dict]:
    """POST /restaurar {session_id | all: true, pc?, limit_by_memory?}: local con restore_local, o
    desde el tablero reenviada a la PC `pc` por /peer/restaurar."""
    pc = d.get("pc")
    if pc is not None and not isinstance(pc, str):
        return 400, {"error": "pc debe ser un pc_id"}
    if desde_tablero and pc and pc != identity.pc_id():
        cuerpo = {k: d[k] for k in ("session_id", "all", "limit_by_memory") if k in d}
        return mirror.MIRROR.forward(pc, "POST", "/restaurar", cuerpo)
    return restore_local(d)


class JsonHandler(BaseHTTPRequestHandler):
    """Lo que comparten el tablero (Handler) y el listener de peers (PeerHandler): contestar JSON,
    leer el cuerpo con techo y el 500 con un id. Antes estaba dos veces, y las copias se habian
    separado: el 500 de PeerHandler no traia `error_id` ni se callaba ante una desconexion."""

    protocol_version = "HTTP/1.1"
    # Mouse y teclado necesitan respuestas pequeñas sin esperar a juntar paquetes TCP.
    disable_nagle_algorithm = True
    # cierra un socket que no manda nada en 30 s (slow-loris, hallazgo A3 del pentest): un cuerpo
    # declarado y no enviado retenia el hilo para siempre. El SSE escribe un latido cada 15 s, asi
    # que las conexiones /events largas no lo alcanzan.
    timeout = 30
    LOG_PREFIJO = ""  # "peer " en PeerHandler: de cual de los dos listeners salio el error

    def log_message(self, fmt, *args):  # silencio; el log propio alcanza
        pass

    def _server_error(self, e: BaseException) -> None:
        """Final de todos los pedidos: si el cliente cerro la conexion a mitad de la respuesta no
        hay a quien contestar. Un RequestError es la respuesta al cliente. Cualquier otra excepcion
        va entera al log con un id corto, y al cliente le llega ese id y nada mas: str(e) podia
        llevar rutas y nombres de la maquina, y por el tunel eso sale hacia afuera. El id esta en
        las dos puntas para poder cruzarlas."""
        if is_disconnect(e):
            return
        if isinstance(e, RequestError):
            return self._json(e.status, {"error": str(e)})
        eid = secrets.token_hex(4)
        log(f"error {eid} en {self.LOG_PREFIJO}{self.command} {self.path}:\n{traceback.format_exc()}")
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
        if self.close_connection:
            self.send_header("Connection", "close")  # que el cliente no reuse un socket que se cierra
        self.end_headers()
        self.wfile.write(body)

    def _largo_declarado(self) -> int:
        """El Content-Length del pedido, validado ANTES de leer nada: uno solo, solo digitos, y sin
        Transfer-Encoding (no se lee chunked). Si no, RequestError y la conexion se cierra: el
        cuerpo queda sin leer en el socket."""
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0].strip() if len(lengths) == 1 else "0"
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1 or not re.fullmatch(r"[0-9]{1,20}", length):
            self.close_connection = True
            raise RequestError("Content-Length invalido o Transfer-Encoding no soportado")
        return int(length)

    def _exigir_techo(self, n: int, techo: int) -> None:
        """413 sin leer un byte si el cuerpo declarado pasa el techo (hallazgo A3 del pentest)."""
        if n > techo:
            self.close_connection = True
            raise RequestError("cuerpo demasiado grande", 413)

    def _leer_cuerpo(self, n: int) -> bytes:
        """Lee exactamente `n` bytes. Si un rechazo temprano deja el cuerpo sin leer en el socket,
        el siguiente pedido de la misma conexion keep-alive lo tomaria como linea de pedido y
        contestaria 501: por eso todo rechazo antes de leer cierra la conexion."""
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:
            self.close_connection = True
            raise RequestError("cuerpo incompleto")
        return raw

    def _decodificar_json(self, raw: bytes) -> dict:
        """El cuerpo como objeto JSON, tolerante a latin-1 (un curl desde Git Bash), o RequestError
        400: un JSON roto no se toma como `{}` (revision 2026-10-04, S8: un envio con el cuerpo
        cortado tecleaba un Enter vacio en la consola)."""
        try:
            return decode_json_body(raw)
        except NotAnObject as e:
            raise RequestError("el cuerpo debe ser un objeto JSON") from e
        except ValueError as e:
            raise RequestError("JSON invalido") from e


class Handler(JsonHandler):
    server_version = "lienzo/0.1"

    def _route(self, read: bool = True) -> list[str]:
        """Primera linea de cada do_*, antes de decidir nada. Parte la ruta (devuelve los tramos de
        la URL, que es con lo que cada handler elige, y deja la query en `self.query`) y valida el
        Content-Length. Con `read=False` no lee el cuerpo: `_prepare` lo lee con `_read_body`
        recien despues de autenticar."""
        u = urllib.parse.urlparse(self.path)
        self.query = urllib.parse.parse_qs(u.query)
        self.query_string = u.query  # para reenviar una vista remota (§3.3) con los mismos n/before
        parts = [p for p in u.path.split("/") if p]
        self._length = self._largo_declarado()
        self._exigir_techo(self._length, max_body(getattr(self, "command", ""), parts))
        if read:
            self._read_body()
        return parts

    def _read_body(self) -> None:
        """Lee el cuerpo ya validado por `_route`; lo deja en `self.raw`."""
        self.raw = self._leer_cuerpo(self._length)

    def _prepare(self, *, write: bool = False, authenticated: bool = False) -> list[str] | None:
        """Mismos limites, Host, login y CSRF para todos los metodos; None si ya se rechazo.

        El login se mira ANTES de leer el cuerpo (revision 2026-10-04, 0.7): antes se leian hasta
        8 MB (64 MB en /attach) de un anonimo por el tunel y recien despues se le decia 401. Que
        ruta es publica sale de RUTAS_PUBLICAS (es_publica); las demas exigen `_authed`, que para
        la propia PC y la LAN es siempre True (el cambio solo toca lo que entra por el tunel).
        `authenticated` queda por compatibilidad: PUT y DELETE no tienen rutas publicas."""
        self.raw = None
        try:
            parts = self._route(read=False)
            if (authenticated or not es_publica(self.command, parts)) and not self._authed():
                raise RequestError("hace falta iniciar sesion", 401)
            # Host y CSRF despues de leer: un 400/403 deja la conexion keep-alive usable, como antes
            self._read_body()
            if not self._host_ok():
                raise RequestError("Host no valido")
            if write and not self._csrf_ok():
                raise RequestError("falta X-Lienzo o el Origin no es propio", 403)
            return parts
        except Exception as e:
            if self.raw is None:
                self.close_connection = True  # el cuerpo quedo en el socket: no se reusa la conexion
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

    def _json_body(self) -> dict:
        return self._decodificar_json(self.raw)

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
            if not parts or parts in (["docs"], ["chrome"]):
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
            if parts == ["restaurables"]:
                # el cuerpo sigue siendo la lista (contrato con el front y con coordinar.py); las PCs
                # que no contestaron van en un header, para no confundirlas con «no hay nada» (S14)
                lista, caidas = restorables_con_fallas()
                return self._json(200, lista, {"X-Lienzo-Unreachable": ",".join(caidas)} if caidas else None)
            if parts == ["secrets"]:
                # solo nombres y vencimientos: el valor no sale nunca por un listado. ?pc= lista los de esa PC
                pc = (self.query.get("pc") or [""])[0]
                if pc and pc != identity.pc_info()["pc_id"]:
                    code, res = mirror.MIRROR.forward(pc, "GET", "/secrets")
                    return self._json(code, res)
                return self._json(200, {"secrets": secretos.BOVEDA.pendientes()})
            if len(parts) == 2 and parts[0] == "secrets":
                return self._secret_take(parts[1])
            if parts == ["salud"]:
                return self._json(200, salud())
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
            if parts == ["xfer"]:
                return self._json(200, xfer.todos())
            if len(parts) == 2 and parts[0] == "xfer":
                code, res = xfer.ver(parts[1])
                return self._json(code, res)
            if parts == ["peers", "lan"]:
                return self._get_peers_lan()
            if parts == ["pending"]:
                return self._json(200, public_pending() + mirror.MIRROR.pending())
            if parts == ["links"]:
                return self._json(200, links.snapshot())
            if parts == ["rules"]:
                # las locales y las que viven en otras PCs (espejo, con su `pc`): un cliente de la API
                # que solo viera las locales creeria que el cableado entre PCs no existe
                return self._json(200, rules.snapshot() + mirror.MIRROR.rules())
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
            return self._json(404, no_session())
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
            if parts == ["browser"]:
                if self._via_tunnel() or not self._is_local():
                    return self._json(403, {"error": "Chrome remoto se maneja desde la PC de Lienzo"})
                code, res = browser_api.dispatch(self._json_body())
                return self._json(code, res)
            if parts == ["rescan"]:
                threading.Thread(target=sweep_once, daemon=True).start()
                return self._json(202, {"ok": True})
            if parts == ["xfer"]:
                # copiar a otra PC (xfer.py): {pc, origen, destino, bs_mib?, hilos?, mbps?, disco_mbps?, espejo?}
                code, res = xfer.nuevo(self._json_body(), identity.pc_id())
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "xfer" and parts[2] in ("retomar", "confirmar"):
                code, res = xfer.retomar(parts[1], confirmar=parts[2] == "confirmar")
                return self._json(code, res)
            if parts == ["restart"]:
                # {pc?}: esta PC o la PC `pc` (por /peer/restart, firmado). Solo desde la LAN
                if self._via_tunnel() or not self._is_local():
                    return self._json(403, {"error": "reiniciar solo desde una PC de la LAN"})
                pc = self._json_body().get("pc")
                if pc and pc != identity.pc_id():
                    code, res = mirror.MIRROR.forward(pc, "POST", "/restart", {})
                    return self._json(code, res)
                code, res = reiniciar()
                return self._json(code, res)
            if parts == ["secrets"]:
                return self._secret_send()
            if parts == ["rules"]:
                code, res = create_rule(self._json_body())
                return self._json(code, res)
            if parts == ["rules", "retarget"]:
                # a mano: las reglas que avisaban a `old` pasan a `new`, aca y en las otras PCs
                code, res = accion_retarget(self._json_body(), desde_tablero=True)
                return self._json(code, res)
            if parts == ["peers", "offer"]:
                return self._peers_offer()
            if parts == ["peers", "join"]:
                return self._peers_join()
            if parts == ["sessions", "launch"]:
                code, res = accion_launch(self._json_body(), desde_tablero=True)
                return self._json(code, res)
            if parts == ["restaurar"]:
                return self._restaurar()
            if parts == ["run"]:
                d = self._json_body()
                pc = d.pop("pc", None)
                if not isinstance(pc, str) or pc not in mirror.MIRROR.peer_ids():
                    return self._json(400, {"error": "run requiere una PC emparejada como destino"})
                code, res = mirror.MIRROR.forward(pc, "POST", "/run", d, timeout=60)
                return self._json(code, res)
            if len(parts) == 2 and parts[0] == "pending":
                code, res = accion_pending(parts[1], self._json_body(), desde_tablero=True)
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "sessions" and ("POST", parts[2]) in ACCIONES_SESION:
                return self._accion_sesion("POST", parts[1], parts[2])
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _secret_take(self, sid: str) -> None:
        """Lee UNA vez un secreto de destino memoria. Desde esta PC o cualquiera de la LAN (no por
        el tunel). Con `?pc=<pc_id>` lo pide a esa PC: viaja cifrado con la clave del par y se
        descifra aca. Despues de leerlo no existe mas en ningun lado."""
        if self._via_tunnel() or not self._is_local():
            return self._json(403, {"error": "un secreto solo se lee desde las PCs de la LAN"})
        pc = (self.query.get("pc") or [""])[0]
        if pc and pc != identity.pc_info()["pc_id"]:
            key = _peer_key(pc)
            if key is None:
                return self._json(404, {"error": f"no hay una PC emparejada {pc}"})
            code, res = mirror.MIRROR.forward(pc, "GET", f"/secrets/{sid}")
            if code != 200:
                return self._json(code, res)
            try:
                valor = secretos.descifrar(key, res.get("cifrado") or {})
            except ValueError as e:
                return self._json(502, {"error": str(e)})
            return self._json(200, {"nombre": res.get("nombre"), "valor": valor, "pc": pc})
        item = secretos.BOVEDA.tomar(sid)
        if item is None:
            return self._json(404, {"error": "no existe, ya se leyo o vencio"})
        log(f"secreto «{item[0]}» leido y borrado")
        return self._json(200, {"nombre": item[0], "valor": item[1]})

    def _secret_send(self) -> None:
        """POST /secrets {pc, nombre, destino, valor | desde: "git_local", git_url?, usuario?}: lo aplica
        en esta PC o lo manda CIFRADO a la PC `pc` (mirror.forward no loguea cuerpos). Con
        `desde: "git_local"` el valor sale del almacen de credenciales de esta PC. La respuesta nunca
        trae el valor."""
        d = self._json_body()
        if d.get("desde") == "git_local" and d.get("destino") == "git":
            # la credencial que esta PC ya tiene para ese host: el agente que lo pide nunca la ve
            cred = secretos.leer_git_local(str(d.get("git_url") or ""))
            if cred is None:
                return self._json(
                    404,
                    {
                        "error": "no se pudo leer la credencial de git de esta PC sin abrir una ventana de login (no hay, o vencio: un git fetch aca la renueva)"
                    },
                )
            d = {**d, "usuario": d.get("usuario") or cred[0], "valor": cred[1]}
        if motivo := secretos.validar(d):
            return self._json(400, {"error": motivo})
        valor = d.get("valor")
        if not isinstance(valor, str):
            return self._json(400, {"error": "valor: texto"})
        pc = d.get("pc") or identity.pc_info()["pc_id"]
        meta = {k: d.get(k) for k in ("nombre", "destino", "git_url", "usuario")}
        if pc == identity.pc_info()["pc_id"]:
            log(f"secreto «{meta['nombre']}» ({meta['destino']}) aplicado en esta PC")
            code, res = secretos.recibir(meta, valor)
            return self._json(code, res)
        key = _peer_key(pc)
        if key is None:
            return self._json(404, {"error": f"no hay una PC emparejada {pc}"})
        log(f"secreto «{meta['nombre']}» ({meta['destino']}) enviado cifrado a {pc}")
        code, res = mirror.MIRROR.forward(pc, "POST", "/secrets", {**meta, "cifrado": secretos.cifrar(key, valor)})
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

    def do_PUT(self):
        parts = self._prepare(write=True, authenticated=True)
        if parts is None:
            return
        try:
            if parts == ["config"]:
                return self._put_config()
            if parts == ["peers", "self"]:
                return self._put_peer_self()
            if len(parts) == 3 and parts[0] == "sessions" and ("PUT", parts[2]) in ACCIONES_SESION:
                return self._accion_sesion("PUT", parts[1], parts[2])
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
        if autoaprobar.CLAVE in d and (self._via_tunnel() or not self._is_local()):
            # aprobar todo sin mirar solo se prende desde la LAN, nunca por el tunel
            return self._json(403, {"error": "auto-aprobar solo se cambia desde una PC de la LAN"})
        for k, v in d.items():
            set_config_key(k, v)
            log(f"config: {k} = {v} (desde la UI, {self._client_ip()})")
        if autoaprobar.CLAVE not in d:
            return self._json(200, public_config())
        # «aprueba todo» vale para todas las PCs emparejadas, no solo para esta. Antes la falla en
        # otra PC iba solo al log y la UI mostraba el valor nuevo como si valiera en todas: apagar
        # auto-aprobar podia dejarlo prendido en una PC caida (revision 2026-10-04, 0.3). Ahora la
        # respuesta dice PC por PC, y las que fallaron quedan pendientes: se les vuelve a mandar
        # cuando contestan (reintentar_config_peers).
        return self._json(200, {**public_config(), "peers": propagar_auto_aprobar(d[autoaprobar.CLAVE])})

    def _cuerpo_accion(self, a: AccionSesion) -> dict:
        """El cuerpo de una accion de tarjeta tal como llega al tablero: JSON, nada, o el adjunto
        crudo con el nombre en X-Filename."""
        if a.cuerpo == "nada":
            return {}
        if a.cuerpo == "adjunto":
            return {"filename": urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin"), "data": self.raw}
        return self._json_body()

    def _accion_sesion(self, metodo: str, sid: str, nombre: str) -> None:
        """/sessions/<id>/<nombre>: decodifica el cuerpo y deja el resto a atender_accion (la misma
        que usa PeerHandler); la tarjeta de otra PC se reenvia a su duena (plan §3.4)."""
        d = self._cuerpo_accion(ACCIONES_SESION[(metodo, nombre)])
        code, res = atender_accion(metodo, sid, nombre, d, desde_tablero=True)
        return self._json(code, res)

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
        # la clave del par no sale nunca del server: se guarda en peers.json y nada mas (medido el
        # 2026-10-04: la respuesta la traia en claro y quedo en la salida de quien emparejo)
        return self._json(200, {k: v for k, v in peer.items() if k != "key"})

    def _restaurar(self) -> None:
        """POST /restaurar: accion_restaurar, que desde el tablero puede reenviar a la PC `pc`."""
        code, res = accion_restaurar(self._json_body(), desde_tablero=True)
        return self._json(code, res)

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
                # borrada a mano: tampoco se restaura. Si la tarjeta ya no estaba, drop_session no
                # llega a restore_on_drop y hay que olvidarla aca
                if not drop_session(sid, "borrada desde la UI"):
                    restore.forget(sid)
                return self._json(200, {"ok": True})
            if len(parts) == 2 and parts[0] == "peers":
                return self._delete_peer(parts[1])
            if len(parts) == 2 and parts[0] == "xfer":
                code, res = xfer.pausar(parts[1])  # pausa: POST /xfer/<id>/retomar sigue desde ahi
                return self._json(code, res)
            if len(parts) == 2 and parts[0] == "rules" and not any(r["id"] == parts[1] for r in rules.snapshot()):
                dueña = mirror.MIRROR.rule_owner(parts[1])
                if dueña:
                    log(f"regla {parts[1]} borrada desde la UI, vive en otra PC ({self._client_ip()})")
                    code, res = mirror.MIRROR.forward(dueña, "DELETE", f"/rules/{parts[1]}")
                    return self._json(code, res)
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
        try:
            removed = federation.remove_peer(PEERS_FILE, pc_id)
        except OSError as e:
            # peers.json existe y no se pudo leer (federation ya no lo pisa): no se olvida nada y
            # el espejo sigue como estaba, para no quedar a medias
            log(f"peer {pc_id}: no se pudo revocar ({e})")
            return self._json(409, {"error": "no se pudo leer peers.json (ver el log): la PC sigue emparejada"})
        mirror.MIRROR.disconnect(pc_id)
        with _ip_conectada_lock:
            _ip_conectada.pop(pc_id, None)
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
        # `ui_clients`: ademas de la verdad local (`clients`, como siempre) este stream recibe el
        # snapshot repetido cada vez que el espejo cambia (broadcast_mirror_snapshot); un peer que
        # se conecta a /peer/events NO se registra ahi (ver PeerHandler._events).
        _stream_sse(self, snapshot_json(con_espejo=True), [ui_clients])


# --- listener de peers: --peer-port, solo /peer/* (plan §3.2, §3.3, §3.4) -----------------------


class PeerHandler(JsonHandler):
    """El segundo listener, bind a la IP de LAN: solo atiende /peer/*, todo firmado salvo
    GET /peer/hello y POST /peer/pair (que son, justamente, como se consigue la clave para firmar
    lo demas). Ejecuta los mismos comandos que Handler pero siempre sobre la sesion LOCAL de esta
    PC: es lo que Handler reenvia cuando `owner_of(sid)` da otra PC, y lo que mirror.py lee para
    armar el espejo."""

    server_version = "lienzo-peer/0.1"
    LOG_PREFIJO = "peer "
    # timeout de cada lectura y escritura del socket (StreamRequestHandler.setup): un par que se
    # fue a mitad de un pedido, o que dejo de leer su /peer/events por un cambio de red, no deja un
    # hilo esperando para siempre. El SSE manda un ping cada 15 s, asi que esto sobra para el vivo.
    timeout = PEER_SOCKET_TIMEOUT_S

    def _parts_and_body(self, method: str) -> tuple[list[str], bytes] | None:
        """Ruta partida y cuerpo leido, con los mismos limites que Handler._route (Content-Length
        exacto, sin Transfer-Encoding). None (ya contestado) si algo no cierra.

        La firma cubre el cuerpo, asi que no se puede verificar sin leerlo; pero ANTES de leer se
        exige lo que si se puede mirar: los cuatro headers de firma y que `X-Lienzo-Peer` sea una
        PC emparejada. Si no, 401 y se cierra sin leer: antes cualquier equipo de la LAN mandaba
        hasta 64 MB sin firma y se leian enteros (revision 2026-10-04, 0.7 y segunda revision).
        Las rutas sin firma (hello, pair) leen como maximo MAX_BODY; MAX_ATTACH solo con un peer
        conocido."""
        u = urllib.parse.urlparse(self.path)
        self.query = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        try:
            n = self._largo_declarado()
            rest = parts[1:] if parts[:1] == ["peer"] else None
            sin_firma = rest is not None and _sin_firma(method, rest)
            if rest is not None and not sin_firma:
                claimed = self.headers.get("X-Lienzo-Peer") or ""
                completos = all(self.headers.get(h) for h in ("X-Lienzo-Ts", "X-Lienzo-Nonce", "X-Lienzo-Sig"))
                if not claimed or not completos or _peer_key(claimed) is None:
                    _avisar_401(claimed or self.client_address[0], "sin headers de firma o PC no emparejada")
                    self.close_connection = True
                    raise RequestError("firma invalida", 401)
            firmada = rest is not None and not sin_firma
            if firmada and rest[:1] == ["xfer"]:
                techo = xfer.MAX_CUERPO  # un bloque de copia entre PCs (xfer.py), ya con un peer conocido
            elif firmada and parts[-1:] == ["attach"]:
                techo = MAX_ATTACH
            else:
                techo = MAX_BODY
            self._exigir_techo(n, techo)
            return parts, self._leer_cuerpo(n)
        except RequestError as e:
            self.close_connection = True  # el cuerpo quedo sin leer (o a medias) en el socket
            self._json(e.status, {"error": str(e)})
            return None

    def _body_json(self, raw: bytes) -> dict:
        return self._decodificar_json(raw)

    def _dispatch(self, method: str) -> None:
        got = self._parts_and_body(method)
        if got is None:
            return
        parts, raw = got
        if not parts or parts[0] != "peer":
            return self._json(404, {"error": "ruta desconocida"})
        rest = parts[1:]
        path = urllib.parse.urlparse(self.path).path
        sin_firma = _sin_firma(method, rest)
        pc_id = None
        if not sin_firma:
            pc_id = verify_peer_request(self.headers, method, path, raw)
            if pc_id is None:
                return self._json(401, {"error": "firma invalida"})
        try:
            self._route(method, rest, raw, pc_id)
        except Exception as e:
            self._server_error(e)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _route(self, method: str, rest: list[str], raw: bytes, pc_id: str | None) -> None:
        if method == "POST" and rest == ["browser"]:
            code, res = browser_api.from_peer(self._body_json(raw), _peer_key(pc_id))
            return self._json(code, res)
        if method == "POST" and rest[:1] == ["xfer"]:
            # copia entre PCs (xfer.py): miles de pedidos por trabajo, no van uno por uno al log
            code, res = xfer.atender_peer(rest[1:], raw)
            if code >= 400:
                log(f"peer POST /peer/{'/'.join(rest)} de {pc_id}: {code} {res.get('error')}")
            return self._json(code, res)
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
        if method == "POST" and rest == ["run"]:
            code, res = remote_run.run(self._body_json(raw), pc_id)
            return self._json(code, res)
        if method == "GET" and rest == ["events"]:
            return self._events()
        if method == "POST" and rest == ["launch"]:
            code, res = accion_launch(self._body_json(raw), desde_tablero=False)
            return self._json(code, res)
        if method == "POST" and rest == ["rules"]:
            d = self._body_json(raw)
            if d.get("kind") == "on_stop" and d.get("from") not in sessions:
                # la regla de otra PC se crea donde ocurre el Stop: si el origen no es de esta PC, no va
                return self._json(409, {"error": "el origen de esa regla no es una sesion de esta PC"})
            code, res = create_rule(d)
            return self._json(code, res)
        if method == "GET" and rest == ["restaurables"]:
            return self._json(200, {"restaurables": restorables_local()})
        if method == "POST" and rest == ["restart"]:
            log(f"reinicio pedido por {pc_id}")
            code, res = reiniciar()
            return self._json(code, res)
        if method == "POST" and rest == ["secrets"]:
            return self._secret_receive(raw, pc_id)
        if method == "GET" and rest == ["secrets"]:
            return self._json(200, {"secrets": secretos.BOVEDA.pendientes()})
        if method == "GET" and len(rest) == 2 and rest[0] == "secrets":
            # otra PC lo lee: sale cifrado con la clave de ESE par y se borra de aca
            key = _peer_key(pc_id or "")
            item = secretos.BOVEDA.tomar(rest[1]) if key else None
            if item is None:
                return self._json(404, {"error": "no existe, ya se leyo o vencio"})
            log(f"secreto «{item[0]}» leido desde {pc_id} y borrado")
            return self._json(200, {"nombre": item[0], "cifrado": secretos.cifrar(key, item[1])})
        if method == "POST" and rest == ["restaurar"]:
            code, res = accion_restaurar(self._body_json(raw), desde_tablero=False)
            return self._json(code, res)
        if method == "PUT" and rest == ["config"]:
            # otra PC emparejada prende o apaga auto-aprobar aca (el check del menu vale para todas)
            d = self._body_json(raw)
            if set(d) != {autoaprobar.CLAVE} or not isinstance(d[autoaprobar.CLAVE], bool):
                return self._json(400, {"error": f"solo {autoaprobar.CLAVE} (true o false)"})
            set_config_key(autoaprobar.CLAVE, d[autoaprobar.CLAVE])
            olvidar_config_pendiente(pc_id or "")
            log(f"config: {autoaprobar.CLAVE} = {d[autoaprobar.CLAVE]} (desde {pc_id})")
            return self._json(200, public_config())
        if method == "POST" and rest == ["rules", "retarget"]:
            code, res = accion_retarget(self._body_json(raw), desde_tablero=False)
            return self._json(code, res)
        if method == "POST" and rest == ["rules", "lock"]:
            return self._rules_lock(raw)
        if method == "POST" and rest == ["rules", "check"]:
            return self._rules_check(raw)
        if len(rest) == 3 and rest[0] == "sessions" and method == "GET" and rest[2] in SESSION_VIEWS:
            return self._session_view(rest[1], rest[2])
        if len(rest) == 3 and rest[0] == "sessions" and method == "POST":
            return self._accion_sesion(method, rest[1], rest[2], raw)
        if len(rest) == 3 and rest[0] == "sessions" and method == "PUT":
            return self._accion_sesion(method, rest[1], rest[2], raw)
        if len(rest) == 2 and rest[0] == "rules" and method == "DELETE":
            rules.remove(lambda x: x["id"] == rest[1])
            return self._json(200, {"ok": True})
        if len(rest) == 2 and rest[0] == "sessions" and method == "DELETE":
            drop_session(rest[1], "borrada desde otra PC")
            return self._json(200, {"ok": True})
        if len(rest) == 2 and rest[0] == "pending" and method == "POST":
            code, res = accion_pending(rest[1], self._body_json(raw), desde_tablero=False)
            return self._json(code, res)
        return self._json(404, {"error": "ruta desconocida"})

    def _secret_receive(self, raw: bytes, pc_id: str | None) -> None:
        """Un secreto que manda otra PC: viene cifrado con la clave del par, ademas de firmado."""
        d = self._body_json(raw)
        if motivo := secretos.validar(d):
            return self._json(400, {"error": motivo})
        key = _peer_key(pc_id or "")
        try:
            valor = secretos.descifrar(key, d.get("cifrado") or {}) if key else None
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        if valor is None:
            return self._json(403, {"error": "PC no emparejada"})
        log(f"secreto «{d['nombre']}» ({d['destino']}) recibido de {pc_id}")
        code, res = secretos.recibir(d, valor)
        return self._json(code, res)

    def _pair(self, raw: bytes) -> None:
        body = self._body_json(raw)
        try:
            res = pairing.accept(body)
        except pairing.PairingError as e:
            return self._json(400, {"error": str(e)})
        _connect_stored_peer(str(body.get("pc_id") or ""))
        return self._json(200, res)

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
            return self._json(404, no_session())
        code, res = session_view_response(s, view, self.query)
        return self._json(code, res)

    def _cuerpo_accion(self, a: AccionSesion, raw: bytes) -> dict:
        """El cuerpo de una accion de tarjeta tal como llega de otra PC: JSON, nada, o el adjunto en
        base64 adentro del JSON (no hay transporte binario entre PCs). Queda igual que el del
        tablero ({filename, data}), asi la accion no sabe por donde vino."""
        if a.cuerpo == "nada":
            return {}
        d = self._body_json(raw)
        if a.cuerpo != "adjunto":
            return d
        name, data_b64 = d.get("filename"), d.get("data_b64")
        data = b""
        if isinstance(data_b64, str) and data_b64:
            try:
                data = base64.b64decode(data_b64, validate=True)
            except ValueError, binascii.Error:
                raise RequestError("adjunto invalido") from None
        # el nombre llega como texto siempre, como en el tablero (sale de X-Filename): uno que no
        # es texto hacia reventar save_attachment
        return {"filename": name if isinstance(name, str) and name else "adjunto.bin", "data": data}

    def _accion_sesion(self, method: str, sid: str, nombre: str, raw: bytes) -> None:
        """/peer/sessions/<id>/<nombre>: la accion se mira ANTES que la tarjeta, asi una que esta
        PC no conoce es «ruta desconocida» y no unknown_session (que el espejo de la otra PC toma
        como tarjeta fantasma). Despues, lo mismo que el tablero, sin reenviar."""
        a = ACCIONES_SESION.get((method, nombre))
        if a is None:
            return self._json(404, {"error": "ruta desconocida"})
        code, res = atender_accion(method, sid, nombre, self._cuerpo_accion(a, raw), desde_tablero=False)
        return self._json(code, res)

    def _events(self) -> None:
        _stream_sse(self, snapshot_json(con_espejo=False), [])


def _lan_ip() -> str | None:
    """La IP de LAN de esta PC: abre un socket UDP hacia una IP publica sin mandar nada (no hace
    falta que responda) y lee con que IP local hubiera salido. None sin red (o sin ruta por
    defecto): el listener de pares de la LAN se abre cuando aparezca (ListenersDePares). Que no hay
    IP de LAN queda en el log una vez, con el motivo, y otra cuando vuelve (revision 2026-10-04, S17:
    antes caia callado a 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError as e:
        ip, motivo = None, f"{type(e).__name__}: {e}"
    else:
        motivo = None if ip and not ip.startswith(("0.", "127.")) else f"la salida por defecto es {ip}"
    state.avisar_si_cambia(
        "red: IP de LAN",
        f"red: sin IP de LAN ({motivo}): el listener de pares de la LAN se abre cuando aparezca" if motivo else None,
    )
    return None if motivo else ip


def _nombre_red(clave: str) -> str:
    return {"lan": "la LAN", "tailscale": "Tailscale"}.get(clave, clave)


class ListenersDePares:
    """Los listeners de pares (7322), uno por direccion propia: la de la LAN y, si esta prendido,
    la de Tailscale. `reconciliar` los deja ligados exactamente a las direcciones que se le pasan:
    abre los que faltan, cierra los de una IP que ya no es la propia y registra el motivo.

    Antes se ligaban una sola vez al arrancar: despues de cambiar de red el de la LAN quedaba
    escuchando en una IP que ya no existia, y el de Tailscale no se volvia a abrir si Tailscale se
    apagaba y prendia (incidente del 2026-10-05). Corre en su propio hilo (red_loop), nunca en el
    camino del HTTP local: abrir y cerrar un listener no toma `lock`."""

    def __init__(self, port: int, handler=None) -> None:
        self.port = port
        self.handler = handler or PeerHandler
        self._mx = threading.Lock()
        self._srv: dict[str, tuple[str, QuietServer]] = {}  # clave -> (ip, server abierto)
        self._vista: dict[str, str] = {}  # clave -> la ultima IP deseada, abra o no
        self._fallo: dict[str, str] = {}  # clave -> el ultimo error de bind avisado
        self.ultimo_cambio: dict | None = None  # {ts, motivo}, para /salud

    def reconciliar(self, deseadas: dict[str, str | None]) -> list[str]:
        """Devuelve los motivos de lo que cambio (vacio si nada): red_loop reconecta el espejo
        cuando la lista no esta vacia."""
        motivos: list[str] = []
        with self._mx:
            for clave in sorted(set(self._vista) | set(deseadas)):
                antes, ahora = self._vista.get(clave), deseadas.get(clave) or None
                nombre = _nombre_red(clave)
                if antes != ahora:
                    if antes and ahora:
                        motivos.append(f"la IP de {nombre} cambió de {antes} a {ahora}")
                    elif antes:
                        motivos.append(f"{nombre} sin red (era {antes})")
                    self._cerrar(clave)
                    self._fallo.pop(clave, None)
                    if ahora:
                        self._vista[clave] = ahora
                    else:
                        self._vista.pop(clave, None)
                if ahora and clave not in self._srv:
                    self._abrir(clave, ahora)
        for m in motivos:
            log(f"red: {m}; los listeners de pares quedan en {self._resumen()}")
        if motivos:
            self.ultimo_cambio = {"ts": now(), "motivo": "; ".join(motivos)}
        return motivos

    def _abrir(self, clave: str, ip: str) -> None:
        try:
            srv = QuietServer((ip, self.port), self.handler)
        except OSError as e:
            error = f"{ip}: {e}"
            if self._fallo.get(clave) != error:  # una vez por motivo, no cada RED_CADA_S
                self._fallo[clave] = error
                log(f"listener de peers ({_nombre_red(clave)}): no se pudo tomar {ip}:{self.port} ({e}); se reintenta")
            return
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, name=f"pares-{clave}", daemon=True).start()
        self._srv[clave] = (ip, srv)
        self._fallo.pop(clave, None)
        log(f"listener de peers ({_nombre_red(clave)}) en http://{ip}:{self.port}")

    def _cerrar(self, clave: str) -> None:
        got = self._srv.pop(clave, None)
        if got is None:
            return
        # shutdown espera a que serve_forever salga (medio segundo como mucho); las conexiones ya
        # abiertas siguen en sus hilos hasta que el par corte o venza PEER_SOCKET_TIMEOUT_S
        got[1].shutdown()
        got[1].server_close()

    def _resumen(self) -> str:
        with_ips = [f"{_nombre_red(k)} {ip}" for k, (ip, _s) in sorted(self._srv.items())]
        return ", ".join(with_ips) or "ninguno"

    def estado(self) -> dict[str, str]:
        """{clave: ip} de los listeners abiertos ahora."""
        return {k: ip for k, (ip, _s) in self._srv.items()}

    def cerrar_todo(self) -> None:
        with self._mx:
            for clave in list(self._srv):
                self._cerrar(clave)
            self._vista.clear()


LISTENERS: ListenersDePares | None = None  # el de main(), para /salud


def direcciones_propias(peer_host_fijo: str | None) -> dict[str, str | None]:
    """A que IPs ligar los listeners de pares ahora: la de LAN (o la fija de --peer-host) y la de
    Tailscale si esta prendido y es otra."""
    lan = peer_host_fijo or _lan_ip()
    ts = red.tailscale_propia()
    return {"lan": lan, "tailscale": ts if ts and ts != lan else None}


def red_loop(listeners: ListenersDePares, peer_host_fijo: str | None, stop_event: threading.Event) -> None:
    """Cada RED_CADA_S: si cambio la IP de LAN o la de Tailscale (otra red, Tailscale prendido o
    apagado, DHCP), vuelve a ligar los listeners, lo registra con el motivo y corta el SSE de cada
    par para que el espejo reconecte ya por la red nueva."""
    while not stop_event.wait(RED_CADA_S):
        try:
            if listeners.reconciliar(direcciones_propias(peer_host_fijo)):
                mirror.MIRROR.reconectar_todos()
        except Exception:
            log(f"red: fallo al revisar las direcciones propias\n{traceback.format_exc()}")


# --- vigia: que el HTTP local no quede colgado sin que se sepa por que -------------------------

_vigia_avisado: set[tuple] = set()
SALUD_LOCK_S = 1.0  # /salud da ok=false con el lock tomado mas que esto (lo normal son milisegundos)
SALUD_CONSOLA_S = 5.0


def vigilar_lock_una_vez(avisar: Callable[[str], None] | None = None) -> None:
    """Si el lock de las tarjetas lleva tomado mas de LOCK_LENTO_S, deja en el log la pila del hilo
    que lo tiene (una vez por episodio): el 2026-10-05 el server quedo colgado horas y no hubo forma
    de saber, despues, donde. Con la consola trabada avisa una vez tambien, para que se sepa por que
    no aparece nada en la ventana."""
    avisar = avisar or log
    t = lock.tenencia()
    if t and t["tomado_hace_s"] >= state.LOCK_LENTO_S:
        clave = ("lock", t["ident"], t["desde"])
        if clave not in _vigia_avisado:
            _vigia_avisado.add(clave)
            frame = sys._current_frames().get(t["ident"])
            pila = "".join(traceback.format_stack(frame)) if frame is not None else "(sin pila)"
            avisar(
                f"vigia: el lock de las tarjetas lleva {t['tomado_hace_s']:.0f} s tomado por el hilo "
                f"{t['hilo']}; GET /sessions y la liveness esperan. Esta parado en:\n{pila}"
            )
    desde = state.consola_trabada_desde()
    if desde is not None and time.monotonic() - desde >= SALUD_CONSOLA_S:
        clave = ("consola", desde)
        if clave not in _vigia_avisado:
            _vigia_avisado.add(clave)
            c = state.consola_estado()
            avisar(
                f"vigia: la consola no acepta texto hace {c['trabada_hace_s']:.0f} s (¿una selección abierta en la "
                f"ventana? Esc la suelta); el log sigue entero en {state.LOG}"
            )


def vigia_loop(cada_s: float = 2.0) -> None:
    while True:
        time.sleep(cada_s)
        try:
            vigilar_lock_una_vez()
        except Exception:
            log(f"vigia: fallo\n{traceback.format_exc()}")


_ARRANQUE = time.time()


def salud() -> dict:
    """GET /salud: el estado del server sin tomar `lock` (si esta trabado, esto lo dice en vez de
    trabarse tambien): quien tiene el lock y desde cuando, la consola, los pares (alive, cuanto
    hace que se supo de cada uno y el diagnostico de red) y a que IPs estan ligados los listeners."""
    t = lock.tenencia()
    c = state.consola_estado()
    lento = bool(t and t["tomado_hace_s"] >= SALUD_LOCK_S)
    trabada = c["trabada_hace_s"] is not None and c["trabada_hace_s"] >= SALUD_CONSOLA_S
    return {
        "ok": not lento and not trabada,
        "ts": now(),
        "arriba_s": round(time.time() - _ARRANQUE),
        "lock": None if t is None else {"hilo": t["hilo"], "tomado_hace_s": t["tomado_hace_s"]},
        "consola": c,
        "pares": mirror.MIRROR.peers_status(),
        "listeners": LISTENERS.estado() if LISTENERS is not None else {},
        "ultimo_cambio_de_red": LISTENERS.ultimo_cambio if LISTENERS is not None else None,
        "hilos": threading.active_count(),
    }


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


RELOAD_EXIT = 75  # codigo de salida que lienzo-server.cmd interpreta como "relanzame"
RELOAD_EVERY_S = 2.0
RELOAD_SETTLE_S = 1.5


def _source_stamp() -> dict[str, tuple[int, int]]:
    """{archivo: (mtime_ns, tamano)} de todo el codigo Python que corre este server."""
    out = {}
    for name in os.listdir(HERE):
        if name.endswith(".py"):
            p = os.path.join(HERE, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[p] = (st.st_mtime_ns, st.st_size)
    return out


def _syntax_error(changed: list[str]) -> str | None:
    """Primer error de sintaxis entre los archivos cambiados, o None. Un `git pull` a medias o
    una edicion rota no tiene que tirar el server: se espera al proximo cambio."""
    for p in changed:
        try:
            with open(p, "rb") as f:
                compile(f.read(), p, "exec")
        except OSError:
            continue
        except SyntaxError as e:
            return f"{os.path.basename(p)}:{e.lineno}: {e.msg}"
    return None


def reiniciar() -> tuple[int, dict]:
    """Reinicio explicito: sale con RELOAD_EXIT para que lienzo-server.cmd lo relance en la misma
    ventana, medio segundo despues de contestar. No sale si no corre bajo ese .cmd (nadie lo
    levantaria) ni si algun .py no compila (relanzaria codigo roto)."""
    if os.environ.get("LIENZO_RELOAD") != "1":
        return 409, {"error": "este server no corre bajo lienzo-server.cmd: si sale, nadie lo relanza"}
    err = _syntax_error(list(_source_stamp()))
    if err:
        return 409, {"error": f"no reinicio: hay codigo que no compila ({err})"}
    log("reinicio pedido explicitamente")
    threading.Timer(0.5, lambda: os._exit(RELOAD_EXIT)).start()
    return 202, {"ok": True, "reinicia": True}


def reload_loop() -> None:
    """Si cambia algun .py del server, sale con RELOAD_EXIT para que lienzo-server.cmd lo relance
    en la misma ventana. Solo corre bajo ese .cmd (LIENZO_RELOAD=1): sin el, salir apagaria el
    server y nadie lo levantaria. Espera a que los archivos dejen de cambiar (un pull escribe
    varios) y no relanza sobre codigo que no compila."""
    base = _source_stamp()
    while True:
        time.sleep(RELOAD_EVERY_S)
        now = _source_stamp()
        if now == base:
            continue
        if not load_config().get("auto_reload"):
            # apagado por defecto (pedido de Ariel, 2026-10-04): con varios agentes cambiando .py el
            # server se reiniciaba a cada rato y cortaba pruebas, capturas y pedidos entre PCs. Se
            # reinicia explicito: POST /restart o coordinar.reiniciar(). Se toma el codigo nuevo
            # como base para no reiniciar de golpe si despues se prende auto_reload.
            base = now
            continue
        time.sleep(RELOAD_SETTLE_S)
        if _source_stamp() != now:
            continue  # sigue escribiendose: la proxima vuelta lo ve estable
        changed = [p for p in now if now[p] != base.get(p)] + [p for p in base if p not in now]
        err = _syntax_error(changed)
        if err:
            log(
                f"recarga: cambio en {', '.join(os.path.basename(p) for p in changed)} con error de sintaxis ({err}); sigo con el codigo viejo"
            )
            base = now
            continue
        log(f"recarga: cambio en {', '.join(sorted(os.path.basename(p) for p in changed))}; reinicio")
        os._exit(RELOAD_EXIT)


def xpc_purge_loop(every_s: float = 60.0, arranque_s: float = 120.0) -> None:
    """Limpia las reglas con destino en otra PC cuyo destino ya no existe, pero solo cuando todos los
    peers ya mandaron su snapshot (y pasaron `arranque_s` desde el arranque): antes de eso, una
    tarjeta ajena que no se ve es una que todavia no llego, y borrarla perderia la regla."""
    t0 = time.time()
    while True:
        time.sleep(every_s)
        try:
            if time.time() - t0 > arranque_s and mirror.MIRROR.all_synced():
                rl.purge_stale_xpc(
                    known_remote=lambda sid: mirror.MIRROR.owner_of(sid) is not None,
                    known_local=lambda sid: sid in sessions,
                )
        except Exception:
            log(traceback.format_exc())


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
            _beacon_sync_once(beacon)
        except Exception:
            log(f"beacon: fallo al sincronizar las IP:\n{traceback.format_exc()}")


def elegir_direccion(info: dict, conectada: str | None, ahora: float, ttl_s: float) -> str | None:
    """Con cual de las direcciones vivas de un peer (las que mandaron un beacon firmado hace menos de
    `ttl_s`) conectar el espejo: la que ya usa mientras siga viva, para no saltar entre la LAN y
    Tailscale cuando llega por las dos; si no, la de la LAN antes que la de Tailscale, y entre
    iguales la mas reciente. None si no hay ninguna viva o si la conectada sigue sirviendo."""
    ips = info.get("ips") or ({info["ip"]: info.get("last_seen", ahora)} if info.get("ip") else {})
    vivas = {ip: t for ip, t in ips.items() if ahora - t <= ttl_s}
    if not vivas or conectada in vivas:
        return None
    return max(vivas, key=lambda ip: (not red.es_tailscale(ip), vivas[ip]))


def _beacon_sync_once(beacon) -> None:
    """Una pasada: cada peer emparejado cuya direccion conectada ya no tiene beacon y que tiene otra
    viva (o sin espejo conectado: la PC que ofrecio la frase guarda ip "" y nunca conectaba) se
    anota en peers.json y se reconecta por esa."""
    try:
        vistos = beacon.seen()
    except Exception as e:
        log(f"beacon: fallo al leer lo visto: {e}")
        return
    ahora = time.time()
    for pc_id, info in vistos.items():
        if not isinstance(info, dict):
            continue
        with _ip_conectada_lock:
            conectada = _ip_conectada.get(pc_id)
        ip = elegir_direccion(info, conectada, ahora, BEACON_TTL_S)
        if not ip:
            continue
        peer = federation.get_peer(PEERS_FILE, pc_id)
        if peer is None:
            continue
        try:
            federation.update_peer_ip(PEERS_FILE, pc_id, ip)
        except OSError as e:
            log(f"peer {pc_id}: no se pudo anotar la IP {ip} en peers.json ({e}); se reconecta igual")
        _connect_peer_from_record({**peer, "ip": ip})
        log(
            f"peer {peer.get('name') or pc_id}: espejo reconectado por beacon a {ip} (antes {conectada or 'sin conexion'})"
        )


def instalar_excepthook() -> None:
    """Cualquier excepcion que mate un hilo va al log propio con su traceback. Sin esto iba a
    stderr, la consola del server que nadie mira, y un hilo de fondo (barrido, reglas, espejo)
    moria en silencio (revision 2026-10-04, 1.1; los hilos que deben seguir vivos atrapan lo
    suyo, esto es la red de abajo)."""

    def hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        nombre = args.thread.name if args.thread is not None else "?"
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log(f"excepcion sin atrapar en el hilo {nombre}:\n{tb}")

    threading.excepthook = hook


def main() -> int:
    global LISTENERS
    instalar_excepthook()
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
    rules.load(lambda r: (r.get("to") in sessions or r.get("xpc")) and (not r.get("from") or r["from"] in sessions))
    purge_stale_at_rules()
    clean_attachments()
    if not a.no_sweep:
        sweep_once()
    threading.Thread(target=consume_events, daemon=True).start()
    threading.Thread(target=scan_pending, daemon=True).start()
    threading.Thread(target=liveness_loop, args=(0 if a.no_sweep else a.sweep_every,), daemon=True).start()
    threading.Thread(target=screen_loop, daemon=True).start()
    threading.Thread(target=rules_loop, daemon=True).start()
    autoaprobar.arrancar()
    if a.remote:
        threading.Thread(target=tunnel_loop, args=(a.port,), daemon=True).start()
    if os.environ.get("LIENZO_RELOAD") == "1":
        threading.Thread(target=reload_loop, daemon=True).start()

    # --- federacion (plan multi-PC, ronda 2): listener de peers, espejo y beacon ----------------
    mirror.MIRROR.on_change = broadcast_mirror_snapshot
    mirror.MIRROR.on_snapshot = reconcile_peer_rules
    mirror.MIRROR.log = log
    health.log = log
    health.cuotas_de_sesiones = cuotas_de_sesiones
    health.remotes_de_sesiones = remotes_de_sesiones
    health.repo_de_remote = repo_de_remote
    health.coda_viva = coda_viva
    secretos.al_guardar_git = health.renovar_git
    xfer.log = log
    xfer.conn_de = mirror.MIRROR.conn_of
    health.xfer_resumen = xfer.resumen
    peers_guardados = federation.list_peers(PEERS_FILE)
    modo_pares = a.peers or bool(peers_guardados)
    if modo_pares:
        # los listeners de pares se ligan a la IP de LAN y a la de Tailscale de AHORA, y red_loop
        # los vuelve a ligar cuando cambian (otra red, Tailscale prendido o apagado)
        LISTENERS = ListenersDePares(a.peer_port)
        LISTENERS.reconciliar(direcciones_propias(a.peer_host))
    for peer in peers_guardados:
        _connect_peer_from_record(peer)
    if peers_guardados:
        threading.Thread(target=xpc_purge_loop, daemon=True).start()
    xfer.arrancar()  # los trabajos de copia que estaban andando antes del reinicio siguen solos
    # siempre, no solo con peers guardados: uno emparejado despues tambien puede quedar pendiente
    threading.Thread(target=config_peers_loop, daemon=True).start()
    threading.Thread(target=vigia_loop, name="vigia", daemon=True).start()
    if modo_pares:
        stop_beacon = threading.Event()
        beacon.start(a.peer_port, stop_beacon)
        threading.Thread(target=_beacon_sync_loop, args=(stop_beacon, beacon), daemon=True).start()
        threading.Thread(target=red_loop, args=(LISTENERS, a.peer_host, stop_beacon), name="red", daemon=True).start()

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
