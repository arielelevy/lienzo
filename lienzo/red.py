"""La red entre PCs: Tailscale y el diagnostico de un peer que no llega (2026-10-05).

El caso que lo motivo: dos PCs en el mismo Wi-Fi publico («YPF Clientes 2») con aislamiento de
clientes. La puerta de enlace contesta y la otra PC no responde ni ARP: ningun paquete de la LAN
pasa entre las dos, y ni el broadcast dirigido ni el barrido unicast del beacon lo arreglan.
Tailscale si: cada PC tiene una IP 100.x.y.z alcanzable desde la otra en cualquier red.

- `tailnet_ips()`: las IPv4 de los otros equipos de la tailnet, de `tailscale status --json`. El
  beacon les manda sus anuncios por unicast; aceptar una IP sigue pidiendo el beacon firmado con
  la clave del par (beacon._recibir), la tailnet no da ningun permiso por si sola.
- `diagnosticar(host, error)`: por que no llega un peer, en una frase para el tablero: sin ARP
  (la red aisla a los equipos), puerto cerrado (no corre el lienzo), firewall, otra red.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import sys
import threading
import time

import subproc

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # el rango de las IP de Tailscale
TAILNET_TTL_S = 60.0
TAILSCALE_TIMEOUT_S = 5.0
ARP_TIMEOUT_S = 3.0

_lock = threading.Lock()
_cache: tuple[float, list[str]] = (0.0, [])


def es_tailscale(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in CGNAT
    except ValueError:
        return False


def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for candidato in (
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe"),
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ):
        if os.path.isfile(candidato):
            return candidato
    return None


def parse_status(texto: str) -> list[str]:
    """Las IPv4 de los peers en linea de un `tailscale status --json`, sin la propia."""
    try:
        status = json.loads(texto)
    except ValueError:
        return []
    if not isinstance(status, dict):
        return []
    peers = status.get("Peer")
    if not isinstance(peers, dict):
        return []
    ips: set[str] = set()
    for p in peers.values():
        if not isinstance(p, dict) or p.get("Online") is False:
            continue
        for ip in p.get("TailscaleIPs") or []:
            if isinstance(ip, str) and es_tailscale(ip):
                ips.add(ip)
    return sorted(ips)


def tailnet_ips(ahora: float | None = None) -> list[str]:
    """Cacheado `TAILNET_TTL_S`: lo llama el beacon cada 10 s. Sin Tailscale instalado o sin
    sesion, lista vacia: el lienzo sigue igual que antes, solo con la LAN."""
    global _cache
    t = time.time() if ahora is None else ahora
    with _lock:
        if t - _cache[0] < TAILNET_TTL_S:
            return list(_cache[1])
    exe = _tailscale_exe()
    ips: list[str] = []
    if exe:
        rc, out, _err = subproc.correr([exe, "status", "--json"], timeout=TAILSCALE_TIMEOUT_S)
        if rc == 0:
            ips = parse_status(out)
    with _lock:
        _cache = (t, ips)
    return list(ips)


def tailscale_propia() -> str | None:
    """La IP de Tailscale de esta PC, o None si no esta prendido. De los adaptadores (sin lanzar el
    CLI): server.py la mira cada minuto para abrir ahi el listener de peers."""
    return next((ip for ip in _ipv4_propias() if es_tailscale(ip)), None)


def _misma_24(ip: str, propias: list[str]) -> bool:
    prefijo = ip.rsplit(".", 1)[0]
    return any(p.rsplit(".", 1)[0] == prefijo for p in propias)


def _ipv4_propias() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith(("127.", "169.254."))})


def tiene_arp(ip: str) -> bool | None:
    """True si la tabla de vecinos tiene la MAC de `ip`, False si no (o quedo incompleta), None si
    no se pudo preguntar. Se mira despues de que la salud ya intento conectar: ese intento es el que
    dispara el ARP."""
    if sys.platform == "win32":
        rc, out, _ = subproc.correr(["arp", "-a", ip], timeout=ARP_TIMEOUT_S)
        if rc not in (0, 1):
            return None
        patron = re.escape(ip) + r"\s+([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}"
        return re.search(patron, out) is not None
    rc, out, _ = subproc.correr(["ip", "neigh", "show", ip], timeout=ARP_TIMEOUT_S)
    if rc == 0:
        return "lladdr" in out and not any(m in out for m in ("FAILED", "INCOMPLETE"))
    rc, out, _ = subproc.correr(["arp", "-n", ip], timeout=ARP_TIMEOUT_S)
    if rc not in (0, 1):
        return None
    return bool(re.search(r"([0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}", out))


# host o red inalcanzable: WSAEHOSTUNREACH, WSAENETUNREACH en Windows; EHOSTUNREACH, ENETUNREACH
_INALCANZABLE = {10065, 10051, 113, 101, 65, 51}


def _no_llega(error: BaseException) -> bool:
    """El paquete no tuvo respuesta (timeout) o la red dijo que no hay camino. Un OSError cualquiera
    (un cuerpo roto, un corte a mitad) no dice nada de la red."""
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, OSError):
        return getattr(error, "winerror", None) in _INALCANZABLE or error.errno in _INALCANZABLE
    return False


def diagnosticar(host: str, error: BaseException, propias: list[str] | None = None, arp=tiene_arp) -> str | None:
    """Por que no llega `host`, en una frase para el tablero; None si el error no dice nada de la
    red (un 401, un cuerpo roto: ya se ve en el log)."""
    if isinstance(error, ConnectionRefusedError):
        return "la PC contesta pero el puerto está cerrado: no corre el lienzo con --peers"
    if not _no_llega(error):
        return None
    if es_tailscale(host):
        return "no llega por Tailscale: ¿está prendido en las dos PCs y con la misma cuenta?"
    propias = _ipv4_propias() if propias is None else propias
    if not _misma_24(host, propias):
        return f"la última IP conocida ({host}) es de otra red: la PC cambió de red; con Tailscale se encuentran en cualquiera"
    hay = arp(host)
    if hay is False:
        return "sin ARP: la red aísla a los equipos (Wi-Fi público); usá Tailscale o un hotspot"
    if hay is True:
        return "la PC está en la red pero no contesta el puerto: firewall (install.py --peer abre solo el perfil Privado) o el lienzo colgado"
    return None
