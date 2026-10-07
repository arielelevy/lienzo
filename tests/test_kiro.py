import json

import launch
import restore

from lienzo import (
    kiro,
    server,  # noqa: F401
    transcripts,
)

SID = "sess_b47dbdad-0ae0-49de-b24a-e14abef7b0db"


def test_identity_uses_engine_parent_and_rejects_ambiguous_locks(tmp_path, monkeypatch):
    folder = tmp_path / ".kiro" / "sessions" / "bucket" / SID
    folder.mkdir(parents=True)
    (folder / ".lock").write_text(json.dumps({"pid": 22}))
    (folder / "session.json").write_text(json.dumps({"id": SID}))
    (folder / "messages.jsonl").write_text("")
    monkeypatch.setattr(kiro.procinfo, "proc_info", lambda pid: (11, "C:/Kiro-Cli/bun.exe"))
    assert kiro.identity(11, str(tmp_path)) == (SID, str(folder / "messages.jsonl"))
    assert kiro.identity(99, str(tmp_path)) is None
    second = folder.parent / "sess_11111111-1111-1111-1111-111111111111"
    second.mkdir()
    for name in (".lock", "messages.jsonl"):
        (second / name).write_bytes((folder / name).read_bytes())
    (second / "session.json").write_text(json.dumps({"id": second.name}))
    assert kiro.identity(11, str(tmp_path)) is None


def test_parser_tracks_turns_tools_permissions_and_steering(tmp_path):
    path = tmp_path / "messages.jsonl"
    rows = [
        {"type": "user", "content": "prueba"},
        {"type": "turn_start", "executionId": "e1"},
        {"type": "pending_interaction", "toolCallId": "t1", "question": "Shell"},
        {"type": "interaction_resolved", "toolCallId": "t1"},
        {"type": "tool_call", "toolCallId": "t1", "toolName": "run_command", "args": {"command": "git status"}},
        {"type": "tool_result", "toolCallId": "t1", "content": "clean", "success": True},
        {"type": "user", "source": "steer", "content": "solo mirar"},
        {
            "type": "user",
            "content": "synthetic duplicate",
            "_meta": {"kiro": {"syntheticUserMessageReason": "steering-injection"}},
        },
        {"type": "assistant", "operationType": "Reasoning", "content": "private"},
        {"type": "assistant", "operationType": "Say", "content": "OK"},
        {"type": "turn_end", "executionId": "e1"},
    ]
    path.write_text(
        "\n".join(
            json.dumps({"id": str(i), "timestamp": "2026-10-07T05:00:00Z", "payload": row})
            for i, row in enumerate(rows)
        ),
        encoding="utf-8",
    )
    parsed = transcripts.parse_kiro(str(path))
    assert len(parsed["turns"]) == 1
    turn = parsed["turns"][0]
    assert turn["ended"] and turn["final"] == "OK"
    assert "kiro_pending" not in turn
    assert turn["blocks"][0]["result"]["text"] == "clean"
    assert transcripts.digest_turn(turn)["commands"] == ["git status"]
    assert not any(b.get("text") == "private" for b in turn["blocks"])
    assert turn["blocks"][1]["text"] == "solo mirar"


def test_resume_uses_exact_kiro_session():
    assert restore.valid_id("kiro", SID)
    assert not restore.valid_id("kiro", "pid-22")
    assert launch._resume_args("kiro", SID) == ["--resume-id", SID]
    assert launch._resume_args("kiro", "sess_foo & calc") == []


def test_partial_transcript_keeps_assistant_when_prompt_is_outside_tail(tmp_path):
    path = tmp_path / "messages.jsonl"
    rows = [
        {"type": "assistant", "operationType": "Say", "content": "respuesta parcial", "executionId": "e"},
        {"type": "turn_end", "executionId": "e"},
    ]
    path.write_text("\n".join(json.dumps({"payload": row}) for row in rows))
    turns = transcripts.parse_kiro(str(path))["turns"]
    assert len(turns) == 1 and turns[0]["ended"]
    assert turns[0]["final"] == "respuesta parcial"
    assert turns[0]["prompt"] == "(turno anterior al corte)"
