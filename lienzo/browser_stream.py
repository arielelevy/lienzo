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

import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import browser_remote
import federation
import identity
import mirror
import secretos
import state
import ws

MAX_SESSIONS = 4  # vistas abiertas a la vez en esta PC (cada una es un worker capturando)
MAX_COMMAND = 65536
RECORD = struct.Struct(">IB")  # largo (tipo + carga) y tipo: J json, F cuadro
TAB_FRAME = struct.Struct(">IIHH")  # generacion, secuencia, ancho, alto; sigue JPEG completo
# El host espera el próximo cuadro del screencast (hasta 0,5 s): el tope sólo frena una página muy animada.
TAB_MIN_INTERVAL = 1 / 30
_tab_owners = {}
_tab_lock = threading.Condition()  # avisa cuando una pestaña queda libre (reconexión rápida)
_sessions = 0
_sessions_lock = threading.Lock()


def channel_key(pair_key: bytes, sid: str, mode="window") -> bytes:
    context = b"lienzo/chrome-tabs-stream/v1/" if mode == "tabs" else b"lienzo/chrome-stream/v1/"
    return hmac.new(pair_key, context + sid.encode("ascii"), hashlib.sha256).digest()


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
        browser_remote.drenar_stderr(self.process, "Chrome stream")

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
        except OSError, ValueError, ConnectionError:
            pass  # el visor se fue o el pipe se cerro: se termina igual
        finally:
            try:
                self.deliver(ws.TEXT, _error("Se cerró el worker de Chrome en esa PC"))
            except OSError, ValueError, ConnectionError:
                pass
            self.on_exit()

    def send(self, line: bytes) -> None:
        with self.lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()

    def close(self) -> None:
        with self.lock:
            browser_remote.cerrar_worker(self.process, timeout=3)


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


def _hover_input(data):
    if data.get("t") != "input" or not data.get("events"):
        return False
    for event in data["events"]:
        if not isinstance(event, dict) or (
            event.get("kind"),
            event.get("type"),
            event.get("button"),
            event.get("buttons"),
            event.get("clickCount"),
        ) != ("mouse", "mouseMoved", "none", 0, 0):
            return False
        for name, maximum in (("x", 3840), ("y", 2160), ("modifiers", 15), ("buttons", 0), ("clickCount", 0)):
            if type(event.get(name)) is not int or not 0 <= event[name] <= maximum:
                return False
    return True


class _InputQueue(queue.Queue):
    """Sólo reemplaza hover consecutivo aún no despachado; el resto conserva FIFO."""

    def put_latest(self, data):
        with self.not_full:
            previous = self.queue[-1] if self.queue else None
            if (
                previous
                and _hover_input(data)
                and _hover_input(previous)
                and (
                    data["generation"] == previous["generation"]
                    and data["n"] > previous["n"]
                    and data.get("basis") == previous.get("basis")
                    and len({e["modifiers"] for e in data["events"] + previous["events"]}) == 1
                )
            ):
                self.queue[-1] = data
                return previous
            if self.maxsize > 0 and self._qsize() >= self.maxsize:
                raise queue.Full
            self._put(data)
            self.unfinished_tasks += 1
            self.not_empty.notify()
        return None


class TabWorker:
    """Una suscripción al HOST existente. Captura, metadata e input no comparten espera CDP."""

    def __init__(self, deliver, on_exit):
        self.deliver, self.on_exit = deliver, on_exit
        self.cv = threading.Condition()
        self.selection_lock = threading.RLock()
        self.closed = False
        self.paused = False
        self.viewer_paused = False
        self.target = None
        self.generation = 0
        self.width, self.height = 1280, 800
        self.seq = 0
        self.awaiting = None
        self.commands = _InputQueue(maxsize=64)
        self.last_image = None
        self.capture_error = False
        self.dialog_wait = False
        self.last_state_error = None
        self.pressed = {}  # releases de downs propios aceptados o de resultado incierto
        self.remaining = 3
        self.release_finished = False
        self.threads = [
            threading.Thread(target=self._run, args=(fn,), daemon=True)
            for fn in (self._capture, self._metadata, self._inputs)
        ]
        for thread in self.threads:
            thread.start()

    def json(self, data):
        self.deliver(ws.TEXT, json.dumps(data, ensure_ascii=True).encode("ascii"))

    def _run(self, function):
        try:
            function()
        except Exception as exc:
            state.log(f"Chrome tabs: {type(exc).__name__}: {exc}")
            self.close()
            self.on_exit()
        finally:
            with self.cv:
                self.remaining -= 1
            self._cleanup_owner()

    def _cleanup_owner(self):
        with self.cv:
            done = self.remaining == 0 and self.release_finished
        if done:
            with _tab_lock:
                for key in [key for key, owner in _tab_owners.items() if owner is self]:
                    del _tab_owners[key]
                _tab_lock.notify_all()

    @staticmethod
    def bounded(value, low, high):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Valor fuera de rango")
        return value

    def send(self, line):
        data = json.loads(line)
        if data.get("t") in ("open", "size", "input", "release-input"):
            if data["t"] not in ("open", "size"):
                self.bounded(data.get("n"), 1, 2**53 - 1)
                self.bounded(data.get("generation"), 1, 0xFFFFFFFF)
            if data["t"] == "input" and (
                not isinstance(data.get("events"), list) or not 1 <= len(data["events"]) <= 64
            ):
                raise ValueError("Entrada inválida")
            try:
                previous = self.commands.put_latest(data)
                if previous is not None:
                    self.json(
                        {
                            "t": "input",
                            "n": previous["n"],
                            "generation": previous["generation"],
                            "outcome": "superseded",
                        }
                    )
            except queue.Full:
                self.json(
                    {
                        "t": "error",
                        "input": data["t"] != "open",
                        "n": data.get("n"),
                        "generation": data.get("generation"),
                        "outcome": "rejected",
                        "message": "La entrada no sigue el ritmo; no se reintentó",
                    }
                )
            return
        with self.selection_lock:
            self._send(line)

    def _send(self, line):
        data = json.loads(line)
        kind = data.get("t")
        if kind == "open":
            generation = self.bounded(data.get("generation"), 1, 0xFFFFFFFF)
            width = self.bounded(data.get("width"), 320, 1920)
            height = self.bounded(data.get("height"), 240, 1080)
            target = data.get("tab")
            if not isinstance(target, str) or not 1 <= len(target) <= 256:
                raise ValueError("Pestaña inválida")
            with self.cv:
                if generation <= self.generation:
                    raise ValueError("Generación de pestaña vencida")
            with _tab_lock:
                if _tab_owners.get(target) not in (None, self):
                    raise ValueError("La pestaña ya tiene un visor abierto")
            code, result = self._release_locked()
            if code != 200:
                self.json(
                    {
                        "t": "error",
                        "generation": generation,
                        "message": "No se pudo confirmar la liberación de entrada: " + result.get("error", "error CDP"),
                    }
                )
                return
            with self.cv:
                # Invalidar antes de esperar viewport: una captura anterior no puede publicarse.
                previous = self.target
                self.generation = generation
                self.paused = True
                self.target = None
                self.awaiting = None
            with _tab_lock:
                owner = _tab_owners.get(target)
                taken = owner is not None and owner is not self
                if not taken:
                    # la anterior vuelve a su tamaño antes de soltar su propiedad: otro visor no la ajusta en el medio
                    if previous and previous != target:
                        self._unfit(previous)
                    for key in [key for key, owner in _tab_owners.items() if owner is self]:
                        del _tab_owners[key]
                    _tab_owners[target] = self
                    _tab_lock.notify_all()
            if taken:
                # el cambio no se hizo: la anterior sigue propia pero sin visor; vuelve a su tamaño
                if previous:
                    self._unfit(previous)
                raise ValueError("La pestaña ya tiene un visor abierto")
            code, result = browser_remote.HOST.request(
                {"action": "viewport", "tab": target, "width": width, "height": height, "fit": True}
            )
            if code != 200:
                self._unfit(target)
                self.json(
                    {
                        "t": "error",
                        "generation": generation,
                        "message": result.get("error", "No se pudo abrir la pestaña"),
                    }
                )
                return
            with self.cv:
                if self.closed:
                    return
                self.target, self.width, self.height = target, width, height
                self.capture_error = False
                self.dialog_wait = False
                self.last_image = None
            # el tamaño CSS real de la pestaña (existing) o el emulado (lienzo): sobre él se mapea la entrada
            css_width, css_height = self._css(result, width, height)
            self.json(
                {
                    "t": "opened",
                    "tab": target,
                    "generation": generation,
                    "width": css_width,
                    "height": css_height,
                    "format": "jpeg",
                }
            )
            with self.cv:
                self.paused = self.viewer_paused
                self.cv.notify_all()
        elif kind == "ack":
            self.bounded(data.get("generation"), 1, 0xFFFFFFFF)
            self.bounded(data.get("n"), 1, 0xFFFFFFFF)
            with self.cv:
                if self.awaiting == (data.get("generation"), data.get("n")):
                    self.awaiting = None
                    self.cv.notify_all()
        elif kind in ("pause", "resume"):
            with self.cv:
                self.viewer_paused = kind == "pause"
                self.paused = self.viewer_paused
                if kind == "resume":
                    self.capture_error = False
                    self.last_image = None
                self.cv.notify_all()
        elif kind == "release":
            self.close()
        else:
            raise ValueError("Pedido de pestaña desconocido")

    def _wait_owner(self, target, timeout=10.0):
        """Un visor vivo sigue siendo exclusivo; uno ya cerrado que termina su captura o su liberación en vuelo se
        espera: la UI reconecta enseguida y antes recibía «ya tiene un visor abierto». El plazo cubre los 8 s de una
        espera CDP del visor viejo. Se llama sin selection_lock: un close() del visor nuevo no queda esperando."""
        deadline = time.monotonic() + timeout
        live_deadline = time.monotonic() + 1.0
        with _tab_lock:
            while not self.closed:
                owner = _tab_owners.get(target)
                if owner is None or owner is self:
                    return
                # un visor vivo puede ser el viejo de esta misma UI cuyo cierre todavía no llegó: se le da 1 s
                left = deadline - time.monotonic() if owner.closed else live_deadline - time.monotonic()
                if left <= 0:
                    return  # _send rechaza: la pestaña tiene otro visor
                _tab_lock.wait(min(left, 0.5))

    def _css(self, result, width, height):
        css_width, css_height = result.get("width", width), result.get("height", height)
        self.bounded(css_width, 1, 3840)
        self.bounded(css_height, 1, 2160)
        return css_width, css_height

    @staticmethod
    def _unfit(target):
        """La pestaña vuelve a su tamaño real. Sin efecto si este visor nunca la ajustó o si ya no existe."""
        code, result = browser_remote.HOST.request({"action": "unfit", "tab": target})
        if code != 200:
            state.log(f"Chrome tabs: no se pudo devolver la pestaña a su tamaño: {result.get('error', code)}")

    def _size(self, data):
        """El visor cambió de tamaño: sin open, sin release y sin generación nueva. La pestaña toma el tamaño
        CSS nuevo del visor (existing con fit y lienzo); el host no vuelve a emular un tamaño repetido."""
        width = self.bounded(data.get("width"), 320, 1920)
        height = self.bounded(data.get("height"), 240, 1080)
        with self.cv:
            target = self.target
            if not target or data.get("generation") != self.generation:
                return
        code, result = browser_remote.HOST.request(
            {"action": "viewport", "tab": target, "width": width, "height": height, "fit": True}
        )
        if code != 200:
            self.json(
                {
                    "t": "error",
                    "generation": data["generation"],
                    "message": result.get("error", "No se pudo cambiar el tamaño"),
                }
            )
            return
        with self.cv:
            if target == self.target and data["generation"] == self.generation:
                self.width, self.height = width, height
                self.last_image = None
                self.cv.notify_all()

    def _inputs(self):
        last_n = 0
        while not self.closed:
            try:
                data = self.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            if data["t"] == "open" and isinstance(data.get("tab"), str):
                self._wait_owner(data["tab"])
            with self.selection_lock:
                if self.closed:
                    return
                if data["t"] in ("open", "size"):
                    try:
                        self._send(json.dumps(data)) if data["t"] == "open" else self._size(data)
                    except ValueError as exc:
                        self.json({"t": "error", "generation": data.get("generation"), "message": str(exc)})
                    continue
                with self.cv:
                    target, generation = self.target, self.generation
                    fresh = data["n"] > last_n
                    valid = target and data["generation"] == generation and fresh and not self.closed
                    last_n = max(last_n, data["n"])
                if valid:
                    if data["t"] == "release-input":
                        code, result = self._release_locked()
                    else:
                        candidates = set()
                        for event in data["events"]:
                            if (
                                isinstance(event, dict)
                                and event.get("type") == "keyDown"
                                and isinstance(event.get("code"), str)
                                and isinstance(event.get("key"), str)
                            ):
                                candidates.add(("key", event["code"], event["key"]))
                            elif (
                                isinstance(event, dict)
                                and event.get("type") == "mousePressed"
                                and isinstance(event.get("button"), str)
                            ):
                                candidates.add(("mouse", event["button"]))
                        if len(set(self.pressed) | candidates) > 128:
                            code, result = (
                                409,
                                {"error": "Demasiadas teclas presionadas; liberá la entrada antes de continuar"},
                            )
                        else:
                            basis = data.get("basis")
                            code, result = browser_remote.HOST.request(
                                {
                                    "action": "input",
                                    "tab": target,
                                    "events": data["events"],
                                    # el tamaño del cuadro sobre el que se mapeó: el host rechaza si cambió
                                    **({"basis": basis} if basis is not None else {}),
                                }
                            )
                        if code == 200 or code >= 500:
                            self._track(data["events"], uncertain=code != 200)
                elif data["t"] == "release-input" and not self.pressed and fresh:
                    # nada propio apretado: soltar no manda nada (p. ej. foco perdido con un open fallido)
                    code, result = 200, {"ok": True}
                else:
                    code, result = 409, {"error": "Entrada de una selección vencida o repetida; no se envió"}
            reply = {"n": data["n"], "generation": data["generation"]}
            try:
                if code == 200:
                    self.json({"t": "input", **reply})
                else:
                    self.json(
                        {
                            "t": "error",
                            "input": True,
                            **reply,
                            "outcome": "uncertain" if valid and code >= 500 else "rejected",
                            "message": result.get("error", "No se pudo enviar la entrada"),
                        }
                    )
            except OSError, ValueError, ConnectionError:
                self.close()
                self.on_exit()

    def _track(self, events, uncertain):
        for event in events:
            if not isinstance(event, dict):
                continue
            kind, action = event.get("kind"), event.get("type")
            if kind == "key" and action in ("keyDown", "keyUp"):
                key = ("key", event.get("code"), event.get("key"))
                if action == "keyDown":
                    self.pressed[key] = {**event, "type": "keyUp", "modifiers": 0}
                elif not uncertain:
                    self.pressed.pop(key, None)
            elif kind == "mouse" and action in ("mousePressed", "mouseReleased"):
                key = ("mouse", event.get("button"))
                if action == "mousePressed":
                    self.pressed[key] = {
                        **event,
                        "type": "mouseReleased",
                        "buttons": 0,
                        "modifiers": 0,
                        "clickCount": 0,
                    }
                elif not uncertain:
                    self.pressed.pop(key, None)
            elif kind == "mouse" and action == "mouseMoved":
                for key, release in self.pressed.items():
                    if key[0] == "mouse":
                        release.update(x=event["x"], y=event["y"], clickCount=0)

    def _release_locked(self):
        if not self.pressed:
            return 200, {"ok": True}
        items = list(self.pressed.items())
        for offset in range(0, len(items), 64):
            batch = items[offset : offset + 64]
            result = browser_remote.HOST.request(
                {"action": "release-input", "tab": self.target, "events": [event for _, event in batch]}
            )
            if result[0] != 200:
                return result
            for key, _ in batch:
                self.pressed.pop(key, None)
        return 200, {"ok": True}

    def _capture(self):
        while True:
            with self.cv:
                self.cv.wait_for(
                    lambda: (
                        self.closed
                        or (self.target and not self.paused and not self.capture_error and self.awaiting is None)
                    )
                )
                if self.closed:
                    return
                target, generation, width, height = self.target, self.generation, self.width, self.height
            started = time.monotonic()
            code, result = browser_remote.HOST.request(
                {"action": "snapshot", "tab": target, "width": width, "height": height}
            )
            try:
                if code != 200:
                    raise ValueError(result.get("error", "Falló la captura"))
                if result.get("dialog"):
                    with self.cv:
                        if generation == self.generation:
                            self.capture_error = True
                            self.dialog_wait = True
                    self.json({"t": "state", "generation": generation, **result})
                    continue
                image = base64.b64decode(result["image"], validate=True)
                if not 1 <= len(image) <= 4 * 1024 * 1024:
                    raise ValueError("La captura supera el límite de 4 MiB")
                with self.cv:
                    if self.closed or generation != self.generation or self.paused:
                        continue
                    if image != self.last_image:
                        self.seq += 1
                        self.awaiting = (generation, self.seq)
                        self.last_image = image
                        packet = TAB_FRAME.pack(generation, self.seq, *self._css(result, width, height)) + image
                    else:
                        packet = None
                if packet is not None:
                    self.deliver(ws.BINARY, packet)
            except (KeyError, ValueError) as exc:
                with self.cv:
                    if generation != self.generation or self.closed:
                        continue
                    self.capture_error = True
                try:
                    self.json({"t": "error", "generation": generation, "message": str(exc)})
                except OSError, ConnectionError:
                    self.close()
                    self.on_exit()
            except OSError, ConnectionError:
                self.close()
                self.on_exit()
            with self.cv:
                self.cv.wait_for(
                    lambda generation=generation: self.closed or generation != self.generation,
                    timeout=max(0, TAB_MIN_INTERVAL - (time.monotonic() - started)),
                )

    def _metadata(self):
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.closed or (self.target and not self.paused))
                if self.closed:
                    return
                target, generation = self.target, self.generation
            code, result = browser_remote.HOST.request({"action": "tab-state", "tab": target})
            try:
                with self.cv:
                    current = not self.closed and generation == self.generation
                    if current and code == 200 and self.dialog_wait and not result.get("dialog"):
                        self.dialog_wait = False
                        self.capture_error = False
                        self.cv.notify_all()
                if current:
                    if code == 200:
                        self.last_state_error = None
                        self.json({"t": "state", "generation": generation, **result})
                    else:
                        message = result.get("error", "Falló el estado de la pestaña")
                        if self.last_state_error != (generation, message):
                            self.last_state_error = (generation, message)
                            self.json({"t": "error", "generation": generation, "message": message})
                # El estado (historial, diálogo, pestaña oculta) se consulta cada 2 s, aparte de los cuadros.
                with self.cv:
                    self.cv.wait_for(
                        lambda generation=generation: self.closed or generation != self.generation, timeout=2
                    )
            except OSError, ValueError, ConnectionError:
                self.close()
                self.on_exit()

    def close(self):
        # La propiedad se libera cuando terminan los tres trabajos, no durante una captura/input.
        with self.selection_lock, self.cv:
            if self.closed:
                return
            self.closed = True
            self.cv.notify_all()
        with self.selection_lock:
            try:
                code, result = self._release_locked()
                if code != 200:
                    message = "No se pudo confirmar la liberación de entrada al cerrar: " + result.get(
                        "error", "error CDP"
                    )
                    state.log(message)
                    try:
                        self.json({"t": "error", "generation": self.generation, "message": message})
                    except OSError, ValueError, ConnectionError:
                        state.log("Chrome tabs: el visor se cerró antes de recibir el error de liberación")
                # visor cerrado, desconectado o caído: la pestaña vuelve a su tamaño en esa PC
                if self.target:
                    self._unfit(self.target)
            finally:
                with self.cv:
                    self.release_finished = True
                self._cleanup_owner()

    def wait_closed(self):
        deadline = time.monotonic() + 23
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            state.log("Chrome tabs: quedaron trabajos pendientes al cerrar el visor")


def _run_worker(sock: ws.Socket, deliver, incoming, mode="window"):
    """Vida de una sesion con worker propio: `incoming()` da el proximo pedido (bytes de JSON) o
    None al cerrar; `deliver` lleva lo del worker al visor."""
    if not _reserve():
        deliver(ws.TEXT, _error("Hay demasiadas vistas de Chrome abiertas en esa PC"))
        return
    try:
        worker = TabWorker(deliver, sock.close) if mode == "tabs" else Worker(deliver, sock.close)
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
        if isinstance(worker, TabWorker):
            worker.wait_closed()
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
        except OSError, ValueError, ConnectionError:
            return None
        if msg is None or msg[0] == ws.TEXT:
            return msg[1] if msg else None


def serve_viewer(handler, pc: str, mode="window") -> None:
    """GET /browser/stream?pc=… del tablero (ya autenticado y local). Toma el socket."""
    sock = ws.server_handshake(handler)
    if sock is None:
        return
    try:
        sock.pings()  # un visor quieto (nada cambia, nadie toca) no tiene que vencer el timeout del socket
        if not pc:
            sock.send(ws.TEXT, _error("Elegí la PC donde querés ver Chrome"))
        elif mode not in ("window", "tabs"):
            sock.send(ws.TEXT, _error("Modo de Chrome remoto inválido"))
        elif pc == identity.pc_id():
            _run_worker(sock, sock.send, lambda: _recv_text(sock), mode)
        else:
            _relay(sock, pc, mode)
    except (OSError, ValueError, ConnectionError) as exc:
        state.log(f"Chrome stream: {type(exc).__name__}: {exc}")
    finally:
        sock.close()


def _relay(sock: ws.Socket, pc: str, mode="window") -> None:
    conn = mirror.MIRROR.conn_of(pc)
    if conn is None:
        sock.send(ws.TEXT, _error("La PC elegida no está emparejada"))
        return
    capability = "browser.tabs.stream.v1" if mode == "tabs" else "browser.stream"
    supported = mirror.MIRROR.supports(pc, capability)
    if supported is False or (mode == "tabs" and supported is not True):
        sock.send(ws.TEXT, _error("Actualizá y reiniciá Lienzo en la otra PC para ver su Chrome en vivo"))
        return
    sid = secrets.token_hex(16)
    # El modo queda en el path firmado; la verificacion peer no autentica query strings.
    path = f"/peer/browser/stream/tabs/{sid}" if mode == "tabs" else f"/peer/browser/stream/{sid}"
    try:
        peer = ws.client_connect(conn.host, conn.port, path, federation.signed_headers(conn, "GET", path, b""))
    except (OSError, ConnectionError) as exc:
        sock.send(ws.TEXT, _error(f"No se pudo abrir el canal con la otra PC: {exc}"))
        return
    sealed = Sealed(channel_key(conn.key, sid, mode), b">", b"<")
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
            except OSError, ValueError, ConnectionError:
                pass
        finally:
            sock.close()

    threading.Thread(target=pump, daemon=True).start()
    try:
        while (payload := _recv_text(sock)) is not None:
            sealed.seal(peer, ws.TEXT, payload)
    finally:
        peer.close()


def serve_peer(handler, pair_key: bytes | None, sid: str, mode="window") -> None:
    """GET /peer/browser/stream/<sid> firmado por la otra PC: el worker vive aca."""
    if (
        pair_key is None
        or mode not in ("window", "tabs")
        or len(sid) != 32
        or not all(c in "0123456789abcdef" for c in sid)
    ):
        handler._json(400, {"error": "canal invalido"})
        return
    sock = ws.server_handshake(handler)
    if sock is None:
        return
    sealed = Sealed(channel_key(pair_key, sid, mode), b"<", b">")

    def incoming():
        while True:
            try:
                msg = sock.recv()
                if msg is None:
                    return None
                if msg[0] != ws.BINARY:
                    continue
                kind, payload = sealed.open(msg[1])
            except OSError, ValueError, ConnectionError:
                return None
            if kind == ws.TEXT:
                return payload

    try:
        _run_worker(sock, lambda kind, payload: sealed.seal(sock, kind, payload), incoming, mode)
    except (OSError, ValueError, ConnectionError) as exc:
        state.log(f"Chrome stream (peer): {type(exc).__name__}: {exc}")
    finally:
        sock.close()
