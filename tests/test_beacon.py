"""Tests de lienzo/beacon.py (plan-multi-pc-2026-09-26.md, ronda 2 encargo A): el anuncio y la
recepcion se prueban con sockets UDP reales en 127.0.0.1 y puertos altos inyectables (nunca el
7323 real, para no pisarse entre corridas ni con la LAN de verdad). El hilo se prueba aparte:
nunca tiene que levantar una excepcion, ni siquiera si el puerto ya esta ocupado.

Una prueba real de dos beacons descubriendose entre PCs (cada uno con su propio LIENZO_HOME al
mismo tiempo) queda afuera: el UDP de Windows entrega un datagrama unicast a un solo socket entre
los que comparten puerto con SO_REUSEADDR, asi que dos procesos escuchando el mismo puerto en
127.0.0.1 dan un resultado no determinista. Eso se prueba de verdad en la notebook (plan F1,
cierre), no en CI. Ver docs/ronda2/notas-A.md.
"""

import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import beacon
import federation as fed
import identity as idn
import state as st


@pytest.fixture
def hogar(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / "estado"))
    os.makedirs(st.LIENZO, exist_ok=True)  # add_peer no crea la carpeta: la crea identity al arrancar
    idn._repo_cache.clear()
    beacon._seen.clear()
    return tmp_path


def _puerto_libre() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


# --- _recibir / seen(), a nivel de socket, sin el hilo -------------------------------------------


def test_recibir_un_beacon_valido_actualiza_la_ip_y_seen(hogar):
    key = b"k" * 32
    fed.add_peer(
        beacon._peers_path(),
        {"pc_id": "peer-remoto1", "name": "notebook", "ip": "10.0.0.1", "port": 7322, "key": key.hex()},
    )
    paquete = fed.encode_signed_beacon(key, "peer-remoto1", "notebook", 7322)

    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        emisor.sendto(paquete, ("127.0.0.1", receptor.getsockname()[1]))
        beacon._recibir(receptor)
    finally:
        emisor.close()
        receptor.close()

    peer = next(p for p in fed.list_peers(beacon._peers_path()) if p["pc_id"] == "peer-remoto1")
    assert peer["ip"] == "127.0.0.1"
    assert beacon.seen()["peer-remoto1"]["ip"] == "127.0.0.1"


def test_recibir_beacon_de_un_peer_desconocido_no_rompe_ni_actualiza_nada(hogar):
    key = b"k" * 32
    paquete = fed.encode_signed_beacon(key, "nadie-lo-conoce", "x", 7322)
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        emisor.sendto(paquete, ("127.0.0.1", receptor.getsockname()[1]))
        beacon._recibir(receptor)
    finally:
        emisor.close()
        receptor.close()
    assert beacon.seen() == {}


def test_recibir_basura_no_rompe(hogar):
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        emisor.sendto(b"esto no es un beacon", ("127.0.0.1", receptor.getsockname()[1]))
        beacon._recibir(receptor)  # no debe levantar
    finally:
        emisor.close()
        receptor.close()
    assert beacon.seen() == {}


def test_recibir_sin_nada_en_el_socket_no_bloquea(hogar):
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(0.2)
    try:
        t0 = time.perf_counter()
        beacon._recibir(receptor)  # nada llego: vuelve por el timeout, no se cuelga
        assert time.perf_counter() - t0 < 1.0
    finally:
        receptor.close()


def test_enviar_manda_un_paquete_firmado_por_cada_peer(hogar):
    key1, key2 = b"1" * 32, b"2" * 32
    fed.add_peer(beacon._peers_path(), {"pc_id": "peer-uno1111", "name": "a", "key": key1.hex()})
    fed.add_peer(beacon._peers_path(), {"pc_id": "peer-dos2222", "name": "b", "key": key2.hex()})

    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    puerto_receptor = receptor.getsockname()[1]
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emisor.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        beacon._enviar(emisor, puerto_receptor, 7322, "127.0.0.1")
        # el anuncio sin firma (descubrimiento) y uno firmado por cada peer
        recibidos = [receptor.recvfrom(4096)[0] for _ in range(3)]
    finally:
        emisor.close()
        receptor.close()

    decodificados_con_key1 = [fed.decode_signed_beacon(key1, d) for d in recibidos]
    decodificados_con_key2 = [fed.decode_signed_beacon(key2, d) for d in recibidos]
    assert any(d is not None for d in decodificados_con_key1)
    assert any(d is not None for d in decodificados_con_key2)


def test_enviar_sin_peers_manda_solo_el_anuncio_sin_firma(hogar):
    # sin nadie emparejado igual se anuncia: es lo que hace que la otra PC la vea en la LAN
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emisor.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        beacon._enviar(emisor, receptor.getsockname()[1], 7322, "127.0.0.1")
        data, _addr = receptor.recvfrom(4096)
        receptor.settimeout(0.3)
        with pytest.raises(TimeoutError):
            receptor.recvfrom(4096)
    finally:
        emisor.close()
        receptor.close()
    anuncio = fed.decode_beacon(data)
    assert anuncio["pc_id"] == idn.pc_id() and anuncio["port"] == 7322


def test_enviar_con_key_corrupta_sigue_con_el_resto(hogar):
    fed.add_peer(beacon._peers_path(), {"pc_id": "peer-malo1111", "name": "malo", "key": "esto no es hex"})
    fed.add_peer(beacon._peers_path(), {"pc_id": "peer-ok11111111", "name": "ok", "key": ("a" * 64)})
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    puerto_receptor = receptor.getsockname()[1]
    emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emisor.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        beacon._enviar(emisor, puerto_receptor, 7322, "127.0.0.1")  # el corrupto no debe frenar al bueno
        recibidos = [receptor.recvfrom(4096)[0] for _ in range(2)]  # sin firma + el del peer bueno
    finally:
        emisor.close()
        receptor.close()
    assert any(fed.decode_signed_beacon(bytes.fromhex("a" * 64), d) is not None for d in recibidos)


# --- el hilo: start()/stop_event, nunca levanta excepcion ----------------------------------------


def test_start_devuelve_un_hilo_vivo_y_stop_event_lo_frena(hogar):
    stop = threading.Event()
    hilo = beacon.start(7322, stop, udp_port=_puerto_libre(), interval_s=0.1, broadcast_addr="127.0.0.1")
    try:
        assert isinstance(hilo, threading.Thread)
        assert hilo.is_alive()
        time.sleep(0.05)
    finally:
        stop.set()
        hilo.join(timeout=5)
    assert not hilo.is_alive()


def test_start_nunca_explota_si_no_puede_abrir_el_socket(hogar, monkeypatch):
    """Windows deja pisar un puerto ya bindeado con SO_REUSEADDR (a diferencia de Linux), asi que
    forzar un choque real de puertos no es fiable para este test: se mockea _abrir_socket para
    forzar el fallo y probar que start() lo absorbe sin tirar la excepcion fuera del hilo."""

    def _falla(_puerto):
        raise OSError("puerto ocupado (simulado)")

    monkeypatch.setattr(beacon, "_abrir_socket", _falla)
    stop = threading.Event()
    hilo = beacon.start(7322, stop, udp_port=12345, interval_s=0.1, broadcast_addr="127.0.0.1")
    hilo.join(timeout=3)
    assert not hilo.is_alive()  # el hilo termino solo: no bloqueo, no crasheo el proceso


def test_start_con_un_peer_se_escucha_a_si_mismo_y_actualiza_seen(hogar):
    """Ciclo completo con el hilo real: un peer emparejado, un intervalo bien corto, y el mismo
    socket que emite tambien recibe (loopback a 127.0.0.1): alcanza para probar que start() junta
    _enviar y _recibir sin ayuda manual, sin depender de un segundo proceso. El peer registrado es
    uno mismo (mismo pc_id): asi el beacon que se manda y que se escucha a si mismo pasa el chequeo
    de que el anuncio diga ser quien tiene esa clave."""
    key = b"k" * 32
    mi_pc_id = idn.pc_id()
    fed.add_peer(beacon._peers_path(), {"pc_id": mi_pc_id, "name": "espejo", "key": key.hex()})
    puerto_udp = _puerto_libre()
    stop = threading.Event()
    hilo = beacon.start(7322, stop, udp_port=puerto_udp, interval_s=0.05, broadcast_addr="127.0.0.1")
    try:
        deadline = time.time() + 3
        while mi_pc_id not in beacon.seen() and time.time() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        hilo.join(timeout=5)
    assert beacon.seen().get(mi_pc_id, {}).get("ip") == "127.0.0.1"


# --- descubrimiento: todas las PCs de la LAN con el lienzo, emparejadas o no --------------------


class _SocketDeUnPaquete:
    def __init__(self, data: bytes, ip: str):
        self.data, self.ip = data, ip

    def recvfrom(self, _n):
        return self.data, (self.ip, 7323)


def test_un_anuncio_sin_firma_de_otra_pc_queda_descubierto(hogar, monkeypatch):
    monkeypatch.setattr(beacon, "_descubiertas", {})
    beacon._recibir(_SocketDeUnPaquete(fed.encode_beacon("0123456789ab", "notebook", 7322), "192.168.1.20"))
    (pc,) = beacon.discovered()
    assert (pc["pc_id"], pc["name"], pc["ip"], pc["port"]) == ("0123456789ab", "notebook", "192.168.1.20", 7322)
    assert fed.list_peers(beacon._peers_path()) == [], "descubrir no empareja"


def test_el_anuncio_propio_no_se_descubre(hogar, monkeypatch):
    monkeypatch.setattr(beacon, "_descubiertas", {})
    beacon._recibir(_SocketDeUnPaquete(fed.encode_beacon(idn.pc_id(), "yo", 7322), "192.168.1.10"))
    assert beacon.discovered() == []


def test_una_pc_que_dejo_de_anunciar_se_va_de_la_lista(hogar, monkeypatch):
    monkeypatch.setattr(beacon, "_descubiertas", {})
    beacon._recibir(_SocketDeUnPaquete(fed.encode_beacon("0123456789ab", "notebook", 7322), "192.168.1.20"))
    assert beacon.discovered(max_age_s=60) != []
    beacon._descubiertas["0123456789ab"]["last_seen"] -= 120
    assert beacon.discovered(max_age_s=60) == []


# --- broadcast dirigido, barrido unicast y respuesta (2026-10-05) ---------------------------------


def test_con_el_broadcast_limitado_sale_tambien_el_dirigido_de_cada_red_propia():
    ips = ["192.168.50.64", "172.17.240.1", "192.168.50.70"]
    assert beacon.destinos(beacon.BROADCAST_LIMITADO, ips) == [
        "255.255.255.255",
        "172.17.240.255",
        "192.168.50.255",
    ]


def test_con_otra_direccion_sale_solo_esa():
    assert beacon.destinos("127.0.0.1", ["192.168.50.64"]) == ["127.0.0.1"]


def test_el_barrido_cubre_la_24_propia_sin_la_ip_propia():
    objetivos = beacon.objetivos_barrido(["192.168.50.64"])
    assert len(objetivos) == 253
    assert "192.168.50.64" not in objetivos
    assert objetivos[0] == "192.168.50.1" and objetivos[-1] == "192.168.50.254"


def _par(hogar, pc_id="peer-remoto1"):
    key = b"k" * 32
    fed.add_peer(
        beacon._peers_path(),
        {"pc_id": pc_id, "name": "notebook", "ip": "192.168.1.63", "port": 7322, "key": key.hex()},
    )
    return key


def test_faltan_los_peers_sin_beacon_reciente(hogar):
    _par(hogar)
    assert [p["pc_id"] for p in beacon.faltantes()] == ["peer-remoto1"]
    beacon._seen["peer-remoto1"] = {"ip": "192.168.50.193", "last_seen": time.time()}
    assert beacon.faltantes() == []
    beacon._seen["peer-remoto1"]["last_seen"] -= beacon.DISCOVERED_TTL_S + 1
    assert [p["pc_id"] for p in beacon.faltantes()] == ["peer-remoto1"]


def test_un_peer_que_reaparece_recibe_respuesta_una_sola_vez(hogar):
    key = _par(hogar)
    respuestas = []

    def responder(peer, addr):
        respuestas.append((peer["pc_id"], addr[0]))

    paquete = fed.encode_signed_beacon(key, "peer-remoto1", "notebook", 7322)
    beacon._recibir(_SocketDeUnPaquete(paquete, "192.168.50.193"), responder)
    time.sleep(0.01)  # el ts firmado tiene que crecer entre los dos beacons
    otro = fed.encode_signed_beacon(key, "peer-remoto1", "notebook", 7322)
    beacon._recibir(_SocketDeUnPaquete(otro, "192.168.50.193"), responder)

    assert respuestas == [("peer-remoto1", "192.168.50.193")]
    peer = next(p for p in fed.list_peers(beacon._peers_path()) if p["pc_id"] == "peer-remoto1")
    assert peer["ip"] == "192.168.50.193"


def test_el_barrido_manda_el_beacon_firmado_de_cada_faltante_a_cada_host(hogar, monkeypatch):
    _par(hogar)
    monkeypatch.setattr(beacon, "_ipv4_propias", lambda: ["192.168.50.64"])
    enviados = []

    class _Sock:
        def sendto(self, data, addr):
            enviados.append(addr)

    assert beacon._barrer(_Sock(), 7323, 7322) == 253
    assert ("192.168.50.193", 7323) in enviados
    beacon._seen["peer-remoto1"] = {"ip": "192.168.50.193", "last_seen": time.time()}
    assert beacon._barrer(_Sock(), 7323, 7322) == 0
