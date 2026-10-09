"""La API del aprendizaje operativo (v5 §6, etapa 4), con el contrato de conocimiento_api:
`dispatch(metodo, partes, cuerpo, query) -> (codigo, cuerpo)`, sin saber de HTTP. `partes` llega sin
el tramo `conocimiento`: `partes[0]` es el proyecto, salvo en `lecciones`, que cruza proyectos.
conocimiento_api._dispatch la engancha por prefijo de ruta.

    GET  /conocimiento/lecciones?agente=&modelo=&proyectos=a,b   reglas de un agente en todos los proyectos
    GET  /conocimiento/<p>/incidentes/<id>/parecidos?limite=      candidatos a recurrencia (BM25 + herramienta/agente)
    GET  /conocimiento/<p>/incidentes/<id>/recurrencia            el grupo `repite`, cada episodio una vez
    GET  /conocimiento/<p>/incidentes/recurrencias               grupos confirmados unicos para el briefing
    POST /conocimiento/<p>/reglas/cuestionar                      pasa a cuestionada toda regla vigente con recurrencia posterior
    POST /conocimiento/<p>/reglas/<id>/cuestionar                 idem, una sola
    GET  /conocimiento/<p>/reglas/cuestionadas                    las cuestionadas con sus episodios contados hoy
    GET  /conocimiento/<p>/avisos                                 apoyos rechazados (decisiones y preguntas)
    GET  /conocimiento/<p>/nodos/<id>/aviso                       el aviso de un nodo
    GET  /conocimiento/<p>/nodos/<id>/dependencias                quien depende de un nodo (transitivo)
"""

from __future__ import annotations

import aprendizaje as ap
import conocimiento as k
from conocimiento import Rechazo


def _q(query: dict, nombre: str, defecto=None):
    v = query.get(nombre)
    if isinstance(v, list):
        v = v[0] if v else None
    return v if v not in (None, "") else defecto


def _entero(v, nombre: str, defecto: int) -> int:
    if v is None:
        return defecto
    try:
        return int(v)
    except (TypeError, ValueError) as e:
        raise Rechazo(f"{nombre} debe ser un entero") from e


def dispatch(metodo: str, partes: list[str], cuerpo: dict | None, query: dict | None) -> tuple[int, dict | list]:
    cuerpo = cuerpo or {}
    query = query or {}
    try:
        return _dispatch(metodo, partes, cuerpo, query)
    except Rechazo as e:
        return e.codigo, {"error": str(e)}


def _dispatch(metodo: str, partes: list[str], d: dict, query: dict) -> tuple[int, dict | list]:
    if partes == ["lecciones"] and metodo == "GET":
        proyectos = _q(query, "proyectos")
        return 200, ap.lecciones(
            _q(query, "agente"),
            modelo=_q(query, "modelo"),
            proyectos=[p for p in proyectos.split(",") if p.strip()] if isinstance(proyectos, str) else None,
        )
    if not partes:
        return 404, {"error": "ruta desconocida"}
    pid, resto = partes[0], partes[1:]
    k.proyecto(pid)  # 404 si no existe
    if resto == ["incidentes", "recurrencias"] and metodo == "GET":
        return 200, ap.recurrencias(pid)
    if len(resto) == 3 and resto[0] == "incidentes" and metodo == "GET":
        if resto[2] == "parecidos":
            limite = _entero(_q(query, "limite"), "limite", ap.LIMITE_PARECIDOS)
            return 200, ap.parecidos(pid, resto[1], limite=limite)
        if resto[2] == "recurrencia":
            return 200, ap.recurrencia(pid, resto[1])
    if resto == ["reglas", "cuestionar"] and metodo == "POST":
        return 200, ap.cuestionar(pid)
    if resto == ["reglas", "cuestionadas"] and metodo == "GET":
        return 200, ap.reglas_cuestionadas(pid)
    if len(resto) == 3 and resto[0] == "reglas" and resto[2] == "cuestionar" and metodo == "POST":
        return 200, ap.cuestionar_regla(pid, resto[1])
    if resto == ["avisos"] and metodo == "GET":
        return 200, ap.apoyos_rechazados(pid)
    if len(resto) == 3 and resto[0] == "nodos" and metodo == "GET":
        if resto[2] == "aviso":
            return 200, ap.aviso(pid, resto[1])
        if resto[2] == "dependencias":
            return 200, ap.dependencias(pid, resto[1])
    return 404, {"error": "ruta desconocida"}
