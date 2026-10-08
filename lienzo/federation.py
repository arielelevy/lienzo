"""Federacion entre PCs de la misma LAN (plan-multi-pc-2026-09-26.md): las piezas de bajo nivel
que comparten server.py (el listener de peers, PeerHandler en :7322), pairing.py,
beacon.py y mirror.py.

  1. `derive_pair_key`: scrypt de la frase de emparejamiento (normalizada, como la passphrase de
     auth.py) con sal derivada de los dos `pc_id` ordenados. NO es la clave del par: pairing.py la
     usa solo para sacar el escalar con el que SPAKE2 ciega los publicos; la clave del par sale del
     Diffie-Hellman de SPAKE2 (ver pairing.py). La frase es de una palabra (pairing.PHRASE_WORDS).
  2. peers.json (en LIENZO_HOME, la ruta la pasa quien llama): `add_peer`, `remove_peer`,
     `list_peers`, `get_peer`, `update_peer_ip`, con tope `MAX_PEERS`; uno corrupto se aparta con
     aviso (`apartar_corrupto`).
  3. Firma de cada request entre peers: `sign` / `verify` / `verify_motivo`, con ventana de tiempo
     y `NonceCache` contra replay; `causa_401` explica un rechazo (reloj corrido, clave distinta).
  4. Beacon UDP: `encode_beacon` / `decode_beacon` (anonimo, para descubrir PCs en la LAN) y
     `encode_signed_beacon` / `decode_signed_beacon_ts` (firmado con la clave del par, para no
     aceptar una IP nueva de cualquiera que grite en la LAN). El hilo que los manda y recibe es
     beacon.py.
  5. `SSEClient`: cliente saliente contra `/peer/events` de un peer, con reconexion y backoff
     inyectable; llama a `on_reconnect` en cada conexion (incluida la primera) para pedir el
     snapshot completo al (re)conectar. Lo usa el espejo (mirror.py).
  6. `Transport` (Protocol) y `HTTPTransport`: como se le habla a un peer (`get`, `post`, `put`,
     `delete`, `subscribe`), todo firmado, con plazos mas largos para las acciones lentas.

Solo biblioteca estandar: hashlib, hmac, secrets, http.client, json, threading.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import threading
import time
import traceback
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


class PeerError(OSError):
    """El peer contesto algo que no se puede usar: HTTP cortado a mitad (`IncompleteRead`, linea de
    estado rota) o un cuerpo que no es JSON. Es OSError a proposito: todos los que le hablan a un
    peer (mirror.forward, la salud) ya tratan OSError como «sin conexion con esa PC»; antes estos
    dos casos salian como HTTPException/ValueError, que nadie atrapaba, y mataban el hilo de salud
    o devolvian un 500 (revision 2026-10-04, B3)."""


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
    se consulta despues, asi que una firma invalida no gasta una entrada del cache. El motivo de
    un rechazo lo da `verify_motivo`."""
    return verify_motivo(key, method, path, body, ts, nonce, sig, nonces, window_s=window_s, now=now)[0]


def verify_motivo(
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
) -> tuple[bool, str]:
    """Lo mismo que `verify`, con el motivo del rechazo ("" si pasa): un 401 que en el log dice
    solo «firma invalida» no distingue reloj corrido, replay o clave distinta, que se arreglan
    distinto (revision 2026-10-04, S2). El motivo no lleva nada secreto: ni la firma esperada ni
    la clave, solo la diferencia de reloj."""
    ahora = time.time() if now is None else now
    dif = float(ts) - ahora
    if abs(dif) > window_s:
        return False, f"fuera de la ventana de tiempo: su reloj difiere {dif:+.0f} s (ventana {window_s:.0f} s)"
    if not isinstance(sig, str) or not sig.isascii():
        # compare_digest exige str ASCII (o bytes-like) de los dos lados; nunca TypeError
        return False, "firma con formato invalido"
    esperada = sign(key, method, path, body, ts, nonce)
    if not hmac.compare_digest(esperada, sig):
        return False, "firma invalida: clave distinta o pedido alterado"
    if not nonces.add(nonce, now=ahora):
        return False, "nonce repetido (replay o reintento del mismo pedido)"
    return True, ""


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


# --- emparejamiento: KDF de la frase (el escalar de SPAKE2 sale de aca, ver pairing.py) --------


def _salt_del_par(pc_id_a: str, pc_id_b: str) -> bytes:
    """El orden de los dos pc_id no importa: se ordenan antes de derivar la sal, asi las dos
    puntas del par llegan a la misma clave sin ponerse de acuerdo en quien es 'a' y quien 'b'."""
    par = "|".join(sorted([pc_id_a, pc_id_b]))
    return hashlib.sha256(par.encode("utf-8")).digest()


def derive_pair_key(passphrase: str, pc_id_a: str, pc_id_b: str) -> bytes:
    """La clave de la FRASE de un par de PCs: mismo par de pc_id (en cualquier orden) y misma frase
    dan lo mismo en las dos puntas; cambiar la frase, o el par, la cambia. scrypt de stdlib con los
    mismos parametros que auth.py usa para la passphrase. No es la clave del par (antes si, y con
    una frase de una palabra se sacaba offline de cualquier mensaje firmado): pairing.py la usa
    solo para el escalar con el que SPAKE2 ciega los publicos."""
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


def apartar_corrupto(path: str, motivo: str) -> None:
    """Un JSON que no se puede leer se renombra a `<archivo>.corrupto-<ts>` y se avisa al log, en
    vez de tratarlo como vacio y pisarlo en la proxima escritura: antes un peers.json roto borraba
    los emparejamientos sin rastro (revision 2026-10-04, B15). La misma idea que identity.py usa
    con peer.json; si state.py llega a tener un helper comun, los dos pasan a usarlo."""
    destino = f"{path}.corrupto-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, destino)
    except OSError as e:
        state.log(f"{os.path.basename(path)} corrupto ({motivo}) y no lo pude apartar ({e}): se va a reescribir")
        return
    state.log(f"{os.path.basename(path)} corrupto ({motivo}): lo aparte en {destino} y sigo como si no existiera")


def _cargar_peers(path: str, *, para_escribir: bool = False) -> dict:
    """Un peers.json que no existe es «sin peers». Uno corrupto (JSON roto o que no es un objeto)
    no rompe: se aparta con `apartar_corrupto` y se sigue sin peers. Uno que existe y no se puede
    leer (antivirus, permisos) se avisa y NO se aparta: el archivo puede estar bien; por eso, con
    `para_escribir` (alta, baja, IP), ese error sube en vez de devolver {}: escribir encima de un
    archivo que no se pudo leer borraria los peers. Devuelve una copia: quien la recibe la puede
    modificar."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {}
    except OSError as e:
        state.log(f"peers.json: no lo puedo ver ({type(e).__name__}: {e})")
        if para_escribir:
            raise
        return {}
    firma = (st.st_mtime_ns, st.st_size)
    with _peers_cache_lock:
        hit = _peers_cache.get(path)
    if hit is None or hit[0] != firma:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except OSError as e:
            state.log(f"peers.json: no lo puedo leer ({type(e).__name__}: {e})")
            if para_escribir:
                raise
            return {}
        except ValueError as e:  # incluye UnicodeDecodeError
            apartar_corrupto(path, f"JSON invalido: {e}")
            return {}
        if not isinstance(data, dict):
            apartar_corrupto(path, f"no es un objeto sino {type(data).__name__}")
            return {}
        with _peers_cache_lock:
            _peers_cache[path] = (firma, data)
    else:
        data = hit[1]
    return {k: dict(v) if isinstance(v, dict) else v for k, v in data.items()}


def list_peers(path: str) -> list[dict]:
    return list(_cargar_peers(path).values())


def get_peer(path: str, pc_id: str) -> dict | None:
    return _cargar_peers(path).get(pc_id)


# leer-modificar-escribir de peers.json bajo un solo lock: el alta de un emparejamiento (server) y
# el beacon (update_peer_ip, cada 10 s) corren en hilos distintos, y sin lock el que escribia
# segundo pisaba lo del primero con su copia vieja (revision 2026-10-04, B8). Un RLock de modulo
# alcanza: hay un solo proceso escribiendo peers.json.
_peers_write_lock = threading.RLock()


def _guardar_peers(path: str, peers: dict) -> None:
    _atomic_write(path, peers)
    with _peers_cache_lock:
        _peers_cache.pop(path, None)  # no fiarse del mtime: dos escrituras seguidas pueden empatar


def add_peer(path: str, peer: dict) -> dict:
    """Alta o actualizacion de un peer por pc_id. Actualizar uno que ya esta no cuenta para el
    tope: solo un pc_id nuevo puede chocar con MAX_PEERS."""
    pc_id = peer["pc_id"]
    with _peers_write_lock:
        peers = _cargar_peers(path, para_escribir=True)
        if pc_id not in peers and len(peers) >= MAX_PEERS:
            raise PeerLimitError(f"ya hay {MAX_PEERS} peers emparejados")
        peers[pc_id] = peer
        _guardar_peers(path, peers)
    return peer


def remove_peer(path: str, pc_id: str) -> bool:
    with _peers_write_lock:
        peers = _cargar_peers(path, para_escribir=True)
        if pc_id not in peers:
            return False
        del peers[pc_id]
        _guardar_peers(path, peers)
    return True


def update_peer_ip(path: str, pc_id: str, ip: str) -> bool:
    """La actualiza el beacon UDP cuando el DHCP le cambio la IP a un peer ya emparejado. True si
    el peer esta emparejado (cambie o no la IP). Solo escribe si la IP cambio: antes reescribia
    peers.json cada 10 s por peer solo para anotar `last_seen`, que nadie lee de ahi (el «visto
    hace» sale de beacon.seen() y del espejo, en memoria)."""
    with _peers_write_lock:
        peers = _cargar_peers(path, para_escribir=True)
        if pc_id not in peers:
            return False
        if peers[pc_id].get("ip") == ip:
            return True
        peers[pc_id]["ip"] = ip
        peers[pc_id]["last_seen"] = time.time()
        _guardar_peers(path, peers)
    return True


MAX_PEER_IPS = 4


def note_peer_address(path: str, pc_id: str, ip: str) -> bool:
    """Suma `ip` a las direcciones conocidas del peer (`ips`: la de la LAN, la de Tailscale) sin
    tocar `ip`, que es la que usa el espejo y la elige server.py entre las que el beacon ve vivas
    (antes una sola `ip` que cada beacon pisaba: con la LAN y Tailscale a la vez, el espejo saltaba
    de una a otra). Solo escribe si la direccion es nueva; se guardan las ultimas MAX_PEER_IPS.
    True si el peer esta emparejado."""
    with _peers_write_lock:
        peers = _cargar_peers(path, para_escribir=True)
        if pc_id not in peers:
            return False
        ips = [x for x in peers[pc_id].get("ips") or [] if isinstance(x, str)]
        if ip in ips:
            return True
        peers[pc_id]["ips"] = [*ips, ip][-MAX_PEER_IPS:]
        if not peers[pc_id].get("ip"):
            peers[pc_id]["ip"] = ip  # la que ofrecio la frase guarda ip "": que haya una para arrancar
        _guardar_peers(path, peers)
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
    r = decode_signed_beacon_ts(key, data, window_s=window_s, now=now)
    return r[0] if r else None


def decode_signed_beacon_ts(
    key: bytes, data: bytes, *, window_s: float = SIGN_WINDOW_S, now: float | None = None
) -> tuple[dict, float] | None:
    """Como `decode_signed_beacon`, con el ts firmado: el que recibe lo usa para aceptar de cada
    peer solo un ts estrictamente mayor al ultimo (beacon.py). La ventana sola deja reenviar un
    beacon capturado desde otra IP durante 30 s (revision 2026-10-04, B9). Mismo formato en el
    cable: el ts ya viajaba firmado."""
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
    anuncio = decode_beacon(payload)
    return (anuncio, ts) if anuncio is not None else None


# --- cliente SSE con reconexion --------------------------------------------------------------


SSE_PING_S = 15.0  # cada cuanto manda un ping el /events del server (server.py)
SSE_READ_TIMEOUT_S = 35.0  # mas que dos pings: uno perdido no corta el stream


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
        log: Callable[[str], None] | None = None,
    ):
        self.host = host
        self.port = port
        self.path = path
        self.headers_fn = headers_fn
        self.on_event = on_event
        self.on_reconnect = on_reconnect
        self.backoff = backoff or _backoff_exponencial
        self.connect_timeout = connect_timeout
        self.log = log or state.log
        self._estado: str | None = None  # el ultimo motivo avisado (ver _avisar)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: http.client.HTTPConnection | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def reconnect(self) -> None:
        """Corta el stream actual: `_run` reconecta y el server manda el snapshot entero."""
        conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def _avisar(self, estado: str) -> bool:
        """Al log solo cuando cambia el motivo (la idea de health.FuenteTemperatura._avisar): un
        peer apagado no puede llenar el log con un rechazo cada pocos segundos, pero tampoco se
        puede callar. Conectar bien de entrada no es noticia; volver a conectar despues de un
        error, si."""
        if estado == self._estado:
            return False
        primera = self._estado is None
        self._estado = estado
        if primera and estado == "conectado":
            return False
        self.log(f"SSE de {self.host}:{self.port}: {estado}")
        return True

    def _run(self) -> None:
        """Nunca deja morir el hilo: un evento que hace fallar a `on_event`, una respuesta HTTP
        rota o cualquier otra excepcion se loguea y se reconecta (el server manda el snapshot
        entero de nuevo). Antes solo se atrapaba OSError y el espejo de esa PC quedaba congelado
        con la ultima foto, viendose vivo por la salud (revision 2026-10-04, B3)."""
        intento = 0
        while not self._stop.is_set():
            try:
                conecto = self._conectar_y_leer()
            except Exception as e:
                if self._avisar(f"falla ({type(e).__name__}: {e}); reconecto"):
                    self.log(traceback.format_exc())  # el traceback, solo la primera vez
                conecto = False
            if self._stop.is_set():
                return
            intento = 0 if conecto else intento + 1
            time.sleep(self.backoff(intento))

    def _conectar_y_leer(self) -> bool:
        """True si llego a conectar (aunque el server haya cortado enseguida): con eso alcanza
        para resetear el backoff, la idea es no escalar la espera cuando el peer esta vivo pero
        el stream se corta seguido. Las excepciones que no son de red las atrapa `_run`."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout)
        self._conn = conn
        conectado = False
        try:
            conn.request("GET", self.path, headers=self.headers_fn())
            sock = conn.sock  # despues de getresponse puede quedar en None (Connection: close)
            resp = conn.getresponse()
            if resp.status != 200:
                self._avisar(f"responde {resp.status}")
                return False
            conectado = True
            # el timeout de conexion (5 s) quedaba como timeout de LECTURA y el server manda un
            # ping cada 15 s: el stream se cortaba solo cada pocos segundos, se perdian eventos y
            # se reenviaba el snapshot entero (revision 2026-10-04, B2). Conectado, se espera mas
            # que dos pings antes de darlo por muerto.
            if sock is not None:
                sock.settimeout(SSE_READ_TIMEOUT_S)
            self._avisar("conectado")
            if self.on_reconnect is not None:
                self.on_reconnect()
            for evento in _leer_eventos_sse(resp, self._stop):
                self.on_event(evento)
            return True
        except OSError as e:
            self._avisar(f"{type(e).__name__}: {e}")
            return conectado  # conecto y se corto despues: no es un fallo para el backoff
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
    """Lo que el server y el espejo necesitan del transporte hacia un peer: pedir, escribir y suscribirse a
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
    path = path.split("?", 1)[0]  # el receptor verifica sobre la ruta sin query (_dispatch)
    return {
        "X-Lienzo-Peer": peer.self_pc_id,
        "X-Lienzo-Ts": repr(ts),
        "X-Lienzo-Nonce": nonce,
        "X-Lienzo-Sig": sign(peer.key, method, path, body, ts, nonce),
    }


_reloj_cache: dict[str, tuple[float, str]] = {}
RELOJ_CACHE_S = 30.0


def causa_401(peer: PeerConn) -> str:
    """Por que la otra PC no acepta mi firma, en una frase y con el dato que se pueda medir: la
    diferencia de reloj contra el `Date` de /peer/hello (sin firma). La ventana de firma es de
    SIGN_WINDOW_S: pasada, toda firma da 401 aunque la clave sea la correcta. Cacheado unos
    segundos por peer: un tablero entero de 401 no tiene que disparar un pedido por cada uno."""
    clave = f"{peer.host}:{peer.port}"
    hit = _reloj_cache.get(clave)
    if hit and time.time() - hit[0] < RELOJ_CACHE_S:
        return hit[1]
    try:
        import email.utils

        t0 = time.time()
        conn = http.client.HTTPConnection(peer.host, peer.port, timeout=2)
        try:
            conn.request("GET", "/peer/hello")
            fecha = conn.getresponse().getheader("Date")
        finally:
            conn.close()
        remoto = email.utils.parsedate_to_datetime(fecha).timestamp() if fecha else None
        if remoto is None:
            causa = "no pude medir su reloj"
        else:
            dif = remoto - (t0 + time.time()) / 2
            causa = (
                f"su reloj difiere {dif:+.0f} s del mio y la ventana es de {SIGN_WINDOW_S:.0f} s: sincroniza la hora"
                if abs(dif) > SIGN_WINDOW_S
                else f"los relojes coinciden ({dif:+.1f} s): clave distinta o su lienzo en mal estado"
            )
    except OSError, ValueError:
        causa = "no pude consultar su reloj"
    _reloj_cache[clave] = (time.time(), causa)
    return causa


# /secrets: guardar una credencial de git corre `git credential approve` en la PC duena; con el
# timeout normal (5 s) el click del violeta decia «sin conexion» aunque se hubiera guardado (2026-10-04)
SLOW_ACTIONS = ("/send", "/launch", "/attach", "/secrets")
SLOW_TIMEOUT_S = 70.0  # un send tipea en la consola con un subproceso de hasta 60 s en la PC dueña
# /restaurar con `all` relanza N sesiones con 2 s de pausa entre cada una: necesita mucho mas
RESTORE_ACTION = "/restaurar"
RESTORE_TIMEOUT_S = 300.0


def _timeout_para(method: str, path: str, normal: float) -> float:
    """Escribir en una consola o lanzar una sesion tarda mas que pedir un dato: con el timeout
    normal (5 s) un envio lento aparecia como "sin conexion" aunque se hubiera tecleado."""
    if method.upper() == "GET":
        return normal
    if path.endswith(RESTORE_ACTION):
        return RESTORE_TIMEOUT_S
    return SLOW_TIMEOUT_S if path.endswith(SLOW_ACTIONS) else normal


class HTTPTransport:
    """Implementacion HTTP del Transport: cada request va firmada con timestamp y nonce nuevos
    (tambien las de `subscribe`, en cada intento de conexion)."""

    def __init__(self, *, timeout: float = 5.0):
        self.timeout = timeout
        self._pool_lock = threading.Lock()
        self._closed = False
        self._idle: list[tuple[float, tuple, http.client.HTTPConnection]] = []

    def _connection(self, peer: PeerConn, timeout: float) -> http.client.HTTPConnection:
        key = (peer.host, peer.port, peer.self_pc_id, peer.key)
        found = None
        with self._pool_lock:
            valid = []
            for stamp, previous, conn in self._idle:
                if time.monotonic() - stamp >= 20:
                    conn.close()
                elif previous == key and found is None:
                    found = conn
                else:
                    valid.append((stamp, previous, conn))
            self._idle = valid
        if found is None:
            return http.client.HTTPConnection(peer.host, peer.port, timeout=timeout)
        found.timeout = timeout
        if found.sock is not None:
            found.sock.settimeout(timeout)
        return found

    def _release(self, peer: PeerConn, conn, reusable: bool) -> None:
        with self._pool_lock:
            if reusable and not self._closed and len(self._idle) < MAX_PEERS * 2:
                self._idle.append((time.monotonic(), (peer.host, peer.port, peer.self_pc_id, peer.key), conn))
                return
        conn.close()

    def close(self) -> None:
        with self._pool_lock:
            self._closed = True
            for _, _, conn in self._idle:
                conn.close()
            self._idle.clear()

    def _headers_firmados(self, peer: PeerConn, method: str, path: str, body: bytes) -> dict:
        return {**signed_headers(peer, method, path, body), "Content-Type": "application/json"}

    def _pedir(
        self, peer: PeerConn, method: str, path: str, body: bytes = b"", timeout: float | None = None
    ) -> tuple[int, dict]:
        """(status, cuerpo). Los metodos publicos de siempre (get/post/put/delete) devuelven solo
        el cuerpo, como antes; `request` (reenviar una accion a la PC duena, /peer/health) devuelve las dos
        cosas, porque ahi hace falta reenviar el codigo tal cual lo dio el peer."""
        headers = self._headers_firmados(peer, method, path, body)
        conn = self._connection(peer, timeout or self.timeout)
        reusable = False
        try:
            if conn.sock is None:
                conn.connect()
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            status = resp.status
            reusable = not getattr(resp, "will_close", True) and status != 401
        except http.client.HTTPException as e:
            # RemoteDisconnected ya es OSError; IncompleteRead y BadStatusLine no lo son
            raise PeerError(f"{method} {path}: respuesta HTTP rota ({type(e).__name__}: {e})") from e
        finally:
            self._release(peer, conn, reusable)
        try:
            cuerpo = json.loads(data.decode("utf-8")) if data else {}
        except ValueError as e:  # incluye UnicodeDecodeError
            raise PeerError(f"{method} {path}: {status} con un cuerpo que no es JSON ({e})") from e
        if status == 401 and isinstance(cuerpo, dict):
            # sin esto el tablero queda mudo: «firma invalida» no dice que hacer (medido el 2026-10-03)
            cuerpo = {
                **cuerpo,
                "error": f"{cuerpo.get('error', '401')}: la otra PC no acepta mi firma ({causa_401(peer)}). "
                "Reinicia su lienzo (lienzo-server.cmd); si sigue igual, reempareja las PCs.",
            }
        return status, cuerpo

    def get(self, peer: PeerConn, path: str) -> dict:
        return self._pedir(peer, "GET", path)[1]

    def post(self, peer: PeerConn, path: str, body: dict) -> dict:
        return self._pedir(peer, "POST", path, json.dumps(body).encode("utf-8"))[1]

    def put(self, peer: PeerConn, path: str, body: dict) -> dict:
        return self._pedir(peer, "PUT", path, json.dumps(body).encode("utf-8"))[1]

    def delete(self, peer: PeerConn, path: str) -> dict:
        return self._pedir(peer, "DELETE", path)[1]

    def request(
        self, peer: PeerConn, method: str, path: str, body: dict | None = None, *, timeout: float | None = None
    ) -> tuple[int, dict]:
        """Para el enrutado de comandos (plan §3.4): devuelve (status, cuerpo) tal como los dio el
        peer, para que el server local se los pase al front sin tocarlos."""
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        return self._pedir(
            peer,
            method.upper(),
            path,
            raw,
            timeout=timeout if timeout is not None else _timeout_para(method, path, self.timeout),
        )

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
