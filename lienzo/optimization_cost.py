"""Cotas comprobables; una estimación económica nunca habilita un envío."""

from __future__ import annotations

import json
import time
import urllib.request
from decimal import Decimal

from optimization_budget import money

JEV_MODEL = "typesafe/jev-1.13"
JEV_ENDPOINT = "TypeSafe | typesafe/jev-1.13-20260917"
JEV_METADATA_URL = "https://openrouter.ai/api/v1/models/typesafe/jev-1.13/endpoints"
LAST_QUOTE = None
CLI_BLOCK = "CLI bloqueada: adaptador sin máximo comprobable ni pausa segura"


def jev_quote(metadata: dict) -> dict:
    """Valida una cotización primaria; no habilita gasto ni concilia históricos.

    El caller debe consultar esta fuente inmediatamente antes de reservar y
    enviar las preferencias retornadas. No convertir bytes locales en tokens.
    """
    data = metadata.get("data") if isinstance(metadata, dict) else None
    if not isinstance(data, dict) or data.get("id") != JEV_MODEL:
        raise ValueError("modelo de cotización incompatible")
    endpoints = data.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 1:
        raise ValueError("proveedor único no acreditado")
    endpoint = endpoints[0]
    if not isinstance(endpoint, dict) or any(
        endpoint.get(k) != v
        for k, v in {
            "name": JEV_ENDPOINT,
            "model_id": JEV_MODEL,
            "provider_name": "TypeSafe",
            "tag": "typesafe",
            "status": 0,
        }.items()
    ):
        raise ValueError("endpoint de cotización incompatible")
    for name, ceiling in (("max_prompt_tokens", 32000), ("context_length", 64000)):
        value = endpoint.get(name)
        if type(value) is not int or not 0 < value <= ceiling:
            raise ValueError("contexto de cotización no acreditado")
    if endpoint["context_length"] < endpoint["max_prompt_tokens"]:
        raise ValueError("contexto incompatible con máximo de entrada")
    pricing = endpoint.get("pricing")
    if not isinstance(pricing, dict):
        raise ValueError("precio ausente")  # noqa: TRY004 - contrato uniforme de cotización
    prompt = money(pricing.get("prompt"))
    completion = money(pricing.get("completion"))
    if prompt != Decimal("0.000000042") or completion != 0:
        raise ValueError("precio cambió; requiere revisión")
    # Reservar contexto total, por encima del máximo de entrada publicado.
    maximum = prompt * endpoint["context_length"]
    return {
        "source": JEV_METADATA_URL,
        "model": JEV_MODEL,
        "effective_model": "typesafe/jev-1.13-20260917",
        "maximum_usd": str(maximum),
        "max_prompt_tokens": endpoint["max_prompt_tokens"],
        "context_length": endpoint["context_length"],
        "provider": {
            "only": ["typesafe"],
            "allow_fallbacks": False,
            "zdr": True,
            "data_collection": "deny",
            "max_price": {"prompt": 0.042, "completion": 0, "request": 0, "image": 0},
        },
        "enabled": False,
    }


def fresh_jev_quote() -> dict:
    # GET público, sin Authorization, sin redirecciones ni caché que habilite gasto.
    import jev

    with jev._open(urllib.request.Request(JEV_METADATA_URL), timeout=12) as response:
        raw = response.read(128001)
    if len(raw) > 128000:
        raise ValueError("cotización demasiado grande")
    quote = jev_quote(json.loads(raw))
    global LAST_QUOTE
    LAST_QUOTE = {**quote, "retrieved_at": time.time()}
    return quote


def maximum(adapter: str) -> str:
    if adapter == "local-rtk-contract":
        return "0"
    if adapter == "jev":
        raise ValueError("Jev bloqueado: USD .001 es estimación, falta máximo comprobable del proveedor")
    raise ValueError(CLI_BLOCK)


def cli_maximum(limits: dict) -> str:
    """Máximo de costo de servicio de una ejecución CLI, sólo si el adaptador lo acredita antes de enviar.

    Se acredita USD 0 sólo con fundamento leído antes de enviar (p. ej. suscripción sin créditos
    cobrables, leída en vivo). Tokens o créditos informados después de la ejecución no son un máximo;
    una clave compartida tampoco. Un máximo mayor que cero sólo con el ledger del investigador leído
    antes de enviar (`ledger`), dentro del disponible del mes y del tope por ejecución; la reserva real
    se hace justo antes de lanzar (optimization_research_ledger.reserve)."""
    bound = limits.get("consumption_bound") if isinstance(limits, dict) else None
    if not isinstance(bound, dict) or bound.get("verified") is not True:
        raise ValueError(CLI_BLOCK + ": consumo sin máximo comprobable antes de enviar")
    if bound.get("unit") != "usd" or not isinstance(bound.get("maximum"), str) or not bound.get("basis"):
        raise ValueError(CLI_BLOCK + ": sólo se acredita un máximo en USD con fundamento")
    if not limits.get("cancellable") or not limits.get("timeout"):
        raise ValueError(CLI_BLOCK + ": falta cancelación propia o timeout")
    try:
        amount = Decimal(bound["maximum"])
    except ArithmeticError as error:
        raise ValueError(CLI_BLOCK + ": máximo ilegible") from error
    if amount == 0:
        return "0"
    ledger = bound.get("ledger")
    if amount < 0 or not isinstance(ledger, dict) or ledger.get("read") is not True:
        raise ValueError(CLI_BLOCK + ": un máximo mayor que cero requiere el ledger del investigador leído")
    if amount > Decimal(ledger["available_usd"]) or amount > Decimal(ledger["max_usd_per_run"]):
        raise ValueError(
            f"tope de gasto: máximo USD {amount} supera el disponible del mes USD {ledger['available_usd']} "
            f"o el tope por ejecución USD {ledger['max_usd_per_run']}"
        )
    return str(amount)


def status() -> dict:
    fresh = LAST_QUOTE is not None and 0 <= time.time() - LAST_QUOTE["retrieved_at"] < 60
    return {
        "jev": {
            "enabled": fresh,
            "reason": "cotización reciente; se revalida antes de envío"
            if fresh
            else "cotización pendiente/expirada; requiere preflight",
            "requires_price_preflight": True,
        },
        "cli": {
            "enabled": False,
            "reason": "sin máximo comprobable ni pausa segura; el investigador evalúa su política por ejecución",
            "policy": "optimization_research_policy: sólo lectura, autorización explícita, máximo verificado",
        },
        "local": {"enabled": True, "max_service_cost_usd": "0", "scope": "análisis y contratos locales, no agentes"},
    }
