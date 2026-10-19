"""Dos procesos aislados para el E2E. Salud fixture; HTTP, HMAC, SSE y puente reales."""

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))

import identity
import server

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
for instance in (peer, board):
    instance.daemon_threads = True
    threading.Thread(target=instance.serve_forever, daemon=True).start()
# Registro inicial caído: la prueba debe abrir el puente para tener comunicación.
server.mirror.MIRROR.connect(other, {"name": other}, "127.0.0.1", 1, b"k" * 32, identity.pc_id())
print(json.dumps({"board": board.server_port, "peer": peer.server_port}), flush=True)
threading.Event().wait()
