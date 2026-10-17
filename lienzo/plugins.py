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
- `salud() -> {"ok": bool, "detalle": str, "conectado": bool?}` y `detener()`: ciclo de vida, solo
  con manifiesto.
`<nombre>` es el del archivo, sin `.py`. Un plugin que no carga queda en el log y no frena al server.

Manifiesto (plugin_manifest.py): `<nombre>.plugin.json` al lado del modulo. Se valida ANTES de
importar: si el plugin esta deshabilitado (`plugins_deshabilitados` en config.json) o el manifiesto es
invalido o incompatible, el modulo no se importa y la ficha dice por que. Con manifiesto, lo que el
modulo exporta tiene que coincidir con lo declarado; eso se ve recien despues de ejecutar el import,
asi que un modulo incoherente no se registra pero sus efectos de import ya ocurrieron. Su
configuracion va en `config.json["plugins"][<nombre>]`. Si su `iniciar()` falla, sus rutas
contestan 503. Un manifiesto sin `.py` es un plugin declarativo (una
forma de trabajo, sin codigo en el server). Un modulo sin manifiesto carga como siempre (legacy).
`GET /ext/<nombre>/_salud` queda reservado: llama a `salud()` de un plugin con manifiesto que la
declara, con tiempo limite. El inventario (`resumen`) nunca llama al plugin: cargado no es conectado.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from types import ModuleType

try:
    from . import plugin_manifest, procinfo, state
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import plugin_manifest
    import procinfo
    import state

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extensiones")
_NOMBRE_RE = plugin_manifest.ID_RE
SALUD_TIMEOUT_S = 5.0
DETALLE_MAX = 300
_cargados: dict[str, ModuleType] = {}
_fichas: dict[str, dict] = {}  # id -> ficha, tambien de los que no cargaron; "_modulo" ata la ficha a su modulo
_lock = threading.Lock()

_DETALLES = {
    "cargado": "Módulo cargado; no acredita conexión ni salud del sistema integrado.",
    "declarado": "Forma de trabajo declarada, sin código en el server.",
    "sin-configurar": "Módulo cargado con configuración incompleta.",
    "deshabilitado": "Deshabilitado en config.json (plugins_deshabilitados); no se importó.",
    "incompatible": "No se importó: incompatible con este Lienzo o esta PC.",
    "error": "No se cargó o falló al iniciar; ver errores.",
}


def _exporta(mod: ModuleType) -> tuple[set[str], set[str]]:
    """(puntos, ciclo de vida) que el modulo exporta de verdad."""
    puntos = {p for p in ("get", "post") if callable(getattr(mod, p, None))}
    if getattr(mod, "RUNNERS_EXTERNOS", None):
        puntos.add("runners_externos")
    return puntos, {c for c in plugin_manifest.CICLO if callable(getattr(mod, c, None))}


def _vista(nombre: str) -> bool:
    return (Path(state.ROOT) / "web/src/extensiones" / f"{nombre}.tsx").is_file()


def _ficha(nombre: str, estado: str, manifiesto: dict | None = None, **extra) -> dict:
    m = manifiesto or {}
    ficha = {
        "id": nombre,
        "nombre": m.get("nombre") or nombre.replace("_", " ").capitalize(),
        "version": m.get("version"),
        "descripcion": m.get("descripcion"),
        "responsable": m.get("responsable"),
        "origen": m.get("origen", "local"),
        "url": m.get("url"),
        "manifiesto": "valido" if manifiesto else "ausente",
        "estado": estado,
        "cargado": False,
        "capacidades": list(m.get("capacidades", [])),
        "puntos": list(m.get("puntos", [])),
        "ciclo_de_vida": list(m.get("ciclo_de_vida", [])),
        "permisos": m.get("permisos"),
        "configuracion": None,
        "evidencia": list(m.get("evidencia", [])),
        "relaciones": m.get("relaciones", {"tools": [], "sistemas": []}),
        "errores": [],
        "advertencias": [],
        "salud": None,
        "detalle": _DETALLES[estado],
        "_manifiesto": manifiesto,
        "_modulo": None,
    }
    ficha.update(extra)
    return ficha


def _registrar(ficha: dict) -> None:
    with _lock:
        _fichas[ficha["id"]] = ficha
    if ficha["estado"] in ("error", "incompatible"):
        state.log(f"plugin {ficha['id']}: {ficha['estado']}: {'; '.join(ficha['errores']) or ficha['detalle']}")


def _deshabilitados(cfg: dict) -> set[str]:
    valor = cfg.get("plugins_deshabilitados", [])
    if isinstance(valor, list) and all(isinstance(v, str) for v in valor):
        return set(valor)
    state.log("plugins: plugins_deshabilitados debe ser una lista de nombres; se ignora")
    return set()


def _tools_conocidas() -> set[str] | None:
    try:
        try:
            from . import tools
        except ImportError:
            import tools
        return {t.id for t in tools.catalogo()}
    except Exception:
        # sin catalogo no se advierte por relaciones; no frena la carga, pero queda en el log
        state.log(f"plugins: catalogo de tools no disponible para validar relaciones:\n{traceback.format_exc()}")
        return None


def _importar(nombre: str, ruta: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"lienzo_ext_{nombre}", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def _incoherencias(mod: ModuleType, manifiesto: dict) -> list[str]:
    """Lo que el modulo exporta y no declaro, o declaro y no exporta."""
    puntos, ciclo = _exporta(mod)
    declarados = set(manifiesto["puntos"]) - {"vista"}
    sobran = sorted((puntos - declarados) | (ciclo - set(manifiesto["ciclo_de_vida"])))
    faltan = sorted((declarados - puntos) | (set(manifiesto["ciclo_de_vida"]) - ciclo))
    errores = []
    if sobran:
        errores.append(f"exporta sin declarar: {sobran}")
    if faltan:
        errores.append(f"declara y no exporta: {faltan}")
    return errores


def _advertencia_vista(nombre: str, manifiesto: dict) -> list[str]:
    declarada = "vista" in manifiesto["puntos"]
    if declarada == _vista(nombre):
        return []
    if declarada:
        return [f"declara vista pero falta web/src/extensiones/{nombre}.tsx"]
    return ["tiene vista en web/src/extensiones sin declararla"]


def _config_de(cfg: dict, nombre: str) -> object:
    """`config.json["plugins"][<nombre>]`: aparte de las claves propias de Lienzo (wait, ejemplos...)."""
    seccion = cfg.get("plugins", {})
    return seccion.get(nombre) if isinstance(seccion, dict) else seccion


def _revisar_manifiesto(carpeta: str, nombre: str, apagado: bool, conocidas) -> tuple[dict | None, dict | None, list]:
    """(ficha si no se debe importar, manifiesto valido, advertencias) de `<nombre>.plugin.json`."""
    leido = plugin_manifest.leer(os.path.join(carpeta, nombre + plugin_manifest.SUFIJO), conocidas)
    advertencias = leido["advertencias"]
    if apagado:  # apagado a proposito: no se reportan errores de lo que no se usa
        return _ficha(nombre, "deshabilitado", leido["manifiesto"], advertencias=advertencias), None, advertencias
    if leido["errores"]:
        errores = ["manifiesto inválido: " + e for e in leido["errores"]]
        ficha = _ficha(nombre, "error", errores=errores, advertencias=advertencias)
        ficha["manifiesto"] = "invalido"
        return ficha, None, advertencias
    motivo = plugin_manifest.incompatibilidad(leido["manifiesto"])
    if motivo:
        ficha = _ficha(nombre, "incompatible", leido["manifiesto"], errores=[motivo], advertencias=advertencias)
        return ficha, None, advertencias
    return None, leido["manifiesto"], advertencias


def _declarativo(nombre: str, manifiesto: dict, configuracion: dict, advertencias: list[str]) -> dict:
    """Sin modulo no hay puntos ni ciclo de vida que atender: declararlos es un error."""
    sin_codigo = sorted(set(manifiesto["puntos"]) - {"vista"}) + manifiesto["ciclo_de_vida"]
    if sin_codigo:
        errores = [f"declara {sin_codigo} sin {nombre}.py"]
        return _ficha(nombre, "error", manifiesto, errores=errores, advertencias=advertencias)
    return _ficha(nombre, "declarado", manifiesto, configuracion=configuracion, advertencias=advertencias)


def _cargar_uno(carpeta: str, nombre: str, archivos: set[str], cfg: dict, apagados: set[str], conocidas) -> dict:
    """La ficha de un candidato. Solo importa el modulo si el manifiesto (si hay) lo permite."""
    manifiesto = None
    advertencias: list[str] = []
    if nombre + plugin_manifest.SUFIJO in archivos:
        terminal, manifiesto, advertencias = _revisar_manifiesto(carpeta, nombre, nombre in apagados, conocidas)
        if terminal is not None:
            return terminal
    elif nombre in apagados:
        return _ficha(nombre, "deshabilitado")
    configuracion = None
    if manifiesto:
        configuracion = plugin_manifest.estado_configuracion(manifiesto, _config_de(cfg, nombre))
        advertencias += _advertencia_vista(nombre, manifiesto)
    if nombre + ".py" not in archivos:
        return _declarativo(nombre, manifiesto, configuracion, advertencias)
    try:
        mod = _importar(nombre, os.path.join(carpeta, nombre + ".py"))
    except Exception as e:
        state.log(f"plugin {nombre}: no cargo:\n{traceback.format_exc()}")
        errores = [f"no cargó: {type(e).__name__}: {str(e)[:DETALLE_MAX]}"]
        return _ficha(nombre, "error", manifiesto, errores=errores, advertencias=advertencias)
    errores = _incoherencias(mod, manifiesto) if manifiesto else []
    if errores:
        sys.modules.pop(f"lienzo_ext_{nombre}", None)
        return _ficha(nombre, "error", manifiesto, errores=errores, advertencias=advertencias)
    for exe, tipo in (getattr(mod, "RUNNERS_EXTERNOS", None) or {}).items():
        procinfo.EXTERNAL_RUNNERS[exe.lower()] = tipo
    _cargados[nombre] = mod
    state.log(f"plugin {nombre}: cargado")
    if not manifiesto:
        return _legacy(nombre, mod)
    estado = "sin-configurar" if not configuracion["completa"] else "cargado"
    return _ficha(
        nombre, estado, manifiesto, cargado=True, configuracion=configuracion, advertencias=advertencias, _modulo=mod
    )


def cargar(carpeta: str = CARPETA, config: dict | None = None) -> list[str]:
    """Importa cada `<nombre>.py` de la carpeta (nombres en minusculas), con su manifiesto si lo tiene,
    y registra sus ejecutables externos. Devuelve los nombres cargados. Idempotente: un plugin ya
    cargado no se reimporta. Cada candidato, cargado o no, deja su ficha para `resumen`."""
    if not os.path.isdir(carpeta):
        return sorted(_cargados)
    cfg = state.load_config() if config is None else config
    apagados = _deshabilitados(cfg)
    conocidas = _tools_conocidas()
    archivos = set(os.listdir(carpeta))
    candidatos = {a[:-3] for a in archivos if a.endswith(".py")}
    candidatos |= {a[: -len(plugin_manifest.SUFIJO)] for a in archivos if a.endswith(plugin_manifest.SUFIJO)}
    for nombre in sorted(n for n in candidatos if _NOMBRE_RE.fullmatch(n) and n not in _cargados):
        _registrar(_cargar_uno(carpeta, nombre, archivos, cfg, apagados, conocidas))
    return sorted(_cargados)


def iniciar() -> None:
    for nombre, mod in _cargados.items():
        fn = getattr(mod, "iniciar", None)
        if fn is None:
            continue
        try:
            fn()
        except Exception as e:
            state.log(f"plugin {nombre}: iniciar fallo:\n{traceback.format_exc()}")
            with _lock:
                ficha = _fichas.get(nombre)
                if ficha is not None and ficha["_modulo"] is mod:
                    ficha["estado"], ficha["detalle"] = "error", _DETALLES["error"]
                    ficha["errores"].append(f"iniciar falló: {type(e).__name__}: {str(e)[:DETALLE_MAX]}")


def detener() -> list[str]:
    """Llama a `detener()` de los plugins con manifiesto que lo declaran. Un fallo queda en el log."""
    parados = []
    for nombre, mod in list(_cargados.items()):
        ficha = _fichas.get(nombre)
        if ficha is None or ficha["_modulo"] is not mod or "detener" not in ficha["ciclo_de_vida"]:
            continue
        try:
            mod.detener()
            parados.append(nombre)
        except Exception:
            state.log(f"plugin {nombre}: detener fallo:\n{traceback.format_exc()}")
    return parados


def nombres() -> list[str]:
    return sorted(_cargados)


def _legacy(nombre: str, mod: ModuleType) -> dict:
    puntos, ciclo = _exporta(mod)
    return _ficha(
        nombre,
        "cargado",
        cargado=True,
        puntos=sorted(puntos | ({"vista"} if _vista(nombre) else set())),
        ciclo_de_vida=sorted(ciclo & {"iniciar"}),
        _modulo=mod,
    )


def resumen() -> list[dict]:
    """Inventario de extensiones, cargadas o no, sin exigir tools ni llamar al plugin ni a sistemas
    externos. La salud solo aparece si alguien la pidio (`/ext/<nombre>/_salud`)."""
    with _lock:
        fichas = {k: dict(v) for k, v in _fichas.items()}
    result = []
    for nombre in sorted(set(_cargados) | set(fichas)):
        mod = _cargados.get(nombre)
        ficha = fichas.get(nombre)
        if mod is not None and (ficha is None or ficha["_modulo"] is not mod):
            ficha = _legacy(nombre, mod)
        elif mod is None and ficha["cargado"]:
            continue  # su modulo ya no esta registrado
        result.append({k: v for k, v in ficha.items() if not k.startswith("_")})
    return result


def _normalizar_salud(res: object) -> dict:
    if not isinstance(res, dict) or type(res.get("ok")) is not bool:
        return {"ok": False, "detalle": "respuesta inválida: se espera {ok: bool, detalle}", "conectado": None}
    conectado = res.get("conectado")
    return {
        "ok": res["ok"],
        "detalle": str(res.get("detalle") or "")[:DETALLE_MAX],
        "conectado": conectado if type(conectado) is bool else None,
    }


def salud(nombre: str) -> tuple[int, dict]:
    """Comprobacion a pedido, con tiempo limite. Un plugin colgado no deja hilos apilados: mientras la
    anterior no termina, contesta 409."""
    mod = _cargados.get(nombre)
    with _lock:
        ficha = _fichas.get(nombre)
        if mod is None or ficha is None or ficha["_modulo"] is not mod or "salud" not in ficha["ciclo_de_vida"]:
            return 404, {"error": "el plugin no declara comprobación de salud"}
        if ficha.get("_salud_en_curso"):
            return 409, {"error": "la comprobación anterior todavía no terminó"}
        ficha["_salud_en_curso"] = True
    caja: dict = {}

    def correr() -> None:
        try:
            caja["res"] = _normalizar_salud(mod.salud())
        except Exception as e:
            state.log(f"plugin {nombre}: salud fallo:\n{traceback.format_exc()}")
            caja["res"] = {"ok": False, "detalle": f"{type(e).__name__}: {str(e)[:DETALLE_MAX]}", "conectado": None}
        finally:
            with _lock:
                ficha["_salud_en_curso"] = False

    hilo = threading.Thread(target=correr, name=f"salud-{nombre}", daemon=True)
    hilo.start()
    hilo.join(SALUD_TIMEOUT_S)
    res = caja.get("res") or {"ok": False, "detalle": f"sin respuesta en {SALUD_TIMEOUT_S:g} s", "conectado": None}
    res = {**res, "ts": time.time()}
    with _lock:
        ficha["salud"] = res
    return 200, {"id": nombre, "salud": res}


def _con_manifiesto(nombre: str) -> dict | None:
    """La ficha del modulo registrado, si tiene manifiesto. Los legacy siguen como siempre."""
    mod = _cargados.get(nombre)
    with _lock:
        ficha = _fichas.get(nombre)
        if mod is None or ficha is None or ficha["_modulo"] is not mod or ficha["_manifiesto"] is None:
            return None
        return dict(ficha)


def get(nombre: str, partes: list[str], query: dict) -> tuple[int, dict]:
    ficha = _con_manifiesto(nombre)
    if ficha is not None and partes == ["_salud"]:
        return salud(nombre)
    if ficha is not None and ficha["estado"] == "error":
        return 503, {"error": "el plugin falló al iniciar; ver su ficha"}
    fn = getattr(_cargados.get(nombre), "get", None)
    if fn is None:
        return 404, {"error": "ruta desconocida"}
    return fn(partes, query)


def post(nombre: str, partes: list[str], cuerpo: dict, ctx: dict) -> tuple[int, dict]:
    ficha = _con_manifiesto(nombre)
    if ficha is not None and ficha["estado"] == "error":
        return 503, {"error": "el plugin falló al iniciar; ver su ficha"}
    fn = getattr(_cargados.get(nombre), "post", None)
    if fn is None:
        return 404, {"error": "ruta desconocida"}
    return fn(partes, cuerpo, ctx)
