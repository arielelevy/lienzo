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

    path = k.db_path()
    out = {"filas": 0, "bytes": 0, "quedan": 0, "archivo": 0}
    if not os.path.isfile(path):
        return out  # sin base todavía no hay crudo: no se crea por depurar
    limite = corte.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    marcas = {}
    for proyecto, hasta in research_creencias.resguardo_capturas().items():
        fecha = dt.datetime.fromisoformat(hasta)
        if fecha.tzinfo is None:
            raise ValueError(f"cursor de capturas sin zona: {proyecto}")
        marcas[proyecto] = fecha.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
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
