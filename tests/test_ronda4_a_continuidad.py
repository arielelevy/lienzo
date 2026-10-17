"""Continuidad con rollouts y reservas temporales; nunca lanza Codex ni usa sesiones reales."""

import json

import codex_identity
import codex_queue as cq
import entregas_informes as ledger
import pytest

OLD = "01a14774-aa3f-7062-b3f3-aa996a33ff35"
NEW = "01a14a6b-1acc-7db2-9dbb-b7faf4033e22"


@pytest.fixture
def measured_card(tmp_path, monkeypatch):
    rollout = tmp_path / "rollout-old.jsonl"
    rollout.write_text("", encoding="utf-8")
    monkeypatch.setattr(cq, "codex_exe", lambda: "codex.exe")
    monkeypatch.setattr(cq.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(cq, "store_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **kw: pytest.fail("no debe lanzar cola"))
    return {"agent": "codex", "pid": 4242, "session_id": OLD,
            "transcript_path": str(rollout), "codex_process_start": 123}


@pytest.mark.parametrize("change", ["thread", "process_start"])
def test_send_rechecks_identity_after_successful_capability(measured_card, monkeypatch, change):
    card = measured_card
    proof = {"verified": True, "process_start": 123, "thread": OLD, "path": card["transcript_path"]}
    monkeypatch.setattr(codex_identity, "probe", lambda pid: dict(proof))
    assert cq.puede_enviar(card)["puede"] is True
    proof[change] = NEW if change == "thread" else 124
    result = cq.enviar(card, "ESTADO: entrega", esperar=0)
    assert result["estado"] == "rechazado"
    assert "identidad de hilo CLI sin verificar" in result["motivo"]
    assert not cq.store_path().exists()


def test_two_open_rollouts_reject_without_choosing_newest(measured_card, monkeypatch):
    monkeypatch.setattr(cq.procinfo, "_WIN", True)
    monkeypatch.setattr(cq.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(codex_identity, "_snapshot", lambda pid: (123, {"rollout-old.jsonl", "rollout-new.jsonl"}))
    result = cq.enviar(measured_card, "ESTADO: entrega", esperar=0)
    assert result["estado"] == "rechazado"
    assert "2 rollouts abiertos" in result["motivo"]
    assert not cq.store_path().exists()


@pytest.mark.parametrize("already_received", [False, True])
def test_late_confirmation_uses_original_rollout_after_serialized_restart(
    measured_card, tmp_path, monkeypatch, already_received
):
    message = "ESTADO: evidencia del frente"
    old_path = measured_card["transcript_path"]
    new_path = tmp_path / "rollout-new.jsonl"
    event = json.dumps({"timestamp": cq._iso(101), "type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": message}]}})
    new_path.write_text(event + "\n", encoding="utf-8")
    monkeypatch.setattr(cq.time, "time", lambda: 102)
    cq._save({"q1": {"envio_id": "q1", "thread": OLD, "rollout": old_path,
                    "sha256": cq._sha(message), "desde": cq._iso(100), "at": 100,
                    "estado": "encolado", "transporte": "codex_queue"}})
    rule = {"to": "coordinator"}
    report = ledger.conservar(rule, {"huella": "final", "texto": message}, "t0")
    ledger.resultado(report, 200, {"estado": "encolado", "envio_id": "q1"}, "t1")
    if already_received:
        assert ledger.acusar(rule, "final", "recibido", "coordinator", "t2")[0] == 200
    # Reinicio simulado de estado: sólo se conserva el JSON, sin caché ni proceso real.
    rule = json.loads(json.dumps(rule))
    report = rule["informes"][0]
    measured_card.update(session_id=NEW, transcript_path=str(new_path))
    result = cq.confirmar("q1")
    assert result["estado"] == "encolado"  # El texto en el hilo nuevo no confirma el viejo.
    assert ledger.confirmar_envio(rule, "q1", result, "t3") is True
    assert report["estado"] == ("recibido" if already_received else "pendiente")
    with open(old_path, "w", encoding="utf-8") as stream:
        stream.write(event + "\n")
    result = cq.confirmar("q1")
    assert result["estado"] == "entregado"
    assert ledger.confirmar_envio(rule, "q1", result, "t4") is True
    assert report["estado"] == ("recibido" if already_received else "entregado")
    assert cq._load()["q1"]["thread"] == OLD
    assert cq._load()["q1"]["rollout"] == old_path
    assert list(cq._load()) == ["q1"]
    if not already_received:
        assert ledger.acusar(rule, "final", "integrado", "coordinator", "t5")[0] == 409
        assert ledger.acusar(rule, "final", "recibido", "coordinator", "t5")[0] == 200
    assert ledger.acusar(rule, "final", "integrado", "coordinator", "t6")[0] == 200
    assert report["respuesta"] == message
    assert ledger.pendientes(rule) is False
