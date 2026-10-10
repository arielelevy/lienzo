"""La API HTTP de la etapa 3 (veredictos.py), con el contrato de conocimiento_api: `dispatch(metodo,
partes, cuerpo, query) -> (codigo, cuerpo)`, donde `partes` llega sin `conocimiento` (`[<p>, ...]`).
La coordinadora la engancha en `conocimiento_api._dispatch` por prefijo de ruta.

    POST /conocimiento/<p>/veredictos               {items, por, revision?, evidencia?, motivo?}
    GET  /conocimiento/<p>/pendientes?ronda=
    GET  /conocimiento/<p>/duplicados?ronda=
    POST /conocimiento/<p>/rondas/<id>/cerrar       {por, veredictos?, sin_resolver?, motivo?}
    POST /conocimiento/<p>/temas                    {texto, por, aliases?}
    GET  /conocimiento/<p>/temas
    GET  /conocimiento/<p>/briefing?archivos=&temas=&q=&desde_cierre=   (parametros repetibles)
    GET  /conocimiento/<p>/preguntar?q=&archivos=&temas=&tipo=&saltos=&prosa=1   (prosa: opt-in, aparte)
    GET  /conocimiento/<p>/vista?tema=
    GET  /conocimiento/<p>/briefing?...&encargos=&markdown=1            (encargos: sus archivos; markdown: el texto)
    GET  /conocimiento/<p>/alternativas/<id>/por_que                    por que se descarto (v5 §8.5 consulta 1)
"""

from __future__ import annotations

import conocimiento as k
import veredictos as v
from conocimiento import Rechazo

PREFIJOS = ("veredictos", "pendientes", "duplicados", "temas", "briefing", "preguntar", "vista", "alternativas")


def es_mia(resto: list[str]) -> bool:
    """Si una ruta `/<p>/...` (ya sin el proyecto) es de esta API: para la linea de enganche."""
    return bool(resto) and (resto[0] in PREFIJOS or (len(resto) == 3 and resto[0] == "rondas" and resto[2] == "cerrar"))


def _lista(query: dict, nombre: str) -> list[str]:
    """Un parametro repetible (`?temas=a&temas=b`) o separado por comas (`?temas=a,b`); `q` solo repetible
    porque una consulta FTS puede llevar comas."""
    val = query.get(nombre)
    if val is None:
        return []
    if not isinstance(val, list):
        val = [val]
    out = []
    for x in val:
        if not isinstance(x, str):
            continue
        out += [x] if nombre == "q" else x.split(",")
    return [x.strip() for x in out if x.strip()]


def _uno(query: dict, nombre: str, defecto=None):
    xs = _lista(query, nombre)
    return xs[0] if xs else defecto


def _entero(val, nombre: str, defecto: int) -> int:
    if val is None:
        return defecto
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        raise Rechazo(f"{nombre} debe ser un entero") from e


def dispatch(metodo: str, partes: list[str], cuerpo: dict | None, query: dict | None) -> tuple[int, dict | list]:
    cuerpo = cuerpo or {}
    query = query or {}
    try:
        if not isinstance(cuerpo, dict):
            raise Rechazo("cuerpo debe ser un objeto")
        return _dispatch(metodo, partes, cuerpo, query)
    except Rechazo as e:
        return e.codigo, {"error": str(e)}


def _dispatch(metodo: str, partes: list[str], d: dict, query: dict) -> tuple[int, dict | list]:
    if not partes:
        return 404, {"error": "ruta desconocida"}
    pid, resto = partes[0], partes[1:]
    k.proyecto(pid)  # 404 si no existe
    if resto == ["veredictos"] and metodo == "POST":
        return 200, v.veredicto(
            pid,
            d.get("items"),
            por=k._texto(d.get("por"), "por", 200),
            revision=d.get("revision"),
            evidencia=d.get("evidencia"),
            motivo=d.get("motivo") or "",
        )
    if resto == ["pendientes"] and metodo == "GET":
        return 200, v.pendientes(pid, _uno(query, "ronda"))
    if resto == ["duplicados"] and metodo == "GET":
        return 200, {"duplicados": v.duplicados(pid, _uno(query, "ronda"))}
    if len(resto) == 3 and resto[0] == "rondas" and resto[2] == "cerrar" and metodo == "POST":
        return 200, v.cerrar_ronda(
            pid,
            resto[1],
            por=k._texto(d.get("por"), "por", 200),
            veredictos=d.get("veredictos"),
            sin_resolver=d.get("sin_resolver"),
            motivo=d.get("motivo") or "",
        )
    if resto == ["temas"] and metodo == "POST":
        return 200, v.tema(pid, d.get("texto"), por=k._texto(d.get("por"), "por", 200), aliases=d.get("aliases"))
    if resto == ["temas"] and metodo == "GET":
        return 200, {"temas": v.temas(pid)}
    if resto == ["briefing"] and metodo == "GET":
        b = v.briefing(
            pid,
            archivos=_lista(query, "archivos"),
            temas=_lista(query, "temas"),
            consultas=_lista(query, "q"),
            desde_cierre=_uno(query, "desde_cierre", "1") not in ("0", "false", "no"),
            encargos=_lista(query, "encargos"),
        )
        if _uno(query, "markdown") in ("1", "true", "si"):
            b["markdown"] = v.briefing_markdown(b)
        return 200, b
    if len(resto) == 3 and resto[0] == "alternativas" and resto[2] == "por_que" and metodo == "GET":
        return 200, v.por_que_descartada(pid, resto[1])
    if resto == ["preguntar"] and metodo == "GET":
        return 200, v.preguntar(
            pid,
            _lista(query, "q"),
            archivos=_lista(query, "archivos"),
            temas=_lista(query, "temas"),
            tipo=_uno(query, "tipo"),
            saltos=_entero(_uno(query, "saltos"), "saltos", 1),
            offset=_entero(_uno(query, "offset"), "offset", 0),
            limite=_entero(_uno(query, "limite"), "limite", 100),
            prosa=_uno(query, "prosa") in ("1", "true", "si"),
        )
    if resto == ["vista"] and metodo == "GET":
        return 200, v.vista(pid, _uno(query, "tema", ""))
    return 404, {"error": "ruta desconocida"}
