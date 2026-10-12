"""Muestras métricas privadas: sin prompts, etiquetas inventadas ni cambios de perfil."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path

import optimization_budget
import optimization_cost
import state


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def sample(report: dict, source_version: str) -> dict:
    context = report["context"]
    safe_context = {name + "_sha256": digest(context.get(name))
                    for name in ("project", "agent", "model", "version", "profile", "profile_origin")}
    safe_context.update(session_sha256=digest(report.get("session_id")),
                        source_version_sha256=digest(source_version),
                        evidence_sha256=digest(report["evidence"]),
                        profile="unknown", profile_origin="launch_evidence_unavailable")
    original = report["evidence"]
    counts = {}
    for name in ("turns", "closed", "tools", "known_results", "missing_results", "errors", "output_characters"):
        value = original["counts"].get(name)
        if value is not None and (type(value) is not int or not 0 <= value <= 10**12):
            raise ValueError("métrica inválida")
        counts[name] = value
    evidence = {"counts": counts, "partial": True,
                "unavailable": bool(original.get("unavailable")),
                "has_more": bool(original.get("has_more")),
                "quality_labels_available": False,
                "causal_comparison_available": False}
    body = {"context": safe_context, "metrics": evidence}
    return {"state": body, "snapshot": digest(body),
            "quality": "sin etiquetas independientes; confianza no es acierto"}


def activate() -> dict:
    """Acción autorizada explícita; reserva TODO uso de clave para el único400.

    usage es all-time, no ventana diaria. Se conserva costo real desconocido.
    El archivo DPAPI debe preceder al intento; una rotación posterior bloquea.
    """
    import jev
    import jev_credentials
    key = jev_credentials.load()
    attempted = dt.datetime.fromisoformat("2026-10-12T15:11:02.917+00:00").timestamp()
    if jev_credentials.path().stat().st_mtime > attempted:
        raise ValueError("credencial cambió desde400; falta acreditar identidad histórica")
    request = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key})
    with jev._open(request, timeout=12) as response:
        raw = response.read(128001)
    if len(raw) > 128000:
        raise ValueError("respuesta de facturación demasiado grande")
    info = json.loads(raw)["data"]
    usage = optimization_budget.money(info.get("usage"))
    byok = optimization_budget.money(info.get("byok_usage"))
    if info.get("limit_reset") is not None or usage < optimization_budget.money(".00002268"):
        raise ValueError("histórico all-time de clave no acreditado")
    quote = optimization_cost.fresh_jev_quote()
    proof = {"source": "https://openrouter.ai/api/v1/key",
             "semantics_source": "https://openrouter.ai/docs/api_reference/limits",
             "retrieved_at": dt.datetime.now(dt.UTC).isoformat(),
             "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
             "usage_usd": str(usage), "byok_usage_usd": str(byok),
             "maximum_usd": str(usage + byok), "actual_cost_usd": None,
             "charge": "jev-initial-http400", "quote": quote,
             "note": "Sobre-reserva total de clave, incluye otros proyectos; no se libera automáticamente"}
    root = Path(state.LIENZO) / "improvements"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("historical-bound-" + digest(proof) + ".json")
    path.write_text(json.dumps(proof, ensure_ascii=True), encoding="utf-8")
    budget = optimization_budget.Budget()
    current = budget.activate()
    if current.get("reserved_usd") and optimization_budget.money(current["reserved_usd"]) > usage + byok:
        raise ValueError("reserva existente mayor; no reducir histórico")
    budget.bound_historical("jev-initial-http400", usage + byok, str(path))
    budget.start_pilot()
    return budget.status()


def save(sample_data: dict, decision: dict) -> str:
    """Resultado observado con coste; la hipótesis sigue sin veredicto."""
    root = Path(state.LIENZO) / "improvements"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("pilot-" + sample_data["snapshot"] + ".json")
    payload = {**sample_data, "decision": decision, "requires_verdict": True,
               "observed_at": dt.datetime.now(dt.UTC).isoformat(),
               "actual_cost_usd": decision["usage"]["cost"]}
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    return str(path)
