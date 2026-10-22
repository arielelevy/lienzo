"""Guardias de la particion de sessions.py y server.py (plan del frente F, 2026-10-21).

1. Un `monkeypatch.setattr(modulo, "nombre", ...)` sobre un modulo de lienzo/ tiene que tener efecto.
   Si `sessions.send_to_session` pasa a `envio.py` y llama a `run_send` desde ahi, un
   `monkeypatch.setattr(ses, "run_send", ...)` deja de alcanzarlo y la prueba puede seguir en verde por
   la razon equivocada. La guardia lee el AST de lienzo/ y hace fallar el parche cuando ningun codigo
   lee ese atributo al correr (dentro del cuerpo de una funcion):
   - el propio modulo, como global (un local o parametro con el mismo nombre no cuenta);
   - otro modulo, como `alias.nombre`, `a.b.nombre` (la cadena se resuelve con los imports de cada
     modulo), `getattr(alias, "nombre")` o `from modulo import nombre` adentro de una funcion;
   - `getattr(alias, variable)` suma los textos de ese archivo; un modulo que se lee por nombre
     (`globals()`, como transcripts.py con los `parse_*`) deja pasar todo.
   Ante un archivo que no parsea, deja pasar.

2. Ningun modulo de lienzo/ importa `server`: server.py corre como script (`__main__`) y un
   `import server` cargaria una segunda copia con su propio `sessions`, `clients` y `lock`.
"""

from __future__ import annotations

import ast
import functools
import importlib
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

LIENZO = Path(__file__).resolve().parent.parent / "lienzo"
_FUNCIONES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _fuentes() -> list[Path]:
    return [p for p in LIENZO.rglob("*.py") if "__pycache__" not in p.parts]


_ARBOLES: dict[Path, ast.Module] = {}


def _arbol(path: Path) -> ast.Module | None:
    """El AST del archivo. Un archivo a medio escribir (otra sesion lo esta guardando) da None y no
    se recuerda: el proximo parche lo vuelve a leer."""
    if path not in _ARBOLES:
        try:
            _ARBOLES[path] = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError, UnicodeDecodeError, OSError:
            return None
    return _ARBOLES[path]


def _nombre_de_modulo(path: Path) -> str:
    partes = path.relative_to(LIENZO).with_suffix("").parts
    if partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


def _sin_lienzo(nombre: str) -> str:
    """`lienzo.server` y `server` son el mismo archivo (las pruebas importan de las dos formas)."""
    return nombre.removeprefix("lienzo.")


def _base_relativa(n: ast.ImportFrom, propio: str, es_paquete: bool) -> str:
    base = n.module or ""
    if n.level:
        paquete = propio.split(".") if es_paquete else propio.split(".")[:-1]
        arriba = paquete[: len(paquete) - (n.level - 1)] if n.level > 1 else paquete
        base = ".".join(x for x in (*arriba, base) if x)
    return _sin_lienzo(base)


def _alias(arbol: ast.Module, propio: str, es_paquete: bool) -> dict[str, str]:
    """nombre local -> lo que importa (`import sessions as ses`, `from tools import rtk`,
    `from . import atomico`, `from .. import x`), en todo el archivo."""
    out: dict[str, str] = {}
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    out[a.asname] = _sin_lienzo(a.name)
                else:
                    out[a.name.split(".")[0]] = _sin_lienzo(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            base = _base_relativa(n, propio, es_paquete)
            for a in n.names:
                out[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
    return out


def _locales(fn) -> set[str]:
    """Los nombres locales de una funcion: parametros y lo que asigna, sin los `global`/`nonlocal` ni
    los nombres que liga un import (esos siguen siendo el modulo). No baja a funciones, clases ni
    comprensiones anidadas (tienen su propio ambito)."""
    a = fn.args
    out = {x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if x}
    declarados: set[str] = set()
    pendientes = list(fn.body) if isinstance(fn.body, list) else [fn.body]
    while pendientes:
        n = pendientes.pop()
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            declarados.update(n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            continue
        elif isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue  # ambito propio: su variable no tapa a un global de la funcion
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        # un `import x` adentro de la funcion no es un local opaco: `x` sigue siendo el modulo (alias)
        pendientes.extend(ast.iter_child_nodes(n))
    return out - declarados


@dataclass
class _Analisis:
    propias: dict[str, set[str]] = field(default_factory=dict)  # modulo -> globales que lee al correr
    externas: dict[str, set[str]] = field(default_factory=dict)  # modulo -> atributos que otros le leen
    por_globals: set[str] = field(default_factory=set)  # modulos que se leen a si mismos por nombre


class _Lector:
    def __init__(self, analisis: _Analisis, path: Path, todos: dict[str, dict[str, str]]):
        self.a, self.todos = analisis, todos
        self.modulo = _nombre_de_modulo(path)
        self.es_paquete = path.name == "__init__.py"
        self.alias = todos[self.modulo]
        self.propias = analisis.propias.setdefault(self.modulo, set())
        self.arbol = _arbol(path)
        self.funciones: list = []  # la pila de funciones en las que estoy

    def _modulo_de(self, expr, locales) -> str | None:
        """El modulo de lienzo/ al que apunta `expr` (`ses`, `ses.mirror`, `tools.rtk`), o None."""
        if isinstance(expr, ast.Name):
            if expr.id in locales:
                return None
            m = self.alias.get(expr.id)
            if m is not None and m not in self.todos and "." in m:  # `from sessions import mirror`
                padre, _, nombre = m.rpartition(".")
                m = self.todos.get(padre, {}).get(nombre)
            return m if m in self.todos else None
        if isinstance(expr, ast.Attribute):
            m = self._modulo_de(expr.value, locales)
            if m is None:
                return None
            ligado = self.todos[m].get(expr.attr)  # lo que `m` importo con ese nombre
            if ligado in self.todos:
                return ligado
            sub = f"{m}.{expr.attr}"
            return sub if sub in self.todos else None
        return None

    def _lee(self, modulo: str, nombre: str) -> None:
        self.a.externas.setdefault(modulo, set()).add(nombre)

    def visitar(self, n, locales: frozenset, corriendo: bool) -> None:
        if isinstance(n, _FUNCIONES):
            for d in (*getattr(n, "decorator_list", ()), *n.args.defaults, *(x for x in n.args.kw_defaults if x)):
                self.visitar(d, locales, corriendo)
            adentro = locales | _locales(n)
            self.funciones.append(n)
            for hijo in n.body if isinstance(n.body, list) else [n.body]:
                self.visitar(hijo, adentro, True)
            self.funciones.pop()
            return
        if corriendo:
            self._mirar(n, locales)
        for hijo in ast.iter_child_nodes(n):
            if isinstance(n, ast.arg) or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and hijo is n.returns):
                continue
            self.visitar(hijo, locales, corriendo)

    def _mirar(self, n, locales) -> None:
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in locales:
            self.propias.add(n.id)
        elif isinstance(n, ast.AugAssign):  # `X += 1` y `alias.X += 1` leen X
            t = n.target
            if isinstance(t, ast.Name) and t.id not in locales:
                self.propias.add(t.id)
            elif isinstance(t, ast.Attribute) and (m := self._modulo_de(t.value, locales)):
                self._lee(m, t.attr)
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            if m := self._modulo_de(n.value, locales):
                self._lee(m, n.attr)
        elif isinstance(n, ast.ImportFrom):  # `from x import y` adentro de una funcion lee x.y al correr
            base = _base_relativa(n, self.modulo, self.es_paquete)
            for x in n.names:
                self._lee(base, x.name)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id not in locales:
            if n.func.id in ("globals", "vars") and not n.args:
                self.a.por_globals.add(self.modulo)
            elif n.func.id in ("getattr", "hasattr") and len(n.args) >= 2:
                m = self._modulo_de(n.args[0], locales)
                if m is None:
                    return
                clave = n.args[1]
                if isinstance(clave, ast.Constant) and isinstance(clave.value, str):
                    self._lee(m, clave.value)
                elif self._reexporta():
                    return  # el __getattr__ de un modulo reexporta: quien lo importa liga el nombre
                else:  # los textos del archivo pueden nombrar el atributo (las tablas suelen ir arriba)
                    for t in ast.walk(self.arbol):
                        if isinstance(t, ast.Constant) and isinstance(t.value, str) and t.value.isidentifier():
                            self._lee(m, t.value)

    def _reexporta(self) -> bool:
        return len(self.funciones) == 1 and getattr(self.funciones[0], "name", None) == "__getattr__"


_ANALISIS: list[_Analisis] = []


def _analizar() -> _Analisis | None:
    """El analisis de todo lienzo/, una vez por sesion. Si un archivo no parsea, None (la guardia deja
    pasar) y no se recuerda: el proximo parche lo vuelve a intentar."""
    if _ANALISIS:
        return _ANALISIS[0]
    rutas = _fuentes()
    arboles = {p: _arbol(p) for p in rutas}
    if any(a is None for a in arboles.values()):
        return None
    nombres = {p: _nombre_de_modulo(p) for p in rutas}
    todos = {nombres[p]: _alias(arboles[p], nombres[p], p.name == "__init__.py") for p in rutas}
    analisis = _Analisis()
    for p in rutas:
        lector = _Lector(analisis, p, todos)
        lector.visitar(arboles[p], frozenset(), False)
    _ANALISIS.append(analisis)
    return analisis


def olvidar() -> None:
    """Para las pruebas de la guardia, que cambian LIENZO."""
    _ARBOLES.clear()
    _ANALISIS.clear()


def _ruta_de(modulo: types.ModuleType) -> Path | None:
    archivo = getattr(modulo, "__file__", None)
    if not archivo:
        return None
    path = Path(archivo).resolve()
    return path if path.is_relative_to(LIENZO) and path.suffix == ".py" else None


def parche_sin_efecto(modulo: object, nombre: str) -> str | None:
    """None si el parche puede tener efecto (o el objetivo no es un modulo de lienzo/); si no, el motivo."""
    if not isinstance(modulo, types.ModuleType):
        return None
    path = _ruta_de(modulo)
    analisis = _analizar() if path is not None else None
    if analisis is None:
        return None
    propio = _nombre_de_modulo(path)
    if (
        propio in analisis.por_globals
        or nombre in analisis.propias.get(propio, ())
        or nombre in analisis.externas.get(propio, ())
    ):
        return None
    return (
        f"monkeypatch.setattr({modulo.__name__}, {nombre!r}) no tiene efecto: ningun codigo de lienzo/ "
        f"lee {modulo.__name__}.{nombre} al correr. Si se movio, parchea el modulo que lo define."
    )


def _modulo_y_nombre(texto: str) -> tuple[object, str] | None:
    """`"sessions.run_send"` -> (modulo sessions, "run_send"), como lo resuelve monkeypatch."""
    nombre_mod, _, nombre = texto.rpartition(".")
    if not nombre_mod:
        return None
    modulo = sys.modules.get(nombre_mod)
    if modulo is None:
        try:
            modulo = importlib.import_module(nombre_mod)
        except ImportError:
            return None
    return modulo, nombre


def instalar() -> None:
    """Envuelve MonkeyPatch.setattr para toda la sesion de pytest."""
    original = pytest.MonkeyPatch.setattr
    if getattr(original, "_guardia_f", False):
        return

    @functools.wraps(original)
    def setattr_con_guardia(self, target, *args, **kwargs):
        if isinstance(target, str):
            par = _modulo_y_nombre(target)  # forma de texto `setattr("mod.attr", valor)`
        else:
            nombre = args[0] if args else kwargs.get("name")
            par = (target, nombre) if isinstance(nombre, str) else None
        if par is not None:
            motivo = parche_sin_efecto(*par)
            if motivo:
                raise AssertionError(motivo)
        return original(self, target, *args, **kwargs)

    setattr_con_guardia._guardia_f = True
    pytest.MonkeyPatch.setattr = setattr_con_guardia


def _import_dinamico(n: ast.Call) -> str | None:
    """`importlib.import_module("x")`, `import_module(".x", "lienzo")` o `__import__("x")` -> "x"."""
    es_import = (isinstance(n.func, ast.Name) and n.func.id in ("__import__", "import_module")) or (
        isinstance(n.func, ast.Attribute) and n.func.attr == "import_module"
    )
    if not es_import or not n.args or not isinstance(n.args[0], ast.Constant) or not isinstance(n.args[0].value, str):
        return None
    nombre = n.args[0].value
    if nombre.startswith("."):
        paquete = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "package"), None)
        if not isinstance(paquete, ast.Constant) or not isinstance(paquete.value, str):
            return None
        nombre = paquete.value + nombre
    return _sin_lienzo(nombre)


def importadores_de_server() -> list[str]:
    """Los modulos de lienzo/ que importan el `server` de arriba (tendria que ser ninguno): `import
    server`, `import lienzo.server`, `from server import x`, `from lienzo.server import x`, `from
    lienzo import server`, `from . import server` (desde arriba) e `import_module`/`__import__`. Un
    `server` de un subpaquete (`tools/server.py`) no cuenta."""
    out = []
    for path in _fuentes():
        if path.name == "server.py" and path.parent == LIENZO:
            continue
        arbol = _arbol(path)
        if arbol is None:
            continue
        propio, es_paquete = _nombre_de_modulo(path), path.name == "__init__.py"
        for n in ast.walk(arbol):
            if isinstance(n, ast.Import):
                importados = [_sin_lienzo(a.name) for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = _base_relativa(n, propio, es_paquete)
                raiz = base in ("", "lienzo")
                importados = [base, *(a.name for a in n.names if raiz)]
            elif isinstance(n, ast.Call):
                importados = [_import_dinamico(n)]
            else:
                continue
            if "server" in importados:
                out.append(path.relative_to(LIENZO).as_posix())
                break
    return out
