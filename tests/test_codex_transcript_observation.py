"""Process-bound read-only discovery cannot grant queue authorization."""

import json

import agentes
import codex_identity as identity
import codex_queue
import pytest
import sessions

SID = "01a14c6f-f6af-7593-a0c3-63e77928b4ae"
OTHER = "01a14bf5-c9c0-7b32-9570-a8b5acf7b08d"


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    paths = {}
    for pid, sid in [(4242, SID), (4243, OTHER)]:
        path = tmp_path / f"rollout-{sid}.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": sid,
                        "originator": "codex-tui",
                        "cwd": str(tmp_path),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        paths[pid] = str(path)

    def snapshot(pid, *, observation=False):
        if not observation:
            raise OSError("no se pudo duplicar un handle: snapshot incompleto")
        return pid * 100, {paths[pid]}

    monkeypatch.setattr(identity.procinfo, "_WIN", True)
    monkeypatch.setattr(identity.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(identity, "_snapshot", snapshot)
    return paths


def test_two_processes_same_folder_keep_their_own_observed_transcripts(inventory):
    for pid, sid in [(4242, SID), (4243, OTHER)]:
        assert not identity.probe(pid)["verified"]
        proof = identity.transcript_identity(pid)
        assert proof["observed"] and not proof["verified"]
        assert (proof["pid"], proof["thread"], proof["path"]) == (pid, sid, inventory[pid])
        assert agentes.perfil("codex").identity({"pid": pid}, {}) == (sid, inventory[pid])


@pytest.mark.parametrize("change", ["multiple", "recycled", "switch", "exec"])
def test_observation_rejects_ambiguous_changed_or_non_tui_rollouts(inventory, monkeypatch, change):
    calls = 0

    def snapshot(pid, *, observation=False):
        nonlocal calls
        if not observation:
            raise OSError("incomplete")
        calls += 1
        if change == "multiple":
            return 1, set(inventory.values())
        if change == "recycled" and calls == 2:
            return 2, {inventory[pid]}
        if change == "switch" and calls == 2:
            return 1, {inventory[4243]}
        return 1, {inventory[pid]}

    if change == "exec":
        from pathlib import Path

        Path(inventory[4242]).write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": SID,
                        "originator": "codex_exec",
                    },
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(identity, "_snapshot", snapshot)
    result = identity.transcript_identity(4242)
    assert not result["verified"] and not result.get("observed")


def test_observed_transcript_attaches_without_recording_send_identity(inventory, monkeypatch, tmp_path):
    card = sessions.new_session("pid-4242", "codex", "sweep")
    card.update(pid=4242, cwd=str(tmp_path), alive=True, codex_process_start=999)
    monkeypatch.setattr(sessions, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(sessions, "repoint_refs", lambda *args: (0, 0))
    monkeypatch.setattr(sessions, "touch", lambda *args: None)
    sessions.attach_transcript(card, (SID, inventory[4242]))
    assert card["session_id"] == SID
    assert card["transcript_path"] == inventory[4242]
    assert "codex_process_start" not in card
    monkeypatch.setattr(codex_queue.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(codex_queue, "codex_exe", lambda: "synthetic-codex")
    assert not codex_queue.puede_enviar(card)["puede"]


def test_observation_does_not_steal_a_card_from_another_live_process(inventory, monkeypatch, tmp_path):
    existing = sessions.new_session(SID, "codex", "sweep")
    existing.update(pid=4243, cwd=str(tmp_path), alive=True)
    monkeypatch.setattr(sessions, "sessions", {SID: existing})
    monkeypatch.setattr(sessions.backend, "agent_alive", lambda s: True)
    sessions.adopt_process({"agent": "codex", "pid": 4242, "cwd": str(tmp_path), "exe": "synthetic"})
    assert existing["pid"] == 4243
