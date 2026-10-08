"""Canal vivo de Chrome remoto (browser_stream.py): sellado por sentido, validacion de pedidos y
registros del worker. Sin sockets reales ni Chrome."""

import io
import json
import struct
from types import SimpleNamespace

import browser_stream as module
import pytest
import ws


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.pinging = False

    def pings(self, interval_s=20.0):
        self.pinging = True

    def send(self, opcode, payload):
        self.sent.append((opcode, payload))

    def close(self):
        self.closed = True


def test_channel_key_depends_on_pair_key_and_channel_id():
    pair = bytes(range(32))
    assert module.channel_key(pair, "a" * 32) != module.channel_key(pair, "b" * 32)
    assert module.channel_key(pair, "a" * 32) != module.channel_key(bytes(32), "a" * 32)


def test_sealed_roundtrip_keeps_kind_and_order():
    key = module.channel_key(bytes(range(32)), "c" * 32)
    viewer, owner = module.Sealed(key, b">", b"<"), module.Sealed(key, b"<", b">")
    sock = FakeSocket()
    viewer.seal(sock, ws.TEXT, b'{"t":"ack"}')
    viewer.seal(sock, ws.BINARY, b"\x89PNG")
    assert all(op == ws.BINARY and b"PNG" not in payload and b"ack" not in payload for op, payload in sock.sent)
    assert owner.open(sock.sent[0][1]) == (ws.TEXT, b'{"t":"ack"}')
    assert owner.open(sock.sent[1][1]) == (ws.BINARY, b"\x89PNG")


def test_replayed_or_reordered_message_is_rejected():
    key = module.channel_key(bytes(range(32)), "d" * 32)
    viewer, owner = module.Sealed(key, b">", b"<"), module.Sealed(key, b"<", b">")
    sock = FakeSocket()
    viewer.seal(sock, ws.TEXT, b"uno")
    viewer.seal(sock, ws.TEXT, b"dos")
    with pytest.raises(ValueError):
        owner.open(sock.sent[1][1])  # el segundo antes que el primero
    fresh = module.Sealed(key, b"<", b">")
    assert fresh.open(sock.sent[0][1]) == (ws.TEXT, b"uno")
    with pytest.raises(ValueError):
        fresh.open(sock.sent[0][1])  # repetido


def test_wrong_direction_does_not_verify():
    key = module.channel_key(bytes(range(32)), "e" * 32)
    sock = FakeSocket()
    module.Sealed(key, b">", b"<").seal(sock, ws.TEXT, b"x")
    with pytest.raises(ValueError):
        module.Sealed(key, b">", b"<").open(sock.sent[0][1])


@pytest.mark.parametrize("payload", [b"[]", b"42", b'{"a":1}', b'{"t":1}', b"{" * 10, pytest.param(b"x" * 70000, id="grande")])
def test_invalid_commands_rejected_before_reaching_worker(payload):
    with pytest.raises((ValueError, UnicodeDecodeError)):
        module._command(payload)


def test_command_becomes_single_ascii_line():
    line = module._command('{"t":"input","events":[{"kind":"text","text":"ñandú\\n"}]}'.encode())
    assert line.endswith(b"\n") and line.count(b"\n") == 1 and line.isascii()
    assert json.loads(line)["events"][0]["text"] == "ñandú\n"


def test_worker_records_are_delivered_by_kind_and_exit_is_reported():
    frame = struct.pack(">IHHHHHHB", 1, 0, 0, 2, 2, 2, 2, 1) + b"\x89PNG"
    out = io.BytesIO(module.RECORD.pack(len(frame) + 1, ord("F")) + frame + module.RECORD.pack(3, ord("J")) + b"{}" + b"\x00\x00")
    delivered, exited = [], []
    worker = module.Worker.__new__(module.Worker)
    worker.process = SimpleNamespace(stdout=out)
    worker.deliver = lambda kind, payload: delivered.append((kind, payload))
    worker.on_exit = lambda: exited.append(True)
    worker._read()
    assert delivered[:2] == [(ws.BINARY, frame), (ws.TEXT, b"{}")]
    assert delivered[2][0] == ws.TEXT and b"Se cerr" in delivered[2][1]
    assert exited == [True]


def test_run_worker_reports_when_sessions_are_exhausted(monkeypatch):
    monkeypatch.setattr(module, "_sessions", module.MAX_SESSIONS)
    sock = FakeSocket()
    module._run_worker(sock, sock.send, lambda: pytest.fail("no debe leer"))
    assert sock.sent and b"demasiadas vistas" in sock.sent[0][1]
    assert module._sessions == module.MAX_SESSIONS


def test_viewer_without_destination_gets_an_error(monkeypatch):
    sock = FakeSocket()
    monkeypatch.setattr(module.ws, "server_handshake", lambda handler: sock)
    module.serve_viewer(object(), "")
    assert sock.sent[0][0] == ws.TEXT and b"PC" in sock.sent[0][1] and sock.closed and sock.pinging


def test_relay_refuses_unpaired_or_old_peer(monkeypatch):
    sock = FakeSocket()
    monkeypatch.setattr(module.mirror.MIRROR, "conn_of", lambda pc: None)
    module._relay(sock, "nadie")
    assert b"emparejada" in sock.sent[-1][1]
    monkeypatch.setattr(module.mirror.MIRROR, "conn_of", lambda pc: SimpleNamespace(key=bytes(32), host="h", port=1))
    monkeypatch.setattr(module.mirror.MIRROR, "supports", lambda pc, cap: False)
    module._relay(sock, "vieja")
    assert b"Actualiz" in sock.sent[-1][1]


def test_peer_channel_id_must_be_hex_of_32():
    replies = []
    handler = SimpleNamespace(_json=lambda code, body: replies.append((code, body)))
    module.serve_peer(handler, bytes(32), "corto")
    module.serve_peer(handler, None, "a" * 32)
    assert [code for code, _ in replies] == [400, 400]
