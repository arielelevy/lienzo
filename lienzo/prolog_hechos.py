"""Hechos medidos y contexto sugerido para una vuelta; ausencia no equivale a cero."""

from __future__ import annotations

import datetime as dt

import prolog_programa


def desde_creencia(node):
    """Metadatos automáticos como hechos; vacío desconocido no agrega comodines."""
    facts = []
    for key, values in node["datos"].get("metadatos", {}).items():
        pred = "ruta" if key == "rutas" else key
        if prolog_programa.VOCABULARIO.get(pred) != ("texto", "texto"):
            continue
        values = [values] if key == "proyecto" and isinstance(values, str) else values
        if isinstance(values, list):
            facts.extend({"pred": pred, "args": [node["id"], val]} for val in values if isinstance(val, str) and val)
    return facts


def medir(pid, contexto, *, leer_memoria=None, sesiones=None, ahora=None):
    if leer_memoria is None:
        import health

        leer_memoria = health._memoria
    now = ahora or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise ValueError("la foto necesita fecha con zona horaria")
    subject = "trabajo:" + pid
    facts = [{"pred": "proyecto", "args": [subject, pid]}]
    limits = ["Chrome, WSL y cuotas no fueron medidos: quedan desconocidos"]
    for key, val in contexto.items():
        if isinstance(val, str) and prolog_programa.VOCABULARIO.get(key) == ("texto", "texto"):
            facts.append({"pred": key, "args": [subject, val]})
    stamp = {"observada_en": now.isoformat(), "vigente_hasta": (now + dt.timedelta(seconds=30)).isoformat()}
    try:
        free, _ = leer_memoria()
    except OSError as exc:
        free = None
        limits.append(f"No se pudo medir memoria: {exc}")
    if type(free) in (int, float) and free >= 0:
        facts.append({"pred": "memoria_libre_gb", "args": [subject, free], **stamp})
    else:
        limits.append("Memoria libre desconocida")
    if sesiones is not None:
        count = sum(
            bool(s.get("alive")) and not s.get("stopped_by") and not s.get("remote") and not s.get("coordinator")
            for s in sesiones
        )
        facts.append({"pred": "frentes_activos", "args": [subject, count], **stamp})
    else:
        limits.append("Frentes desconocidos: no se recibió foto de sesiones")
    return {"hechos": facts, "limitaciones": limits, "fecha": now.isoformat()}
