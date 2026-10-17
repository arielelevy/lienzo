"""Manifiesto uniforme de plugins locales: `lienzo/extensiones/<id>.plugin.json`.

Declara que es el plugin, con que es compatible, que capacidades aporta y que permisos y efectos
necesita. Se valida sin importar ni ejecutar codigo del plugin. Validarlo acredita estructura, no
seguridad ni calidad: el plugin corre dentro del proceso del server y Lienzo NO aplica los permisos
declarados (no es un sandbox); se muestran para decidir antes de habilitarlo.

Minimo: `compatibilidad`, `permisos` e identidad (`id`, `nombre`, `version`). Todo lo demas es
opcional y una lista vacia es valida: un plugin puede ser solo una forma de trabajo, sin codigo, sin
tools, sin endpoints ni interfaz.

    {
      "id": "notas", "nombre": "Notas de ronda", "version": "1.0.0",
      "descripcion": "...", "responsable": "Ariel",
      "origen": {"tipo": "local" | "privado" | "publico", "url": "https://..."},
      "compatibilidad": {"contrato": 1 | [1], "plataformas": ["windows", "linux", "macos"]},
      "capacidades": ["integracion", "forma-de-trabajo", "tools", "documentacion", "evaluacion"],
      "puntos": ["get", "post", "runners_externos", "vista"],
      "ciclo_de_vida": ["iniciar", "salud", "detener"],
      "configuracion": {"campos": [{"clave": "url", "tipo": "texto", "obligatorio": true}]},
      "permisos": {"lectura": [], "escritura": [], "ejecucion": [], "red": [], "efectos_externos": []},
      "evidencia": ["logs", "eventos", "pruebas", "resultados"],
      "relaciones": {"tools": ["anatomy"], "sistemas": ["Stepwise"]}
    }

La configuracion vive en `~/.lienzo/config.json`, en `plugins.<id>` (aparte de las claves de Lienzo). Un campo `secreto` guarda el
NOMBRE de una variable de entorno, nunca el valor; solo se comprueba que la variable exista.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CONTRATO = 1
SUFIJO = ".plugin.json"
MAX_BYTES = 64 * 1024
ID_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")  # el mismo nombre que el modulo, sin `.py`
_VERSION_RE = re.compile(r"\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?")
_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

ORIGENES = ("local", "privado", "publico")
PLATAFORMAS = ("windows", "linux", "macos")
CAPACIDADES = ("integracion", "forma-de-trabajo", "tools", "documentacion", "evaluacion")
PUNTOS = ("get", "post", "runners_externos", "vista")
CICLO = ("iniciar", "salud", "detener")
PERMISOS = ("lectura", "escritura", "ejecucion", "red", "efectos_externos")
EVIDENCIA = ("logs", "eventos", "pruebas", "resultados")
TIPOS_CAMPO = {
    "texto": (str,),
    "numero": (int, float),
    "booleano": (bool,),
    "lista": (list,),
    "objeto": (dict,),
    "secreto": (str,),
}
_CLAVES = frozenset(
    {
        "id", "nombre", "version", "descripcion", "responsable", "origen", "compatibilidad", "capacidades",
        "puntos", "ciclo_de_vida", "configuracion", "permisos", "evidencia", "relaciones",
    }
)  # fmt: skip


def plataforma_actual() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _texto(valor: object, maximo: int) -> bool:
    return isinstance(valor, str) and 0 < len(valor.strip()) and len(valor) <= maximo


def _lista_de(valor: object, permitidos: tuple[str, ...], campo: str, errores: list[str]) -> list[str]:
    if valor is None:
        return []
    if not isinstance(valor, list) or any(not isinstance(v, str) for v in valor):
        errores.append(f"{campo}: debe ser una lista de textos")
        return []
    desconocidos = sorted(set(valor) - set(permitidos))
    if desconocidos:
        errores.append(f"{campo}: valores desconocidos {desconocidos}; admitidos {list(permitidos)}")
    if len(set(valor)) != len(valor):
        errores.append(f"{campo}: valores repetidos")
    return [v for v in valor if v in permitidos]


def _identidad(data: dict, esperado: str | None, errores: list[str]) -> None:
    pid = data.get("id")
    if not isinstance(pid, str) or not ID_RE.fullmatch(pid):
        errores.append("id: obligatorio; minúsculas, números y guion bajo, empezando por letra (hasta 32)")
    elif esperado is not None and pid != esperado:
        errores.append(f"id: {pid!r} no coincide con el archivo {esperado!r}")
    if not _texto(data.get("nombre"), 80):
        errores.append("nombre: obligatorio, hasta 80 caracteres")
    version = data.get("version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        errores.append("version: obligatoria, con forma 1.2 o 1.2.3")
    for campo, maximo in (("descripcion", 500), ("responsable", 120)):
        if campo in data and not _texto(data[campo], maximo):
            errores.append(f"{campo}: texto de hasta {maximo} caracteres")


def _origen(origen: object, errores: list[str]) -> tuple[str, str | None]:
    if not isinstance(origen, dict) or origen.get("tipo") not in ORIGENES or set(origen) - {"tipo", "url"}:
        errores.append(f"origen: objeto con tipo {list(ORIGENES)} y url opcional")
        return "local", None
    url = origen.get("url")
    if url is not None and not (isinstance(url, str) and url.startswith("https://") and len(url) <= 300):
        errores.append("origen.url: https, hasta 300 caracteres")
        url = None
    if origen["tipo"] == "publico" and url is None:
        errores.append("origen: un plugin público declara su url")
    return origen["tipo"], url


def _compatibilidad(compat: object, errores: list[str], advertencias: list[str]) -> dict:
    if not isinstance(compat, dict):
        errores.append("compatibilidad: obligatoria, con contrato y plataformas opcionales")
        return {"contrato": [], "plataformas": []}
    raw = compat.get("contrato")
    raw = [raw] if type(raw) is int else raw
    contratos: list[int] = []
    if not isinstance(raw, list) or not raw or any(type(c) is not int or c < 1 for c in raw):
        errores.append("compatibilidad.contrato: entero o lista de enteros positivos")
    else:
        contratos = sorted(set(raw))
    extras = sorted(set(compat) - {"contrato", "plataformas"})
    if extras:
        advertencias.append(f"compatibilidad: claves ignoradas {extras}")
    plataformas = _lista_de(compat.get("plataformas"), PLATAFORMAS, "compatibilidad.plataformas", errores)
    return {"contrato": contratos, "plataformas": plataformas}


def _permisos(raw: object, errores: list[str]) -> dict[str, list[str]]:
    permisos: dict[str, list[str]] = {k: [] for k in PERMISOS}
    if not isinstance(raw, dict):
        errores.append(f"permisos: obligatorio, objeto con {list(PERMISOS)}; listas vacías si no usa ninguno")
        return permisos
    for clave, valor in raw.items():
        if clave not in PERMISOS:
            errores.append(f"permisos.{clave}: desconocido; admitidos {list(PERMISOS)}")
        elif not isinstance(valor, list) or any(not _texto(v, 200) for v in valor):
            errores.append(f"permisos.{clave}: lista de textos de hasta 200 caracteres")
        else:
            permisos[clave] = list(valor)
    return permisos


def _campo_valido(campo: object) -> bool:
    return (
        isinstance(campo, dict)
        and isinstance(campo.get("clave"), str)
        and bool(_ENV_RE.fullmatch(campo["clave"]))
        and campo.get("tipo") in TIPOS_CAMPO
        and type(campo.get("obligatorio", False)) is bool
        and ("descripcion" not in campo or _texto(campo["descripcion"], 300))
        and not set(campo) - {"clave", "tipo", "obligatorio", "descripcion"}
    )


def _configuracion(config: object, errores: list[str]) -> list[dict]:
    if config is None:
        return []
    lista = config.get("campos") if isinstance(config, dict) else None
    if not isinstance(lista, list) or set(config) - {"campos"}:
        errores.append("configuracion: objeto con una lista campos")
        return []
    campos: list[dict] = []
    for i, campo in enumerate(lista):
        if not _campo_valido(campo):
            errores.append(f"configuracion.campos[{i}]: clave, tipo {list(TIPOS_CAMPO)}, obligatorio y descripción")
        elif any(c["clave"] == campo["clave"] for c in campos):
            errores.append(f"configuracion.campos[{i}]: clave repetida {campo['clave']!r}")
        else:
            campos.append({"obligatorio": False, **campo})
    return campos


def _relaciones(raw: object, conocidas: set[str] | None, errores: list[str], advertencias: list[str]) -> dict:
    relaciones: dict[str, list[str]] = {"tools": [], "sistemas": []}
    if not isinstance(raw, dict) or set(raw) - set(relaciones):
        errores.append("relaciones: objeto con tools y sistemas opcionales")
        return relaciones
    for clave in relaciones:
        valor = raw.get(clave, [])
        if not isinstance(valor, list) or any(not _texto(v, 80) for v in valor):
            errores.append(f"relaciones.{clave}: lista de textos")
        else:
            relaciones[clave] = list(valor)
    ajenas = sorted(set(relaciones["tools"]) - conocidas) if conocidas is not None else []
    if ajenas:
        advertencias.append(f"relaciones.tools: fuera del catálogo de esta versión {ajenas}")
    return relaciones


def validar(data: object, esperado: str | None = None, tools_conocidas: set[str] | None = None) -> dict:
    """{"manifiesto": normalizado o None, "errores": [...], "advertencias": [...]}. Sin efectos."""
    if not isinstance(data, dict):
        return {"manifiesto": None, "errores": ["el manifiesto debe ser un objeto JSON"], "advertencias": []}
    errores: list[str] = []
    advertencias: list[str] = []
    extras = sorted(set(data) - _CLAVES)
    if extras:
        advertencias.append(f"claves ignoradas: {extras}")
    _identidad(data, esperado, errores)
    origen, url = _origen(data.get("origen", {"tipo": "local"}), errores)
    manifiesto = {
        "id": data.get("id"),
        "nombre": data["nombre"].strip() if isinstance(data.get("nombre"), str) else None,
        "version": data.get("version"),
        "descripcion": data.get("descripcion"),
        "responsable": data.get("responsable"),
        "origen": origen,
        "url": url,
        "compatibilidad": _compatibilidad(data.get("compatibilidad"), errores, advertencias),
        "capacidades": _lista_de(data.get("capacidades"), CAPACIDADES, "capacidades", errores),
        "puntos": _lista_de(data.get("puntos"), PUNTOS, "puntos", errores),
        "ciclo_de_vida": _lista_de(data.get("ciclo_de_vida"), CICLO, "ciclo_de_vida", errores),
        "configuracion": _configuracion(data.get("configuracion"), errores),
        "permisos": _permisos(data.get("permisos"), errores),
        "evidencia": _lista_de(data.get("evidencia"), EVIDENCIA, "evidencia", errores),
        "relaciones": _relaciones(data.get("relaciones", {}), tools_conocidas, errores, advertencias),
    }
    return {"manifiesto": None if errores else manifiesto, "errores": errores, "advertencias": advertencias}


def leer(ruta: str | Path, tools_conocidas: set[str] | None = None) -> dict:
    """Lee y valida `<id>.plugin.json`. Un archivo ilegible es un error del manifiesto, no una excepcion."""
    ruta = Path(ruta)
    esperado = ruta.name[: -len(SUFIJO)] if ruta.name.endswith(SUFIJO) else None
    try:
        if ruta.stat().st_size > MAX_BYTES:
            return {"manifiesto": None, "errores": [f"{ruta.name}: supera {MAX_BYTES} bytes"], "advertencias": []}
        data = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as e:
        return {
            "manifiesto": None,
            "errores": [f"{ruta.name}: no se pudo leer ({type(e).__name__})"],
            "advertencias": [],
        }
    except ValueError as e:
        return {"manifiesto": None, "errores": [f"{ruta.name}: JSON inválido ({e})"], "advertencias": []}
    return validar(data, esperado, tools_conocidas)


def incompatibilidad(manifiesto: dict, plataforma: str | None = None) -> str | None:
    """Motivo por el que este Lienzo no debe cargarlo, o None."""
    if CONTRATO not in manifiesto["compatibilidad"]["contrato"]:
        return f"declara contrato {manifiesto['compatibilidad']['contrato']}; este Lienzo usa {CONTRATO}"
    plataformas = manifiesto["compatibilidad"]["plataformas"]
    actual = plataforma or plataforma_actual()
    if plataformas and actual not in plataformas:
        return f"declara plataformas {plataformas}; esta PC es {actual}"
    return None


def _revisar_valor(campo: dict, valor: object, entorno, faltan: list[str], errores: list[str]) -> None:
    clave, tipo = campo["clave"], campo["tipo"]
    if not isinstance(valor, TIPOS_CAMPO[tipo]) or (tipo == "numero" and isinstance(valor, bool)):
        errores.append(f"{clave}: se esperaba {tipo}")
    elif tipo == "secreto" and not _ENV_RE.fullmatch(valor):
        errores.append(f"{clave}: guarda el nombre de una variable de entorno, no el secreto")
    elif tipo == "secreto" and not entorno.get(valor):
        faltan.append(f"{clave} (variable {valor} no definida)")


def estado_configuracion(manifiesto: dict, valores: object, entorno: dict | None = None) -> dict:
    """{"completa", "faltan", "errores"} de `config.json["plugins"][<id>]`. De un secreto solo se mira si
    la variable existe; su valor no se lee ni se devuelve."""
    entorno = os.environ if entorno is None else entorno
    campos = manifiesto["configuracion"]
    faltan: list[str] = []
    errores: list[str] = []
    if not campos:
        return {"completa": True, "faltan": [], "errores": []}
    if valores is None:
        valores = {}
    if not isinstance(valores, dict):
        return {"completa": False, "faltan": [], "errores": [f"plugins.{manifiesto['id']} debe ser un objeto"]}
    for campo in campos:
        clave = campo["clave"]
        if clave in valores:
            _revisar_valor(campo, valores[clave], entorno, faltan, errores)
        elif campo["obligatorio"]:
            faltan.append(clave)
    return {"completa": not faltan and not errores, "faltan": faltan, "errores": errores}
