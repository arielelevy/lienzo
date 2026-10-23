"""Evaluación temporal y derivaciones con prueba, sin otorgar veredictos (AA)."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import aprendizaje
import conocimiento as k
import creencias as c
import prolog_contraste as pc
import prolog_learning as learning
import prolog_programa as programa
import prolog_servicio as servicio
from atomico import atomic_write

AUTOR = "server:prolog-ciclo"
L, R = pc._lit, pc._regla
B, E = "?B", "?E"
REGLAS = [
    R("temporal_alcanza", L("alcanza", B, E), L("creencia_temporal", B), L("motivada", B, E)),
    R(
        "temporal_alcanza_decision",
        L("alcanza", B, E),
        L("alcanza", B, "?D"),
        L("decision_sana", "?D"),
        L("motivada", "?D", E),
    ),
    R("temporal_respaldo", L("cuestionada", B, E), L("alcanza", B, E), L("fuente_caida", E)),
    R("temporal_retirado", L("cuestionada", B, E), L("retirado", B, E)),
    R("temporal_contradiccion", L("cuestionada", B, E), L("contradiccion_posterior", B, E)),
    R("temporal_delegada", L("cuestionada", B, E), L("delegada", B), L("incidente_posterior", B, E)),
    R("temporal_uso", L("cuestionada", B, B), L("usos_negativos", B, "?N"), {"cmp": ">=", "args": ["?N", 2]}),
    R("temporal_premisa", L("cuestionada", B, E), L("premisa_caida", B, E)),
    R("temporal_transitiva", L("cuestionada", B, E), L("depende", B, "?P"), L("cuestionada", "?P", E)),
    R(
        "deriva_ram",
        L("impedir", "?C", "?A", "ram"),
        L("escenario_ram", "?C", "?S", "?F", "?M"),
        L("recurso_necesita_gb", "?A", "?N"),
        {"cmp": "<", "args": ["?M", "?N"]},
    ),
]
METADATA = ("tecnologia", "tipo_archivo", "area", "fase", "tipo_trabajo")


class Cancelada(Exception):
    pass


revision = programa.revision


def _cancelar(cancelar):
    if cancelar():
        raise Cancelada("vuelta del motor cancelada; no se publicaron resultados")


def _sha(value):
    return hashlib.sha256(programa.canonico(value).encode()).hexdigest()


def estado_actual(node):
    if node["estado"] not in ("propuesta", "vigente"):
        return None
    data = node["datos"]
    reev = data.get("reevaluacion", {})
    if (
        reev.get("revision_evaluada") == revision(node)
        and reev.get("veredicto_fecha") == data.get("veredicto_fecha")
        and reev.get("estado") == "cuestionada"
        and reev.get("requiere_veredicto")
    ):
        return reev
    return None


def _leer_foto(con, owners):
    marks = ",".join("?" for _ in owners)
    nodes = [k._fila(r) for r in con.execute(f"SELECT * FROM nodo WHERE proyecto IN ({marks}) ORDER BY id", owners)]
    links = [
        dict(r)
        for r in con.execute(
            f"SELECT v.* FROM vinculo v JOIN nodo n ON n.id=v.de WHERE n.proyecto IN ({marks}) ORDER BY v.de,v.relacion,v.a",
            owners,
        )
    ]
    return nodes, links


def _foto(pid, owners=None):
    with k._abrir(pid) as con:
        con.execute("BEGIN")
        return _leer_foto(con, sorted(set(owners or [pid])))


def _beliefs(nodes):
    return [n for n in nodes if n["tipo"] == "decision" and n["datos"].get("clase") == "creencia_operativa"]


def _vigente(node, links):
    d = node["datos"]
    return (
        node["estado"] == "vigente"
        and programa.veredicto_actual(node)
        and d.get("resultado") == "validada"
        and str(d.get("veredicto_por", "")).startswith("persona:")
        and c._vigente(d)
        and any(
            v["de"] == node["id"]
            and v["relacion"] == "apoya"
            and v["a"] == d.get("evidencia_veredicto")
            and v["activo"]
            for v in links
        )
        and estado_actual(node) is None
    )


def _posterior(node, belief):
    fecha = learning._epoch(node.get("fecha"))
    desde = learning._epoch(belief["datos"].get("veredicto_fecha"))
    return fecha is not None and desde is not None and fecha > desde


def _facts(nodes, links, habilitadas=None):
    import prolog_hechos

    facts, byid = [], {n["id"]: n for n in nodes}
    for belief in _beliefs(nodes):
        facts.extend(prolog_hechos.desde_creencia(belief))
    for n in nodes:
        fallen = (n["tipo"], n["estado"]) in aprendizaje.RESPALDOS_CAIDOS
        if fallen:
            facts.append(L("fuente_caida", n["id"]))
        elif n["tipo"] == "decision":
            facts.append(L("decision_sana", n["id"]))
    facts.extend(L("motivada", v["de"], v["a"]) for v in links if v["activo"] and v["relacion"] == "motivada_por")
    active = {n["id"] for n in _beliefs(nodes) if _vigente(n, links)}
    if habilitadas is not None:
        active &= habilitadas
    for b in _beliefs(nodes):
        bid, data = b["id"], b["datos"]
        if b["estado"] == "vigente":
            facts.append(L("creencia_temporal", bid))
            ev = data.get("evidencia_veredicto")
            if isinstance(ev, str) and not any(
                v["de"] == bid and v["a"] == ev and v["relacion"] == "apoya" and v["activo"] for v in links
            ):
                facts.append(L("retirado", bid, ev))
            if data.get("ia_delegada") or byid.get(ev, {}).get("datos", {}).get("clase") == "ia_delegada":
                facts.append(L("delegada", bid))
            uses = {
                u.get("encargo", str(i))
                for i, u in enumerate(data.get("usos", []))
                if isinstance(u, dict)
                and u.get("resultado") == "no_aplico"
                and (learning._epoch(u.get("fecha")) or 0) > (learning._epoch(data.get("veredicto_fecha")) or 0)
            }
            facts.append(L("usos_negativos", bid, len(uses)))
            for n in nodes:
                if n["tipo"] not in ("incidente", "evidencia", "hallazgo") or not _posterior(n, b):
                    continue
                if bid in n["datos"].get("contradice_creencias", []):
                    facts.append(L("contradiccion_posterior", bid, n["id"]))
                if bid in n["datos"].get("creencias_afectadas", []) and n["tipo"] == "incidente":
                    facts.append(L("incidente_posterior", bid, n["id"]))
        for prem in data.get("derivacion", {}).get("premisas", []):
            facts.append(L("depende", bid, prem["id"]))
            source = byid.get(prem["id"])
            if source is None or source["id"] not in active or revision(source) != prem["revision"]:
                facts.append(L("premisa_caida", bid, prem["id"]))
        if bid in active:
            facts.append(L("creencia_habilitada", bid))
    # Conflictos explícitos del grafo: elegir y descartar la misma alternativa vigente.
    choices = [v for v in links if v["activo"] and v["relacion"] in ("elige", "descarta") and v["de"] in active]
    for a in choices:
        for b in choices:
            if a["a"] == b["a"] and a["relacion"] != b["relacion"]:
                facts.append(L("contradiccion_posterior", a["de"], b["de"]))
    return [{**f, "source": "memoria"} for f in facts]


def _validar_hechos(facts):
    out = []
    if not isinstance(facts, list) or len(facts) > 20000:
        raise ValueError("hechos inválidos o demasiados")
    for f in facts:
        if not isinstance(f, dict) or f.get("pred") not in programa.VOCABULARIO:
            raise ValueError("hecho fuera del vocabulario")
        if "vigente_hasta" in f:
            until = learning._epoch(f["vigente_hasta"])
            if until is None:
                raise ValueError("hecho con vencimiento inválido")
            if until <= dt.datetime.now(dt.UTC).timestamp():
                continue
        args = f.get("args")
        if not isinstance(args, list) or any(programa._variable(x) for x in args):
            raise ValueError("los hechos deben ser ground")
        if len(args) != len(programa.VOCABULARIO[f["pred"]]):
            raise ValueError("aridad inválida en hecho")
        programa._tipos(f, {})
        out.append({"pred": f["pred"], "args": args, "source": "observacion"})
    return out


def _reglas(nodes):
    out = list(REGLAS)
    policy = programa.validar(politica_recursos()["regla_logica"])
    out.append({"id": "politica_conservadora_recursos", **policy})
    for b in _beliefs(nodes):
        data = b["datos"]
        if data.get("regla_logica") is not None:
            ast = programa.validar(data["regla_logica"])
            out.append(
                {
                    "id": "creencia_" + b["id"],
                    "head": ast["head"],
                    "body": [L("creencia_habilitada", b["id"]), *ast["body"]],
                }
            )
    return out


def _resolver(facts, rules, queries, *, archivos=None, cancelar=lambda: False, negables=None):
    own = [r for r in rules if not archivos or not r["id"].startswith("creencia_")]
    payload = {
        "contract": 3,
        "domain": "logic",
        "facts": facts,
        "rules": own,
        "queries": queries,
        "explain": True,
        "limits": {"seconds": 5, "proof_depth": 64, "max_results": 1000},
    }
    result = servicio.consultar(payload, archivos=archivos, cancelar=cancelar)
    if not isinstance(result, dict) or result.get("contract") != 3 or not result.get("consistent"):
        raise ValueError("respuesta inconsistente del motor")
    answers = result.get("answers")
    if not isinstance(answers, list) or len(answers) != len(queries):
        raise ValueError("respuesta incompleta del motor")
    given = {(f["pred"], tuple(f["args"])) for f in facts}
    byrule = {r["id"]: r for r in rules}
    for query, ans in zip(queries, answers, strict=True):
        if ans.get("pred") != query["pred"] or ans.get("truncated") is not False:
            raise ValueError("respuesta truncada o fuera de consulta")
        rows = ans.get("results")
        if not isinstance(rows, list) or ans.get("count") != len(rows):
            raise ValueError("conteo de respuestas inválido")
        for row in rows:
            binding = row.get("bindings", {})
            expected = {
                "pred": query["pred"],
                "args": [binding.get(x[1:]) if programa._variable(x) else x for x in query["args"]],
            }
            proof = row.get("proof", {})
            if proof.get("fact") != expected or pc._prueba(
                proof, given, negables or {}, reglas=byrule, base={f["pred"] for f in facts}
            ):
                raise ValueError("prueba incompleta o de otra conclusión")
    return result


def _premisas(proof):
    out = set()
    if proof.get("rule", "").startswith("creencia_"):
        out.add(proof["rule"][len("creencia_") :])
    for p in proof.get("premises", []):
        out.update(_premisas(p))
    return out


def _evaluaciones(nodes, answers, snap, motor):
    observations = {}
    for row in answers:
        bid, ev = row["bindings"]["B"], row["bindings"]["E"]
        observations.setdefault(bid, []).append((ev, row["proof"]))
    out = {}
    for b in _beliefs(nodes):
        if b["estado"] != "vigente" and not b["datos"].get("derivacion"):
            continue
        items = observations.get(b["id"], [])
        old = estado_actual(b)
        questioned = bool(items or old)
        status = "cuestionada" if questioned else "sostenida"
        if not questioned and not b["datos"].get("regla_logica"):
            status = "datos_insuficientes"
        out[b["id"]] = {
            "estado": status,
            "requiere_veredicto": questioned,
            "revision_evaluada": revision(b),
            "veredicto_fecha": b["datos"].get("veredicto_fecha"),
            "snapshot": snap,
            "fecha": k.ahora(),
            "motivos": sorted({p["rule"] for _, p in items}) if items else (old or {}).get("motivos", []),
            "evidencias": sorted({ev for ev, _ in items}) if items else (old or {}).get("evidencias", []),
            "prueba": [p for _, p in items] if items else (old or {}).get("prueba", []),
            "motor": motor,
        }
    return out


def _preparar_derivacion(pid, contexto):
    local, _ = _foto(pid)
    externas = reusar(pid, contexto) if contexto else []
    owners = {pid, *(x["proyecto"] for x in externas)}
    for b in _beliefs(local):
        owners.update(p["proyecto"] for p in b["datos"].get("derivacion", {}).get("premisas", []))
    if any(p["id"] == "lienzo" for p in k.proyectos()):
        owners.add("lienzo")
    nodes, links = _foto(pid, owners)
    allowed = {b["id"] for b in _beliefs(nodes) if b["proyecto"] == pid}
    allowed.update(
        b["id"] for b in _beliefs(nodes) if b["proyecto"] == "lienzo" and b["datos"].get("alcance") == "proceso_lienzo"
    )
    selected = {(e["proyecto"], e["creencia"]): e["revision"] for e in externas}
    allowed.update(b["id"] for b in _beliefs(nodes) if selected.get((b["proyecto"], b["id"])) == revision(b))
    files = {}
    for owner in sorted(owners):
        for f in programa.archivos(owner):
            files[f["path"]] = f
    return nodes, links, allowed, sorted(owners), list(files.values())


def _guardar_derivada(con, context, pred, row):
    pid, byid, evaluated = context["pid"], context["byid"], context["evaluated"]
    prem = sorted(_premisas(row["proof"]))
    if len(prem) < 2 or any(evaluated.get(x, {}).get("estado") == "cuestionada" for x in prem):
        return None
    proof = {
        "regla": row["proof"]["rule"],
        "premisas": [{"proyecto": byid[x]["proyecto"], "id": x, "revision": revision(byid[x])} for x in prem],
        "hechos": context["hechos"],
        "prueba": row["proof"],
        "snapshot": context["snapshot"],
        "program_hash": context["program_hash"],
    }
    key = "derivada:" + _sha([pred, row["bindings"], [(x, revision(byid[x])) for x in prem]])
    evidence = k.crear_nodo(
        pid,
        "evidencia",
        "Cadena de prueba de una conclusión derivada",
        {
            "clase": "derivacion_logica",
            "derivacion": proof,
        },
        autor=AUTOR,
        clave_ingesta="prueba:" + _sha([key, row["proof"]]),
        con=con,
    )
    import metadatos_creencias

    own = [x for x in prem if byid[x]["proyecto"] == pid]
    payload = {
        "clase": "creencia_operativa",
        "dimension": "memoria",
        "contexto": context["contexto"],
        "fuentes": [evidence["id"], *own],
        "accion": f"Revisar la conclusión {pred}: {programa.canonico(row['bindings'])}",
        "tipo_propuesta": "derivada",
        "derivacion": proof,
        "confianza": "deducción; espera veredicto",
        "metadatos": metadatos_creencias.completar(pid, context["contexto"], [byid[x] for x in prem]),
    }
    root = context["reglas"][row["proof"]["rule"]]
    payload["regla_logica"] = programa.desde_ast(
        {"head": root["head"], "body": [item for item in root["body"] if item.get("pred") != "creencia_habilitada"]}
    )
    node = k.crear_nodo(
        pid,
        "decision",
        f"Derivada: {pred} {programa.canonico(row['bindings'])}",
        payload,
        autor=AUTOR,
        clave_ingesta=key,
        con=con,
    )
    if not node.get("creado"):
        fuentes = sorted(set(node["datos"].get("fuentes", [])) | {evidence["id"]})
        k.actualizar_datos(
            pid,
            node["id"],
            {"fuentes": fuentes, "derivacion": proof},
            por=AUTOR,
            motivo="prueba adicional de la misma conclusión",
            con=con,
        )
    for source in own if node.get("creado") else []:
        k.vincular(pid, node["id"], "motivada_por", source, autor=AUTOR, motivo="premisa de derivación", con=con)
    return node["id"]


def vuelta(pid, *, hechos=None, contexto=None, cancelar=lambda: False):
    _cancelar(cancelar)
    contexto = contexto or {}
    nodes, links, allowed, owners, files = _preparar_derivacion(pid, contexto)
    beliefs = _beliefs(nodes)
    if not beliefs:
        return {"cuestionadas": [], "derivadas": [], "creencias": 0, "estado": "sin_creencias"}
    facts = _facts(nodes, links, allowed) + _validar_hechos(hechos or [])
    rules = _reglas(nodes)
    snap = _sha([nodes, links, facts])
    result = _resolver(
        facts,
        rules,
        [L("cuestionada", "?B", "?E"), L("impedir", "?C", "?A", "?M"), L("recomendar", "?C", "?A", "?M")],
        archivos=files,
        cancelar=cancelar,
    )
    _cancelar(cancelar)
    evaluated = _evaluaciones(nodes, result["answers"][0]["results"], snap, result["engine"])
    derived = []
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        current, current_links = _leer_foto(con, owners)
        if _sha([current, current_links]) != _sha([nodes, links]):
            raise k.Rechazo("La memoria cambió durante la reevaluación; no se publicó", 409)
        _cancelar(cancelar)
        for bid, evaluation in evaluated.items():
            if next(b for b in beliefs if b["id"] == bid)["proyecto"] != pid:
                continue
            k.actualizar_datos(
                pid, bid, {"reevaluacion": evaluation}, por=AUTOR, motivo="reevaluación temporal", con=con
            )
        byid = {b["id"]: b for b in beliefs}
        context = {
            "pid": pid,
            "byid": byid,
            "evaluated": evaluated,
            "hechos": hechos or [],
            "contexto": contexto,
            "snapshot": snap,
            "program_hash": result["program_hash"],
            "reglas": {r["id"]: r for r in rules},
        }
        for ans in result["answers"][1:]:
            for row in ans["results"]:
                nid = _guardar_derivada(con, context, ans["pred"], row)
                if nid is not None:
                    derived.append(nid)
        _cancelar(cancelar)
    policies = [row for row in result["answers"][1]["results"] if row["bindings"]["M"] == "politica_conservadora"]
    return {
        "cuestionadas": sorted(
            b for b, e in evaluated.items() if e["estado"] == "cuestionada" and byid[b]["proyecto"] == pid
        ),
        "derivadas": derived,
        "creencias": len(beliefs),
        "estado": "evaluado",
        "program_hash": result["program_hash"],
        "politicas": [{**politica_recursos(), "prueba_condiciones": row["proof"]} for row in policies],
    }


def politica_recursos():
    """Política autorizada, separada de lo que demuestran las mediciones disponibles."""
    return {
        "tipo": "politica_conservadora",
        "requiere_veredicto": False,
        "origen": "Ariel aprobó el diseño AA el 2026-10-22; umbral conservador hasta medir 2 y 3 frentes",
        "pendiente_medicion": [2, 3],
        "actividades": ["investigador", "pruebas_wsl"],
        "texto": "Con Chrome en uso y más de 2 frentes, no lanzar investigador ni pruebas WSL",
        "regla_logica": {
            "version": 1,
            "vocabulario": 1,
            "clausula": "impedir(C, investigador_y_pruebas_wsl, politica_conservadora) :- chrome_en_uso(C), frentes_activos(C, N), N > 2.",
        },
    }


def generalizar(pid, *, cancelar=lambda: False):
    """La IA propone el principio; Prolog agrupa sus casos, sin probar una ley universal."""
    _cancelar(cancelar)
    nodes, _ = _foto(pid)
    beliefs = _beliefs(nodes)
    byid = {b["id"]: b for b in beliefs}
    candidates = [
        b
        for b in beliefs
        if b["datos"].get("principio") is True
        and b["estado"] in ("propuesta", "vigente")
        and len(set(b["datos"].get("ejemplos", []))) >= 2
    ]
    if not candidates:
        return {"principios": [], "estado": "sin_candidatos"}
    facts = []
    for b in beliefs:
        if b["estado"] in ("propuesta", "vigente"):
            facts.append(L("dimension_caso", b["id"], b["datos"]["dimension"]))
    for b in candidates:
        facts.append(L("principio_candidato", b["id"]))
        for example in sorted(set(b["datos"]["ejemplos"])):
            if example in byid and example != b["id"]:
                facts.append(L("ejemplo_de", b["id"], example))
    rules = [
        R(
            "generalizacion_caso",
            L("apoyo_inductivo", "?P", "?E"),
            L("principio_candidato", "?P"),
            L("ejemplo_de", "?P", "?E"),
            L("dimension_caso", "?P", "?D"),
            L("dimension_caso", "?E", "?D"),
        )
    ]
    result = _resolver(
        [{**f, "source": "casos"} for f in facts], rules, [L("apoyo_inductivo", "?P", "?E")], cancelar=cancelar
    )
    found = {}
    for row in result["answers"][0]["results"]:
        found.setdefault(row["bindings"]["P"], []).append(row)
    saved = []
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        for b in candidates:
            rows = found.get(b["id"], [])
            expected = set(b["datos"]["ejemplos"])
            if {r["bindings"]["E"] for r in rows} != expected:
                continue  # ejemplos incompatibles/no existentes no acreditan la agrupación
            if any(k._nodo(con, pid, nid) != byid[nid] for nid in [b["id"], *expected]):
                raise k.Rechazo("Cambió un caso durante la generalización; no se publicó", 409)
            _cancelar(cancelar)
            k.actualizar_datos(
                pid,
                b["id"],
                {
                    "generalizacion": {
                        "tipo": "inductiva",
                        "ejemplos": sorted(expected),
                        "pruebas": [r["proof"] for r in rows],
                        "confianza": "agrupación de casos; no prueba universal",
                        "requiere_veredicto": True,
                        "program_hash": result["program_hash"],
                    }
                },
                por=AUTOR,
                motivo="agrupación inductiva de ejemplos",
                con=con,
            )
            saved.append(b["id"])
    return {"principios": saved, "estado": "propuestos"}


def reusar(pid, context):
    out, candidates, facts, missing, omitted = [], {}, [], set(), set()
    for key, val in context.items():
        if isinstance(val, str):
            facts.append(L("contexto_reuso", key, val))
    for project in k.proyectos():
        owner = project["id"]
        if owner == pid:
            continue
        nodes, links = _foto(owner)
        supported = {x["creencia"] for x in c._evaluadas(owner, None) if x["estado"] == "vigente"}
        for b in _beliefs(nodes):
            if owner == c.PROYECTO_LIENZO and b["datos"].get("alcance") != "proceso_lienzo":
                continue  # las reglas propias del tablero no se exportan como aprendizaje de otros proyectos
            if b["id"] not in supported or not _vigente(b, links):
                continue
            candidates[b["id"]] = b
            facts.append(L("candidata_reuso", b["id"]))
            metadata = b["datos"].get("metadatos", {})
            required = {key: metadata[key] for key in METADATA if isinstance(metadata.get(key), list) and metadata[key]}
            for key, vals in required.items():
                for val in vals:
                    facts.append(L("requisito_reuso", b["id"], key, val))
                if context.get(key) not in vals:
                    missing.add((b["id"],))
            count = len(
                {
                    u["clave"]
                    for u in b["datos"].get("usos_destino", [])
                    if u["destino"] == pid and u["resultado"] == "no_aplico" and u["revision"] == revision(b)
                }
            )
            facts.append(L("negativos_reuso", b["id"], count))
            if count >= 2:
                omitted.add((b["id"],))
    if not candidates:
        return []
    rules = [
        R("reuso_con_metadata", L("tiene_metadata", B), L("requisito_reuso", B, "?K", "?V")),
        R("reuso_clave", L("clave_reuso", B, "?K"), L("requisito_reuso", B, "?K", "?V")),
        R(
            "reuso_coincide",
            L("coincide_reuso", B, "?K"),
            L("requisito_reuso", B, "?K", "?V"),
            L("contexto_reuso", "?K", "?V"),
        ),
        R("reuso_falta", L("falta_reuso", B), L("clave_reuso", B, "?K"), L("coincide_reuso", B, "?K", **{"not": True})),
        R("reuso_omitida", L("omitida_reuso", B), L("negativos_reuso", B, "?N"), {"cmp": ">=", "args": ["?N", 2]}),
        R(
            "reuso_aplicable",
            L("aplicable_externa", B),
            L("candidata_reuso", B),
            L("tiene_metadata", B),
            L("falta_reuso", B, **{"not": True}),
            L("omitida_reuso", B, **{"not": True}),
        ),
    ]
    matches = {
        (b["id"], key)
        for b in candidates.values()
        for key in METADATA
        if context.get(key) in b["datos"].get("metadatos", {}).get(key, [])
    }
    result = _resolver(
        [{**f, "source": "contexto"} for f in facts],
        rules,
        [L("aplicable_externa", B)],
        negables={"falta_reuso": missing, "omitida_reuso": omitted, "coincide_reuso": matches},
    )
    for row in result["answers"][0]["results"]:
        b = candidates[row["bindings"]["B"]]
        item = c._item(b, "aplicable", [])
        item.update(proyecto=b["proyecto"], de=b["proyecto"], peso="externa", prueba_reuso=row["proof"])
        item["revision"] = revision(b)
        out.append(item)
    return out


def _omitida(node, destino):
    uses = node["datos"].get("usos_destino", [])
    keys = {
        u["clave"]
        for u in uses
        if u["destino"] == destino and u["resultado"] == "no_aplico" and u["revision"] == revision(node)
    }
    return len(keys) >= 2


def registrar_uso_destino(origen, bid, destino, data):
    k.proyecto(destino)
    por = data.get("por", "")
    if k.rol_de(por) not in (k.P, k.C):
        raise k.Rechazo("El uso requiere persona o coordinadora", 403)
    if data.get("resultado") not in c.USOS:
        raise k.Rechazo("resultado debe ser sirvio, no_aplico o ya_sabido")
    key = k._texto(data.get("clave", data.get("encargo")), "clave de uso", 64)
    with k._abrir(origen) as con:
        con.execute("BEGIN IMMEDIATE")
        b = c._creencia(con, origen, bid)
        if data.get("encargo"):
            task = k._nodo(con, destino, data["encargo"])
            if task["tipo"] != "encargo":
                raise k.Rechazo("encargo no es un encargo")
        uses = b["datos"].get("usos_destino", [])
        if not any(u["clave"] == key and u["destino"] == destino and u["revision"] == revision(b) for u in uses):
            uses = [
                *uses,
                {
                    "destino": destino,
                    "clave": key,
                    "revision": revision(b),
                    "resultado": data["resultado"],
                    "por": por,
                    "fecha": k.ahora(),
                    "nota": data.get("nota", ""),
                },
            ]
            k.actualizar_datos(origen, bid, {"usos_destino": uses}, por=por, motivo="uso en proyecto destino", con=con)
    return {"omitida": _omitida({**b, "datos": {**b["datos"], "usos_destino": uses}}, destino)}


def graduar(*, archivo):
    lines = ["# Principios de proceso aceptados", "", "Proyección de SQLite. Consultar vigencia antes de aplicar.", ""]
    try:
        nodes, links = _foto("lienzo")
        supported = {x["creencia"] for x in c._evaluadas("lienzo", None) if x["estado"] == "vigente"}
    except k.Rechazo as exc:
        if exc.codigo != 404:
            raise
        nodes, links = [], []
        supported = set()
    for b in _beliefs(nodes):
        if (
            b["datos"].get("alcance") == "proceso_lienzo"
            and b["datos"].get("principio") is True
            and _vigente(b, links)
            and b["id"] in supported
            and b["datos"].get("regla_logica")
        ):
            lines.append(
                f"- {b['datos']['accion']} — [creencia {b['id']}](http://127.0.0.1:7321/conocimiento/lienzo/nodos/{b['id']}); revisión {revision(b)}."
            )
    path = Path(archivo)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(str(path), "\n".join(lines) + "\n")
    return {"principios": sum(line.startswith("- ") for line in lines), "archivo": str(path)}
