"""Contraste lógico de candidatos de aprendizaje con el motor separado (contrato 3, sin almacén).

Los candidatos son lo que espera veredicto: decisiones y reglas propuestas, hallazgos propuestos y
mediciones propuestas (propuestas del investigador, hipótesis, creencias). El motor recibe hechos
del grafo y reglas propias de Lienzo como datos, y devuelve observaciones con su prueba: respaldo
caído, regla cuestionada, contradicción con una decisión vigente, reapertura de un hallazgo
rechazado, apoyo retirado y falta de evidencia independiente. Nunca promueve, rechaza ni cierra:
lee la base en solo lectura y no escribe conocimiento. Una regla Python independiente calcula lo
mismo para que una diferencia se vea, sin elegir ganador."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading

import conocimiento as k
import prolog_learning

REGLAS_VERSION = "contraste-1"
MAX_NODOS = 1000
MAX_VINCULOS = 4000
MAX_RESULTADOS = 5000
# relaciones que entran al contraste; el resto (sobre, declarado_en, ...) no expresa dependencia ni oposición
RELACIONES = ("motivada_por", "derivada_de", "apoya", "mismo_que", "reemplaza", "elige", "descarta")
CANDIDATOS = (("decision", "propuesta"), ("hallazgo", "propuesto"), ("regla", "propuesta"), ("medicion", "propuesta"))
CAIDAS = (
    ("hallazgo", "rechazado"),
    ("medicion", "rechazada"),
    ("decision", "revertida"),
    ("decision", "reemplazada"),
    ("regla", "retirada"),
)
# evidencia que el propio Lienzo produjo sin oráculo independiente: no cuenta como contraste
AUTOGENERADA = (
    "analisis_optimizacion",
    "investigacion_cli",
    "investigacion_cli_fallida",
    "piloto_jev",
    "patron_desarrollo",
)
SIN_ESTADO = "sin_estado"
_ocupado = threading.BoundedSemaphore(1)


def _lit(pred, *args, **extra):
    return {"pred": pred, "args": list(args), **extra}


def _regla(rid, head, *body):
    return {"id": rid, "head": head, "body": list(body)}


C, F, M, R, D, A, H, E = "?C", "?F", "?M", "?R", "?D", "?A", "?H", "?E"
RULES = [
    *(_regla(f"candidato_{t}", _lit("candidato", C), _lit("nodo", C, t, s)) for t, s in CANDIDATOS),
    *(_regla(f"caida_{t}_{s}", _lit("caida", F), _lit("nodo", F, t, s)) for t, s in CAIDAS),
    _regla("cuestionada", _lit("cuestionada", R), _lit("nodo", R, "regla", "cuestionada")),
    _regla("depende_motivo", _lit("depende", C, F), _lit("vinculo", C, "motivada_por", F)),
    _regla("depende_derivacion", _lit("depende", C, F), _lit("vinculo", C, "derivada_de", F)),
    # como el checklist: la cadena sigue sólo a través de decisiones
    _regla("alcanza_directo", _lit("alcanza", C, F), _lit("depende", C, F)),
    _regla(
        "alcanza_decision",
        _lit("alcanza", C, F),
        _lit("depende", C, M),
        _lit("nodo", M, "decision", "?_"),
        _lit("alcanza", M, F),
    ),
    _regla(
        "respaldo_caido", _lit("respaldo_caido", C, F), _lit("candidato", C), _lit("alcanza", C, F), _lit("caida", F)
    ),
    _regla(
        "regla_cuestionada",
        _lit("regla_cuestionada", C, R),
        _lit("candidato", C),
        _lit("alcanza", C, R),
        _lit("cuestionada", R),
    ),
    _regla(
        "reemplaza_cuestionada",
        _lit("regla_cuestionada", C, R),
        _lit("candidato", C),
        _lit("vinculo", C, "reemplaza", R),
        _lit("cuestionada", R),
    ),
    # oposición estructurada: la misma alternativa elegida por uno y descartada por una decisión vigente
    _regla(
        "contradice_elige",
        _lit("contradice", C, D, A),
        _lit("candidato", C),
        _lit("vinculo", C, "elige", A),
        _lit("vinculo", D, "descarta", A),
        _lit("nodo", D, "decision", "vigente"),
    ),
    _regla(
        "contradice_descarta",
        _lit("contradice", C, D, A),
        _lit("candidato", C),
        _lit("vinculo", C, "descarta", A),
        _lit("vinculo", D, "elige", A),
        _lit("nodo", D, "decision", "vigente"),
    ),
    _regla(
        "reabre_rechazado",
        _lit("reabre_rechazado", C, H),
        _lit("candidato", C),
        _lit("vinculo", C, "mismo_que", H),
        _lit("nodo", H, "hallazgo", "rechazado"),
    ),
    _regla(
        "apoyo_retirado",
        _lit("apoyo_retirado", C, E),
        _lit("candidato", C),
        _lit("vinculo_retirado", C, "apoya", E),
    ),
    *(_regla(f"autogenerada_{c}", _lit("autogenerada", E), _lit("clase", E, c)) for c in AUTOGENERADA),
    # independencia sólo con procedencia humana: una clase desconocida o un agente no la prueban
    _regla("humana", _lit("humana", E), _lit("autor_rol", E, "persona")),
    _regla(
        "evidencia_humana",
        _lit("evidencia_humana", C),
        _lit("candidato", C),
        _lit("vinculo", C, "apoya", E),
        _lit("nodo", E, "evidencia", "?_"),
        _lit("humana", E),
    ),
    _regla(
        "evidencia_sin_verificar",
        _lit("evidencia_sin_verificar", C),
        _lit("candidato", C),
        _lit("vinculo", C, "apoya", E),
        _lit("nodo", E, "evidencia", "?_"),
        _lit("autogenerada", E, **{"not": True}),
        _lit("humana", E, **{"not": True}),
    ),
    _regla(
        "sin_evidencia_independiente",
        _lit("sin_evidencia_independiente", C),
        _lit("candidato", C),
        _lit("evidencia_humana", C, **{"not": True}),
    ),
    _regla(
        "independencia_no_verificada",
        _lit("independencia_no_verificada", C),
        _lit("candidato", C),
        _lit("evidencia_humana", C, **{"not": True}),
        _lit("evidencia_sin_verificar", C),
    ),
    *(
        _regla(f"observado_{p}", _lit("observado", C), _lit(p, C, *["?_"] * n))
        for p, n in (
            ("respaldo_caido", 1),
            ("regla_cuestionada", 1),
            ("contradice", 2),
            ("reabre_rechazado", 1),
            ("apoyo_retirado", 1),
        )
    ),
    _regla(
        "listo_para_revision",
        _lit("listo_para_revision", C),
        _lit("candidato", C),
        _lit("evidencia_humana", C),
        _lit("observado", C, **{"not": True}),
    ),
]
RULE_IDS = {r["id"] for r in RULES}
RULE_BY_ID = {r["id"]: r for r in RULES}
BASE = {"nodo", "clase", "autor_rol", "vinculo", "vinculo_retirado"}  # predicados que sólo vienen de hechos
OBSERVACIONES = ("respaldo_caido", "regla_cuestionada", "contradice", "reabre_rechazado", "apoyo_retirado")
# pred -> nombres de las variables que devuelve, en orden
QUERIES = {
    "candidato": ("C",),
    "respaldo_caido": ("C", "F"),
    "regla_cuestionada": ("C", "R"),
    "contradice": ("C", "D", "A"),
    "reabre_rechazado": ("C", "H"),
    "apoyo_retirado": ("C", "E"),
    "sin_evidencia_independiente": ("C",),
    "independencia_no_verificada": ("C",),
    "listo_para_revision": ("C",),
}


def _base_ro():
    return sqlite3.connect(f"file:{k.db_path()}?mode=ro", uri=True)


def snapshot(pid: str) -> dict:
    """Hechos de un proyecto en una sola transacción de lectura. Excederse es un rechazo, nunca un recorte."""
    if not os.path.isdir(k._carpeta(pid)):
        raise k.Rechazo(f"proyecto desconocido: {pid}", 404)
    con = _base_ro()
    try:
        con.execute("BEGIN")
        nodos = con.execute(
            "SELECT id, tipo, estado, autor, json_extract(datos,'$.clase'), substr(texto, 1, 200) FROM nodo "
            "WHERE proyecto=? ORDER BY id LIMIT ?",
            (pid, MAX_NODOS + 1),
        ).fetchall()
        marcas = ",".join("?" * len(RELACIONES))
        vinculos = con.execute(
            f"SELECT v.de, v.relacion, v.a, v.activo FROM vinculo v JOIN nodo n ON n.id=v.de "
            f"WHERE n.proyecto=? AND v.relacion IN ({marcas}) ORDER BY v.de, v.relacion, v.a LIMIT ?",
            (pid, *RELACIONES, MAX_VINCULOS + 1),
        ).fetchall()
        con.execute("COMMIT")
    finally:
        con.close()
    if len(nodos) > MAX_NODOS or len(vinculos) > MAX_VINCULOS:
        raise k.Rechazo(
            f"El proyecto excede {MAX_NODOS} nodos o {MAX_VINCULOS} vínculos; no se contrasta con datos truncados", 413
        )
    ids = {n[0] for n in nodos}
    # lo que la vista muestra de cada nodo; no entra al motor
    info = {n[0]: {"tipo": n[1], "estado": n[2], "clase": n[4], "texto": n[5] or ""} for n in nodos}
    facts = []
    for nid, tipo, estado, autor, clase, _texto in nodos:
        facts.append(_lit("nodo", nid, tipo, estado or SIN_ESTADO, source="grafo"))
        if isinstance(clase, str) and clase:
            facts.append(_lit("clase", nid, clase, source="grafo"))
        if tipo == "evidencia":
            # el rol antes del ':' (persona, coordinadora, frente, server); sin autor no hay procedencia
            rol = autor.split(":", 1)[0] if isinstance(autor, str) and autor else "desconocido"
            facts.append(_lit("autor_rol", nid, rol, source="grafo"))
    for de, rel, a, activo in vinculos:
        if a not in ids:  # el destino es de otro proyecto o ya no existe: no se inventa su estado
            continue
        if activo:
            facts.append(_lit("vinculo", de, rel, a, source="grafo"))
        elif rel == "apoya":
            facts.append(_lit("vinculo_retirado", de, rel, a, source="grafo"))
    return {
        "proyecto": pid,
        "nodos": ids,
        "info": info,
        "facts": facts,
        "cobertura": {"nodos": len(nodos), "vinculos": len(vinculos)},
    }


def consulta(facts: list) -> dict:
    return {
        "contract": 3,
        "domain": "logic",
        "facts": facts,
        "rules": RULES,
        "queries": [_lit(p, *("?" + v for v in vs)) for p, vs in QUERIES.items()],
        "explain": True,
        "limits": {"seconds": 5, "max_results": MAX_RESULTADOS, "proof_depth": 64},
    }


def run(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=True, allow_nan=False)
    if len(text.encode()) > 4 * 1024 * 1024:
        raise k.Rechazo("La consulta supera 4 MiB", 413)
    if not prolog_learning.ENGINE.is_file():
        raise prolog_learning.MotorError(
            "Motor lógico no encontrado: cloná motor-logico junto a Lienzo o fijá LIENZO_PROLOG_ENGINE"
        )
    if not _ocupado.acquire(blocking=False):
        raise k.Rechazo("El contraste lógico está ocupado; volvé a consultar", 409)
    try:
        result = subprocess.run(
            prolog_learning.command(),
            input=text + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            code = _codigo(result.stderr)
            raise prolog_learning.MotorError(f"El motor rechazó el contraste ({code})")
        if len(result.stdout.encode("utf-8")) > 8 * 1024 * 1024:
            raise prolog_learning.MotorError("La respuesta del motor excede 8 MiB")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise prolog_learning.MotorError(
            f"Motor Prolog no disponible o respuesta inválida ({type(exc).__name__})"
        ) from None
    finally:
        _ocupado.release()


def _codigo(stderr: str) -> str:
    try:
        return str(json.loads(stderr.strip().splitlines()[-1])["code"])[:40]
    except ValueError, KeyError, IndexError, TypeError:
        return "sin código"


def _literal(value, what: str) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("pred"), str) or not isinstance(value.get("args"), list):
        raise TypeError(f"{what} con forma inválida")
    return value


def _unificar(patron: list, args: list, ligaduras: dict) -> None:
    """Los argumentos de la prueba encajan con los de la regla: constantes iguales y cada variable
    con un único valor en toda la regla. `?_` acepta cualquier valor."""
    if len(patron) != len(args):
        raise ValueError("aridad distinta a la de la regla")
    for p, a in zip(patron, args, strict=True):
        if p == "?_":
            continue
        if isinstance(p, str) and p.startswith("?"):
            if ligaduras.setdefault(p, a) != a:
                raise ValueError(f"la variable {p} toma dos valores en la misma regla")
        elif p != a:
            raise ValueError("una constante no coincide con la regla")


def _prueba(proof, hechos: set, negables: dict, depth: int = 0) -> bool:
    """Verifica una prueba del contrato 3 contra las reglas propias, sin resolver de nuevo: cada paso
    es una regla de RULES con su cabeza y su cuerpo instanciados de forma coherente, cada hoja un
    hecho enviado y cada negación falsa en los hechos o en el modelo Python. Devuelve si hubo recorte."""
    if depth > 200:
        raise ValueError("prueba demasiado profunda")
    if not isinstance(proof, dict):
        raise TypeError("prueba con forma inválida")
    by = proof.get("by")
    fact = _literal(proof.get("fact"), "hecho de la prueba")
    if by == "truncated":
        return True
    if by == "given":
        if (fact["pred"], tuple(fact["args"])) not in hechos:
            raise ValueError("la prueba cita un hecho que no se envió")
        return False
    regla = RULE_BY_ID.get(proof.get("rule")) if by == "rule" else None
    if regla is None or not isinstance(proof.get("premises"), list):
        raise ValueError("paso de prueba desconocido")
    if fact["pred"] != regla["head"]["pred"]:
        raise ValueError("la cabeza de la regla no es el hecho probado")
    ligaduras = {}
    _unificar(regla["head"]["args"], fact["args"], ligaduras)
    if len(proof["premises"]) != len(regla["body"]):
        raise ValueError("la prueba no tiene una premisa por cada elemento del cuerpo")
    truncada = False
    for item, premise in zip(regla["body"], proof["premises"], strict=True):  # todas, sin cortocircuito
        if item.get("not"):
            if not isinstance(premise, dict) or set(premise) != {"not"}:
                raise ValueError("el cuerpo pide una negación")
            lit = _literal(premise["not"], "negación")
            if lit["pred"] != item["pred"]:
                raise ValueError("la negación no es la del cuerpo")
            _unificar(item["args"], lit["args"], ligaduras)
            clave = (lit["pred"], tuple(lit["args"]))
            if lit["pred"] not in negables and lit["pred"] not in BASE:
                raise ValueError("negación que no se puede comprobar")
            if clave in hechos or tuple(lit["args"]) in negables.get(lit["pred"], ()):
                raise ValueError("negación falsa: el literal se cumple")
            continue
        if isinstance(premise, dict) and set(premise) == {"not"}:
            raise ValueError("el cuerpo pide un literal positivo")
        if not isinstance(premise, dict):
            raise TypeError("premisa con forma inválida")
        hecho = _literal(premise.get("fact"), "premisa")
        if hecho["pred"] != item["pred"]:
            raise ValueError("la premisa no es la del cuerpo")
        _unificar(item["args"], hecho["args"], ligaduras)
        if _prueba(premise, hechos, negables, depth + 1):
            truncada = True
    return truncada


def resultados(output: dict, facts: list) -> tuple[dict, dict]:
    """(pred -> tuplas, (pred, tupla) -> justificación). Una respuesta incompleta, truncada, con IDs
    ajenos o con pruebas que no cierran contra los hechos enviados es un error."""
    nodos = {f["args"][0] for f in facts if f["pred"] == "nodo"}
    hechos = {(f["pred"], tuple(f["args"])) for f in facts}
    negables = _modelo(facts)  # lo que se deduce de verdad: una negación de algo de acá es falsa
    if (
        not isinstance(output, dict)
        or type(output.get("contract")) is not int
        or output["contract"] != 3
        or output.get("domain") != "logic"
        or not isinstance(output.get("engine"), dict)
        or not isinstance(output["engine"].get("version"), str)
        or not isinstance(output.get("program_hash"), str)
        or not isinstance(output.get("answers"), list)
        or len(output["answers"]) != len(QUERIES)
    ):
        raise ValueError("contrato 3 inválido")
    found, why = {}, {}
    for answer, (pred, names) in zip(output["answers"], QUERIES.items(), strict=True):
        if not isinstance(answer, dict) or answer.get("pred") != pred or answer.get("truncated") is not False:
            raise ValueError(f"respuesta inválida o truncada en {pred}")
        if not isinstance(answer.get("results"), list) or type(answer.get("count")) is not int:
            raise ValueError(f"resultados o conteo ausentes en {pred}")
        rows = set()
        for item in answer["results"]:
            bindings = item.get("bindings") if isinstance(item, dict) else None
            if not isinstance(bindings, dict) or set(bindings) != set(names):
                raise ValueError(f"ligaduras inválidas en {pred}")
            row = tuple(bindings[n] for n in names)
            if any(not isinstance(v, str) for v in row) or any(v not in nodos for v in row):
                raise ValueError(f"{pred} nombra un nodo fuera del snapshot")
            proof = item.get("proof")
            if not isinstance(proof, dict) or proof.get("fact") != {"pred": pred, "args": list(row)}:
                raise ValueError(f"{pred} sin prueba de su propio resultado")
            sources = item.get("sources")
            if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
                raise ValueError(f"{pred} sin fuentes")
            truncada = _prueba(proof, hechos, negables)
            why[(pred, row)] = {"prueba": proof, "fuentes": sources, "prueba_truncada": truncada}
            rows.add(row)
        if len(rows) != answer["count"]:
            raise ValueError(f"conteo inconsistente en {pred}")
        found[pred] = rows
    return found, why


def oraculo(facts: list) -> dict:
    """La misma semántica en Python, independiente del motor, para la comparación diferencial."""
    modelo = _modelo(facts)
    return {p: modelo[p] for p in QUERIES}


def _modelo(facts: list) -> dict:
    """Las consultas más los predicados que alguna regla niega, calculados en Python."""
    nodo = {f["args"][0]: (f["args"][1], f["args"][2]) for f in facts if f["pred"] == "nodo"}
    clase = {f["args"][0]: f["args"][1] for f in facts if f["pred"] == "clase"}
    humana = {f["args"][0] for f in facts if f["pred"] == "autor_rol" and f["args"][1] == "persona"}
    vinc = {tuple(f["args"]) for f in facts if f["pred"] == "vinculo"}
    retirado = {tuple(f["args"]) for f in facts if f["pred"] == "vinculo_retirado"}
    cand = {n for n, ts in nodo.items() if ts in CANDIDATOS}
    caida = {n for n, ts in nodo.items() if ts in CAIDAS}
    cuest = {n for n, ts in nodo.items() if ts == ("regla", "cuestionada")}
    depende = {}
    for de, rel, a in vinc:
        if rel in ("motivada_por", "derivada_de"):
            depende.setdefault(de, set()).add(a)

    def alcanza(c):
        seen, frontier, out = set(), [c], set()
        while frontier:
            x = frontier.pop()
            for f in depende.get(x, ()):
                out.add(f)
                if nodo.get(f, ("",))[0] == "decision" and f not in seen:
                    seen.add(f)
                    frontier.append(f)
        return out

    reach = {c: alcanza(c) for c in cand}
    auto = {n for n, c in clase.items() if c in AUTOGENERADA}
    rows = {
        "candidato": {(c,) for c in cand},
        "respaldo_caido": {(c, f) for c in cand for f in reach[c] if f in caida},
        "regla_cuestionada": {(c, r) for c in cand for r in reach[c] if r in cuest}
        | {(c, r) for c, rel, r in vinc if c in cand and rel == "reemplaza" and r in cuest},
        "contradice": {
            (c, d, a)
            for c, rel, a in vinc
            if c in cand and rel in ("elige", "descarta")
            for d, rel2, a2 in vinc
            if a2 == a
            and rel2 == ("descarta" if rel == "elige" else "elige")
            and nodo.get(d) == ("decision", "vigente")
        },
        "reabre_rechazado": {
            (c, h)
            for c, rel, h in vinc
            if c in cand and rel == "mismo_que" and nodo.get(h) == ("hallazgo", "rechazado")
        },
        "apoyo_retirado": {(c, e) for c, rel, e in retirado if c in cand and rel == "apoya"},
    }
    apoyos = {(c, e) for c, rel, e in vinc if c in cand and rel == "apoya" and nodo.get(e, ("",))[0] == "evidencia"}
    con_humana = {c for c, e in apoyos if e in humana}
    sin_verificar = {c for c, e in apoyos if e not in auto and e not in humana}
    observado = {r[0] for p in OBSERVACIONES for r in rows[p]}
    rows["sin_evidencia_independiente"] = {(c,) for c in cand - con_humana}
    rows["independencia_no_verificada"] = {(c,) for c in (cand - con_humana) & sin_verificar}
    rows["listo_para_revision"] = {(c,) for c in con_humana - observado}
    # los negados en RULES; deben coincidir con los que las reglas producen (lo prueba el diferencial)
    rows["autogenerada"] = {(e,) for e in auto}
    rows["humana"] = {(e,) for e in humana}
    rows["evidencia_humana"] = {(c,) for c in con_humana}
    rows["observado"] = {(c,) for c in observado}
    return rows


def contrastar(pid: str) -> tuple[int, dict]:
    """Observaciones por candidato; un motor ausente o una respuesta inválida se informan, nunca como vacío."""
    snap = snapshot(pid)
    payload = consulta(snap["facts"])
    python = oraculo(snap["facts"])
    try:
        output = run(payload)
        found, why = resultados(output, snap["facts"])
    except prolog_learning.MotorError as exc:
        return 503, {"error": str(exc), "code": "prolog_unavailable"}
    except (ValueError, TypeError) as exc:
        return 502, {"error": f"Respuesta del motor inválida: {exc}", "code": "prolog_invalid"}
    diferencias = [
        {"consulta": p, "solo_prolog": sorted(found[p] - python[p]), "solo_python": sorted(python[p] - found[p])}
        for p in QUERIES
        if found[p] != python[p]
    ]
    concluyente = not diferencias  # con diferencias no se dice que algo está listo: se informan las dos lecturas
    por_candidato = {}
    for (c,) in sorted(found["candidato"]):
        if (c,) in found["independencia_no_verificada"]:
            evidencia = "no_verificada"
        elif (c,) in found["sin_evidencia_independiente"]:
            evidencia = "ausente"
        else:
            evidencia = "humana"
        listo = (c,) in found["listo_para_revision"]
        justificacion = why.get(("listo_para_revision", (c,)))
        # una prueba recortada no acredita el «listo»: queda sin conclusión para ese candidato
        completo = concluyente and not (justificacion and justificacion["prueba_truncada"])
        por_candidato[c] = {
            "observaciones": [
                {"tipo": p, "con": list(r[1:]), **why[(p, r)]}
                for p in OBSERVACIONES
                for r in sorted(found[p])
                if r[0] == c
            ],
            "evidencia_independiente": evidencia,
            "listo_para_revision": listo if completo else None,
            "justificacion_listo": justificacion if completo and listo else None,
        }
    return 200, {
        "autoridad": "observación; no promueve, no rechaza ni cierra",
        "concluyente": concluyente,
        "reglas": REGLAS_VERSION,
        "motor": output["engine"],
        "program_hash": output["program_hash"],
        "proyecto": pid,
        "cobertura": {**snap["cobertura"], "candidatos": len(por_candidato)},
        "snapshot": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "candidatos": por_candidato,
        "nodos": {
            n: snap["info"][n]
            for n in sorted(
                set(por_candidato) | {x for c in por_candidato.values() for o in c["observaciones"] for x in o["con"]}
            )
        },
        "diferencias_python": diferencias,
    }
