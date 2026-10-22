"""Caso checklist-motor-e2e (encargo J, 2026-10-22): siembra por la API real de una instancia aislada (7354, LIENZO_HOME temporal) el ciclo
completo del aprendizaje: encargos con tipo de trabajo, creencias propuestas, veredicto de una
persona, una regla derivada que se cuestiona por recurrencia real, y lee el checklist sostenido por
el motor. Deja la evidencia en checklist-e2e.json. Nunca toca el server de 7321."""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("LIENZO_URL", "http://127.0.0.1:7354")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados", "checklist-motor", "checklist-e2e.json")
P = "demo-j"
CTX = {"tipo_trabajo": "bugfix", "agente": "claude"}
evidencia = {"base": BASE, "pasos": []}


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo, ensure_ascii=False).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + "/conocimiento" + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("X-Lienzo", "1")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def paso(nombre, codigo, cuerpo, ok=None):
    ok = codigo == 200 if ok is None else ok
    evidencia["pasos"].append({"paso": nombre, "codigo": codigo, "ok": bool(ok), "cuerpo": cuerpo})
    print(("OK  " if ok else "MAL ") + nombre, codigo, flush=True)
    if not ok:
        raise SystemExit(json.dumps(cuerpo, ensure_ascii=False)[:2000])
    return cuerpo


def nodo(tipo, texto, autor, datos=None):
    return paso(
        f"nodo {tipo}: {texto}",
        *pedir("POST", f"/{P}/nodos", {"tipo": tipo, "texto": texto, "datos": datos or {}, "autor": autor}),
    )


def main():
    paso("registrar proyecto", *pedir("POST", "/proyectos", {"id": P, "nombre": "Demo J"}))
    paso("registrar proyecto sin creencias", *pedir("POST", "/proyectos", {"id": "vacio-j", "nombre": "Vacío J"}))
    ronda = paso("abrir ronda", *pedir("POST", f"/{P}/rondas", {"objetivo": "demo del checklist sostenido"}))
    for letra in "AB":  # dos encargos del mismo contexto: forman un patrón
        paso(
            f"encargo {letra} con tipo_trabajo",
            *pedir(
                "POST",
                f"/{P}/encargos",
                {"ronda": ronda["id"], "letra": letra, "texto": f"# Encargo {letra}", "contexto_desarrollo": CTX},
            ),
        )
    hallazgo = nodo(
        "hallazgo",
        "Los bugfix sin reproducción vuelven a fallar",
        "persona:Ariel",
        {"donde": "rondas 2026-10-20", "gravedad": "media"},
    )
    ev = nodo(
        "evidencia",
        "Tres bugfix de la ronda 2026-10-20 revisados a mano",
        "persona:Ariel",
        {"clase": "revision", "referencia": "review/2026-10-20"},
    )
    creencias = []
    for texto, accion in (
        ("Un bugfix necesita una prueba que reproduzca la falla", "Escribir la prueba en rojo antes del arreglo"),
        ("Un bugfix se cierra con el log del fallo original", "Adjuntar el log del fallo al informe"),
    ):
        creencias.append(
            paso(
                "proponer creencia",
                *pedir(
                    "POST",
                    f"/{P}/creencias",
                    {
                        "texto": texto,
                        "accion": accion,
                        "dimension": "pruebas",
                        "contexto": CTX,
                        "fuentes": [hallazgo["id"]],
                    },
                ),
            )
        )
    hasta = (dt.datetime.now(dt.UTC) + dt.timedelta(days=30)).isoformat()
    antes = paso("checklist antes del veredicto", *pedir("GET", f"/{P}/checklist?tipo_trabajo=bugfix&agente=claude"))
    paso("sin veredicto nada aplica", 200, {"total": antes["total"]}, ok=antes["total"] == 0)
    for c in creencias:
        paso(
            "veredicto de una persona",
            *pedir(
                "POST",
                f"/{P}/creencias/{c['id']}/veredicto",
                {
                    "por": "persona:Ariel",
                    "motivo": "revisado",
                    "resultado": "validada",
                    "evidencia": ev["id"],
                    "vigente_hasta": hasta,
                },
            ),
        )
    # recurrencia real: incidente, regla derivada de él y de la segunda creencia, vigente, y se repite
    inc = nodo(
        "incidente",
        "El bugfix de cuotas volvió a fallar",
        "persona:Ariel",
        {"herramienta": "pytest", "agente": "claude"},
    )
    regla = nodo("regla", "Todo bugfix adjunta el log del fallo", "persona:Ariel", {"ambito": "proyecto"})
    for destino in (inc["id"], creencias[1]["id"]):
        paso(
            "regla derivada_de",
            *pedir(
                "POST",
                f"/{P}/vinculos",
                {"de": regla["id"], "relacion": "derivada_de", "a": destino, "autor": "persona:Ariel"},
            ),
        )
    paso(
        "regla vigente",
        *pedir(
            "POST",
            f"/{P}/nodos/{regla['id']}/estado",
            {"estado": "vigente", "por": "persona:Ariel", "motivo": "adoptada"},
        ),
    )
    inc2 = nodo(
        "incidente",
        "El bugfix de cuotas falló otra vez",
        "persona:Ariel",
        {"herramienta": "pytest", "agente": "claude"},
    )
    paso(
        "recurrencia",
        *pedir(
            "POST", f"/{P}/vinculos", {"de": inc2["id"], "relacion": "repite", "a": inc["id"], "autor": "persona:Ariel"}
        ),
    )
    q = paso("cuestionar regla", *pedir("POST", f"/{P}/reglas/{regla['id']}/cuestionar"))
    paso("la regla quedó cuestionada", 200, q, ok=q.get("cuestionada") is True)
    out = paso("checklist sostenido", *pedir("GET", f"/{P}/checklist?tipo_trabajo=bugfix&agente=claude"))
    paso(
        "una sostenida con prueba y una cuestionada por la regla",
        200,
        {
            "motor": out["motor"],
            "items": [x["creencia"] for x in out["items"]],
            "cuestionadas": [x["creencia"] for x in out["cuestionadas"]],
        },
        ok=out["motor"]["estado"] == "sostenido"
        and [x["creencia"] for x in out["items"]] == [creencias[0]["id"]]
        and out["items"][0]["sostenida"]["prueba"]["rule"] == "sostenida"
        and [x["creencia"] for x in out["cuestionadas"]] == [creencias[1]["id"]]
        and out["cuestionadas"][0]["cuestionada_por"][0]["regla"] == regla["id"],
    )
    resumen = paso("resumen del tablero", *pedir("GET", "/aprendizaje-resumen"))
    fila = [x for x in resumen if x["proyecto"] == P]
    paso(
        "fila del proyecto",
        200,
        fila,
        ok=len(fila) == 1 and fila[0]["creencias"] == {"vigente": 2} and fila[0]["reglas_cuestionadas"] == 1,
    )
    patrones = paso("patrones", *pedir("GET", f"/{P}/patrones-desarrollo"))
    paso(
        "dos encargos bugfix forman un patrón",
        200,
        patrones["patrones"],
        ok=any(p["encargos"] == 2 for p in patrones["patrones"]),
    )
    evidencia["ids"] = {"creencias": [c["id"] for c in creencias], "regla": regla["id"], "evidencia": ev["id"]}


os.makedirs(os.path.dirname(OUT), exist_ok=True)
try:
    main()
    evidencia["ok"] = True
finally:
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(evidencia, f, ensure_ascii=False, indent=1)
sys.exit(0 if evidencia.get("ok") else 1)
