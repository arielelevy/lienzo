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
            command = [node, str(Path(__file__).with_name("browser_host.mjs")), str(Path(state.LIENZO) / "chrome-remoto")]
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        threading.Thread(target=self._read, args=(self.process, self.responses), daemon=True).start()

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
        if self.process is not None:
            if self.process.poll() is None:
                self.process.stdin.close()  # EOF: el worker cierra solamente su Chrome.
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process.stdout.close()
            self.process = None

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
                if data.get("action") not in ("start", "profiles", "prepare", "connect", "windows"):
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
atexit.register(HOST.close)
atexit.register(WINDOW.close)


def request(data):
    if isinstance(data, dict) and data.get("action") in ("windows", "window-frame", "window-input", "window-release"):
        return WINDOW.request(data)
    return HOST.request(data)
