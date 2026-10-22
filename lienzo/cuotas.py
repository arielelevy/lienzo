"""Cuotas de Claude, Codex y Kiro y sugerencia de lanzamiento entre las ventanas semanales comparables.

Claude: GET https://api.anthropic.com/api/oauth/usage con el token OAuth de `<CLAUDE_CONFIG_DIR o ~/.claude>/
.credentials.json`. El token va sólo a ese host, sin redirecciones; nunca se loguea, se guarda ni aparece en
una respuesta o un error (los errores se arman con textos fijos, códigos HTTP y nombres de excepción).
Codex: `optimization_research_quota.read_codex` (codex app-server, sin inferencia), con cada ventana mapeada
por su duración. Una lectura fallida es `ok: false` con el motivo y ventanas `null`: nunca se inventan números.
Kiro: ACP `_kiro/account/getUsage` (el /usage de la TUI), sin sesión ni inferencia. Créditos y mensajes
mensuales separados; un recurso ausente queda null. No participa del balance semanal Claude/Codex.

Caché por agente (5 min; un fallo, 30 s). Cada agente se lee en su hilo: uno lento o caído no frena al otro.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import kiro_quota
import optimization_research_quota as codex_quota

AGENTS = ("claude", "codex")
NAMES = {"claude": "Claude", "codex": "Codex", "kiro": "Kiro"}
CLAUDE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_S, FAIL_CACHE_S = 300, 30
READ_TIMEOUT = 10  # cada lector corta solo antes de esto
LAUNCH_WAIT_S = 5  # lo que un lanzamiento espera una lectura sin caché; después lanza y avisa
FIVE_HOURS_MAX = 90  # con 5 h en este porcentaje o más, el agente no es elegible
MAX_BODY = 65536


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # el token no sigue a otro host


_OPENER = urllib.request.build_opener(_NoRedirect)


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _failure(error: str) -> dict:
    return {"ok": False, "plan": None, "five_hour": None, "weekly": None, "read_at": _now(), "error": error}


def _pct(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("porcentaje inválido")
    return float(value)


def _iso_epoch(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return dt.datetime.fromtimestamp(value, dt.UTC).isoformat(timespec="seconds")


def credentials_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / ".credentials.json"


def _claude_window(body: dict, name: str) -> dict | None:
    window = body.get(name)
    if window is None:
        return None
    if not isinstance(window, dict):
        raise ValueError(f"ventana {name} inválida")  # noqa: TRY004 - contrato uniforme de lectura
    resets = window.get("resets_at")
    return {"used_pct": _pct(window.get("utilization")), "resets_at": resets if isinstance(resets, str) else None}


def read_claude(timeout: float = READ_TIMEOUT) -> dict:
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _failure("sin credenciales de Claude en esta PC (.credentials.json)")
    except (OSError, ValueError) as error:
        return _failure(f"credenciales de Claude ilegibles: {type(error).__name__}")
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if not isinstance(token, str) or not token.strip():
        return _failure("credenciales de Claude sin token OAuth")
    request = urllib.request.Request(
        CLAUDE_URL,
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": "lienzo-cuotas",
        },
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        return _failure(f"Anthropic respondió {error.code} a la lectura de uso")
    except (urllib.error.URLError, OSError) as error:
        return _failure(f"sin respuesta de Anthropic: {type(error).__name__}")
    if len(raw) > MAX_BODY:
        return _failure("respuesta de uso demasiado grande")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("no es objeto")  # noqa: TRY004 - se convierte en fallo legible abajo
        weekly, five = _claude_window(body, "seven_day"), _claude_window(body, "five_hour")
    except ValueError:
        return _failure("respuesta de uso de Claude ilegible")
    if weekly is None:
        return _failure("Claude no informó el uso semanal")
    plan = oauth.get("subscriptionType")
    return {
        "ok": True,
        "plan": plan if isinstance(plan, str) else None,
        "five_hour": five,
        "weekly": weekly,
        "read_at": _now(),
        "error": None,
    }


def read_codex(timeout: float = READ_TIMEOUT) -> dict:
    reading = codex_quota.read_codex(timeout=timeout)
    if not reading.get("ok"):
        return _failure(f"cuota de Codex: {reading.get('error')}")
    five = None
    if reading.get("five_hour_used_pct") is not None:
        five = {"used_pct": reading["five_hour_used_pct"], "resets_at": _iso_epoch(reading.get("five_hour_resets_at"))}
    return {
        "ok": True,
        "plan": reading.get("plan_type"),
        "five_hour": five,
        "weekly": {"used_pct": reading["used_pct"], "resets_at": _iso_epoch(reading.get("resets_at"))},
        "read_at": _now(),
        "error": None,
    }


def read_kiro(timeout: float = READ_TIMEOUT) -> dict:
    try:
        usage = kiro_quota.read_usage(timeout)
    except (OSError, ValueError, KeyError, TypeError, queue.Empty) as error:
        return {
            **_failure(f"uso de Kiro no disponible: {type(error).__name__}"),
            "credits": None,
            "messages": None,
            "resets_at": None,
        }
    return {**_failure(""), **usage, "ok": True, "error": None}


READERS = {"claude": read_claude, "codex": read_codex, "kiro": read_kiro}  # las pruebas los reemplazan
_cache: dict[str, tuple[float, dict]] = {}
_inflight: dict[str, threading.Event] = {}
_lock = threading.Lock()
_generation = 0  # olvidar() la sube: una lectura de antes no escribe en la caché nueva


def _run(agent: str, done: threading.Event, generation: int) -> None:
    try:
        value = READERS[agent]()
    except Exception as error:  # un lector roto queda como fallo legible, no tira el hilo en silencio
        value = _failure(f"lectura de {NAMES[agent]} fallida: {type(error).__name__}")
    with _lock:
        if generation == _generation:
            _cache[agent] = (time.monotonic(), value)
            if _inflight.get(agent) is done:
                del _inflight[agent]
    done.set()


def _start(agent: str, refresh: bool) -> dict | threading.Event:
    """Lo cacheado si sigue vigente; si no, el evento de una lectura en curso (nueva o ya lanzada)."""
    with _lock:
        hit = _cache.get(agent)
        if hit and not refresh:
            ttl = CACHE_S if hit[1]["ok"] else FAIL_CACHE_S
            if time.monotonic() - hit[0] < ttl:
                return hit[1]
        done = _inflight.get(agent)
        if done is None:
            done = _inflight[agent] = threading.Event()
            threading.Thread(target=_run, args=(agent, done, _generation), name=f"cuota-{agent}", daemon=True).start()
        return done


def iniciar() -> None:
    """Arranca las lecturas vencidas sin esperarlas (un lanzamiento las pide antes de lanzar)."""
    for agent in AGENTS:
        _start(agent, False)


def leer_todas(refrescar: bool = False, espera: float = READ_TIMEOUT + 5, *, agents: tuple | None = None) -> dict:
    """Las lecturas en paralelo, esperando a lo sumo `espera` segundos en total. Una que no volvió a
    tiempo queda como fallo («no volvió en N s») y sigue en curso: llena la caché para la próxima."""
    started = {agent: _start(agent, refrescar) for agent in (READERS if agents is None else agents)}
    deadline = time.monotonic() + espera
    result = {}
    for agent, value in started.items():
        if isinstance(value, dict):
            result[agent] = value
        else:
            value.wait(max(0.0, deadline - time.monotonic()))
            with _lock:
                hit = _cache.get(agent) if value.is_set() else None
            result[agent] = hit[1] if hit else _failure(f"la lectura de {NAMES[agent]} no volvió en {espera:g} s")
    return result


def _free(reading: dict) -> float:
    return 100 - reading["weekly"]["used_pct"]


def _not_eligible(reading: dict) -> str | None:
    if not reading["ok"]:
        return reading["error"]
    five = reading["five_hour"]
    if five is not None and five["used_pct"] >= FIVE_HOURS_MAX:
        return f"{five['used_pct']:g} % usado en 5 h"
    return None


def sugerir(readings: dict) -> tuple[str | None, str]:
    """El agente elegible con menor uso semanal; empate, menor uso de 5 h (sin ventana de 5 h cuenta 0)."""
    eligible = [a for a in AGENTS if _not_eligible(readings[a]) is None]
    reasons = {a: _not_eligible(readings[a]) for a in AGENTS if a not in eligible}
    if not eligible:
        return None, "ninguno elegible: " + "; ".join(f"{NAMES[a]}: {why}" for a, why in reasons.items())

    def key(agent):
        five = readings[agent]["five_hour"]
        return (readings[agent]["weekly"]["used_pct"], five["used_pct"] if five else 0.0)

    best = min(eligible, key=key)
    others = [a for a in eligible if a != best]
    reason = f"{NAMES[best]} {_free(readings[best]):g} % libre en la semana"
    if others:
        reason += f" contra {_free(readings[others[0]]):g} % de {NAMES[others[0]]}"
    reason += "".join(f"; {NAMES[a]} no elegible: {why}" for a, why in reasons.items())
    return best, reason


def estado(refrescar: bool = False, espera: float = READ_TIMEOUT + 5, *, agents: tuple | None = None) -> dict:
    readings = leer_todas(refrescar, espera, agents=agents)
    suggested, reason = sugerir(readings)
    return {**readings, "sugerido": suggested, "motivo": reason}


def aviso(agent: str, status: dict) -> str | None:
    """Aviso legible para un lanzamiento manual; nunca lo bloquea."""
    if agent not in AGENTS:
        return None
    reading = status[agent]
    if not reading["ok"]:
        return f"No se pudo medir la cuota de {NAMES[agent]}: {reading['error']}. Se lanzó igual."
    parts = []
    five = reading["five_hour"]
    if five is not None and five["used_pct"] >= FIVE_HOURS_MAX:
        parts.append(f"{NAMES[agent]} {five['used_pct']:g} % en 5 h")
    other = next(a for a in AGENTS if a != agent)
    if status["sugerido"] == other and status[other]["weekly"]["used_pct"] < reading["weekly"]["used_pct"]:
        parts.append(f"{NAMES[agent]} {reading['weekly']['used_pct']:g} % semanal; {NAMES[other]} tiene más margen")
    return "; ".join(parts) or None


def para_lanzar(agent: str) -> dict:
    """Lo que acompaña a un lanzamiento: la cuota del agente lanzado, la sugerencia y un aviso opcional."""
    status = estado(espera=LAUNCH_WAIT_S, agents=AGENTS)
    cuotas = {"sugerido": status["sugerido"], "motivo": status["motivo"]}
    if agent in AGENTS:
        cuotas[agent] = status[agent]
    return {"cuotas": cuotas, "aviso": aviso(agent, status)}


def resolver_auto() -> tuple[str | None, dict]:
    """`agent: "auto"`: el sugerido con las lecturas de este momento (caché ≤ 5 min)."""
    status = estado(espera=LAUNCH_WAIT_S, agents=AGENTS)
    return status["sugerido"], status


def olvidar() -> None:
    global _generation
    with _lock:
        _generation += 1
        _cache.clear()
        _inflight.clear()
