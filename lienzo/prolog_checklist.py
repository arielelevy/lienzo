"""Checklist sostenido por el motor lógico (contrato 3, reglas de Lienzo como datos).

El checklist de `creencias` decide en Python qué creencia aplica a un contexto. Acá el motor
separado (motor-logico) recibe los hechos de la misma foto del grafo y estas reglas, y devuelve el
estado de cada creencia con su prueba. Una creencia entra al checklist sólo si las dos lecturas
coinciden en que aplica y el motor la sostiene: con una prueba que cierra contra los hechos
enviados y sin una regla cuestionada que derive de ella o de una decisión que la motiva. Lo que el
motor cuestiona, o donde las dos lecturas no coinciden, se marca como cuestionada con el porqué.
Sin motor el checklist sigue: cada ítem dice que no tiene contraste, nunca que el motor lo sostiene.
Nada se escribe: el veredicto sigue siendo de una persona."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import aprendizaje
import conocimiento as k
import creencias
import prolog_contraste as pc
import prolog_learning

REGLAS_VERSION = "checklist-1"
MAX_HECHOS = 20000
L, regla = pc._lit, pc._regla
NO = {"not": True}
B, E, F, K, M, N, R, S, T, V, W = "?B", "?E", "?F", "?K", "?M", "?N", "?R", "?S", "?T", "?V", "?W"
CAIDAS = sorted(aprendizaje.RESPALDOS_CAIDOS)
MOTIVO_CUESTIONADA = "Una regla que deriva de ella, o de una decisión que la motiva, quedó cuestionada"
MOTIVO_DISCREPA = "El motor lógico y Python no coinciden en que aplique: queda sin sostener hasta revisarla"

RULES = [
    # el orden de gravedad de creencias._evaluar: cada estado excluye a los anteriores por negación
    regla("refutada_revertida", L("refutada", B), L("creencia", B), L("nodo", B, "decision", "revertida")),
    regla("refutada_reemplazada", L("refutada", B), L("creencia", B), L("nodo", B, "decision", "reemplazada")),
    regla("refutada_veredicto", L("refutada", B), L("creencia", B), L("veredicto", B, "refutada")),
    regla(
        "con_veredicto",
        L("con_veredicto", B),
        L("nodo", B, "decision", "vigente"),
        L("veredicto", B, "validada"),
        L("por_persona", B),
    ),
    regla(
        "sin_veredicto", L("sin_veredicto", B), L("creencia", B), L("refutada", B, **NO), L("con_veredicto", B, **NO)
    ),
    regla("respaldada", L("respaldada", B), L("evidencia_veredicto", B, E), L("apoyo", B, E)),
    regla(
        "respaldo_retirado",
        L("respaldo_retirado", B),
        L("con_veredicto", B),
        L("refutada", B, **NO),
        L("respaldada", B, **NO),
    ),
    regla("activa", L("activa", B), L("con_veredicto", B), L("refutada", B, **NO), L("respaldada", B)),
    # la cadena de respaldos sigue sólo por decisiones que no cayeron, como aprendizaje._Respaldos
    regla("alcanza_directo", L("alcanza", B, F), L("activa", B), L("motiva", B, F)),
    regla(
        "alcanza_decision",
        L("alcanza", B, F),
        L("alcanza", B, M),
        L("nodo", M, "decision", S),
        L("caida", M, **NO),
        L("motiva", M, F),
    ),
    *(regla(f"caida_{t}_{s}", L("caida", F), L("nodo", F, t, s)) for t, s in CAIDAS),
    regla("respaldo_caido", L("respaldo_caido", B, F), L("alcanza", B, F), L("caida", F)),
    regla("con_caida", L("con_caida", B), L("respaldo_caido", B, F)),
    regla(
        "en_fecha",
        L("en_fecha", B),
        L("activa", B),
        L("con_caida", B, **NO),
        L("hasta", B, T),
        L("ahora", N),
        {"cmp": ">", "args": [T, N]},
    ),
    regla("vencida", L("vencida", B), L("activa", B), L("con_caida", B, **NO), L("en_fecha", B, **NO)),
    regla("invalido_clave", L("invalido", B), L("requiere", B, K, V), L("clave", K, **NO)),
    regla("invalido_valor", L("invalido", B), L("valor_no_texto", B)),
    regla("invalido_forma", L("invalido", B), L("contexto_no_objeto", B)),
    regla("contexto_invalido", L("contexto_invalido", B), L("en_fecha", B), L("invalido", B)),
    regla("ctx_ok", L("ctx_ok", B), L("en_fecha", B), L("invalido", B, **NO)),
    regla("informado", L("informado", K), L("dado", K, V)),
    regla("falta", L("falta", B), L("ctx_ok", B), L("requiere", B, K, V), L("informado", K, **NO)),
    regla("contexto_insuficiente", L("contexto_insuficiente", B), L("falta", B)),
    regla("coincide", L("coincide", B, K), L("requiere", B, K, V), L("dado", K, V)),
    regla(
        "distinto",
        L("distinto", B),
        L("ctx_ok", B),
        L("requiere", B, K, V),
        L("dado", K, W),
        L("coincide", B, K, **NO),
    ),
    regla("fuera_de_contexto", L("fuera_de_contexto", B), L("distinto", B), L("falta", B, **NO)),
    regla("aplicable", L("aplicable", B), L("ctx_ok", B), L("falta", B, **NO), L("distinto", B, **NO)),
    # una regla derivada de la creencia (o de una decisión vigente que la motiva) con recurrencia posterior
    regla(
        "cuestionada_directa",
        L("cuestionada", B, R),
        L("aplicable", B),
        L("deriva", R, B),
        L("nodo", R, "regla", "cuestionada"),
    ),
    regla(
        "cuestionada_por_decision",
        L("cuestionada", B, R),
        L("aplicable", B),
        L("alcanza", B, M),
        L("nodo", M, "decision", S),
        L("caida", M, **NO),
        L("deriva", R, M),
        L("nodo", R, "regla", "cuestionada"),
    ),
    regla("con_cuestion", L("con_cuestion", B), L("cuestionada", B, R)),
    regla("sostenida", L("sostenida", B), L("aplicable", B), L("con_cuestion", B, **NO)),
]
RULE_BY_ID = {r["id"]: r for r in RULES}
BASE = {
    "creencia",
    "nodo",
    "veredicto",
    "por_persona",
    "evidencia_veredicto",
    "apoyo",
    "motiva",
    "deriva",
    "hasta",
    "ahora",
    "clave",
    "dado",
    "requiere",
    "valor_no_texto",
    "contexto_no_objeto",
}
ESTADOS = tuple(creencias.MOTIVOS)  # un predicado por estado de creencias._evaluar
QUERIES = {
    **{s: ("B", "F") if s == "respaldo_caido" else ("B",) for s in ESTADOS},
    "cuestionada": ("B", "R"),
    "sostenida": ("B",),
}


def hechos(context, beliefs, apoyos, graph, deriva, ahora) -> list:
    """Los hechos de la foto: creencias, veredictos, apoyos, la cadena de respaldos que alcanzan y las
    reglas que derivan de ellas. Sólo los nodos alcanzables desde una creencia entran al motor."""
    facts = [L("clave", key) for key in sorted(creencias.CONTEXTO)]
    facts += [L("dado", key, val) for key, val in sorted(context.items())]
    facts.append(L("ahora", ahora.timestamp()))
    ids = {b["id"] for b in beliefs}
    alcanzados, frontera = set(ids), list(ids)
    while frontera:
        for nxt in graph.motiva.get(frontera.pop(), ()):
            if nxt not in alcanzados:
                alcanzados.add(nxt)
                frontera.append(nxt)
    for nid in sorted(alcanzados):
        nodo = graph.nodos.get(nid) or next(b for b in beliefs if b["id"] == nid)
        facts.append(L("nodo", nid, nodo["tipo"], nodo.get("estado") or pc.SIN_ESTADO))
        facts += [L("motiva", nid, a) for a in sorted(set(graph.motiva.get(nid, ())))]
    for rid, estado, origen in deriva:
        if origen in alcanzados:
            facts += [L("nodo", rid, "regla", estado or pc.SIN_ESTADO), L("deriva", rid, origen)]
    for b in beliefs:
        data, bid = b["datos"], b["id"]
        facts.append(L("creencia", bid))
        if isinstance(data.get("resultado"), str):
            facts.append(L("veredicto", bid, data["resultado"]))

        if str(data.get("veredicto_por", "")).startswith("persona:") and creencias._veredicto_evaluable(b):
            facts.append(L("por_persona", bid))
        if isinstance(data.get("evidencia_veredicto"), str):
            facts.append(L("evidencia_veredicto", bid, data["evidencia_veredicto"]))
        until = prolog_learning._epoch(data.get("vigente_hasta"))
        if until is not None:
            facts.append(L("hasta", bid, until))
        required = data.get("contexto")
        if not isinstance(required, dict):
            facts.append(L("contexto_no_objeto", bid))
        else:
            for key, val in sorted(required.items()):
                facts.append(L("requiere", bid, key, val) if isinstance(val, str) else L("valor_no_texto", bid))
    facts += [L("apoyo", de, a) for de, a in sorted(apoyos) if de in ids]
    # una regla dada dos veces con la misma forma es un solo hecho; se deduplica para el conteo
    unicos = {json.dumps(f, sort_keys=True): f for f in facts}
    return [{**f, "source": "grafo"} for f in unicos.values()]


def _modelo(facts: list) -> dict:
    """La misma semántica en Python, calculada desde los hechos y sin el motor. Sirve para comprobar
    las negaciones de cada prueba y como segunda lectura de las cuestionadas."""
    rel = {}
    for f in facts:
        rel.setdefault(f["pred"], set()).add(tuple(f["args"]))
    get = lambda p: rel.get(p, set())
    nodo = {n: (t, s) for n, t, s in get("nodo")}
    creencia = {b for (b,) in get("creencia")}
    veredicto = {b: r for b, r in get("veredicto")}
    persona = {b for (b,) in get("por_persona")}
    evid = {b: e for b, e in get("evidencia_veredicto")}
    ahora = next(iter(get("ahora")))[0]
    hasta = {b: t for b, t in get("hasta")}
    dado = {key: val for key, val in get("dado")}
    claves = {key for (key,) in get("clave")}
    requiere = {}
    for b, key, val in get("requiere"):
        requiere.setdefault(b, {})[key] = val
    motiva = {}
    for de, a in get("motiva"):
        motiva.setdefault(de, set()).add(a)
    caida = {n for n, ts in nodo.items() if ts in CAIDAS}

    refutada = {b for b in creencia if nodo[b][1] in ("revertida", "reemplazada") or veredicto.get(b) == "refutada"}
    con_veredicto = {
        b for b, (t, s) in nodo.items() if t == "decision" and s == "vigente" and veredicto.get(b) == "validada"
    } & persona
    respaldada = {b for b, e in evid.items() if (b, e) in get("apoyo")}
    activa = (con_veredicto - refutada) & respaldada

    def alcanza(b):
        out, pend, vistos = set(), list(motiva.get(b, ())), set()
        while pend:
            x = pend.pop()
            if x in out:
                continue
            out.add(x)
            if x in nodo and nodo[x][0] == "decision" and x not in caida and x not in vistos:
                vistos.add(x)
                pend.extend(motiva.get(x, ()))
        return out

    reach = {b: alcanza(b) for b in activa}
    caidos = {(b, f) for b in activa for f in reach[b] if f in caida}
    con_caida = {b for b, _ in caidos}
    en_fecha = {b for b in activa - con_caida if b in hasta and _numero(hasta[b]) and hasta[b] > ahora}
    invalido = (
        {b for b, keys in requiere.items() if set(keys) - claves}
        | {b for (b,) in get("valor_no_texto")}
        | {b for (b,) in get("contexto_no_objeto")}
    )
    ctx_ok = en_fecha - invalido
    falta = {b for b in ctx_ok if any(key not in dado for key in requiere.get(b, {}))}
    distinto = {b for b in ctx_ok if any(key in dado and dado[key] != val for key, val in requiere.get(b, {}).items())}
    aplicable = ctx_ok - falta - distinto
    # pares (regla, origen): una regla puede derivar de varias creencias o decisiones
    cuestionada_reglas = [(r, o) for r, o in get("deriva") if nodo.get(r) == ("regla", "cuestionada")]
    cuestionada = {
        (b, r)
        for b in aplicable
        for r, origen in cuestionada_reglas
        if origen == b or (origen in reach[b] and nodo.get(origen, ("",))[0] == "decision" and origen not in caida)
    }
    con_cuestion = {b for b, _ in cuestionada}
    uno = lambda xs: {(x,) for x in xs}
    return {
        "refutada": uno(refutada),
        "sin_veredicto": uno(creencia - refutada - con_veredicto),
        "respaldo_retirado": uno(con_veredicto - refutada - respaldada),
        "respaldo_caido": caidos,
        "vencida": uno(activa - con_caida - en_fecha),
        "contexto_invalido": uno(en_fecha & invalido),
        "contexto_insuficiente": uno(falta),
        "fuera_de_contexto": uno(distinto - falta),
        "aplicable": uno(aplicable),
        "cuestionada": cuestionada,
        "sostenida": uno(aplicable - con_cuestion),
        # los negados en RULES
        "con_veredicto": uno(con_veredicto),
        "respaldada": uno(respaldada),
        "caida": uno(caida),
        "con_caida": uno(con_caida),
        "en_fecha": uno(en_fecha),
        "invalido": uno(invalido),
        "informado": uno(dado),
        "falta": uno(falta),
        "coincide": {(b, key) for b, keys in requiere.items() for key, val in keys.items() if dado.get(key) == val},
        "distinto": uno(distinto),
        "con_cuestion": uno(con_cuestion),
    }


def _numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def consulta(facts: list) -> dict:
    return {
        "contract": 3,
        "domain": "logic",
        "facts": facts,
        "rules": RULES,
        "queries": [L(p, *("?" + v for v in vs)) for p, vs in QUERIES.items()],
        "explain": True,
        "limits": {"seconds": 5, "max_results": pc.MAX_RESULTADOS, "proof_depth": 64},
    }


def _foto(pid, context):
    """Python y los hechos del motor desde la misma transacción de lectura."""
    ahora = dt.datetime.now(dt.UTC)
    with k._abrir(pid) as con:
        con.execute("BEGIN")
        beliefs, apoyos = creencias._leer(con, pid)
        graph = aprendizaje._Respaldos(con, pid)
        deriva = con.execute(
            "SELECT r.id, r.estado, v.a FROM vinculo v JOIN nodo r ON r.id=v.de AND r.proyecto=? AND r.tipo='regla' "
            "WHERE v.relacion='derivada_de' AND v.activo=1 ORDER BY r.id, v.a",
            (pid,),
        ).fetchall()

        def cadenas(nid):
            return graph.cadenas(nid) if nid in graph.nodos else []

        evaluated = [(b, *creencias._evaluar(b, context, apoyos, cadenas, ahora=ahora)) for b in beliefs]
    facts = hechos(context, beliefs, apoyos, graph, [tuple(r) for r in deriva], ahora) if beliefs else []
    return evaluated, facts


def sostener(pid, context, *, esperar_wsl=True):
    """(contexto, ítems evaluados, informe del motor). Cada aplicable de Python queda sostenido con su
    prueba, cuestionado con su porqué, o sin contraste si el motor no respondió. Con `esperar_wsl=False`
    un WSL dormido no se despierta (el alta de un encargo no espera hasta 90 s): va sin contraste."""
    context = creencias._contexto(context)
    evaluated, facts = _foto(pid, context)
    items = [creencias._item(node, state, chains) for node, state, chains in evaluated]
    if not evaluated:
        return context, items, {"estado": "sin_creencias", "reglas": REGLAS_VERSION}
    if len(facts) > MAX_HECHOS:
        return context, _sin_contraste(items), _falla("no_disponible", f"la foto excede {MAX_HECHOS} hechos")
    payload = consulta(facts)
    python = _modelo(facts)  # una vez: comprueba las negaciones de cada prueba y es la segunda lectura
    try:
        output = pc.run(payload, despertar=esperar_wsl)
        found, why = pc.resultados(output, facts, (QUERIES, RULE_BY_ID, BASE, lambda _facts: python))
    except (prolog_learning.MotorError, k.Rechazo) as exc:  # sin motor, ocupado o demasiado grande
        return context, _sin_contraste(items), _falla("no_disponible", str(exc))
    except (ValueError, TypeError) as exc:
        return context, _sin_contraste(items), _falla("respuesta_invalida", f"Respuesta del motor inválida: {exc}")
    motor_estado = {}  # creencia -> estados que el motor le dedujo (respaldo_caido trae una fila por fuente)
    for state in ESTADOS:
        for bid in sorted({row[0] for row in found[state]}):
            motor_estado.setdefault(bid, []).append(state)
    diferencias = [
        {"creencia": item["creencia"], "python": item["estado"], "prolog": motor_estado.get(item["creencia"], [])}
        for item in items
        if motor_estado.get(item["creencia"]) != [item["estado"]]
    ] + [
        {"consulta": p, "solo_prolog": sorted(found[p] - python[p]), "solo_python": sorted(python[p] - found[p])}
        for p in ("cuestionada", "sostenida")
        if found[p] != python[p]
    ]
    for item in items:
        if item["estado"] != "aplicable":
            continue
        bid = item["creencia"]
        reglas = sorted(r for b, r in found["cuestionada"] if b == bid)
        sostenida = ("sostenida", (bid,)) in why and (bid,) in python["sostenida"]
        if reglas:
            item.update(estado="cuestionada", motivo=MOTIVO_CUESTIONADA)
            item["cuestionada_por"] = [{"regla": r, **why[("cuestionada", (bid, r))]} for r in reglas]
        elif not sostenida or motor_estado.get(bid) != ["aplicable"]:
            item.update(estado="cuestionada", motivo=MOTIVO_DISCREPA, sostenida=None)
        elif why[("sostenida", (bid,))]["prueba_truncada"]:
            item.update(estado="cuestionada", motivo="La prueba del motor se recortó por profundidad", sostenida=None)
        else:
            item["sostenida"] = why[("sostenida", (bid,))]
    return (
        context,
        items,
        {
            "estado": "sostenido" if not diferencias else "con_diferencias",
            "reglas": REGLAS_VERSION,
            "motor": output["engine"],
            "program_hash": output["program_hash"],
            "snapshot": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "hechos": len(facts),
            "diferencias": diferencias,
        },
    )


def _sin_contraste(items):
    for item in items:
        if item["estado"] == "aplicable":
            item["sostenida"] = None
    return items


def _falla(estado, error):
    return {"estado": estado, "reglas": REGLAS_VERSION, "error": error}


def checklist(pid, context, *, limite=8, esperar_wsl=True):
    """El checklist de creencias con el motor: aplicables sostenidas (o sin contraste, si no hay motor),
    cuestionadas aparte y por qué no aplica el resto."""
    creencias._limite(limite)
    context, items, motor = sostener(pid, context, esperar_wsl=esperar_wsl)
    for item in items:
        item["proyecto"] = pid
    extra = {}
    if pid != creencias.PROYECTO_LIENZO:
        # las de proceso de Lienzo valen para todos (revisión V-5): se evalúan y contrastan en su proyecto
        # dueño, con su motor, y se suman una vez; las propias de lienzo nunca salen de lienzo
        try:
            _, own, extra["motor_proceso"] = sostener(creencias.PROYECTO_LIENZO, context, esperar_wsl=esperar_wsl)
        except k.Rechazo:  # una PC sin el proyecto lienzo registrado no tiene aprendizaje de proceso
            own = []
        items += [{**x, "proyecto": creencias.PROYECTO_LIENZO} for x in own if x["alcance"] == "proceso_lienzo"]
    cuestionadas = [x for x in items if x["estado"] == "cuestionada"]
    out = creencias.armar(pid, context, [x for x in items if x["estado"] != "cuestionada"], limite=limite)
    import prolog_ciclo

    try:
        if not esperar_wsl and prolog_learning.dormido():
            externas, reuso = [], {"estado": "sin_motor", "motivo": "WSL dormido"}
        else:
            externas, reuso = prolog_ciclo.reusar(pid, context), {"estado": "evaluado"}
    except (prolog_ciclo.servicio.ErrorServicio, ValueError, k.Rechazo) as exc:
        externas, reuso = [], {"estado": "sin_contraste", "motivo": str(exc)}
    # Las propias y las de proceso conservan prioridad. No duplicar referencias ya presentes.
    refs = {(x.get("proyecto", pid), x["creencia"]) for x in items}
    externas = [x for x in externas if (x["proyecto"], x["creencia"]) not in refs]
    out["items"] = [*out["items"], *externas][:limite]
    out["total"] += len(externas)
    out["reuso"] = reuso
    # tres listas disjuntas: aplicables sostenidas, cuestionadas y las que no aplican con su motivo
    return {**out, "motor": motor, **extra, "cuestionadas_total": len(cuestionadas), "cuestionadas": cuestionadas[:50]}
