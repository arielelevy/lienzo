"""Creencias operativas y checklist contextual sobre el grafo existente.

Una creencia es una decisión propuesta. Sólo un veredicto humano con evidencia
puede volverla vigente; el checklist vuelve a comprobar su respaldo en cada lectura.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import conocimiento as k

DIMENSIONES = {"herramientas", "contexto", "memoria", "olas", "pruebas", "coordinacion", "capacidades"}
CONTEXTO = {"agente", "modelo", "fase", "tipo_trabajo", "tecnologia", "area"}


def _contexto(value):
    if not isinstance(value, dict) or set(value) - CONTEXTO:
        raise k.Rechazo("contexto admite agente, modelo, fase, tipo_trabajo, tecnologia y area")
    return {key: k._texto(val, key, 100) for key, val in value.items()}


def _creencia(con, pid, nid):
    node = k._nodo(con, pid, nid)
    if node["tipo"] != "decision" or node["datos"].get("clase") != "creencia_operativa":
        raise k.Rechazo("el nodo no es una creencia operativa")
    return node


def proponer(pid, data, *, autor, con=None):
    """Propuesta idempotente con fuentes del mismo proyecto; sin aceptación implícita."""
    if con is None:
        with k._abrir(pid) as connection:
            return proponer(pid, data, autor=autor, con=connection)
    dimension = data.get("dimension")
    if not isinstance(dimension, str) or dimension not in DIMENSIONES:
        raise k.Rechazo("dimensión inválida")
    text = k._texto(data.get("texto"), "texto", 2000)
    action = k._texto(data.get("accion"), "accion", 1000)
    context = _contexto(data.get("contexto", {}))
    sources = data.get("fuentes")
    if not isinstance(sources, list) or not sources or len(sources) > 30:
        raise k.Rechazo("se requieren entre 1 y 30 fuentes")
    for source in sources:
        k._nodo(con, pid, k._texto(source, "fuente", 64))
    payload = {
        "clase": "creencia_operativa",
        "dimension": dimension,
        "accion": action,
        "contexto": context,
        "fuentes": sorted(set(sources)),
        "confianza": "sin validación empírica",
        "excepciones": data.get("excepciones", ""),
    }
    payload["excepciones"] = k._texto(payload["excepciones"], "excepciones", 2000) if payload["excepciones"] else ""
    digest = hashlib.sha256(json.dumps([text, payload], sort_keys=True).encode()).hexdigest()
    return k.crear_nodo(pid, "decision", text, payload, autor=autor, clave_ingesta="creencia:" + digest, con=con)


def resolver(pid, nid, data):
    """Validar o refutar conserva el historial y los vínculos, en una transacción."""
    por = k._texto(data.get("por"), "por", 200)
    if not por.startswith("persona:") or not por[8:].strip():
        raise k.Rechazo("el veredicto requiere persona:<nombre>", 403)
    motive = k._texto(data.get("motivo"), "motivo", 2000)
    result = data.get("resultado")
    if not isinstance(result, str) or result not in ("validada", "refutada"):
        raise k.Rechazo("resultado debe ser validada o refutada")
    with k._abrir(pid) as con:
        node = _creencia(con, pid, nid)
        evidence = k._nodo(con, pid, k._texto(data.get("evidencia"), "evidencia", 64))
        if evidence["tipo"] != "evidencia":
            raise k.Rechazo("el veredicto requiere un nodo evidencia")
        if result == "validada" and node["estado"] not in ("propuesta", "vigente"):
            raise k.Rechazo("una creencia refutada requiere una propuesta nueva", 409)
        k.vincular(pid, nid, "apoya", evidence["id"], autor=por, motivo=motive, con=con)
        fields = {
            "resultado": result,
            "evidencia_veredicto": evidence["id"],
            "confianza": "veredicto humano",
            "veredicto_por": por,
            "veredicto_fecha": k.ahora(),
        }
        if result == "validada":
            fields["vigente_hasta"] = _vencimiento(data.get("vigente_hasta"))
        k.actualizar_datos(pid, nid, fields, por=por, motivo=motive, con=con)
        k.cambiar_estado(pid, nid, "vigente" if result == "validada" else "revertida", por=por, motivo=motive, con=con)
        return k._nodo(con, pid, nid)


def _vencimiento(value):
    try:
        date = dt.datetime.fromisoformat(value)
        if date.tzinfo is None or date <= dt.datetime.now(dt.UTC):
            raise ValueError
    except TypeError, ValueError:
        raise k.Rechazo("vigente_hasta requiere una fecha futura con zona horaria") from None
    return date.isoformat()


def listar(pid):
    with k._abrir(pid) as con:
        rows = con.execute(
            "SELECT * FROM nodo WHERE proyecto=? AND tipo='decision' "
            "AND json_extract(datos,'$.clase')='creencia_operativa' ORDER BY fecha,id",
            (pid,),
        )
        return [k._fila(row) for row in rows]


def _aplica(data, context):
    if data.get("resultado") != "validada" or not data.get("veredicto_por", "").startswith("persona:"):
        return False
    if any(context.get(key) != val for key, val in data["contexto"].items()):
        return False
    try:
        expires = dt.datetime.fromisoformat(data["vigente_hasta"])
    except KeyError, TypeError, ValueError:
        return False  # metadata ausente/inválida no acredita vigencia
    return expires.tzinfo is not None and expires > dt.datetime.now(dt.UTC)


def _item(node):
    data = node["datos"]
    return {
        "creencia": node["id"],
        "accion": data["accion"],
        "dimension": data["dimension"],
        "evidencia": data["evidencia_veredicto"],
        "excepciones": data["excepciones"],
        "vigente_hasta": data["vigente_hasta"],
    }


def checklist(pid, context, *, limite=8):
    context = _contexto(context)
    if type(limite) is not int or not 1 <= limite <= 20:
        raise k.Rechazo("limite debe estar entre 1 y 20")
    with k._abrir(pid) as con:
        rows = con.execute(
            "SELECT b.* FROM nodo b JOIN vinculo v ON v.de=b.id AND v.relacion='apoya' AND v.activo=1 "
            "AND v.a=json_extract(b.datos,'$.evidencia_veredicto') "
            "JOIN nodo e ON e.id=v.a AND e.tipo='evidencia' AND e.proyecto=b.proyecto "
            "WHERE b.proyecto=? AND b.tipo='decision' AND b.estado='vigente' "
            "AND json_extract(b.datos,'$.clase')='creencia_operativa' ORDER BY b.estado_fecha DESC,b.id",
            (pid,),
        ).fetchall()
        nodes = [k._fila(row) for row in rows]
        items = [_item(node) for node in nodes if _aplica(node["datos"], context)]
        return {"proyecto": pid, "contexto": context, "total": len(items), "items": items[:limite]}
