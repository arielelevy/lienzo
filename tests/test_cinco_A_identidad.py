"""P0 /new: handles estables no autorizan queue. Sólo fixtures, sin envíos reales."""

import json
from pathlib import Path

import codex_identity as identity
import codex_queue as queue
import pytest

THREAD = "01a14774-aa3f-7062-b3f3-aa996a33ff35"


@pytest.fixture
def card(tmp_path, monkeypatch):
    path = tmp_path / "rollout-old.jsonl"
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": THREAD, "originator": "codex-tui"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(identity.procinfo, "_WIN", True)
    monkeypatch.setattr(identity.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(identity.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(identity, "_snapshot", lambda pid: (123, {str(path)}))
    monkeypatch.setattr(queue, "codex_exe", lambda: "codex.exe")
    monkeypatch.setattr(queue, "store_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(queue.subproc, "correr", lambda *a, **kw: pytest.fail("envío oculto"))
    return {
        "agent": "codex",
        "session_id": THREAD,
        "transcript_path": str(path),
        "pid": 4242,
        "codex_process_start": 123,
    }


@pytest.mark.parametrize("transition", ["/new", "/clear", "hilo-abandonado"])
def test_stable_old_handle_does_not_authorize_queue(card, transition):
    assert identity.probe(card["pid"])["verified"] is False
    result = queue.enviar(card, transition, esperar=0)
    assert result["estado"] == "rechazado"
    assert "sin prueba del hilo visible" in result["motivo"]
    assert not queue.store_path().exists()


@pytest.mark.parametrize("change", ["pid", "rollout", "multiple", "missing"])
def test_identity_changes_are_rejected(card, monkeypatch, change):
    snapshots = iter(
        [
            (123, {card["transcript_path"]}),
            (
                124 if change == "pid" else 123,
                {"other"}
                if change == "rollout"
                else {card["transcript_path"], "other"}
                if change == "multiple"
                else set(),
            ),
        ]
    )
    monkeypatch.setattr(identity, "_snapshot", lambda pid: next(snapshots))
    assert not queue.puede_enviar(card)["puede"]


@pytest.mark.parametrize("thread", ["invalid", THREAD.upper(), "../thread"])
def test_invalid_uuid_never_authorizes_queue(card, thread):
    Path(card["transcript_path"]).write_text(
        json.dumps({"type": "session_meta", "payload": {"id": thread, "originator": "codex-tui"}}), encoding="utf-8"
    )
    assert "id de hilo" in identity.probe(card["pid"])["reason"]
    assert not queue.puede_enviar(card)["puede"]


def test_desktop_still_requires_running_app(card, monkeypatch):
    card.update(pid=None, external={"kind": "codex-desktop", "via": "rollout"})
    monkeypatch.setattr(queue, "app_running", lambda: False)
    assert not queue.puede_enviar(card)["puede"]
    monkeypatch.setattr(queue, "app_running", lambda: True)
    assert queue.puede_enviar(card)["transporte"] == "codex_queue"


def test_uncertain_previous_send_is_not_replayed(card):
    record = {
        "estado": "sin_confirmacion",
        "at": 1,
        "thread": THREAD,
        "rollout": card["transcript_path"],
        "sha256": queue._sha("texto"),
        "desde": queue._iso(1),
    }
    queue._save({"old": record})
    before = queue.store_path().read_bytes()
    assert queue.enviar(card, "texto", {"envio_id": "old"}, esperar=0)["estado"] == "rechazado"
    assert queue.store_path().read_bytes() == before
