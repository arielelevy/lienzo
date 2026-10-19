"""Arranque persistente, inventario de la tailnet y puentes sin pestaña.

Reutiliza el mismo endpoint y multiplexor que el navegador. El inventario incluye
todos los nodos publicados por el helper; sólo los pares conocidos pueden conectar.
"""

from __future__ import annotations

import atexit
import http.client
import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlparse

import federation
import identity
import red
import state
import tailchrome_native
import ws


def hostname():
    base = re.sub(r"[^a-z0-9-]", "-", socket.gethostname().lower()).strip("-")[:55]
    return f"{base}-lienzo"


def probe(host, ip, port):
    """El hello sólo descubre: no acredita identidad ni permisos del nodo."""
    connection = http.client.HTTPConnection(ip, port, timeout=3)
    try:
        connection.sock = host.tunnel(ip, port, timeout=3)
        connection.request("GET", "/peer/hello")
        response = connection.getresponse()
        if response.status != 200:
            return None
        data = json.loads(response.read(8193))
        if (
            isinstance(data, dict)
            and isinstance(data.get("pc_id"), str)
            and re.fullmatch(r"[0-9a-f]{12}", data["pc_id"])
            and isinstance(data.get("name"), str)
            and data["name"]
        ):
            return data
    except OSError, ValueError, RuntimeError, http.client.HTTPException:
        return None  # nodo sin listener compatible; no se le concede confianza
    finally:
        connection.close()
    return None


class Relay:
    """La misma lanzadera de la página, ejecutada como un hilo del servidor."""

    def __init__(self, host, board_port, peer, ip, log):
        self.host, self.board_port, self.peer, self.ip, self.log = host, board_port, peer, ip, log
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.wires = []
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _wire(self, *args, **kwargs):
        wire = ws.client_connect(*args, **kwargs)
        with self.lock:
            if self.closed.is_set():
                wire.close()
                raise ConnectionError("el puente se detuvo")
            self.wires.append(wire)
        return wire

    def _run(self):
        try:
            path = "/tailchrome/stream?" + urlencode({"pc": self.peer["pc_id"], "host": self.ip})
            local = self._wire("127.0.0.1", self.board_port, path, {"Origin": f"http://127.0.0.1:{self.board_port}"})
            message = local.recv()
            if message is None or message[0] != ws.TEXT:
                raise ValueError("Lienzo no publicó el destino del puente")
            url = urlparse(json.loads(message[1])["url"])
            if url.scheme != "ws" or url.hostname != self.ip or url.port != self.peer["port"]:
                raise ValueError("destino del puente inesperado")
            tunnel = self.host.tunnel(self.ip, url.port)
            remote = self._wire(self.ip, url.port, url.path + "?" + url.query, {}, connected_socket=tunnel)
            threading.Thread(target=self._pump, args=(remote, local), daemon=True).start()
            self._pump(local, remote)
        except (OSError, ValueError, RuntimeError, KeyError, http.client.HTTPException) as exc:
            self.error = str(exc)
            self.log(f"Tailchrome automático {self.peer['pc_id']}: {exc}")
        finally:
            self.close()

    def _pump(self, source, target):
        try:
            while not self.closed.is_set():
                message = source.recv()
                if message is None:
                    break
                opcode, data = message
                if opcode == ws.BINARY:
                    target.send(opcode, data)
                elif opcode == ws.TEXT and json.loads(data).get("ready"):
                    self.ready.set()
        except (OSError, ValueError) as exc:
            if not self.closed.is_set():
                self.error = str(exc)
                self.log(f"Tailchrome automático: canal interrumpido ({exc})")
        finally:
            self.close()

    def close(self):
        self.closed.set()
        with self.lock:
            wires = list(self.wires)
        for wire in wires:
            wire.close()


class Service:
    def __init__(self, board_port, peer_port=7322, host_factory=None):
        self.board_port, self.peer_port = board_port, peer_port
        self.host_factory = host_factory or tailchrome_native.Host
        self.lock = threading.RLock()
        self.lifecycle = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.host = None
        self.rows = []
        self.relays = {}
        self.retry_at = {}
        self.error = None
        self.enabled = False
        self.total = 0
        self.truncated = False

    @property
    def config_path(self):
        return Path(state.LIENZO) / "tailchrome-process.json"

    def autostart(self):
        if self.config_path.exists():
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("configuración del proceso inválida")
            if data.get("enabled") is True:
                self.configure(True)

    def configure(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled debe ser booleano")
        with self.lifecycle:
            if self.thread is not None and self.thread.is_alive():
                if enabled:
                    return
                self.close()
                self.thread.join(8)
                if self.thread.is_alive():
                    raise RuntimeError("el proceso todavía se está cerrando; esperá unos segundos")
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            state.atomic_write(str(self.config_path), json.dumps({"enabled": enabled}))
            self.enabled = enabled
            if enabled:
                self.stop = threading.Event()
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            host = None
            try:
                host = self.host_factory("lienzo-" + identity.pc_id())
                with self.lock:
                    self.host = host
                host.start()
                host.send({"cmd": "set-prefs", "prefs": {"hostname": hostname()}})
                with self.lock:
                    self.error = None
                login_requested = False
                while not self.stop.is_set() and not host.dead.is_set():
                    host.send({"cmd": "get-status"})
                    snapshot = host.snapshot()
                    if snapshot.get("needsLogin") and not login_requested:
                        host.send({"cmd": "login"})
                        login_requested = True
                    self._scan(host, snapshot)
                    if self.stop.wait(10):
                        break
                if host.dead.is_set() and not self.stop.is_set():
                    raise RuntimeError(host.error or "el helper terminó")
            except (OSError, ValueError, RuntimeError) as exc:
                with self.lock:
                    changed = self.error != str(exc)
                    self.error = str(exc)
                if changed:
                    state.log(f"Tailchrome automático: {exc}")
            finally:
                self._close_relays()
                if host is not None:
                    host.close()
                with self.lock:
                    if self.host is host:
                        self.host = None
            if self.stop.wait(10):
                break

    def _scan(self, host, snapshot):
        own_node = snapshot.get("selfNode")
        nodes = ([own_node] if own_node else []) + (snapshot.get("peers") or [])
        peers = {peer["pc_id"]: peer for peer in federation.list_peers(str(Path(state.LIENZO) / "peers.json"))}
        ports = {self.peer_port}
        ports.update(
            peer["port"] for peer in peers.values() if type(peer.get("port")) is int and 0 < peer["port"] < 65536
        )
        with self.lock:
            previous = {row["node_id"]: row for row in self.rows}
        rows = []
        jobs = []
        for node in nodes:
            ips = [
                ip
                for ip in node.get("tailscaleIPs", [])
                if isinstance(ip, str) and ":" not in ip and red.es_tailscale(ip)
            ]
            row = {
                "node_id": node.get("id") or node.get("hostname"),
                "name": node.get("hostname"),
                "ips": ips,
                "online": node.get("online") is True,
                "lienzo": None,
                "paired": False,
                "connected": False,
            }
            old = previous.get(row["node_id"])
            if old:
                row.update({key: old[key] for key in ("lienzo", "paired", "connected")})
            rows.append(row)
            if node is not own_node and row["online"] and ips and snapshot.get("running"):
                jobs.append((row, ips))
            else:
                row["connected"] = False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda job: self._inspect(host, peers, ports, *job), jobs))
        for row, result in results:
            row.update(result)
        with self.lock:
            self.rows = rows
            self.total = snapshot.get("totalPeers", len(nodes) - bool(own_node)) + bool(own_node)
            self.truncated = snapshot.get("peersTruncated") is True

    def _inspect(self, host, peers, ports, row, ips):
        for ip in ips:
            for port in sorted(ports):
                if self.stop.is_set():
                    return row, {}
                found = probe(host, ip, port)
                if found is None:
                    continue
                pc_id = found["pc_id"]
                peer = peers.get(pc_id)
                result = {
                    "lienzo": {"pc_id": pc_id, "name": found["name"]},
                    "paired": peer is not None,
                    "connected": False,
                }
                if peer is not None:
                    with self.lock:
                        relay = self.relays.get(pc_id)
                        if (relay is None or relay.closed.is_set()) and time.monotonic() >= self.retry_at.get(pc_id, 0):
                            relay = Relay(host, self.board_port, peer, ip, state.log)
                            self.relays[pc_id] = relay
                            self.retry_at[pc_id] = time.monotonic() + 30
                            relay.start()
                        result["connected"] = relay is not None and relay.ready.is_set() and not relay.closed.is_set()
                return row, result
        return row, {"lienzo": None, "paired": False, "connected": False}

    def public(self):
        with self.lock:
            snapshot = self.host.snapshot() if self.host is not None else {}
            url = snapshot.get("browseToURL") or snapshot.get("authURL") or ""
            parsed = urlparse(url)
            # Sólo el enlace de login oficial; nunca URLs arbitrarias emitidas por un helper.
            login = url if parsed.scheme == "https" and parsed.hostname == "login.tailscale.com" else None
            return {
                "enabled": self.enabled,
                "hostname": hostname(),
                "running": bool(snapshot.get("running")),
                "needs_login": bool(snapshot.get("needsLogin")),
                "login_url": login,
                "error": self.error,
                "devices": [dict(row) for row in self.rows],
                "total": self.total,
                "truncated": self.truncated,
            }

    def _close_relays(self):
        with self.lock:
            relays = list(self.relays.values())
            self.relays.clear()
            for row in self.rows:
                row["connected"] = False
        for relay in relays:
            relay.close()

    def close(self):
        self.stop.set()
        self._close_relays()
        with self.lock:
            host = self.host
        if host is not None:
            host.close()


_service = None
_service_lock = threading.Lock()


def service(board_port, peer_port=7322):
    global _service
    with _service_lock:
        if _service is None:
            _service = Service(board_port, peer_port)
            atexit.register(_service.close)
        return _service
