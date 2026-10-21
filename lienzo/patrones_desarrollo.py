"""Patrones descriptivos por clase de desarrollo; no infiere calidad de menciones.

Sólo etiquetas explícitas identifican el tipo de trabajo y sus controles. Lo que
falta queda desconocido, sin convertir una mención de review en una revisión ejecutada.
"""

from __future__ import annotations

import collections
import hashlib
import json

import conocimiento as k
import creencias

TIPOS = {"bugfix", "feature", "refactor", "investigacion", "documentacion", "arquitectura"}
SIN_CLASIFICAR = "sin_clasificar"  # declarado a propósito: se cuenta aparte, nunca como un patrón
CONTROLES = {"pruebas", "claude_review_local", "auditoria_skill"}


def datos_encargo(contexto=None, controles=None):
    """Etiquetas explícitas del productor; declarar un control no acredita su ejecución."""
    data = {}
    if contexto is not None:
        context = creencias._contexto(contexto)
        if context.get("tipo_trabajo") not in TIPOS | {SIN_CLASIFICAR}:
            raise k.Rechazo("contexto_desarrollo requiere un tipo_trabajo válido o sin_clasificar")
        data["contexto_desarrollo"] = context
    if controles is not None:
        if not isinstance(controles, list) or any(not isinstance(x, str) or x not in CONTROLES for x in controles):
            raise k.Rechazo("controles_declarados admite pruebas, claude_review_local y auditoria_skill")
        data["controles_declarados"] = list(dict.fromkeys(controles))
    return data


def analizar(pid):
    """Cuenta encargos declarados, separados por tipo, tecnología y área; máximo 500."""
    import patrones_evidencia

    with k._abrir(pid) as con:
        rows = con.execute(
            "SELECT * FROM nodo WHERE proyecto=? AND tipo='encargo' ORDER BY fecha DESC,id DESC LIMIT 501", (pid,)
        ).fetchall()
    groups = collections.defaultdict(list)
    unknown = 0
    for row in rows[:500]:
        node = k._fila(row)
        context = node["datos"].get("contexto_desarrollo", {})
        if (
            not isinstance(context, dict)
            or not isinstance(context.get("tipo_trabajo"), str)
            or context["tipo_trabajo"] not in TIPOS
        ):
            unknown += 1
            continue
        context = creencias._contexto(context)
        key = json.dumps(context, sort_keys=True)
        groups[key].append(node)
    respaldos = patrones_evidencia.controles_lote(pid, [node for nodes in groups.values() for node in nodes])
    patterns = []
    for key, nodes in sorted(groups.items()):
        declared = collections.Counter()
        for node in nodes:
            controls = node["datos"].get("controles_declarados", [])
            if isinstance(controls, list):
                declared.update({x for x in controls if isinstance(x, str) and x in CONTROLES})
        patterns.append(
            {
                "contexto": json.loads(key),
                "encargos": len(nodes),
                "fuentes": [n["id"] for n in nodes[:30]],
                "controles_declarados": dict(declared),
                "controles_evidencia": [respaldos[node["id"]] for node in nodes],
                "calidad": "no inferida; requiere resultados y revisión de evidencia",
            }
        )
    return {
        "proyecto": pid,
        "revisados": min(len(rows), 500),
        "muestra_parcial": len(rows) > 500,
        "sin_clasificar": unknown,
        "patrones": patterns,
    }


def registrar(pid, analysis):
    """Patrón repetido -> pregunta investigable, nunca receta universal ni checklist activo."""
    result = []
    with k._abrir(pid) as con:
        for pattern in analysis["patrones"]:
            if pattern["encargos"] < 2:
                continue
            digest = hashlib.sha256(json.dumps(pattern, sort_keys=True).encode()).hexdigest()
            evidence = k.crear_nodo(
                pid,
                "evidencia",
                "Patrón declarado de desarrollo; calidad no evaluada",
                {"clase": "patron_desarrollo", **pattern},
                autor="server",
                clave_ingesta="patron-desarrollo:" + digest,
                con=con,
            )
            belief = creencias.proponer(
                pid,
                {
                    "texto": "Investigar el flujo para " + pattern["contexto"]["tipo_trabajo"],
                    "accion": "Comparar alternativas de arquitectura, planificación y construcción con pruebas, "
                    "review local de Claude y auditoría; conservar los resultados y hallazgos pendientes",
                    "dimension": "olas",
                    "contexto": pattern["contexto"],
                    "fuentes": [evidence["id"]],
                    "excepciones": "La repetición no prueba eficacia. Los controles declarados no acreditan ejecución.",
                },
                autor="server",
                con=con,
            )
            result.append(belief["id"])
    return result
