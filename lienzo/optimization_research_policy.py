"""Política del investigador CLI: sólo lectura, autorización explícita y consumo acotado comprobable.

Implementar el investigador no concede presupuesto. Sin autorización vigente de una persona, o con un
adaptador cuyo consumo no tiene un máximo acreditado antes de enviar, el estado es `blocked` con sus
motivos. Los experimentos aislados y la aplicación de cambios no se habilitan desde acá.

Codex usa la suscripción: Ariel lo autorizó el 2026-10-16 a correr mientras quede >= 20 % del semanal
(`uso_semanal_max_pct` 80; un archivo de autorización para codex puede restringirlo). La cuota se lee en vivo antes de cada inicio y durante la
ejecución; sin créditos cobrables el costo en dólares es 0 comprobable.

Adaptadores: `codex` (por defecto) y `coda-dgx`. Qué proyectos admiten `coda-dgx` es una regla privada
que vive fuera de Git, en `lienzo/extensiones/investigador-reglas.json` (junto a los plugins locales).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import optimization_cost
import state

MODES = ("read_only", "isolated_experiment", "apply")
# Techos del código: una autorización puede bajarlos, nunca subirlos.
CEILINGS = {"max_seconds": 900, "max_runs_per_day": 6, "max_output_bytes": 20_000_000, "max_starts_per_case": 2}
ADAPTERS = ("codex", "coda-dgx")
FIELDS = {
    "version",
    "autorizado_por",
    "fecha",
    "vence",
    "adaptador",
    "modo",
    "max_ejecuciones_dia",
    "max_segundos",
    "envia_a_servicio_externo",
    "presupuesto_usd",
    "costo_por_uso_usd",
    "uso_semanal_max_pct",
    "modelo",
}
# Autorización de Ariel en la conversación del 2026-10-16 (frente A); no es un presupuesto en dólares.
# Rige para codex cuando no hay archivo para codex; un archivo válido la reemplaza, uno inválido bloquea.
CODEX_AUTHORIZATION = {
    "autorizado_por": "persona:Ariel",
    "fecha": "2026-10-16",
    "vence": None,
    "adaptador": "codex",
    "modo": "read_only",
    "envia_a_servicio_externo": True,
    "uso_semanal_max_pct": 80,
    "fuente": "conversación 2026-10-16: usar la suscripción mientras quede >= 20 % del semanal",
}
RULE_FIELDS = {"version", "coda_dgx"}
CODA_FIELDS = {"proyectos", "perfil", "modelo", "herramientas", "motivo"}
ENABLE_PATH = [
    (
        "codex: autorizado por Ariel el 2026-10-16 a usar la suscripción mientras quede >= 20 % del semanal "
        "(uso <= 80 %). Antes de cada inicio y cada minuto se lee la cuota en vivo (codex app-server, "
        "account/rateLimits/read): uso semanal <= tope, sin créditos cobrables ni control de gasto alcanzado. "
        "Un archivo de autorización para codex puede restringirlo."
    ),
    (
        "coda-dgx: sólo para proyectos listados en la regla local lienzo/extensiones/investigador-reglas.json "
        "(fuera de Git) y con autorización firmada adaptador 'coda-dgx' y costo_por_uso_usd '0'."
    ),
    (
        "La autorización va en ~/.lienzo/research-authorization.json: version 1, autorizado_por "
        "'persona:<nombre>', fecha y vence con zona horaria, modo 'read_only', max_ejecuciones_dia, "
        "max_segundos, envia_a_servicio_externo, presupuesto_usd '0'). Obligatorio para coda-dgx; "
        "un archivo inválido bloquea a los dos adaptadores."
    ),
    (
        "No se cambia el límite de una clave compartida para simular un presupuesto propio. Experimentos "
        "aislados y aplicación de cambios requieren otra política."
    ),
]


def authorization_path() -> Path:
    return Path(state.LIENZO) / "research-authorization.json"


def rules_path() -> Path:
    return Path(__file__).resolve().parent / "extensiones" / "investigador-reglas.json"


def load_rules() -> tuple[dict, str | None]:
    """Regla local de adaptadores por proyecto. Ausente = ningún proyecto admite coda-dgx."""
    path = rules_path()
    if not path.exists():
        return {"coda_dgx": None}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"coda_dgx": None}, f"regla local ilegible: {type(error).__name__}"
    coda = data.get("coda_dgx") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or set(data) - RULE_FIELDS
        or data.get("version") != 1
        or not isinstance(coda, dict)
        or set(coda) - CODA_FIELDS
        or not isinstance(coda.get("proyectos"), list)
        or not all(isinstance(p, str) and p for p in coda["proyectos"])
        or not all(isinstance(coda.get(k), str) and coda[k] for k in ("perfil", "modelo"))
        or not isinstance(coda.get("herramientas"), list)
        or not coda["herramientas"]
        or not all(isinstance(t, str) and t.isidentifier() for t in coda["herramientas"])
    ):
        return {"coda_dgx": None}, "regla local inválida; coda-dgx no se habilita"
    return {"coda_dgx": coda}, None


def adapter_for(project: str) -> str:
    rules, _ = load_rules()
    coda = rules["coda_dgx"]
    return "coda-dgx" if coda and project in coda["proyectos"] else "codex"


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def load_authorization(now: dt.datetime | None = None) -> tuple[dict | None, str | None]:
    """(autorización validada, motivo de rechazo). Ausente o inválida nunca habilita."""
    path = authorization_path()
    if not path.exists():
        return None, "falta autorización explícita de una persona (research-authorization.json ausente)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"autorización ilegible: {type(error).__name__}"
    if not isinstance(data, dict) or set(data) - FIELDS:
        return None, "autorización con campos desconocidos o formato inválido"
    moment = now or dt.datetime.now(dt.UTC)
    signer = data.get("autorizado_por")
    if data.get("version") != 1 or not isinstance(signer, str) or not signer.startswith("persona:") or len(signer) < 10:
        return None, "autorización sin versión 1 o sin firma 'persona:<nombre>'"
    signed, expires = _parse_time(data.get("fecha")), _parse_time(data.get("vence"))
    if signed is None or expires is None or signed > moment:
        return None, "autorización sin fecha/vencimiento con zona horaria válidos"
    if expires <= moment:
        return None, "autorización vencida"
    if data.get("adaptador") not in ADAPTERS:
        return None, "adaptador no autorizable"
    if data.get("modo") != "read_only":
        return None, "sólo se autoriza investigación de sólo lectura"
    runs, seconds = data.get("max_ejecuciones_dia"), data.get("max_segundos")
    if type(runs) is not int or runs < 1 or type(seconds) is not int or seconds < 60:
        return None, "topes de ejecuciones o segundos inválidos"
    if type(data.get("envia_a_servicio_externo")) is not bool:
        return None, "debe declarar si envía el caso a un servicio externo"
    if data.get("presupuesto_usd") != "0":
        return None, "presupuesto monetario no admitido: sin ledger propio del investigador; usar '0'"
    weekly = data.get("uso_semanal_max_pct")
    if data["adaptador"] == "codex" and (type(weekly) is not int or not 1 <= weekly <= 95):
        return None, "codex requiere uso_semanal_max_pct entero entre 1 y 95"
    if data["adaptador"] != "codex" and weekly is not None:
        return None, "uso_semanal_max_pct sólo aplica a codex"
    if "costo_por_uso_usd" in data and (data["adaptador"] != "coda-dgx" or data["costo_por_uso_usd"] != "0"):
        return None, "costo_por_uso_usd sólo se declara '0' para coda-dgx"
    if "modelo" in data and (not isinstance(data["modelo"], str) or not data["modelo"]):
        return None, "modelo inválido"
    return data, None


def effective_authorization(adapter: str, now=None) -> tuple[dict | None, str | None]:
    """La autorización que rige para `adapter`: el archivo si es suyo y válido; para codex, sin archivo
    propio, la del 2026-10-16. Un archivo presente e inválido bloquea siempre."""
    auth, reason = load_authorization(now)
    if auth is not None and auth["adaptador"] == adapter:
        return auth, None
    if reason and authorization_path().exists():
        return None, reason
    if adapter == "codex":
        return CODEX_AUTHORIZATION, None
    return None, reason or "falta autorización para este adaptador"


def evaluate(adapter_limits: dict, *, mode: str = "read_only", runs_today: int = 0, now=None) -> dict:
    """Decide si el investigador puede lanzar UNA ejecución ahora. Re-evaluar antes de cada inicio.

    `adapter_limits` sale de `adapter.limits(auth, project)`: el adaptador sólo acredita un máximo
    cuando la autorización vigente y la regla local lo permiten para ese proyecto."""
    reasons = []
    if mode not in MODES:
        reasons.append("modo desconocido")
    elif mode == "isolated_experiment":
        reasons.append("experimentos aislados sin política ni autorización: bloqueados")
    elif mode == "apply":
        reasons.append("aplicar cambios nunca es automático: requiere decisión de Ariel fuera del investigador")
    auth, auth_reason = effective_authorization(adapter_limits.get("name"), now)
    if auth_reason:
        reasons.append(auth_reason)
    reasons += list(adapter_limits.get("blocked_by") or [])
    if not adapter_limits.get("available"):
        reasons.append(adapter_limits.get("available_reason") or "adaptador no disponible")
    try:
        maximum = optimization_cost.cli_maximum(adapter_limits)
    except ValueError as error:
        maximum = None
        reasons.append(str(error))
    if adapter_limits.get("sandbox") not in ("read-only", "read-only-tools"):
        reasons.append("adaptador sin modo de sólo lectura")
    limits = dict(CEILINGS)
    if auth:
        if adapter_limits.get("sends_to_external_service") and not auth["envia_a_servicio_externo"]:
            reasons.append("el adaptador envía el caso a un servicio externo y la autorización no lo permite")
        limits["max_seconds"] = min(limits["max_seconds"], auth.get("max_segundos", limits["max_seconds"]))
        limits["max_runs_per_day"] = min(
            limits["max_runs_per_day"], auth.get("max_ejecuciones_dia", limits["max_runs_per_day"])
        )
        if "uso_semanal_max_pct" in auth:
            limits["max_weekly_used_pct"] = auth["uso_semanal_max_pct"]
    if type(runs_today) is not int or runs_today < 0:
        reasons.append("conteo de ejecuciones del día desconocido")
    elif runs_today >= limits["max_runs_per_day"]:
        reasons.append(f"tope diario alcanzado ({runs_today} de {limits['max_runs_per_day']})")
    reasons = list(dict.fromkeys(reasons))
    return {
        "enabled": not reasons,
        "state": "enabled" if not reasons else "blocked",
        "mode": mode,
        "reasons": reasons,
        "limits": limits,
        "runs_today": runs_today,
        "service_max_usd": maximum,
        "adapter": {
            k: adapter_limits.get(k)
            for k in ("name", "available", "sends_to_external_service", "sandbox", "consumption_bound")
        },
        "authorization": None
        if auth is None
        else {
            k: auth.get(k)
            for k in ("autorizado_por", "fecha", "vence", "adaptador", "modo", "envia_a_servicio_externo", "fuente")
        },
        "authorization_path": str(authorization_path()),
        "budget_granted_usd": "0",
        "promotion": "nunca automática: propuestas en estado propuesta con veredicto humano",
        "enable_path": ENABLE_PATH,
    }
