"""Recuentos de una muestra; no puntúan calidad ni convierten bytes en tokens."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

import transcripts


def _duration(turn: dict) -> float | None:
    if not turn.get("ended"):
        return None
    try:
        start = dt.datetime.fromisoformat(turn["ts_start"])
        end = dt.datetime.fromisoformat(turn["ts_end"])
        if start.tzinfo is None or end.tzinfo is None:
            return None
        value = (end - start).total_seconds()
        return value if value >= 0 else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def summarize(session: dict, page: dict) -> dict:
    refs, durations, usages = [], [], []
    count = {"turns": 0, "closed": 0, "tools": 0, "known_results": 0,
             "missing_results": 0, "errors": 0, "output_characters": 0}
    for turn in page.get("turns", []):
        count["turns"] += 1
        count["closed"] += bool(turn.get("ended"))
        duration = _duration(turn)
        if duration is not None:
            durations.append({"turn": turn["id"], "seconds": duration})
        if isinstance(turn.get("usage"), dict):
            usages.append({"turn": turn["id"], "reported": turn["usage"]})
        for block in turn.get("blocks", []):
            if block.get("kind") != "tool":
                continue
            count["tools"] += 1
            result = block.get("result")
            known = isinstance(result, dict)
            error = known and result.get("is_error") is True
            count["known_results"] += known
            count["missing_results"] += not known
            count["errors"] += error
            chars = len(str(result.get("text") or "")) if known else None
            count["output_characters"] += chars or 0
            # Nombres/IDs se restringen antes de enviar: nada de argumentos, prompts o salidas crudas.
            refs.append({"turn": str(turn.get("id", ""))[:80], "tool_id": str(block.get("id", ""))[:80],
                         "tool": re.sub(r"[^a-zA-Z0-9_.:-]", "", str(block.get("name", "?")))[:80],
                         "characters": chars, "error": bool(error), "result_known": known})
    meta = page.get("meta", {})
    unavailable = not page.get("turns") and bool(page.get("note"))
    evidence = {"counts": {k: None for k in count} if unavailable else count, "tools": refs[-80:], "partial": True,
                "unavailable": unavailable,
                "has_more": bool(page.get("has_more")), "truncated": meta.get("truncated"),
                "tool_refs_omitted": max(0, len(refs) - 80),
                "scope": "ultimos 10 turnos leidos; texto de resultados puede estar recortado"}
    snapshot = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {"session_id": session["session_id"], "agent": session["agent"],
            "pc": session.get("pc"), "project": session.get("repo"),
            "model": session.get("model"), "version": meta.get("version"),
            "evidence": evidence, "snapshot": snapshot, "durations": durations,
            "usage": usages, "usage_note": "Consumo informado por fuente; no se suma como total. Codex puede informar acumulados.",
            "quality": "sin validacion funcional; no evaluada", "note": page.get("note")}


def evaluate(session: dict) -> dict:
    path = session.get("transcript_path")
    if not path:
        return summarize(session, {"note": "sin transcripcion", "turns": [], "meta": {}})
    page = transcripts.turns(session["agent"], path, 10, leaf_id=transcripts.leaf_of(session))
    return summarize(session, page)
