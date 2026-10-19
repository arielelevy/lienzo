"""Dos procesos aislados para el E2E. Salud fixture; HTTP, HMAC, SSE y puente reales."""

import json
import os
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))

import identity
import server
import state

other = sys.argv[1]
server.health.snapshot = lambda: {"protocol_version": 1, "fixture_pc": identity.pc_id()}


class Board(server.Handler):
    def do_GET(self):
        if self.path == "/test/forward-health":
            code, body = server.mirror.MIRROR.forward(other, "GET", "/health")
            return self._json(code, body)
        return super().do_GET()


peer = server.QuietServer(("127.0.0.1", 0), server.PeerHandler)
board = server.QuietServer(("127.0.0.1", 0), Board)


class NativeFixture:
    """Sustituye el programa externo; el supervisor y los puentes son reales."""

    def __init__(self, profile):
        self.dead = threading.Event()
        self.error = None

    def start(self):
        pass

    def send(self, message):
        pass

    def snapshot(self):
        path = Path(state.LIENZO) / "network.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def tunnel(self, host, port, timeout=5):
        peer = server.federation.get_peer(server.PEERS_FILE, other)
        if host != "100.81.147.100" or port != peer["port"]:
            raise ConnectionRefusedError("nodo fixture sin listener")
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)

    def close(self):
        self.dead.set()


if os.environ.get("LIENZO_TEST_AUTO_HOST") == "1":
    server.tailchrome_process._service = server.tailchrome_process.Service(
        board.server_port, host_factory=NativeFixture
    )
server.tailchrome_process.service(board.server_port).autostart()
for instance in (peer, board):
    instance.daemon_threads = True
    threading.Thread(target=instance.serve_forever, daemon=True).start()
# Registro inicial caído: la prueba debe abrir el puente para tener comunicación.
server.mirror.MIRROR.connect(other, {"name": other}, "127.0.0.1", 1, b"k" * 32, identity.pc_id())
print(json.dumps({"board": board.server_port, "peer": peer.server_port}), flush=True)
threading.Event().wait()
