"""Tests de lienzo/pairing.py (plan-multi-pc-2026-09-26.md, ronda 2 encargo A): offer/accept del
lado que muestra la frase, con freno de intentos y tope de peers; y un punta a punta real de
join() contra un servidor HTTP minimo (que expone /peer/hello y /peer/pair llamando a accept(),
tal como lo va a enchufar server.py en esta ronda) corriendo por sockets de verdad. El lado que
pega la frase corre en un subproceso con su propio LIENZO_HOME, para no compartir el estado
global de este proceso (que se queda siendo la otra PC todo el tiempo)."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (test_identity.py)
from lienzo import server  # noqa: F401
import federation as fed
import identity as idn
import pairing
import state as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def hogar(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / "estado"))
    os.makedirs(st.LIENZO, exist_ok=True)  # add_peer no crea la carpeta: la crea identity al arrancar
    idn._repo_cache.clear()
    pairing._offer = None
    pairing._fails.clear()
    pairing._blocked_until = 0.0
    return tmp_path


def _req(pc_id, name="otra", color="#111111", port=7322, proof=""):
    return {"pc_id": pc_id, "name": name, "color": color, "port": port, "proof": proof}


# --- offer / accept: local, sin red -------------------------------------------------------------


def test_offer_da_una_palabra_y_vencimiento_futuro():
    oferta = pairing.offer()
    assert len(oferta["phrase"].split()) == pairing.PHRASE_WORDS == 1
    assert oferta["expires"] > time.time()


def test_accept_sin_oferta_pendiente_rechaza(hogar):
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req("otro-pc-id-1"))


def test_accept_con_proof_correcto_guarda_el_peer_y_devuelve_proof_de_vuelta(hogar):
    oferta = pairing.offer()
    su_pc_id = "abc123abc123"
    mi_pc_id = idn.pc_id()
    key = fed.derive_pair_key(oferta["phrase"], mi_pc_id, su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    resultado = pairing.accept(_req(su_pc_id, name="notebook", proof=proof))
    assert resultado["pc_id"] == mi_pc_id
    assert resultado["port"] == pairing.PEER_PORT
    assert resultado["proof"] == pairing._proof(key, mi_pc_id)
    peers = fed.list_peers(pairing._peers_path())
    assert len(peers) == 1
    assert peers[0]["pc_id"] == su_pc_id
    assert peers[0]["name"] == "notebook"
    assert peers[0]["key"] == key.hex()


def test_accept_consume_la_frase_un_segundo_intento_ya_no_sirve(hogar):
    oferta = pairing.offer()
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    pairing.accept(_req(su_pc_id, proof=proof))
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req(su_pc_id, proof=proof))


def test_accept_con_frase_vencida_rechaza(hogar):
    oferta = pairing.offer(ttl_s=-1)  # ya vencida
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req(su_pc_id, proof=proof))


def test_accept_con_proof_invalido_rechaza(hogar):
    pairing.offer()
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req("abc123abc123", proof="0" * 64))


def test_accept_con_proof_invalido_no_consume_la_frase(hogar):
    """Un intento fallido no gasta la frase: la PC que la muestra puede reintentar sin generar
    una frase nueva."""
    oferta = pairing.offer()
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req("abc123abc123", proof="0" * 64))
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    resultado = pairing.accept(_req(su_pc_id, proof=proof))
    assert resultado["pc_id"] == idn.pc_id()


def test_accept_respeta_el_tope_de_peers(hogar):
    for i in range(fed.MAX_PEERS):
        fed.add_peer(pairing._peers_path(), {"pc_id": f"peer{i:07d}", "name": "x", "key": "ab" * 32})
    oferta = pairing.offer()
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    with pytest.raises(pairing.PairingError):
        pairing.accept(_req(su_pc_id, proof=proof))


def test_cinco_intentos_fallidos_bloquean_accept_quince_minutos(hogar):
    for _ in range(pairing.MAX_FAILS):
        pairing.offer()
        with pytest.raises(pairing.PairingError):
            pairing.accept(_req("abc123abc123", proof="0" * 64))
    oferta = pairing.offer()
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    with pytest.raises(pairing.PairingError, match="bloqueado"):
        pairing.accept(_req(su_pc_id, proof=proof))  # el sexto, con proof correcto, cae igual


def test_bloqueo_se_libera_pasados_los_quince_minutos(hogar):
    for _ in range(pairing.MAX_FAILS):
        pairing.offer()
        with pytest.raises(pairing.PairingError):
            pairing.accept(_req("abc123abc123", proof="0" * 64))
    pairing._blocked_until = time.time() - 1  # simula que ya paso el bloqueo
    oferta = pairing.offer()
    su_pc_id = "abc123abc123"
    key = fed.derive_pair_key(oferta["phrase"], idn.pc_id(), su_pc_id)
    proof = pairing._proof(key, su_pc_id)
    resultado = pairing.accept(_req(su_pc_id, proof=proof))
    assert resultado["pc_id"] == idn.pc_id()


def test_mi_port_respeta_la_variable_de_entorno(hogar, monkeypatch):
    monkeypatch.setenv("LIENZO_PEER_PORT", "9999")
    assert pairing._my_port() == 9999
    monkeypatch.delenv("LIENZO_PEER_PORT")
    assert pairing._my_port() == pairing.PEER_PORT


# --- punta a punta real: join() contra un server HTTP minimo que envuelve accept() --------------


class _HandlerPeer(BaseHTTPRequestHandler):
    """Server de prueba minimo: expone /peer/hello y /peer/pair llamando a accept(), tal como C
    lo va a enchufar en server.py. /peer/hello no va firmado (todavia no hay clave compartida);
    /peer/pair valida por el proof del cuerpo, no por una firma HMAC de request."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _responder(self, status: int, cuerpo: dict):
        data = json.dumps(cuerpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/peer/hello":
            info = idn.pc_info()
            self._responder(200, {"pc_id": info["pc_id"], "name": info["name"]})
        else:
            self._responder(404, {"error": "no encontrado"})

    def do_POST(self):
        if self.path != "/peer/pair":
            self._responder(404, {"error": "no encontrado"})
            return
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo).decode("utf-8"))
        try:
            self._responder(200, pairing.accept(cuerpo))
        except pairing.PairingError as e:
            self._responder(409, {"error": str(e)})


def _correr_en_subproceso(home_b: str, codigo_join: str) -> subprocess.CompletedProcess:
    """`codigo_join` tiene que venir ya sin sangria comun (textwrap.dedent(...).strip() del lado
    de quien llama): armar el dedent aca, con el codigo_join ya interpolado adentro, no sirve
    porque una linea sin sangria en el medio (un f-string de una sola linea, por ejemplo) hace que
    dedent no le saque nada de indentacion al resto."""
    codigo = f"import sys\nsys.path.insert(0, {ROOT!r})\nfrom lienzo import server\nimport pairing\n{codigo_join}\n"
    env = dict(os.environ)
    env["LIENZO_HOME"] = home_b
    return subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL
    )


def test_join_punta_a_punta_contra_un_server_http_real(hogar, tmp_path):
    """PC A (este proceso) ofrece la frase y sirve /peer/hello + /peer/pair de verdad, por
    sockets reales; PC B (un subproceso, con su propio LIENZO_HOME) la pega con join(). Al
    terminar, las dos puntas tienen el peer de la otra en su peers.json, con la misma clave."""
    oferta = pairing.offer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _HandlerPeer)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    try:
        host, port = httpd.server_address
        home_b = str(tmp_path / "pc-b")
        t0 = time.perf_counter()
        r = _correr_en_subproceso(
            home_b,
            f"import json\nprint(json.dumps(pairing.join({oferta['phrase']!r}, {host!r}, {port})))",
        )
        duracion = time.perf_counter() - t0
    finally:
        httpd.shutdown()
        httpd.server_close()
        hilo.join(timeout=5)

    assert r.returncode == 0, r.stderr
    peer_de_a_visto_por_b = json.loads(r.stdout.strip().splitlines()[-1])

    mi_pc_id = idn.pc_id()
    assert peer_de_a_visto_por_b["pc_id"] == mi_pc_id
    assert peer_de_a_visto_por_b["port"] == pairing.PEER_PORT

    peers_de_a = fed.list_peers(pairing._peers_path())
    assert len(peers_de_a) == 1
    assert peers_de_a[0]["key"] == peer_de_a_visto_por_b["key"]

    with open(os.path.join(home_b, "peers.json"), encoding="utf-8") as f:
        peers_de_b = json.load(f)
    peer_b = next(iter(peers_de_b.values()))
    assert peer_b["pc_id"] == mi_pc_id
    assert peer_b["key"] == peers_de_a[0]["key"]

    print(f"emparejamiento de punta a punta: {duracion * 1000:.0f} ms (incluye dos scrypt)")


def test_join_con_frase_equivocada_no_guarda_nada_de_ningun_lado(hogar, tmp_path):
    pairing.offer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _HandlerPeer)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    try:
        host, port = httpd.server_address
        home_b = str(tmp_path / "pc-b")
        r = _correr_en_subproceso(
            home_b,
            textwrap.dedent(f"""\
                try:
                    pairing.join("frase completamente distinta a la ofrecida aca", {host!r}, {port})
                    print("SIN-ERROR")
                except pairing.PairingError as e:
                    print("ERROR:" + str(e))
                """),
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        hilo.join(timeout=5)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith("ERROR:")
    assert fed.list_peers(pairing._peers_path()) == []
    assert not os.path.exists(os.path.join(home_b, "peers.json"))


def test_join_sin_server_del_otro_lado_da_un_error_claro(hogar, tmp_path):
    home_b = str(tmp_path / "pc-b")
    puerto_muerto = 1  # nada escucha ahi
    r = _correr_en_subproceso(
        home_b,
        textwrap.dedent(f"""\
            try:
                pairing.join("frase que da igual, no hay nadie del otro lado", "127.0.0.1", {puerto_muerto})
                print("SIN-ERROR")
            except Exception as e:
                print(type(e).__name__ + ":" + str(e))
            """),
    )
    assert r.returncode == 0, r.stderr
    assert not r.stdout.strip().startswith("SIN-ERROR")
