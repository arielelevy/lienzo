"""Correr un programa externo sin que pueda colgar al server.

Una sola función, `correr`, para todo lo que el lienzo lanza y espera (git, powershell, tmux).
Junta las tres lecciones que estaban repartidas (revisión 2026-10-04, 0.5):

- La salida va a ARCHIVOS temporales, no a tuberías. Con una credencial de git vencida el Git
  Credential Manager queda vivo como nieto de git y retiene la tubería: `subprocess.run(timeout=)`
  mata a git pero la lectura sigue colgada para siempre (medido el 2026-10-03 en health; el mismo
  cuelgue estaba latente en secretos.leer_git_local). Un archivo no espera a nadie.
- Al vencer el plazo se mata el ÁRBOL (taskkill /T /F en Windows, el grupo de procesos en el
  resto), no solo el hijo: el nieto es justamente el que retiene.
- Sin stdin heredado (DEVNULL): un proceso sin consola heredable hace fallar el DuplicateHandle con
  WinError 50 (medido en health con powershell). Y sin ventana (CREATE_NO_WINDOW).

Nunca levanta TimeoutExpired ni OSError: devuelve un código distinto de cero y el motivo en stderr.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading

WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VENCIDO = 124  # como `timeout` de coreutils: se mató el árbol porque no terminó a tiempo
NO_ARRANCO = 127  # como la shell con un comando que no existe: OSError al lanzar

# Lo que evita que git (o el Git Credential Manager) abra una ventana de login o pregunte por
# consola: en un server sin nadie mirando, una pregunta es un cuelgue.
ENV_SIN_PROMPTS = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def _matar_arbol(p: subprocess.Popen) -> None:
    """Mata `p` y todo lo que lanzó. Nunca levanta: si ya terminó, no hay nada que matar."""
    if WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError, subprocess.SubprocessError:
            pass
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)  # arrancó con start_new_session: su grupo es su pid
        except OSError:
            pass
    try:
        p.kill()
    except OSError:
        pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass  # no se espera más: el código de salida ya es VENCIDO


def _escribir(stdin, datos: bytes) -> None:
    try:
        stdin.write(datos)
    except OSError:
        pass  # el programa terminó o cerró su entrada sin leerla: no es asunto nuestro
    finally:
        try:
            stdin.close()
        except OSError:
            pass


def correr(
    argv: list[str],
    *,
    entrada: str | None = None,
    timeout: float,
    sin_prompts: bool = False,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """(código de salida, stdout, stderr) como texto UTF-8 (lo ilegible se reemplaza).

    `entrada` va por una tubería que escribe un hilo aparte y no por un archivo temporal: suele ser
    un secreto (`git credential approve` lleva la contraseña) y los secretos del lienzo no tocan
    disco (secretos.py). Escribir no cuelga como leer: si el programa no la lee, el hilo queda
    trabado en un write que muere con el proceso al vencer el plazo.

    Al vencer `timeout` mata el árbol y devuelve (VENCIDO, lo que haya salido, motivo). Si el
    programa no existe o no se puede lanzar, (NO_ARRANCO, "", motivo)."""
    entorno = {**os.environ, **(env or {}), **(ENV_SIN_PROMPTS if sin_prompts else {})}
    extra = {"creationflags": CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE if entrada is not None else subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=entorno,
                **extra,
            )
        except OSError as e:
            return NO_ARRANCO, "", f"no se pudo lanzar {argv[0]}: {type(e).__name__}: {e}"
        if entrada is not None:
            threading.Thread(target=_escribir, args=(p.stdin, entrada.encode("utf-8")), daemon=True).start()
        try:
            rc = p.wait(timeout=timeout)
            motivo = ""
        except subprocess.TimeoutExpired:
            _matar_arbol(p)
            rc, motivo = VENCIDO, f"{argv[0]} no termino en {timeout:g} s: se mato el arbol de procesos"

        def leer(f) -> str:
            f.seek(0)
            return f.read().decode("utf-8", errors="replace")

        stdout, stderr = leer(out), leer(err)
    if motivo:
        stderr = (stderr + "\n" + motivo).strip()
    return rc, stdout, stderr
