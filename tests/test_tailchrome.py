"""Puente: sockets reales aislados; no conecta la tailnet ni sesiones de Ariel."""

import http.client
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import federation
import pytest
import server
import tailchrome
import ws


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (self.server.label + self.path).encode() * 20000
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def bridges():
    targets = [ThreadingHTTPServer(("127.0.0.1", 0), Echo) for _ in range(2)]
    for target, label in zip(targets, ("A", "B")):
        target.label = label
        threading.Thread(target=target.serve_forever, daemon=True).start()
    left, right = socket.socketpair()
    wires = [ws.Socket(left, left.makefile("rb"), True), ws.Socket(right, right.makefile("rb"), False)]
    logs = []
    pair = [
        tailchrome.Bridge(
            wires[0], b"k" * 32, "a" * 32, True, targets[0].server_address, "A", "B", lambda _: None, logs.append
        ),
        tailchrome.Bridge(
            wires[1], b"k" * 32, "a" * 32, False, targets[1].server_address, "B", "A", lambda _: None, logs.append
        ),
    ]
    # El navegador consume los mensajes de estado; este ensayo une las puntas
    # directamente y omite solamente esos textos informativos.
    for wire in wires:
        original_send = wire.send

        def send(opcode, payload, original=original_send):
            if opcode != ws.TEXT:
                original(opcode, payload)

        wire.send = send
    threads = [threading.Thread(target=bridge.run, daemon=True) for bridge in pair]
    for thread in threads:
        thread.start()
    assert all(bridge.ready.wait(3) for bridge in pair)
    yield pair, logs
    for bridge in pair:
        bridge.close()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    for target in targets:
        target.shutdown()
        target.server_close()


def request(address, path):
    conn = http.client.HTTPConnection(*address, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        assert response.status == 200
        return response.read()
    finally:
        conn.close()


def test_tcp_bidireccional_multiplexado_y_payload_fragmentado(bridges):
    pair, _ = bridges
    with ThreadPoolExecutor(8) as executor:
        jobs = [(executor.submit(request, pair[i % 2].address, f"/{i}"), i) for i in range(8)]
        for job, i in jobs:
            label = "B" if i % 2 == 0 else "A"
            assert job.result() == (label + f"/{i}").encode() * 20000


def test_cierre_de_una_punta_cierra_ambas(bridges):
    pair, _ = bridges
    pair[0].close()
    assert pair[1].closed.wait(3)
    with pytest.raises(OSError):
        socket.create_connection(pair[1].address, timeout=0.5)


def test_no_acepta_apertura_del_mismo_sentido(bridges):
    pair, _ = bridges
    with pytest.raises(ValueError, match="apertura"):
        pair[0]._dispatch(tailchrome.OPEN, 1, b"")


def test_no_acepta_replay_ni_reflexion():
    class Wire:
        def send(self, opcode, payload):
            self.payload = payload

        def recv(self):
            return ws.BINARY, self.payload

    wire = Wire()
    bridge = tailchrome.Bridge(wire, b"k" * 32, "a" * 32, True, ("127.0.0.1", 1), "A", "B", None, print)
    try:
        bridge.send(tailchrome.HELLO, payload=b"A")
        with pytest.raises(ValueError, match="alterado"):
            bridge.receive()  # reflexión: dirección I en lugar de R
        bridge.rx_direction = b"I"
        assert bridge.receive() == (tailchrome.HELLO, 0, b"A")
        with pytest.raises(ValueError, match="alterado"):
            bridge.receive()  # misma secuencia, repetida
    finally:
        bridge.listener.close()


@pytest.fixture
def http_server(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PEERS_FILE", str(tmp_path / "peers.json"))
    federation.add_peer(server.PEERS_FILE, {"pc_id": "other", "ip": "192.168.1.172", "port": 7322, "key": "ab" * 32})
    monkeypatch.setattr(server, "_peer_nonces", federation.NonceCache())
    servers = [server.QuietServer(("127.0.0.1", 0), handler) for handler in (server.Handler, server.PeerHandler)]
    for instance in servers:
        threading.Thread(target=instance.serve_forever, daemon=True).start()
    yield servers
    for instance in servers:
        instance.shutdown()
        instance.server_close()


def get(instance, path, headers=None):
    conn = http.client.HTTPConnection(*instance.server_address, timeout=3)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_endpoints_exigen_origin_y_firma(http_server):
    local, remote = http_server
    assert get(local, "/tailchrome")[0] == 200
    assert get(local, "/tailchrome/stream?pc=other&host=100.81.147.100")[0] == 403
    assert get(remote, "/peer/tailchrome")[0] == 401


@pytest.mark.parametrize("host", ["192.168.1.172", "127.0.0.1", "100.81.147.100:9999", "100.128.0.1"])
def test_el_navegador_no_puede_elegir_destinos_fuera_de_tailscale(http_server, host):
    local, _ = http_server
    headers = {"Origin": f"http://127.0.0.1:{local.server_port}"}
    code, _ = get(local, f"/tailchrome/stream?pc=other&host={host}", headers)
    assert code == 400


def test_segundo_puente_no_reemplaza_el_que_esta_abierto(http_server, monkeypatch):
    local, _ = http_server
    fake = type("Bridge", (), {"closed": threading.Event()})()
    registry = {"other": fake}
    monkeypatch.setattr(server, "_tailchrome_bridges", registry)
    headers = {"Origin": f"http://127.0.0.1:{local.server_port}"}
    code, _ = get(local, "/tailchrome/stream?pc=other&host=100.81.147.100", headers)
    assert code == 409
    assert registry == {"other": fake}


def test_ticket_firmado_solo_vale_una_vez(http_server, monkeypatch):
    from urllib.parse import urlencode

    _, remote = http_server
    seen = []

    def serve(handler, pc_id, nonce, **kwargs):
        seen.append((pc_id, nonce))
        handler._json(200, {"ok": True})

    monkeypatch.setattr(server, "_tailchrome_serve", serve)
    conn = federation.PeerConn("127.0.0.1", 1, bytes.fromhex("ab" * 32), "other")
    ticket = federation.signed_headers(conn, "GET", tailchrome.PATH, b"")
    path = tailchrome.PATH + "?" + urlencode(ticket)
    assert get(remote, path)[0] == 200
    assert seen == [("other", ticket["X-Lienzo-Nonce"])]
    assert get(remote, path)[0] == 401


def test_puente_no_persiste_ruta_efimera(tmp_path, monkeypatch):
    path = str(tmp_path / "peers.json")
    peer = {"pc_id": "other", "ip": "192.168.1.172", "port": 7322, "key": "ab" * 32}
    federation.add_peer(path, peer)
    before = Path(path).read_bytes()
    ready = threading.Event()
    ready.set()
    fake = type("Bridge", (), {"address": ("127.0.0.1", 12345), "ready": ready, "closed": threading.Event()})()
    monkeypatch.setattr(server, "_tailchrome_bridges", {"other": fake})
    calls = []
    monkeypatch.setattr(server.mirror.MIRROR, "connect", lambda *args: calls.append(args))
    monkeypatch.setattr(server, "_ip_conectada", {})
    server._connect_peer_from_record(peer)
    assert calls[0][2:4] == ("127.0.0.1", 12345)
    assert Path(path).read_bytes() == before
    fake.closed.set()
    server._connect_peer_from_record(peer)
    assert calls[1][2:4] == ("192.168.1.172", 7322)
