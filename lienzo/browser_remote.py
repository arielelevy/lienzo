"""Chrome propio de Lienzo. El worker Node mantiene CDP en loopback; nunca se publica en la LAN."""

import atexit
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import state


def drenar_stderr(process, prefijo: str, limite: int = 8192) -> None:
    """Lee stderr del worker hasta que termina y registra como mucho `limite` caracteres (texto o
    bytes, segun como se abrio el pipe): el diagnostico de una caida sin llenar el log."""
    remaining = limite
    try:
        while line := process.stderr.readline(1024):
            if remaining > 0:
                excerpt = line[:remaining]
                if isinstance(excerpt, bytes):
                    excerpt = excerpt.decode("utf-8", "replace")
                remaining -= len(excerpt)
                state.log(f"{prefijo}: {excerpt.rstrip()}")
    except OSError, ValueError:
        pass  # El cierre del proceso tambien cierra el lector de diagnostico.


def cerrar_worker(process, timeout: float = 5) -> None:
    """Cierra stdin (el worker termina solo al quedarse sin pedidos), espera, mata si hace falta y
    cierra los tres pipes. Tolera solo los OSError de un pipe ya roto."""
    if process.poll() is None:
        try:
            process.stdin.close()  # Un pipe roto puede fallar tambien al hacer flush.
        except OSError:
            pass  # Igual se espera y termina solo este worker propio.
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass


class BrowserHost:
    def __init__(self, window=False):
        self.window = window
        self.lock = threading.Lock()
        self.process = None
        self.responses = queue.Queue()

    def _start(self):
        if self.window:
            if os.name != "nt":
                raise RuntimeError("La vista de ventana real requiere Windows en esa PC")
            command = [sys.executable, str(Path(__file__).with_name("browser_window.py"))]
        else:
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Instalá Node.js 24 o posterior en esta PC para usar Chrome remoto")
            command = [
                node,
                str(Path(__file__).with_name("browser_host.mjs")),
                str(Path(state.LIENZO) / "chrome-remoto"),
            ]
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        threading.Thread(target=self._read, args=(self.process, self.responses), daemon=True).start()
        threading.Thread(target=self._errors, args=(self.process,), daemon=True).start()

    @staticmethod
    def _errors(process):
        drenar_stderr(process, "Chrome worker")

    @staticmethod
    def _read(process, responses):
        try:
            for line in process.stdout:
                responses.put(json.loads(line))
        except (OSError, ValueError) as exc:
            responses.put({"status": 502, "error": f"Respuesta inválida del navegador: {type(exc).__name__}"})
        finally:
            responses.put({"status": 502, "error": "Se cerró el proceso de Chrome remoto"})

    def close(self):
        process = self.process
        self.process = None
        if process is not None:
            cerrar_worker(process)

    def request(self, data):
        if not isinstance(data, dict) or len(json.dumps(data)) > 65536:
            return 400, {"error": "Pedido de navegador inválido o demasiado grande"}
        if not self.lock.acquire(timeout=2):
            return 409, {"error": "Chrome está atendiendo otro pedido; esperá un momento"}
        try:
            if self.process is None or self.process.poll() is not None:
                self.close()
                if data.get("action") == "state":
                    return 200, {"running": False, "tabs": []}
                if self.window and data.get("action") == "window-release":
                    return 200, {"ok": True}
                if data.get("action") not in ("start", "profiles", "prepare", "connect", "windows") and not (
                    self.window and data.get("action") in ("window-frame", "window-input")
                ):
                    return 409, {"error": "Chrome está cerrado. Abrilo desde Chrome remoto"}
                self._start()
            self.process.stdin.write(json.dumps(data, ensure_ascii=True) + "\n")
            self.process.stdin.flush()
            result = self.responses.get(timeout=22)
            status = result.pop("status", 200)
            return status, result
        except queue.Empty:
            self.close()
            return 504, {"error": "Chrome no respondió a tiempo. El pedido no se reintentó"}
        except (OSError, RuntimeError) as exc:
            self.close()
            return 503, {"error": str(exc)}
        finally:
            self.lock.release()


HOST = BrowserHost()
WINDOW = BrowserHost(window=True)
FRAMES = BrowserHost(window=True)
atexit.register(HOST.close)
atexit.register(WINDOW.close)
atexit.register(FRAMES.close)


def request(data):
    if isinstance(data, dict) and data.get("action") == "window-frame":
        return FRAMES.request(data)
    if isinstance(data, dict) and data.get("action") in ("windows", "window-frame", "window-input", "window-release"):
        return WINDOW.request(data)
    return HOST.request(data)
