"""Emparejamiento entre dos PCs (plan-multi-pc-2026-09-26.md §3.1; plan-refactor-2026-10-04.md 0.4).
Una PC ofrece una frase corta (PHRASE_WORDS palabras del generador EFF de auth.new_passphrase); la
otra la pega. La clave del par NO sale de la frase: sale de un Diffie-Hellman efimero que la frase
autentica (SPAKE2 sobre el grupo MODP de 2048 bits del RFC 3526), asi que capturar el trafico no
sirve para nada.

Por que (0.4, verificado): antes la clave era derive_pair_key(frase, pc_id_a, pc_id_b), con una
frase de UNA palabra (~13 bits) y los dos pc_id publicos. Con cualquier mensaje firmado capturado
(el POST de emparejamiento, o un beacon firmado que cada PC grita a la LAN cada 10 s) se probaban
las 7776 palabras offline en ~6 minutos y salia la clave que firma todo /peer/* y cifra los
secretos. Ahora la clave depende de dos exponentes secretos de 256 bits que nunca viajan.

Por que SPAKE2 y no "DH en claro + proof con la clave de la frase": en un DH comun autenticado por
un HMAC derivado de la frase, quien se hace pasar por la otra punta conoce su propio exponente,
asi que el proof que recibe le alcanza para probar las 7776 palabras OFFLINE (diccionario sobre el
proof). En SPAKE2 cada publico va cegado con la frase (X = g^x * M^w, Y = g^y * N^w): probar una
palabra exige haber elegido el publico con esa palabra antes de mandarlo, asi que un atacante activo
tiene UN intento por intercambio y uno pasivo no aprende nada. Como un intento fallido consume la
oferta (y cuenta para el freno MAX_FAILS/BLOCK_S), queda un intento por frase mostrada.

El intercambio viaja por la misma ruta de siempre (POST /peer/pair, cuyo cuerpo server.py le pasa
entero a accept() y cuya respuesta devuelve entera), en dos idas y vueltas:

  1. join -> {step: "start", pc_id, name, color, port, spake: X}
     accept <- {pc_info, port, step: "start", spake: Y, hs}
  2. join -> {step: "confirm", pc_id, name, color, port, hs, proof: confirmacion del que pega}
     accept <- {pc_info, port, proof: confirmacion del que ofrecio}

  offer()  -> lado que muestra la frase: la deja pendiente en memoria, una sola a la vez.
  accept() -> el mismo lado que ofrecio, para cada uno de los dos pasos de /peer/pair.
  join()   -> el lado que pega la frase: no conoce el pc_id de la otra PC de antemano, lo resuelve
              con GET /peer/hello (sin firma, todavia no hay clave compartida) y recien despues
              hace los dos POST /peer/pair.

peers.json vive en <LIENZO_HOME>/peers.json; las funciones sobre el archivo (add_peer, list_peers,
update_peer_ip, MAX_PEERS, PeerLimitError) son de federation.py, no se duplican aca. Las claves que
ya estan guardadas siguen sirviendo tal cual (el formato de peers.json no cambia): solo cambia
como se consigue una clave nueva.

El puerto propio para el listener de peers es fijo (7322, plan §3.2), pero se puede pisar con la
variable LIENZO_PEER_PORT, igual que LIENZO_HOME: sirve para correr dos PCs de prueba en la misma
maquina sin que se pisen los puertos.
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

import auth
import federation as fed
import identity
import state

PEER_PORT = 7322
OFFER_TTL_S = 300
PHRASE_WORDS = 1  # una palabra: comoda de tipear; la seguridad la da el DH (un intento por frase)
MAX_FAILS = 5
BLOCK_S = 15 * 60

_lock = threading.RLock()
_offer: dict | None = None  # {"phrase", "expires", "hs"}; una sola pendiente a la vez
_fails: list[float] = []
_blocked_until = 0.0


class PairingError(RuntimeError):
    """Frase vencida, proof invalido o tope de peers: un solo mensaje claro hacia afuera."""


def _peers_path() -> str:
    return os.path.join(state.LIENZO, "peers.json")


def _my_port() -> int:
    raw = os.environ.get("LIENZO_PEER_PORT")
    try:
        return int(raw) if raw else PEER_PORT
    except ValueError:
        return PEER_PORT


# --- SPAKE2 sobre MODP-2048 (RFC 3526, grupo 14), solo con pow ----------------------------------

# p es primo seguro (p = 2q + 1) y p = 7 mod 8, asi que g = 2 es residuo cuadratico y genera el
# subgrupo de orden primo q: todo publico valido vive ahi (se verifica con pow(v, q, p) == 1).
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74"
    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F1437"
    "4FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF05"
    "98DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB"
    "9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
G = 2
Q = (P - 1) // 2
_LEN = 256  # bytes de un elemento del grupo
EXP_BITS = 256  # exponentes efimeros: 2x los ~110 bits de seguridad del grupo (RFC 3526 §8)


def _hash_al_grupo(etiqueta: bytes) -> int:
    """M y N de SPAKE2: elementos del subgrupo cuyo logaritmo en base g nadie conoce (si alguien lo
    conociera podria sacar w de un publico cegado). Se obtienen hasheando una etiqueta fija a un
    numero mod p y elevandolo al cuadrado, que lo lleva al subgrupo de orden q."""
    crudo = hashlib.shake_256(b"lienzo-spake2/" + etiqueta).digest(_LEN + 32)
    return pow(int.from_bytes(crudo, "big") % P, 2, P)


M = _hash_al_grupo(b"M")  # ciega el publico del que pega la frase (join)
N = _hash_al_grupo(b"N")  # ciega el publico del que la ofrecio (accept)


def _w(clave_frase: bytes) -> int:
    """El escalar de la frase: sale de la clave scrypt de siempre (derive_pair_key), reducido mod q."""
    return int.from_bytes(hmac.new(clave_frase, b"lienzo-spake2/w", hashlib.sha512).digest(), "big") % Q


def _exponente() -> int:
    return secrets.randbelow(2**EXP_BITS - 2) + 2


def _cegar(exp: int, w: int, base: int) -> int:
    return pow(G, exp, P) * pow(base, w, P) % P


def _publico_valido(v) -> bool:
    """1 < v < p-1 y dentro del subgrupo de orden q: descarta 0, 1, p-1, p y cualquier elemento de
    orden chico que filtraria bits del exponente propio."""
    return isinstance(v, int) and not isinstance(v, bool) and 1 < v < P - 1 and pow(v, Q, P) == 1


def _leer_publico(raw) -> int:
    """Hex de a lo sumo 2*_LEN digitos (sin esa cota un int gigante es un DoS barato) -> int valido."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 2 * _LEN:
        raise PairingError("publico DH ausente o mal formado")
    try:
        v = int(raw, 16)
    except ValueError:
        raise PairingError("publico DH ausente o mal formado") from None
    if not _publico_valido(v):
        raise PairingError("publico DH invalido")
    return v


def _hex(v: int) -> str:
    return v.to_bytes(_LEN, "big").hex()


def _compartido(su_publico: int, w: int, su_base: int, mi_exp: int) -> int:
    """K = (su_publico / su_base^w)^mi_exp: le saca la ceguera con la frase y hace el DH."""
    return pow(su_publico * pow(su_base, -w, P) % P, mi_exp, P)


def _transcript(id_join: str, id_offer: str, x_pub: int, y_pub: int) -> bytes:
    """Orden canonico por rol (primero el que pega, despues el que ofrecio), cada campo con su largo
    adelante para que no haya dos transcripts distintos con los mismos bytes."""
    partes = [b"lienzo-pair-v2", id_join.encode("utf-8"), id_offer.encode("utf-8")]
    partes += [x_pub.to_bytes(_LEN, "big"), y_pub.to_bytes(_LEN, "big")]
    return b"".join(len(p).to_bytes(4, "big") + p for p in partes)


def _clave_final(clave_frase: bytes, transcript: bytes, k: int) -> bytes:
    return hmac.new(clave_frase, b"lienzo-pair-dh/" + transcript + k.to_bytes(_LEN, "big"), hashlib.sha256).digest()


def _confirmacion(clave: bytes, rol: bytes, transcript: bytes) -> str:
    """Prueba de posesion de la clave final sobre el transcript entero, distinta por rol: un proof de
    un lado no le sirve al otro para reenviarlo como propio, y uno de otro intercambio no da."""
    return hmac.new(clave, b"confirm/" + rol + b"/" + transcript, hashlib.sha256).hexdigest()


# --- freno de intentos, igual que auth.login (MAX_FAILS, BLOCK_S) ------------------------------


def _blocked_remaining() -> float:
    return max(0.0, _blocked_until - time.time())


def _register_fail() -> None:
    global _blocked_until
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < BLOCK_S]
    _fails.append(now)
    if len(_fails) >= MAX_FAILS:
        _blocked_until = now + BLOCK_S
        _fails.clear()


def _guardar_peer(peer: dict) -> None:
    """add_peer con los errores traducidos: el tope de peers y un peers.json que existe pero no se
    puede leer (federation ya no lo pisa en silencio, 0.8) salen como PairingError con el motivo, no
    como un 500."""
    try:
        fed.add_peer(_peers_path(), peer)
    except fed.PeerLimitError:
        raise PairingError(f"ya hay {fed.MAX_PEERS} peers emparejados") from None
    except OSError as e:
        raise PairingError(f"no se pudo guardar peers.json: {e}") from None


# --- offer / accept: el lado que muestra la frase ----------------------------------------------


def offer(ttl_s: int = OFFER_TTL_S) -> dict:
    """Genera la frase (PHRASE_WORDS palabras) y la deja pendiente. Una nueva llamada reemplaza la
    anterior, vencida o no: solo hay una frase pendiente a la vez."""
    global _offer
    phrase = auth.new_passphrase(PHRASE_WORDS)
    expires = time.time() + ttl_s
    with _lock:
        _offer = {"phrase": phrase, "expires": expires, "hs": None}
    return {"phrase": phrase, "expires": expires}


def accept(req: dict) -> dict:
    """Un paso del intercambio pedido por la otra PC en POST /peer/pair (ver el docstring del modulo).

    "start": valida el publico X, contesta con el publico propio Y y un id de intercambio. No cuenta
    como intento ni consume la frase, porque no revela nada: Y es indistinguible de un numero al azar
    sin el exponente. Un "start" nuevo reemplaza al pendiente.

    "confirm": verifica la confirmacion del otro lado. Si no da, consume la frase y cuenta como
    intento fallido (cinco bloquean accept 15 minutos): asi un atacante activo tiene un solo intento
    por frase. Si da: guarda el peer, consume la frase y devuelve pc_info() + el puerto propio + la
    confirmacion propia, para que join() verifique que habla con quien tiene la misma clave.

    Un pedido sin "step" (el formato de antes del DH) se rechaza sin evaluarlo."""
    global _offer
    with _lock:
        wait = _blocked_remaining()
        if wait > 0:
            raise PairingError(f"bloqueado {int(wait // 60) + 1} min por intentos fallidos")
        step = req.get("step")
        if step not in ("start", "confirm"):
            raise PairingError("la otra PC usa un emparejamiento viejo (sin DH): actualiza su lienzo")
        their_id = str(req.get("pc_id") or "")
        my_id = identity.pc_id()
        oferta = _offer
        if not oferta or not their_id or time.time() > oferta["expires"]:
            _register_fail()
            raise PairingError("frase vencida o inexistente")
        if their_id == my_id:
            raise PairingError("no se puede emparejar una PC consigo misma")
        if step == "start":
            x_pub = _leer_publico(req.get("spake"))
            clave_frase = fed.derive_pair_key(oferta["phrase"], my_id, their_id)
            w = _w(clave_frase)
            y = _exponente()
            y_pub = _cegar(y, w, N)
            # sin chequear K aca: rechazar un K raro en "start" (que no cuenta como intento) le
            # diria a un atacante si su X estaba cegado con la palabra correcta
            k = _compartido(x_pub, w, M, y)
            transcript = _transcript(their_id, my_id, x_pub, y_pub)
            clave = _clave_final(clave_frase, transcript, k)
            hs = secrets.token_hex(16)
            oferta["hs"] = {"id": hs, "pc_id": their_id, "transcript": transcript, "key": clave}
            return {**identity.pc_info(), "port": _my_port(), "step": "start", "spake": _hex(y_pub), "hs": hs}
        pendiente = oferta.get("hs")
        hs = req.get("hs")
        if (
            not pendiente
            or not isinstance(hs, str)
            or not hmac.compare_digest(pendiente["id"], hs)
            or pendiente["pc_id"] != their_id
        ):
            # no revela nada de la frase: no cuenta como intento (el que pega reintenta desde join)
            raise PairingError("intercambio inexistente o reemplazado: volve a pegar la frase")
        clave, transcript = pendiente["key"], pendiente["transcript"]
        proof = req.get("proof")
        if not isinstance(proof, str) or not hmac.compare_digest(_confirmacion(clave, b"join", transcript), proof):
            _offer = None  # un intento por frase: la siguiente prueba necesita una frase nueva
            _register_fail()
            raise PairingError("la frase no coincide: genera una frase nueva y volve a probar")
        peer = {
            "pc_id": their_id,
            "name": req.get("name") or their_id,
            "color": req.get("color") or "",
            "ip": "",
            "port": req.get("port"),
            "key": clave.hex(),
            "last_seen": time.time(),
        }
        _guardar_peer(peer)
        _offer = None  # consumida: no sirve para un segundo intento
        _fails.clear()
        return {**identity.pc_info(), "port": _my_port(), "proof": _confirmacion(clave, b"offer", transcript)}


# --- join: el lado que pega la frase -------------------------------------------------------------


PEDIR_TIMEOUT_S = 30.0  # el otro lado corre scrypt y potencias de 2048 bits: en una PC cargada 5 s no alcanzaron


def _pedir(
    host: str, port: int, method: str, path: str, body: dict | None = None, timeout: float = PEDIR_TIMEOUT_S
) -> dict:
    try:
        return _pedir_crudo(host, port, method, path, body, timeout)
    except (OSError, http.client.HTTPException, ValueError) as e:
        # un timeout o un corte no es un error interno del server: que diga que paso (medido el
        # 2026-10-04: un emparejamiento contra una PC cargada salio como 500 por un TimeoutError)
        raise PairingError(f"la otra PC ({host}:{port}) no contestó bien: {type(e).__name__}: {e}") from e


def _pedir_crudo(host: str, port: int, method: str, path: str, body: dict | None, timeout: float) -> dict:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if resp.status != 200:
            motivo = parsed.get("error") if isinstance(parsed, dict) else None
            raise PairingError(str(motivo or f"HTTP {resp.status}"))
        return parsed
    finally:
        conn.close()


def join(phrase: str, host: str, port: int) -> dict:
    """Pega la frase: resuelve el pc_id de la otra PC con GET /peer/hello (sin firma: todavia no hay
    clave compartida), hace el intercambio en dos POST /peer/pair y verifica la confirmacion de
    vuelta antes de guardar el peer: si no coincide, la otra PC no tenia la misma frase (o no es
    quien dijo ser). Un tope de peers propio sale como fed.PeerLimitError, como antes."""
    hello = _pedir(host, port, "GET", "/peer/hello")
    their_id = str(hello.get("pc_id") or "")
    if not their_id:
        raise PairingError("la otra PC no contesto /peer/hello")
    my_id = identity.pc_id()
    clave_frase = fed.derive_pair_key(phrase, my_id, their_id)
    w = _w(clave_frase)
    x = _exponente()
    x_pub = _cegar(x, w, M)
    info = {**identity.pc_info(), "port": _my_port()}
    inicio = _pedir(host, port, "POST", "/peer/pair", {**info, "step": "start", "spake": _hex(x_pub)})
    y_pub = _leer_publico(inicio.get("spake"))
    k = _compartido(y_pub, w, N, x)
    if k in (0, 1, P - 1):  # solo pasa si el otro lado eligio Y para forzarlo: no es un DH honesto
        raise PairingError("intercambio DH invalido")
    transcript = _transcript(my_id, their_id, x_pub, y_pub)
    clave = _clave_final(clave_frase, transcript, k)
    body = {**info, "step": "confirm", "hs": inicio.get("hs"), "proof": _confirmacion(clave, b"join", transcript)}
    resultado = _pedir(host, port, "POST", "/peer/pair", body)
    proof_vuelta = resultado.get("proof")
    esperado = _confirmacion(clave, b"offer", transcript)
    if not isinstance(proof_vuelta, str) or not hmac.compare_digest(esperado, proof_vuelta):
        raise PairingError("proof de vuelta invalido: la otra PC no tiene la misma clave")
    peer = {
        "pc_id": their_id,
        "name": resultado.get("name") or their_id,
        "color": resultado.get("color") or "",
        "ip": host,
        "port": resultado.get("port"),
        "key": clave.hex(),
        "last_seen": time.time(),
    }
    try:
        fed.add_peer(_peers_path(), peer)
    except OSError as e:
        raise PairingError(f"no se pudo guardar peers.json: {e}") from None
    return peer
