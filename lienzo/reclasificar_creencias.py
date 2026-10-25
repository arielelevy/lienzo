"""Reclasificación de creencias revertidas que no se refutaron con evidencia en contra (pedido de Ariel,
2026-10-25). La revisión IA de antes sólo podía aceptar o rechazar, y rechazó por «beneficio no medido» o por
«evidencia no provista». Esto arma la lista y, sólo con la firma de una persona, la aplica.

No reescribe ningún veredicto: una revertida queda revertida en la historia. Lo que se recupera nace como
propuesta nueva, marcada pendiente (`creencias.dejar_pendiente`), que `reemplaza` a las viejas; por eso las
viejas pasan a leerse `reemplazada` y su evidencia sigue en la nueva.

- `medicion_repetida`: las copias diarias de una misma métrica de `optimizacion_trabajo` (esperas,
  difusiones) se juntan en una propuesta por métrica, con la clave que desde ahora usa el sueño, pendiente
  de medir la eficacia de la acción.
- `falta_eficacia` y `falta_evidencia`: rechazadas porque no se midió si la acción sirve, o porque la
  evidencia provista no alcanzaba. Se reabren como propuesta pendiente de eso.
- `mantener`: el resto (también las que ya tienen sucesora: se leen `reemplazada` sin tocar nada).

    py -m reclasificar_creencias lienzo                       la lista, sin cambiar nada
    py -m reclasificar_creencias lienzo --aplicar --por "persona:Ariel"
"""

from __future__ import annotations

import json
import re
import sys

import conocimiento as k
import creencias
import optimizacion_trabajo

_EFICACIA = re.compile(r"benefici|no tiene beneficio|destrab|consejo|no est[aá] medid|sin medir", re.IGNORECASE)
_EVIDENCIA = re.compile(r"sin evidencia|no consta|no menciona|no hay evidencia|evidencia provista", re.IGNORECASE)


def _plantillas():
    """métrica -> (prefijo fijo del texto, sugerencia) de los hallazgos de trabajo."""
    return {m: (texto.split("{", 1)[0].strip(), sug) for m, (_, texto, sug) in optimizacion_trabajo.UMBRALES.items()}


def _motivo(con, nid):
    row = con.execute(
        "SELECT motivo FROM cambio WHERE nodo_id=? AND accion='estado' ORDER BY seq DESC LIMIT 1", (nid,)
    ).fetchone()
    return (row["motivo"] if row else "") or ""


def plan(pid: str) -> dict:
    with k._abrir(pid) as con:
        con.execute("BEGIN")
        nodes, _ = creencias._leer(con, pid)
        revertidas = [n for n in nodes if n["estado"] == "revertida" and not n.get("_reemplazada")]
        plantillas = _plantillas()
        grupos: dict[str, list] = {}
        reabrir, mantener = [], []
        for n in revertidas:
            motivo = _motivo(con, n["id"])
            metrica = next((m for m, (pre, _) in plantillas.items() if pre and n["texto"].startswith(pre)), None)
            fila = {"id": n["id"], "texto": n["texto"], "motivo": motivo}
            if metrica:
                grupos.setdefault(metrica, []).append(fila)
            elif _EFICACIA.search(motivo):
                reabrir.append({**fila, "falta": "eficacia"})
            elif _EVIDENCIA.search(motivo):
                reabrir.append({**fila, "falta": "evidencia"})
            else:
                mantener.append(fila)
        ya = [
            {"id": n["id"], "texto": n["texto"]} for n in nodes if n.get("_reemplazada") and n["estado"] == "revertida"
        ]
    return {
        "proyecto": pid,
        "medicion_repetida": [
            {"metrica": m, "accion": plantillas[m][1], "copias": sorted(fs, key=lambda f: f["texto"])}
            for m, fs in sorted(grupos.items())
        ],
        "reabrir": reabrir,
        "mantener": mantener,
        "ya_reemplazadas": ya,
    }


def aplicar(pid: str, lista: dict, por: str) -> dict:
    """Aplica la lista en una transacción, firmada por una persona. Idempotente: lo que ya tiene sucesora se
    saltea. Devuelve las propuestas creadas."""
    por = creencias._persona({"por": por})
    creadas = []
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        evidencia = k.crear_nodo(
            pid,
            "evidencia",
            f"Reclasificación de creencias revertidas sin evidencia en contra, firmada por {por[8:].strip()}",
            {"clase": "revision_humana", "reclasificacion": lista},
            autor=por,
            motivo="reclasificar creencias",
            con=con,
        )
        nodes = {n["id"]: n for n in creencias._leer(con, pid)[0]}

        def pendientes(viejas):
            return [nodes[v] for v in viejas if v in nodes and not nodes[v].get("_reemplazada")]

        def nacer(base, texto, accion, fuentes, falta, motivo, viejas, clave=None):
            data = {
                "texto": texto,
                "accion": accion,
                "dimension": base["datos"].get("dimension", "coordinacion"),
                "contexto": base["datos"].get("contexto", {}),
                "fuentes": fuentes[-30:],
                "excepciones": f"Reabierta el {k.ahora()[:10]} por reclasificación: {motivo}",
                "alcance": base["datos"].get("alcance", "proyecto"),
            }
            if clave:
                data["clave"] = clave
            nueva = creencias.proponer(pid, data, autor=por, con=con)
            creencias.dejar_pendiente(con, pid, nueva["id"], por, falta, motivo, evidencia["id"])
            for v in viejas:
                k.vincular(pid, nueva["id"], "reemplaza", v["id"], autor=por, motivo=motivo, con=con)
            creadas.append(nueva["id"])

        for grupo in lista.get("medicion_repetida", []):
            viejas = pendientes([c["id"] for c in grupo["copias"]])
            if not viejas:
                continue
            fuentes = list(dict.fromkeys(f for v in viejas for f in v["datos"].get("fuentes", [])))
            ultima = max(viejas, key=lambda v: v["fecha"])
            motivo = "la medición está respaldada; falta medir si la acción sirve"
            nacer(
                ultima,
                ultima["texto"],
                grupo["accion"],
                fuentes,
                "eficacia",
                motivo,
                viejas,
                f"trabajo:{grupo['metrica']}",
            )
        for fila in lista.get("reabrir", []):
            viejas = pendientes([fila["id"]])
            if not viejas:
                continue
            v = viejas[0]
            motivo = (
                "falta medir si la acción sirve"
                if fila["falta"] == "eficacia"
                else "la evidencia provista no alcanzaba"
            )
            nacer(
                v,
                v["texto"],
                v["datos"].get("accion", v["texto"]),
                v["datos"].get("fuentes", []),
                fila["falta"],
                motivo,
                viejas,
            )
    return {"evidencia": evidencia["id"], "creadas": creadas}


def texto(lista: dict) -> str:
    out = [f"# Reclasificación de creencias revertidas · `{lista['proyecto']}`", ""]
    n = sum(len(g["copias"]) for g in lista["medicion_repetida"])
    out += [
        (
            f"- Copias de una misma medición: {n} en {len(lista['medicion_repetida'])} métricas → una propuesta por "
            "métrica, pendiente de medir la eficacia."
        ),
        f"- Para reabrir como pendiente: {len(lista['reabrir'])}.",
        f"- Se mantienen refutadas: {len(lista['mantener'])}.",
        f"- Ya se leen reemplazadas (tienen sucesora), sin cambios: {len(lista['ya_reemplazadas'])}.",
        "",
    ]
    for g in lista["medicion_repetida"]:
        out += [f"## Métrica `{g['metrica']}` ({len(g['copias'])} copias → 1)", "", f"Acción: {g['accion']}", ""]
        out += [f"- `{c['id'][:8]}` {c['texto']}" for c in g["copias"]] + [""]
    if lista["reabrir"]:
        out += ["## Reabrir como pendiente", ""]
        out += [
            f"- `{f['id'][:8]}` falta **{f['falta']}**: {f['texto'][:140]}  \n  Motivo del rechazo: {f['motivo'][:200]}"
            for f in lista["reabrir"]
        ] + [""]
    if lista["mantener"]:
        out += (
            ["## Se mantienen refutadas", ""]
            + [f"- `{f['id'][:8]}` {f['texto'][:140]}" for f in lista["mantener"]]
            + [""]
        )
    if lista["ya_reemplazadas"]:
        out += ["## Ya reemplazadas (sin cambios)", ""] + [
            f"- `{f['id'][:8]}` {f['texto'][:140]}" for f in lista["ya_reemplazadas"]
        ]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("proyecto")
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--por", help="persona:<nombre>; obligatorio con --aplicar")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # la consola de Windows en cp1252
    lista = plan(a.proyecto)
    if a.aplicar:
        print(json.dumps(aplicar(a.proyecto, lista, a.por or ""), ensure_ascii=False))
    else:
        print(json.dumps(lista, ensure_ascii=False, indent=1) if a.json else texto(lista))
    return 0


if __name__ == "__main__":
    sys.exit(main())
