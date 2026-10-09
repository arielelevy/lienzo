import pytest
import sessions as ses
import state


def rule(rid, source, target):
    return {
        "id": rid,
        "kind": "on_stop",
        "from": source,
        "to": target,
        "enabled": True,
        "fired": 1,
        "max_fires": 3,
        "text": "{respuesta}",
    }


def test_transfer_incoming_outgoing_and_copy_of_copy(monkeypatch):
    monkeypatch.setattr(ses, "_mirror_rules", list)
    state.rules.items[:] = [rule("in", "worker", "old"), rule("out", "old", "boss")]
    state.links.items[:] = [{"id": "history", "from": "worker", "to": "old"}]
    assert ses.transfer_work_rules("old", "copy") == 2
    assert ses.transfer_work_rules("copy", "next") == 2
    assert [(r["from"], r["to"], r["fired"]) for r in state.rules.items] == [("worker", "next", 1), ("next", "boss", 1)]
    assert state.links.items[0]["to"] == "old"
    assert ses.transfer_work_rules("copy", "next") == 0


def test_transfer_rejects_loop_without_changing_rules(monkeypatch):
    monkeypatch.setattr(ses, "_mirror_rules", list)
    before = [rule("in", "worker", "old"), rule("reverse", "copy", "worker")]
    state.rules.items[:] = before
    with pytest.raises(ValueError, match="bucle"):
        ses.transfer_work_rules("old", "copy")
    assert state.rules.items == before


def test_transfer_storage_failure_preserves_original(monkeypatch):
    monkeypatch.setattr(ses, "_mirror_rules", list)
    before = [rule("in", "worker", "old")]
    state.rules.items[:] = before

    def fail(**kwargs):
        raise OSError("disco")

    monkeypatch.setattr(state.rules, "save", fail)
    with pytest.raises(OSError, match="disco"):
        ses.transfer_work_rules("old", "copy")
    assert state.rules.items == before


def test_handover_keeps_coordination_but_duplicate_keeps_original(monkeypatch):
    monkeypatch.setattr(ses, "_mirror_rules", list)
    monkeypatch.setattr(ses, "set_stopped", lambda *args, **kwargs: {"interrupted": False})
    monkeypatch.setattr(ses, "set_coordinator", lambda s, on: s.update(coordinator=on))
    monkeypatch.setattr(ses, "touch", lambda s: None)
    origin = {"session_id": "old", "coordinator": True, "title": ""}
    target = {"session_id": "copy"}
    state.rules.items[:] = [rule("in", "worker", "old")]
    ses.hand_over(target, origin, stop=False)
    assert origin["coordinator"] is True and state.rules.items[0]["to"] == "old"
    ses.hand_over(target, origin)
    assert target["coordinator"] is True and origin["coordinator"] is False
    assert state.rules.items[0]["to"] == "copy"
