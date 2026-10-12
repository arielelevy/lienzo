"""Propuestas idempotentes en la memoria existente; ninguna confirma un beneficio."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import conocimiento


def sources(project: str) -> list[str]:
    # No crear/migrar una base en segundo plano. Solo proyectos con memoria inicializada.
    con = _connect()
    try:
        rows = con.execute("SELECT id FROM nodo WHERE proyecto=? AND tipo='incidente' ORDER BY fecha DESC,id DESC LIMIT 30",
                           (project,)).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def source_snapshot(project: str) -> dict:
    con = _connect()
    try:
        rows = con.execute("SELECT id,fecha,datos,origen FROM nodo WHERE proyecto=? AND tipo='incidente' ORDER BY fecha DESC,id DESC LIMIT 30", (project,)).fetchall()
        version = hashlib.sha256(json.dumps([list(r) for r in rows], ensure_ascii=True).encode()).hexdigest()
        return {"ids": [r[0] for r in rows], "version": version}
    finally:
        con.close()


def _connect():
    uri = Path(conocimiento.db_path()).resolve().as_uri() + "?mode=rw"
    con = sqlite3.connect(uri, uri=True, timeout=.25)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    deadline = time.monotonic() + 1
    con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return con


def propose(project: str, source_id: str) -> str | None:
    con = _connect()
    try:
        with con:
            row = con.execute("SELECT * FROM nodo WHERE proyecto=? AND id=? AND tipo='incidente'", (project, source_id)).fetchone()
            if row is None:
                raise ValueError("incidente fuente ausente o de otro proyecto")
            data = json.loads(row["datos"])
            tool = str(data.get("herramienta", "")).lower()
            profile = _candidate(tool)
            if profile is None:
                return None
            context = {key: data.get(key) for key in ("agente", "modelo", "pc", "version")}
            sid = json.loads(row["origen"]).get("session_id")
            if sid:
                session = con.execute("SELECT datos FROM nodo WHERE proyecto=? AND clave_ingesta=?", (project, f"sesion:{sid}")).fetchone()
                if session:
                    session_data = json.loads(session["datos"])
                    for key, value in context.items():
                        if value is None:
                            context[key] = session_data.get(key)
            digest = hashlib.sha256(json.dumps([source_id, row["fecha"], profile, context], sort_keys=True).encode()).hexdigest()
            expires = (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat()
            hypothesis = conocimiento.crear_nodo(project, "decision", f"Probar {profile} con oráculo y comparación OFF/ON",
                {"clase": "hipotesis_optimizacion", "motivo": "Incidente observado; beneficio desconocido",
                 "fuentes": [source_id], "contexto": context, "perfil": profile, "vigente_hasta": expires,
                 "confianza": "sin validación empírica", "resultado": "experimento no ejecutado",
                 "comparacion": "misma tarea/contexto/oráculo, OFF frente a ON",
                 "rollback": "restaurar perfil previo solo en lanzamientos futuros",
                 "presupuesto_usd": None, "requiere_veredicto": True},
                autor="server", origen={"modulo": "optimization_scheduler", "fuente": source_id},
                clave_ingesta="optimization:" + digest, con=con)
            conocimiento.vincular(project, hypothesis["id"], "motivada_por", source_id,
                                  autor="server", motivo="fuente observada, no prueba de mejora", con=con)
            return hypothesis["id"]
    finally:
        con.close()


def _candidate(tool: str) -> str | None:
    if any(t in tool for t in ("shell", "bash", "exec", "powershell")):
        return "RTK"
    if any(t in tool for t in ("read", "grep", "search")):
        return "CodeGraph"
    return None


def record_analysis(project: str, job_id: str, count: int, hypotheses: list[str]) -> str:
    con = _connect()
    try:
        with con:
            evidence = conocimiento.crear_nodo(project, "evidencia", "Análisis local de incidentes; beneficio no medido",
                {"clase": "analisis_optimizacion", "referencia": "optimization-job:" + job_id,
                 "fuentes_revisadas": count, "hipotesis": hypotheses, "experimentos_ejecutados": 0,
                 "costo_servicios_usd": 0, "calidad": "no evaluada"}, autor="server",
                clave_ingesta="optimization-analysis:" + job_id, con=con)
            for hypothesis in hypotheses:
                conocimiento.vincular(project, hypothesis, "apoya", evidence["id"], autor="server", con=con)
            return evidence["id"]
    finally:
        con.close()


def record_local_experiment(project: str, artifact: str, profiles: list[dict]) -> str:
    con = _connect()
    try:
        with con:
            node = conocimiento.crear_nodo(project, "evidencia", "OFF/ON de contratos locales; no valida agentes",
                {"clase": "experimento_local", "referencia": artifact,
                 "perfiles": [{k: p[k] for k in ("profile", "code", "seconds", "output_chars")} for p in profiles],
                 "service_cost_usd": 0, "agent_quality": "no evaluada", "requires_verdict": True},
                autor="server", clave_ingesta="off-on:" + artifact, con=con)
            return node["id"]
    finally:
        con.close()


def record_jev(project: str, artifact: str, decision: dict) -> str:
    con = _connect()
    try:
        with con:
            node = conocimiento.crear_nodo(project, "evidencia", "Piloto Jev: hipótesis, sin etiqueta de calidad",
                {"clase": "piloto_jev", "referencia": artifact,
                 "hipotesis": decision["choice"], "probabilidades": decision["probabilities"],
                 "service_cost_usd": decision["usage"]["cost"], "usage": decision["usage"],
                 "model": decision["model"], "generation_id": decision["id"],
                 "calidad": "sin oráculo independiente", "requires_verdict": True},
                autor="server", clave_ingesta="jev-pilot:" + artifact, con=con)
            return node["id"]
    finally:
        con.close()
