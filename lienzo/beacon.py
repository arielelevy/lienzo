"""Beacon UDP en la LAN (plan-multi-pc-2026-09-26.md §3.2). Cada `interval_s` (10 s en produccion)
cada PC manda dos cosas:

- un anuncio **sin firma** (pc_id, nombre, puerto): es el que hace que el tablero muestre todas las
  PCs de la LAN con el lienzo corriendo, emparejadas o no. No da ningun permiso: emparejar sigue
  pidiendo la frase de seis palabras, y hablarle a una PC sigue pidiendo la clave del par.
- por cada peer emparejado, un anuncio firmado con la clave de ESE par
  (federation.encode_signed_beacon): el que decodifica con la clave de un peer conocido le
  actualiza la IP (federation.update_peer_ip). Sin firma, cualquiera podria desviar esa IP.

Un socket UDP con SO_BROADCAST alcanza porque no hace falta conocer la IP de la LAN de antemano.

`start(port, stop_event)` es la firma que usa server.py (ronda 2): `port` es el puerto TCP propio
del listener de peers (7322), el que se anuncia adentro de cada beacon para que quien lo reciba
sepa donde hablarle despues. El socket UDP en si escucha y emite en `udp_port` (7323 fijo en
produccion, inyectable solo para pruebas).

Nunca deja escapar una excepcion del hilo: un peer caido, un paquete corrupto o una LAN sin
broadcast no pueden tumbar el beacon de los demas peers.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import federation as fed
import identity
import state

BEACON_PORT = 7323
INTERVAL_S = 10.0
RECV_BUFSIZE = 4096

_lock = threading.RLock()
_seen: dict[str, dict] = {}  # pc_id -> {"ip", "last_seen"}, solo peers emparejados (anuncio firmado)
_descubiertas: dict[str, dict] = {}  # pc_id -> {"name", "ip", "port", "last_seen"}, cualquier PC de la LAN
DISCOVERED_TTL_S = 3 * INTERVAL_S + 5  # tres anuncios perdidos seguidos: se da por apagada


def _peers_path() -> str:
    return os.path.join(state.LIENZO, "peers.json")


def seen() -> dict[str, dict]:
    """Ultimo beacon valido recibido de cada peer, por pc_id."""
    with _lock:
        return {k: dict(v) for k, v in _seen.items()}


def discovered(max_age_s: float = DISCOVERED_TTL_S) -> list[dict]:
    """Las PCs de la LAN con el lienzo corriendo que anunciaron hace menos de `max_age_s`, sin la
    propia, las mas recientes primero: `{pc_id, name, ip, port, last_seen}`."""
    limite = time.time() - max_age_s
    with _lock:
        vivas = [{"pc_id": k, **v} for k, v in _descubiertas.items() if v["last_seen"] >= limite]
    return sorted(vivas, key=lambda d: -d["last_seen"])


def _abrir_socket(udp_port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass  # no todos los Windows lo tienen; sin esto igual funciona, solo no comparte puerto
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", udp_port))
    sock.settimeout(1.0)  # para poder revisar stop_event sin bloquearse para siempre
    return sock


def _enviar(sock: socket.socket, udp_port: int, mi_puerto_tcp: int, broadcast_addr: str) -> None:
    info = identity.pc_info()
    pc_id, nombre = info["pc_id"], info["name"]
    try:
        sock.sendto(fed.encode_beacon(pc_id, nombre, mi_puerto_tcp), (broadcast_addr, udp_port))
    except OSError:
        pass  # LAN sin broadcast: los firmados de abajo tampoco van a salir, pero se intenta
    for peer in fed.list_peers(_peers_path()):
        key_hex = peer.get("key")
        if not key_hex:
            continue
        try:
            paquete = fed.encode_signed_beacon(bytes.fromhex(key_hex), pc_id, nombre, mi_puerto_tcp)
            sock.sendto(paquete, (broadcast_addr, udp_port))
        except OSError, ValueError:
            pass  # LAN sin broadcast, peer con la key corrupta: se sigue con el resto


def _recibir(sock: socket.socket) -> None:
    try:
        data, addr = sock.recvfrom(RECV_BUFSIZE)
    except TimeoutError, OSError:
        return
    anuncio = fed.decode_beacon(data)
    if anuncio is not None:
        _registrar_descubierta(anuncio, addr[0])
        return
    for peer in fed.list_peers(_peers_path()):
        key_hex = peer.get("key")
        if not key_hex:
            continue
        try:
            anuncio = fed.decode_signed_beacon(bytes.fromhex(key_hex), data)
        except ValueError:
            continue
        if anuncio is None or anuncio.get("pc_id") != peer.get("pc_id"):
            continue  # decodifica pero dice ser otro pc_id: firmado con esta clave no corresponde
        ip = addr[0]
        fed.update_peer_ip(_peers_path(), peer["pc_id"], ip)
        with _lock:
            _seen[peer["pc_id"]] = {"ip": ip, "last_seen": time.time()}
        return


def _registrar_descubierta(anuncio: dict, ip: str) -> None:
    """Un anuncio sin firma: se anota para mostrarlo, nunca se usa para rutear ni para confiar."""
    pc_id = anuncio.get("pc_id")
    port = anuncio.get("port")
    if not isinstance(pc_id, str) or pc_id == identity.pc_id() or not isinstance(port, int):
        return
    nombre = anuncio.get("name")
    with _lock:
        _descubiertas[pc_id] = {
            "name": nombre if isinstance(nombre, str) and nombre.strip() else pc_id,
            "ip": ip,
            "port": port,
            "last_seen": time.time(),
        }


def _run(
    udp_port: int, mi_puerto_tcp: int, stop_event: threading.Event, interval_s: float, broadcast_addr: str
) -> None:
    try:
        sock = _abrir_socket(udp_port)
    except OSError as e:
        state.log(f"beacon: no se pudo abrir el puerto UDP {udp_port}: {e}")
        return
    try:
        ultimo_envio = 0.0
        while not stop_event.is_set():
            ahora = time.time()
            if ahora - ultimo_envio >= interval_s:
                try:
                    _enviar(sock, udp_port, mi_puerto_tcp, broadcast_addr)
                except Exception as e:  # nunca se cae el hilo por un beacon que no salio
                    state.log(f"beacon: fallo al enviar: {e}")
                ultimo_envio = ahora
            try:
                _recibir(sock)
            except Exception as e:
                state.log(f"beacon: fallo al recibir: {e}")
    finally:
        sock.close()


def start(
    port: int,
    stop_event: threading.Event,
    *,
    udp_port: int = BEACON_PORT,
    interval_s: float = INTERVAL_S,
    broadcast_addr: str = "255.255.255.255",
) -> threading.Thread:
    """`port`: puerto TCP propio del listener de peers, el que se anuncia. `udp_port` y
    `broadcast_addr` son inyectables para poder correr dos beacons de prueba en 127.0.0.1 sin
    pisarse ni depender del broadcast real de la LAN."""
    thread = threading.Thread(
        target=_run,
        args=(udp_port, port, stop_event, interval_s, broadcast_addr),
        daemon=True,
    )
    thread.start()
    return thread
