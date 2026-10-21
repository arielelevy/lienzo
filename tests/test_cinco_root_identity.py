"""La incertidumbre retira la prueba antigua sin mover identidad ni referencias."""

import pytest
import sessions as ses


@pytest.mark.parametrize("race", [None, "pid", "card"])
def test_uncertain_probe_preserves_card_and_references(monkeypatch, race):
    card = {
        "agent": "codex",
        "pid": 42,
        "session_id": "old",
        "cwd": "fixture",
        "started": "now",
        "transcript_path": "old.jsonl",
        "codex_process_start": 123,
        "envio_codex": {"estado": "sin_confirmacion", "envio_id": "reserved"},
    }
    monkeypatch.setattr(ses, "sessions", {"old": card})
    monkeypatch.setattr(ses, "guess_transcript", lambda *args: ("old", "old.jsonl"))
    monkeypatch.setattr(ses, "transcript_home", lambda s: "fixture")
    touched = []
    monkeypatch.setattr(ses, "touch", lambda s: touched.append(s))
    monkeypatch.setattr(ses, "repoint_refs", lambda *args: pytest.fail("no mover referencias"))

    def probe(pid):
        assert pid == 42
        if race == "pid":
            card["pid"] = 43
        elif race == "card":
            ses.sessions["old"] = dict(card)
        return {"verified": False, "reason": "hilo visible incierto"}

    monkeypatch.setattr(ses.codex_identity, "probe", probe)
    ses.attach_transcript(card, ("old", "old.jsonl"))
    assert card["session_id"] == "old" and card["transcript_path"] == "old.jsonl"
    assert card["envio_codex"] == {"estado": "sin_confirmacion", "envio_id": "reserved"}
    if race:
        assert card["codex_process_start"] == 123 and not touched
    else:
        assert "codex_process_start" not in card
        assert card["codex_identity_reason"] == "hilo visible incierto"
        assert touched == [card]
