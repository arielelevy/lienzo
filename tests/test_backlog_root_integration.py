"""Codex CLI usa su consola; las guardas de proceso y los informes siguen vigentes."""

import pytest
import sessions as ses


@pytest.mark.parametrize("used", [False, True])
def test_cli_console_remains_available_after_prior_turns(monkeypatch, used):
    card = {
        "session_id": "pid-4242",
        "pid": 4242,
        "agent": "codex",
        "source": "sweep",
        "last_prompt": "pedido previo" if used else "",
        "transcript_path": None,
    }
    monkeypatch.setattr(ses, "queue_blocked", lambda s: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses.codex_queue, "puede_enviar", lambda s: pytest.fail("CLI no debe consultar queue"))
    plan = ses.puede_enviar(card)
    assert plan == {"puede": True, "motivo": None, "transporte": "tecleo"}


def test_bootstrap_keeps_process_guard(monkeypatch):
    card = {"session_id": "pid-4242", "pid": 4242, "agent": "codex", "source": "sweep"}
    monkeypatch.setattr(ses, "queue_blocked", lambda s: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: (409, {"error": "proceso distinto"}))
    assert ses.puede_enviar(card) == {"puede": False, "motivo": "proceso distinto", "transporte": None}


@pytest.fixture
def report_http(monkeypatch):
    import http.client
    import json
    import threading

    import server
    import state

    state.rules.items.append(
        {
            "id": "r",
            "from": "worker",
            "to": "coordinator",
            "kind": "on_stop",
            "enabled": True,
            "informes": [{"id": "i", "estado": "pendiente", "respuesta": "informe"}],
        }
    )
    monkeypatch.setattr(server.Handler, "_authed", lambda self: True)
    instance = server.QuietServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()

    def request(method, path, data=None, tunnel=False):
        connection = http.client.HTTPConnection("127.0.0.1", instance.server_port, timeout=3)
        headers = {"X-Lienzo": "1", "Content-Type": "application/json"}
        if tunnel:
            headers["CF-Connecting-IP"] = "8.8.8.8"
        connection.request(method, path, json.dumps(data or {}), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    yield request
    instance.shutdown()
    instance.server_close()
    thread.join(2)


def test_report_acknowledgement_order_and_local_user(report_http):
    path = "/rules/r/informes/i/acuse"
    assert report_http("POST", path, {"estado": "integrado"})[0] == 409
    status, received = report_http("POST", path, {"estado": "recibido", "session_id": "inventado"})
    assert status == 200 and received["recibido_por"] == "coordinator"
    status, integrated = report_http("POST", path, {"estado": "integrado"})
    assert status == 200 and integrated["estado"] == "integrado"
    assert report_http("POST", path, {"estado": "recibido"})[1]["estado"] == "integrado"


def test_report_acknowledgement_tunnel_is_rejected(report_http):
    assert report_http("POST", "/rules/r/informes/i/acuse", {"estado": "recibido"}, tunnel=True)[0] == 403


def test_deleting_rule_preserves_unintegrated_report(report_http):
    import state

    status, body = report_http("DELETE", "/rules/r")
    assert status == 409 and body["conservada"] is True
    assert len(state.rules.items) == 1
    assert state.rules.items[0]["enabled"] is False
    assert state.rules.items[0]["informes"][0]["respuesta"] == "informe"


def test_report_retention_survives_capacity_limit():
    import rules
    import state

    protected = {"id": "protected", "informes": [{"estado": "pendiente"}]}
    state.rules.items[:] = [protected, {"id": "old"}, {"id": "newer"}]
    rules.agregar_regla({"id": "new"}, cap=2)
    assert [r["id"] for r in state.rules.items] == ["protected", "new"]


def test_retiring_rule_restores_memory_after_disk_failure(monkeypatch):
    import rules
    import state

    protected = {"id": "protected", "enabled": True, "informes": [{"estado": "pendiente"}]}
    state.rules.items.append(protected)
    monkeypatch.setattr(state.rules, "save", lambda **kw: (_ for _ in ()).throw(OSError("disco")))
    with pytest.raises(OSError, match="disco"):
        rules.retirar_regla("protected")
    assert protected["enabled"] is True
