"""Creencias operativas y checklist contextual sobre el grafo existente.

Una creencia es una decisión propuesta. Sólo un veredicto humano con evidencia
puede volverla vigente; el checklist vuelve a comprobar su respaldo en cada lectura
y explica por qué una creencia no aplica. El uso declarado vuelve como señal de revisión,
nunca como veredicto.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import aprendizaje
import conocimiento as k

DIMENSIONES = {"herramientas", "contexto", "memoria", "olas", "pruebas", "coordinacion", "capacidades"}
CONTEXTO = {"agente", "modelo", "fase", "tipo_trabajo", "tecnologia", "area", "version_agente", "version_modelo"}
USOS = {"sirvio", "no_aplico", "ya_sabido"}
MOTIVOS = {
    "aplicable": "Validada por una persona, vigente, con respaldo activo y del mismo contexto",
    "refutada": "Una persona la refutó o fue reemplazada",
    "sin_veredicto": "Es una propuesta: falta el veredicto de una persona con evidencia",
    "respaldo_retirado": "El vínculo con la evidencia del veredicto ya no está activo",
    "respaldo_caido": "Una fuente de la que depende fue rechazada o revertida",
    "vencida": "Pasó su fecha de vigencia",
    "contexto_insuficiente": "La consulta no informa un dato de contexto que la creencia exige",
    "fuera_de_contexto": "Exige otro contexto de trabajo",
    "contexto_invalido": "Su contexto registrado no es válido: requiere revisión",
}
# una fuente motiva la creencia por el grafo: así un rechazo posterior se ve como respaldo caído.
# La evidencia no tiene estado que caiga y `apoya` queda reservado al veredicto humano.
_FUENTES_QUE_MOTIVAN = {"hallazgo", "medicion", "incidente", "decision"}


def _contexto(value):
    if not isinstance(value, dict) or set(value) - CONTEXTO:
        raise k.Rechazo("contexto admite agente, modelo, fase, tipo_trabajo, tecnologia, area, version_agente y version_modelo")
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
    nodes = [k._nodo(con, pid, k._texto(source, "fuente", 64)) for source in sources]
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
    belief = k.crear_nodo(pid, "decision", text, payload, autor=autor, clave_ingesta="creencia:" + digest, con=con)
    # sólo al nacer: repetir la propuesta no reactiva un vínculo que alguien retiró
    for node in nodes if belief.get("creado") else []:
        if node["tipo"] in _FUENTES_QUE_MOTIVAN:
            k.vincular(pid, belief["id"], "motivada_por", node["id"], autor=autor, motivo="fuente de la creencia", con=con)
    return belief


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
        if result == "validada":
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


def _vigente(data, ahora=None):
    try:
        expires = dt.datetime.fromisoformat(data["vigente_hasta"])
    except KeyError, TypeError, ValueError:
        return False  # metadata ausente/inválida no acredita vigencia
    return expires.tzinfo is not None and expires > (ahora if ahora is not None else dt.datetime.now(dt.UTC))


def _evaluar(node, context, apoyos, cadenas, ahora=None):
    """El primer motivo por el que no aplica, en orden de gravedad, o `aplicable`, con las cadenas
    hasta un respaldo caído. `cadenas(id)` se llama sólo para las validadas con respaldo activo."""
    data = node["datos"]
    if node["estado"] in ("revertida", "reemplazada") or data.get("resultado") == "refutada":
        return "refutada", []
    if node["estado"] != "vigente" or data.get("resultado") != "validada" or not str(
        data.get("veredicto_por", "")
    ).startswith("persona:"):
        return "sin_veredicto", []
    if (node["id"], data.get("evidencia_veredicto")) not in apoyos:
        return "respaldo_retirado", []
    chains = cadenas(node["id"])
    return _vigencia(data, context, chains, ahora), chains


def _vigencia(data, context, chains, ahora=None):
    if chains:
        return "respaldo_caido"
    if not _vigente(data, ahora):
        return "vencida"
    required = data.get("contexto")
    if not isinstance(required, dict) or set(required) - CONTEXTO or not all(isinstance(v, str) for v in required.values()):
        return "contexto_invalido"  # metadata rota no se lee como «cualquier contexto»
    if any(key not in context for key in required):
        return "contexto_insuficiente"
    if any(context[key] != val for key, val in required.items()):
        return "fuera_de_contexto"
    return "aplicable"


def _usos(data):
    usos = data.get("usos") if isinstance(data.get("usos"), list) else []
    counts = {x: sum(1 for u in usos if isinstance(u, dict) and u.get("resultado") == x) for x in sorted(USOS)}
    # señal para que una persona la mire; nunca cambia el estado
    return counts, counts["no_aplico"] >= 2 and counts["no_aplico"] > counts["sirvio"]


def _item(node, state, chains):
    data = node["datos"]
    usos, revisar = _usos(data)
    item = {
        "creencia": node["id"],
        "texto": node["texto"],
        "accion": data.get("accion", ""),
        "dimension": data.get("dimension", ""),
        "estado": state,
        "motivo": MOTIVOS[state],
        "evidencia": data.get("evidencia_veredicto"),
        "excepciones": data.get("excepciones", ""),
        "vigente_hasta": data.get("vigente_hasta"),
        "contexto": data["contexto"] if isinstance(data.get("contexto"), dict) else {},
        "usos": usos,
        "revisar": revisar,
    }
    if chains:
        item["cadenas"] = chains
    return item


def evaluar(pid, context):
    """Cada creencia del proyecto con su estado para este contexto y el motivo, en una lectura."""
    context = _contexto(context)
    with k._abrir(pid) as con:
        con.execute("BEGIN")  # creencias, apoyos y respaldos de la misma foto: un veredicto en medio no se mezcla
        rows = con.execute(
            "SELECT * FROM nodo WHERE proyecto=? AND tipo='decision' "
            "AND json_extract(datos,'$.clase')='creencia_operativa' ORDER BY estado_fecha DESC,id",
            (pid,),
        ).fetchall()
        apoyos = {
            (row["de"], row["a"])
            for row in con.execute(
                "SELECT v.de, v.a FROM vinculo v JOIN nodo e ON e.id=v.a AND e.tipo='evidencia' AND e.proyecto=? "
                "WHERE v.relacion='apoya' AND v.activo=1",
                (pid,),
            )
        }
        nodes = [k._fila(row) for row in rows]
        # el subgrafo de respaldos se carga una vez y sólo si alguna creencia llega a necesitarlo
        grafo = []

        def cadenas(nid):
            if not grafo:
                grafo.append(aprendizaje._Respaldos(con, pid))
            return grafo[0].cadenas(nid) if nid in grafo[0].nodos else []

        evaluated = [(node, *_evaluar(node, context, apoyos, cadenas)) for node in nodes]
    return context, [_item(node, state, chains) for node, state, chains in evaluated]


def checklist(pid, context, *, limite=8):
    """Aplicables primero (hasta `limite`) y, aparte, por qué no aplican las demás."""
    if type(limite) is not int or not 1 <= limite <= 20:
        raise k.Rechazo("limite debe estar entre 1 y 20")
    context, evaluated = evaluar(pid, context)
    items = [x for x in evaluated if x["estado"] == "aplicable"]
    others = [x for x in evaluated if x["estado"] != "aplicable"]
    return {
        "proyecto": pid,
        "contexto": context,
        "total": len(items),
        "items": items[:limite],
        "no_aplican_total": len(others),
        "no_aplican": others[:50],
    }


def para_encargo(pid, task, *, limite=3):
    """Lo aplicable al contexto del encargo `task` (el nodo recién creado) y registra qué se mostró,
    no que se siguió. Devuelve (items, nodo actualizado)."""
    if task["tipo"] != "encargo":
        raise k.Rechazo("se requiere un encargo")
    context = task["datos"].get("contexto_desarrollo")
    if not isinstance(context, dict):
        return [], task
    items = checklist(pid, context, limite=limite)["items"]
    if items:
        shown = [{"creencia": x["creencia"], "evidencia": x["evidencia"], "fecha": k.ahora()} for x in items]
        task = k.actualizar_datos(pid, task["id"], {"aprendizajes_mostrados": shown}, por="server",
                                  motivo="aprendizajes aplicables mostrados al crear el encargo")
    return items, task


def texto_aprendizajes(items):
    """La sección que la coordinadora pega en el mensaje al frente."""
    if not items:
        return ""
    lines = ["## Aprendizajes aplicables del proyecto",
             "Validados por una persona para este tipo de trabajo. Si alguno no aplica, decilo en el informe."]
    for item in items:
        lines.append(f"- {item['accion']} (creencia {item['creencia']}, evidencia {item['evidencia']})")
        if item["excepciones"]:
            lines.append(f"  Excepciones: {item['excepciones']}")
    return "\n".join(lines)


def registrar_uso(pid, nid, data):
    """Si un aprendizaje mostrado sirvió: queda en su historial y sólo marca `revisar`."""
    por = k._texto(data.get("por"), "por", 200)
    if k.rol_de(por) not in (k.C, k.P) or not por.split(":", 1)[1].strip():
        raise k.Rechazo("el uso lo declara persona:<nombre> o coordinadora:<sesión>", 403)
    result = data.get("resultado")
    if not isinstance(result, str) or result not in USOS:
        raise k.Rechazo("resultado debe ser sirvio, no_aplico o ya_sabido")
    note = k._texto(data["nota"], "nota", 1000) if data.get("nota") else ""
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")  # leer y agregar a `usos` sin perder un uso concurrente
        node = _creencia(con, pid, nid)
        use = {"resultado": result, "por": por, "fecha": k.ahora(), "nota": note}
        if data.get("encargo") is not None:
            task = k._nodo(con, pid, k._texto(data["encargo"], "encargo", 64))
            if task["tipo"] != "encargo":
                raise k.Rechazo("encargo no es un encargo")
            use["encargo"] = task["id"]
        usos = node["datos"].get("usos") if isinstance(node["datos"].get("usos"), list) else []
        k.actualizar_datos(pid, nid, {"usos": [*usos, use][-100:]}, por=por, motivo="uso declarado: " + result, con=con)
        return k._nodo(con, pid, nid)
