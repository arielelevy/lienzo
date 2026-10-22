"""Lectura de /usage mediante ACP, sin sesión, prompt ni herramientas del modelo."""

import json
import math
import queue
import shutil
import subprocess
import threading
import time

import subproc


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("uso de Kiro inválido")
    return value


def _resource(item: dict) -> dict:
    used = _number(item.get("used"))
    limit = _number(item.get("limit")) if item.get("hasLimit") is True else None
    return {"used": used, "limit": limit, "available": None if limit is None else round(max(0, limit - used), 2)}


def parse_usage(data: dict) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("usageBreakdowns"), list):
        raise ValueError("Kiro no informó los recursos mensuales")  # noqa: TRY004 - error uniforme de lectura
    result = {"credits": None, "messages": None, "resets_at": None, "plan": data.get("planName")}
    reset = data.get("billingCycleReset")
    if isinstance(reset, str) and reset != "Unknown":
        result["resets_at"] = reset
    for item in data["usageBreakdowns"]:
        kind = item.get("resourceType", "").upper()
        label = item.get("displayName", "").lower()
        if kind in ("CREDIT", "CREDITS"):
            result["credits"] = _resource(item)
        elif kind in ("CHAT", "MESSAGE", "MESSAGES") or label == "messages":
            result["messages"] = _resource(item)
    if result["credits"] is None and result["messages"] is None:
        raise ValueError("Kiro no informó créditos ni mensajes mensuales")
    return result


def _receive(lines: queue.Queue, request_id: int, deadline: float) -> dict:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Kiro sin respuesta")
        line = lines.get(timeout=remaining)
        if line is None:
            raise ValueError("Kiro cerró ACP sin cuota")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("respuesta ACP inválida")  # noqa: TRY004 - contrato uniforme de lectura
        if message.get("id") == request_id:
            if "error" in message:
                raise ValueError("Kiro rechazó la lectura ACP")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError("respuesta ACP sin resultado")
            return result
        if "id" in message and "method" in message:
            # Sólo lectura de cuenta: nunca aprobamos un pedido inverso del agente.
            raise ValueError("Kiro pidió una acción del cliente durante la lectura")


def read_usage(timeout: float = 10, exe: str | None = None) -> dict:
    exe = exe or shutil.which("kiro-cli")
    if not exe:
        raise FileNotFoundError("kiro-cli no encontrado")
    extra = {"creationflags": subproc.CREATE_NO_WINDOW} if subproc.WINDOWS else {"start_new_session": True}
    process = subprocess.Popen(
        [exe, "acp", "--agent-engine", "v3"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        **extra,
    )
    lines = queue.Queue()

    def read_lines():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_lines, daemon=True, name="kiro-usage-acp").start()
    deadline = time.monotonic() + timeout
    try:
        for request_id, method, params in (
            (
                1,
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "lienzo-usage", "version": "1"},
                },
            ),
            (2, "_kiro/account/getUsage", {}),
        ):
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"
            )
            process.stdin.flush()
            result = _receive(lines, request_id, deadline)
        if result.get("success") is not True:
            raise ValueError("Kiro no pudo leer el uso de la cuenta")
        return parse_usage(result.get("data"))
    finally:
        subproc._matar_arbol(process)
