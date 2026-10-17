"""Proyecciones de registro. No modifica ni depura fuentes o transcripciones."""

from __future__ import annotations

import re

import agent_evaluation
import conocimiento as k
import transcripts


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
