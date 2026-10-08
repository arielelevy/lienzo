"""WebSocket minimo (lienzo/ws.py): tramas, mascara, ping, cierre y limites, sobre un socketpair."""

import socket
import struct
import threading

import pytest
import ws


@pytest.fixture
def pair():
    a, b = socket.socketpair()
    client = ws.Socket(a, a.makefile("rb"), mask=True)
    server = ws.Socket(b, b.makefile("rb"), mask=False)
    yield client, server
    client.close()
    server.close()


def test_accept_key_matches_rfc_example():
    assert ws.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.mark.parametrize("n", [0, 5, 125, 126, 65535, 65536, 300_000])
def test_roundtrip_both_directions_and_sizes(pair, n):
    client, server = pair
    payload = bytes(range(256)) * (n // 256 + 1)
    payload = payload[:n]
    client.send(ws.BINARY, payload)
    assert server.recv() == (ws.BINARY, payload)
    server.send(ws.TEXT, payload)
    assert client.recv() == (ws.TEXT, payload)


def test_client_frames_are_masked_on_the_wire():
    a, b = socket.socketpair()
    try:
        client = ws.Socket(a, a.makefile("rb"), mask=True)
        client.send(ws.TEXT, b"hola")
        raw = b.recv(64)
        assert raw[1] & 0x80 and raw[1] & 0x7F == 4 and raw[6:] != b"hola"
    finally:
        a.close()
        b.close()


def test_ping_is_answered_with_pong_and_skipped(pair):
    client, server = pair
    client.send(ws.PING, b"x")
    client.send(ws.TEXT, b"dato")
    assert server.recv() == (ws.TEXT, b"dato")
    b0, b1 = client.reader.read(2)
    assert b0 & 0x0F == ws.PONG and b1 == 1 and client.reader.read(1) == b"x"


def test_close_frame_ends_recv_with_none(pair):
    client, server = pair
    client.close()
    assert server.recv() is None
    with pytest.raises(ConnectionError):
        client.send(ws.TEXT, b"tarde")


def test_fragments_are_joined(pair):
    client, server = pair
    client.sock.sendall(bytes([0x01, 0x80 | 2]) + b"\0\0\0\0" + b"ab")
    client.sock.sendall(bytes([0x80, 0x80 | 2]) + b"\0\0\0\0" + b"cd")
    assert server.recv() == (ws.TEXT, b"abcd")


def test_oversized_message_is_rejected(pair, monkeypatch):
    client, server = pair
    monkeypatch.setattr(ws, "MAX_MESSAGE", 10)
    with pytest.raises(ValueError):
        server.send(ws.BINARY, b"x" * 11)
    client.sock.sendall(bytes([0x82, 0x80 | 127]) + struct.pack(">Q", 11) + b"\0\0\0\0" + b"x" * 11)
    with pytest.raises(ValueError):
        server.recv()


def test_server_handshake_requires_upgrade_headers():
    class Handler:
        close_connection = False

        def __init__(self):
            self.out = bytearray()
            self.headers = {"Upgrade": "websocket", "Connection": "keep-alive", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "x" * 24}

        def send_response(self, code):
            self.out += f"{code}".encode()

        def send_header(self, *_):
            pass

        def end_headers(self):
            pass

        class wfile:
            @staticmethod
            def write(data):
                pass

            @staticmethod
            def flush():
                pass

    handler = Handler()
    assert ws.server_handshake(handler) is None
    assert handler.out == b"400"


def test_client_connect_against_minimal_server():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    got = {}

    def serve():
        conn, _ = listener.accept()
        reader = conn.makefile("rb")
        request = reader.readline().decode()
        headers = {}
        while (line := reader.readline()) not in (b"\r\n", b""):
            k, _, v = line.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        got.update(request=request, headers=headers)
        conn.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {ws.accept_key(headers['sec-websocket-key'])}\r\n\r\n".encode())
        server = ws.Socket(conn, reader, mask=False)
        assert server.recv() == (ws.TEXT, b"hola")
        server.send(ws.BINARY, b"chau")
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = ws.client_connect("127.0.0.1", listener.getsockname()[1], "/peer/browser/stream/abc", {"X-Lienzo-Peer": "yo"})
    client.send(ws.TEXT, b"hola")
    assert client.recv() == (ws.BINARY, b"chau")
    assert client.recv() is None
    thread.join(5)
    listener.close()
    assert got["request"].startswith("GET /peer/browser/stream/abc HTTP/1.1") and got["headers"]["x-lienzo-peer"] == "yo"
