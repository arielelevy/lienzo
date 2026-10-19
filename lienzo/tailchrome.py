"""Puente TCP entre pares transportado por una pestaña con Tailchrome.

El navegador sólo mueve sobres cifrados. Cada conexión termina exclusivamente en
el listener privado de PeerHandler; los pedidos conservan su firma habitual.
Ni los puertos efímeros ni las IP del puente se guardan en peers.json.
"""

from __future__ import annotations

import hashlib
import hmac
import socket
import struct
import threading

import secretos
import ws

PATH = "/peer/tailchrome"
MAX_CHANNELS = 32
CHUNK = 16384
HEADER = struct.Struct(">BI")
HELLO, OPEN, DATA, END = 0, 1, 2, 3


def channel_key(key: bytes, nonce: str) -> bytes:
    return hmac.new(key, b"lienzo/tailchrome/v1/" + nonce.encode("ascii"), hashlib.sha256).digest()


class Bridge:
    """Multiplexor acotado, con secuencias independientes por sentido."""

    def __init__(self, wire, key, nonce, initiator, target, self_id, peer_id, on_ready, log):
        self.wire = wire
        self.key = channel_key(key, nonce)
        self.tx_direction = b"I" if initiator else b"R"
        self.rx_direction = b"R" if initiator else b"I"
        self.tx_seq = self.rx_seq = 0
        self.next_id = 1 if initiator else 2
        self.parity = self.next_id % 2
        self.last_remote_id = 0
        self.target = target
        self.self_id, self.peer_id = self_id, peer_id
        self.on_ready, self.log = on_ready, log
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.channels = {}
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(MAX_CHANNELS)
        self.listener.settimeout(0.5)
        self.address = self.listener.getsockname()

    def send(self, kind, cid=0, payload=b""):
        with self.send_lock:
            aad = self.tx_direction + self.tx_seq.to_bytes(8, "big")
            blob = secretos.sellar(self.key, HEADER.pack(kind, cid) + payload, aad)
            self.wire.send(ws.BINARY, blob)
            self.tx_seq += 1

    def receive(self):
        message = self.wire.recv()
        if message is None:
            return None
        opcode, blob = message
        if opcode != ws.BINARY or len(blob) > CHUNK + 128:
            raise ValueError("sobre de puente inválido")
        aad = self.rx_direction + self.rx_seq.to_bytes(8, "big")
        raw = secretos.abrir(self.key, blob, aad)
        self.rx_seq += 1
        if len(raw) < HEADER.size:
            raise ValueError("mensaje de puente incompleto")
        kind, cid = HEADER.unpack(raw[: HEADER.size])
        return kind, cid, raw[HEADER.size :]

    def run(self):
        try:
            self.wire.pings()
            self.send(HELLO, payload=self.self_id.encode("ascii"))
            if self.receive() != (HELLO, 0, self.peer_id.encode("ascii")):
                raise ValueError("el puente no confirmó la identidad del par")
            self.ready.set()
            self.wire.send(ws.TEXT, b'{"ready":true}')
            threading.Thread(target=self._accept, daemon=True).start()
            # El callback abre SSE; no debe bloquear al lector de ese mismo SSE.
            threading.Thread(target=self.on_ready, args=(self,), daemon=True).start()
            while not self.closed.is_set():
                message = self.receive()
                if message is None:
                    break
                self._dispatch(*message)
        except (OSError, ValueError, UnicodeError) as exc:
            self.log(f"puente Tailchrome {self.peer_id}: {exc}")
        finally:
            self.close()

    def _accept(self):
        while not self.closed.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self.lock:
                if len(self.channels) >= MAX_CHANNELS:
                    conn.close()
                    continue
                cid = self.next_id
                self.next_id += 2
                conn.settimeout(90)
                self.channels[cid] = conn
            try:
                self.send(OPEN, cid)
            except (OSError, ValueError) as exc:
                self.log(f"puente Tailchrome: no se pudo abrir un canal ({exc})")
                self.close()
                return
            threading.Thread(target=self._pump, args=(cid, conn), daemon=True).start()

    def _dispatch(self, kind, cid, payload):
        if not cid or len(payload) > CHUNK:
            raise ValueError("canal de puente inválido")
        if kind == OPEN:
            with self.lock:
                if payload or cid % 2 == self.parity or cid <= self.last_remote_id:
                    raise ValueError("apertura de canal inválida")
                self.last_remote_id = cid
                if len(self.channels) >= MAX_CHANNELS:
                    self.send(END, cid)
                    return
                try:
                    conn = socket.create_connection(self.target, timeout=5)
                except OSError as exc:
                    self.log(f"puente Tailchrome: listener local inaccesible ({exc})")
                    self.send(END, cid)
                    return
                conn.settimeout(90)
                self.channels[cid] = conn
            threading.Thread(target=self._pump, args=(cid, conn), daemon=True).start()
        elif kind == DATA:
            with self.lock:
                conn = self.channels.get(cid)
            if conn is not None:
                try:
                    conn.sendall(payload)
                except OSError:
                    self._drop(cid)
                    self.send(END, cid)
        elif kind == END and not payload:
            self._drop(cid)
        else:
            raise ValueError("operación de puente inválida")

    def _pump(self, cid, conn):
        try:
            while not self.closed.is_set():
                data = conn.recv(CHUNK)
                if not data:
                    break
                self.send(DATA, cid, data)
        except (OSError, ValueError) as exc:
            if not self.closed.is_set():
                self.log(f"puente Tailchrome canal {cid}: {exc}")
        finally:
            self._drop(cid)
            if not self.closed.is_set():
                try:
                    self.send(END, cid)
                except OSError:
                    self.close()

    def _drop(self, cid):
        with self.lock:
            conn = self.channels.pop(cid, None)
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # el cierre remoto puede haber cerrado ambos sentidos
            conn.close()

    def close(self):
        self.closed.set()
        self.listener.close()
        with self.lock:
            ids = list(self.channels)
        for cid in ids:
            self._drop(cid)
        self.wire.close()
