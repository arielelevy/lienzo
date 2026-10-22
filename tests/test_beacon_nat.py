"""El beacon que llega por un NAT no rompe una conexión que anda (encargo K, 2026-10-22).

Medido emparejando el server nativo de Linux en WSL (red NAT) con una instancia de Windows: los
beacons de Windows llegan a WSL desde la puerta del NAT (172.17.240.1), donde Windows no tiene
listener de pares. Como la IP conectada (la LAN, 192.168.1.72) no manda beacons a WSL,
`_beacon_sync_once` saltaba a la puerta y el par quedaba caído a los 10 s. Ahora, con una conexión
en uso, sólo se salta a una dirección que abre el puerto. Necesita `server.diff` de K integrado."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lienzo"))

import federation as fed
import server

CLAVE = bytes(range(32))


class _Beacon:
    def __init__(self, vistos):
        self.vistos = vistos

    def seen(self):
        return self.vistos


def _armar(tmp_path, monkeypatch, abierto):
    peers = tmp_path / "peers.json"
    monkeypatch.setattr(server, "PEERS_FILE", str(peers))
    monkeypatch.setattr(server, "_ip_conectada", {})
    conexiones = []
    monkeypatch.setattr(server.mirror.MIRROR, "connect", lambda pc, info, host, port, key, yo: conexiones.append(host))
    monkeypatch.setattr(server.mirror.MIRROR, "disconnect", lambda pc: None)
    sondeos = []
    monkeypatch.setattr(
        server,
        "_puerto_abierto",
        lambda ip, port: sondeos.append((ip, port)) or (abierto(ip) if callable(abierto) else abierto),
    )
    registro = {"pc_id": "win", "name": "ariel", "ip": "192.168.1.72", "port": 27356, "key": CLAVE.hex()}
    fed.add_peer(str(peers), registro)
    server._connect_peer_from_record(registro)
    return conexiones, sondeos


def test_no_salta_a_la_puerta_del_nat_si_ahi_no_escucha_nadie(tmp_path, monkeypatch):
    conexiones, sondeos = _armar(tmp_path, monkeypatch, abierto=False)
    server._beacon_sync_once(_Beacon({"win": {"ips": {"172.17.240.1": time.time()}}}))
    assert sondeos == [("172.17.240.1", 27356)]
    assert conexiones == ["192.168.1.72"], "sigue en la que andaba"
    assert fed.get_peer(str(tmp_path / "peers.json"), "win")["ip"] == "192.168.1.72"


def test_si_la_nueva_abre_el_puerto_se_salta_como_siempre(tmp_path, monkeypatch):
    conexiones, sondeos = _armar(tmp_path, monkeypatch, abierto=True)
    server._beacon_sync_once(_Beacon({"win": {"ips": {"192.168.1.80": time.time()}}}))
    assert sondeos == [("192.168.1.80", 27356)]
    assert conexiones == ["192.168.1.72", "192.168.1.80"]


def test_si_la_mejor_no_abre_prueba_la_siguiente(tmp_path, monkeypatch):
    """La puerta del NAT (172.x) le gana a la de Tailscale en el orden: si no abre, se prueba la
    siguiente viva en vez de saltear el par."""
    conexiones, sondeos = _armar(tmp_path, monkeypatch, abierto=lambda ip: ip.startswith("100."))
    ahora = time.time()
    server._beacon_sync_once(_Beacon({"win": {"ips": {"172.17.240.1": ahora, "100.81.147.100": ahora - 1}}}))
    assert sondeos == [("172.17.240.1", 27356), ("100.81.147.100", 27356)]
    assert conexiones[-1] == "100.81.147.100"


def test_sin_conexion_en_uso_tambien_se_sondea(tmp_path, monkeypatch):
    """Al arrancar (sin IP conectada) la puerta del NAT quedaba en peers.json y no se iba mas."""
    conexiones, sondeos = _armar(tmp_path, monkeypatch, abierto=False)
    monkeypatch.setattr(server, "_ip_conectada", {})
    server._beacon_sync_once(_Beacon({"win": {"ips": {"172.17.240.1": time.time()}}}))
    assert sondeos == [("172.17.240.1", 27356)]
    assert fed.get_peer(str(tmp_path / "peers.json"), "win")["ip"] == "192.168.1.72"
