"""Escritura atomica de un archivo de texto, la UNICA del lienzo (state, auth y hook la comparten).

Modulo hoja y liviano a proposito: solo os, time y _thread (que viene compilado en el interprete),
nada del lienzo. Lo importa hook.py, que arranca como subproceso en cada evento de un agente y no
puede arrastrar state.py (ver hook.py); por eso tampoco usa `threading`, que cuesta ~1,5 ms de import.

Se llama atomico.py y no _io.py como decia el plan: `_io` es un modulo que viene compilado en
CPython (sys.builtin_module_names) y con lienzo/ en sys.path (server.py, auth.py, las pruebas) un
`import _io` trae el de Python, no este.
"""

from __future__ import annotations

import os
import time
from _thread import get_ident

REINTENTOS = 5


def atomic_write(path: str, text: str) -> None:
    """Escribe `text` (UTF-8) en un .tmp y lo cambia por `path` de un saque.

    El .tmp lleva el pid y el id del hilo: dos hilos que guardan la misma tarjeta a la vez
    (consume_events bajo lock, liveness/screen_loop sin lock) chocaban en el mismo .tmp y os.replace
    fallaba con WinError 32 (medido 2026-09-05 16:30); el pid separa ademas dos procesos (dos hooks).
    Si Windows todavia tiene el destino abierto por otro lector (antivirus, el otro hilo), se
    reintenta un poco (medio segundo en total) antes de levantar el PermissionError; el .tmp no
    queda tirado."""
    tmp = f"{path}.{os.getpid()}.{get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for i in range(REINTENTOS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == REINTENTOS - 1:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (i + 1))
