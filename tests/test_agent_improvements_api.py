import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import state

from lienzo import server


@pytest.fixture
def http_api(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(server.optimization_scheduler, "INSTANCE", None)
    monkeypatch.setattr(server.optimization_scheduler, "ERROR", None)
    monkeypatch.setattr(server, "sessions", {"local": {"session_id": "local", "agent": "codex"}})
    monkeypatch.setattr(server.mirror.MIRROR, "owner_of", lambda sid: "other-pc" if sid == "remote" else None)
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *a, **k: (503, {"error": "PC dueña desconectada"}))
    listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{listener.server_port}"

    def request(path, method="GET", data=None, csrf=True):
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-Lienzo"] = "1"
        req = urllib.request.Request(
            base + path, method=method, headers=headers, data=json.dumps(data).encode() if data is not None else None
        )
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    yield request
    listener.shutdown()
    listener.server_close()
    thread.join(5)


def test_preferences_api_keeps_csrf_and_rejects_commands(http_api):
    code, status = http_api("/agent-improvements")
    assert code == 200 and status["preferences"] == {"brief": False, "rtk": False}
    code, _ = http_api("/agent-improvements", "PUT", {"brief": True}, csrf=False)
    assert code == 403
    code, _ = http_api("/agent-improvements", "PUT", {"command": "whoami"})
    assert code == 400
    code, result = http_api("/agent-improvements", "PUT", {"brief": True})
    assert code == 200 and result["preferences"]["brief"]
    assert "api_key" not in json.dumps(result)


def test_session_owner_and_paid_request_boundaries(http_api):
    code, result = http_api("/sessions/local/improvements")
    assert code == 200 and result["session_id"] == "local" and result["note"] == "sin transcripcion"
    code, _ = http_api("/sessions/unknown/improvements")
    assert code == 404
    code, result = http_api("/sessions/remote/improvements")
    assert code == 503 and "desconectada" in result["error"]
    code, _ = http_api("/sessions/local/improvements/jev", "POST", {})
    assert code == 400
    code, result = http_api("/sessions/remote/improvements/jev", "POST", {"allow_cost": True, "snapshot": "reviewed"})
    assert code == 503


def test_changed_sample_rejects_before_any_paid_request(http_api, monkeypatch):
    calls = []
    monkeypatch.setattr(server.agent_suggestions.jev, "decide", lambda data: calls.append(data))
    code, result = http_api("/sessions/local/improvements/jev", "POST", {"allow_cost": True, "snapshot": "old"})
    assert code == 409 and "muestra cambio" in result["error"] and not calls


def test_scheduler_api_limits_commands_and_keeps_csrf(http_api):
    code, result = http_api("/agent-improvements/scheduler")
    assert code == 200 and result["paid_enabled"] is False
    assert result["new_agents_enabled"] is False
    code, _ = http_api("/agent-improvements/scheduler", "PUT", {"action": "activity"}, csrf=False)
    assert code == 403
    code, _ = http_api("/agent-improvements/scheduler", "PUT", {"action": "launch", "command": "whoami"})
    assert code == 400
    code, result = http_api("/agent-improvements/scheduler", "PUT", {"action": "configure", "enabled": False})
    assert code == 200 and result["enabled"] is False
    code, _ = http_api("/agent-improvements/scheduler", "PUT", {"action": "enqueue", "project": "unknown"})
    assert code == 400


def test_scheduler_get_does_not_create_ledger_or_peer(http_api):
    from pathlib import Path

    root = Path(state.LIENZO)
    before = {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    code, _ = http_api("/agent-improvements/scheduler")
    assert code == 200
    after = {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    assert not (root / "optimization-budget.sqlite").exists()
    assert not (root / "peer.json").exists()
    assert after == before
    peer = root / "peer.json"
    peer.write_text("{corrupt", encoding="utf-8")
    stamp = peer.stat().st_mtime_ns
    code, _ = http_api("/agent-improvements/scheduler")
    assert code == 503
    assert peer.read_text(encoding="utf-8") == "{corrupt" and peer.stat().st_mtime_ns == stamp
    assert len(list(root.glob("peer*"))) == 1  # no apartar/reparar identidad desde GET


def test_pilot_activation_keeps_csrf_and_pause_stops_paid_readiness(http_api, monkeypatch):
    calls = []
    monkeypatch.setattr(server.optimization_scheduler.pilot, "activate", lambda: calls.append("activated"))
    code, _ = http_api("/agent-improvements/scheduler", "PUT", {"action": "start_pilot"}, csrf=False)
    assert code == 403 and not calls
    code, _ = http_api("/agent-improvements/scheduler", "PUT", {"action": "start_pilot"})
    assert code == 200 and calls == ["activated"]
    code, result = http_api("/agent-improvements/scheduler", "PUT", {"action": "configure", "enabled": False})
    assert code == 200 and result["enabled"] is False and result["paid_enabled"] is False
