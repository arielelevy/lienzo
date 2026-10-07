"""Tailscale y el diagnostico de un peer que no llega (red.py, 2026-10-05), y lo que cambia por eso
en el beacon (anuncios a la tailnet), peers.json (`ips`) y server.py (con cual direccion conectar)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lienzo"))

import beacon
import federation as fed
import red
import server

STATUS = {
    "Self": {"HostName": "ariel", "TailscaleIPs": ["100.101.1.1", "fd7a:115c:a1e0::1"], "Online": True},
    "Peer": {
        "nodekey:a": {"HostName": "ar-it33940", "TailscaleIPs": ["100.88.2.3", "fd7a:115c:a1e0::2"], "Online": True},
        "nodekey:b": {"HostName": "apagada", "TailscaleIPs": ["100.77.4.5"], "Online": False},
        "nodekey:c": {"HostName": "sin-dato", "TailscaleIPs": ["100.66.6.7"]},
    },
}


def test_las_ip_de_tailscale_son_las_del_rango_cgnat():
    assert red.es_tailscale("100.88.2.3")
    assert red.es_tailscale("100.127.255.254")
    assert not red.es_tailscale("100.128.0.1")
    assert not red.es_tailscale("192.168.50.193")
    assert not red.es_tailscale("basura")


def test_status_de_tailscale_da_las_ipv4_de_los_peers_en_linea_sin_la_propia():
    assert red.parse_status(json.dumps(STATUS)) == ["100.66.6.7", "100.88.2.3"]


def test_status_roto_o_vacio_no_da_nada():
    assert red.parse_status("no es json") == []
    assert red.parse_status("[]") == []
    assert red.parse_status(json.dumps({"Self": {}})) == []


def test_sin_tailscale_instalado_la_tailnet_esta_vacia(monkeypatch):
    monkeypatch.setattr(red, "_cache", (0.0, []))
    monkeypatch.setattr(red, "_tailscale_exe", lambda: None)
    assert red.tailnet_ips(ahora=1000.0) == []


def test_la_tailnet_se_pregunta_una_vez_por_minuto(monkeypatch):
    monkeypatch.setattr(red, "_cache", (0.0, []))
    monkeypatch.setattr(red, "_tailscale_exe", lambda: "tailscale")
    llamadas = []

    def correr(argv, timeout):
        llamadas.append(argv)
        return 0, json.dumps(STATUS), ""

    monkeypatch.setattr(red.subproc, "correr", correr)
    assert red.tailnet_ips(ahora=1000.0) == ["100.66.6.7", "100.88.2.3"]
    assert red.tailnet_ips(ahora=1030.0) == ["100.66.6.7", "100.88.2.3"]
    assert len(llamadas) == 1
    red.tailnet_ips(ahora=1061.0)
    assert len(llamadas) == 2


# --- diagnostico -------------------------------------------------------------------------------


def _timeout():
    return TimeoutError("timed out")


def test_sin_arp_no_afirma_aislamiento_ni_manda_a_tailscale():
    """2026-10-07: la tira decia «Wi-Fi público, usá Tailscale» con las dos PCs en la red de casa.
    Sin ARP tambien es una PC apagada o dormida."""
    d = red.diagnosticar("192.168.50.193", _timeout(), propias=["192.168.50.64"], arp=lambda ip: False)
    assert d is not None and d.startswith("sin ARP") and "apagada" in d
    assert "Tailscale" not in d and "público" not in d


def test_con_arp_y_sin_respuesta_es_el_firewall():
    d = red.diagnosticar("192.168.50.193", _timeout(), propias=["192.168.50.64"], arp=lambda ip: True)
    assert d is not None and "firewall" in d


def test_conexion_rechazada_es_el_puerto_cerrado():
    d = red.diagnosticar("192.168.50.193", ConnectionRefusedError(), propias=["192.168.50.64"], arp=lambda ip: True)
    assert d is not None and "puerto" in d and "no corre el lienzo" in d


def test_la_ip_vieja_de_otra_red():
    d = red.diagnosticar("192.168.1.63", _timeout(), propias=["192.168.50.64"], arp=lambda ip: None)
    assert d is not None and "192.168.1.63" in d and "otra red" in d


def test_por_tailscale_no_se_mira_arp():
    def arp(ip):
        raise AssertionError("una IP de Tailscale no tiene ARP")

    d = red.diagnosticar("100.88.2.3", _timeout(), propias=["192.168.50.64"], arp=arp)
    assert d is not None and "Tailscale" in d


def test_un_error_que_no_es_de_red_no_tiene_diagnostico():
    assert (
        red.diagnosticar("192.168.50.193", OSError("cuerpo roto"), propias=["192.168.50.64"], arp=lambda ip: False)
        is None
    )
    assert red.diagnosticar("192.168.50.193", fed.PeerError("401"), propias=["192.168.50.64"]) is None


def test_host_inalcanzable_cuenta_como_que_no_llega():
    e = OSError(65, "No route to host")
    d = red.diagnosticar("192.168.50.193", e, propias=["192.168.50.64"], arp=lambda ip: False)
    assert d is not None and d.startswith("sin ARP")


# --- peers.json: mas de una direccion ------------------------------------------------------------


def test_cada_direccion_nueva_se_suma_sin_pisar_la_del_espejo(tmp_path):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, {"pc_id": "p1", "key": "00" * 32, "ip": "192.168.50.193", "port": 7322})
    fed.note_peer_address(path, "p1", "192.168.50.193")
    fed.note_peer_address(path, "p1", "100.88.2.3")
    fed.note_peer_address(path, "p1", "192.168.50.193")
    peer = fed.get_peer(path, "p1")
    assert peer["ip"] == "192.168.50.193"
    assert peer["ips"] == ["192.168.50.193", "100.88.2.3"]


def test_se_guardan_las_ultimas_direcciones(tmp_path):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, {"pc_id": "p1", "key": "00" * 32, "ip": "", "port": 7322})
    for h in range(1, 7):
        fed.note_peer_address(path, "p1", f"10.0.0.{h}")
    peer = fed.get_peer(path, "p1")
    assert peer["ips"] == ["10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6"]
    assert peer["ip"] == "10.0.0.1", "la que ofrecio la frase (ip vacia) se queda con la primera que aparecio"


def test_un_peer_desconocido_no_se_anota(tmp_path):
    path = str(tmp_path / "peers.json")
    assert fed.note_peer_address(path, "nadie", "10.0.0.1") is False


# --- con cual direccion conecta el espejo -------------------------------------------------------


def test_mientras_la_conectada_siga_viva_no_se_cambia():
    info = {"ips": {"192.168.50.193": 100.0, "100.88.2.3": 101.0}}
    assert server.elegir_direccion(info, "100.88.2.3", 110.0, 35.0) is None
    assert server.elegir_direccion(info, "192.168.50.193", 110.0, 35.0) is None


def test_si_la_conectada_murio_se_prefiere_la_lan():
    info = {"ips": {"192.168.50.193": 100.0, "100.88.2.3": 101.0, "192.168.1.63": 10.0}}
    assert server.elegir_direccion(info, "192.168.1.63", 110.0, 35.0) == "192.168.50.193"


def test_sin_lan_viva_va_por_tailscale():
    info = {"ips": {"192.168.50.193": 10.0, "100.88.2.3": 101.0}}
    assert server.elegir_direccion(info, "192.168.50.193", 110.0, 35.0) == "100.88.2.3"


def test_sin_ninguna_viva_no_se_toca_nada():
    info = {"ips": {"192.168.50.193": 10.0}}
    assert server.elegir_direccion(info, None, 110.0, 35.0) is None


# --- el beacon anuncia por la tailnet -----------------------------------------------------------


def test_cada_anuncio_sale_tambien_a_cada_equipo_de_la_tailnet(tmp_path, monkeypatch):
    monkeypatch.setattr(beacon.state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(beacon, "_ipv4_propias", lambda: ["192.168.50.64"])
    fed.add_peer(beacon._peers_path(), {"pc_id": "p1", "key": ("ab" * 32), "ip": "", "port": 7322})
    enviados = []

    class _Sock:
        def sendto(self, data, addr):
            enviados.append(addr[0])

    beacon._enviar(_Sock(), 7323, 7322, beacon.BROADCAST_LIMITADO, tailnet=["100.88.2.3"])
    assert enviados.count("100.88.2.3") == 2, "el anuncio sin firma y el firmado del par"
    assert "255.255.255.255" in enviados and "192.168.50.255" in enviados


def test_la_ip_de_tailscale_no_es_una_lan_para_broadcast_ni_barrido(monkeypatch):
    infos = [(2, 2, 17, "", (ip, 0)) for ip in ("192.168.50.64", "100.101.1.1", "127.0.0.1")]
    monkeypatch.setattr(beacon.socket, "getaddrinfo", lambda *a, **k: infos)
    assert beacon._ipv4_propias() == ["192.168.50.64"]
