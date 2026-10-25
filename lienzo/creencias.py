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
CONTEXTO = {
    "agente",
    "modelo",
    "fase",
    "tipo_trabajo",
    "tecnologia",
    "area",
    "version_agente",
    "version_modelo",
    "tipo_archivo",
    "ruta",
}
USOS = {"sirvio", "no_aplico", "ya_sabido"}
# dos alcances (pedido de Ariel, 2026-10-22): lo propio de cada proyecto y cómo se trabaja con Lienzo
# (coordinación, frentes, verificación, releases), que vive en el proyecto `lienzo` y vale para todos
ALCANCES = {"proyecto", "proceso_lienzo"}
PROYECTO_LIENZO = "lienzo"
REVISIONES = {"aceptar", "rechazar", "corregir"}
REVISION_DIAS = 90  # la vigencia de lo aceptado en un clic; se renueva aceptándola de nuevo
MOTIVOS = {
    "aplicable": "Validada por una persona, vigente, con respaldo activo y del mismo contexto",
    "refutada": "Una persona la refutó",
    "reemplazada": "La reemplazó una versión corregida o fusionada; su evidencia sigue en la sucesora",
    "pendiente_validacion": "Lo observado está respaldado; falta medir si la acción sirve",
    "pendiente_evidencia": "Falta evidencia para decidir; no hay evidencia en contra",
    "pendiente_formalizacion": "Aceptada, pero falta formalizar su cláusula para el motor lógico",
    "sin_veredicto": "Es una propuesta: falta el veredicto de una persona con evidencia",
    "respaldo_retirado": "El vínculo con la evidencia del veredicto ya no está activo",
    "respaldo_caido": "Una fuente de la que depende fue rechazada o revertida",
    "vencida": "Pasó su fecha de vigencia",
    "contexto_insuficiente": "La consulta no informa un dato de contexto que la creencia exige",
    "fuera_de_contexto": "Exige otro contexto de trabajo",
    "contexto_invalido": "Su contexto registrado no es válido: requiere revisión",
}
# sólo en la vista del proyecto, sin contexto: no es un estado del checklist ni del motor lógico
MOTIVO_VIGENTE = "Validada por una persona, vigente y con respaldo activo"
# una fuente motiva la creencia por el grafo: así un rechazo posterior se ve como respaldo caído.
# La evidencia no tiene estado que caiga y `apoya` queda reservado al veredicto humano.
_FUENTES_QUE_MOTIVAN = {"hallazgo", "medicion", "incidente", "decision"}


def _contexto(value):
    if not isinstance(value, dict) or set(value) - CONTEXTO:
        raise k.Rechazo(
            "contexto admite agente, modelo, fase, tipo_trabajo, tecnologia, area, version_agente y version_modelo"
        )
    return {key: k._texto(val, key, 100) for key, val in value.items()}


def _alcance(pid, value):
    if not isinstance(value, str) or value not in ALCANCES:
        raise k.Rechazo("alcance debe ser proyecto o proceso_lienzo")
    if value == "proceso_lienzo" and pid != PROYECTO_LIENZO:
        raise k.Rechazo("las creencias de proceso de Lienzo viven en el proyecto lienzo")
    return value


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
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")  # buscar equivalente y anexar evidencia forman una operación
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
    # sin alcance vale «proyecto»: así la clave de una propuesta repetida no cambia respecto de las anteriores
    if _alcance(pid, data.get("alcance", "proyecto")) != "proyecto":
        payload["alcance"] = data["alcance"]
    if "regla_logica" in data:
        import prolog_programa

        try:
            prolog_programa.validar(data["regla_logica"])
        except ValueError as exc:
            raise k.Rechazo(f"regla_logica inválida: {exc}") from None
        payload["regla_logica"] = data["regla_logica"]
    if data.get("clave") is not None:
        # una medición que se repite (esperas, difusiones: una por noche) suma su observación a la creencia
        # abierta de la misma clave en vez de crear otra (2026-10-25: 10 copias de 2 observaciones)
        payload["clave"] = k._texto(data["clave"], "clave", 200)
        abierta = _abierta_por_clave(con, pid, payload["clave"])
        if abierta is not None:
            return _sumar_observacion(con, pid, abierta, text, nodes, sources, autor)
    digest = hashlib.sha256(json.dumps([text, payload], sort_keys=True).encode()).hexdigest()
    import metadatos_creencias

    payload["metadatos"] = metadatos_creencias.completar(
        pid, context, metadatos_creencias.relacionadas(con, pid, nodes)
    )
    import prolog_programa

    belief = prolog_programa.equivalente(con, pid, payload)
    if belief is None:
        belief = k.crear_nodo(pid, "decision", text, payload, autor=autor, clave_ingesta="creencia:" + digest, con=con)
    if not belief.get("creado") and payload.get("regla_logica"):
        previous = belief["datos"].get("fuentes", [])
        union = sorted(set(previous) | set(sources))
        if len(union) > 30:
            raise k.Rechazo("La propuesta equivalente supera las 30 fuentes; no se descarta evidencia", 409)
        observations = belief["datos"].get("observaciones", [])
        observation = {"texto": text, "fuentes": sorted(set(sources))}
        changed = union != previous or (text != belief["texto"] and observation not in observations)
        if text != belief["texto"] and observation not in observations:
            observations = [*observations, observation]
        if changed:
            metadata = metadatos_creencias.completar(
                pid,
                context,
                metadatos_creencias.relacionadas(con, pid, [k._nodo(con, pid, source) for source in union]),
            )
            belief = {
                **k.actualizar_datos(
                    pid,
                    belief["id"],
                    {"fuentes": union, "observaciones": observations, "metadatos": metadata},
                    por=autor,
                    motivo="evidencia adicional de propuesta equivalente",
                    con=con,
                ),
                "creado": False,
            }
            for node in nodes:
                if node["id"] not in previous and node["tipo"] in _FUENTES_QUE_MOTIVAN:
                    k.vincular(
                        pid, belief["id"], "motivada_por", node["id"], autor=autor, motivo="nueva evidencia", con=con
                    )
    # sólo al nacer: repetir la propuesta no reactiva un vínculo que alguien retiró
    for node in nodes if belief.get("creado") else []:
        if node["tipo"] in _FUENTES_QUE_MOTIVAN:
            k.vincular(
                pid, belief["id"], "motivada_por", node["id"], autor=autor, motivo="fuente de la creencia", con=con
            )
    return belief


def _abierta_por_clave(con, pid, clave):
    row = con.execute(
        "SELECT * FROM nodo WHERE proyecto=? AND tipo='decision' AND estado IN ('propuesta','vigente') "
        "AND json_extract(datos,'$.clase')='creencia_operativa' AND json_extract(datos,'$.clave')=? "
        "ORDER BY fecha,id LIMIT 1",
        (pid, clave),
    ).fetchone()
    return k._fila(row) if row else None


def _sumar_observacion(con, pid, belief, text, nodes, sources, autor):
    """La observación nueva y sus fuentes van a la creencia abierta de la misma clave. El texto de la creencia
    no cambia (lo revisado es ese); la última medición queda en `ultima_observacion` y todas en
    `observaciones`. Se conservan las 30 fuentes más nuevas, el tope de siempre."""
    previous = belief["datos"].get("fuentes", [])
    nuevas = [s for s in sources if s not in previous]
    if not nuevas:
        return {**belief, "creado": False}
    union = [*previous, *nuevas][-30:]
    observations = [*belief["datos"].get("observaciones", []), {"texto": text, "fuentes": sorted(set(sources))}][-30:]
    k.actualizar_datos(
        pid,
        belief["id"],
        {"fuentes": union, "observaciones": observations, "ultima_observacion": text},
        por=autor,
        motivo="la misma medición volvió a pasar su umbral",
        con=con,
    )
    for node in nodes:
        if node["id"] in nuevas and node["tipo"] in _FUENTES_QUE_MOTIVAN:
            k.vincular(pid, belief["id"], "motivada_por", node["id"], autor=autor, motivo="nueva medición", con=con)
    return {**k._nodo(con, pid, belief["id"]), "creado": False}


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
        evidence = k._texto(data.get("evidencia"), "evidencia", 64)
        until = data.get("vigente_hasta") if result == "validada" else None
        return _veredicto(con, pid, nid, por, result, evidence, motive, until)


def _veredicto(con, pid, nid, por, result, evidence_id, motive, until):
    """El veredicto dentro de la transacción de `con`; `until` sólo cuenta al validar. Refutar es por
    evidencia en contra: lo que no se pudo medir queda pendiente (`dejar_pendiente`), no refutado."""
    node = _creencia(con, pid, nid)
    evidence = k._nodo(con, pid, evidence_id)
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
    import prolog_programa

    fields["revision_veredicto"] = prolog_programa.revision(node)
    if evidence["datos"].get("clase") == "ia_delegada":
        fields.update(ia_delegada=True, confianza="veredicto IA delegada")
    elif "ia_delegada" in node["datos"]:
        fields["ia_delegada"] = False  # un veredicto humano posterior sustituye la delegación (AB/AA)
    if result == "validada":
        fields["vigente_hasta"] = _vencimiento(until)
        fields["pendiente"] = None  # un veredicto cierra lo que estaba pendiente
    k.actualizar_datos(pid, nid, fields, por=por, motivo=motive, con=con)
    k.cambiar_estado(pid, nid, "vigente" if result == "validada" else "revertida", por=por, motivo=motive, con=con)
    return k._nodo(con, pid, nid)


def _persona(data):
    por = k._texto(data.get("por"), "por", 200)
    if not por.startswith("persona:") or not por[8:].strip():
        raise k.Rechazo("el veredicto requiere persona:<nombre>", 403)
    return por


_MOTIVO_REVISION = {
    "aceptar": "aceptada en la revisión del proyecto",
    "rechazar": "rechazada en la revisión del proyecto",
    "corregir": "corregida en la revisión del proyecto",
}


def revisar(pid, nid, data):
    """Veredicto en un clic desde la vista del proyecto (pedido de Ariel, 2026-10-22): aceptar, rechazar o
    corregir. La evidencia es la revisión misma: un nodo `evidencia` de clase `revision_humana` firmado por la
    persona, con qué decidió y sobre qué texto, creado en la misma transacción que el veredicto (si algo
    falla no queda una revisión suelta). Aceptar una vigente la renueva sin acortar su vigencia. Corregir
    crea la sucesora (mismo contexto, dimensión y alcance, salvo que se cambie) ya validada, la vincula con
    `reemplaza` y retira la original."""
    por = _persona(data)
    action = data.get("accion")
    if not isinstance(action, str) or action not in REVISIONES:
        raise k.Rechazo("accion debe ser aceptar, rechazar o corregir")
    motive = k._texto(data["motivo"], "motivo", 2000) if data.get("motivo") else _MOTIVO_REVISION[action]
    new = {}
    if action == "corregir":
        new["accion"] = k._texto(data.get("accion_nueva"), "accion_nueva", 1000)
        if data.get("texto_nuevo"):
            new["texto"] = k._texto(data["texto_nuevo"], "texto_nuevo", 2000)
        if data.get("alcance") is not None:
            new["alcance"] = _alcance(pid, data["alcance"])
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")  # leer, dejar la revisión y decidir sin que otra persona se cruce
        node = _creencia(con, pid, nid)
        if node["estado"] not in ("propuesta", "vigente"):
            raise k.Rechazo("la creencia ya fue refutada o reemplazada: no se revisa de nuevo", 409)
        revision = {"creencia": nid, "estado": node["estado"], "texto": node["texto"], "decision": action}
        evidence = k.crear_nodo(
            pid,
            "evidencia",
            f"Revisión de {por[8:].strip()}: {action} «{node['datos'].get('accion') or node['texto']}»"[:2000],
            {"clase": "revision_humana", "revision": {**revision, "motivo": motive, "correccion": new}},
            autor=por,
            motivo="revisión de una creencia",
            con=con,
        )
        until = dt.datetime.now(dt.UTC) + dt.timedelta(days=REVISION_DIAS)
        if _vigente(node["datos"]):  # renovar nunca acorta lo que otra persona validó por más tiempo
            until = max(until, dt.datetime.fromisoformat(node["datos"]["vigente_hasta"]))
        until = until.isoformat()
        if action == "aceptar":
            return {"creencia": _veredicto(con, pid, nid, por, "validada", evidence["id"], motive, until)}
        if action == "rechazar":
            return {"creencia": _veredicto(con, pid, nid, por, "refutada", evidence["id"], motive, None)}
        datos = node["datos"]
        sources = [
            s
            for s in datos.get("fuentes") or []
            if isinstance(s, str) and con.execute("SELECT 1 FROM nodo WHERE id=? AND proyecto=?", (s, pid)).fetchone()
        ]
        successor = proponer(
            pid,
            {
                "dimension": datos.get("dimension"),
                "texto": new.get("texto", node["texto"]),
                "accion": new["accion"],
                "contexto": datos.get("contexto", {}),
                "fuentes": [*sources[:29], evidence["id"]],
                "excepciones": datos.get("excepciones", ""),
                "alcance": new.get("alcance", datos.get("alcance", "proyecto")),
            },
            autor=por,
            con=con,
        )
        successor = _veredicto(con, pid, successor["id"], por, "validada", evidence["id"], motive, until)
        k.vincular(pid, successor["id"], "reemplaza", nid, autor=por, motivo=motive, con=con)
        return {"creencia": reemplazar(con, pid, nid, successor["id"], por, motive), "nueva": successor}


def reemplazar(con, pid, nid, sucesora, por, motivo):
    """La original de una corrección queda `reemplazada`, no refutada (2026-10-25): su evidencia sigue en la
    sucesora, que la `reemplaza`. El vínculo se crea antes: el estado lo exige como respaldo."""
    k.actualizar_datos(pid, nid, {"reemplazada_por": sucesora}, por=por, motivo=motivo, con=con)
    k.cambiar_estado(pid, nid, "reemplazada", por=por, motivo=motivo, con=con)
    return k._nodo(con, pid, nid)


FALTAS = {"eficacia", "evidencia"}


def dejar_pendiente(con, pid, nid, por, falta, motivo, evidencia_id):
    """Ni aceptar ni refutar: lo observado puede estar respaldado y faltar medir si la acción sirve
    (`eficacia`), o faltar evidencia para decidir (`evidencia`). Sigue `propuesta`, con la marca y la
    evidencia de quién lo dijo; una revisión IA no la vuelve a mirar hasta que llegue evidencia nueva."""
    node = _creencia(con, pid, nid)
    if node["estado"] != "propuesta":
        raise k.Rechazo("sólo una propuesta queda pendiente", 409)
    if falta not in FALTAS:
        raise k.Rechazo("falta debe ser eficacia o evidencia")
    marca = {
        "falta": falta,
        "motivo": motivo,
        "evidencia": evidencia_id,
        "por": por,
        "fecha": k.ahora(),
        "fuentes": sorted(node["datos"].get("fuentes", [])),
    }
    k.actualizar_datos(pid, nid, {"pendiente": marca}, por=por, motivo=motivo, con=con)
    return k._nodo(con, pid, nid)


def cambiar_alcance(pid, nid, data):
    """Reclasifica una creencia entre proyecto y proceso de Lienzo sin recrearla ni tocar su veredicto: es
    su ámbito, no su validez. Lo hace una persona o la coordinadora."""
    por = k._texto(data.get("por"), "por", 200)
    if k.rol_de(por) not in (k.C, k.P) or not por.split(":", 1)[1].strip():
        raise k.Rechazo("el alcance lo cambia persona:<nombre> o coordinadora:<sesión>", 403)
    scope = _alcance(pid, data.get("alcance"))
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        _creencia(con, pid, nid)
        k.actualizar_datos(pid, nid, {"alcance": scope}, por=por, motivo="alcance: " + scope, con=con)
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


_EN_CURSO = ("pendiente", "enviado", "entregado", "verificando")


def contexto_sugerido(pid, session_id=None, tarjeta=None):
    """El contexto de trabajo para precompletar el aprendizaje (agregado de Ariel, 2026-10-22): el del
    encargo más nuevo que tomó la sesión y, si ése no aporta nada (o la sesión no tomó ninguno acá), el
    del encargo en curso más nuevo del proyecto; más agente y modelo de la tarjeta. `sin_clasificar`
    no se sugiere y los valores se recortan como los valida la API. Es una sugerencia: no escribe."""
    with k._abrir(pid) as con:
        rows = []
        if session_id:
            # por clave_ingesta, como _ronda_de_sesion: el id del nodo sesion cambia si cambia el remote
            rows += con.execute(
                "SELECT e.* FROM nodo s JOIN vinculo v ON v.a=s.id AND v.relacion='ejecutado_por' AND v.activo=1 "
                "JOIN nodo e ON e.id=v.de AND e.tipo='encargo' WHERE s.proyecto=? AND s.clave_ingesta=? "
                "ORDER BY e.fecha DESC, e.id DESC LIMIT 1",
                (pid, f"sesion:{session_id}"),
            ).fetchall()
        marcas = ",".join("?" * len(_EN_CURSO))
        rows += con.execute(
            f"SELECT * FROM nodo WHERE proyecto=? AND tipo='encargo' AND estado IN ({marcas}) "
            "AND json_extract(datos,'$.contexto_desarrollo.tipo_trabajo') IS NOT NULL "
            "AND json_extract(datos,'$.contexto_desarrollo.tipo_trabajo')!='sin_clasificar' "
            "ORDER BY fecha DESC, id DESC LIMIT 1",
            (pid, *_EN_CURSO),
        ).fetchall()
    context, task = {}, None
    for row in rows:  # el primero que aporte algo
        candidate = k._fila(row)
        datos = candidate["datos"] if isinstance(candidate["datos"], dict) else {}
        context = _sugeribles(datos.get("contexto_desarrollo"))
        if context:
            task = candidate
            break
    del_encargo = f"encargo {task['datos'].get('letra') or task['id'][:8]} ({task['estado']})" if task else None
    fuentes = dict.fromkeys(context, del_encargo)
    card = tarjeta or {}
    sid = card.get("session_id")
    de_tarjeta = f"la sesión {sid[:8]}" if isinstance(sid, str) and sid else "la sesión elegida"
    for key, campo in (("agente", "agent"), ("modelo", "model"), ("version_agente", "version")):
        val = card.get(campo)
        if isinstance(val, str) and val.strip():
            context[key] = val.strip()[:100]
            fuentes[key] = de_tarjeta
    fuente = del_encargo or (de_tarjeta if context else None)
    # cada dato dice de dónde salió (pedido de Ariel, 2026-10-22); `fuente` resume, para lo ya existente
    return {"contexto": context, "encargo": task["id"] if task else None, "fuente": fuente, "fuentes": fuentes}


def _sugeribles(raw):
    if not isinstance(raw, dict):
        return {}
    return {
        key: val.strip()[:100]
        for key, val in raw.items()
        if key in CONTEXTO and isinstance(val, str) and val.strip() and val.strip() != "sin_clasificar"
    }


def resumen():
    """Por proyecto, cuánto aprendizaje hay para mirar: creencias por estado, reglas cuestionadas y
    encargos con o sin tipo de trabajo. Sólo los que tienen algo; leer no cambia nada."""
    import patrones_desarrollo  # depende de este módulo

    names = {p["id"]: p.get("nombre") or p["id"] for p in k.proyectos()}
    with k._Conexion(k.db_path()) as con:
        con.execute("BEGIN")  # los tres conteos de la misma foto
        states = con.execute(
            "SELECT proyecto, estado, count(*) FROM nodo WHERE tipo='decision' "
            "AND json_extract(datos,'$.clase')='creencia_operativa' GROUP BY 1, 2"
        ).fetchall()
        questioned = con.execute(
            "SELECT proyecto, count(*) FROM nodo WHERE tipo='regla' AND estado='cuestionada' GROUP BY 1"
        ).fetchall()
        tasks = con.execute(
            "SELECT proyecto, json_extract(datos,'$.contexto_desarrollo.tipo_trabajo'), count(*) FROM nodo "
            "WHERE tipo='encargo' GROUP BY 1, 2"
        ).fetchall()
    out = {
        pid: {
            "proyecto": pid,
            "nombre": name,
            "creencias": {},
            "reglas_cuestionadas": 0,
            "encargos_clasificados": 0,
            "encargos_sin_clasificar": 0,
        }
        for pid, name in names.items()
    }
    for pid, state, n in states:
        if pid in out:
            out[pid]["creencias"][state] = n
    for pid, n in questioned:
        if pid in out:
            out[pid]["reglas_cuestionadas"] = n
    for pid, kind, n in tasks:
        if pid in out:
            typed = isinstance(kind, str) and kind != patrones_desarrollo.SIN_CLASIFICAR
            out[pid]["encargos_clasificados" if typed else "encargos_sin_clasificar"] += n
    return [x for x in out.values() if x["creencias"] or x["reglas_cuestionadas"] or x["encargos_clasificados"]]


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

    if node["estado"] == "reemplazada" or node.get("_reemplazada") or data.get("fusionada_en"):
        return "reemplazada", []
    if node["estado"] == "revertida" or data.get("resultado") == "refutada":
        return "refutada", []
    pendiente = data.get("pendiente")
    if node["estado"] == "propuesta" and isinstance(pendiente, dict):
        return ("pendiente_evidencia" if pendiente.get("falta") == "evidencia" else "pendiente_validacion"), []
    if (
        node["estado"] != "vigente"
        or data.get("resultado") != "validada"
        or not str(data.get("veredicto_por", "")).startswith("persona:")
        or not _veredicto_evaluable(node)
    ):
        return "sin_veredicto", []
    if (node["id"], data.get("evidencia_veredicto")) not in apoyos:
        return "respaldo_retirado", []
    chains = cadenas(node["id"])
    return _vigencia(data, context, chains, ahora), chains


def _contexto_guardado_valido(data):
    required = data.get("contexto")
    return (
        isinstance(required, dict)
        and not (set(required) - CONTEXTO)
        and all(isinstance(v, str) for v in required.values())
    )


def _veredicto_evaluable(node):
    import prolog_programa

    # Un contexto roto conserva su diagnóstico, después de respaldo y vigencia.
    return prolog_programa.veredicto_actual(node) or not _contexto_guardado_valido(node["datos"])


def _vigencia(data, context, chains, ahora=None):
    """`context` None: la vista del proyecto, que informa el contexto exigido sin exigirlo."""
    if chains:
        return "respaldo_caido"
    if not _vigente(data, ahora):
        return "vencida"
    required = data.get("contexto")
    if not _contexto_guardado_valido(data):
        return "contexto_invalido"  # metadata rota no se lee como «cualquier contexto»
    if context is None:
        return "vigente"
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
        "motivo": MOTIVO_VIGENTE if state == "vigente" else MOTIVOS[state],
        "evidencia": data.get("evidencia_veredicto"),
        "excepciones": data.get("excepciones", ""),
        "vigente_hasta": data.get("vigente_hasta"),
        "contexto": data["contexto"] if isinstance(data.get("contexto"), dict) else {},
        "alcance": data.get("alcance") if data.get("alcance") in ALCANCES else "proyecto",
        "usos": usos,
        "revisar": revisar,
    }
    if chains:
        item["cadenas"] = chains
    import prolog_ciclo

    temporal = prolog_ciclo.estado_actual(node)
    if temporal:
        item.update(
            estado="cuestionada", motivo="La reevaluación del motor requiere un nuevo veredicto", reevaluacion=temporal
        )
    elif (
        node["estado"] in ("propuesta", "vigente")
        and data.get("ia_delegada")
        and not data.get("regla_logica")
        and state not in ("pendiente_validacion", "pendiente_evidencia")  # la IA no la aceptó: no hay qué formalizar
    ):
        # aceptada por IA sin cláusula: falta formalizarla, no hay evidencia en contra (2026-10-25). Sigue fuera
        # del checklist hasta que el motor la pueda sostener, como antes
        item.update(estado="pendiente_formalizacion", motivo=MOTIVOS["pendiente_formalizacion"])
    if isinstance(data.get("pendiente"), dict) and item["estado"] in ("pendiente_validacion", "pendiente_evidencia"):
        item["pendiente"] = {
            key: data["pendiente"][key] for key in ("falta", "motivo", "fecha") if key in data["pendiente"]
        }
    if data.get("clave") and data.get("observaciones"):
        item["observaciones"] = len(data["observaciones"]) + 1
        item["ultima_observacion"] = data.get("ultima_observacion")
    found = data.get("contraste")
    if isinstance(found, dict) and isinstance(found.get("resultado"), str):
        # lo que el motor dijo de la propuesta al guardarla (S): una observación con fecha, no el estado actual
        item["contraste"] = {key: found[key] for key in _CONTRASTE if key in found}
    return item


_CONTRASTE = ("resultado", "motivo", "observaciones", "fecha", "motor")


def _leer(con, pid):
    """Las creencias del proyecto y sus apoyos activos a evidencia, dentro de la transacción de `con`."""
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
    # una revertida con sucesora (`reemplaza` activo que llega) fue corregida o fusionada, no refutada: así se
    # leen también las de antes de que una propuesta pudiera pasar a `reemplazada` (2026-10-25)
    reemplazadas = {
        row["a"]
        for row in con.execute(
            "SELECT v.a FROM vinculo v JOIN nodo n ON n.id=v.a AND n.proyecto=? "
            "WHERE v.relacion='reemplaza' AND v.activo=1",
            (pid,),
        )
    }
    nodes = [k._fila(row) for row in rows]
    for node in nodes:
        if node["id"] in reemplazadas:
            node["_reemplazada"] = True
    return nodes, apoyos


def evaluar(pid, context):
    """Cada creencia del proyecto con su estado para este contexto y el motivo, en una lectura."""
    context = _contexto(context)
    return context, _evaluadas(pid, context)


def _evaluadas(pid, context):
    return _evaluadas_con_reglas(pid, context)[0]


def _evaluadas_con_reglas(pid, context):
    """Las evaluadas y, de la misma foto, las reglas cuestionadas derivadas de cada creencia (V-4)."""
    with k._abrir(pid) as con:
        con.execute("BEGIN")  # creencias, apoyos y respaldos de la misma foto: un veredicto en medio no se mezcla
        nodes, apoyos = _leer(con, pid)
        questioned = {}
        for belief, rule in con.execute(
            "SELECT v.a, r.id FROM vinculo v JOIN nodo r ON r.id=v.de AND r.proyecto=? AND r.tipo='regla' "
            "AND r.estado='cuestionada' WHERE v.relacion='derivada_de' AND v.activo=1 ORDER BY r.id",
            (pid,),
        ):
            questioned.setdefault(belief, []).append(rule)
        # el subgrafo de respaldos se carga una vez y sólo si alguna creencia llega a necesitarlo
        grafo = []

        def cadenas(nid):
            if not grafo:
                grafo.append(aprendizaje._Respaldos(con, pid))
            return grafo[0].cadenas(nid) if nid in grafo[0].nodos else []

        evaluated = [(node, *_evaluar(node, context, apoyos, cadenas)) for node in nodes]
    return [_item(node, state, chains) for node, state, chains in evaluated], questioned


# lo que espera veredicto, arriba; lo cerrado, abajo
_ORDEN_VISTA = {
    "sin_veredicto": 0,
    "pendiente_evidencia": 1,
    "pendiente_validacion": 1,
    "pendiente_formalizacion": 1,
    "vigente": 2,
    "reemplazada": 4,
    "refutada": 4,
}


def _vista(pid):
    """Sin contexto, con lo que el motor dejó dicho (V-4): el contraste guardado de cada propuesta y las
    reglas derivadas que quedaron cuestionadas. La prueba actual del motor está en el filtro."""
    items, questioned = _evaluadas_con_reglas(pid, None)
    for item in items:
        item["reglas_cuestionadas"] = questioned.get(item["creencia"], [])
    return items


def vista_proyecto(pid):
    """El aprendizaje de un proyecto sin pedir contexto (pedido de Ariel, 2026-10-22: «el aprendizaje es por
    proyecto»): cada creencia con su estado propio y el contexto exigido como dato. Dos bloques: las del
    proyecto y las de cómo se trabaja con Lienzo (alcance proceso_lienzo del proyecto `lienzo`), que valen
    para todos; en `lienzo` las de proceso van sólo en su bloque. Leer no cambia nada."""
    own = _vista(pid)
    if pid == PROYECTO_LIENZO:
        process = [x for x in own if x["alcance"] == "proceso_lienzo"]
        own = [x for x in own if x["alcance"] != "proceso_lienzo"]
    else:
        try:
            process = [x for x in _vista(PROYECTO_LIENZO) if x["alcance"] == "proceso_lienzo"]
        except k.Rechazo:  # una PC sin el proyecto lienzo registrado no tiene aprendizaje de proceso
            process = []

    def block(items):
        items = sorted(items, key=lambda x: _ORDEN_VISTA.get(x["estado"], 3))
        return {"total": len(items), "items": items}

    return {"id": pid, "proyecto": block(own), "lienzo": block(process)}


def checklist(pid, context, *, limite=8):
    """Aplicables primero (hasta `limite`) y, aparte, por qué no aplican las demás."""
    _limite(limite)
    return armar(pid, *evaluar(pid, context), limite=limite)


def _limite(limite):
    if type(limite) is not int or not 1 <= limite <= 20:
        raise k.Rechazo("limite debe estar entre 1 y 20")


def armar(pid, context, evaluated, *, limite=8):
    """El checklist a partir de las creencias ya evaluadas (aquí o por el motor lógico)."""
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
    import prolog_checklist  # depende de este módulo

    context = task["datos"].get("contexto_desarrollo")
    if not isinstance(context, dict):
        return [], task
    # sin esperar el arranque de WSL: la coordinadora corta a los 20 s y su reintento sería 409
    items = prolog_checklist.checklist(pid, context, limite=limite, esperar_wsl=False)["items"]
    if items:
        shown = [
            {
                "creencia": x["creencia"],
                "evidencia": x["evidencia"],
                "sostenida": bool(x["sostenida"]),
                "proyecto": x.get("proyecto", pid),
                "fecha": k.ahora(),
            }
            for x in items
        ]
        task = k.actualizar_datos(
            pid,
            task["id"],
            {"aprendizajes_mostrados": shown},
            por="server",
            motivo="aprendizajes aplicables mostrados al crear el encargo",
        )
    return items, task


def texto_aprendizajes(items):
    """La sección que la coordinadora pega en el mensaje al frente."""
    if not items:
        return ""
    lines = [
        "## Aprendizajes aplicables del proyecto",
        "Validados por una persona para este tipo de trabajo. Si alguno no aplica, decilo en el informe.",
    ]
    for item in items:
        contraste = "" if item.get("sostenida") else "; sin contraste del motor lógico"
        # una de proceso vive en lienzo: el uso se declara allá (revisión V-5)
        dueno = f" del proyecto {item['proyecto']}" if item.get("alcance") == "proceso_lienzo" else ""
        lines.append(
            f"- {item['accion']} (creencia {item['creencia']}{dueno}, evidencia {item['evidencia']}{contraste})"
        )
        if item["excepciones"]:
            lines.append(f"  Excepciones: {item['excepciones']}")
    return "\n".join(lines)


def registrar_uso(pid, nid, data):
    """Si un aprendizaje mostrado sirvió: queda en su historial y sólo marca `revisar`."""
    if data.get("destino") is not None:
        import prolog_ciclo

        return prolog_ciclo.registrar_uso_destino(pid, nid, data["destino"], data)
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
