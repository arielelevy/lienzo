"""Canal persistente de Chrome remoto: un WebSocket del visor al worker de la PC duena.

Visor (navegador) ──ws──> Lienzo local ──ws firmado y cifrado──> Lienzo de la otra PC ──pipe──> worker
                                        (o directo al worker si la PC elegida es esta)

El worker (`browser_window.py --stream`) captura solo y empuja cada cuadro apenas cambia algo; el
visor acusa cada cuadro y nunca hay mas de dos en vuelo. La entrada va por el mismo canal, sin
cola ni espera de la imagen. Entre PCs cada mensaje viaja sellado con una clave derivada de la
del par y del id de este canal, con numero de secuencia por sentido: ni replay ni reorden.

Mensajes de texto (JSON) del visor al worker: open, size, input, ack, release, windows.
Del worker al visor: texto JSON (opened, input, error, windows) y binario (cuadro: cabecera de
17 bytes y PNG, ver browser_window.FRAME_HEADER).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import struct
import subprocess
import sys
import threading
from pathlib import Path

import federation
import identity
import mirror
import secretos
import state
import ws

MAX_SESSIONS = 4  # vistas abiertas a la vez en esta PC (cada una es un worker capturando)
MAX_COMMAND = 65536
RECORD = struct.Struct(">IB")  # largo (tipo + carga) y tipo: J json, F cuadro
_sessions = 0
_sessions_lock = threading.Lock()


def channel_key(pair_key: bytes, sid: str) -> bytes:
    return hmac.new(pair_key, b"lienzo/chrome-stream/v1/" + sid.encode("ascii"), hashlib.sha256).digest()


def _command(payload: bytes) -> bytes:
    """Una linea JSON ASCII y acotada para el worker; ValueError si no es un objeto razonable."""
    if len(payload) > MAX_COMMAND:
        raise ValueError("pedido demasiado grande")
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("t"), str):
        raise ValueError("pedido invalido")  # noqa: TRY004 - el visor recibe un solo tipo de error
    return json.dumps(data, ensure_ascii=True).encode("ascii") + b"\n"


def _error(message: str) -> bytes:
    return json.dumps({"t": "error", "message": message}, ensure_ascii=True).encode("ascii")


class Worker:
    """El proceso de captura y entrada de esta PC. `deliver(opcode, payload)` lleva lo que emite
    hacia el visor; `on_exit()` avisa cuando el proceso termina."""

    def __init__(self, deliver, on_exit):
        if os.name != "nt":
            raise RuntimeError("La vista de ventana real requiere Windows en esa PC")
        self.deliver = deliver
        self.on_exit = on_exit
        self.lock = threading.Lock()
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("browser_window.py")), "--stream"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()

    def _errors(self):
        remaining = 8192
        try:
            while line := self.process.stderr.readline(1024):
                if remaining > 0:
                    excerpt = line[:remaining].decode("utf-8", "replace")
                    remaining -= len(excerpt)
                    state.log(f"Chrome stream: {excerpt.rstrip()}")
        except (OSError, ValueError):
            pass  # el cierre del proceso corta tambien este lector

    def _read(self):
        out = self.process.stdout
        try:
            while True:
                head = out.read(RECORD.size)
                if len(head) != RECORD.size:
                    break
                n, kind = RECORD.unpack(head)
                if n < 1 or n > ws.MAX_MESSAGE:
                    break
                payload = out.read(n - 1)
                if len(payload) != n - 1:
                    break
                self.deliver(ws.TEXT if kind == ord("J") else ws.BINARY, payload)
        except (OSError, ValueError, ConnectionError):
            pass  # el visor se fue o el pipe se cerro: se termina igual
        finally:
            try:
                self.deliver(ws.TEXT, _error("Se cerró el worker de Chrome en esa PC"))
            except (OSError, ValueError, ConnectionError):
                pass
            self.on_exit()

    def send(self, line: bytes) -> None:
        with self.lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()

    def close(self) -> None:
        process = self.process
        with self.lock:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass


def _reserve() -> bool:
    global _sessions
    with _sessions_lock:
        if _sessions >= MAX_SESSIONS:
            return False
        _sessions += 1
        return True


def _free() -> None:
    global _sessions
    with _sessions_lock:
        _sessions -= 1


def _run_worker(sock: ws.Socket, deliver, incoming):
    """Vida de una sesion con worker propio: `incoming()` da el proximo pedido (bytes de JSON) o
    None al cerrar; `deliver` lleva lo del worker al visor."""
    if not _reserve():
        deliver(ws.TEXT, _error("Hay demasiadas vistas de Chrome abiertas en esa PC"))
        return
    try:
        worker = Worker(deliver, sock.close)
    except (OSError, RuntimeError) as exc:
        _free()
        deliver(ws.TEXT, _error(str(exc)))
        return
    try:
        while (payload := incoming()) is not None:
            try:
                worker.send(_command(payload))
            except (ValueError, UnicodeDecodeError) as exc:
                deliver(ws.TEXT, _error(f"Pedido inválido: {exc}"))
            except OSError:
                break  # el worker murio: su lector ya avisa y cierra
    finally:
        worker.close()
        _free()


class Sealed:
    """Una punta del tramo entre PCs: sella lo que sale y abre lo que entra, cada sentido con su
    contador. El contador entra en la MAC: un mensaje repetido o fuera de orden no verifica."""

    def __init__(self, key: bytes, outgoing: bytes, incoming: bytes):
        self.key = key
        self.out_dir, self.in_dir = outgoing, incoming
        self.sent = 0
        self.received = 0
        self.lock = threading.Lock()

    def seal(self, sock: ws.Socket, kind: int, payload: bytes) -> None:
        with self.lock:
            aad = self.out_dir + self.sent.to_bytes(8, "big")
            self.sent += 1
            sock.send(ws.BINARY, secretos.sellar(self.key, (b"T" if kind == ws.TEXT else b"B") + payload, aad))

    def open(self, payload: bytes) -> tuple[int, bytes]:
        aad = self.in_dir + self.received.to_bytes(8, "big")
        self.received += 1
        plain = secretos.abrir(self.key, payload, aad)
        if not plain or plain[:1] not in (b"T", b"B"):
            raise ValueError("tipo de mensaje invalido")
        return (ws.TEXT if plain[:1] == b"T" else ws.BINARY), plain[1:]


def _recv_text(sock: ws.Socket):
    """El proximo mensaje de texto del visor; lo binario se ignora, el cierre da None."""
    while True:
        try:
            msg = sock.recv()
        except (OSError, ValueError, ConnectionError):
            return None
        if msg is None or msg[0] == ws.TEXT:
            return msg[1] if msg else None


def serve_viewer(handler, pc: str) -> None:
    """GET /browser/stream?pc=… del tablero (ya autenticado y local). Toma el socket."""
    sock = ws.server_handshake(handler)
    if sock is None:
        return
    try:
        sock.pings()  # un visor quieto (nada cambia, nadie toca) no tiene que vencer el timeout del socket
        if not pc:
            sock.send(ws.TEXT, _error("Elegí la PC donde querés ver Chrome"))
        elif pc == identity.pc_id():
            _run_worker(sock, sock.send, lambda: _recv_text(sock))
        else:
            _relay(sock, pc)
    except (OSError, ValueError, ConnectionError) as exc:
        state.log(f"Chrome stream: {type(exc).__name__}: {exc}")
    finally:
        sock.close()


def _relay(sock: ws.Socket, pc: str) -> None:
    conn = mirror.MIRROR.conn_of(pc)
    if conn is None:
        sock.send(ws.TEXT, _error("La PC elegida no está emparejada"))
        return
    if mirror.MIRROR.supports(pc, "browser.stream") is False:
        sock.send(ws.TEXT, _error("Actualizá y reiniciá Lienzo en la otra PC para ver su Chrome en vivo"))
        return
    sid = secrets.token_hex(16)
    path = f"/peer/browser/stream/{sid}"
    try:
        peer = ws.client_connect(conn.host, conn.port, path, federation.signed_headers(conn, "GET", path, b""))
    except (OSError, ConnectionError) as exc:
        sock.send(ws.TEXT, _error(f"No se pudo abrir el canal con la otra PC: {exc}"))
        return
    sealed = Sealed(channel_key(conn.key, sid), b">", b"<")
    peer.pings()

    def pump():
        try:
            while (msg := peer.recv()) is not None:
                if msg[0] == ws.BINARY:
                    kind, payload = sealed.open(msg[1])
                    sock.send(kind, payload)
        except (OSError, ValueError, ConnectionError) as exc:
            try:
                sock.send(ws.TEXT, _error(f"Se cortó el canal con la otra PC ({type(exc).__name__})"))
            except (OSError, ValueError, ConnectionError):
                pass
        finally:
            sock.close()

    threading.Thread(target=pump, daemon=True).start()
    try:
        while (payload := _recv_text(sock)) is not None:
            sealed.seal(peer, ws.TEXT, payload)
    finally:
        peer.close()


def serve_peer(handler, pair_key: bytes | None, sid: str) -> None:
    """GET /peer/browser/stream/<sid> firmado por la otra PC: el worker vive aca."""
    if pair_key is None or len(sid) != 32 or not all(c in "0123456789abcdef" for c in sid):
        handler._json(400, {"error": "canal invalido"})
        return
    sock = ws.server_handshake(handler)
    if sock is None:
        return
    sealed = Sealed(channel_key(pair_key, sid), b"<", b">")

    def incoming():
        while True:
            try:
                msg = sock.recv()
                if msg is None:
                    return None
                if msg[0] != ws.BINARY:
                    continue
                kind, payload = sealed.open(msg[1])
            except (OSError, ValueError, ConnectionError):
                return None
            if kind == ws.TEXT:
                return payload

    try:
        _run_worker(sock, lambda kind, payload: sealed.seal(sock, kind, payload), incoming)
    except (OSError, ValueError, ConnectionError) as exc:
        state.log(f"Chrome stream (peer): {type(exc).__name__}: {exc}")
    finally:
        sock.close()

