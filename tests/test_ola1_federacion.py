"""Plan de refactor 2026-10-04, la parte de federacion (federation, mirror, rules, beacon, identity,
procinfo, coordinar): cada prueba reproduce un hallazgo de la revision antes de su arreglo. Usa los
modulos sueltos (lienzo/ en el sys.path, lo agrega conftest.py), igual que el server, y no importa
server.py."""

import http.server
import threading
import time

import federation as fed
import mirror as mi
import pytest


def _server(handler):
    """Un ThreadingHTTPServer en 127.0.0.1 con un puerto libre, ya sirviendo. Devuelve (server, cerrar)."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()

    def cerrar():
        srv.shutdown()
        srv.server_close()
        hilo.join(timeout=5)

    return srv, cerrar


def _esperar(cond, timeout=5.0):
    limite = time.time() + timeout
    while time.time() < limite:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# --- 0.9: el espejo de una PC se congela y se ve vivo ------------------------------------------


class _HandlerRoto(http.server.BaseHTTPRequestHandler):
    """/nojson contesta 200 con un cuerpo que no es JSON; /corto promete 100 bytes y manda 10."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/nojson":
            data = b"<html>no soy json</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'{"a": 1234')
            self.wfile.flush()
            self.close_connection = True


@pytest.mark.parametrize("ruta", ["/nojson", "/corto"])
def test_respuesta_rota_de_un_peer_es_peer_error_que_es_oserror(ruta):
    """Antes salia ValueError (JSON) o IncompleteRead (HTTPException): nadie los atrapaba."""
    srv, cerrar = _server(_HandlerRoto)
    try:
        peer = fed.PeerConn(*srv.server_address, key=b"k" * 32)
        with pytest.raises(fed.PeerError) as info:
            fed.HTTPTransport(timeout=2).get(peer, ruta)
        assert isinstance(info.value, OSError)
    finally:
        cerrar()


class _HandlerDosConexiones(http.server.BaseHTTPRequestHandler):
    """Primera conexion: un evento y se queda abierta (el cliente revienta procesandolo). Segunda:
    otro evento y espera a que el test termine."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        est = self.server.est
        with est["lock"]:
            n = est["conexiones"]
            est["conexiones"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(f'data: {{"n": {n}}}\n\n'.encode())
        self.wfile.flush()
        est["fin"].wait(timeout=5)


def test_sse_sigue_vivo_si_on_event_revienta_y_lo_avisa_una_vez():
    srv, cerrar = _server(_HandlerDosConexiones)
    srv.est = {"lock": threading.Lock(), "conexiones": 0, "fin": threading.Event()}
    eventos, log = [], []

    def on_event(ev):
        eventos.append(ev)
        if ev["n"] == 0:
            raise RuntimeError("bug en on_change")

    cliente = fed.SSEClient(
        *srv.server_address,
        "/peer/events",
        headers_fn=dict,
        on_event=on_event,
        backoff=lambda i: 0.0,
        log=log.append,
    )
    cliente.start()
    try:
        assert _esperar(lambda: len(eventos) >= 2), "el hilo SSE murio con la primera excepcion"
    finally:
        srv.est["fin"].set()
        cliente.stop()
        cerrar()
    assert [e["n"] for e in eventos][:2] == [0, 1]
    avisos = [m for m in log if m.startswith("SSE de") and "bug en on_change" in m]
    assert len(avisos) == 1  # el motivo, una vez (mas el traceback aparte)
    assert any("Traceback" in m for m in log)


class _Transporte:
    def __init__(self, salud):
        self.salud = salud  # lista de lo que devuelve cada get: un valor, o una excepcion
        self.llamadas = 0

    def get(self, peer, path):
        self.llamadas += 1
        r = self.salud[min(self.llamadas - 1, len(self.salud) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    def request(self, peer, method, path, body=None):
        r = self.get(peer, path)
        return (r[0], r[1]) if isinstance(r, tuple) else (200, r)

    def subscribe(self, peer, path, on_event, on_reconnect=None, backoff=None):
        class _C:
            def stop(self, timeout=5.0):
                pass

        return _C()


def test_hilo_de_salud_sobrevive_a_una_excepcion_que_no_es_oserror(monkeypatch):
    monkeypatch.setattr(mi, "HEALTH_EVERY_S", 0.02)
    t = _Transporte([RuntimeError("raro"), RuntimeError("raro"), {"cpu_pct": 1.0}])
    m = mi.Mirror(transport=t)
    log = []
    m.log = log.append
    m.connect("p1", {"name": "notebook"}, "h", 1, b"k" * 32, "yo")
    try:
        assert _esperar(lambda: m._get("p1") and m._get("p1").health == {"cpu_pct": 1.0})
    finally:
        m.stop()
    assert len([x for x in log if "RuntimeError" in x]) == 1  # dos fallas iguales: un aviso


def test_salud_que_no_es_un_objeto_se_toma_como_falla():
    t = _Transporte([["no", "dict"]])
    m = mi.Mirror(transport=t)
    log = []
    m.log = log.append
    m.connect("p1", {"name": "notebook"}, "h", 1, b"k" * 32, "yo")
    try:
        m._poll_health("p1")
        assert m._get("p1").health is None
        assert any("no es un objeto" in x for x in log)
    finally:
        m.stop()


def test_salud_con_401_no_hace_ver_viva_a_la_pc():
    """Antes el cuerpo del 401 se guardaba como salud y actualizaba last_seen: PC «viva» que no
    aceptaba ni un pedido."""
    t = _Transporte([(401, {"error": "firma invalida: la otra PC no acepta mi firma"})])
    m = mi.Mirror(transport=t)
    log = []
    m.log = log.append
    m.connect("p1", {"name": "notebook"}, "h", 1, b"k" * 32, "yo")
    try:
        m._poll_health("p1")
        pm = m._get("p1")
        assert pm.health is None
        assert pm.last_seen == 0.0
        assert not m.peers_status()[0]["alive"]
        assert any("401" in x and "no acepta mi firma" in x for x in log)
    finally:
        m.stop()


def test_evento_sse_que_no_es_objeto_se_ignora_sin_reventar():
    m = mi.Mirror(transport=_Transporte([{}]))
    log = []
    m.log = log.append
    m.connect("p1", {"name": "notebook"}, "h", 1, b"k" * 32, "yo")
    try:
        pm = m._get("p1")
        m._apply_event(pm, "texto que no era json")
        m._apply_event(pm, "otro")
        m._apply_event(pm, {"type": "session", "session_id": "x", "session": {"session_id": "s1"}})
        assert "s1" in pm.sessions
        assert len(log) == 1  # el mismo tipo raro se avisa una vez
    finally:
        m.stop()
