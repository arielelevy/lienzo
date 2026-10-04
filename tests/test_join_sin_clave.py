"""POST /peers/join no devuelve la clave del par (medido el 2026-10-04: la respuesta la traia en
claro y quedo en la salida de quien emparejo)."""

import http.client
import json
import os
import socket
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import server


def test_join_no_devuelve_la_clave(monkeypatch):
    registro = {"pc_id": "abc", "name": "otra", "ip": "10.0.0.2", "port": 7322, "key": "ff" * 32}
    monkeypatch.setattr(server.pairing, "join", lambda phrase, host, port: dict(registro))
    monkeypatch.setattr(server, "_connect_peer_from_record", lambda peer: None)
    monkeypatch.setattr(server, "log", lambda m: None)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"phrase": "palabra", "host": "10.0.0.2", "port": 7322})
        c.request("POST", "/peers/join", body=body, headers={"X-Lienzo": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        out = json.loads(r.read())
        assert r.status == 200 and out["pc_id"] == "abc"
        assert "key" not in out and "ff" * 32 not in json.dumps(out)
    finally:
        srv.shutdown()
