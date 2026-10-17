"""Cómo se trabaja, no sólo qué falla (pedido de Ariel, 2026-10-16: «en tu sueño es mejorar cómo
trabajar, buscá optimizaciones»). El scheduler de mejoras, en sus ratos quietos, mide desde las
capturas de la memoria (pedidos, respuestas, envíos y disparos de reglas, ya guardados) dónde se va
el tiempo de una ronda, y deja cada patrón que pasa su umbral como un hallazgo *propuesto*, con su
número, ejemplos y la primitiva del lienzo que lo ataca. Nada pasa a vigente sin veredicto, y esto
no manda mensajes, no lanza agentes ni gasta.

Medido en OpenSyync (13 al 16 de octubre, 4599 capturas): 92,8 h de frentes que ya habían entregado
y esperaban a una coordinadora ocupada; 4 acuses sin tarea que hicieron trabajar al frente y volvieron como
aviso; 46 avisos repetidos; 86 turnos intermedios avisados; 20 textos iguales a varios frentes.

`medir(caps)` es pura (la prueban los tests); `analizar` lee la base en sólo lectura y `registrar`
escribe los hallazgos, idempotentes por métrica y día."""

from __future__ import annotations

import bisect
import collections
import datetime as dt
import json
import re
import sqlite3
import statistics
import time
from pathlib import Path

import conocimiento
import creencias
import optimization_memory

VENTANA_H = 72
ESPERA_S = 600  # una espera de un frente cuenta desde los 10 min
ACTIVA_MIN = 3  # eventos de la coordinadora durante la espera: estaba trabajando en otra cosa
ACUSE_MAX_B = 300
VUELTA_S = 300
DIFUSION_S = 120
DIFUSION_MIN_B = 40  # un «ok» a dos frentes no es una difusion
LEER_S = 3.0  # tope de la lectura en el hilo del scheduler
EJEMPLOS = 3

ACUSE = re.compile(
    r"\b(entrega recibida|recibid[oa]|qued[aá]te quiet[oa]|qued[aá] quiet[oa]|conserv[aá] (el )?contexto|gracias|perfecto|ok)\b",
    re.IGNORECASE,
)
# un acuse no trae tarea: «Perfecto, ahora implementá el endpoint» es un encargo y su aviso se espera
TAREA = re.compile(
    r"(\?|\b(ahora|segu[ií]|implement|corr[eé]|hac[eé]|revis[aá]|agreg[aá]|arregl[aá]|prob[aá]|mand[aá]|"
    r"le[eé] |cambi[aá]|sub[ií]|aplic[aá]|termin[aá]|pas[aá]|retom[aá]|empez[aá]|arranc[aá])\w*)",
    re.IGNORECASE,
)
INTERMEDIO = re.compile(
    r"\b(sigo esperando|espero (a |que |la |el |tu )|sigue corriendo|todav[ií]a (corre|no termin)|en curso|aguardo|quedo quiet[oa])\b",
    re.IGNORECASE,
)
ENCABEZADO = re.compile(r"^\[lienzo: [^\]]*\]\n")

# metrica -> (umbral, texto del hallazgo, sugerencia). El umbral es de ejemplo, calibrado a ojo con
# OpenSyync: se ajusta cuando haya veredictos sobre estos hallazgos.
UMBRALES = {
    "esperas_h": (
        2.0,
        "Frentes esperando a la coordinadora: {valor:.1f} h en {n} esperas (mediana {mediana:.0f} min)",
        (
            "Revisar por lotes y dejar a cada frente la tarea siguiente del encargo en vez de «quedo quieto»; "
            "un frente por funcionalidad de punta a punta reduce lo que hay que integrar."
        ),
    ),
    "acuses_vuelta": (
        5,
        "Acuses que hicieron trabajar al frente y volvieron como aviso: {valor}",
        "Mandar los acuses con sin_aviso=True (c.enviar(s, texto, sin_aviso=True)) o no mandarlos.",
    ),
    "avisos_repetidos": (
        5,
        "Avisos con el mismo contenido que uno anterior: {valor} de {n}",
        "Revisar reglas con dedupe: false; el dedupe del server está prendido por defecto.",
    ),
    "avisos_intermedios": (
        10,
        "Avisos a la coordinadora con turnos intermedios: {valor} de {n}",
        'Cablear con solo_si="ESTADO:" (c.cablear(solo_si="ESTADO:")) y pedir a los frentes que cierren cada entrega con ESTADO:.',
    ),
    "difusiones": (
        3,
        "El mismo texto a varios frentes casi a la vez: {valor} veces",
        "Usar c.aviso(texto, frentes): un solo aviso cuando confirmen todos, sin idas y vueltas.",
    ),
}


def _ts(f: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(f)  # 3.11+ acepta la Z de las capturas
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)  # una fecha sin zona no rompe las restas


def coordinadora(caps: list[dict]) -> str | None:
    """La sesión que más avisos de regla recibe en la ventana."""
    destinos = collections.Counter(c["session_id"] for c in caps if c["clase"] == "regla")
    return destinos.most_common(1)[0][0] if destinos else None


def medir(caps: list[dict], coord: str | None = None) -> dict:
    """Métricas de trabajo sobre capturas ordenadas por fecha: cada una {session_id, clase, origen
    (dict), texto, bytes, hash, fecha (datetime), id}. Devuelve {metrica: {valor, ...}}. `coord`: quien
    coordina, si se sabe de una ventana mas larga (un tramo corto puede no tener avisos de regla)."""
    coord = coord or coordinadora(caps)
    if coord is None:
        return {}
    reglas = [c for c in caps if c["clase"] == "regla"]
    a_coord = [c for c in reglas if c["session_id"] == coord]
    envios = [c for c in caps if c["clase"] == "envio" and c["origen"].get("de") == coord]
    actividad = sorted(c["fecha"] for c in caps if c["session_id"] == coord or c["origen"].get("de") == coord)
    out: dict[str, dict] = {"coordinadora": {"valor": coord}}

    # esperas: el frente respondió y no recibió nada en >10 min mientras la coordinadora trabajaba
    por_sesion = collections.defaultdict(list)
    for c in caps:
        if c["clase"] in ("respuesta", "envio", "pedido"):
            por_sesion[c["session_id"]].append(c)
    frentes = {c["session_id"] for c in envios}
    esperas, ej = [], []
    for sid in frentes:
        for a, b in zip(por_sesion[sid], por_sesion[sid][1:], strict=False):
            if a["clase"] != "respuesta" or b["clase"] == "respuesta":
                continue
            w = (b["fecha"] - a["fecha"]).total_seconds()
            activos = bisect.bisect_left(actividad, b["fecha"]) - bisect.bisect_right(actividad, a["fecha"])
            if w > ESPERA_S and activos >= ACTIVA_MIN:
                esperas.append(w)
                ej.append(a["id"])
    out["esperas_h"] = {
        "valor": round(sum(esperas) / 3600, 2),
        "n": len(esperas),
        "mediana": statistics.median(esperas) / 60 if esperas else 0,
        "ejemplos": ej[:EJEMPLOS],
    }

    # acuses que vuelven: un envío corto de acuse y, en <5 min, un aviso de ese frente a la coordinadora
    vueltas, ej = 0, []
    avisos_de = collections.defaultdict(list)
    for r in a_coord:
        avisos_de[r["origen"].get("de")].append(r["fecha"])
    for c in envios:
        if c["bytes"] >= ACUSE_MAX_B or not ACUSE.search(c["texto"][:200]) or TAREA.search(c["texto"]):
            continue
        fs = avisos_de.get(c["session_id"], [])
        i = bisect.bisect_right(fs, c["fecha"])
        if i < len(fs) and (fs[i] - c["fecha"]).total_seconds() < VUELTA_S:
            vueltas += 1
            ej.append(c["id"])
    out["acuses_vuelta"] = {"valor": vueltas, "ejemplos": ej[:EJEMPLOS]}

    # avisos repetidos: mismo origen, destino y cuerpo (sin el encabezado de la demora)
    vistos, rep, ej = set(), 0, []
    for c in reglas:
        cuerpo = ENCABEZADO.sub("", c["texto"])  # el texto puede venir resumido: principio y final
        k = (c["origen"].get("de"), c["session_id"], cuerpo[:150], cuerpo[-300:])
        if k in vistos:
            rep += 1
            ej.append(c["id"])
        vistos.add(k)
    out["avisos_repetidos"] = {"valor": rep, "n": len(reglas), "ejemplos": ej[:EJEMPLOS]}

    inter = [c for c in a_coord if "ESTADO:" not in c["texto"] and INTERMEDIO.search(c["texto"][-600:])]
    out["avisos_intermedios"] = {
        "valor": len(inter),
        "n": len(a_coord),
        "ejemplos": [c["id"] for c in inter[:EJEMPLOS]],
    }

    # difusiones: el mismo texto (no un «ok») a dos o más frentes, en tandas de envíos a menos de 2 min
    # uno de otro; el mismo texto reenviado horas después es otra tanda
    grupos = collections.defaultdict(list)
    for c in envios:
        if c["bytes"] >= DIFUSION_MIN_B:
            grupos[c["hash"]].append(c)
    dif = []
    for g in grupos.values():
        tanda = [g[0]]
        for c in [*g[1:], None]:
            if c is not None and (c["fecha"] - tanda[-1]["fecha"]).total_seconds() < DIFUSION_S:
                tanda.append(c)
                continue
            if len({x["session_id"] for x in tanda}) > 1:
                dif.append(tanda)
            if c is not None:
                tanda = [c]
    out["difusiones"] = {"valor": len(dif), "ejemplos": [t[0]["id"] for t in dif[:EJEMPLOS]]}

    por_hora = collections.defaultdict(set)
    for c in caps:
        por_hora[c["fecha"].strftime("%Y-%m-%d %H")].add(c["session_id"])
    hora, sids = max(por_hora.items(), key=lambda kv: len(kv[1])) if por_hora else ("", set())
    out["pico_sesiones"] = {"valor": len(sids), "hora_utc": hora}
    return out


def hallazgos(metricas: dict) -> list[dict]:
    """Las métricas que pasan su umbral, como {metrica, texto, valor, umbral, sugerencia, ejemplos}."""
    out = []
    for nombre, (umbral, texto, sugerencia) in UMBRALES.items():
        m = metricas.get(nombre)
        if not m or m["valor"] < umbral:
            continue
        out.append(
            {
                "metrica": nombre,
                "texto": texto.format(**{"n": 0, "mediana": 0, **m}),
                "valor": m["valor"],
                "umbral": umbral,
                "sugerencia": sugerencia,
                "ejemplos": m.get("ejemplos") or [],
                **({"corregido": m["corregido"]} if m.get("corregido") else {}),
            }
        )
        if m.get("corregido"):
            # ya se habia dado por resuelto: lo que pasa el umbral desde la correccion es una reaparicion
            out[-1]["texto"] = f"Reaparece después de {m['corregido']['commit'] or 'la corrección'}: {out[-1]['texto']}"
    return out


def correcciones(proyecto: str) -> dict[str, dict]:
    """{metrica: {hallazgo, desde, commit}}: los hallazgos de trabajo que una coordinadora o una persona
    dio por `corregido`, con la evidencia `corregido_en` que dice desde cuando rige la correccion
    (`datos.desde`). Desde ahi se vuelve a medir esa metrica: lo de antes ya no cuenta."""
    con = _leer()
    try:
        filas = con.execute(
            "SELECT h.id, h.datos AS hd, e.datos AS ed, h.estado_fecha FROM nodo h "
            "JOIN vinculo v ON v.de = h.id AND v.relacion = 'corregido_en' AND v.activo = 1 "
            "JOIN nodo e ON e.id = v.a "
            "WHERE h.proyecto = ? AND h.tipo = 'hallazgo' AND h.estado = 'corregido' ORDER BY h.estado_fecha",
            (proyecto,),
        ).fetchall()
    finally:
        con.close()
    out = {}
    for f in filas:
        hd, ed = json.loads(f["hd"] or "{}"), json.loads(f["ed"] or "{}")
        if hd.get("clase") == "optimizacion_trabajo" and hd.get("metrica") and ed.get("desde"):
            out[hd["metrica"]] = {"hallazgo": f["id"], "desde": ed["desde"], "commit": ed.get("commit")}
    return out


def _leer() -> sqlite3.Connection:
    """Sólo lectura, sin crear ni migrar la base, con un tope de LEER_S: corre en el hilo del scheduler.
    Escribir va por optimization_memory._connect, como el resto del análisis en segundo plano."""
    uri = Path(conocimiento.db_path()).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=0.25)
    con.row_factory = sqlite3.Row
    limite = time.monotonic() + LEER_S
    con.set_progress_handler(lambda: int(time.monotonic() > limite), 1000)
    return con


def capturas(proyecto: str, ventana_h: float = VENTANA_H, hasta: dt.datetime | None = None) -> list[dict]:
    hasta = hasta or dt.datetime.now(dt.UTC)
    desde = (hasta - dt.timedelta(hours=ventana_h)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    con = _leer()
    try:
        # de un texto largo alcanza el principio y el final (las metricas miran los primeros 200 y los
        # ultimos 600 caracteres): no se traen a memoria informes y encargos enteros
        filas = con.execute(
            "SELECT id, clase, session_id, origen, bytes, hash, fecha, "
            "CASE WHEN length(texto) <= 1000 THEN texto "
            "ELSE substr(texto, 1, 400) || char(10) || '[…]' || char(10) || substr(texto, -600) END AS texto "
            "FROM captura WHERE proyecto = ? AND fecha >= ? ORDER BY fecha",
            (proyecto, desde),
        ).fetchall()
    finally:
        con.close()
    return [{**dict(f), "origen": json.loads(f["origen"] or "{}"), "fecha": _ts(f["fecha"])} for f in filas]


def analizar(proyecto: str, ventana_h: float = VENTANA_H) -> dict:
    """GET /trabajo/<proyecto>: las métricas de la ventana y los hallazgos que pasan su umbral. Sólo lee."""
    caps = capturas(proyecto, ventana_h)
    metricas = medir(caps)
    for metrica, corr in correcciones(proyecto).items():
        # una metrica dada por corregida se mide solo desde la correccion; si no pasa el umbral, no aparece
        desde = _ts(corr["desde"])
        tramo = [c for c in caps if c["fecha"] >= desde]
        # la del tramo si tiene avisos (la coordinadora puede haber cambiado); si no, la de la ventana
        despues = medir(tramo, coordinadora(tramo) or coordinadora(caps)).get(metrica) or {"valor": 0}
        metricas[metrica] = {**despues, "corregido": corr, "antes": (metricas.get(metrica) or {}).get("valor")}
    return {
        "proyecto": proyecto,
        "ventana_h": ventana_h,
        "capturas": len(caps),
        "desde": caps[0]["fecha"].isoformat() if caps else None,
        "hasta": caps[-1]["fecha"].isoformat() if caps else None,
        "metricas": metricas,
        "hallazgos": hallazgos(metricas),
    }


def registrar(proyecto: str, analisis: dict) -> list[str]:
    """Cada hallazgo como nodo `hallazgo` propuesto, uno por métrica y día (clave_ingesta): un patrón
    que sigue no se repite (sus números quedan los de la primera medición del día), y el del día
    siguiente es otro hallazgo. Devuelve los ids de los nodos NUEVOS."""
    if not analisis.get("hallazgos"):
        return []
    dia = (analisis.get("hasta") or "")[:10]
    con = optimization_memory._connect()
    try:
        ids = []
        with con:
            for h in analisis["hallazgos"]:
                nodo = conocimiento.crear_nodo(
                    proyecto,
                    "hallazgo",
                    h["texto"],
                    {
                        "clase": "optimizacion_trabajo",
                        "metrica": h["metrica"],
                        "valor": h["valor"],
                        "umbral": h["umbral"],
                        "sugerencia": h["sugerencia"],
                        "capturas_ejemplo": h["ejemplos"],
                        "ventana_h": analisis["ventana_h"],
                        "capturas_revisadas": analisis["capturas"],
                        "beneficio": "no medido",
                        "requiere_veredicto": True,
                    },
                    autor="server",
                    origen={"modulo": "optimizacion_trabajo", "dia": dia},
                    clave_ingesta=f"trabajo:{h['metrica']}:{dia}" + (":reaparece" if h.get("corregido") else ""),
                    con=con,
                )
                if h.get("corregido") and nodo.get("creado", True):
                    # la reaparicion queda atada al hallazgo resuelto: reabrirlo es un veredicto
                    conocimiento.vincular(
                        proyecto,
                        nodo["id"],
                        "mismo_que",
                        h["corregido"]["hallazgo"],
                        autor="server",
                        motivo="la metrica volvio a pasar su umbral despues de la correccion",
                        con=con,
                    )
                if nodo.get("creado", True):
                    ids.append(nodo["id"])
                creencias.proponer(
                    proyecto,
                    {"texto": h["texto"], "accion": h["sugerencia"], "dimension": "coordinacion",
                     "fuentes": [nodo["id"]], "contexto": {},
                     "excepciones": "Patrón observado; beneficio de la acción todavía no medido"},
                    autor="server", con=con,
                )
        return ids
    finally:
        con.close()
