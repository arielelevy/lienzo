import json

import agentes
import launch
import pytest
import restore

from lienzo import kiro


def test_catalogue_shared_by_every_provider():
    assert set(agentes.CAPACIDADES) == set(agentes.AGENTES)
    assert {a for a, p in agentes.AGENTES.items() if p.capabilities["screen"]} == {"claude", "codex", "kiro"}
    assert all(p.capabilities["coordinable"] for p in agentes.AGENTES.values())


@pytest.mark.parametrize("sid", ["sess_" + "-" * 36, "sess_" + "a" * 36, "sess_123", "pid-1", "&calc", None])
def test_kiro_rejects_invalid_ids_at_both_entrypoints(sid):
    assert launch._resume_args("kiro", sid) == []
    assert not restore.valid_id("kiro", sid)


def test_kiro_platform_contract(monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", False)
    monkeypatch.setattr(launch.sys, "platform", "linux")
    assert not launch.launch("/tmp", "Kiro", "kiro")["ok"]


def test_bad_metadata_logs_once_and_recovers(tmp_path, caplog):
    path = tmp_path / "session.json"
    path.write_text("[]", encoding="utf-8")
    assert kiro.read_object(path) == {}
    assert kiro.read_object(path) == {}
    assert len(caplog.records) == 1
    path.write_text(json.dumps({"modelId": "auto"}), encoding="utf-8")
    assert kiro.read_metadata(str(tmp_path / "messages.jsonl"))["modelId"] == "auto"
    path.write_text("[]", encoding="utf-8")
    kiro.read_object(path)
    assert len(caplog.records) == 2


def test_missing_metadata_is_transient(tmp_path, caplog):
    assert kiro.read_metadata(str(tmp_path / "messages.jsonl")) == {}
    assert not caplog.records


def test_kiro_dialog_does_not_confirm_replaced_tool():
    p = agentes.perfil("kiro")
    before = {"question": "Allow?", "detail": "read", "kiro_tool_call_id": "one"}
    current = {"question": "Allow?", "detail": "read"}
    assert not p.same_dialog(current, before, lambda: {"turns": [{"kiro_pending": {"toolCallId": "two"}}]})
    assert p.same_dialog(current, before, lambda: {"turns": [{"kiro_pending": {"toolCallId": "one"}}]})
