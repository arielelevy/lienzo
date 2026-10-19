"""Cliente del helper instalado de Tailchrome, sin copiar ni modificar su binario.

Usa un perfil propio de Lienzo. Las credenciales del proxy viajan por pipes y sólo
se conservan en memoria; nunca se extraen del proceso o del perfil de Chrome.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import struct
import subprocess
import threading
from pathlib import Path

HOST_NAME = "com.tailscale.browserext.chrome"
MAX_NATIVE = 1024 * 1024


def installed_helper() -> str:
    if os.name != "nt":
        raise RuntimeError("la detección del helper de Tailchrome requiere Windows")
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for browser in ("Google\\Chrome", "Microsoft\\Edge"):
            key = f"Software\\{browser}\\NativeMessagingHosts\\{HOST_NAME}"
            try:
                with winreg.OpenKey(hive, key) as registry:
                    manifest_path = winreg.QueryValue(registry, None)
            except FileNotFoundError:
                continue
            with open(manifest_path, encoding="utf-8-sig") as file:
                manifest = json.load(file)
            if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
                raise RuntimeError("el registro del helper de Tailchrome no contiene un ejecutable")  # noqa: TRY004
            path = Path(manifest["path"])
            if manifest.get("name") != HOST_NAME or not path.is_absolute() or not path.is_file():
                raise RuntimeError("el registro del helper de Tailchrome es inválido")
            return str(path)
    raise RuntimeError("no se encontró el helper instalado de Tailchrome para Chrome o Edge")


def read_message(stream):
    prefix = stream.read(4)
    if not prefix:
        raise EOFError("el helper de Tailchrome terminó")
    if len(prefix) != 4:
        raise ValueError("cabecera incompleta del helper")
    size = struct.unpack("<I", prefix)[0]
    if not 0 < size <= MAX_NATIVE:
        raise ValueError("mensaje del helper fuera de límite")
    raw = stream.read(size)
    if len(raw) != size:
        raise ValueError("mensaje incompleto del helper")
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise ValueError("mensaje inválido del helper")  # noqa: TRY004 - protocolo remoto
    return message


class Host:
    def __init__(self, profile: str, executable=None):
        self.profile = profile
        self.executable = executable
        self.process = None
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.proc_ready = threading.Event()
        self.init_ready = threading.Event()
        self.dead = threading.Event()
        self.proxy = None
        self.status = {}
        self.error = None
        self.closing = False
        self.reader = None

    def start(self):
        executable = self.executable or installed_helper()
        with self.write_lock:
            if self.dead.is_set():
                raise RuntimeError("se canceló el arranque del helper")
            self.process = subprocess.Popen(
                [executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.proc_ready.wait(10) or self.error or self.dead.is_set():
            raise RuntimeError(self.error or "el helper no publicó el proxy")
        self.send({"cmd": "init", "initID": self.profile, "wantRunning": True})
        if not self.init_ready.wait(30) or self.error or self.dead.is_set():
            raise RuntimeError(self.error or "el helper no inicializó el perfil de Lienzo")

    def send(self, message):
        raw = json.dumps(message).encode("utf-8")
        with self.write_lock:
            if self.process is None or self.dead.is_set():
                raise RuntimeError("el helper no está activo")
            self.process.stdin.write(struct.pack("<I", len(raw)) + raw)
            self.process.stdin.flush()

    def _read(self):
        try:
            while True:
                message = read_message(self.process.stdout)
                with self.lock:
                    cmd = message.get("cmd")
                    if cmd == "procRunning":
                        proxy = message.get("procRunning") or {}
                        auth = proxy.get("proxyAuth") or {}
                        port = proxy.get("port")
                        if (
                            proxy.get("error")
                            or type(port) is not int
                            or not 0 < port < 65536
                            or auth.get("version") != 1
                            or not auth.get("username")
                            or not auth.get("password")
                        ):
                            raise RuntimeError("el helper requiere una versión con proxy autenticado")
                        self.proxy = (port, auth["username"], auth["password"])
                        self.proc_ready.set()
                    elif cmd == "init":
                        if (message.get("init") or {}).get("error"):
                            raise RuntimeError("el helper rechazó el perfil de Lienzo")
                        self.init_ready.set()
                    elif cmd == "status":
                        self.status = message.get("status") or {}
                    elif cmd == "error":
                        raise RuntimeError("el helper informó un error de protocolo; revisá su conexión")
        except (OSError, EOFError, ValueError, RuntimeError) as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            self.dead.set()
            self.proc_ready.set()
            self.init_ready.set()

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def tunnel(self, host: str, port: int, timeout=5) -> socket.socket:
        with self.lock:
            proxy = self.proxy
        if proxy is None or self.dead.is_set():
            raise RuntimeError("el proxy de Tailchrome no está disponible")
        proxy_port, username, password = proxy
        credential = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        connection = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=timeout)
        connection.set_tunnel(host, port, {"Proxy-Authorization": "Basic " + credential})
        try:
            connection.connect()
            sock = connection.sock
            connection.sock = None
            return sock
        finally:
            connection.close()

    def close(self):
        with self.write_lock:
            if self.closing:
                return
            self.closing = True
            self.dead.set()
            process = self.process
            if process is not None:
                try:
                    process.stdin.close()  # EOF cierra el nodo y su proxy en Tailchrome
                except OSError:
                    pass  # el proceso puede haber terminado antes
        if process is not None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if self.reader is not None:
                self.reader.join(1)
            process.stdout.close()
        self.dead.set()
        self.proc_ready.set()
        self.init_ready.set()
        with self.lock:
            self.proxy = None
