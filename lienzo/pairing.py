"""Emparejamiento entre dos PCs (plan-multi-pc-2026-09-26.md §3.1). Una PC ofrece una frase de
seis palabras (reusa auth.new_passphrase, mismo generador EFF); la otra la pega. De ahi sale la
clave compartida del par (federation.derive_pair_key) y cada lado prueba que la conoce con un
HMAC atado a su propio pc_id, para que un proof capturado no sirva para hacerse pasar por el otro
lado del par.

  offer()  -> lado que muestra la frase: la deja pendiente en memoria, una sola a la vez.
  accept() -> el mismo lado que ofrecio, cuando llega el pedido de la otra PC (via /peer/pair,
              que server.py todavia no expone: eso es la ronda 2 de quien enchufa esto).
  join()   -> el lado que pega la frase: no conoce el pc_id de la otra PC de antemano, lo resuelve
              con GET /peer/hello (sin firma, todavia no hay clave compartida) y recien despues
              manda el POST /peer/pair con su proof.

peers.json vive en <LIENZO_HOME>/peers.json; las funciones sobre el archivo (add_peer, list_peers,
list_peers, update_peer_ip, MAX_PEERS, PeerLimitError) son de federation.py, no se duplican aca.

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
import threading
import time

import auth
import federation as fed
import identity
import state

PEER_PORT = 7322
OFFER_TTL_S = 300
PHRASE_WORDS = 1  # una palabra: cómoda de tipear; con 6 sería mucho más difícil de adivinar
MAX_FAILS = 5
BLOCK_S = 15 * 60

_lock = threading.RLock()
_offer: dict | None = None  # {"phrase", "expires"}; una sola pendiente a la vez
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


def _proof(key: bytes, pc_id_: str) -> str:
    """Cada lado prueba que conoce la clave firmando su PROPIO pc_id: asi el proof que un lado
    genera para probarse a si mismo no sirve para que el otro lado lo reenvie como si fuera
    suyo (los pc_id son distintos, asi que el HMAC tambien)."""
    return hmac.new(key, f"pair|{pc_id_}".encode(), hashlib.sha256).hexdigest()


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


# --- offer / accept: el lado que muestra la frase ----------------------------------------------


def offer(ttl_s: int = OFFER_TTL_S) -> dict:
    """Genera la frase (PHRASE_WORDS palabras) y la deja pendiente. Una nueva llamada reemplaza la
    anterior, vencida o no: solo hay una frase pendiente a la vez."""
    global _offer
    phrase = auth.new_passphrase(PHRASE_WORDS)
    expires = time.time() + ttl_s
    with _lock:
        _offer = {"phrase": phrase, "expires": expires}
    return {"phrase": phrase, "expires": expires}


def accept(req: dict) -> dict:
    """Valida el pedido {pc_id, name, color, port, proof} de la otra PC contra la frase pendiente.
    Si la frase vencio, el proof no da o ya hay MAX_PEERS emparejados levanta PairingError con un
    mensaje claro; los primeros dos casos cuentan como intento fallido (cinco bloquean accept 15
    minutos). Si todo da: guarda el peer, consume la frase y devuelve pc_info() + el puerto propio
    + el proof de vuelta, para que join() verifique que esta hablando con quien tiene la clave."""
    global _offer
    with _lock:
        wait = _blocked_remaining()
        if wait > 0:
            raise PairingError(f"bloqueado {int(wait // 60) + 1} min por intentos fallidos")
        their_id = str(req.get("pc_id") or "")
        oferta = _offer
        if not oferta or not their_id or time.time() > oferta["expires"]:
            _register_fail()
            raise PairingError("frase vencida o inexistente")
        key = fed.derive_pair_key(oferta["phrase"], identity.pc_id(), their_id)
        proof = req.get("proof")
        if not isinstance(proof, str) or not hmac.compare_digest(_proof(key, their_id), proof):
            _register_fail()
            raise PairingError("proof invalido")
        peer = {
            "pc_id": their_id,
            "name": req.get("name") or their_id,
            "color": req.get("color") or "",
            "ip": "",
            "port": req.get("port"),
            "key": key.hex(),
            "last_seen": time.time(),
        }
        try:
            fed.add_peer(_peers_path(), peer)
        except fed.PeerLimitError:
            raise PairingError(f"ya hay {fed.MAX_PEERS} peers emparejados") from None
        _offer = None  # consumida: no sirve para un segundo intento, exitoso o no
        _fails.clear()
        return {**identity.pc_info(), "port": _my_port(), "proof": _proof(key, identity.pc_id())}


# --- join: el lado que pega la frase -------------------------------------------------------------


def _pedir(host: str, port: int, method: str, path: str, body: dict | None = None, timeout: float = 5.0) -> dict:
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
    """Pega la frase: no conoce el pc_id de la otra PC de antemano, lo resuelve con
    GET /peer/hello (sin firma: todavia no hay clave compartida) y recien ahi puede armar el
    proof para el POST /peer/pair. Verifica el proof de vuelta antes de guardar el peer: si no
    coincide, la otra PC no tenia la misma frase (o no es quien dijo ser)."""
    hello = _pedir(host, port, "GET", "/peer/hello")
    their_id = str(hello.get("pc_id") or "")
    if not their_id:
        raise PairingError("la otra PC no contesto /peer/hello")
    my_id = identity.pc_id()
    key = fed.derive_pair_key(phrase, my_id, their_id)
    body = {**identity.pc_info(), "port": _my_port(), "proof": _proof(key, my_id)}
    resultado = _pedir(host, port, "POST", "/peer/pair", body)
    proof_vuelta = resultado.get("proof")
    if not isinstance(proof_vuelta, str) or not hmac.compare_digest(_proof(key, their_id), proof_vuelta):
        raise PairingError("proof de vuelta invalido: la otra PC no tiene la misma clave")
    peer = {
        "pc_id": their_id,
        "name": resultado.get("name") or their_id,
        "color": resultado.get("color") or "",
        "ip": host,
        "port": resultado.get("port"),
        "key": key.hex(),
        "last_seen": time.time(),
    }
    fed.add_peer(_peers_path(), peer)
    return peer
