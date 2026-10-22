"""Copia entre PCs por el listener de peers (lienzo/xfer.py, encargo del 2026-10-04).

Las dos puntas corren en este proceso: el que manda es un `xfer.Trabajo` y el que recibe un
`server.PeerHandler` real en 127.0.0.1, con la firma de siempre (peers.json con la clave de una PC
"origen" inventada). Ademas de copiar y saltear lo igual, cubre lo que pide el encargo y falla sin el
canal: el receptor que muere a mitad y se retoma desde el diario, un bloque que llega corrupto y se
vuelve a pedir, un archivo que cambia en el origen mientras viaja, una ruta fuera de copy_roots y
una firma vieja."""

import contextlib
import fnmatch
import hashlib
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import tempfile
import time
import traceback
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import federation as fed
import state as st
import xfer

MIB = 1024 * 1024
PC_ORIGEN = "a1a1a1a1a1a1"

# La distro se apaga sola a los ~30 s sin uso y el primer acceso UNC la vuelve a levantar; ese
# arranque corre `systemd-tmpfiles --remove --boot` y la regla `D /tmp` vacía /tmp con la prueba
# en curso (cierre 409 con ceros, WinError 2). Medido el 2026-10-21 (noche) en .temp/resultados/noche-A.
WSL_BASE_LINUX = "/var/tmp"
WSL_BASE = "\\\\wsl.localhost\\Ubuntu" + WSL_BASE_LINUX.replace("/", "\\")


def _puerto_libre() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class _Server(server.QuietServer):
    """Anota cada conexion aceptada: matar el server tiene que cortar tambien las keep-alive ya
    abiertas, como cuando el proceso muere (shutdown solo deja de aceptar nuevas)."""

    def get_request(self):
        sock, addr = super().get_request()
        self.socks.append(sock)
        return sock, addr


class Receptor:
    """Un PeerHandler real que se puede matar y volver a levantar en el mismo puerto."""

    def __init__(self, port: int):
        self.port = port
        self.srv = None

    def levantar(self) -> None:
        for _ in range(50):
            try:
                self.srv = _Server(("127.0.0.1", self.port), server.PeerHandler)
                self.srv.socks = []
                break
            except OSError:
                time.sleep(0.1)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def matar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        for sock in self.srv.socks:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except OSError:
                pass


@pytest.fixture
def canal(tmp_path, monkeypatch):
    home = tmp_path / "home"
    origen = tmp_path / "origen"
    destino = tmp_path / "destino"
    for d in (home, origen, destino):
        d.mkdir()
    monkeypatch.setattr(st, "LIENZO", str(home))
    monkeypatch.setattr(server, "log", lambda msg: None)
    monkeypatch.setattr(xfer, "log", lambda msg: None)
    monkeypatch.setattr(st, "load_config", lambda: {"copy_roots": [str(origen), str(destino)]})
    monkeypatch.setattr(xfer, "REINTENTO_MAX_S", 0.3)
    # la memoria real de la PC no entra en las pruebas: con la PC bajo la reserva, el freno dejaba
    # cada copia esperando para siempre (medido el 2026-10-04)
    monkeypatch.setattr(xfer, "mem_libre_gb", lambda: None)
    key = secrets.token_bytes(32)
    peers = str(home / "peers.json")
    monkeypatch.setattr(server, "PEERS_FILE", peers)
    fed.add_peer(peers, {"pc_id": PC_ORIGEN, "name": "origen", "ip": "127.0.0.1", "port": 1, "key": key.hex()})
    rec = Receptor(_puerto_libre())
    rec.levantar()
    conn = fed.PeerConn(host="127.0.0.1", port=rec.port, key=key, self_pc_id=PC_ORIGEN)
    monkeypatch.setattr(xfer, "conn_de", lambda pc: conn if pc == "destino-pc" else None)
    xfer.TRABAJOS.clear()
    xfer.CACHE.cerrar()
    yield {"origen": origen, "destino": destino, "rec": rec, "conn": conn, "home": home}
    for t in list(xfer.TRABAJOS.values()):
        t.pausar()
        if t._hilo is not None:
            t._hilo.join(timeout=10)
    xfer.TRABAJOS.clear()
    xfer.CACHE.cerrar()
    with contextlib.suppress(Exception):  # ya muerto por la prueba
        rec.matar()


def _escribir(p, data: bytes) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def _arbol(origen) -> dict[str, bytes]:
    """Cientos de chicos en varias subcarpetas (la forma de una carpeta de recortes) y un grande."""
    datos = {}
    for c in range(12):
        for i in range(25):
            datos[f"fuente{c:02d}/pag{i:03d}.jpg"] = os.urandom(2000 + 37 * i)
    datos["vacio.txt"] = b""
    datos["dump/partida.dat"] = os.urandom(5 * MIB + 12345)
    for rel, b in datos.items():
        _escribir(os.path.join(origen, *rel.split("/")), b)
    return datos


def _correr(canal, *, esperar=True, **kw) -> xfer.Trabajo:
    d = {"pc": "destino-pc", "origen": str(canal["origen"]), "destino": str(canal["destino"]), "bs_mib": 1, **kw}
    code, res = xfer.nuevo(d, "yo")
    assert code == 202, res
    t = xfer.TRABAJOS[res["id"]]
    if esperar:
        _esperar_fin(t)
    return t


def _esperar_fin(t: xfer.Trabajo, s: float = 60) -> None:
    fin = time.time() + s
    while time.time() < fin and t.estado not in ("terminado", "con_errores", "error", "pausado", "confirmar_espejo"):
        time.sleep(0.05)
    t._hilo.join(timeout=10)


def _igual(canal, datos: dict[str, bytes]) -> None:
    for rel, b in datos.items():
        p = os.path.join(canal["destino"], *rel.split("/"))
        with open(p, "rb") as f:
            assert f.read() == b, rel
        assert os.stat(p).st_mtime_ns == os.stat(os.path.join(canal["origen"], *rel.split("/"))).st_mtime_ns
    sobras = [
        os.path.join(r, n)
        for r, _, ns in os.walk(canal["destino"])
        for n in ns
        if n.endswith((xfer.PARTE, xfer.DIARIO))
    ]
    assert sobras == []


def test_copia_arbol_y_la_segunda_vez_no_manda_nada(canal):
    datos = _arbol(canal["origen"])
    t = _correr(canal)
    assert t.estado == "terminado", t.errores
    _igual(canal, datos)
    assert t.archivos_hechos == len(datos)
    v = t.vista()
    assert v["pct"] == 100.0 and v["archivos_hechos"] == len(datos)

    t2 = _correr(canal)
    assert t2.estado == "terminado", t2.errores
    assert t2.bytes_enviados == 0
    assert t2.salteados == len(datos)


def test_solo_viaja_el_bloque_que_cambio(canal):
    datos = _arbol(canal["origen"])
    assert _correr(canal).estado == "terminado"
    grande = os.path.join(canal["origen"], "dump", "partida.dat")
    b = bytearray(datos["dump/partida.dat"])
    b[3 * MIB + 10] ^= 0xFF  # un byte del cuarto bloque
    _escribir(grande, bytes(b))
    datos["dump/partida.dat"] = bytes(b)
    t = _correr(canal)
    assert t.estado == "terminado", t.errores
    assert t.bytes_enviados == MIB  # un bloque de 1 MiB, nada mas
    _igual(canal, datos)


def test_mismo_tamano_y_fecha_no_alcanzan_para_saltear(canal):
    datos = _arbol(canal["origen"])
    assert _correr(canal).estado == "terminado"
    rel = "fuente03/pag004.jpg"
    p = os.path.join(canal["destino"], *rel.split("/"))
    st0 = os.stat(p)
    with open(p, "r+b") as f:  # mismo tamano, mismo mtime, otro contenido
        f.write(b"X")
    os.utime(p, ns=(st0.st_mtime_ns, st0.st_mtime_ns))
    xfer.CACHE.cerrar()
    os.remove(os.path.join(canal["home"], "xfer", "hashes.db"))  # sin la cache: el destino rehashea
    t = _correr(canal)
    assert t.estado == "terminado"
    assert t.salteados == len(datos) - 1
    _igual(canal, datos)


def test_receptor_muere_a_mitad_y_se_retoma_desde_el_diario(canal, monkeypatch):
    datos = {"grande.bin": os.urandom(24 * MIB)}
    _escribir(os.path.join(canal["origen"], "grande.bin"), datos["grande.bin"])
    llegados = []
    original = xfer.r_bloque

    def contar(raw):
        r = original(raw)
        llegados.append(json.loads(raw[: raw.index(b"\n")])["i"])
        return r

    monkeypatch.setattr(xfer, "r_bloque", contar)
    t = _correr(canal, esperar=False, mbps=12, hilos=2)
    fin = time.time() + 20
    while len(llegados) < 8 and time.time() < fin:
        time.sleep(0.02)
    canal["rec"].matar()  # el receptor se cae a mitad de la copia
    antes = set(llegados)
    diario = xfer.leer_diario(os.path.join(canal["destino"], "grande.bin"), MIB)
    assert diario is not None and len(diario) >= 8
    time.sleep(1.0)
    assert t.estado == "copiando" and "reintento" in t.detalle
    llegados.clear()
    canal["rec"].levantar()
    _esperar_fin(t)
    assert t.estado == "terminado", t.errores
    _igual(canal, datos)
    # retomo: lo que ya estaba en el diario no viaja de nuevo, salvo los bloques que estaban en vuelo
    # cuando murio el receptor (hasta `hilos`): los escribio pero su respuesta no llego, y el emisor los
    # reintenta. La asercion estricta fallaba de vez en cuando segun el instante del corte (2026-10-10)
    assert len(set(diario) & set(llegados)) <= 2
    assert len(antes) + len(llegados) <= 24 + 2


def test_el_que_manda_se_reinicia_y_retoma_sin_releer_lo_hecho(canal, monkeypatch):
    datos = {"a.txt": b"primero", "b.txt": b"segundo", "c.txt": b"tercero"}
    for rel, data in datos.items():
        _escribir(os.path.join(canal["origen"], rel), data)
    confirmado, seguir = threading.Event(), threading.Event()
    original = xfer.Trabajo._hecho

    def al_confirmar(self, rel, *args):
        original(self, rel, *args)
        if rel == "a.txt":
            confirmado.set()
            if not seguir.wait(20):
                raise RuntimeError("la prueba no liberó el archivo confirmado")

    monkeypatch.setattr(xfer, "GRUPO", 1)
    monkeypatch.setattr(xfer.Trabajo, "_hecho", al_confirmar)
    t = _correr(canal, esperar=False, mbps=1, hilos=1)
    try:
        assert confirmado.wait(20), "no se confirmó el primer archivo"
        assert t.archivos_hechos == 1
        xfer.pausar(t.id)
    finally:
        seguir.set()
    t._hilo.join(timeout=10)
    assert t.estado == "pausado"
    hechos = t.archivos_hechos
    # el server se reinicia: el registro se pierde y se carga de disco
    with open(t._ruta(".json"), encoding="utf-8") as f:
        guardado = json.load(f)
    guardado["estado"] = "copiando"  # como quedaria si se cortaba la luz
    st.atomic_write(t._ruta(".json"), json.dumps(guardado))
    xfer.TRABAJOS.clear()
    xfer.arrancar()
    t2 = xfer.TRABAJOS[t.id]
    t2._red = xfer.Balde(0)
    _esperar_fin(t2)
    assert t2.estado == "terminado", t2.errores
    assert t2.salteados == 0  # lo hecho antes no se volvio a comparar: salio del .hechos
    assert t2.archivos_hechos == len(datos) and hechos > 0
    _igual(canal, datos)


def test_bloque_corrupto_en_el_camino_se_rechaza_y_se_vuelve_a_mandar(canal, monkeypatch):
    datos = {"grande.bin": os.urandom(4 * MIB)}
    _escribir(os.path.join(canal["origen"], "grande.bin"), datos["grande.bin"])
    original = xfer._armar
    rotos = []

    def romper(cab, datos_):
        cuerpo = original(cab, datos_)
        if "i" in cab and cab["i"] == 2 and not rotos:
            rotos.append(1)
            cuerpo = cuerpo[:-1] + bytes([cuerpo[-1] ^ 1])  # un bit cambiado despues de hashear
        return cuerpo

    monkeypatch.setattr(xfer, "_armar", romper)
    t = _correr(canal)
    assert rotos and t.estado == "terminado", t.errores
    assert any("llego corrupto" in e for e in t.errores)
    _igual(canal, datos)


def test_bloque_corrupto_en_disco_lo_detecta_el_cierre(canal):
    path = os.path.join(canal["destino"], "a.bin")
    data = os.urandom(3 * MIB)
    hashes = [xfer.hash_bytes(data[i : i + MIB]) for i in range(0, len(data), MIB)]
    base = {"destino": str(canal["destino"]), "bs": MIB, "rel": "a.bin", "size": len(data)}
    for i in range(3):
        xfer.r_bloque(xfer._armar({**base, "i": i, "hash": hashes[i]}, data[i * MIB : (i + 1) * MIB]))
    with open(path + xfer.PARTE, "r+b") as f:  # el disco del destino devuelve otra cosa
        f.seek(MIB + 5)
        f.write(b"\x00\x01")
    code, res = xfer.r_cerrar({**base, "mtime_ns": 1, "hashes": hashes})
    assert code == 409 and res["faltan"] == [1]
    assert not os.path.exists(path)  # nunca queda el nombre bueno con un archivo a medias
    assert 1 not in xfer.leer_diario(path, MIB)


def test_archivo_que_cambia_en_el_origen_mientras_viaja(canal, monkeypatch):
    p = os.path.join(canal["origen"], "vivo.bin")
    _escribir(p, os.urandom(6 * MIB))
    original = xfer.Trabajo._leer
    cambios = []

    def leer(self, path, off, n):
        b = original(self, path, off, n)
        if off == 3 * MIB and not cambios:
            cambios.append(1)
            with open(p, "r+b") as f:  # alguien escribe el archivo con la copia en curso
                f.seek(MIB)
                f.write(b"cambiado")
            os.utime(p, ns=(time.time_ns() + 10**9,) * 2)
        return b

    monkeypatch.setattr(xfer.Trabajo, "_leer", leer)
    t = _correr(canal, hilos=1)
    assert t.estado == "terminado", t.errores
    assert any("cambio en el origen" in e for e in t.errores)
    with open(p, "rb") as f:
        _igual(canal, {"vivo.bin": f.read()})


def test_fuera_de_copy_roots_no_se_copia_ni_se_escribe(canal, tmp_path):
    afuera = tmp_path / "afuera"
    afuera.mkdir()
    _escribir(str(afuera / "x.txt"), b"hola")
    code, res = xfer.nuevo({"pc": "destino-pc", "origen": str(afuera), "destino": str(canal["destino"])}, "yo")
    assert code == 403 and "copy_roots" in res["error"]
    # y del lado que recibe, aunque el pedido venga bien firmado
    body = json.dumps({"destino": str(afuera), "bs": MIB, "archivos": []}).encode()
    status, res = _firmado(canal, "/peer/xfer/estado", body)
    assert status == 403 and "copy_roots" in res["error"]
    body = json.dumps({"destino": str(canal["destino"]), "bs": MIB, "archivos": ["../afuera/x.txt"]}).encode()
    status, res = _firmado(canal, "/peer/xfer/estado", body)
    assert status == 400
    cab = {
        "destino": str(canal["destino"]),
        "bs": MIB,
        "archivos": [{"rel": "../../x", "size": 1, "mtime_ns": 1, "hash": xfer.hash_bytes(b"a")}],
    }
    status, res = _firmado(canal, "/peer/xfer/paquete", xfer._armar(cab, b"a"))
    assert status == 400
    assert not os.path.exists(tmp_path / "x")


def _firmado(canal, path, body, ts=None):
    conn = canal["conn"]
    headers = fed.signed_headers(conn, "POST", path, body)
    if ts is not None:
        nonce = secrets.token_hex(16)
        headers.update(
            {
                "X-Lienzo-Ts": repr(ts),
                "X-Lienzo-Nonce": nonce,
                "X-Lienzo-Sig": fed.sign(conn.key, "POST", path, body, ts, nonce),
            }
        )
    c = http.client.HTTPConnection("127.0.0.1", conn.port, timeout=10)
    try:
        c.request("POST", path, body=body, headers=headers)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()


def test_firma_vieja_o_sin_firma_no_escribe(canal):
    data = b"z" * 1000
    cab = {
        "destino": str(canal["destino"]),
        "bs": MIB,
        "archivos": [{"rel": "z.txt", "size": len(data), "mtime_ns": 1, "hash": xfer.hash_bytes(data)}],
    }
    body = xfer._armar(cab, data)
    status, _ = _firmado(canal, "/peer/xfer/paquete", body, ts=time.time() - 120)
    assert status == 401
    # sin headers de firma: 401 sin leer el cuerpo (que podria ser de 33 MiB)
    c = http.client.HTTPConnection("127.0.0.1", canal["conn"].port, timeout=10)
    c.request("POST", "/peer/xfer/paquete", body=body, headers={"Content-Length": str(len(body))})
    assert c.getresponse().status == 401
    c.close()
    assert not os.path.exists(os.path.join(canal["destino"], "z.txt"))
    status, res = _firmado(canal, "/peer/xfer/paquete", body)  # la misma, firmada ahora: pasa
    assert status == 200 and res["archivos"]["z.txt"] == "ok"


def test_conexion_lenta_no_consume_ventana_de_firma(canal, monkeypatch):
    """La firma debe nacer después de conectar, incluso tras perder el keep-alive."""
    original_connect = http.client.HTTPConnection.connect
    connected = []
    signed = []
    original_headers = fed.signed_headers

    def connect(conn):
        original_connect(conn)
        connected.append(conn)

    def headers(*args):
        assert connected, "se firmó antes de completar la conexión TCP"
        signed.append(len(connected))
        return original_headers(*args)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    monkeypatch.setattr(fed, "signed_headers", headers)
    trabajo = xfer.Trabajo({"id": "firma-conexion", "pc": "destino-pc"})
    body = json.dumps({"destino": str(canal["destino"]), "bs": MIB, "archivos": []}).encode()
    try:
        for _ in range(2):
            code, _ = trabajo.pedir("estado", body)
            assert code == 200
        assert len(connected) == 1  # conserva keep-alive
        trabajo._soltar()
        assert trabajo.pedir("estado", body)[0] == 200
        assert signed == [1, 1, 2]
    finally:
        trabajo._soltar()


@pytest.mark.parametrize("limite", ["mbps", "disco_mbps"])
def test_pausa_interrumpe_limite_y_devuelve_presupuesto(monkeypatch, limite):
    job = xfer.Trabajo({"id": "pausa-limite", limite: 0.000001})
    started, cleanup, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    wait = job._esperar

    def waiting(seconds):
        started.set()
        wait(seconds)

    def uninterruptible_sleep(seconds):
        started.set()
        assert cleanup.wait(5), "limpieza de la prueba no solicitada"

    def worker():
        try:
            if limite == "mbps":
                job._enviar("paquete", b"synthetic", 30)
            else:
                job._leer("NO_DEBE_ABRIRSE", 0, 30)
            errors.append("continuó después de pausar")
        except xfer.Pausa:
            pass
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            finished.set()

    monkeypatch.setattr(job, "_esperar", waiting)
    monkeypatch.setattr(xfer, "time", SimpleNamespace(monotonic=time.monotonic, sleep=uninterruptible_sleep))
    monkeypatch.setattr(xfer, "mem_libre_gb", lambda: None)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert started.wait(2)
        job.pausar()
        assert finished.wait(1), "el límite de velocidad no se interrumpe con pausa"
        assert not errors
        bucket = job._red if limite == "mbps" else job._disco
        assert bucket._fichas == pytest.approx(bucket.rate)
    finally:
        job.pausar()
        cleanup.set()
        thread.join(2)
    assert not thread.is_alive()


def test_espejo_lista_antes_y_borra_solo_con_confirmacion(canal):
    datos = _arbol(canal["origen"])
    _escribir(os.path.join(canal["destino"], "viejo", "sobra.txt"), b"sobra")
    t = _correr(canal, espejo=True)
    assert t.estado == "confirmar_espejo"
    assert t.vista()["borraria"] == ["viejo/sobra.txt"]
    assert os.path.exists(os.path.join(canal["destino"], "viejo", "sobra.txt"))
    assert xfer.retomar(t.id, confirmar=True)[0] == 202
    _esperar_fin(t)
    assert t.estado == "terminado", t.errores
    assert not os.path.exists(os.path.join(canal["destino"], "viejo", "sobra.txt"))
    _igual(canal, datos)


@pytest.mark.parametrize("previous", ["pausado", "confirmar_espejo"])
def test_retomar_publica_estado_activo_antes_de_fases(canal, monkeypatch, previous):
    t = xfer.Trabajo(
        {
            "id": "barrera-inicio",
            "estado": previous,
            "pc": "destino-pc",
            "origen": str(canal["origen"]),
            "destino": str(canal["destino"]),
            "bs": MIB,
            "hilos": 1,
            "espejo": previous == "confirmar_espejo",
            "errores": ["error anterior"],
        }
    )
    t._pausa.set()
    entered, release = threading.Event(), threading.Event()

    def fases_con_barrera():
        entered.set()
        assert release.wait(30), "la prueba no liberó su hilo"
        t.estado = "terminado"

    monkeypatch.setattr(t, "_fases", fases_con_barrera)
    xfer.TRABAJOS[t.id] = t
    try:
        code, response = xfer.retomar(t.id, confirmar=t.espejo)
        assert code == 202 and response == {"id": t.id}
        assert entered.wait(10), "el hilo no llegó a la barrera"
        assert t.estado == "listando"
        assert not t._pausa.is_set()
        assert t.confirmado is t.espejo
        assert t.errores == []
    finally:
        release.set()
        if t._hilo is not None:
            t._hilo.join(timeout=10)
    assert t.estado == "terminado"


def test_arrancar_no_duplica_hilo_vivo_ni_resetea_su_estado(canal, monkeypatch):
    t = xfer.Trabajo({"id": "barrera-vivo", "estado": "pausado", "errores": ["conservar"]})
    entered, release = threading.Event(), threading.Event()

    def fases_con_barrera():
        entered.set()
        assert release.wait(30), "la prueba no liberó su hilo"
        raise RuntimeError("fallo inocuo de fases")

    monkeypatch.setattr(t, "_fases", fases_con_barrera)
    xfer.TRABAJOS[t.id] = t
    try:
        t.arrancar()
        assert entered.wait(10), "el hilo no llegó a la barrera"
        original = t._hilo
        t.estado = "copiando"
        t.pausar()
        t.arrancar()
        assert t._hilo is original
        assert t.estado == "copiando" and t._pausa.is_set()
        assert t.errores == ["conservar"]
    finally:
        release.set()
        if t._hilo is not None:
            t._hilo.join(timeout=10)
    assert t.estado == "error"
    assert any("fallo inocuo de fases" in error for error in t.errores)


def test_sin_espejo_nunca_borra(canal):
    _arbol(canal["origen"])
    _escribir(os.path.join(canal["destino"], "sobra.txt"), b"sobra")
    assert _correr(canal).estado == "terminado"
    assert os.path.exists(os.path.join(canal["destino"], "sobra.txt"))


def test_hash_del_archivo_es_el_de_la_lista_de_bloques():
    hs = [hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()]
    assert xfer.hash_total(hs) == hashlib.sha256("\n".join(hs).encode()).hexdigest()


def test_ruta_wsl_y_soltar_la_cache_cada_tanto(monkeypatch):
    """Copiar GB por 9p llenaba la cache de la VM de WSL y la PC que recibia bajaba de 2,6 a 0,5 GB
    libres (medido el 2026-10-04): cada SOLTAR_CADA bytes y al cerrar se le pide a WSL que la suelte."""
    assert xfer.ruta_wsl("//wsl.localhost/Ubuntu-24.04/home/ariel/x.bin") == ("Ubuntu-24.04", "/home/ariel/x.bin")
    assert xfer.ruta_wsl("//wsl$/Ubuntu/home/a/b") == ("Ubuntu", "/home/a/b")
    assert xfer.ruta_wsl("C:/datos/x.bin") is None
    sueltos = []
    monkeypatch.setattr(xfer, "soltar_cache", sueltos.append)
    sol = xfer.Soltador()
    p = "//wsl.localhost/Ubuntu/home/a/grande.bin"
    for _ in range(xfer.SOLTAR_CADA // MIB - 1):
        sol.sumar(p, MIB)
    assert sueltos == []
    sol.sumar(p, MIB)
    assert sueltos == [p]
    sol.sumar("C:/datos/x.bin", xfer.SOLTAR_CADA)  # fuera de WSL no cuenta
    sol.cerrar(p)
    assert sueltos == [p, p]


def test_traer_manda_el_archivo_mas_nuevo_a_la_pc_que_lo_pide(canal):
    viejo, nuevo = canal["origen"] / "viejo.zip", canal["origen"] / "nuevo.zip"
    _escribir(viejo, os.urandom(3000))
    _escribir(nuevo, os.urandom(2 * MIB + 7))
    os.utime(viejo, ns=(1_000_000_000, 1_000_000_000))
    _escribir(canal["origen"] / ("a" + xfer.PARTE), b"temporal mas nuevo")
    code, res = xfer.enviar_a_pedido(
        {"origen": str(canal["origen"]), "destino": str(canal["destino"]), "ultimo": True}, "destino-pc", "yo"
    )
    assert code == 202 and res["origen"] == str(nuevo), res
    _esperar_fin(xfer.TRABAJOS[res["id"]])
    assert (canal["destino"] / "nuevo.zip").read_bytes() == nuevo.read_bytes()
    assert not (canal["destino"] / "viejo.zip").exists()


def test_traer_exige_firma_y_origen_dentro_de_copy_roots(canal, tmp_path):
    pedido = {"origen": str(canal["origen"]), "destino": str(canal["destino"]), "ultimo": True}
    assert xfer.enviar_a_pedido(pedido, None, "yo")[0] == 401
    afuera = tmp_path / "afuera"
    afuera.mkdir()
    assert xfer.enviar_a_pedido({**pedido, "origen": str(afuera)}, "destino-pc", "yo")[0] == 403
    assert xfer.enviar_a_pedido(pedido, "destino-pc", "yo")[0] == 404  # carpeta vacia
    assert not xfer.TRABAJOS


def test_traer_local_valida_el_destino_antes_de_reenviar(canal, tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(xfer, "reenviar", lambda *a: (llamadas.append(a), (202, {"id": "abc"}))[1])
    pedido = {"pc": "otra-pc", "origen": "C:/Users/x/Downloads", "ultimo": True}
    code, res = xfer.traer({**pedido, "destino": str(tmp_path / "afuera")}, "yo")
    assert code == 403 and not llamadas
    assert xfer.traer({**pedido, "pc": "yo", "destino": str(canal["destino"])}, "yo")[0] == 400
    code, res = xfer.traer({**pedido, "destino": str(canal["destino"])}, "yo")
    assert code == 202 and res == {"id": "abc", "pc": "otra-pc"}
    assert llamadas == [
        (
            "otra-pc",
            "POST",
            "/xfer/traer",
            {"origen": pedido["origen"], "destino": str(canal["destino"]), "ultimo": True},
        )
    ]


@pytest.mark.parametrize("size", [113, 3 * MIB + 17], ids=["chico", "varios-bloques"])
def test_cache_caliente_no_certifica_bytes_alterados(canal, size):
    rel = "caliente.bin"
    original = b"a" * size
    source = canal["origen"] / rel
    target = canal["destino"] / rel
    source.write_bytes(original)
    first = _correr(canal)
    assert first.estado == "terminado", first.errores
    db = xfer.CACHE._db
    assert db is not None
    before = target.stat()
    with target.open("r+b") as f:
        f.seek(size // 2)
        f.write(b"b")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert target.stat().st_size == before.st_size
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert target.read_bytes() != original
    work = _correr(canal)
    assert xfer.CACHE._db is db, "la caché tiene que seguir abierta durante la reproducción"
    assert work.estado == "terminado", work.errores
    assert target.read_bytes() == original
    assert work.salteados == 0
    assert work.bytes_enviados == min(MIB, size)
    normal = _correr(canal)
    assert normal.estado == "terminado"
    assert normal.salteados == 1 and normal.bytes_enviados == 0


def test_cierre_con_cache_caliente_no_certifica_destino_alterado(canal):
    target = canal["destino"] / "final.bin"
    target.write_bytes(b"original")
    hashes = [xfer.hash_bytes(b"original")]
    assert xfer._hashes_final(str(target), MIB) == hashes
    db = xfer.CACHE._db
    before = target.stat()
    target.write_bytes(b"alterado")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    code, response = xfer.r_cerrar(
        {
            "destino": str(canal["destino"]),
            "bs": MIB,
            "rel": target.name,
            "size": 8,
            "mtime_ns": before.st_mtime_ns,
            "hashes": hashes,
        }
    )
    assert xfer.CACHE._db is db
    assert code == 409 and response["faltan"] == [0]
    assert target.read_bytes() == b"alterado"


@pytest.mark.parametrize("extension", [xfer.PARTE, xfer.DIARIO])
@pytest.mark.parametrize("action", ["estado", "bloque", "cerrar"])
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_auxiliar_enlazado_se_rechaza_sin_alterar_victima(canal, tmp_path, extension, action, link_kind):
    target = canal["destino"] / "enlace.bin"
    victim = tmp_path / "victima.bin"
    data = b"VICTIMA-EXTERIOR-INTACTA"
    victim.write_bytes(data if extension == xfer.PARTE else b"bs 1048576\n")
    if extension == xfer.PARTE:
        (canal["destino"] / (target.name + xfer.DIARIO)).write_text("bs 1048576\n", encoding="ascii")
    else:
        (canal["destino"] / (target.name + xfer.PARTE)).write_bytes(data)
    aux = str(target) + extension
    try:
        (os.symlink if link_kind == "symlink" else os.link)(victim, aux)
    except OSError as exc:
        if link_kind == "symlink" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink no disponible sin privilegios; no se cambian permisos")
        raise
    before = victim.read_bytes(), victim.stat().st_mtime_ns
    base = {"destino": str(canal["destino"]), "bs": MIB, "rel": target.name, "size": 1}
    if action == "bloque":
        raw = xfer._armar({**base, "i": 0, "hash": xfer.hash_bytes(b"x")}, b"x")
    elif action == "cerrar":
        raw = json.dumps({**base, "mtime_ns": 1, "hashes": [xfer.hash_bytes(b"x")]}).encode()
    else:
        raw = json.dumps({**base, "archivos": [target.name]}).encode()
    code, response = xfer.atender_peer([action], raw)
    # Comprobar la víctima incluso cuando el receptor no rechazó el pedido.
    assert (victim.read_bytes(), victim.stat().st_mtime_ns) == before
    assert code in (400, 403), response


def test_parte_redirigida_entre_preparacion_y_apertura(canal, tmp_path, monkeypatch):
    target = canal["destino"] / "carrera.bin"
    victim = tmp_path / "victima-carrera.bin"
    victim.write_bytes(b"intacta")
    original = xfer._asegurar_parte
    blocked = []

    def redirect(path, bs):
        original(path, bs)
        try:
            os.unlink(path + xfer.PARTE)
        except PermissionError:
            blocked.append(True)
            return
        os.link(victim, path + xfer.PARTE)

    monkeypatch.setattr(xfer, "_asegurar_parte", redirect)
    raw = xfer._armar(
        {
            "destino": str(canal["destino"]),
            "bs": MIB,
            "rel": target.name,
            "size": 1,
            "i": 0,
            "hash": xfer.hash_bytes(b"x"),
        },
        b"x",
    )
    code, response = xfer.atender_peer(["bloque"], raw)
    assert victim.read_bytes() == b"intacta"
    assert code == 200 if blocked else code in (400, 403), response


@pytest.mark.skipif(sys.platform != "win32", reason="junction nativa de Windows")
def test_junction_cambiada_antes_de_abrir_parte_no_altera_victima(canal, tmp_path, monkeypatch):
    folder = canal["destino"] / "sub"
    folder.mkdir()
    outside = tmp_path / "exterior-junction"
    outside.mkdir()
    victim = outside / ("a.bin" + xfer.PARTE)
    victim.write_bytes(b"intacta")
    original = xfer._asegurar_parte
    blocked = []

    def redirect(path, bs):
        original(path, bs)
        try:
            folder.rename(canal["destino"] / "sub-original")
        except PermissionError:
            blocked.append(True)  # Un handle que fija la carpeta impide la redirección.
            return
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(folder), str(outside)],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )

    monkeypatch.setattr(xfer, "_asegurar_parte", redirect)
    raw = xfer._armar(
        {
            "destino": str(canal["destino"]),
            "bs": MIB,
            "rel": "sub/a.bin",
            "size": 1,
            "i": 0,
            "hash": xfer.hash_bytes(b"x"),
        },
        b"x",
    )
    code, response = xfer.atender_peer(["bloque"], raw)
    assert victim.read_bytes() == b"intacta"
    assert code == 200 if blocked else code in (400, 403), response


@pytest.mark.skipif(sys.platform != "win32", reason="junction nativa de Windows")
@pytest.mark.parametrize("punto", ["unir", "permitido"])
def test_espejo_no_borra_por_junction_puesta_tras_validar(canal, tmp_path, monkeypatch, punto):
    """El borrado del espejo validaba la ruta y después borraba por nombre: una junction puesta en
    el medio llevaba el borrado afuera del destino. `punto` es la última validación por ruta antes
    de la sustitución; después de `permitido` sólo quedan los handles fijados."""
    folder = canal["destino"] / "sub"
    folder.mkdir()
    (folder / "a.bin").write_bytes(b"del destino")
    outside = tmp_path / "exterior-espejo"
    outside.mkdir()
    victim = outside / "a.bin"
    victim.write_bytes(b"intacta")
    target = os.path.normcase(str(folder / "a.bin"))
    swapped = []

    def swap():
        folder.rename(canal["destino"] / "sub-original")
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(folder), str(outside)],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
        swapped.append(True)

    original = getattr(xfer, punto)

    def validar_y_sustituir(*args):
        out = original(*args)
        ruta = out if punto == "unir" else args[0]
        if not swapped and out is not None and os.path.normcase(os.path.normpath(ruta)) == target:
            swap()
        return out

    monkeypatch.setattr(xfer, punto, validar_y_sustituir)
    code, response = xfer.atender_peer(
        ["borrar"], json.dumps({"destino": str(canal["destino"]), "rels": ["sub/a.bin"]}).encode()
    )
    assert swapped, "la sustitución tiene que ocurrir entre la validación y el borrado"
    assert victim.read_bytes() == b"intacta"
    assert (code, response) == (200, {"borrados": 0, "rechazados": 1})


def test_espejo_borra_dentro_del_destino_sin_crear_carpetas(canal):
    destino = canal["destino"]
    (destino / "sub").mkdir()
    (destino / "sub" / "a.bin").write_bytes(b"sobra")
    (destino / "b.bin").write_bytes(b"sobra")
    os.link(destino / "b.bin", destino / "b-otro.bin")  # borrar un nombre no toca el otro
    rels = ["sub/a.bin", "b.bin", "no-esta.bin", "vieja/sub/c.bin", "../fuera.bin"]
    body = {"destino": str(destino), "rels": rels}
    assert xfer.atender_peer(["borrar"], json.dumps(body).encode()) == (200, {"borrados": 2, "rechazados": 0})
    assert not (destino / "sub" / "a.bin").exists() and not (destino / "b.bin").exists()
    assert (destino / "b-otro.bin").read_bytes() == b"sobra"
    assert not (destino / "vieja").exists()


def test_control_creacion_carpetas_nuevas_y_publicacion(canal):
    rel = "nueva/anidada/control.txt"
    data = b"control normal"
    response = xfer.r_paquete(
        xfer._armar(
            {
                "destino": str(canal["destino"]),
                "bs": MIB,
                "archivos": [{"rel": rel, "size": len(data), "mtime_ns": 123456789000, "hash": xfer.hash_bytes(data)}],
            },
            data,
        )
    )
    assert response["archivos"][rel] == "ok"
    target = canal["destino"] / rel
    assert target.read_bytes() == data
    assert target.stat().st_mtime_ns == 123456789000
    target.rename(target.with_suffix(".renombrado"))  # ningún handle propio quedó abierto


def test_control_abrir_seguro_libera_handle(canal):
    target = str(canal["destino"] / "handle.bin")
    with xfer._abrir_seguro(target, "wb") as f:
        f.write(b"control")
    os.unlink(target)
    assert not os.path.exists(target)


@pytest.mark.skipif(sys.platform != "win32", reason="pinning de directorios Windows")
def test_carpeta_nueva_permanece_fijada_hasta_salir(canal):
    folder = canal["destino"] / "nueva" / "fijada"
    moved = folder.with_name("movida")
    with xfer._carpeta_fija(str(folder / "archivo.bin")):
        assert folder.is_dir()
        with pytest.raises(PermissionError):
            folder.rename(moved)
    folder.rename(moved)
    assert moved.is_dir()


@pytest.mark.parametrize("action", ["estado", "cerrar"])
def test_final_hardlink_no_modifica_victima(canal, tmp_path, action):
    victim = tmp_path / "final-victima.bin"
    victim.write_bytes(b"intacta")
    target = canal["destino"] / "final-hardlink.bin"
    os.link(victim, target)
    before = victim.read_bytes(), victim.stat().st_mtime_ns
    body = {
        "destino": str(canal["destino"]),
        "bs": MIB,
        "rel": target.name,
        "size": 7,
        "mtime_ns": 1,
        "hashes": [xfer.hash_bytes(b"intacta")],
        "archivos": [target.name],
    }
    code, response = xfer.atender_peer([action], json.dumps(body).encode())
    assert (victim.read_bytes(), victim.stat().st_mtime_ns) == before
    assert code in (400, 403), response


@pytest.mark.skipif(sys.platform != "win32", reason="publicación nativa Windows")
def test_publicacion_conserva_handle_verificado(canal, tmp_path, monkeypatch):
    victim = tmp_path / "publicacion-victima.bin"
    victim.write_bytes(b"intacta")
    original = xfer._publicar_parte
    protected = []

    def publish(path, f):
        try:
            os.unlink(path + xfer.PARTE)
        except PermissionError:
            protected.append(True)
        else:
            os.link(victim, path + xfer.PARTE)
        original(path, f)

    monkeypatch.setattr(xfer, "_publicar_parte", publish)
    data = b"contenido verificado"
    raw = xfer._armar(
        {
            "destino": str(canal["destino"]),
            "bs": MIB,
            "archivos": [{"rel": "publicado.bin", "size": len(data), "mtime_ns": 12300, "hash": xfer.hash_bytes(data)}],
        },
        data,
    )
    assert xfer.r_paquete(raw)["archivos"]["publicado.bin"] == "ok"
    assert protected
    assert victim.read_bytes() == b"intacta"
    assert (canal["destino"] / "publicado.bin").read_bytes() == data


@pytest.mark.skipif(sys.platform != "win32", reason="nombres nativos Windows")
@pytest.mark.parametrize("kind", ["short", "unc-local"])
def test_destino_legitimo_con_nombre_nativo(canal, monkeypatch, kind):
    import ctypes
    from ctypes import wintypes

    folder = str(canal["destino"])
    if kind == "short":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        buffer = ctypes.create_unicode_buffer(32768)
        n = kernel.GetShortPathNameW(folder, buffer, len(buffer))
        if not n or n >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        folder = buffer.value
        if os.path.normcase(folder) == os.path.normcase(str(canal["destino"])):
            pytest.skip("el volumen no expone alias 8.3 para este Temp")
    else:
        drive, rest = os.path.splitdrive(folder)
        if len(drive) != 2:
            pytest.skip("Temp no está en una unidad local")
        folder = "\\\\localhost\\" + drive[0] + "$" + rest
        if not os.path.isdir(folder):
            pytest.skip("share local existente inaccesible; no se crea share ni se elevan permisos")
    monkeypatch.setattr(st, "load_config", lambda: {"copy_roots": [folder]})
    data = b"nombre legitimo"
    raw = xfer._armar(
        {
            "destino": folder,
            "bs": MIB,
            "archivos": [{"rel": "alias.txt", "size": len(data), "mtime_ns": 12300, "hash": xfer.hash_bytes(data)}],
        },
        data,
    )
    assert xfer.r_paquete(raw)["archivos"]["alias.txt"] == "ok"
    assert (canal["destino"] / "alias.txt").read_bytes() == data


def _regla_que_la_vacia(ruta: str, config: str) -> str | None:
    """La línea de tmpfiles.d que borra `ruta` en un `--remove --boot`, o None. `D` vacía el
    contenido de su directorio y `R` borra el directorio entero; los especificadores `%x` y los
    comodines se comparan como `*`."""
    for line in config.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].startswith("#") or parts[0][0] not in "DR":
            continue
        patron = re.sub(r"%.", "*", parts[1]).rstrip("/")
        if fnmatch.fnmatchcase(ruta, patron + "/*") or (parts[0][0] == "R" and fnmatch.fnmatchcase(ruta, patron)):
            return line
    return None


def test_regla_que_la_vacia_lee_tmpfiles():
    config = "# x\nD /tmp 1777 root root 30d\nR! /var/tmp/systemd-private-%b-*\nd /var/tmp 1777 root root 30d\n"
    assert _regla_que_la_vacia("/tmp/lienzo-E-xfer-x", config) == "D /tmp 1777 root root 30d"
    assert _regla_que_la_vacia("/var/tmp/systemd-private-abc-unidad", config).startswith("R!")
    assert _regla_que_la_vacia("/var/tmp/lienzo-E-xfer-x", config) is None
    assert _regla_que_la_vacia("/tmp", config) is None  # D no borra el directorio, sólo su contenido


@pytest.mark.skipif(sys.platform != "win32", reason="UNC WSL desde Windows")
def test_base_wsl_de_las_pruebas_sobrevive_al_arranque_de_la_distro():
    try:
        out = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--", "systemd-tmpfiles", "--cat-config"],
            capture_output=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"WSL Ubuntu no disponible: {type(exc).__name__}")
    if out.returncode != 0:
        pytest.skip(f"systemd-tmpfiles no disponible en Ubuntu (rc {out.returncode})")
    assert _regla_que_la_vacia(WSL_BASE_LINUX + "/lienzo-E-xfer-x", out.stdout.decode("utf-8", "replace")) is None


@pytest.mark.skipif(sys.platform != "win32", reason="UNC WSL desde Windows")
@pytest.mark.parametrize("leer_antes", [False, True], ids=["cierre-inmediato", "con-observacion"])
def test_wsl_unc_archivo_inocuo(canal, monkeypatch, leer_antes):
    base = WSL_BASE
    try:
        own = tempfile.TemporaryDirectory(prefix="lienzo-E-xfer-", dir=base)
    except OSError as exc:
        pytest.skip(
            f"WSL Ubuntu {WSL_BASE_LINUX} no disponible: {type(exc).__name__}, winerror={getattr(exc, 'winerror', None)}"
        )
    with own as folder:
        monkeypatch.setattr(st, "load_config", lambda: {"copy_roots": [folder]})
        # No se pide a WSL soltar caché de un archivo de pocos bytes ni se inicia un peer.
        monkeypatch.setattr(xfer, "soltar_cache", lambda path: None)
        data = b"WSL: prueba inocua de apertura y publicacion\n"
        hashes = [xfer.hash_bytes(data)]
        body = {"destino": folder, "bs": MIB, "rel": "inocuo.bin", "size": len(data)}
        assert xfer.r_bloque(xfer._armar({**body, "i": 0, "hash": hashes[0]}, data))["ok"]
        path = os.path.join(folder, "inocuo.bin")
        if leer_antes:
            with open(path + xfer.PARTE, "rb") as f:
                assert f.read() == data, "bytes de .parte después del bloque"
        code, response = xfer.r_cerrar({**body, "hashes": hashes, "mtime_ns": 123456789000})
        with open(path if code == 200 else path + xfer.PARTE, "rb") as f:
            actual = f.read()
        assert code == 200, (response, actual)
        assert xfer.hashes_de(path, MIB) == hashes
        with open(path, "rb") as f:
            assert f.read() == data
        os.rename(path, path + ".cerrado")  # descriptor propio liberado


@pytest.mark.parametrize("alterado", [False, True])
def test_cache_caliente_lee_una_sola_vez_y_actualiza_hashes(canal, monkeypatch, alterado):
    target = canal["destino"] / "lecturas.bin"
    target.write_bytes(b"original")
    assert xfer._hashes_final(str(target), MIB) == [xfer.hash_bytes(b"original")]
    db = xfer.CACHE._db
    before = target.stat()
    expected = b"alterado" if alterado else b"original"
    if alterado:
        target.write_bytes(expected)
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    calls = []
    original = xfer.hashes_de

    def count(path, bs):
        calls.append(path)
        return original(path, bs)

    monkeypatch.setattr(xfer, "hashes_de", count)
    assert xfer._hashes_final(str(target), MIB) == [xfer.hash_bytes(expected)]
    assert calls == [str(target)]
    assert xfer.CACHE._db is db
    row = db.execute("SELECT hashes FROM h WHERE ruta=?", (xfer._norm(str(target)),)).fetchone()
    assert json.loads(row[0]) == [xfer.hash_bytes(expected)]


def _registrar_error_wsl(func, errors):
    """Captura el traceback antes de que atender_peer reduzca OSError a un mensaje."""

    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except OSError as exc:
            errors.append(
                {
                    "tipo": type(exc).__name__,
                    "winerror": getattr(exc, "winerror", None),
                    "ntstatus": getattr(exc, "ntstatus", None),
                    "traceback": "".join(traceback.format_exception(exc)),
                }
            )
            raise

    return wrapped


@pytest.mark.skipif(sys.platform != "win32", reason="UNC WSL desde Windows")
def test_wsl_unc_diez_cierres_inmediatos(canal, monkeypatch, record_property, tmp_path):
    base = WSL_BASE
    try:
        own = tempfile.TemporaryDirectory(prefix="lienzo-E-xfer-diez-", dir=base)
    except OSError as exc:
        pytest.skip(
            f"WSL Ubuntu {WSL_BASE_LINUX} no disponible: {type(exc).__name__}, winerror={getattr(exc, 'winerror', None)}"
        )
    with own as folder:
        monkeypatch.setattr(st, "load_config", lambda: {"copy_roots": [folder]})
        monkeypatch.setattr(xfer, "soltar_cache", lambda path: None)
        errors = []
        monkeypatch.setattr(xfer, "r_bloque", _registrar_error_wsl(xfer.r_bloque, errors))
        monkeypatch.setattr(xfer, "r_cerrar", _registrar_error_wsl(xfer.r_cerrar, errors))
        results = []
        for i in range(10):
            data = f"WSL inocuo numero {i}: cierre inmediato\n".encode()
            hashes = [xfer.hash_bytes(data)]
            name = f"inocuo-{i}.bin"
            body = {"destino": folder, "bs": MIB, "rel": name, "size": len(data)}
            errors.clear()
            block_code, block_response = xfer.atender_peer(
                ["bloque"], xfer._armar({**body, "i": 0, "hash": hashes[0]}, data)
            )
            # Ninguna lectura ni sleep entre bloque y cierre.
            code, response = xfer.atender_peer(
                ["cerrar"], json.dumps({**body, "hashes": hashes, "mtime_ns": 123456789000}).encode()
            )
            path = os.path.join(folder, name)
            actual, read_error = b"", None
            try:
                with open(path if code == 200 else path + xfer.PARTE, "rb") as f:
                    actual = f.read()
            except OSError as exc:
                read_error = {"tipo": type(exc).__name__, "winerror": getattr(exc, "winerror", None)}
            results.append(
                {
                    "archivo": name,
                    "bloque_codigo": block_code,
                    "bloque_response": block_response,
                    "codigo": code,
                    "response": response,
                    "bytes_despues_hex": actual.hex(),
                    "bytes_esperados_hex": data.hex(),
                    "igual": actual == data,
                    "lectura_error": read_error,
                    "excepciones_antes_de_respuesta": list(errors),
                }
            )
            # Sólo después del cierre: no calienta el primer bloque ni cambia su oráculo.
            (tmp_path / "cierres-wsl.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        record_property("cierres_wsl", json.dumps(results))
        print("cierres_wsl=" + json.dumps(results))
        assert all(r["codigo"] == 200 and r["igual"] for r in results), results


def test_diagnostico_wsl_preserva_excepcion_y_respuesta(monkeypatch):
    errors = []
    error = FileNotFoundError(2, "fallo inocuo inyectado")
    error.winerror = 2
    error.ntstatus = 0xC0000034

    def causa_nativa_inyectada(raw):
        raise error

    wrapped = _registrar_error_wsl(causa_nativa_inyectada, errors)
    with pytest.raises(FileNotFoundError) as raised:
        wrapped(b"")
    assert raised.value is error
    monkeypatch.setattr(xfer, "r_bloque", wrapped)
    code, response = xfer.atender_peer(["bloque"], b"")
    assert code == 500 and response == {"error": f"FileNotFoundError: {error}"}
    assert len(errors) == 2
    assert all(e["winerror"] == 2 and e["ntstatus"] == 0xC0000034 for e in errors)
    assert all("causa_nativa_inyectada" in e["traceback"] for e in errors)


@pytest.mark.parametrize("action", ["estado", "bloque", "cerrar"])
def test_parcial_valido_no_se_descarta_por_exists_falso(canal, monkeypatch, action):
    data = b"A" * MIB + b"WSL inocuo numero 0: cierre inmediato\n"
    hashes = [xfer.hash_bytes(data[:MIB]), xfer.hash_bytes(data[MIB:])]
    folder = str(canal["destino"])
    path = os.path.join(folder, "contradiccion.bin")
    body = {"destino": folder, "bs": MIB, "rel": "contradiccion.bin", "size": len(data)}
    for i, block in enumerate((data[:MIB], data[MIB:])):
        xfer.r_bloque(xfer._armar({**body, "i": i, "hash": hashes[i]}, block))
    original_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: False if p == path + xfer.PARTE else original_exists(p))
    if action == "cerrar":
        code, response = xfer.r_cerrar({**body, "hashes": hashes, "mtime_ns": 123456789000})
        assert code == 200, response
        with open(path, "rb") as file:
            assert file.read() == data
    else:
        if action == "bloque":
            xfer.r_bloque(xfer._armar({**body, "i": 1, "hash": hashes[1]}, data[MIB:]))
        state = xfer.estado_archivo(path, MIB)
        assert state["parcial"] is True and state["bloques"] == {str(i): h for i, h in enumerate(hashes)}
        with open(path + xfer.PARTE, "rb") as file:
            assert file.read() == data


def test_diario_no_verificable_no_autoriza_borrar_parcial(canal, monkeypatch):
    path = os.path.join(canal["destino"], "diario.bin")
    data = b"parcial propio valido"
    body = {"destino": str(canal["destino"]), "bs": MIB, "rel": "diario.bin", "size": len(data)}
    xfer.r_bloque(xfer._armar({**body, "i": 0, "hash": xfer.hash_bytes(data)}, data))
    original = xfer._abrir_seguro

    @contextlib.contextmanager
    def inaccessible(candidate, mode, **kwargs):
        if candidate == path + xfer.DIARIO and mode == "r":
            raise PermissionError("fallo inocuo al validar diario")
        with original(candidate, mode, **kwargs) as file:
            yield file

    monkeypatch.setattr(xfer, "_abrir_seguro", inaccessible)
    with pytest.raises(PermissionError, match="fallo inocuo"):
        xfer.estado_archivo(path, MIB)
    with open(path + xfer.PARTE, "rb") as file:
        assert file.read() == data


def test_presencia_segura_distingue_ausencia_y_error_de_validacion(canal, monkeypatch):
    path = str(canal["destino"] / "presencia.bin")
    assert xfer._presente_seguro(path) is False
    _escribir(path, b"archivo propio")
    assert xfer._presente_seguro(path) is True

    def bad_fstat(fd):
        raise FileNotFoundError(2, "fallo inocuo después de abrir")

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fstat", bad_fstat)
        with pytest.raises(FileNotFoundError, match="después de abrir"):
            xfer._presente_seguro(path)
    os.rename(path, path + ".cerrado")  # no queda un handle que impida mover en Windows


@pytest.mark.parametrize("journal", [None, b"cabecera rota\n", b"bs 2\n", b"\xff"])
def test_diario_ausente_o_invalido_conserva_semantica_de_reinicio(canal, journal):
    path = str(canal["destino"] / "reinicio.bin")
    _escribir(path + xfer.PARTE, b"parcial sin diario utilizable")
    if journal is not None:
        _escribir(path + xfer.DIARIO, journal)
    xfer._asegurar_parte(path, MIB)
    with open(path + xfer.PARTE, "rb") as file:
        assert file.read() == b""
    assert xfer.leer_diario(path, MIB) == {}


@pytest.mark.skipif(sys.platform != "win32", reason="validación de handle Windows")
def test_win_presencia_no_confunde_winerror2_post_apertura_con_ausencia(canal, monkeypatch):
    import ctypes
    from ctypes import wintypes

    path = str(canal["destino"] / "info.bin")
    _escribir(path, b"archivo propio")
    win_dll = ctypes.WinDLL
    kernel = win_dll("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    closed = []

    class Call:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    def bad_info(*args):
        ctypes.set_last_error(2)
        return 0

    def close(handle):
        closed.append(handle)
        return kernel.CloseHandle(handle)

    class Kernel:
        GetFileInformationByHandle = Call(bad_info)
        CloseHandle = Call(close)

        def __getattr__(self, name):
            return getattr(kernel, name)

    proxy = Kernel()
    with monkeypatch.context() as patcher:
        patcher.setattr(
            ctypes, "WinDLL", lambda name, *a, **kw: proxy if name == "kernel32" else win_dll(name, *a, **kw)
        )
        with pytest.raises(FileNotFoundError) as raised:
            xfer._win_abrir(path, carpeta=False, ausente_ok=True)
        assert raised.value.winerror == 2
    assert len(closed) == 1
    os.rename(path, path + ".cerrado")


@pytest.mark.skipif(sys.platform != "win32", reason="NTSTATUS de publicación Windows")
def test_publicacion_preserva_ntstatus_sin_cambiar_rename(canal, monkeypatch):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    path = str(canal["destino"] / "status.bin")
    data = b"publicacion propia con error inyectado"
    _escribir(path + xfer.PARTE, data)
    win_dll = ctypes.WinDLL
    native = win_dll("ntdll")
    calls = []

    class RenameInfo(ctypes.Structure):
        _fields_ = [
            ("replace", wintypes.BOOLEAN),
            ("root", wintypes.HANDLE),
            ("length", wintypes.DWORD),
            ("name", wintypes.WCHAR * 1),
        ]

    class Call:
        def __call__(self, handle, io, buffer, size, information):
            info = RenameInfo.from_buffer(buffer)
            name = ctypes.string_at(ctypes.addressof(buffer) + RenameInfo.name.offset, info.length).decode("utf-16-le")
            calls.append((handle, info.root, info.replace, name, information))
            ctypes.cast(io, ctypes.POINTER(ctypes.c_long))[0] = ctypes.c_long(0xC0000034).value
            return ctypes.c_long(0xC0000034).value

    class Native:
        NtSetInformationFile = Call()

        def __getattr__(self, name):
            return getattr(native, name)

    proxy = Native()
    with xfer._abrir_seguro(path + xfer.PARTE, "r+b") as file:
        with monkeypatch.context() as patcher:
            patcher.setattr(
                ctypes, "WinDLL", lambda name, *a, **kw: proxy if name == "ntdll" else win_dll(name, *a, **kw)
            )
            with pytest.raises(FileNotFoundError) as raised:
                xfer._publicar_parte(path, file)
        assert raised.value.ntstatus == 0xC0000034
        assert raised.value.winerror == 2
        assert len(calls) == 1
        handle, root, replace, name, information = calls[0]
        assert handle == msvcrt.get_osfhandle(file.fileno())
        assert root and replace and name == "status.bin" and information == 10
        file.seek(0)
        assert file.read() == data
    assert not os.path.exists(path)


@pytest.mark.skipif(sys.platform != "win32", reason="enlaces POSIX expuestos por UNC WSL")
@pytest.mark.parametrize("extension", [xfer.PARTE, xfer.DIARIO])
@pytest.mark.parametrize("action", ["estado", "bloque", "cerrar"])
def test_wsl_auxiliar_symlink_no_altera_victima(canal, monkeypatch, extension, action):
    if not os.path.isdir(WSL_BASE):
        pytest.skip(f"WSL Ubuntu {WSL_BASE_LINUX} no disponible")
    created = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "mktemp", "-d", WSL_BASE_LINUX + "/lienzo-E-xfer-link-XXXXXXXX"],
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
    )
    linux = created.stdout.decode().strip()
    prefix = WSL_BASE_LINUX + "/"
    assert linux.startswith(prefix + "lienzo-E-xfer-link-") and "/" not in linux[len(prefix) :]
    folder = os.path.join(WSL_BASE, linux.removeprefix(prefix))
    try:
        allowed = os.path.join(folder, "permitida")
        subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--", "mkdir", linux + "/permitida"],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
        victim = os.path.join(folder, "victima.bin")
        content = b"bs 1048576\n" if extension == xfer.DIARIO else b"victima intacta"
        with open(victim, "wb") as f:
            f.write(content)
        target = os.path.join(allowed, "aux.bin")
        other = xfer.DIARIO if extension == xfer.PARTE else xfer.PARTE
        with open(target + other, "wb") as f:
            f.write(b"bs 1048576\n" if other == xfer.DIARIO else b"parte")
        subprocess.run(
            [
                "wsl.exe",
                "-d",
                "Ubuntu",
                "--",
                "ln",
                "-s",
                linux + "/victima.bin",
                linux + "/permitida/aux.bin" + extension,
            ],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
        monkeypatch.setattr(st, "load_config", lambda: {"copy_roots": [allowed]})
        body = {
            "destino": allowed,
            "bs": MIB,
            "rel": "aux.bin",
            "size": 1,
            "mtime_ns": 1,
            "hashes": [xfer.hash_bytes(b"x")],
            "archivos": ["aux.bin"],
        }
        raw = (
            xfer._armar({**body, "i": 0, "hash": xfer.hash_bytes(b"x")}, b"x")
            if action == "bloque"
            else json.dumps(body).encode()
        )
        code, response = xfer.atender_peer([action], raw)
        with open(victim, "rb") as f:
            assert f.read() == content
        assert code in (400, 403), response
    finally:
        # Ruta absoluta devuelta por mktemp, verificada arriba, sin permisos cambiados ni root.
        subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--", "rm", "-rf", "--", linux],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
