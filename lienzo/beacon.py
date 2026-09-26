"""Beacon UDP para descubrir peers ya emparejados en la LAN (plan-multi-pc-2026-09-26.md §3.2):
cada `interval_s` (10 s en produccion) cada PC manda, por cada peer emparejado, un anuncio firmado
con la clave de ESE par (federation.encode_signed_beacon) y escucha los anuncios de los demas; el
que decodifica con la clave de un peer conocido le actualiza la IP (federation.update_peer_ip). Un
socket UDP con SO_BROADCAST alcanza porque no hace falta conocer la IP de la LAN de antemano.

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
_seen: dict[str, dict] = {}  # pc_id -> {"ip", "last_seen"}


def _peers_path() -> str:
    return os.path.join(state.LIENZO, "peers.json")


def seen() -> dict[str, dict]:
    """Ultimo beacon valido recibido de cada peer, por pc_id."""
    with _lock:
        return {k: dict(v) for k, v in _seen.items()}


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
    peers = fed.list_peers(_peers_path())
    if not peers:
        return
    pc_id = identity.pc_id()
    nombre = identity.pc_info()["name"]
    for peer in peers:
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
