"""Copia entre PCs por el listener de peers (lienzo/xfer.py, encargo del 2026-10-04).

Las dos puntas corren en este proceso: el que manda es un `xfer.Trabajo` y el que recibe un
`server.PeerHandler` real en 127.0.0.1, con la firma de siempre (peers.json con la clave de una PC
"origen" inventada). Ademas de copiar y saltear lo igual, cubre lo que pide el encargo y falla sin el
canal: el receptor que muere a mitad y se retoma desde el diario, un bloque que llega corrupto y se
vuelve a pedir, un archivo que cambia en el origen mientras viaja, una ruta fuera de copy_roots y
una firma vieja."""

import contextlib
import hashlib
import http.client
import json
import os
import secrets
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import federation as fed
import state as st
import xfer

MIB = 1024 * 1024
PC_ORIGEN = "a1a1a1a1a1a1"


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
    # retomo: los bloques que ya estaban en el diario no viajaron de nuevo
    assert not (set(diario) & set(llegados))
    assert len(antes) + len(llegados) <= 24 + 2


def test_el_que_manda_se_reinicia_y_retoma_sin_releer_lo_hecho(canal):
    datos = _arbol(canal["origen"])
    t = _correr(canal, esperar=False, mbps=1, hilos=1)
    fin = time.time() + 20
    while t.archivos_hechos < 50 and time.time() < fin:
        time.sleep(0.02)
    xfer.pausar(t.id)
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
