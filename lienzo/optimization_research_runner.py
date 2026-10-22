"""Proceso propio del investigador: cancelable, con plazo, salida acotada y sin tocar procesos ajenos.

`subproc.correr` espera bloqueado hasta el timeout; el investigador necesita además cortar ante
actividad del usuario, pausa, falta de memoria, cancelación explícita o salida excesiva. Este runner
sondea `should_stop` y, al cortar o vencer, mata el árbol del PID que lanzó ÉL MISMO
(`subproc._matar_arbol`). Un PID leído de disco tras un reinicio nunca se mata: el sistema puede
haberlo reutilizado para otro proceso.

La salida se lee por tuberías con un tope TOTAL (stdout + stderr) contado mientras el proceso corre:
al pasarlo, los lectores dejan de leer, el proceso queda trabado en su write y se mata su árbol. Nada
crece en disco ni en memoria más allá del tope más un bloque de lectura. La lección de subproc (un nieto
que retiene la tubería) se cubre con lectores en hilos daemon que nunca se esperan más de JOIN_SECONDS.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import subproc

POLL_SECONDS = 0.5
CHUNK = 65536
JOIN_SECONDS = 2
# prioridad baja: el investigador corre aunque haya agentes trabajando y no les quita CPU (Ariel, 2026-10-22)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)
NICE = 10


class _Output:
    """Bytes leídos de las dos tuberías con un tope compartido. Al pasarlo marca `exceeded`."""

    def __init__(self, limit: int):
        self.limit, self.used = limit, 0
        self.lock = threading.Lock()
        self.exceeded = threading.Event()
        self.parts = {"stdout": bytearray(), "stderr": bytearray()}

    def reader(self, name: str, pipe):
        try:
            while not self.exceeded.is_set():
                chunk = pipe.read1(CHUNK) if hasattr(pipe, "read1") else pipe.read(CHUNK)
                if not chunk:
                    return
                with self.lock:
                    room = self.limit - self.used
                    self.parts[name] += chunk[: max(0, room)]
                    self.used += min(len(chunk), max(0, room))
                    if len(chunk) > room:
                        self.exceeded.set()  # dejar de leer: el proceso se traba en su write
        except OSError, ValueError:
            return  # tubería cerrada al matar el árbol


def run(
    argv,
    *,
    stdin_text,
    cwd,
    timeout,
    should_stop,
    max_output,
    on_start=None,
    poll=POLL_SECONDS,
    env=None,
    env_remove=(),
):
    """Corre `argv` y devuelve code, stdout, stderr, seconds, stopped, timed_out, output_exceeded y pid.

    `stopped` es el motivo devuelto por `should_stop()` cuando cortó; `timed_out` marca el plazo;
    `output_exceeded` marca que stdout + stderr pasaron `max_output` bytes y se mató el árbol. Nunca
    levanta por el proceso: un fallo al lanzar devuelve `subproc.NO_ARRANCO`. `env_remove` quita variables
    heredadas (p. ej. una clave de API que cambiaría la suscripción por facturación)."""
    started = time.monotonic()
    extra = (
        {"creationflags": subproc.CREATE_NO_WINDOW | BELOW_NORMAL} if subproc.WINDOWS else {"start_new_session": True}
    )
    result = {
        "code": None,
        "stdout": "",
        "stderr": "",
        "seconds": 0.0,
        "stopped": None,
        "timed_out": False,
        "output_exceeded": False,
        "pid": None,
    }
    reason = should_stop()
    if reason:
        result.update(stopped=reason, seconds=round(time.monotonic() - started, 3))
        return result
    try:
        p = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env={
                k: v
                for k, v in {**os.environ, **subproc.ENV_SIN_PROMPTS, **(env or {})}.items()
                if k.upper() not in {name.upper() for name in env_remove}
            },
            **extra,
        )
    except OSError as error:
        result.update(code=subproc.NO_ARRANCO, stderr=f"no se pudo lanzar {argv[0]}: {type(error).__name__}")
        return result
    result["pid"] = p.pid
    if not subproc.WINDOWS:
        try:  # después de lanzar: preexec_fn no es seguro en un server con hilos
            os.setpriority(os.PRIO_PROCESS, p.pid, NICE)
        except OSError:
            pass
    output = _Output(max_output)
    readers = [
        threading.Thread(target=output.reader, args=(name, pipe), daemon=True)
        for name, pipe in (("stdout", p.stdout), ("stderr", p.stderr))
    ]
    for thread in readers:
        thread.start()
    threading.Thread(target=subproc._escribir, args=(p.stdin, stdin_text.encode("utf-8")), daemon=True).start()
    try:
        if on_start:
            on_start(p.pid)
        while p.poll() is None:
            if output.exceeded.is_set():
                result["output_exceeded"] = True
                break
            if time.monotonic() - started >= timeout:
                result["timed_out"] = True
                break
            reason = should_stop()
            if reason:
                result["stopped"] = reason
                break
            output.exceeded.wait(poll)  # despierta al instante si la salida pasa el tope
    except BaseException:
        subproc._matar_arbol(p)  # un error propio no deja huérfano el proceso que lanzamos
        raise
    if p.poll() is None:
        subproc._matar_arbol(p)
    result["code"] = subproc.VENCIDO if result["timed_out"] else p.returncode
    for thread in readers:
        thread.join(JOIN_SECONDS)
    result["output_exceeded"] = result["output_exceeded"] or output.exceeded.is_set()
    with output.lock:
        result["stdout"] = output.parts["stdout"].decode("utf-8", errors="replace")
        result["stderr"] = output.parts["stderr"].decode("utf-8", errors="replace")
    result["seconds"] = round(time.monotonic() - started, 3)
    if result["timed_out"]:
        result["stderr"] = (result["stderr"] + f"\nno terminó en {timeout:g} s: se mató el árbol propio").strip()
    if result["output_exceeded"]:
        result["stderr"] = (result["stderr"] + f"\nsalida mayor a {max_output} bytes: se mató el árbol propio").strip()
    return result
