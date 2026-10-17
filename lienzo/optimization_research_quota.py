"""Cuota de la suscripción Codex, leída en vivo sin inferencia (codex app-server, account/rateLimits/read).

La lectura es de la cuenta, no de esta PC: incluye el uso de las otras PCs y sesiones. Sólo se conserva lo
necesario para decidir (porcentaje semanal, créditos, control de gasto); el id de cuenta se descarta.
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time

import subproc

WEEK_MINUTES = 10080
FIVE_HOURS_MINUTES = 300
READ_TIMEOUT = 20


def _parse(result: dict) -> dict:
    limits = result.get("rateLimits") if isinstance(result, dict) else None
    if not isinstance(limits, dict):
        raise ValueError("respuesta sin rateLimits")  # noqa: TRY004 - contrato uniforme de lectura
    # Cada ventana se reconoce por su duración, no por ser primary o secondary (medido el 2026-10-17: el plan
    # prolite trae la semanal en primary y secondary null, sin ventana de 5 h).
    windows = {}
    for name in ("primary", "secondary"):
        window = limits.get(name)
        if isinstance(window, dict) and window.get("windowDurationMins") in (FIVE_HOURS_MINUTES, WEEK_MINUTES):
            windows[window["windowDurationMins"]] = window
    weekly, five = windows.get(WEEK_MINUTES), windows.get(FIVE_HOURS_MINUTES)
    five_used = five.get("usedPercent") if five else None
    if five is not None and (
        isinstance(five_used, bool) or not isinstance(five_used, (int, float)) or not 0 <= five_used <= 100
    ):
        raise ValueError("porcentaje de 5 h inválido")
    if weekly is None:
        raise ValueError("sin ventana semanal en la cuota")
    used = weekly.get("usedPercent")
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
        raise ValueError("porcentaje semanal inválido")
    credits = limits.get("credits")
    if not isinstance(credits, dict):
        raise ValueError("créditos desconocidos")  # noqa: TRY004 - contrato uniforme de lectura
    return {
        "used_pct": float(used),
        "resets_at": weekly.get("resetsAt"),
        "credits_has": credits.get("hasCredits"),
        "credits_unlimited": credits.get("unlimited"),
        "credits_balance": credits.get("balance"),
        "spend_control_reached": limits.get("spendControlReached"),
        "rate_limit_reached_type": limits.get("rateLimitReachedType"),
        "ordinary_usage_allowed": result.get("ordinaryUsageAllowed"),
        "plan_type": limits.get("planType"),
        "five_hour_used_pct": None if five is None else float(five_used),
        "five_hour_resets_at": None if five is None else five.get("resetsAt"),
    }


def read_codex(timeout: float = READ_TIMEOUT, exe: str | None = None) -> dict:
    """Lee la cuota. Nunca levanta: un fallo devuelve {"ok": False, "error": ...} y bloquea al llamador."""
    exe = exe or shutil.which("codex")
    if not exe:
        return {"ok": False, "error": "codex no encontrado en PATH", "read_at": time.time()}
    extra = {"creationflags": subproc.CREATE_NO_WINDOW} if subproc.WINDOWS else {"start_new_session": True}
    try:
        p = subprocess.Popen(
            [exe, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **extra,
        )
    except OSError as error:
        return {"ok": False, "error": f"no se pudo lanzar codex app-server: {type(error).__name__}"}
    lines: queue.Queue = queue.Queue()

    def reader():
        for line in p.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + timeout
    try:
        for message in (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "lienzo", "version": "1"}},
            },
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"},
        ):
            p.stdin.write(json.dumps(message) + "\n")
        p.stdin.flush()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"ok": False, "error": f"cuota sin respuesta en {timeout:g} s", "read_at": time.time()}
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                return {"ok": False, "error": "codex app-server terminó sin cuota", "read_at": time.time()}
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == 2:
                if "error" in message:
                    return {"ok": False, "error": "codex rechazó la lectura de cuota", "read_at": time.time()}
                return {"ok": True, **_parse(message.get("result")), "read_at": time.time()}
    except (OSError, ValueError) as error:
        return {"ok": False, "error": f"cuota ilegible: {error}", "read_at": time.time()}
    finally:
        subproc._matar_arbol(p)  # el app-server es nuestro; nunca otro proceso


def assess(quota: dict, max_used_pct: int | None) -> tuple[dict | None, list[str]]:
    """(cota en USD acreditada, motivos de bloqueo). Sin tope autorizado o con lectura dudosa, bloquea."""
    reasons = []
    if max_used_pct is None:
        reasons.append("sin uso_semanal_max_pct autorizado para codex")
    if not quota.get("ok"):
        return None, [*reasons, "cuota de Codex desconocida: " + str(quota.get("error"))]
    if quota.get("ordinary_usage_allowed") is not True:
        reasons.append("la cuenta no admite uso ordinario ahora")
    if quota.get("spend_control_reached") is not False:
        reasons.append("control de gasto alcanzado o desconocido")
    if quota.get("rate_limit_reached_type") is not None:
        reasons.append("límite de uso alcanzado")
    if quota.get("five_hour_used_pct") is not None and quota["five_hour_used_pct"] >= 100:
        reasons.append("ventana de 5 h agotada")
    if quota.get("credits_unlimited") is not False or (
        quota.get("credits_has") is not False and quota.get("credits_balance") != "0"
    ):
        reasons.append("hay créditos cobrables o desconocidos: un exceso podría cobrarse")
    if max_used_pct is not None and quota["used_pct"] > max_used_pct:
        reasons.append(f"uso semanal {quota['used_pct']:g} % supera el tope {max_used_pct} %")
    if reasons:
        return None, reasons
    bound = {
        "unit": "usd",
        "maximum": "0",
        "verified": True,
        "basis": "suscripción sin créditos cobrables, leída en vivo antes de enviar",
        "weekly_used_pct": quota["used_pct"],
        "weekly_max_used_pct": max_used_pct,
    }
    return bound, []
