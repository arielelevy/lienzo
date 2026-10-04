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
    assert not ok and "ventana" in motivo and "-45 s" in motivo  # su reloj esta 45 s atras del mio
    ok, motivo = fed.verify_motivo(b"o" * 32, m, p, b, ts, "n3", sig, cache, now=ts)
    assert not ok and "firma" in motivo
    ok, motivo = fed.verify_motivo(key, m, p, b, ts, "n4", 123, cache, now=ts)
    assert not ok and "formato" in motivo


def test_verify_sigue_devolviendo_bool():
    key, m, p, b, ts, nonce, sig = _firmado()
    assert fed.verify(key, m, p, b, ts, nonce, sig, fed.NonceCache(), now=ts) is True
    assert fed.verify(key, m, p, b, ts, nonce, "x", fed.NonceCache(), now=ts) is False


# --- 1.12: peers.json leer-modificar-escribir sin lock; el beacon escribe aunque no cambie la IP ---


def test_altas_concurrentes_de_peers_no_se_pisan(tmp_path, monkeypatch):
    path = str(tmp_path / "peers.json")
    escribir = fed._atomic_write

    def escritura_lenta(p, obj):
        time.sleep(0.1)  # agranda la ventana entre leer y escribir, como un disco lento
        escribir(p, obj)

    monkeypatch.setattr(fed, "_atomic_write", escritura_lenta)
    hilos = [threading.Thread(target=fed.add_peer, args=(path, {"pc_id": f"p{i}", "key": "ab"})) for i in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(p["pc_id"] for p in fed.list_peers(path)) == ["p0", "p1", "p2", "p3"]


def test_update_peer_ip_no_escribe_si_la_ip_no_cambio(tmp_path, monkeypatch):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, {"pc_id": "p1", "key": "ab", "ip": "10.0.0.5"})
    escrituras = []
    escribir = fed._atomic_write
    monkeypatch.setattr(fed, "_atomic_write", lambda p, obj: (escrituras.append(obj), escribir(p, obj)))
    assert fed.update_peer_ip(path, "p1", "10.0.0.5") is True  # el beacon cada 10 s: nada que escribir
    assert escrituras == []
    assert fed.update_peer_ip(path, "p1", "10.0.0.9") is True
    assert len(escrituras) == 1
    assert fed.get_peer(path, "p1")["ip"] == "10.0.0.9"


# --- 1.13: una regla hacia otra PC se borraba sin log si el espejo estaba vacio -------------------

OTRA = "20000000-0000-4000-8000-000000000002"


class _Espejo:
    """Lo que rules necesita del espejo: owner_of/forward/sessions/rules, y peer_ids/all_synced."""

    def __init__(self, peers=("pc-b",), synced=False):
        self._peers, self._synced = list(peers), synced

    def owner_of(self, sid):
        return None

    def forward(self, *a, **kw):
        return 503, {"error": "no"}

    def sessions(self):
        return []

    def rules(self):
        return []

    def peer_ids(self):
        return list(self._peers)

    def all_synced(self):
        return bool(self._peers) and self._synced


@pytest.fixture
def reglas(tmp_path, monkeypatch, log_capturado):
    import types

    import rules as rl
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "LIENZO", str(tmp_path))
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st.rules, "path", str(tmp_path / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.links, "path", str(tmp_path / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    os.makedirs(st.SESSIONS, exist_ok=True)
    st.sessions.clear()

    def con_espejo(espejo):
        monkeypatch.setattr(ses, "mirror", types.SimpleNamespace(MIRROR=espejo))

    yield rl, st, con_espejo
    st.sessions.clear()


def _regla(xpc=False):
    r = {"id": "r1", "kind": "at", "from": None, "to": OTRA, "text": "x", "enabled": True, "fired": 0}
    return {**r, "xpc": True} if xpc else r


def test_fire_rule_no_borra_si_el_espejo_no_termino_de_sincronizar(reglas, log_capturado):
    rl, st, con_espejo = reglas
    con_espejo(_Espejo(synced=False))
    r = _regla()
    st.rules.items.append(r)
    rl.fire_rule(r)
    rl.fire_rule(r)  # la vuelta siguiente del bucle: sigue esperando, sin repetir el aviso
    assert r in st.rules.items and r["enabled"] is True and r["fired"] == 0
    assert len([m for m in log_capturado if "r1" in m and "espera" in m]) == 1


def test_fire_rule_hacia_otra_pc_no_se_borra_sin_peers_conectados(reglas, log_capturado):
    """El arranque: el espejo todavia vacio. La regla xpc espera; la purga (purge_stale_xpc) es la
    que decide, con los peers sincronizados."""
    rl, st, con_espejo = reglas
    con_espejo(_Espejo(peers=()))
    r = _regla(xpc=True)
    st.rules.items.append(r)
    rl.fire_rule(r)
    assert r in st.rules.items


def test_fire_rule_borra_con_log_si_el_destino_no_existe_y_todo_esta_sincronizado(reglas, log_capturado):
    rl, st, con_espejo = reglas
    con_espejo(_Espejo(synced=True))
    r = _regla()
    st.rules.items.append(r)
    rl.fire_rule(r)
    assert r not in st.rules.items
    assert any("r1" in m and "borrada" in m for m in log_capturado)


def test_fire_rule_sin_federacion_borra_con_log(reglas, log_capturado, monkeypatch):
    import sessions as ses

    rl, st, _ = reglas
    monkeypatch.setattr(ses, "mirror", None)
    r = _regla()
    st.rules.items.append(r)
    rl.fire_rule(r)
    assert r not in st.rules.items
    assert any("r1" in m and "borrada" in m for m in log_capturado)


# --- B11: dos Stop seguidos disparaban dos veces mientras el primer envio tardaba ----------------

ORIGEN = "10000000-0000-4000-8000-000000000001"


def test_on_stop_reserva_antes_de_enviar(reglas, monkeypatch):
    import sessions as ses

    rl, st, _ = reglas
    monkeypatch.setattr(ses, "mirror", None)
    st.sessions[ORIGEN] = ses.new_session(ORIGEN, "claude", "hook")
    r = {"id": "r1", "kind": "on_stop", "from": ORIGEN, "to": OTRA, "text": "x", "enabled": True, "repeat": True}
    st.rules.items.append(r)
    disparos = []

    def envio_lento(regla):
        disparos.append(regla["id"])
        time.sleep(0.3)  # send_to_session puede tardar hasta 60 s
        regla["last_fired"] = st.now()  # lo que hace fire_rule recien despues de enviar

    monkeypatch.setattr(rl, "fire_rule", envio_lento)
    hilos = [threading.Thread(target=rl.fire_on_stop, args=(ORIGEN,)) for _ in range(2)]
    for h in hilos:
        h.start()
        time.sleep(0.05)  # el segundo Stop llega con el primer envio en vuelo
    for h in hilos:
        h.join()
    assert disparos == ["r1"]


def test_on_stop_libera_la_reserva_si_el_envio_revienta(reglas, monkeypatch):
    import sessions as ses

    rl, st, _ = reglas
    monkeypatch.setattr(ses, "mirror", None)
    st.sessions[ORIGEN] = ses.new_session(ORIGEN, "claude", "hook")
    r = {"id": "r1", "kind": "on_stop", "from": ORIGEN, "to": OTRA, "text": "x", "enabled": True, "repeat": True}
    st.rules.items.append(r)
    disparos = []

    def envio_roto(regla):
        disparos.append(regla["id"])
        raise RuntimeError("se cayo")

    monkeypatch.setattr(rl, "fire_rule", envio_roto)
    for _ in range(2):
        rl.fire_on_stop(ORIGEN)  # la excepcion va al log (1.1), no corta nada
    assert disparos == ["r1", "r1"]  # sin last_fired no hay enfriamiento: la reserva no queda colgada


# --- 1.1 (parte rules): una regla que revienta no se lleva puestas a las demas ni queda muda -----


def _dos_reglas(st, kind="on_stop"):
    base = {"kind": kind, "from": ORIGEN, "text": "x", "enabled": True, "repeat": True}
    r1 = {**base, "id": "r1", "to": OTRA}
    r2 = {**base, "id": "r2", "to": "30000000-0000-4000-8000-000000000003"}
    st.rules.items.extend([r1, r2])
    return r1, r2


def test_on_stop_una_regla_que_revienta_no_corta_las_demas(reglas, monkeypatch, log_capturado):
    import sessions as ses

    rl, st, _ = reglas
    monkeypatch.setattr(ses, "mirror", None)
    st.sessions[ORIGEN] = ses.new_session(ORIGEN, "claude", "hook")
    _dos_reglas(st)
    disparos = []

    def fire(regla):
        disparos.append(regla["id"])
        if regla["id"] == "r1":
            raise RuntimeError("se cayo r1")

    monkeypatch.setattr(rl, "fire_rule", fire)
    rl.fire_on_stop(ORIGEN)
    assert disparos == ["r1", "r2"]
    assert any("Traceback" in m and "se cayo r1" in m for m in log_capturado)


def test_aviso_muerta_un_destino_que_revienta_no_corta_los_demas(reglas, monkeypatch, log_capturado):
    import sessions as ses

    rl, st, _ = reglas
    monkeypatch.setattr(ses, "mirror", None)
    st.sessions[ORIGEN] = ses.new_session(ORIGEN, "claude", "hook")
    r1, r2 = _dos_reglas(st)
    for r in (r1, r2):
        st.sessions[r["to"]] = ses.new_session(r["to"], "claude", "hook")
    enviados = []

    def send(dst, texto, adjuntos):
        enviados.append(dst["session_id"])
        if dst["session_id"] == OTRA:
            raise RuntimeError("consola rota")
        return 200, {}

    monkeypatch.setattr(rl, "send_to_session", send)
    rl.aviso_muerta(ORIGEN, "corriendo")
    assert sorted(enviados) == sorted([r1["to"], r2["to"]])
    assert any("Traceback" in m and "consola rota" in m for m in log_capturado)


def test_rules_loop_una_regla_que_revienta_no_corta_las_demas(reglas, monkeypatch, log_capturado):
    rl, st, _ = reglas
    r1, r2 = _dos_reglas(st, kind="at")
    for r in (r1, r2):
        r["at"] = st.now()
    disparos = []

    def fire(regla):
        disparos.append(regla["id"])
        if regla["id"] == "r1":
            raise RuntimeError("se cayo r1")

    class _Fin(BaseException):
        pass

    def dormir(s):
        raise _Fin

    monkeypatch.setattr(rl, "fire_rule", fire)
    import types

    monkeypatch.setattr(rl, "time", types.SimpleNamespace(sleep=dormir))  # no el time.sleep de todos
    with pytest.raises(_Fin):
        rl.rules_loop()
    assert disparos == ["r1", "r2"]
    assert any("se cayo r1" in m for m in log_capturado)


# --- 1.16: procinfo.py no importaba fuera de Windows -------------------------------------------


def test_procinfo_importa_y_responde_nada_fuera_de_windows(monkeypatch):
    """En Mac/Linux no hay ctypes.WinDLL: el modulo tiene que importar igual (lo usan hook, procs y
    backend) y las consultas Win32 devolver «nada»."""
    import ctypes
    import importlib.util
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    ruta = os.path.join(os.path.dirname(fed.__file__), "procinfo.py")
    spec = importlib.util.spec_from_file_location("procinfo_fuera_de_windows", ruta)
    pi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pi)
    assert pi.open_process(1234) is None
    assert pi.alive(1234) is False
    assert pi.proc_info(1234) == (None, None)
    assert pi.command_args('node "/opt/pi coding/cli.js" --mode rpc') == [
        "node",
        "/opt/pi coding/cli.js",
        "--mode",
        "rpc",
    ]
    assert pi.command_args("") == []
    assert pi.agent_of("/usr/bin/claude") is None  # sin .exe: no es un agente de Windows
