import agent_suggestions as suggestions
import pytest
import state


def sample():
    return {"session_id": "s1", "snapshot": "digest", "evidence": {"tools": [
        {"turn": "t1", "tool_id": "a", "tool": "exec_command", "characters": 3000, "error": False, "result_known": True}]}}


def test_suggestion_cites_tool_and_does_not_claim_savings():
    result = suggestions.suggestions(sample())
    assert result[0]["tool"] == "rtk"
    assert result[0]["evidence"]["turn"] == "t1"
    assert "no demuestra" in result[0]["limit"]
    assert suggestions.suggestions({"evidence": {"tools": []}}) == []


def test_no_paid_request_without_approval_or_matching_snapshot(monkeypatch):
    monkeypatch.setattr(suggestions, "report", lambda s: sample())
    calls = []
    monkeypatch.setattr(suggestions.jev, "decide", lambda data: calls.append(data))
    for data in ({}, {"allow_cost": True, "snapshot": "old"}):
        with pytest.raises(ValueError):
            suggestions.judge({"session_id": "s1"}, data)
    assert not calls


def test_judgment_is_saved_without_using_provider_id_as_path(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(suggestions, "report", lambda s: sample())
    monkeypatch.setattr(suggestions.jev, "decide", lambda data: {"id": "../escape", "choice": "rtk"})
    result = suggestions.judge({"session_id": "s1"}, {"allow_cost": True, "snapshot": "digest"})
    assert result["decision"]["choice"] == "rtk"
    assert len(list((tmp_path / "improvements").glob("*.json"))) == 1
    assert not (tmp_path.parent / "escape").exists()


def test_concurrent_judgment_is_rejected_before_call(monkeypatch):
    suggestions.JUDGE_LOCK.acquire()
    try:
        with pytest.raises(ValueError, match="otra consulta"):
            suggestions.judge({"session_id": "s1"}, {"allow_cost": True, "snapshot": "digest"})
    finally:
        suggestions.JUDGE_LOCK.release()


def test_empty_sample_is_not_sent_to_paid_model(monkeypatch):
    monkeypatch.setattr(suggestions, "report", lambda s: {"snapshot": "empty", "evidence": {"tools": []}})
    with pytest.raises(ValueError, match="no hay herramientas"):
        suggestions.judge({"session_id": "s1"}, {"allow_cost": True, "snapshot": "empty"})


def test_storage_failure_reports_that_provider_charged(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(suggestions, "report", lambda s: sample())
    monkeypatch.setattr(suggestions.jev, "decide", lambda data: {"usage": {"cost": .00001}})
    (tmp_path / "improvements").write_text("not a directory")
    with pytest.raises(ValueError, match="cobro USD"):
        suggestions.judge({"session_id": "s1"}, {"allow_cost": True, "snapshot": "digest"})
