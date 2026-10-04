"""Plan de refactor 2026-10-04, la parte de federacion (federation, mirror, rules, beacon, identity,
procinfo, coordinar): cada prueba reproduce un hallazgo de la revision antes de su arreglo. Usa los
modulos sueltos (lienzo/ en el sys.path, lo agrega conftest.py), igual que el server, y no importa
server.py."""

import http.server
import os
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


# --- 0.10: el SSE entre PCs reconecta cada pocos segundos -------------------------------------


class _HandlerPing(http.server.BaseHTTPRequestHandler):
    """Un /peer/events de verdad: un ping cada `cada_s` hasta que el test termine."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        est = self.server.est
        with est["lock"]:
            est["conexiones"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            while not est["fin"].wait(est["cada_s"]):
                self.wfile.write(b'data: {"type": "ping"}\n\n')
                self.wfile.flush()
        except OSError:
            pass


def test_sse_no_reconecta_entre_pings_mas_lentos_que_el_timeout_de_conexion():
    """El timeout de conexion (5 s en produccion) quedaba como timeout de lectura y el ping es cada
    15 s: el stream se cortaba y reconectaba solo, perdiendo eventos. Aca a escala: conexion de 1 s,
    ping cada 3 s."""
    srv, cerrar = _server(_HandlerPing)
    srv.est = {"lock": threading.Lock(), "conexiones": 0, "fin": threading.Event(), "cada_s": 3.0}
    eventos = []
    cliente = fed.SSEClient(
        *srv.server_address,
        "/peer/events",
        headers_fn=dict,
        on_event=eventos.append,
        backoff=lambda i: 0.0,
        connect_timeout=1.0,
        log=lambda m: None,
    )
    cliente.start()
    try:
        assert _esperar(lambda: len(eventos) >= 2, timeout=8)
    finally:
        srv.est["fin"].set()
        cliente.stop()
        cerrar()
    assert srv.est["conexiones"] == 1


def test_sse_que_conecto_y_se_corta_por_silencio_no_escala_el_backoff(monkeypatch):
    """Conecto y despues el peer quedo mudo mas que el timeout de lectura: cuenta como conectado
    (backoff 0), no como un fallo de conexion."""
    monkeypatch.setattr(fed, "SSE_READ_TIMEOUT_S", 0.3)
    srv, cerrar = _server(_HandlerPing)
    srv.est = {"lock": threading.Lock(), "conexiones": 0, "fin": threading.Event(), "cada_s": 60.0}
    intentos = []

    def backoff(i):
        intentos.append(i)
        return 0.0

    cliente = fed.SSEClient(
        *srv.server_address,
        "/peer/events",
        headers_fn=dict,
        on_event=lambda e: None,
        backoff=backoff,
        log=lambda m: None,
    )
    cliente.start()
    try:
        assert _esperar(lambda: len(intentos) >= 2)
    finally:
        srv.est["fin"].set()
        cliente.stop()
        cerrar()
    assert intentos[:2] == [0, 0]


# --- 0.8: un JSON corrupto borraba datos sin aviso (peers.json, peer.json) ---------------------


@pytest.fixture
def log_capturado(monkeypatch):
    import state

    log = []
    monkeypatch.setattr(state, "log", log.append)
    return log


def _corruptos(carpeta, nombre):
    return sorted(p for p in os.listdir(carpeta) if p.startswith(nombre + ".corrupto-"))


def test_peers_json_corrupto_se_aparta_con_aviso_y_no_se_pisa(tmp_path, log_capturado):
    path = str(tmp_path / "peers.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"p1": {"pc_id": "p1", "key": "ab"')  # cortado a mitad
    assert fed.list_peers(path) == []
    apartados = _corruptos(tmp_path, "peers.json")
    assert len(apartados) == 1
    with open(tmp_path / apartados[0], encoding="utf-8") as f:
        assert f.read().startswith('{"p1"')  # el original, intacto para recuperarlo a mano
    assert any("peers.json corrupto" in m for m in log_capturado)
    fed.add_peer(path, {"pc_id": "p2", "key": "cd"})  # se puede seguir: el archivo nuevo es otro
    assert [p["pc_id"] for p in fed.list_peers(path)] == ["p2"]


def test_peers_json_que_no_existe_es_vacio_sin_aviso(tmp_path, log_capturado):
    assert fed.list_peers(str(tmp_path / "peers.json")) == []
    assert log_capturado == []


def test_peers_json_que_no_se_puede_leer_no_se_pisa_al_escribir(tmp_path, log_capturado, monkeypatch):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, {"pc_id": "p1", "key": "ab"})
    fed._peers_cache.clear()
    real_open = open

    def open_bloqueado(p, *a, **kw):
        if str(p) == path and "w" not in (a[0] if a else kw.get("mode", "r")):
            raise PermissionError(13, "lo tiene el antivirus")
        return real_open(p, *a, **kw)

    monkeypatch.setattr("builtins.open", open_bloqueado)
    assert fed.list_peers(path) == []  # leer: se avisa y se sigue
    with pytest.raises(PermissionError):
        fed.add_peer(path, {"pc_id": "p2", "key": "cd"})  # escribir encima: NO
    monkeypatch.setattr("builtins.open", real_open)
    assert [p["pc_id"] for p in fed.list_peers(path)] == ["p1"]


@pytest.fixture
def lienzo_tmp(tmp_path, monkeypatch, log_capturado):
    import identity
    import state

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(identity, "_peer_cache", None)
    return tmp_path


def test_peer_json_corrupto_se_aparta_con_aviso(lienzo_tmp, log_capturado):
    import identity

    with open(lienzo_tmp / "peer.json", "w", encoding="utf-8") as f:
        f.write('{"pc_id": "0123456789ab", "name": ')
    nuevo = identity.pc_id()
    assert len(nuevo) == 12
    apartados = _corruptos(lienzo_tmp, "peer.json")
    assert len(apartados) == 1
    with open(lienzo_tmp / apartados[0], encoding="utf-8") as f:
        assert "0123456789ab" in f.read()  # la identidad vieja queda para recuperarla a mano
    assert any("peer.json corrupto" in m for m in log_capturado)


def test_peer_json_que_no_existe_se_crea_sin_aviso(lienzo_tmp, log_capturado):
    import identity

    assert len(identity.pc_id()) == 12
    assert _corruptos(lienzo_tmp, "peer.json") == []
    assert log_capturado == []


def test_peer_json_que_no_se_puede_leer_no_cambia_el_pc_id(lienzo_tmp, log_capturado, monkeypatch):
    """Antes un PermissionError pasajero (antivirus) devolvia None y se creaba un pc_id nuevo
    encima del bueno: la PC perdia todos sus emparejamientos."""
    import identity

    original = identity.pc_id()
    path = str(lienzo_tmp / "peer.json")
    os.utime(path, (time.time() + 5, time.time() + 5))  # invalida el cache: obliga a releer
    real_open = open

    def open_bloqueado(p, *a, **kw):
        if str(p) == path:
            raise PermissionError(13, "lo tiene el antivirus")
        return real_open(p, *a, **kw)

    monkeypatch.setattr("builtins.open", open_bloqueado)
    assert identity.pc_id() == original
    monkeypatch.setattr("builtins.open", real_open)
    with open(path, encoding="utf-8") as f:
        assert original in f.read()


# --- 1.8: 401 sin motivo ------------------------------------------------------------------------


def _firmado(key=b"k" * 32, ts=1_800_000_000.0, nonce="n1"):
    return key, "POST", "/peer/x", b"{}", ts, nonce, fed.sign(key, "POST", "/peer/x", b"{}", ts, nonce)


def test_verify_motivo_dice_por_que_rechaza():
    key, m, p, b, ts, nonce, sig = _firmado()
    cache = fed.NonceCache()
    assert fed.verify_motivo(key, m, p, b, ts, nonce, sig, cache, now=ts) == (True, "")
    ok, motivo = fed.verify_motivo(key, m, p, b, ts, nonce, sig, cache, now=ts)
    assert not ok and "nonce repetido" in motivo
    ok, motivo = fed.verify_motivo(key, m, p, b, ts, "n2", sig, cache, now=ts + 45)
    assert not ok and "ventana" in motivo and "+45" in motivo.replace(" ", "")
    ok, motivo = fed.verify_motivo(b"o" * 32, m, p, b, ts, "n3", sig, cache, now=ts)
    assert not ok and "firma" in motivo
    ok, motivo = fed.verify_motivo(key, m, p, b, ts, "n4", 123, cache, now=ts)
    assert not ok and "formato" in motivo


def test_verify_sigue_devolviendo_bool():
    key, m, p, b, ts, nonce, sig = _firmado()
    assert fed.verify(key, m, p, b, ts, nonce, sig, fed.NonceCache(), now=ts) is True
    assert fed.verify(key, m, p, b, ts, nonce, "x", fed.NonceCache(), now=ts) is False
