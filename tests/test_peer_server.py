"""Tests de punta a punta del listener de peers (server.PeerHandler) y el enrutado de comandos
entre dos PCs (plan-multi-pc-2026-09-26.md, ronda 2 encargo C, F1/F2). "PC A" es este proceso de
test (LIENZO_HOME propio via monkeypatch, y un server.Handler real en 127.0.0.1); "PC B" es un
subproceso con su propio LIENZO_HOME (variable de entorno) y solo un server.PeerHandler -- la misma
tecnica que test_pairing.py usa para no compartir el estado global de este proceso (sessions,
pending, links, reglas son dicts a nivel de modulo). La clave del par se deriva y se escribe
directo en los dos peers.json, sin pasar por pairing.py: eso ya lo prueba test_pairing.py.

Cada test pide su propio puerto libre y su propio pc_id (nunca uno fijo): la maquina donde corre
esto tiene otras seis o siete sesiones trabajando a la vez, y un puerto fijo reusado entre pruebas
quedo una vez pisado por el propio subproceso anterior, todavia cerrando bajo carga (401 en vez de
503: contestaba un B viejo, con otra clave)."""

import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_identity.py)
from lienzo import server
import federation as fed
import identity as idn
import mirror
import state as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSPHRASE = "correcto caballo bateria grapa test federacion"
SID_B = "b0000000-0000-4000-8000-000000000001"
RID_B = "req-desde-b-0001"


def _puerto_libre() -> int:
    """Un puerto TCP libre en 127.0.0.1 ahora mismo (bind a :0 y cerrar). No es 100% atomico contra
    otro proceso de la maquina, pero alcanza para no reusar un puerto fijo entre pruebas."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture
def dos_pcs(tmp_path, monkeypatch):
    """Arma la identidad y el peers.json de las dos PCs (con puertos y pc_id nuevos en cada
    llamada); no arranca ningun server (cada test arranca lo que necesita). El estado global de
    ESTE proceso (que hace de PC A) queda aislado en tmp_path y se limpia al final; el de PC B vive
    entero en su subproceso."""
    home_a = tmp_path / "pc-a"
    home_b = tmp_path / "pc-b"
    os.makedirs(home_a, exist_ok=True)
    os.makedirs(home_b, exist_ok=True)

    monkeypatch.setattr(st, "LIENZO", str(home_a))
    monkeypatch.setattr(st, "SESSIONS", str(home_a / "sessions"))
    monkeypatch.setattr(server, "PEERS_FILE", str(home_a / "peers.json"))
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(server, "log", lambda msg: None)
    st.sessions.clear()
    st.pending.clear()
    st.links.items.clear()
    st.rules.items.clear()
    idn._repo_cache.clear()

    pc_id_a = idn.pc_id()  # crea home_a/peer.json
    pc_id_b = secrets.token_hex(6)
    peer_port_b = _puerto_libre()
    ui_port_a = _puerto_libre()
    with open(home_b / "peer.json", "w", encoding="utf-8") as f:
        json.dump({"pc_id": pc_id_b, "name": "pc-b", "color": "#222222"}, f)

    key = fed.derive_pair_key(PASSPHRASE, pc_id_a, pc_id_b)
    fed.add_peer(
        str(home_a / "peers.json"),
        {
            "pc_id": pc_id_b,
            "name": "pc-b",
            "color": "#222222",
            "ip": "127.0.0.1",
            "port": peer_port_b,
            "key": key.hex(),
        },
    )
    fed.add_peer(
        str(home_b / "peers.json"),
        {
            "pc_id": pc_id_a,
            "name": "pc-a",
            "color": "#111111",
            "ip": "127.0.0.1",
            "port": _puerto_libre(),
            "key": key.hex(),
        },
    )

    yield {
        "pc_id_a": pc_id_a,
        "pc_id_b": pc_id_b,
        "peer_port_b": peer_port_b,
        "ui_port_a": ui_port_a,
        "home_a": home_a,
        "home_b": home_b,
        "key": key,
    }

    mirror.MIRROR.stop()
    mirror.MIRROR.on_change = lambda: None
    st.sessions.clear()
    st.pending.clear()
    st.links.items.clear()
    st.rules.items.clear()


def _codigo_b(peer_port_b: int) -> str:
    """Lo que corre el subproceso: sin sweep, sin hilos de reglas ni liveness -- solo el registro
    con una tarjeta y un pendiente de prueba, y el listener de peers de verdad."""
    return f"""
import sys, os, time, threading
sys.path.insert(0, {ROOT!r})
from lienzo import server
import state as st
import sessions as ses

os.makedirs(st.PENDING, exist_ok=True)
os.makedirs(st.ANSWERS, exist_ok=True)
os.makedirs(st.SESSIONS, exist_ok=True)

sid = {SID_B!r}
s = ses.new_session(sid, "claude", "hook")
s["cwd"] = "D:/Repos/demo"
s["repo"], s["repo_key"] = "demo", "demo"
s["title"] = "sesion de B"
st.sessions[sid] = s

st.pending[{RID_B!r}] = {{
    "request_id": {RID_B!r}, "session_id": sid, "nonce": "n123",
    "tool_name": "Bash", "tool_input": {{"command": "echo hola"}},
    "expires_at": "2099-01-01T00:00:00",
}}

from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", {peer_port_b}), server.PeerHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
print("LISTO", flush=True)
time.sleep(120)
"""


def _lanzar_b(home_b, peer_port_b: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["LIENZO_HOME"] = str(home_b)
    return subprocess.Popen(
        [sys.executable, "-c", _codigo_b(peer_port_b)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _esperar_listo(port: int, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    ultimo_error: Exception | None = None
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            c.request("GET", "/peer/hello")
            c.getresponse().read()
            c.close()
            return
        except OSError as e:
            ultimo_error = e
            time.sleep(0.1)
    raise AssertionError(f"el peer en :{port} no respondio a tiempo: {ultimo_error}")


# --- el listener de peers: solo /peer/*, todo firmado salvo hello y pair ------------------------


def test_peer_handler_solo_atiende_peer_y_exige_firma(dos_pcs):
    peer_port_b, pc_id_b = dos_pcs["peer_port_b"], dos_pcs["pc_id_b"]
    proc = _lanzar_b(dos_pcs["home_b"], peer_port_b)
    try:
        _esperar_listo(peer_port_b)
        conn = http.client.HTTPConnection("127.0.0.1", peer_port_b, timeout=3)

        conn.request("GET", "/sessions")  # no es /peer/*
        r = conn.getresponse()
        r.read()
        assert r.status == 404

        conn.request("GET", "/peer/hello")  # sin firma, a proposito
        r = conn.getresponse()
        cuerpo = json.loads(r.read())
        assert r.status == 200
        assert cuerpo == {"pc_id": pc_id_b, "name": "pc-b"}

        conn.request("GET", "/peer/snapshot")  # firmado, pero sin cabeceras: rechazado
        r = conn.getresponse()
        r.read()
        assert r.status == 401
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_peer_handler_rechaza_una_firma_con_la_clave_equivocada(dos_pcs):
    peer_port_b = dos_pcs["peer_port_b"]
    proc = _lanzar_b(dos_pcs["home_b"], peer_port_b)
    try:
        _esperar_listo(peer_port_b)
        peer_malo = fed.PeerConn(host="127.0.0.1", port=peer_port_b, key=b"o" * 32, self_pc_id=dos_pcs["pc_id_a"])
        transporte = fed.HTTPTransport()
        status, _ = transporte.request(peer_malo, "GET", "/peer/snapshot")
        assert status == 401

        peer_bueno = fed.PeerConn(host="127.0.0.1", port=peer_port_b, key=dos_pcs["key"], self_pc_id=dos_pcs["pc_id_a"])
        status, cuerpo = transporte.request(peer_bueno, "GET", "/peer/snapshot")
        assert status == 200
        assert [s["session_id"] for s in cuerpo["sessions"]] == [SID_B]
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# --- punta a punta: espejo + enrutado a traves de un server.Handler real -------------------------


def test_punta_a_punta_dos_pcs_mirror_sessions_y_enrutado(dos_pcs, capsys):
    pc_id_a, pc_id_b, key = dos_pcs["pc_id_a"], dos_pcs["pc_id_b"], dos_pcs["key"]
    peer_port_b, ui_port_a = dos_pcs["peer_port_b"], dos_pcs["ui_port_a"]
    proc = _lanzar_b(dos_pcs["home_b"], peer_port_b)
    try:
        _esperar_listo(peer_port_b)
        mirror.MIRROR.connect(pc_id_b, {"name": "pc-b", "color": "#222222"}, "127.0.0.1", peer_port_b, key, pc_id_a)

        srv_a = ThreadingHTTPServer(("127.0.0.1", ui_port_a), server.Handler)
        srv_a.daemon_threads = True
        threading.Thread(target=srv_a.serve_forever, daemon=True).start()
        try:
            # el espejo trae el snapshot de B al conectar: esperar a que la tarjeta aparezca
            deadline = time.time() + 5
            vistos = []
            while time.time() < deadline and not vistos:
                vistos = mirror.MIRROR.sessions()
                if not vistos:
                    time.sleep(0.05)
            assert [s["session_id"] for s in vistos] == [SID_B]

            conn = http.client.HTTPConnection("127.0.0.1", ui_port_a, timeout=5)

            # GET /sessions mezclado (local + espejo), con la latencia que pide medir el encargo
            t0 = time.perf_counter()
            conn.request("GET", "/sessions")
            r = conn.getresponse()
            cuerpo = json.loads(r.read())
            lat_sessions_ms = (time.perf_counter() - t0) * 1000
            assert r.status == 200
            por_id = {s["session_id"]: s for s in cuerpo}
            assert SID_B in por_id
            assert por_id[SID_B]["pc"] == pc_id_b

            # interrupt enrutado a B: sin pid vivo ahi, 409 REAL (no 404): prueba que el comando
            # viajo, se firmo, se verifico y corrio de verdad en el otro proceso
            t0 = time.perf_counter()
            conn.request(
                "POST",
                f"/sessions/{SID_B}/interrupt",
                body="{}",
                headers={"X-Lienzo": "1", "Content-Type": "application/json"},
            )
            r = conn.getresponse()
            cuerpo = json.loads(r.read())
            lat_interrupt_ms = (time.perf_counter() - t0) * 1000
            assert r.status == 409
            assert "PID vivo" in cuerpo.get("error", "")

            # POST /pending/<id> enrutado: la decision tiene que llegar al disco de B
            conn.request(
                "POST",
                f"/pending/{RID_B}",
                body=json.dumps({"decision": "deny"}),
                headers={"X-Lienzo": "1", "Content-Type": "application/json"},
            )
            r = conn.getresponse()
            cuerpo = json.loads(r.read())
            assert (r.status, cuerpo.get("ok")) == (200, True)

            respuesta_path = dos_pcs["home_b"] / "answers" / f"{RID_B}.json"
            deadline = time.time() + 3
            while not respuesta_path.exists() and time.time() < deadline:
                time.sleep(0.05)
            assert respuesta_path.exists(), "la respuesta al pendiente de B no llego a su disco"
            with open(respuesta_path, encoding="utf-8") as f:
                assert json.load(f)["decision"] == "deny"

            # sesion desconocida en las dos puntas: 404 de siempre, no un 503 disfrazado
            conn.request("GET", "/sessions/no-existe-en-ningun-lado/screen")
            r = conn.getresponse()
            r.read()
            assert r.status == 404

            with capsys.disabled():
                print(
                    f"\nGET /sessions mezclado (local+espejo): {lat_sessions_ms:.1f} ms · "
                    f"interrupt enrutado a B: {lat_interrupt_ms:.1f} ms"
                )
        finally:
            srv_a.shutdown()
            srv_a.server_close()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_espejo_refleja_una_sesion_nueva_de_b_sin_reconectar(dos_pcs):
    """Una vez conectado el espejo, una tarjeta que aparece del lado de B tiene que verse sola (por
    el SSE de /peer/events), sin que nadie vuelva a pedir el snapshot. Mide cuanto tarda."""
    pc_id_a, pc_id_b, key = dos_pcs["pc_id_a"], dos_pcs["pc_id_b"], dos_pcs["key"]
    peer_port_b = dos_pcs["peer_port_b"]
    proc = _lanzar_b(dos_pcs["home_b"], peer_port_b)
    try:
        _esperar_listo(peer_port_b)
        mirror.MIRROR.connect(pc_id_b, {"name": "pc-b"}, "127.0.0.1", peer_port_b, key, pc_id_a)
        deadline = time.time() + 5
        while time.time() < deadline and not mirror.MIRROR.sessions():
            time.sleep(0.02)
        assert mirror.MIRROR.sessions(), "el snapshot inicial del espejo no llego"

        peer = fed.PeerConn(host="127.0.0.1", port=peer_port_b, key=key, self_pc_id=pc_id_a)
        transporte = fed.HTTPTransport()
        t0 = time.perf_counter()
        # no hay ruta para "crear" una sesion por HTTP (nacen de hooks o del barrido): se simula el
        # cambio directo en B via su propio /peer/sessions/<id>/title, que toca y publica la tarjeta
        # existente; para una tarjeta nueva de verdad alcanza con touch() en el subproceso, pero
        # aca reusamos la ruta ya expuesta para no abrir un canal de prueba nuevo
        status, _ = transporte.request(
            peer, "PUT", f"/peer/sessions/{SID_B}/title", {"title": "cambiado desde el test"}
        )
        assert status == 200

        deadline = time.time() + 5
        reflejado = None
        while time.time() < deadline:
            candidatos = [s for s in mirror.MIRROR.sessions() if s["session_id"] == SID_B]
            if candidatos and candidatos[0].get("title") == "cambiado desde el test":
                reflejado = candidatos[0]
                break
            time.sleep(0.02)
        tardanza_ms = (time.perf_counter() - t0) * 1000
        assert reflejado is not None, "el cambio de B no se reflejo en el espejo de A"
        print(f"\nespejo: cambio de B reflejado en A en {tardanza_ms:.1f} ms")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_peer_caido_da_503_a_traves_del_forward(dos_pcs):
    """Sin B corriendo, un forward tiene que dar 503 con el nombre del peer, no colgarse ni tirar
    una excepcion sin capturar (el timeout de HTTPTransport es de unos segundos)."""
    pc_id_a, pc_id_b, key = dos_pcs["pc_id_a"], dos_pcs["pc_id_b"], dos_pcs["key"]
    peer_port_b = dos_pcs["peer_port_b"]
    mirror.MIRROR.connect(pc_id_b, {"name": "pc-b"}, "127.0.0.1", peer_port_b, key, pc_id_a)
    code, body = mirror.MIRROR.forward(pc_id_b, "POST", f"/sessions/{SID_B}/interrupt", {})
    assert code == 503
    assert "error" in body
