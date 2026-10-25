"""Transporte JSONL persistente, acotado y cancelable del motor (AA)."""

from __future__ import annotations

import atexit
import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid

MAX_RESPUESTA = 8 * 1024 * 1024


class ErrorServicio(Exception):
    pass


class Servicio:
    def __init__(self, command, *, plazo=20, inactividad=120):
        self.command = command
        self.plazo = plazo
        self.proceso = None
        self._lock = threading.Lock()
        self._cola = None
        self._ultimo = 0
        self.inactividad = inactividad
        self._timer = None

    @staticmethod
    def _ofrecer(output, value):
        try:
            output.put(value, timeout=0.1)
            return True
        except queue.Full:
            return False  # dos respuestas pendientes ya acreditan un servidor fuera del protocolo

    @staticmethod
    def _leer(stream, output):
        try:
            while True:
                line = stream.readline(MAX_RESPUESTA + 1)
                if not line:
                    Servicio._ofrecer(output, ErrorServicio("el motor cerró stdout"))
                    return
                if len(line.encode("utf-8")) > MAX_RESPUESTA or not line.endswith("\n"):
                    Servicio._ofrecer(output, ErrorServicio("respuesta excesiva o incompleta"))
                    return
                if not Servicio._ofrecer(output, line):
                    return
        except UnicodeError:
            # lo que no es UTF-8 no lo escribió el motor: es el lanzador (wsl.exe sin la distro, o sin swipl)
            # contestando en la codificación de Windows (2026-10-25, ar-it33940)
            Servicio._ofrecer(
                output, ErrorServicio("el motor no está disponible: el lanzador respondió en vez de SWI-Prolog")
            )
        except (OSError, ValueError) as exc:
            Servicio._ofrecer(output, ErrorServicio(f"lectura del motor: {exc}"))

    def _iniciar(self):
        if self.proceso is not None and (self.proceso.poll() is not None or time.monotonic() - self._ultimo > 120):
            self._cerrar()
        if self.proceso is not None:
            return
        self.proceso = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        self._cola = queue.Queue(maxsize=2)
        threading.Thread(target=self._leer, args=(self.proceso.stdout, self._cola), daemon=True).start()

    def pedir(self, message, *, cancelar=lambda: False):
        if not self._lock.acquire(blocking=False):
            raise ErrorServicio("el motor persistente está ocupado")
        try:
            until = time.monotonic() + self.plazo
            if self._timer:
                self._timer.cancel()
            if cancelar():
                raise ErrorServicio("consulta cancelada")
            self._iniciar()
            rid = uuid.uuid4().hex
            data = json.dumps({**message, "request_id": rid}, ensure_ascii=True, allow_nan=False)
            if len(data.encode()) > 4 * 1024 * 1024:
                raise ErrorServicio("consulta mayor a 4 MiB")

            # Escribir también puede bloquear si el motor no drena stdin. El mismo deadline
            # cubre escritura y lectura; sólo el hilo escritor toca el stream mientras está activo.
            def write(proc, output):
                try:
                    proc.stdin.write(data + "\n")
                    proc.stdin.flush()
                except (OSError, ValueError) as exc:
                    self._ofrecer(output, ErrorServicio(f"escritura del motor: {exc}"))

            writer = threading.Thread(target=write, args=(self.proceso, self._cola), daemon=True)
            writer.start()
            while True:
                if cancelar():
                    raise ErrorServicio("consulta cancelada")
                if time.monotonic() >= until:
                    raise ErrorServicio("el motor excedió el plazo")
                try:
                    line = self._cola.get(timeout=min(0.05, max(0.001, until - time.monotonic())))
                except queue.Empty:
                    continue
                if isinstance(line, Exception):
                    raise line
                response = json.loads(line)
                if not isinstance(response, dict) or response.get("request_id") != rid:
                    raise ErrorServicio("request_id incorrecto en respuesta")
                if response.get("ok") is not True:
                    raise ErrorServicio(
                        f"{response.get('code', 'error_motor')}: {response.get('error', 'respuesta rechazada')}"
                    )
                self._ultimo = time.monotonic()
                self._timer = threading.Timer(self.inactividad, self.expirar)
                self._timer.daemon = True
                self._timer.start()
                return response
        except (OSError, ValueError, ErrorServicio) as exc:
            self._cerrar(abortar=True)
            raise ErrorServicio(str(exc)) from None
        finally:
            self._lock.release()

    def _cerrar(self, *, abortar=False):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        proc, self.proceso = self.proceso, None
        if proc is None:
            return
        if proc.poll() is None:
            if abortar:
                # Matar antes de close: close espera el lock de un stdin.write bloqueado.
                self._matar_arbol(proc)
            # EOF pide cierre limpio al bucle. Después, matar el árbol si no responde.
            if not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass  # proceso recogido; el pedido ya tiene un error visible
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                self._matar_arbol(proc)
        for stream in (proc.stdin, proc.stdout):
            if stream and not stream.closed:
                stream.close()

    @staticmethod
    def _matar_arbol(proc):
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
            )
            if result.returncode and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
                raise ErrorServicio(f"taskkill no pudo recoger el árbol: código {result.returncode}")
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)

    def cerrar(self):
        with self._lock:
            self._cerrar()

    def expirar(self):
        if not self._lock.acquire(blocking=False):
            return  # la consulta activa instalará su temporizador al terminar
        try:
            if time.monotonic() - self._ultimo >= self.inactividad:
                self._cerrar()
        finally:
            self._lock.release()


_instancia = None
_instancia_lock = threading.Lock()


def instancia():
    global _instancia
    import prolog_learning

    with _instancia_lock:
        if _instancia is None:
            command = prolog_learning.command()
            idx = command.index("-s") + 1
            command[idx] = (
                command[idx].rsplit("/", 1)[0] + "/servicio.pl"
                if prolog_learning.WSL
                else str(prolog_learning.ENGINE.with_name("servicio.pl"))
            )
            command[command.index("-g") + 1] = "servicio_main"
            _instancia = Servicio(command)
            atexit.register(_instancia.cerrar)
        return _instancia


def consultar(payload, *, archivos=None, cancelar=lambda: False, despertar=True):
    import prolog_learning

    if despertar:
        prolog_learning.despertar()
    response = instancia().pedir(
        {"contract": 4, "op": "query", "payload": payload, "archivos": archivos or []},
        cancelar=cancelar,
    )
    prolog_learning.respondio()
    return response["resultado"]
