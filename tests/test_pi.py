"""Pi: parser de rama activa, procesos Node y registro de extension. Sin APIs de modelos."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install
from lienzo import procinfo, procs, transcripts

HEADER = {"type": "session", "id": "pi-session", "version": 3, "cwd": "D:/Apps/lienzo"}


def message(id, parent, role, content, **extra):
    return {
        "type": "message",
        "id": id,
        "parentId": parent,
        "timestamp": "2026-09-10T10:00:00Z",
        "message": {"role": role, "content": content, **extra},
    }


def text(value):
    return [{"type": "text", "text": value}]


def transcript(tmp_path, rows):
    path = tmp_path / "pi.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [HEADER, *rows]) + "\n", encoding="utf-8")
    return str(path)


def test_pi_tools_digest_and_unicode(tmp_path):
    path = transcript(
        tmp_path,
        [
            {"type": "session_info", "id": "name", "parentId": None, "name": "Revisión Pi"},
            message("u", "name", "user", text("Revisá esto") + [{"type": "image", "data": "not text"}]),
            message(
                "a",
                "u",
                "assistant",
                [
                    {"type": "thinking", "thinking": "privado"},
                    *text("Voy a revisar"),
                    {"type": "toolCall", "id": "r", "name": "read", "arguments": {"path": "a.py"}},
                    {"type": "toolCall", "id": "w", "name": "edit", "arguments": {"path": "a.py", "edits": []}},
                    {"type": "toolCall", "id": "b", "name": "bash", "arguments": {"command": "pytest"}},
                ],
                stopReason="toolUse",
            ),
            message("rb", "a", "toolResult", text("falló"), toolCallId="b", toolName="bash", isError=True),
            message("rr", "rb", "toolResult", text("leído"), toolCallId="r", toolName="read", isError=False),
            message("rw", "rr", "toolResult", text("editado"), toolCallId="w", toolName="edit", isError=False),
            message("end", "rw", "assistant", text("Listo."), stopReason="stop", usage={"input": 10, "output": 4}),
        ],
    )
    parsed = transcripts.parse("pi", path)
    turn = parsed["turns"][0]
    assert parsed["meta"]["title"] == "Revisión Pi"
    assert turn["prompt"] == "Revisá esto" and turn["ended"]
    assert turn["usage"]["input"] == 10
    digest = transcripts.digest("pi", path)["turns"][0]
    assert digest["files"] == ["a.py"]
    assert digest["reads"] == 1 and digest["tools"] == 3
    assert digest["commands"] == ["pytest"]
    assert digest["errors"] == ["bash: falló"]
    assert digest["says"] == ["Voy a revisar"] and digest["final"] == "Listo."
    assert "privado" not in json.dumps(digest)


def test_pi_branch_does_not_mix_abandoned_work(tmp_path):
    path = transcript(
        tmp_path,
        [
            message("u", None, "user", "primero"),
            message("a", "u", "assistant", text("base"), stopReason="stop"),
            message("old", "a", "user", "abandonado"),
            message("old-end", "old", "assistant", text("no reenviar"), stopReason="stop"),
            message("new", "a", "user", "otra rama"),
            message("new-end", "new", "assistant", text("respuesta nueva"), stopReason="stop"),
        ],
    )
    assert [t["prompt"] for t in transcripts.parse("pi", path)["turns"]] == ["primero", "otra rama"]
    assert transcripts.turns("pi", path, leaf_id="old-end")["turns"][-1]["final"] == "no reenviar"
    assert transcripts.digest("pi", path, leaf_id="")["turns"] == []
    assert transcripts.turns("pi", path, before="new")["turns"][-1]["id"] == "u"


def test_pi_tail_partial_result_and_broken_lines(tmp_path):
    path = transcript(
        tmp_path,
        [
            message("u", None, "user", "x" * 3000),
            message("r", "u", "toolResult", text("resultado"), toolCallId="missing", toolName="write", isError=True),
            message("a", "r", "assistant", [], stopReason="error", errorMessage="connection error"),
        ],
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write('null\n[]\n{"broken":')
    parsed = transcripts.parse("pi", path, max_bytes=900)
    assert parsed["meta"]["truncated"] and parsed["meta"]["cwd"] == HEADER["cwd"]
    turn = parsed["turns"][0]
    assert turn["prompt"] == "(turno anterior al corte)"
    assert turn["blocks"][0]["result"]["is_error"]
    assert turn["error"] == "connection error" and turn["ended"]
    assert transcripts.parse("pi", path, max_bytes=900, leaf_id="u")["turns"] == []


@pytest.mark.parametrize(
    "reason,ended", [("toolUse", False), ("stop", True), ("length", True), ("aborted", True), ("deferred", False)]
)
def test_pi_stop_reasons(tmp_path, reason, ended):
    path = transcript(
        tmp_path, [message("u", None, "user", "hola"), message("a", "u", "assistant", [], stopReason=reason)]
    )
    turn = transcripts.parse_pi(path)["turns"][0]
    assert turn["ended"] is ended
    assert (turn["error"] == "turno abortado") is (reason == "aborted")


def test_pi_retry_clears_error(tmp_path):
    path = transcript(
        tmp_path,
        [
            message("u", None, "user", "hola"),
            message("bad", "u", "assistant", [], stopReason="error", errorMessage="overloaded"),
            message("a", "bad", "assistant", text("recuperado"), stopReason="stop"),
        ],
    )
    assert transcripts.parse_pi(path)["turns"][0]["error"] is None


PI_ENTRY = r"C:\Users\Ariel\AppData\Roaming\npm\node_modules\@earendil-works\pi-coding-agent\dist\bundle\cli.js"
PI_CMD = f'"C:\\Program Files\\nodejs\\node.exe" "{PI_ENTRY}"'


@pytest.mark.parametrize("suffix", ["", ' --session "C:\\ruta con espacios\\s.jsonl"', ' -- "--print"'])
def test_pi_node_cli(suffix):
    assert procinfo.agent_of(r"C:\Program Files\nodejs\node.exe", PI_CMD + suffix) == "pi"
    assert procinfo.agent_of("node.exe", PI_CMD.replace("bundle\\", "")) == "pi"


@pytest.mark.parametrize(
    "suffix",
    [
        " --mode rpc",
        " --mode=json",
        " -p",
        " --print",
        " --export a.jsonl",
        " --list-models",
        " update",
        " install npm:test",
        " --version",
    ],
)
def test_pi_excludes_noninteractive(suffix):
    assert procinfo.agent_of("node.exe", PI_CMD + suffix) is None


def test_pi_not_every_node_is_an_agent():
    assert procinfo.agent_of("node.exe") is None
    assert procinfo.agent_of("node.exe", f'node other.js "{PI_ENTRY}"') is None
    assert procinfo.agent_of("node.exe", PI_CMD.replace("cli.js", "cli.js.fake")) is None
    assert "test_pi" in (procinfo.command_line(os.getpid()) or "") or "pytest" in (
        procinfo.command_line(os.getpid()) or ""
    )


def test_pi_liveness_and_send_validation(monkeypatch):
    monkeypatch.setattr(procinfo, "image_path", lambda pid: r"C:\node.exe")
    monkeypatch.setattr(procs, "image_path", procinfo.image_path)
    monkeypatch.setattr(procinfo, "command_line", lambda pid: PI_CMD)
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    assert procs.agent_alive(42) and procs.is_tui(42)
    monkeypatch.setattr(procinfo, "command_line", lambda pid: "node other.js")
    assert not procs.agent_alive(42) and not procs.is_tui(42)


def test_pi_install_idempotent_preserves_settings(tmp_path):
    path = tmp_path / "agent" / "settings.json"
    path.parent.mkdir()
    original = {"defaultModel": "test", "extensions": ["other.ts"], "packages": ["npm:other"]}
    path.write_text(json.dumps(original), encoding="utf-8")
    install.merge_pi(str(path), False)
    install.merge_pi(str(path), False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["extensions"] == ["other.ts", f"{install.HERE}/extensions/pi-lienzo.ts"]
    assert data["packages"] == original["packages"]
    install.merge_pi(str(path), True)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(path.parent.glob("settings.json.bak-*"))


def test_pi_install_fresh_and_invalid(tmp_path):
    path = tmp_path / "new" / "settings.json"
    install.merge_pi(str(path), True)
    assert not path.exists()
    install.merge_pi(str(path), False)
    assert path.exists()
    path.write_text('{"extensions": "not a list"}', encoding="utf-8")
    with pytest.raises(TypeError):
        install.merge_pi(str(path), False)
    assert path.read_text(encoding="utf-8") == '{"extensions": "not a list"}'


def test_pi_child_session_requires_matching_header_and_no_ambiguity(tmp_path, monkeypatch):
    first = transcript(tmp_path, [message("u", None, "user", "historial")])
    second = tmp_path / "other.jsonl"
    second.write_text(json.dumps({**HEADER, "id": "other"}) + "\n", encoding="utf-8")
    envs = {
        10: {"PI_SESSION_ID": HEADER["id"], "PI_SESSION_FILE": first},
        11: {"PI_SESSION_ID": "other", "PI_SESSION_FILE": str(second)},
        12: {"PI_SESSION_ID": "wrong", "PI_SESSION_FILE": first},
        13: {"PI_SESSION_ID": HEADER["id"], "PI_SESSION_FILE": "relative.jsonl"},
    }
    monkeypatch.setattr(procinfo, "pi_session_environment", lambda child, parent: envs.get(child, {}))
    assert procs.pi_session_from_children(42, [10]) == (HEADER["id"], os.path.normcase(first))
    assert procs.pi_session_from_children(42, [10, 11]) is None
    assert procs.pi_session_from_children(42, [12, 13, 14]) is None


def test_pi_environment_only_returns_session_fields(monkeypatch):
    from types import SimpleNamespace

    payload = "SECRET=not-returned\0PI_SESSION_ID=session\0PI_SESSION_FILE=C:\\sesión.jsonl\0\0".encode("utf-16-le")
    closed = []
    monkeypatch.setattr(procinfo, "open_process", lambda *args: 7)
    monkeypatch.setattr(procinfo, "close_handle", closed.append)
    info = SimpleNamespace(PebBaseAddress=0x1000, InheritedFromUniqueProcessId=42)
    monkeypatch.setattr(procinfo, "basic_info", lambda h: info)

    def memory(h, address, length):
        if address == 0x1020:
            return (0x2000).to_bytes(8, "little")
        if address == 0x2080:
            return (0x3000).to_bytes(8, "little")
        if address == 0x3000:
            return payload.ljust(length, b"\0")
        return None

    monkeypatch.setattr(procinfo, "read_memory", memory)
    assert procinfo.pi_session_environment(10, 42) == {
        "PI_SESSION_ID": "session",
        "PI_SESSION_FILE": "C:\\sesión.jsonl",
    }
    assert closed == [7]
    info.InheritedFromUniqueProcessId = 99
    assert procinfo.pi_session_environment(10, 42) == {}
