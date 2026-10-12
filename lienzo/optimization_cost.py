"""Cotas comprobables; una estimación económica nunca habilita un envío."""
from __future__ import annotations


def maximum(adapter: str) -> str:
    if adapter == "local-rtk-contract":
        return "0"
    if adapter == "jev":
        raise ValueError("Jev bloqueado: USD .001 es estimación, falta máximo comprobable del proveedor")
    raise ValueError("CLI bloqueada: adaptador sin máximo comprobable ni pausa segura")


def status() -> dict:
    return {"jev": {"enabled": False, "reason": "sin máximo comprobable por petición"},
            "cli": {"enabled": False, "reason": "sin máximo comprobable ni pausa segura"},
            "local": {"enabled": True, "max_service_cost_usd": "0", "scope": "análisis y contratos locales, no agentes"}}
