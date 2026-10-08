"""WebSocket minimo (RFC 6455) con la biblioteca estandar, para el canal de Chrome remoto.

Por que: cada cuadro de Chrome viajaba en un POST propio (JSON + base64 + cifrado por salto) y el
visor recien pedia el siguiente al terminar de dibujar. Un canal persistente deja que la PC duena
empuje los cuadros y que el mouse salga sin esperar a nadie.

Lado servidor (`server_handshake`): toma el socket de un BaseHTTPRequestHandler ya autenticado.
Lado cliente (`client_connect`): un socket crudo hacia el listener de pares, con los headers
firmados de siempre. Las dos puntas comparten `Socket`: send con lock, recv con pong automatico,
limite de tamano y cierre limpio.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import socket
import struct
import threading

TEXT, BINARY, CLOSE, PING, PONG = 1, 2, 8, 9, 10
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 32 * 1024 * 1024  # un cuadro PNG de 3840x2160 entra con margen
IDLE_TIMEOUT_S = 90.0  # mas que el ping de 20 s: un par que no habla en este tiempo se corta


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


def _xor_mask(payload: bytes, mask: bytes) -> bytes:
    if not payload:
        return payload
    n = len(payload)
    rep = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "little") ^ int.from_bytes(rep, "little")).to_bytes(n, "little")


class Socket:
    """Un WebSocket abierto. `mask` es True del lado cliente (RFC: el cliente enmascara)."""

    def __init__(self, sock: socket.socket, reader, mask: bool):
        self.sock = sock
        self.reader = reader
        self.mask = mask
        self.closed = False
        self._send_lock = threading.Lock()
        self._pinger: threading.Thread | None = None
        self._stop = threading.Event()
        sock.settimeout(IDLE_TIMEOUT_S)

    def _exact(self, n: int) -> bytes:
        data = self.reader.read(n)
        if len(data) != n:
            raise ConnectionError("conexion cerrada")
        return data

    def send(self, opcode: int, payload: bytes) -> None:
        if len(payload) > MAX_MESSAGE:
            raise ValueError("mensaje demasiado grande")
        head = bytes([0x80 | opcode])
        n = len(payload)
        flag = 0x80 if self.mask else 0
        if n < 126:
            head += bytes([flag | n])
        elif n < 65536:
            head += bytes([flag | 126]) + struct.pack(">H", n)
        else:
            head += bytes([flag | 127]) + struct.pack(">Q", n)
        if self.mask:
            mask = secrets.token_bytes(4)
            head += mask
            payload = _xor_mask(payload, mask)
        with self._send_lock:
            if self.closed:
                raise ConnectionError("websocket cerrado")
            self.sock.sendall(head + payload)

    def recv(self) -> tuple[int, bytes] | None:
        """(opcode, mensaje) del proximo mensaje de datos; None si la otra punta cerro. Los ping
        se contestan solos y los pong se ignoran. Fragmentos se juntan hasta el ultimo."""
        parts: list[bytes] = []
        opcode = 0
        while True:
            b0, b1 = self._exact(2)
            fin, op, masked, n = b0 & 0x80, b0 & 0x0F, b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            if n > MAX_MESSAGE:
                self.close(1009)
                raise ValueError("mensaje demasiado grande")
            mask = self._exact(4) if masked else b""
            data = self._exact(n)
            if masked:
                data = _xor_mask(data, mask)
            if op == CLOSE:
                self.close()
                return None
            if op == PING:
                try:
                    self.send(PONG, data)
                except (OSError, ConnectionError):
                    return None
                continue
            if op == PONG:
                continue
            if op in (TEXT, BINARY):
                if parts:
                    raise ValueError("fragmento sin terminar")
                opcode = op
            elif op == 0:
                if not parts:
                    raise ValueError("continuacion sin inicio")
            else:
                raise ValueError("opcode desconocido")
            parts.append(data)
            if sum(len(p) for p in parts) > MAX_MESSAGE:
                self.close(1009)
                raise ValueError("mensaje demasiado grande")
            if fin:
                return opcode, b"".join(parts)

    def pings(self, interval_s: float = 20.0) -> None:
        """Un ping periodico desde esta punta, para que un socket callado no se corte."""

        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.send(PING, b"")
                except (OSError, ValueError, ConnectionError):
                    return

        self._pinger = threading.Thread(target=loop, daemon=True)
        self._pinger.start()

    def close(self, code: int = 1000) -> None:
        with self._send_lock:
            if self.closed:
                return
            self.closed = True
            self._stop.set()
            payload = struct.pack(">H", code)
            if self.mask:
                mask = secrets.token_bytes(4)
                frame = bytes([0x80 | CLOSE, 0x80 | 2]) + mask + _xor_mask(payload, mask)
            else:
                frame = bytes([0x80 | CLOSE, 2]) + payload
            try:
                self.sock.sendall(frame)
            except OSError:
                pass  # ya estaba cortado: solo queda cerrar de este lado
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()


def server_handshake(handler) -> Socket | None:
    """Contesta 101 sobre la conexion del handler y devuelve el Socket; None (ya contestado con
    400) si el pedido no es un upgrade valido."""
    h = handler.headers
    key = h.get("Sec-WebSocket-Key") or ""
    if (
        "websocket" not in (h.get("Upgrade") or "").lower()
        or "upgrade" not in (h.get("Connection") or "").lower()
        or h.get("Sec-WebSocket-Version") != "13"
        or len(key) != 24
    ):
        handler.send_response(400)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(b'{"error": "hace falta un WebSocket"}')
        return None
    handler.wfile.write(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        ).encode("ascii")
    )
    handler.wfile.flush()
    handler.close_connection = True
    return Socket(handler.connection, handler.rfile, mask=False)


def client_connect(host: str, port: int, path: str, headers: dict, timeout: float = 10.0) -> Socket:
    """Abre un WebSocket contra `host:port` con los headers dados (los firmados del par)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        reader = sock.makefile("rb")
        status = reader.readline(8192).decode("latin-1", "replace").strip()
        got: dict[str, str] = {}
        while True:
            line = reader.readline(8192)
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1", "replace").partition(":")
            got[name.strip().lower()] = value.strip()
        if not status.startswith("HTTP/1.1 101"):
            raise ConnectionError(f"la otra PC no abrio el canal ({status[:80] or 'sin respuesta'})")
        if got.get("sec-websocket-accept") != accept_key(key):
            raise ConnectionError("la otra PC contesto un websocket invalido")
        return Socket(sock, reader, mask=True)
    except BaseException:
        sock.close()
        raise
