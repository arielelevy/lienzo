"""El HTTP local (127.0.0.1:7321) no puede quedar sin respuesta por nada de afuera: ni una consola
que no acepta mas texto, ni una PC par que no contesta, ni una interfaz de red que desaparece
(incidente del 2026-10-05, `docs/informe-red-2026-10-05.md` en el historial de git).

Lo que paso ese dia, en orden: a las 14:50 la consola del server dejo de aceptar texto (en una
ventana de conhost alcanza con hacer click adentro: la seleccion de QuickEdit frena toda escritura
hasta un Esc). `state.log` escribia el archivo y despues hacia `print` en el mismo hilo, asi que el
primer hilo que logueo quedo trabado en el print. A las 14:57 un hook (consume_events) logueo con
`lock` tomado y ya no lo solto: desde ahi GET /sessions, la liveness, la salud de los pares y el
espejo esperaban ese lock para siempre."""

import http.client
import json
import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import federation as fed
import mirror
import sessions as ses
import state as st

SID = "7e57c0de-0000-4000-8000-000000000001"


class ConsolaTrabada:
    """Un stdout cuyo write no vuelve hasta que se suelta: lo que hace una consola de Windows con
    una seleccion de QuickEdit abierta, o un pipe que nadie lee."""

    def __init__(self):
        self.suelta = threading.Event()
        self.trabados = 0

    def write(self, texto):
        self.trabados += 1
        self.suelta.wait()
        return len(texto)

    def flush(self):
        self.suelta.wait()

    def isatty(self):
        return False


@pytest.fixture
def server_local(tmp_path, monkeypatch):
    """Un Handler real en un puerto libre, con el registro de tarjetas en tmp y el log de verdad
    (archivo temporal de conftest + consola), que es justamente lo que se prueba."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    os.makedirs(tmp_path / "sessions", exist_ok=True)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    st.sessions.clear()
    st.transcript_stat.clear()
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    st.sessions.clear()
    st.transcript_stat.clear()


def _get(port: int, path: str, timeout: float = 3.0) -> tuple[int, object, float]:
    t0 = time.monotonic()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", path)
        r = c.getresponse()
        cuerpo = json.loads(r.read() or b"null")
        return r.status, cuerpo, time.monotonic() - t0
    finally:
        c.close()


def _ev(name: str, **k) -> dict:
    return {"hook_event_name": name, "session_id": SID, "agent": "claude", **k}


# --- la causa del 2026-10-05: una consola trabada ---------------------------------------------


def test_consola_trabada_no_deja_sin_respuesta_a_sessions(server_local, monkeypatch):
    """El camino exacto de las 14:57:33: un Notification idle_prompt que se loguea con `lock`
    tomado (sessions.hook_notification) mientras la consola no acepta texto. Antes, ese hilo se
    quedaba en el print con el lock en la mano y GET /sessions no contestaba nunca."""
    consola = ConsolaTrabada()
    monkeypatch.setattr(sys, "stdout", consola)
    try:
        ses.apply_event(_ev("UserPromptSubmit", prompt_id="A", prompt="hace algo"))
        ses.apply_event(_ev("Stop", prompt_id="A", last_assistant_message="listo, quedo hecho."))
        hook = threading.Thread(
            target=ses.apply_event, args=(_ev("Notification", notification_type="idle_prompt"),), daemon=True
        )
        hook.start()
        time.sleep(0.5)
        try:
            code, cuerpo, demora = _get(server_local, "/sessions")
        except TimeoutError:
            pytest.fail("GET /sessions no contesto en 3 s: el hook se quedo con el lock trabado en el print")
        assert code == 200 and [s["session_id"] for s in cuerpo] == [SID]
        assert demora < 2.0
        hook.join(2.0)
        assert not hook.is_alive(), "el hook quedo trabado en el log: la consola no puede frenar a quien loguea"
        with open(st.LOG, encoding="utf-8") as f:
            assert "idle_prompt sin pregunta al final" in f.read(), "el archivo de log tiene todo igual"
    finally:
        consola.suelta.set()


def test_consola_trabada_descarta_y_avisa_cuantas_lineas_no_salieron(monkeypatch):
    """Con la consola trabada el log no crece en memoria sin limite: pasado el tope descarta y,
    cuando la consola vuelve, dice cuantas lineas no salieron (estan todas en el archivo)."""
    consola = ConsolaTrabada()
    escrito: list[str] = []

    class Anota:
        def write(self, t):
            escrito.append(t)
            return len(t)

        def flush(self):
            pass

        def isatty(self):
            return False

    monkeypatch.setattr(st, "CONSOLA_MAX", 5)
    monkeypatch.setattr(sys, "stdout", consola)
    st.consola_reiniciar()
    try:
        for i in range(50):
            st.log(f"linea {i}")
        assert st.consola_estado()["perdidas"] >= 40
    finally:
        monkeypatch.setattr(sys, "stdout", Anota())
        consola.suelta.set()
    limite = time.monotonic() + 3
    while time.monotonic() < limite and not any("no salieron por consola" in t for t in escrito):
        time.sleep(0.05)
    assert any("no salieron por consola" in t for t in escrito), escrito[-5:]
    with open(st.LOG, encoding="utf-8") as f:
        assert f.read().count("linea ") == 50


# --- un par colgado ------------------------------------------------------------------------------


@pytest.fixture
def par_colgado():
    """Un puerto que acepta la conexion y no dice nada nunca: la PC par con el lienzo trabado, o
    una IP que quedo del otro lado de un cambio de red."""
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(16)
    abiertas: list[socket.socket] = []
    corta = threading.Event()

    def aceptar():
        lsock.settimeout(0.2)
        while not corta.is_set():
            try:
                c, _ = lsock.accept()
                abiertas.append(c)  # se queda abierta y muda
            except OSError:
                continue

    threading.Thread(target=aceptar, daemon=True).start()
    yield lsock.getsockname()[1]
    corta.set()
    for c in abiertas:
        c.close()
    lsock.close()


def test_con_un_par_colgado_sessions_contesta(server_local, par_colgado, monkeypatch):
    """El espejo conectado a un par que acepta y no habla: el SSE, la salud y un reenvio quedan
    esperando su timeout, cada uno en su hilo, y GET /sessions sigue contestando enseguida. Al
    vencer, el par queda marcado caido con su motivo y queda en el log."""
    logs: list[str] = []
    monkeypatch.setattr(mirror.MIRROR, "log", logs.append)
    monkeypatch.setattr(mirror.MIRROR, "transport", fed.HTTPTransport(timeout=1.0))
    monkeypatch.setattr(mirror.MIRROR, "diagnosticar", lambda host, e: "no contesta (prueba)")
    monkeypatch.setattr(mirror.MIRROR, "on_change", lambda: None)
    monkeypatch.setattr(mirror, "PEER_TIMEOUT_S", 1.5)
    pc = "c01ga0000001"
    mirror.MIRROR.connect(pc, {"name": "colgada"}, "127.0.0.1", par_colgado, b"k" * 32, "yo0000000000")
    try:
        mirror.MIRROR._get(pc).last_seen = time.time()  # estuvo viva hasta recien
        hilos = [
            threading.Thread(target=mirror.MIRROR._poll_health, args=(pc,), daemon=True),
            threading.Thread(target=mirror.MIRROR.forward, args=(pc, "GET", "/sessions/x/screen"), daemon=True),
        ]
        for h in hilos:
            h.start()
        for _ in range(5):
            code, _cuerpo, demora = _get(server_local, "/sessions")
            assert code == 200 and demora < 0.5, f"GET /sessions tardo {demora:.2f} s con un par colgado"
        for h in hilos:
            h.join(5)
        time.sleep(1.6)
        mirror.MIRROR.revisar_vivos()
        fila = next(p for p in mirror.MIRROR.peers_status() if p["pc_id"] == pc)
        assert fila["alive"] is False
        assert fila["diagnostico"] == "no contesta (prueba)"
        assert any("colgada" in m and "caída" in m for m in logs), logs
    finally:
        mirror.MIRROR.disconnect(pc)


def test_el_listener_de_pares_corta_una_conexion_muda(monkeypatch):
    """Una conexion entrante al 7322 que no manda nada (un par que se fue a mitad de pedido, o
    cualquiera de la red) no deja un hilo esperando para siempre: el PeerHandler tiene timeout."""
    monkeypatch.setattr(server.PeerHandler, "timeout", 0.5)
    srv = server.QuietServer(("127.0.0.1", 0), server.PeerHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = socket.create_connection(srv.server_address, timeout=5)
        c.sendall(b"GET /peer/hello HTTP/1.1\r\n")  # media linea y nada mas
        c.settimeout(5)
        t0 = time.monotonic()
        try:
            resto = c.recv(1024)
        except ConnectionError:
            resto = b""
        assert resto == b"" and time.monotonic() - t0 < 3, "el server tenia que cortar la conexion muda"
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


# --- cambio de red: los listeners de pares se vuelven a ligar -----------------------------------


def test_cambio_de_ip_vuelve_a_ligar_el_listener_y_lo_registra(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(server, "log", logs.append)
    puerto = _puerto_libre()
    ls = server.ListenersDePares(puerto)
    try:
        ls.reconciliar({"lan": "127.0.0.1"})
        assert _escucha("127.0.0.1", puerto)
        ls.reconciliar({"lan": "127.0.0.2"})  # la PC cambio de red: la IP de antes ya no existe
        assert _escucha("127.0.0.2", puerto)
        assert not _escucha("127.0.0.1", puerto)
        assert any("127.0.0.1" in m and "127.0.0.2" in m and "cambió" in m for m in logs), logs
        ls.reconciliar({})  # sin red
        assert not _escucha("127.0.0.2", puerto)
        assert any("sin red" in m for m in logs), logs
        assert ls.estado() == {}
    finally:
        ls.cerrar_todo()


def test_un_listener_que_no_se_puede_ligar_se_reintenta_y_se_avisa_una_vez(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(server, "log", logs.append)
    ocupa = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ocupa.bind(("127.0.0.1", 0))
    ocupa.listen(1)
    puerto = ocupa.getsockname()[1]
    ls = server.ListenersDePares(puerto)
    try:
        ls.reconciliar({"lan": "127.0.0.1"})
        ls.reconciliar({"lan": "127.0.0.1"})
        assert sum("no se pudo tomar" in m for m in logs) == 1, logs
        ocupa.close()
        ls.reconciliar({"lan": "127.0.0.1"})
        assert _escucha("127.0.0.1", puerto)
    finally:
        ocupa.close()
        ls.cerrar_todo()


# --- salud y vigia del lock -----------------------------------------------------------------------


def test_salud_contesta_con_el_lock_tomado_y_dice_quien_lo_tiene(server_local):
    soltar = threading.Event()

    def retener():
        with st.lock:
            soltar.wait(10)

    h = threading.Thread(target=retener, name="retiene-el-lock", daemon=True)
    h.start()
    try:
        time.sleep(1.2)  # mas que SALUD_LOCK_S: lo normal es tenerlo milisegundos
        code, cuerpo, demora = _get(server_local, "/salud")
        assert code == 200 and demora < 1.0
        assert cuerpo["lock"]["hilo"] == "retiene-el-lock"
        assert cuerpo["lock"]["tomado_hace_s"] >= 1.0
        assert cuerpo["ok"] is False
        assert "pares" in cuerpo and "consola" in cuerpo and "listeners" in cuerpo
    finally:
        soltar.set()
        h.join(5)
    code, cuerpo, _ = _get(server_local, "/salud")
    assert code == 200 and cuerpo["lock"] is None


def test_vigia_registra_la_pila_de_quien_retiene_el_lock(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(st, "LOCK_LENTO_S", 0.2)
    soltar = threading.Event()

    def retener_aca():
        with st.lock:
            soltar.wait(10)

    h = threading.Thread(target=retener_aca, name="retiene", daemon=True)
    h.start()
    try:
        time.sleep(0.4)
        server.vigilar_lock_una_vez(logs.append)
        server.vigilar_lock_una_vez(logs.append)  # el mismo episodio no se repite
        assert len(logs) == 1, logs
        assert "retiene" in logs[0] and "retener_aca" in logs[0]
    finally:
        soltar.set()
        h.join(5)


def _puerto_libre() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _escucha(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False
