"""Plugins locales del server: modulos en `lienzo/extensiones/*.py`, carpeta que Git ignora. Un plugin
existe solo en la PC que lo tiene; sin ninguno, el server anda igual.

Un plugin es un modulo con, todo opcional:
- `RUNNERS_EXTERNOS: dict[str, str]`: ejecutable -> tipo. Un agente que corre debajo de uno de esos
  procesos es una ejecucion externa (procs.external_origin): se ve, pero no se le teclea, ni se lo
  mata, ni lo mueven reglas.
- `iniciar()`: se llama una vez al arrancar el server (sus hilos, si los tiene).
- `get(partes, query) -> (codigo, cuerpo)`: `GET /ext/<nombre>/<partes...>`.
- `post(partes, cuerpo, ctx) -> (codigo, cuerpo)`: `POST /ext/<nombre>/<partes...>`. `ctx` trae
  `autor` (quien lo pidio desde el tablero). Pasa por la autenticacion y el CSRF de siempre.
`<nombre>` es el del archivo, sin `.py`. Un plugin que no carga queda en el log y no frena al server.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import traceback
from types import ModuleType

try:
    from . import procinfo, state
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import procinfo
    import state

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extensiones")
_NOMBRE_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")
_cargados: dict[str, ModuleType] = {}


def cargar(carpeta: str = CARPETA) -> list[str]:
    """Importa cada `<nombre>.py` de la carpeta (nombres en minusculas) y registra sus ejecutables
    externos. Devuelve los nombres cargados. Idempotente: un plugin ya cargado no se reimporta."""
    if not os.path.isdir(carpeta):
        return sorted(_cargados)
    for archivo in sorted(os.listdir(carpeta)):
        nombre, ext = os.path.splitext(archivo)
        if ext != ".py" or not _NOMBRE_RE.fullmatch(nombre) or nombre in _cargados:
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"lienzo_ext_{nombre}", os.path.join(carpeta, archivo))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            state.log(f"plugin {nombre}: no cargo:\n{traceback.format_exc()}")
            continue
        for exe, tipo in (getattr(mod, "RUNNERS_EXTERNOS", None) or {}).items():
            procinfo.EXTERNAL_RUNNERS[exe.lower()] = tipo
        _cargados[nombre] = mod
        state.log(f"plugin {nombre}: cargado")
    return sorted(_cargados)


def iniciar() -> None:
    for nombre, mod in _cargados.items():
        fn = getattr(mod, "iniciar", None)
        if fn is None:
            continue
        try:
            fn()
        except Exception:
            state.log(f"plugin {nombre}: iniciar fallo:\n{traceback.format_exc()}")


def nombres() -> list[str]:
    return sorted(_cargados)


def get(nombre: str, partes: list[str], query: dict) -> tuple[int, dict]:
    fn = getattr(_cargados.get(nombre), "get", None)
    if fn is None:
        return 404, {"error": "ruta desconocida"}
    return fn(partes, query)


def post(nombre: str, partes: list[str], cuerpo: dict, ctx: dict) -> tuple[int, dict]:
    fn = getattr(_cargados.get(nombre), "post", None)
    if fn is None:
        return 404, {"error": "ruta desconocida"}
    return fn(partes, cuerpo, ctx)
