"""Los tres niveles del registro. El 1 es el crudo que guarda el lienzo (capturas, lienzo.log y eventos
de hooks que nadie consumió) y se depura a los RETENCION_DIAS (decisión 5 de Ariel, 2026-10-22); el 2
(`herramientas`) es para el investigador y el 3 (`externo`) para sistemas externos. Las transcripciones
son de cada CLI: no se modifican ni se depuran."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
import traceback

import agent_evaluation
import conocimiento as k
import state
import transcripts

RETENCION_DIAS = 30
LOTE_CAPTURAS = 2000  # filas por transacción: el lock de escritura dura poco aunque haya mucho viejo
_FECHA = re.compile(rb"\d{4}-\d{2}-\d{2}")


def herramientas(session: dict, *, limite: int = 80) -> dict:
    """Nivel 2 por turno/paso; nunca argumentos, texto de resultados ni consumo libre."""
    if not 1 <= limite <= 80:
        raise ValueError("limite debe estar entre 1 y 80")
    path = session.get("transcript_path")
    if not path:
        return {"disponible": False, "motivo": "sin transcripción", "pasos": []}
    try:
        page = transcripts.turns(session["agent"], path, 10, leaf_id=transcripts.leaf_of(session))
    except (OSError, ValueError, KeyError) as error:
        return {"disponible": False, "motivo": type(error).__name__, "pasos": []}
    report = agent_evaluation.summarize(session, page)
    evidence = report["evidence"]
    steps = []
    # El índice es el del bloque original, permite reconstruir el orden aun con texto intercalado.
    for turn in page.get("turns", []):
        for index, block in enumerate(turn.get("blocks", [])):
            if block.get("kind") != "tool":
                continue
            result = block.get("result")
            known = isinstance(result, dict)
            steps.append(
                {
                    "turno": re.sub(r"[^a-zA-Z0-9_.:-]", "", str(turn.get("id", "")))[:80],
                    "paso": index,
                    "herramienta": re.sub(r"[^a-zA-Z0-9_.:-]", "", str(block.get("name", "?")))[:80],
                    "resultado_conocido": known,
                    "error": result.get("is_error") is True if known else None,
                    "caracteres": len(str(result.get("text") or "")) if known else None,
                    "duracion_s": None,  # La fuente no informa duración individual.
                }
            )
    return {
        "disponible": not evidence["unavailable"],
        "pasos": steps[-limite:],
        "omitidos": max(0, len(steps) - limite),
        "hay_mas": evidence["has_more"],
        "parcial": True,
        "alcance": "últimos 10 turnos; duraciones individuales no disponibles",
        "turnos": [{"turno": d["turn"], "duracion_s": d["seconds"]} for d in report["durations"]],
    }


def externo(proyecto: str) -> dict:
    """Nivel 3: actividad agregada por proyecto, sin prosa interna, IDs de sesión ni rutas.

    Una vista mínima deliberada: los resúmenes narrativos requieren curaduría humana.
    La API debe validar autorización antes de invocar esta función.
    """
    with k._abrir(proyecto) as con:
        rows = con.execute(
            "SELECT tipo, estado, COUNT(*) AS cantidad FROM nodo "
            "WHERE proyecto=? AND tipo NOT IN ('sesion','captura') "
            "GROUP BY tipo, estado ORDER BY tipo, estado",
            (proyecto,),
        ).fetchall()
    return {"nivel": 3, "proyecto": proyecto, "actividad": [dict(row) for row in rows]}


# Qué del nivel 3 sale con texto: tipo -> estados vivos. Lo revertido, reemplazado, rechazado o ya
# contestado no es «qué hay hoy». Encargos, informes y evidencia quedan fuera: son prosa interna. La
# excepción son los informes del resumidor (`resumidor.CLASE`): son el nivel 3 escrito para afuera.
NIVEL3_ESTADOS = {
    "decision": ("vigente", "propuesta"),
    "hallazgo": ("propuesto", "confirmado"),
    "pregunta": ("abierta",),
}
RESUMEN = "resumen_nivel3"  # resumidor.CLASE, sin importarlo: el resumidor importa el investigador
NIVEL3_LIMITE = 30
NIVEL3_TEXTO = 300
_RUTA = re.compile(r"(?:\b[A-Za-z]:[\\/]|~[\\/]|(?<![\w.:/])/(?=[\w.-]+/))[^\s\"'<>|`]*")
_ID = re.compile(r"\b[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\b")


def _limpio(texto: str | None) -> str:
    """Texto apto para afuera: secretos tapados, sin rutas ni IDs (de sesión o de nodo), recortado."""
    import captura  # captura importa este paquete de memoria; diferido como el investigador

    out, _ = captura.tapar(texto or "")
    out = _ID.sub("[id]", _RUTA.sub("[ruta]", out))
    out = " ".join(out.split())
    return out if len(out) <= NIVEL3_TEXTO else out[: NIVEL3_TEXTO - 1] + "…"


def _filtro_vivos(alias: str = "n") -> str:
    # constantes del modulo, no entrada del cliente
    return (
        "("
        + " OR ".join(
            f"({alias}.tipo = '{t}' AND {alias}.estado IN ({','.join(repr(e) for e in es)}))"
            for t, es in NIVEL3_ESTADOS.items()
        )
        + f" OR {alias}.tipo = 'tema'"
        + f" OR ({alias}.tipo = 'informe' AND json_extract({alias}.datos, '$.clase') = '{RESUMEN}'))"
    )


def _temas_de(con: sqlite3.Connection, ids: list[str]) -> dict[str, list[str]]:
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out: dict[str, list[str]] = {}
    for r in con.execute(
        f"SELECT v.de, t.texto FROM vinculo v JOIN nodo t ON t.id = v.a "
        f"WHERE v.activo = 1 AND v.relacion IN ('sobre','aplica_a') AND t.tipo = 'tema' AND v.de IN ({q}) "
        "ORDER BY t.texto",
        ids,
    ):
        out.setdefault(r["de"], []).append(_limpio(r["texto"]))
    return out


def _items(con: sqlite3.Connection, filas) -> list[dict]:
    filas = list(filas)
    temas = _temas_de(con, [r["id"] for r in filas])
    return [_resumen(r, temas) if r["tipo"] == "informe" else _item(r, temas) for r in filas]


def _item(r, temas: dict) -> dict:
    return {
        "tipo": r["tipo"],
        "texto": _limpio(r["texto"]),
        "estado": r["estado"],
        "fecha": (r["estado_fecha"] or r["fecha"])[:10],
        "temas": temas.get(r["id"], []),
    }


def _resumen(r, temas: dict) -> dict:
    """Un día resumido: qué se hizo en viñetas y en qué quedó. `revisado` dice si Ariel ya lo miró."""
    datos = json.loads(r["datos"] or "{}")
    return {
        "tipo": "resumen",
        "dia": datos.get("dia") or r["fecha"][:10],
        "que_se_hizo": [_limpio(x) for x in datos.get("que_se_hizo") or []][:8],
        "en_que_quedo": _limpio(datos.get("en_que_quedo")),
        "temas": temas.get(r["id"], []),
        "revisado": r["estado"] == "revisado",
    }


def externo_detalle(proyecto: str, *, limite: int = NIVEL3_LIMITE) -> dict:
    """Nivel 3 con contenido: qué se hizo por día (resumidor), temas del proyecto y lo vivo de decisiones,
    hallazgos y preguntas, lo más reciente primero. Mismo contrato que `externo`: sin prosa interna, IDs de sesión ni rutas."""
    limite = max(1, min(int(limite), NIVEL3_LIMITE))
    base = externo(proyecto)
    with k._abrir(proyecto) as con:
        temas = [
            {"tema": _limpio(r["texto"]), "nodos": r["n"]}
            for r in con.execute(
                "SELECT t.texto, COUNT(v.de) AS n FROM nodo t LEFT JOIN vinculo v ON v.a = t.id AND v.activo = 1 "
                "AND v.relacion IN ('sobre','aplica_a') WHERE t.proyecto = ? AND t.tipo = 'tema' "
                "GROUP BY t.id ORDER BY n DESC, t.texto LIMIT ?",
                (proyecto, limite),
            )
        ]
        resumenes = _items(
            con,
            con.execute(
                "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'informe' AND json_extract(datos, '$.clase') = ? "
                "ORDER BY json_extract(datos, '$.dia') DESC, id LIMIT ?",
                (proyecto, RESUMEN, limite),
            ),
        )
        listas = {}
        for tipo, estados in NIVEL3_ESTADOS.items():
            q = ",".join("?" * len(estados))
            listas[tipo] = _items(
                con,
                con.execute(
                    f"SELECT * FROM nodo WHERE proyecto = ? AND tipo = ? AND estado IN ({q}) "
                    "ORDER BY COALESCE(estado_fecha, fecha) DESC, id LIMIT ?",
                    (proyecto, tipo, *estados, limite),
                ),
            )
    return {
        **base,
        "que_se_hizo": resumenes,
        "temas": temas,
        "decisiones": listas["decision"],
        "hallazgos": listas["hallazgo"],
        "preguntas": listas["pregunta"],
    }


def externo_buscar(proyecto: str, consulta: str, *, limite: int = 20) -> dict:
    """Búsqueda BM25 (la de la memoria, v5 §7.1) restringida a lo que `externo_detalle` deja salir."""
    consulta = k._texto(consulta, "q", 500)
    limite = max(1, min(int(limite), NIVEL3_LIMITE))
    with k._abrir(proyecto) as con:
        try:
            filas = con.execute(
                "SELECT n.* FROM nodo_fts JOIN nodo n ON n.rowid = nodo_fts.rowid "
                f"WHERE nodo_fts MATCH ? AND n.proyecto = ? AND {_filtro_vivos()} "
                "ORDER BY bm25(nodo_fts, 3.0, 1.0), n.id LIMIT ?",
                (consulta, proyecto, limite),
            ).fetchall()
        except sqlite3.OperationalError as e:
            raise k._rechazo_fts(e) from e
        return {"nivel": 3, "proyecto": proyecto, "consulta": consulta, "resultados": _items(con, filas)}


def externo_indice() -> dict:
    """Los proyectos con algo vivo en el nivel 3: id, nombre y cuántos de cada tipo. Sin carpetas ni remotes."""
    filtro = _filtro_vivos()
    with k._Conexion(k.db_path()) as con:
        cuentas: dict[str, dict] = {}
        for r in con.execute(
            f"SELECT n.proyecto, n.tipo, COUNT(*) AS c, MAX(COALESCE(n.estado_fecha, n.fecha)) AS f "
            f"FROM nodo n WHERE {filtro} GROUP BY n.proyecto, n.tipo"
        ):
            p = cuentas.setdefault(r["proyecto"], {"cantidades": {}, "ultima_fecha": ""})
            p["cantidades"]["resumen" if r["tipo"] == "informe" else r["tipo"]] = r["c"]
            p["ultima_fecha"] = max(p["ultima_fecha"], (r["f"] or "")[:10])
    nombres = {p["id"]: p.get("nombre") for p in k.proyectos()}
    proyectos = [
        {"proyecto": pid, "nombre": _limpio(nombres.get(pid) or pid), **datos}
        for pid, datos in cuentas.items()
        if pid in nombres
    ]
    proyectos.sort(key=lambda p: (p["ultima_fecha"], p["proyecto"]), reverse=True)
    return {"nivel": 3, "proyectos": proyectos}


def depurar_crudo(dias: int = RETENCION_DIAS, *, ahora: dt.datetime | None = None) -> dict:
    """Nivel 1: borra lo crudo anterior al corte (ahora menos `dias`) y devuelve qué se fue y cuánto pesa."""
    if not 1 <= dias <= 3650:
        raise ValueError("dias debe estar entre 1 y 3650")
    ahora = ahora or dt.datetime.now(dt.UTC)
    corte = ahora - dt.timedelta(days=dias)
    return {
        "dias": dias,
        "corte": corte.isoformat(timespec="seconds"),
        "capturas": _parte(_depurar_capturas, corte),
        "log": _parte(_depurar_log, corte),
        "eventos": _parte(_depurar_eventos, corte),
    }


def _parte(fn, corte: dt.datetime) -> dict:
    """Cada parte por su cuenta: una base trabada no deja sin depurar el log ni los eventos."""
    try:
        return fn(corte)
    except (OSError, sqlite3.Error, ValueError) as error:
        return {"error": f"{type(error).__name__}: {error}"[:200]}


def _depurar_capturas(corte: dt.datetime) -> dict:
    """Capturas con fecha (UTC, formato de `k.ahora`) anterior al corte. Nunca la de rowid más alto: sin
    AUTOINCREMENT SQLite lo reusaría y el cursor de réplica de otra PC se saltearía las nuevas. Cada PC
    depura su copia; borrar no es un cambio y no viaja. El archivo no se achica (sin VACUUM): las
    páginas liberadas las reusan las capturas siguientes."""
    import research_creencias  # el investigador usa el nivel 2: evitar el ciclo al importar
    import resumidor

    path = k.db_path()
    out = {"filas": 0, "bytes": 0, "quedan": 0, "archivo": 0}
    if not os.path.isfile(path):
        return out  # sin base todavía no hay crudo: no se crea por depurar
    limite = corte.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    # Lo leído por los dos: el investigador (nivel 4) y el resumidor (nivel 3). Un proyecto al que le
    # falta el cursor de alguno no está en las marcas y no se depura.
    leidas = [research_creencias.resguardo_capturas(), resumidor.resguardo_capturas()]
    marcas = {}
    for proyecto in set(leidas[0]).intersection(*leidas[1:]):
        fechas = []
        for hasta in (cursor[proyecto] for cursor in leidas):
            fecha = dt.datetime.fromisoformat(hasta)
            if fecha.tzinfo is None:
                raise ValueError(f"cursor de capturas sin zona: {proyecto}")
            fechas.append(fecha)
        marcas[proyecto] = min(fechas).astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    marcas_json = json.dumps(marcas)
    viejas = (
        "SELECT rowid, bytes FROM captura WHERE fecha < ? AND rowid < (SELECT MAX(rowid) FROM captura) "
        # Sin cursor no sabemos si se leyó: conservar hasta que el investigador avance.
        "AND fecha <= (SELECT value FROM json_each(?) WHERE key = captura.proyecto) "
        "ORDER BY rowid LIMIT ?"
    )
    parametros = (limite, marcas_json, LOTE_CAPTURAS)
    with k._Conexion(path) as con:
        while True:
            con.execute("BEGIN IMMEDIATE")
            n, b = con.execute(f"SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM ({viejas})", parametros).fetchone()
            if n:
                con.execute(f"DELETE FROM captura WHERE rowid IN (SELECT rowid FROM ({viejas}))", parametros)
            con.commit()
            out["filas"] += n
            out["bytes"] += b
            if n < LOTE_CAPTURAS:
                break
        out["quedan"] = con.execute("SELECT COUNT(*) FROM captura").fetchone()[0]
    out["archivo"] = os.path.getsize(path)
    return out


def _depurar_log(corte: dt.datetime) -> dict:
    """Exclusión con state.log desde la lectura hasta replace; un append nunca queda en el archivo viejo.
    Lock propio del archivo, sin tomar el lock de sesiones ni escribir a consola desde esta sección."""
    with state.log_lock:
        return _depurar_log_exclusivo(corte)


def _depurar_log_exclusivo(corte: dt.datetime) -> dict:
    """Con log_lock tomado. Las continuaciones de traceback acompañan su línea fechada anterior."""
    path = state.LOG
    try:
        antes = os.path.getsize(path)
    except OSError:
        return {"lineas": 0, "antes": 0, "despues": 0}
    desde = corte.astimezone().strftime("%Y-%m-%d").encode()
    lineas, offset = 0, None
    with open(path, "rb") as f:
        for linea in iter(f.readline, b""):
            m = _FECHA.match(linea)
            if m and m.group() >= desde:
                offset = f.tell() - len(linea)
                break
            lineas += 1
        else:
            offset = f.tell()  # todo viejo (o sin fechas): no queda nada
    if not lineas:
        return {"lineas": 0, "antes": antes, "despues": antes}
    tmp = f"{path}.{os.getpid()}.depurando"
    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            src.seek(offset)
            esperas = 0
            while True:
                bloque = src.read(1 << 20)
                if bloque:
                    dst.write(bloque)
                    continue
                if os.path.getsize(path) <= src.tell():
                    break
                esperas += 1  # una línea a medio escribir: el tamaño llegó antes que los datos
                if esperas > 100:
                    raise TimeoutError("lienzo.log no se asienta")
                time.sleep(0.01)
        os.replace(tmp, path)
    except OSError as error:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"lineas": 0, "antes": antes, "despues": antes, "error": type(error).__name__}
    return {"lineas": lineas, "antes": antes, "despues": os.path.getsize(path)}


def _depurar_eventos(corte: dt.datetime) -> dict:
    """Eventos de hooks a medio escribir (`.tmp`) que quedaron huérfanos: los `.json` los consume
    `hooks_eventos`, y uno trabado es un error a mirar, no crudo para borrar."""
    out = {"archivos": 0, "bytes": 0}
    try:
        nombres = os.listdir(state.EVENTS)
    except OSError:
        return out
    tope = corte.timestamp()
    for nombre in nombres:
        if not nombre.endswith(".tmp"):
            continue
        p = os.path.join(state.EVENTS, nombre)
        try:
            st = os.stat(p)
            if st.st_mtime >= tope:
                continue
            os.remove(p)
        except OSError:
            continue
        out["archivos"] += 1
        out["bytes"] += st.st_size
    return out


def bucle(parar: threading.Event | None = None, *, arranque_s: float = 600.0, cada_s: float = 86400.0) -> None:
    """Hilo del server: depura el crudo una vez por día (la primera, `arranque_s` después de arrancar) y lo
    deja en lienzo.log. Un error se registra y se reintenta en la próxima vuelta."""
    parar = parar or threading.Event()
    if parar.wait(arranque_s):
        return
    while True:
        try:
            state.log(f"registro: crudo depurado a {RETENCION_DIAS} días {depurar_crudo()}")
        except Exception:  # un hilo de mantenimiento no puede morir por una vuelta
            state.log("registro: falló la depuración del crudo\n" + traceback.format_exc())
        if parar.wait(cada_s):
            return
