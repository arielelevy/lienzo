"""Federacion entre PCs de la misma LAN (plan-multi-pc-2026-09-26.md). Ronda 1: el modulo entero,
sin enchufar a server.py todavia (eso es ronda 2). Piezas, en el orden en que las usaria la
ronda 2:

  1. Emparejamiento: `derive_pair_key` saca la clave compartida de un par de PCs a partir de una
     frase de seis palabras (reusa el estilo de auth.py: passphrase normalizada + scrypt), con
     sal derivada de los dos `pc_id` ordenados. Se guarda en peers.json junto con el peer.
  2. peers.json: `add_peer`, `remove_peer`, `list_peers`, `update_peer_ip`. Tope de `MAX_PEERS`.
  3. Firma de cada request entre peers: `sign` / `verify`, con ventana de tiempo y `NonceCache`
     contra replay.
  4. Beacon UDP: `encode_beacon` / `decode_beacon` (anonimo, para descubrir) y
     `encode_signed_beacon` / `decode_signed_beacon` (firmado con la clave del par, para no
     aceptar a cualquiera que grite en la LAN).
  5. `SSEClient`: cliente saliente contra `/peer/events` de un peer, con reconexion y backoff
     inyectable; llama a `on_reconnect` en cada conexion (incluida la primera) porque el plan
     pide pedir el snapshot completo al (re)conectar.
  6. `Transport` (Protocol) y `HTTPTransport`: lo minimo que la ronda 2 necesita para hablarle a
     un peer (`get`, `post`, `put`, `delete`, `subscribe`), todo firmado.

Lo que falta para enchufarlo (ronda 2):
  - Un listener `:7322` en server.py que reciba `/peer/*`, verifique la firma de cada request
    contra el peer que dice ser el emisor (por `pc_id` o por IP) y sirva `/peer/events` con el
    broadcast que ya existe en state.py.
  - Que `identity.py` (frente A de esta ronda) le pase `pc_id()` a `derive_pair_key` y que
    `peers.json` viva en `LIENZO_HOME`, no en un parametro suelto como en estos tests.
  - El emisor del beacon (un hilo que llama a `encode_signed_beacon` cada 10 s) y el listener que
    lo recibe y llama `update_peer_ip`: hoy solo estan las funciones de codificar/decodificar.
  - `install.py --peer`: la regla de firewall del 7322 en el perfil Privado.

Solo biblioteca estandar: hashlib, hmac, secrets, socket, http.client, json, threading.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# como hook.py con procinfo: importado como lienzo.federation (los tests) o suelto (el server)
try:
    from . import state
except ImportError:
    import state

MAX_PEERS = 4
SIGN_WINDOW_S = 30
NONCE_TTL_S = 90  # bastante mas que la ventana de firma: cubre el reloj corrido de los dos lados
BEACON_VERSION = 1

# los de auth.SCRYPT; copiados porque auth.py no se puede importar suelto (hace `import state`)
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class PeerLimitError(RuntimeError):
    """Se intento agregar un peer nuevo habiendo ya MAX_PEERS emparejados."""


# --- firma y replay -----------------------------------------------------------------------


def _mensaje_a_firmar(method: str, path: str, body: bytes, ts: float, nonce: str) -> bytes:
    """El body puede traer cualquier byte; los demas campos van como texto separados por NUL, que
    no aparece en un metodo, una ruta ni un nonce hex."""
    partes = [
        method.upper().encode("utf-8"),
        path.encode("utf-8"),
        repr(float(ts)).encode("ascii"),
        nonce.encode("utf-8"),
    ]
    return b"\x00".join(partes) + b"\x00" + bytes(body)


def sign(key: bytes, method: str, path: str, body: bytes, ts: float, nonce: str) -> str:
    """HMAC-SHA256 hex sobre metodo + ruta + cuerpo + timestamp + nonce."""
    return hmac.new(key, _mensaje_a_firmar(method, path, body, ts, nonce), hashlib.sha256).hexdigest()


def verify(
    key: bytes,
    method: str,
    path: str,
    body: bytes,
    ts: float,
    nonce: str,
    sig: str,
    nonces: NonceCache,
    *,
    window_s: float = SIGN_WINDOW_S,
    now: float | None = None,
) -> bool:
    """True si la firma es valida, el ts cae dentro de +-window_s y el nonce no se vio antes. La
    comparacion de la firma es en tiempo constante (hmac.compare_digest); el registro de nonces
    se consulta despues, asi que una firma invalida no gasta una entrada del cache."""
    ahora = time.time() if now is None else now
    if abs(ahora - float(ts)) > window_s:
        return False
    if not isinstance(sig, str) or not sig.isascii():
        return False  # compare_digest exige str ASCII (o bytes-like) de los dos lados; nunca TypeError
    esperada = sign(key, method, path, body, ts, nonce)
    if not hmac.compare_digest(esperada, sig):
        return False
    return nonces.add(nonce, now=ahora)


class NonceCache:
    """Registro de nonces ya vistos, para rechazar un replay dentro de la ventana de firma. Se
    purga solo en cada `add`, asi que queda acotado en memoria: nunca guarda mas que los nonces
    de los ultimos `ttl_s` segundos."""

    def __init__(self, ttl_s: float = NONCE_TTL_S):
        self.ttl_s = ttl_s
        self._vistos: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, nonce: str, now: float | None = None) -> bool:
        """True si el nonce era nuevo (y queda registrado); False si ya estaba (replay)."""
        ahora = time.time() if now is None else now
        with self._lock:
            self._purgar(ahora)
            if nonce in self._vistos:
                return False
            self._vistos[nonce] = ahora
            return True

    def _purgar(self, ahora: float) -> None:
        vencidos = [n for n, t in self._vistos.items() if ahora - t > self.ttl_s]
        for n in vencidos:
            del self._vistos[n]


# --- emparejamiento: KDF de la frase de seis palabras --------------------------------------


def _salt_del_par(pc_id_a: str, pc_id_b: str) -> bytes:
    """El orden de los dos pc_id no importa: se ordenan antes de derivar la sal, asi las dos
    puntas del par llegan a la misma clave sin ponerse de acuerdo en quien es 'a' y quien 'b'."""
    par = "|".join(sorted([pc_id_a, pc_id_b]))
    return hashlib.sha256(par.encode("utf-8")).digest()


def derive_pair_key(passphrase: str, pc_id_a: str, pc_id_b: str) -> bytes:
    """Clave compartida de un par de PCs: mismo par de pc_id (en cualquier orden) y misma frase de
    seis palabras dan la misma clave en las dos puntas. Cambiar la frase, o el par, cambia la
    clave. scrypt de stdlib con los mismos parametros que auth.py usa para la passphrase."""
    normalizada = " ".join(passphrase.lower().split())
    salt = _salt_del_par(pc_id_a, pc_id_b)
    return hashlib.scrypt(normalizada.encode("utf-8"), salt=salt, **SCRYPT_PARAMS)


# --- peers.json ------------------------------------------------------------------------------


def _atomic_write(path: str, obj) -> None:
    state.atomic_write(path, json.dumps(obj, indent=1, ensure_ascii=False))


# peers.json se lee en cada request firmado, en cada tick del beacon y en cada vuelta del espejo:
# se cachea por ruta, mtime y tamano, y cada escritura lo invalida sola al cambiar el mtime
_peers_cache: dict[str, tuple[tuple[int, int], dict]] = {}
_peers_cache_lock = threading.Lock()


def _cargar_peers(path: str) -> dict:
    """Un peers.json corrupto no rompe: se trata como si no hubiera peers, y la proxima escritura
    lo reemplaza por uno valido. Devuelve una copia: quien la recibe la puede modificar."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    firma = (st.st_mtime_ns, st.st_size)
    with _peers_cache_lock:
        hit = _peers_cache.get(path)
    if hit is None or hit[0] != firma:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError, ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        with _peers_cache_lock:
            _peers_cache[path] = (firma, data)
    else:
        data = hit[1]
    return {k: dict(v) if isinstance(v, dict) else v for k, v in data.items()}


def list_peers(path: str) -> list[dict]:
    return list(_cargar_peers(path).values())


def get_peer(path: str, pc_id: str) -> dict | None:
    return _cargar_peers(path).get(pc_id)


def add_peer(path: str, peer: dict) -> dict:
    """Alta o actualizacion de un peer por pc_id. Actualizar uno que ya esta no cuenta para el
    tope: solo un pc_id nuevo puede chocar con MAX_PEERS."""
    pc_id = peer["pc_id"]
    peers = _cargar_peers(path)
    if pc_id not in peers and len(peers) >= MAX_PEERS:
        raise PeerLimitError(f"ya hay {MAX_PEERS} peers emparejados")
    peers[pc_id] = peer
    _atomic_write(path, peers)
    return peer


def remove_peer(path: str, pc_id: str) -> bool:
    peers = _cargar_peers(path)
    if pc_id not in peers:
        return False
    del peers[pc_id]
    _atomic_write(path, peers)
    return True


def update_peer_ip(path: str, pc_id: str, ip: str) -> bool:
    """La actualiza el beacon UDP cuando el DHCP le cambio la IP a un peer ya emparejado."""
    peers = _cargar_peers(path)
    if pc_id not in peers:
        return False
    peers[pc_id]["ip"] = ip
    peers[pc_id]["last_seen"] = time.time()
    _atomic_write(path, peers)
    return True


# --- beacon UDP ------------------------------------------------------------------------------


def encode_beacon(pc_id: str, name: str, port: int, version: int = BEACON_VERSION) -> bytes:
    return json.dumps({"pc_id": pc_id, "name": name, "port": port, "version": version}, ensure_ascii=False).encode(
        "utf-8"
    )


def decode_beacon(data: bytes) -> dict | None:
    """None ante cualquier basura: un beacon corrupto o de otro protocolo no puede romper el
    listener UDP."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    if not isinstance(obj, dict) or "pc_id" not in obj or "port" not in obj:
        return None
    return obj


def _mensaje_de_beacon(payload: bytes, ts: float) -> bytes:
    return payload + b"\x00" + repr(float(ts)).encode("ascii")


def encode_signed_beacon(
    key: bytes, pc_id: str, name: str, port: int, version: int = BEACON_VERSION, *, ts: float | None = None
) -> bytes:
    """Anuncio con HMAC de la clave del par: sin esto, cualquiera que grite pc_id/nombre/puerto en
    la LAN se haria pasar por un peer ya emparejado. El ts va adentro de lo firmado: sin el, un
    beacon capturado se podia grabar y reenviar mas tarde desde otra IP para desviar
    `update_peer_ip` (el mismo motivo que la firma de request tiene ventana y nonce)."""
    ts = time.time() if ts is None else ts
    payload = encode_beacon(pc_id, name, port, version)
    firma = hmac.new(key, _mensaje_de_beacon(payload, ts), hashlib.sha256).hexdigest()
    return json.dumps({"payload": payload.decode("utf-8"), "ts": ts, "sig": firma}, ensure_ascii=False).encode("utf-8")


def decode_signed_beacon(
    key: bytes, data: bytes, *, window_s: float = SIGN_WINDOW_S, now: float | None = None
) -> dict | None:
    try:
        externo = json.loads(data.decode("utf-8"))
        payload = externo["payload"].encode("utf-8")
        ts = float(externo["ts"])
        sig = externo["sig"]
    except UnicodeDecodeError, ValueError, KeyError, AttributeError, TypeError:
        return None
    ahora = time.time() if now is None else now
    if abs(ahora - ts) > window_s:
        return None  # beacon vencido o reenviado: la firma ya no alcanza
    if not isinstance(sig, str) or not sig.isascii():
        return None
    esperada = hmac.new(key, _mensaje_de_beacon(payload, ts), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperada, sig):
        return None
    return decode_beacon(payload)


# --- cliente SSE con reconexion --------------------------------------------------------------


def _backoff_exponencial(intento: int) -> float:
    return min(0.5 * (2**intento), 10.0)


def _leer_eventos_sse(resp, stop_event: threading.Event):
    """Generador de eventos `data: ...` de un stream SSE. Termina cuando el server corta la
    conexion (readline devuelve vacio) o cuando stop_event se activa."""
    buffer_datos: list[str] = []
    while not stop_event.is_set():
        linea = resp.readline()
        if not linea:
            return
        linea = linea.decode("utf-8", errors="replace").rstrip("\r\n")
        if linea == "":
            if buffer_datos:
                cuerpo = "\n".join(buffer_datos)
                buffer_datos = []
                try:
                    yield json.loads(cuerpo)
                except ValueError:
                    yield cuerpo
            continue
        if linea.startswith("data:"):
            buffer_datos.append(linea[len("data:") :].lstrip(" "))


class SSEClient:
    """Cliente SSE saliente contra `/peer/events` de un peer. Reconecta con backoff cuando el
    server corta la conexion, y llama a `on_reconnect` cada vez que (re)conecta, porque el plan
    (3.3) pide el snapshot completo en cada conexion, no solo en la primera. `backoff` es
    inyectable para que los tests no esperen tiempo real."""

    def __init__(
        self,
        host: str,
        port: int,
        path: str,
        *,
        headers_fn: Callable[[], dict],
        on_event: Callable[[dict], None],
        on_reconnect: Callable[[], None] | None = None,
        backoff: Callable[[int], float] | None = None,
        connect_timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.path = path
        self.headers_fn = headers_fn
        self.on_event = on_event
        self.on_reconnect = on_reconnect
        self.backoff = backoff or _backoff_exponencial
        self.connect_timeout = connect_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        intento = 0
        while not self._stop.is_set():
            conecto = self._conectar_y_leer()
            if self._stop.is_set():
                return
            intento = 0 if conecto else intento + 1
            time.sleep(self.backoff(intento))

    def _conectar_y_leer(self) -> bool:
        """True si llego a conectar (aunque el server haya cortado enseguida): con eso alcanza
        para resetear el backoff, la idea es no escalar la espera cuando el peer esta vivo pero
        el stream se corta seguido."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout)
        try:
            conn.request("GET", self.path, headers=self.headers_fn())
            resp = conn.getresponse()
            if resp.status != 200:
                return False
            if self.on_reconnect is not None:
                self.on_reconnect()
            for evento in _leer_eventos_sse(resp, self._stop):
                self.on_event(evento)
            return True
        except OSError:
            return False
        finally:
            conn.close()


# --- transporte --------------------------------------------------------------------------


@dataclass(frozen=True)
class PeerConn:
    """Lo minimo para hablarle a un peer: donde esta, con que clave firmarle, y con que pc_id
    identificarse (header `X-Lienzo-Peer`: el que recibe lo necesita para saber contra que clave
    verificar la firma). `self_pc_id` es opcional (default vacio) para no romper una construccion
    vieja que no lo pasaba; una llamada real siempre lo completa."""

    host: str
    port: int
    key: bytes
    self_pc_id: str = ""


class Transport(Protocol):
    """Lo que la ronda 2 necesita del transporte hacia un peer: pedir, escribir y suscribirse a
    sus eventos. Una implementacion de broker (Redis, Azure Web PubSub) cumpliria el mismo
    Protocol sin tocar el resto del codigo."""

    def get(self, peer: PeerConn, path: str) -> dict: ...

    def post(self, peer: PeerConn, path: str, body: dict) -> dict: ...

    def put(self, peer: PeerConn, path: str, body: dict) -> dict: ...

    def delete(self, peer: PeerConn, path: str) -> dict: ...

    def subscribe(
        self,
        peer: PeerConn,
        path: str,
        on_event: Callable[[dict], None],
        on_reconnect: Callable[[], None] | None = None,
    ) -> SSEClient: ...


def signed_headers(peer: PeerConn, method: str, path: str, body: bytes) -> dict:
    """Los cuatro headers X-Lienzo-* de un request firmado, con ts y nonce nuevos."""
    ts = time.time()
    nonce = secrets.token_hex(16)
    return {
        "X-Lienzo-Peer": peer.self_pc_id,
        "X-Lienzo-Ts": repr(ts),
        "X-Lienzo-Nonce": nonce,
        "X-Lienzo-Sig": sign(peer.key, method, path, body, ts, nonce),
    }


class HTTPTransport:
    """Implementacion HTTP del Transport: cada request va firmada con timestamp y nonce nuevos
    (tambien las de `subscribe`, en cada intento de conexion)."""

    def __init__(self, *, timeout: float = 5.0):
        self.timeout = timeout

    def _headers_firmados(self, peer: PeerConn, method: str, path: str, body: bytes) -> dict:
        return {**signed_headers(peer, method, path, body), "Content-Type": "application/json"}

    def _pedir(self, peer: PeerConn, method: str, path: str, body: bytes = b"") -> tuple[int, dict]:
        """(status, cuerpo). Los metodos publicos de siempre (get/post/put/delete) devuelven solo
        el cuerpo, como antes; `request` (para el enrutado de comandos, ronda 2) devuelve las dos
        cosas, porque ahi hace falta reenviar el codigo tal cual lo dio el peer."""
        headers = self._headers_firmados(peer, method, path, body)
        conn = http.client.HTTPConnection(peer.host, peer.port, timeout=self.timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            status = resp.status
        finally:
            conn.close()
        return status, (json.loads(data.decode("utf-8")) if data else {})

    def get(self, peer: PeerConn, path: str) -> dict:
        return self._pedir(peer, "GET", path)[1]

    def post(self, peer: PeerConn, path: str, body: dict) -> dict:
        return self._pedir(peer, "POST", path, json.dumps(body).encode("utf-8"))[1]

    def put(self, peer: PeerConn, path: str, body: dict) -> dict:
        return self._pedir(peer, "PUT", path, json.dumps(body).encode("utf-8"))[1]

    def delete(self, peer: PeerConn, path: str) -> dict:
        return self._pedir(peer, "DELETE", path)[1]

    def request(self, peer: PeerConn, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        """Para el enrutado de comandos (plan §3.4): devuelve (status, cuerpo) tal como los dio el
        peer, para que el server local se los pase al front sin tocarlos."""
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        return self._pedir(peer, method.upper(), path, raw)

    def subscribe(
        self,
        peer: PeerConn,
        path: str,
        on_event: Callable[[dict], None],
        on_reconnect: Callable[[], None] | None = None,
        backoff: Callable[[int], float] | None = None,
    ) -> SSEClient:
        cliente = SSEClient(
            peer.host,
            peer.port,
            path,
            # headers nuevos en cada intento de conexion: ts y nonce no se pueden reusar
            headers_fn=lambda: signed_headers(peer, "GET", path, b""),
            on_event=on_event,
            on_reconnect=on_reconnect,
            backoff=backoff,
        )
        cliente.start()
        return cliente
