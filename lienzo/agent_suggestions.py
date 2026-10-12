"""Sugerencias con citas; el juez nunca configura herramientas ni ejecuta acciones."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import agent_evaluation
import jev
import jev_credentials
import optimization_budget
import optimization_cost
import optimization_experiment
import optimization_pilot
import state

JUDGE_LOCK = threading.Lock()


def suggestions(report: dict) -> list[dict]:
    refs = report["evidence"]["tools"]
    out = []
    for ref in refs:
        if (ref["characters"] or 0) >= 2000 and any(x in ref["tool"].lower() for x in ("shell", "bash", "exec", "powershell")):
            out.append({"tool": "rtk", "evidence": ref,
                        "action": "Probar RTK en este comando y comparar diagnosticos y salida original",
                        "limit": "La longitud no demuestra desperdicio ni ahorro facturado"})
        elif any(x in ref["tool"].lower() for x in ("read", "grep", "search")):
            out.append({"tool": "codegraph", "evidence": ref,
                        "action": "Evaluar un indice de codigo si esta exploracion se repite",
                        "limit": "Leer codigo puede ser necesario; verificar vigencia y cobertura del indice"})
        if len(out) >= 4:
            break
    return out


def report(session: dict) -> dict:
    data = agent_evaluation.evaluate(session)
    data["suggestions"] = suggestions(data)
    data["jev_max_cost_usd"] = jev.MAX_COST
    data["jev_available"] = False
    data["paid_block_reason"] = optimization_cost.status()["jev"]["reason"]
    budget = optimization_budget.Budget().status()
    if budget.get("pilot") and budget["pilot"]["within_window"]:
        data["jev_available"] = bool(jev_credentials.available() and optimization_budget.Budget().pilot_eligible("manual-status-only"))
        data["paid_block_reason"] = "precio/cooldown/tope y muestra se revalidan antes de enviar"
    return data


def judge(session: dict, data: dict) -> dict:
    if data.get("allow_cost") is not True or not isinstance(data.get("snapshot"), str):
        raise ValueError("revisar la muestra y autorizar el costo antes de consultar Jev")
    if not JUDGE_LOCK.acquire(blocking=False):
        raise ValueError("hay otra consulta Jev en curso; no se lanzo una segunda")
    try:
        current = report(session)
        if current["snapshot"] != data["snapshot"]:
            raise ValueError("la muestra cambio; actualizala antes de consultar Jev")
        if not current["evidence"]["tools"]:
            raise ValueError("no hay herramientas observadas para consultar Jev")
        budget = optimization_budget.Budget().status()
        if budget.get("pilot"):
            sample = optimization_pilot.sample(current, optimization_experiment.manifest())
            decision = jev.pilot_decide(sample["state"], sample["snapshot"])
        else:
            decision = jev.decide(current["evidence"])
        payload = {"session_id": session["session_id"], "snapshot": current["snapshot"],
                   "evidence": current["evidence"], "decision": decision}
        root = Path(state.LIENZO) / "improvements"
        # Archivo propio con nombre aleatorio: el id del proveedor nunca decide una ruta.
        import secrets
        target = root / f"{secrets.token_hex(12)}.json"
        try:
            root.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            raise ValueError(f"Jev respondio y cobro USD {decision['usage']['cost']}, pero no se pudo guardar el informe") from None
        return payload
    finally:
        JUDGE_LOCK.release()
