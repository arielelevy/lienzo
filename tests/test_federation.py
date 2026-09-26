"""Tests de lienzo/federation.py (plan-multi-pc-2026-09-26.md, F0/F1, criterio de seguridad del
plan p4): firma HMAC y replay, KDF del emparejamiento, peers.json con tope de 4, beacon UDP
(anonimo y firmado) con sockets reales en 127.0.0.1, cliente SSE con reconexion y backoff
inyectable contra un ThreadingHTTPServer de prueba, y el transporte HTTP. Nada de sleeps largos:
el backoff de los tests es instantaneo.
"""

import http.server
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lienzo import federation as fed

# --- firma -------------------------------------------------------------------------------


def test_firma_buena_pasa():
    key = b"clave-de-prueba-0123456789abcdef"
    ts = 1_800_000_000.0
    nonce = "n1"
    sig = fed.sign(key, "POST", "/peer/sessions", b'{"a":1}', ts, nonce)
    cache = fed.NonceCache()
    assert fed.verify(key, "POST", "/peer/sessions", b'{"a":1}', ts, nonce, sig, cache, now=ts)


def _firma_rota(**kw):
    key = b"clave-de-prueba-0123456789abcdef"
    base = {
        "key": key,
        "method": "POST",
        "path": "/peer/sessions",
        "body": b'{"a":1}',
        "ts": 1_800_000_000.0,
        "nonce": "n1",
    }
    sig = fed.sign(**{k: v for k, v in base.items()})
    base.update(kw)
    cache = fed.NonceCache()
    return fed.verify(
        base["key"], base["method"], base["path"], base["body"], base["ts"], base["nonce"], sig, cache, now=base["ts"]
    )


def test_cambiar_un_byte_del_cuerpo_rompe_la_firma():
    assert _firma_rota(body=b'{"a":2}') is False


def test_cambiar_la_ruta_rompe_la_firma():
    assert _firma_rota(path="/peer/otra") is False


def test_cambiar_el_metodo_rompe_la_firma():
    assert _firma_rota(method="GET") is False


def test_cambiar_el_ts_rompe_la_firma():
    assert _firma_rota(ts=1_800_000_001.0) is False


def test_cambiar_el_nonce_rompe_la_firma():
    assert _firma_rota(nonce="n2") is False


def test_ts_fuera_de_ventana_se_rechaza():
    key = b"k" * 32
    ts = 1_800_000_000.0
    sig = fed.sign(key, "GET", "/peer/health", b"", ts, "n1")
    cache = fed.NonceCache()
    # 31 s de diferencia: fuera de la ventana de +-30 s
    assert fed.verify(key, "GET", "/peer/health", b"", ts, "n1", sig, cache, now=ts + 31) is False


def test_ts_dentro_de_ventana_pasa():
    key = b"k" * 32
    ts = 1_800_000_000.0
    sig = fed.sign(key, "GET", "/peer/health", b"", ts, "n1")
    cache = fed.NonceCache()
    assert fed.verify(key, "GET", "/peer/health", b"", ts, "n1", sig, cache, now=ts + 29) is True


def test_mismo_nonce_dos_veces_se_rechaza():
    key = b"k" * 32
    ts = 1_800_000_000.0
    sig = fed.sign(key, "GET", "/peer/health", b"", ts, "rep")
    cache = fed.NonceCache()
    assert fed.verify(key, "GET", "/peer/health", b"", ts, "rep", sig, cache, now=ts) is True
    assert fed.verify(key, "GET", "/peer/health", b"", ts, "rep", sig, cache, now=ts) is False


def test_verify_con_firma_que_no_es_str_no_revienta():
    """hmac.compare_digest exige str o bytes-like de los dos lados; una firma que llega None,
    bytes o un numero (un peer que manda cualquier cosa en el header) tiene que dar False, no
    TypeError."""
    key = b"k" * 32
    ts = 1_800_000_000.0
    cache = fed.NonceCache()
    for sig_mala in (None, b"01ab", 12345, 3.14, ["01ab"]):
        assert fed.verify(key, "GET", "/peer/health", b"", ts, "n1", sig_mala, cache, now=ts) is False


def test_nonce_cache_purga_los_vencidos_y_queda_acotado():
    cache = fed.NonceCache(ttl_s=10)
    assert cache.add("a", now=1000.0) is True
    assert cache.add("b", now=1005.0) is True
    # a las t=1015 ya vencio "a" (paso mas de 10s); se purga solo y el cache no crece sin limite
    assert cache.add("c", now=1015.0) is True
    assert "a" not in cache._vistos
    assert len(cache._vistos) <= 2


def test_verify_es_rapido():
    """Cuanto cuesta verify por request: sirve para no meter algo caro en el camino caliente."""
    key = b"k" * 32
    cache = fed.NonceCache()
    n = 500
    t0 = time.perf_counter()
    for i in range(n):
        ts = 1_800_000_000.0
        nonce = f"n{i}"
        sig = fed.sign(key, "GET", "/peer/health", b"", ts, nonce)
        assert fed.verify(key, "GET", "/peer/health", b"", ts, nonce, sig, cache, now=ts)
    dt = time.perf_counter() - t0
    por_request_ms = (dt / n) * 1000
    assert por_request_ms < 5.0  # HMAC-SHA256 sobre stdlib: deberia andar en microsegundos


# --- emparejamiento (KDF) -----------------------------------------------------------------


def test_misma_frase_y_mismo_par_dan_la_misma_clave_en_las_dos_puntas():
    k_a = fed.derive_pair_key("correcto caballo bateria grapa uno dos", "aaa111", "bbb222")
    k_b = fed.derive_pair_key("correcto caballo bateria grapa uno dos", "bbb222", "aaa111")
    assert k_a == k_b  # el orden de los pc_id no importa: la sal se ordena


def test_frase_equivocada_da_clave_distinta():
    k1 = fed.derive_pair_key("correcto caballo bateria grapa uno dos", "aaa111", "bbb222")
    k2 = fed.derive_pair_key("otra frase completamente distinta aca", "aaa111", "bbb222")
    assert k1 != k2


def test_distinto_par_da_clave_distinta():
    k1 = fed.derive_pair_key("misma frase para los dos casos aca", "aaa111", "bbb222")
    k2 = fed.derive_pair_key("misma frase para los dos casos aca", "aaa111", "ccc333")
    assert k1 != k2


# --- peers.json --------------------------------------------------------------------------


def _peer(pc_id, name="pc", ip="127.0.0.1", port=7322):
    return {"pc_id": pc_id, "name": name, "ip": ip, "port": port, "key": "ab" * 32}


def test_alta_baja_y_lista_de_peers(tmp_path):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, _peer("p1"))
    fed.add_peer(path, _peer("p2"))
    assert {p["pc_id"] for p in fed.list_peers(path)} == {"p1", "p2"}
    assert fed.remove_peer(path, "p1") is True
    assert {p["pc_id"] for p in fed.list_peers(path)} == {"p2"}
    assert fed.remove_peer(path, "no-existe") is False


def test_actualizacion_de_ip_por_pc_id(tmp_path):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, _peer("p1", ip="10.0.0.5"))
    assert fed.update_peer_ip(path, "p1", "10.0.0.9") is True
    peer = next(p for p in fed.list_peers(path) if p["pc_id"] == "p1")
    assert peer["ip"] == "10.0.0.9"
    assert fed.update_peer_ip(path, "no-existe", "10.0.0.1") is False


def test_tope_de_cuatro_peers(tmp_path):
    path = str(tmp_path / "peers.json")
    for i in range(fed.MAX_PEERS):
        fed.add_peer(path, _peer(f"p{i}"))
    try:
        fed.add_peer(path, _peer("p-quinto"))
        assert False, "tendria que haber rechazado el quinto peer"
    except fed.PeerLimitError:
        pass
    assert len(fed.list_peers(path)) == fed.MAX_PEERS
    # actualizar uno que ya esta no cuenta como alta nueva: no choca con el tope
    fed.add_peer(path, _peer("p0", name="renombrado"))
    assert len(fed.list_peers(path)) == fed.MAX_PEERS


def test_escritura_atomica_no_deja_tmp(tmp_path):
    path = str(tmp_path / "peers.json")
    fed.add_peer(path, _peer("p1"))
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_archivo_corrupto_no_rompe(tmp_path):
    path = str(tmp_path / "peers.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{esto no es json valido")
    assert fed.list_peers(path) == []
    # y se puede seguir escribiendo: no queda trabado por el archivo roto
    fed.add_peer(path, _peer("p1"))
    assert len(fed.list_peers(path)) == 1


# --- beacon UDP --------------------------------------------------------------------------


def test_codificar_y_decodificar_el_anuncio():
    data = fed.encode_beacon("pc123", "oficina", 7322, version=1)
    out = fed.decode_beacon(data)
    assert out == {"pc_id": "pc123", "name": "oficina", "port": 7322, "version": 1}


def test_decodificar_basura_no_rompe():
    assert fed.decode_beacon(b"\xff\xfe no es json") is None
    assert fed.decode_beacon(b"[1,2,3]") is None
    assert fed.decode_beacon(b"{}") is None


def test_anuncio_firmado_solo_lo_acepta_quien_tiene_la_clave_del_par():
    key = b"k" * 32
    data = fed.encode_signed_beacon(key, "pc123", "oficina", 7322)
    assert fed.decode_signed_beacon(key, data) == {
        "pc_id": "pc123",
        "name": "oficina",
        "port": 7322,
        "version": fed.BEACON_VERSION,
    }
    assert fed.decode_signed_beacon(b"o" * 32, data) is None  # otra clave: no es del par


def test_anuncio_firmado_viejo_se_rechaza():
    """Sin ts en el payload firmado, un beacon capturado se podia reenviar mas tarde (desde otra
    IP) y forzar un update_peer_ip a destiempo. Con ts, cae fuera de la ventana de +-30 s."""
    key = b"k" * 32
    data = fed.encode_signed_beacon(key, "pc123", "oficina", 7322, ts=1_800_000_000.0)
    assert fed.decode_signed_beacon(key, data, now=1_800_000_029.0) is not None  # dentro de la ventana
    assert fed.decode_signed_beacon(key, data, now=1_800_000_031.0) is None  # reenviado 31s despues


def test_anuncio_firmado_con_ts_alterado_sin_recalcular_la_firma_se_rechaza():
    key = b"k" * 32
    data = fed.encode_signed_beacon(key, "pc123", "oficina", 7322, ts=1_800_000_000.0)
    externo = json.loads(data.decode("utf-8"))
    externo["ts"] = time.time()  # intenta "refrescar" un beacon viejo sin la clave del par
    manipulado = json.dumps(externo).encode("utf-8")
    assert fed.decode_signed_beacon(key, manipulado) is None


def test_beacon_real_con_dos_sockets_udp_en_loopback():
    key = b"k" * 32
    receptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receptor.bind(("127.0.0.1", 0))
    receptor.settimeout(2.0)
    puerto_receptor = receptor.getsockname()[1]
    try:
        emisor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            paquete = fed.encode_signed_beacon(key, "pc-emisor", "notebook", 7322)
            emisor.sendto(paquete, ("127.0.0.1", puerto_receptor))
            data, _addr = receptor.recvfrom(4096)
        finally:
            emisor.close()
        anuncio = fed.decode_signed_beacon(key, data)
        assert anuncio is not None
        assert anuncio["pc_id"] == "pc-emisor"
        assert anuncio["port"] == 7322
    finally:
        receptor.close()


# --- cliente SSE con reconexion ------------------------------------------------------------


class _HandlerSSE(http.server.BaseHTTPRequestHandler):
    """Server de prueba: la primera conexion manda dos eventos y corta; la segunda (la
    reconexion) manda un evento mas y se queda esperando hasta que el test la cierre."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        estado = self.server.estado_test
        with estado["lock"]:
            intento = estado["intentos"]
            estado["intentos"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.close_connection = True  # cada conexion de esta prueba se cierra a proposito
        self.end_headers()
        if intento == 0:
            self.wfile.write(b'data: {"n": 1}\n\n')
            self.wfile.write(b'data: {"n": 2}\n\n')
            self.wfile.flush()
            return  # corta la conexion (Connection: close): dispara la reconexion
        self.wfile.write(b'data: {"n": 3}\n\n')
        self.wfile.flush()
        estado["segunda_conexion_lista"].set()
        estado["cerrar"].wait(timeout=5)


def test_cliente_sse_reconecta_con_backoff_y_avisa_para_pedir_snapshot():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HandlerSSE)
    server.estado_test = {
        "lock": threading.Lock(),
        "intentos": 0,
        "segunda_conexion_lista": threading.Event(),
        "cerrar": threading.Event(),
    }
    hilo_server = threading.Thread(target=server.serve_forever, daemon=True)
    hilo_server.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        eventos = []
        reconexiones = []
        backoffs_pedidos = []

        def backoff_instantaneo(intento):
            backoffs_pedidos.append(intento)
            return 0.0

        cliente = fed.SSEClient(
            host,
            port,
            "/peer/events",
            headers_fn=dict,
            on_event=lambda ev: eventos.append(ev),
            on_reconnect=lambda: reconexiones.append(True),
            backoff=backoff_instantaneo,
        )
        cliente.start()
        try:
            assert server.estado_test["segunda_conexion_lista"].wait(timeout=5)
            # dio tiempo a que el ultimo evento de la segunda conexion se entregue
            deadline = time.time() + 2
            while len(eventos) < 3 and time.time() < deadline:
                time.sleep(0.02)
        finally:
            server.estado_test["cerrar"].set()
            cliente.stop()
        assert [e["n"] for e in eventos] == [1, 2, 3]
        assert len(reconexiones) >= 2  # conexion inicial + la reconexion
        assert len(backoffs_pedidos) >= 1
    finally:
        server.shutdown()
        server.server_close()
        hilo_server.join(timeout=5)


# --- transporte -----------------------------------------------------------------------------


class _HandlerHTTP(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _responder(self, cuerpo: dict):
        data = json.dumps(cuerpo).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.pedidos.append(("GET", self.path, b"", dict(self.headers)))
        self._responder({"ok": True, "path": self.path})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo)
        self.server.pedidos.append(("POST", self.path, cuerpo, dict(self.headers)))
        self._responder({"ok": True, "recibido": json.loads(cuerpo)})


def test_transporte_http_get_y_post_firmados():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HandlerHTTP)
    server.pedidos = []
    hilo_server = threading.Thread(target=server.serve_forever, daemon=True)
    hilo_server.start()
    try:
        host, port = server.server_address
        key = b"k" * 32
        peer = fed.PeerConn(host=host, port=port, key=key)
        transporte = fed.HTTPTransport()

        resp = transporte.get(peer, "/peer/sessions")
        assert resp == {"ok": True, "path": "/peer/sessions"}

        resp = transporte.post(peer, "/peer/sessions/x/send", {"text": "hola"})
        assert resp == {"ok": True, "recibido": {"text": "hola"}}

        # las dos requests llegaron firmadas y verifican contra la misma clave
        cache = fed.NonceCache()
        for metodo, path, cuerpo, headers in server.pedidos:
            ts = float(headers["X-Lienzo-Ts"])
            nonce = headers["X-Lienzo-Nonce"]
            sig = headers["X-Lienzo-Sig"]
            assert fed.verify(key, metodo, path, cuerpo, ts, nonce, sig, cache, now=ts)
    finally:
        server.shutdown()
        server.server_close()
        hilo_server.join(timeout=5)
