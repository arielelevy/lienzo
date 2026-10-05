"""Beacon UDP en la LAN (plan-multi-pc-2026-09-26.md §3.2). Cada `interval_s` (10 s en produccion)
cada PC manda dos cosas:

- un anuncio **sin firma** (pc_id, nombre, puerto): es el que hace que el tablero muestre todas las
  PCs de la LAN con el lienzo corriendo, emparejadas o no. No da ningun permiso: emparejar sigue
  pidiendo la frase de una palabra que muestra la otra PC (SPAKE2, ver pairing.py), y hablarle a
  una PC sigue pidiendo la clave del par.
- por cada peer emparejado, un anuncio firmado con la clave de ESE par
  (federation.encode_signed_beacon): el que decodifica con la clave de un peer conocido le
  actualiza la IP (federation.update_peer_ip). Sin firma, cualquiera podria desviar esa IP.

Un socket UDP con SO_BROADCAST alcanza porque no hace falta conocer la IP de la LAN de antemano.
Pero Windows saca el broadcast limitado (255.255.255.255) por una sola interfaz, y con los
adaptadores virtuales de WSL, Hyper-V o wslc esa puede no ser la de la LAN: por eso cada anuncio
sale tambien como broadcast dirigido (x.y.z.255) por cada IPv4 propia.

Una red que filtra el broadcast deja a un peer que cambio de IP sin forma de reencontrarse. Para
eso, mientras haya un peer emparejado sin anuncio reciente, cada `SWEEP_S` se le manda su beacon
firmado por unicast a cada IP de las /24 propias; el que lo recibe y no habia visto a ese peer hace
poco le contesta con su propio beacon firmado, por unicast a la IP de donde vino. Asi los dos
aprenden la IP nueva del otro sin broadcast, con la misma firma y la misma regla de ts creciente.
Un aislamiento de clientes del Wi-Fi (sin ARP entre equipos) no lo arregla nada de esto.

`start(port, stop_event)` es como lo arranca server.py: `port` es el puerto TCP propio
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
from collections.abc import Callable

import federation as fed
import identity
import state

BEACON_PORT = 7323
INTERVAL_S = 10.0
RECV_BUFSIZE = 4096
BROADCAST_LIMITADO = "255.255.255.255"
SWEEP_S = 60.0  # cada cuanto se barren las /24 propias por un peer emparejado que no anuncia

_lock = threading.RLock()
_seen: dict[str, dict] = {}  # pc_id -> {"ip", "last_seen"}, solo peers emparejados (anuncio firmado)
_descubiertas: dict[str, dict] = {}  # pc_id -> {"name", "ip", "port", "last_seen"}, cualquier PC de la LAN
_ultimo_ts: dict[str, float] = {}  # pc_id -> ts firmado del ultimo beacon aceptado (ver _recibir)
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


def _ipv4_propias() -> list[str]:
    """Las IPv4 de esta PC, sin loopback ni link-local. Sin psutil: las que resuelve el propio
    nombre, que en Windows son las de todos los adaptadores, fisicos y virtuales."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith(("127.", "169.254."))})


def _prefijo24(ip: str) -> str:
    return ip.rsplit(".", 1)[0]


def destinos(broadcast_addr: str, ips: list[str] | None = None) -> list[str]:
    """A donde sale cada anuncio. Con el broadcast limitado (produccion), ademas el dirigido de
    cada /24 propia; con otra direccion (pruebas en 127.0.0.1), solo esa."""
    if broadcast_addr != BROADCAST_LIMITADO:
        return [broadcast_addr]
    propias = _ipv4_propias() if ips is None else ips
    return [BROADCAST_LIMITADO, *sorted({f"{_prefijo24(ip)}.255" for ip in propias})]


def objetivos_barrido(ips: list[str]) -> list[str]:
    """Cada host de las /24 propias, sin las IP propias."""
    propias = set(ips)
    prefijos = sorted({_prefijo24(ip) for ip in ips})
    return [f"{p}.{h}" for p in prefijos for h in range(1, 255) if f"{p}.{h}" not in propias]


def faltantes(ahora: float | None = None) -> list[dict]:
    """Los peers emparejados, con clave, sin un beacon firmado en los ultimos `DISCOVERED_TTL_S`."""
    limite = (time.time() if ahora is None else ahora) - DISCOVERED_TTL_S
    with _lock:
        vistos = {k for k, v in _seen.items() if v["last_seen"] >= limite}
    return [p for p in fed.list_peers(_peers_path()) if p.get("key") and p.get("pc_id") not in vistos]


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


def _firmado(peer: dict, mi_puerto_tcp: int) -> bytes:
    info = identity.pc_info()
    return fed.encode_signed_beacon(bytes.fromhex(peer["key"]), info["pc_id"], info["name"], mi_puerto_tcp)


def _enviar(sock: socket.socket, udp_port: int, mi_puerto_tcp: int, broadcast_addr: str) -> None:
    info = identity.pc_info()
    pc_id, nombre = info["pc_id"], info["name"]
    anuncio = fed.encode_beacon(pc_id, nombre, mi_puerto_tcp)
    firmados = []
    for peer in fed.list_peers(_peers_path()):
        if not peer.get("key"):
            continue
        try:
            firmados.append(_firmado(peer, mi_puerto_tcp))
        except ValueError:
            pass  # peer con la key corrupta: se sigue con el resto
    for destino in destinos(broadcast_addr):
        for paquete in (anuncio, *firmados):
            try:
                sock.sendto(paquete, (destino, udp_port))
            except OSError:
                pass  # interfaz sin broadcast: se intenta igual por las otras


def _barrer(sock: socket.socket, udp_port: int, mi_puerto_tcp: int) -> int:
    """El beacon firmado de cada peer faltante, por unicast a cada host de las /24 propias.
    Devuelve cuantos paquetes salieron."""
    pendientes = faltantes()
    if not pendientes:
        return 0
    objetivos = objetivos_barrido(_ipv4_propias())
    enviados = 0
    for peer in pendientes:
        try:
            paquete = _firmado(peer, mi_puerto_tcp)
        except ValueError:
            continue
        for ip in objetivos:
            try:
                sock.sendto(paquete, (ip, udp_port))
                enviados += 1
            except OSError:
                pass  # host inalcanzable: es lo esperado en casi toda la /24
    return enviados


def _recibir(sock: socket.socket, responder: Callable[[dict, tuple], None] | None = None) -> None:
    """`responder(peer, addr)`, si viene, se llama cuando llega el beacon firmado de un peer que no
    se habia visto en `DISCOVERED_TTL_S` o que cambio de IP: es la respuesta unicast del barrido."""
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
            decodificado = fed.decode_signed_beacon_ts(bytes.fromhex(key_hex), data)
        except ValueError:
            continue
        anuncio, ts = decodificado if decodificado else (None, 0.0)
        if anuncio is None or anuncio.get("pc_id") != peer.get("pc_id"):
            continue  # decodifica pero dice ser otro pc_id: firmado con esta clave no corresponde
        ahora = time.time()
        with _lock:
            # solo un ts estrictamente mayor al ultimo aceptado de este peer: la ventana de firma
            # sola dejaba reenviar desde otra IP, durante 30 s, un beacon capturado (B9). Un
            # duplicado legitimo (el mismo broadcast por dos interfaces) se descarta sin dano
            if ts <= _ultimo_ts.get(peer["pc_id"], 0.0):
                return
            _ultimo_ts[peer["pc_id"]] = ts
            previo = _seen.get(peer["pc_id"])
            reaparece = previo is None or previo["ip"] != addr[0] or ahora - previo["last_seen"] > DISCOVERED_TTL_S
            _seen[peer["pc_id"]] = {"ip": addr[0], "last_seen": ahora}
        fed.update_peer_ip(_peers_path(), peer["pc_id"], addr[0])
        if reaparece and responder is not None:
            responder(peer, addr)
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
    udp_port: int,
    mi_puerto_tcp: int,
    stop_event: threading.Event,
    interval_s: float,
    broadcast_addr: str,
    sweep_s: float,
) -> None:
    try:
        sock = _abrir_socket(udp_port)
    except OSError as e:
        state.log(f"beacon: no se pudo abrir el puerto UDP {udp_port}: {e}")
        return

    def responder(peer: dict, addr: tuple) -> None:
        try:
            sock.sendto(_firmado(peer, mi_puerto_tcp), addr)
            state.log(f"beacon: {peer.get('name') or peer['pc_id']} aparecio en {addr[0]}; respondido por unicast")
        except OSError, ValueError:
            pass  # si no sale, el proximo barrido del otro lado lo vuelve a intentar

    try:
        ultimo_envio = 0.0
        ultimo_barrido = time.time()  # el primer barrido, despues de dar tiempo a los anuncios normales
        while not stop_event.is_set():
            ahora = time.time()
            if ahora - ultimo_envio >= interval_s:
                try:
                    _enviar(sock, udp_port, mi_puerto_tcp, broadcast_addr)
                except Exception as e:  # nunca se cae el hilo por un beacon que no salio
                    state.log(f"beacon: fallo al enviar: {e}")
                ultimo_envio = ahora
            if broadcast_addr == BROADCAST_LIMITADO and ahora - ultimo_barrido >= sweep_s:
                try:
                    n = _barrer(sock, udp_port, mi_puerto_tcp)
                    if n:
                        state.log(f"beacon: barrido unicast por peers sin anuncio, {n} paquetes")
                except Exception as e:
                    state.log(f"beacon: fallo el barrido: {e}")
                ultimo_barrido = ahora
            try:
                _recibir(sock, responder)
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
    broadcast_addr: str = BROADCAST_LIMITADO,
    sweep_s: float = SWEEP_S,
) -> threading.Thread:
    """`port`: puerto TCP propio del listener de peers, el que se anuncia. `udp_port`,
    `broadcast_addr` y `sweep_s` son inyectables para poder correr dos beacons de prueba en
    127.0.0.1 sin pisarse ni depender del broadcast real de la LAN; con una direccion que no es la
    de broadcast limitado no hay broadcast dirigido ni barrido."""
    thread = threading.Thread(
        target=_run,
        args=(udp_port, port, stop_event, interval_s, broadcast_addr, sweep_s),
        daemon=True,
    )
    thread.start()
    return thread
