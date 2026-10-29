"""Cuotas de la cuenta (Claude y Codex), sugerencia y lanzamiento balanceado. Sin red ni app-server: los
lectores y el transporte se reemplazan. El token de Claude no puede aparecer en ninguna salida."""

import io
import json
import os
import sys
import threading
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import cuotas
import optimization_research_quota as codex_quota
import pytest

TOKEN = "sk-ant-oat01-SECRETO-DE-PRUEBA-0123456789abcdef"


def reading(weekly, five=None, plan="team"):
    return {
        "ok": True,
        "plan": plan,
        "five_hour": None if five is None else {"used_pct": float(five), "resets_at": "2026-10-17T15:00:00+00:00"},
        "weekly": {"used_pct": float(weekly), "resets_at": "2026-10-20T10:00:00+00:00"},
        "read_at": "2026-10-17T11:00:00+00:00",
        "error": None,
    }


def failed(error="sin respuesta"):
    return cuotas._failure(error)


@pytest.fixture(autouse=True)
def readers(monkeypatch):
    calls = {"claude": 0, "codex": 0}
    values = {"claude": reading(82, 11), "codex": reading(51, plan="prolite")}

    def make(agent):
        def read():
            calls[agent] += 1
            value = values[agent]
            return value() if callable(value) else value

        return read

    cuotas.olvidar()
    monkeypatch.setattr(cuotas, "READERS", {a: make(a) for a in cuotas.AGENTS})
    yield {"calls": calls, "values": values}
    cuotas.olvidar()


# ------------------------------------------------------------------ Codex: ventanas por duración


def window(minutes, used):
    return {"usedPercent": used, "windowDurationMins": minutes, "resetsAt": 1792672991}


def rate(primary, secondary):
    return {
        "ordinaryUsageAllowed": True,
        "rateLimits": {
            "primary": primary,
            "secondary": secondary,
            "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            "spendControlReached": False,
            "planType": "prolite",
            "rateLimitReachedType": None,
        },
    }


def test_codex_maps_windows_by_duration_not_position():
    prolite = codex_quota._parse(rate(window(10080, 51), None))  # medido el 2026-10-17
    assert prolite["used_pct"] == 51 and prolite["five_hour_used_pct"] is None
    swapped = codex_quota._parse(rate(window(300, 12), window(10080, 40)))
    assert swapped["used_pct"] == 40 and swapped["five_hour_used_pct"] == 12


def test_codex_reading_shape(monkeypatch):
    monkeypatch.setattr(
        cuotas.codex_quota,
        "read_codex",
        lambda timeout, exe=None: {"ok": True, **codex_quota._parse(rate(window(10080, 51), None))},
    )
    value = cuotas.read_codex()
    assert value["ok"] and value["five_hour"] is None and value["weekly"]["used_pct"] == 51
    assert value["weekly"]["resets_at"].startswith("2026-") and value["plan"] == "prolite"
    monkeypatch.setattr(cuotas.codex_quota, "read_codex", lambda timeout, exe=None: {"ok": False, "error": "codex no encontrado"})
    assert cuotas.read_codex() == {**cuotas.read_codex(), "ok": False, "five_hour": None, "weekly": None}


# ------------------------------------------------------------------ Claude: lectura y token


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    home = tmp_path / "claude-cred"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    payload = {"claudeAiOauth": {"accessToken": TOKEN, "refreshToken": "r", "subscriptionType": "team"}}
    (home / ".credentials.json").write_text(json.dumps(payload), encoding="utf-8")
    return home


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_claude_reading_sends_token_only_to_anthropic_and_parses(credentials, monkeypatch):
    seen = {}

    def open_(request, timeout):
        seen.update(
            url=request.full_url, auth=request.get_header("Authorization"), beta=request.get_header("Anthropic-beta")
        )
        body = {
            "five_hour": {"utilization": 11, "resets_at": "2026-10-17T15:00:00Z"},
            "seven_day": {"utilization": 82, "resets_at": "2026-10-20T10:00:00Z"},
        }
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(cuotas._OPENER, "open", open_)
    value = cuotas.read_claude()
    assert seen == {
        "url": "https://api.anthropic.com/api/oauth/usage",
        "auth": "Bearer " + TOKEN,
        "beta": "oauth-2025-04-20",
    }
    assert (
        value["ok"]
        and value["plan"] == "team"
        and value["weekly"]["used_pct"] == 82
        and value["five_hour"]["used_pct"] == 11
    )
    assert TOKEN not in json.dumps(value)


def test_claude_enterprise_spend_without_weekly_is_visible_but_not_comparable(credentials, monkeypatch):
    def money(amount):
        return {"amount_minor": amount, "currency": "USD", "exponent": 2}

    body = {"five_hour": None, "seven_day": None, "spend": {"enabled": True, "used": money(119), "limit": money(20000)}}
    monkeypatch.setattr(cuotas._OPENER, "open", lambda request, timeout: FakeResponse(json.dumps(body).encode()))
    claude = cuotas.read_claude()
    assert claude["ok"] and claude["weekly"] is None
    assert claude["spend"] == {"used": 1.19, "limit": 200, "currency": "USD"}
    status = {"claude": claude, "codex": reading(51), "sugerido": "codex"}
    assert cuotas.sugerir(status)[0] == "codex"
    assert cuotas.aviso("claude", status) is None
    body["spend"]["used"]["currency"] = "EUR"
    assert not cuotas.read_claude()["ok"]


def test_dos_cuentas_claude_usan_credenciales_separadas(credentials, tmp_path, monkeypatch):
    second = tmp_path / "smartbi"
    monkeypatch.setenv("LIENZO_CLAUDE_SMARTBI_DIR", str(second))
    assert "sin iniciar sesión" in cuotas.read_claude_smartbi()["error"]
    second.mkdir()
    (second / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "otro-token", "subscriptionType": "pro"}}), encoding="utf-8")
    tokens = []
    def open_(request, timeout):
        tokens.append(request.get_header("Authorization"))
        return FakeResponse(json.dumps({"seven_day": {"utilization": len(tokens), "resets_at": None}}).encode())
    monkeypatch.setattr(cuotas._OPENER, "open", open_)
    assert cuotas.read_claude()["weekly"]["used_pct"] == 1
    assert cuotas.read_claude_smartbi()["weekly"]["used_pct"] == 2
    assert tokens == ["Bearer " + TOKEN, "Bearer otro-token"]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(cuotas.CLAUDE_URL, 401, "Unauthorized " + TOKEN, {}, None),
        urllib.error.URLError("fallo con " + TOKEN),
        TimeoutError("timeout " + TOKEN),
    ],
)
def test_claude_errors_never_carry_the_token(credentials, monkeypatch, error):
    def open_(request, timeout):
        raise error

    monkeypatch.setattr(cuotas._OPENER, "open", open_)
    value = cuotas.read_claude()
    assert not value["ok"] and value["weekly"] is None and TOKEN not in json.dumps(value)


@pytest.mark.parametrize(
    "body,message",
    [(b"no es json", "ilegible"), (json.dumps({"five_hour": None}).encode(), "semanal"), (b"[]", "ilegible")],
)
def test_claude_bad_bodies_are_failures_not_numbers(credentials, monkeypatch, body, message):
    monkeypatch.setattr(cuotas._OPENER, "open", lambda request, timeout: FakeResponse(body))
    value = cuotas.read_claude()
    assert not value["ok"] and message in value["error"] and value["five_hour"] is None


def test_claude_without_credentials_and_redirects_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "vacio"))
    assert "sin credenciales" in cuotas.read_claude()["error"]
    handler = cuotas._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://otro.example/") is None


# ------------------------------------------------------------------ caché y paralelismo


def test_cache_per_agent_and_refresh(readers):
    first = cuotas.estado()
    assert first["sugerido"] == "codex" and readers["calls"] == {"claude": 1, "codex": 1}
    cuotas.estado()
    assert readers["calls"] == {"claude": 1, "codex": 1}
    cuotas.estado(refrescar=True)
    assert readers["calls"] == {"claude": 2, "codex": 2}


def test_failures_are_cached_briefly(readers, monkeypatch):
    readers["values"]["claude"] = failed()
    cuotas.estado()
    clock = time.monotonic() + cuotas.FAIL_CACHE_S + 1
    monkeypatch.setattr(cuotas.time, "monotonic", lambda: clock)
    cuotas.estado()
    assert readers["calls"] == {"claude": 2, "codex": 1}


def test_failure_preserves_last_measurement_without_recommending_it(readers):
    previous = cuotas.estado()["codex"]
    readers["values"]["codex"] = failed("sin respuesta nueva")
    for _ in range(2):
        status = cuotas.estado(refrescar=True)
        assert status["codex"] == {**previous, "ok": False, "error": "sin respuesta nueva"}
        assert status["sugerido"] == "claude"
    readers["values"]["codex"] = reading(23)
    assert cuotas.estado(refrescar=True)["codex"] == reading(23)


def test_timeout_preserves_last_measurement(readers):
    previous = cuotas.estado()["codex"]
    release = threading.Event()
    readers["values"]["codex"] = lambda: (release.wait(5), reading(25))[1]
    try:
        value = cuotas.estado(refrescar=True, espera=0.05)["codex"]
        assert not value["ok"] and "no volvió" in value["error"]
        assert value["weekly"] == previous["weekly"] and value["read_at"] == previous["read_at"]
    finally:
        release.set()


def test_slow_reader_does_not_hold_the_other(readers):
    release = threading.Event()
    readers["values"]["claude"] = lambda: (release.wait(5), reading(70))[1]
    started = time.monotonic()
    status = cuotas.estado(espera=0.3)
    assert time.monotonic() - started < 2
    assert status["codex"]["ok"] and not status["claude"]["ok"] and "no volvió" in status["claude"]["error"]
    assert status["sugerido"] == "codex"
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and cuotas._cache.get("claude") is None:
        time.sleep(0.02)
    assert cuotas.estado()["claude"]["weekly"]["used_pct"] == 70  # la lectura tardía llenó la caché


def test_broken_reader_is_a_legible_failure(readers):
    readers["values"]["codex"] = lambda: 1 / 0
    status = cuotas.estado()
    assert status["codex"]["error"] == "lectura de Codex fallida: ZeroDivisionError" and status["sugerido"] == "claude"


# ------------------------------------------------------------------ regla de balance y avisos


@pytest.mark.parametrize(
    "claude,codex,expected,fragment",
    [
        (reading(82, 11), reading(51), "codex", "Codex 49 % libre en la semana contra 18 % de Claude"),
        (reading(30, 95), reading(60), "codex", "Claude no elegible: 95 % usado en 5 h"),
        (reading(40, 20), reading(40, 10), "codex", "Codex 60 % libre"),
        (reading(40, 0), reading(40), "claude", "Claude 60 % libre"),
        (failed("Anthropic respondió 401 a la lectura de uso"), reading(51), "codex", "Claude no elegible: Anthropic"),
        (reading(10, 90), failed("codex no encontrado"), None, "ninguno elegible"),
    ],
)
def test_balance_rule(claude, codex, expected, fragment):
    chosen, reason = cuotas.sugerir({"claude": claude, "codex": codex})
    assert chosen == expected and fragment in reason


def test_manual_launch_warnings_never_block(readers):
    status = cuotas.estado()
    assert cuotas.aviso("claude", status) == "Claude 82 % semanal; Codex tiene más margen"
    assert cuotas.aviso("codex", status) is None
    assert cuotas.aviso("coda", status) is None
    readers["values"]["codex"] = reading(51, 93)
    status = cuotas.estado(refrescar=True)
    assert cuotas.aviso("codex", status) == "Codex 93 % en 5 h"
    readers["values"]["claude"] = failed("sin credenciales de Claude en esta PC (.credentials.json)")
    status = cuotas.estado(refrescar=True)
    assert cuotas.aviso("claude", status).startswith("No se pudo medir la cuota de Claude")


# ------------------------------------------------------------------ server: GET /cuotas y lanzamiento


def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.launch, "launch", lambda cwd, title, agent, **k: calls.append(agent) or {"ok": True, "agent": agent}
    )
    return calls


def test_auto_launches_the_suggested_agent_and_says_why(monkeypatch):
    calls = launched(monkeypatch)
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "auto", "title": "t"}, desde_tablero=True)
    assert code == 200 and calls == ["codex"] and body["agent"] == "codex"  # nombres que asume la UI
    assert "Codex 49 % libre" in body["motivo"] and body["cuotas"]["codex"]["weekly"]["used_pct"] == 51
    assert "aviso" not in body


def test_auto_without_eligible_agent_is_409_and_launches_nothing(readers, monkeypatch):
    calls = launched(monkeypatch)
    readers["values"]["claude"] = reading(10, 95)
    readers["values"]["codex"] = failed("codex no encontrado")
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "auto"}, desde_tablero=True)
    assert code == 409 and calls == [] and "ninguno elegible" in body["error"] and body["cuotas"]["sugerido"] is None
    assert body["motivo"].startswith("ninguno elegible")


def test_manual_launch_carries_quota_and_warning_but_launches(monkeypatch):
    calls = launched(monkeypatch)
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "claude"}, desde_tablero=True)
    assert code == 200 and calls == ["claude"] and body["aviso"] == "Claude 82 % semanal; Codex tiene más margen"
    assert body["cuotas"]["sugerido"] == "codex" and body["cuotas"]["claude"]["weekly"]["used_pct"] == 82


def test_manual_launch_with_unanswered_quota_still_launches_and_warns(readers, monkeypatch):
    calls = launched(monkeypatch)
    release = threading.Event()
    readers["values"]["claude"] = lambda: (release.wait(10), reading(5))[1]
    monkeypatch.setattr(cuotas, "LAUNCH_WAIT_S", 0.3)
    started = time.monotonic()
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "claude"}, desde_tablero=True)
    release.set()
    assert code == 200 and calls == ["claude"] and time.monotonic() - started < 3
    assert "No se pudo medir la cuota de Claude" in body["aviso"]


def test_rejected_launch_and_vscode_do_not_read_quotas(readers, monkeypatch):
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "claude", "modo": "magia"}, desde_tablero=True)
    assert code == 400 and "cuotas" not in body and readers["calls"] == {"claude": 0, "codex": 0}
    monkeypatch.setattr(server.launch, "launch", lambda *a, **k: {"ok": False, "error": "cwd fuera de launch_roots"})
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "claude"}, desde_tablero=True)
    assert code == 400 and "cuotas" not in body  # la lectura anticipada pudo arrancar; un fallo no la adjunta
    cuotas.olvidar()
    readers["calls"].update(claude=0, codex=0)
    monkeypatch.setattr(server.launch, "open_vscode", lambda cwd: {"ok": True})
    code, body = server.accion_launch({"cwd": "D:/x", "agent": "vscode"}, desde_tablero=True)
    assert code == 200 and "cuotas" not in body and readers["calls"] == {"claude": 0, "codex": 0}


def test_get_cuotas_route_is_wired():
    # Débil a propósito: verifica el cableado de la ruta en el código; la ruta viva se prueba tras reiniciar.
    from pathlib import Path

    source = Path(server.__file__).read_text(encoding="utf-8")
    assert (
        'if parts == ["cuotas"]:' in source
        and 'cuotas.estado(refrescar=self.query.get("refrescar") == ["1"])' in source
    )


def test_contract_shape_of_state():
    status = cuotas.estado()
    assert set(status) == {"claude", "codex", "sugerido", "motivo"}
    for agent in cuotas.AGENTS:
        assert set(status[agent]) == {"ok", "plan", "five_hour", "weekly", "read_at", "error"}
    assert status["codex"]["five_hour"] is None and status["claude"]["five_hour"]["used_pct"] == 11
