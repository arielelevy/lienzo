"""Contrato de terminal de Antigravity según agy 1.4.3 --help."""

from pathlib import Path

import agentes
import launch
import procinfo
import procs
import pytest
import sessions
import state
import transcripts


def test_detect_and_launch_from_official_install_directory(tmp_path, monkeypatch):
    exe = tmp_path / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(launch.shutil, "which", lambda _: None)
    assert launch.harness_executable("antigravity") == str(exe)
    assert procinfo.agent_of(str(exe)) == "antigravity"
    assert "-like 'agy.exe*'" in procs._PS
    assert launch._model_args("antigravity", "gemini-3.8-flash-high") == ["--model", "gemini-3.8-flash-high"]


@pytest.mark.parametrize("sid", ["pid-123", "&calc", "", None, "deadbeef", "0" * 40, "-" * 36])
def test_resume_rejects_unidentified_or_unsafe_session(sid):
    assert launch._resume_args("antigravity", sid) == []


def test_resume_uses_conversation_id():
    sid = "11111111-2222-4333-8444-555555555555"
    assert launch._resume_args("antigravity", sid) == ["--conversation", sid]


@pytest.mark.parametrize(
    "args",
    [
        "models",
        "update",
        "--version",
        "-v",
        "--help",
        "-p hello",
        "--print=hello",
        "--prompt hello",
        "--model x models",
        "--model=x plugins list",
        "login",
        "logout",
        "hello --print",
    ],
)
def test_noninteractive_commands_are_not_cards(args):
    assert procinfo.agent_of("agy.exe", "agy.exe " + args) is None


def test_interactive_model_and_resume_are_cards():
    assert procinfo.agent_of("agy.exe", "agy.exe --model gemini-3.8-flash-high") == "antigravity"
    assert procinfo.agent_of("agy.exe", "agy.exe --conversation 551ea4e6-21f8-4257-aafc-a5f20376001d") == "antigravity"
    assert procinfo.agent_of("agy.exe", "agy.exe --model models") == "antigravity"
    assert procinfo.agent_of("agy.exe", 'agy.exe --prompt-interactive "use --print for docs"') == "antigravity"
    assert procinfo.agent_of("agy.exe", "agy.exe -- models") == "antigravity"


def test_wsl_launch_is_explicitly_unsupported(monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", True)
    assert "WSL" in launch.launch("D:/Apps/lienzo", "Antigravity", "antigravity", distro="Ubuntu")["error"]


def test_terminal_only_never_borrows_claude_history_or_approves_permissions(tmp_path):
    claude = tmp_path / ".claude" / "projects"
    claude.mkdir(parents=True)
    assert agentes.guess_transcript("antigravity", str(tmp_path), None, str(tmp_path)) == (None, None)
    parsed = transcripts.parse("antigravity", "private-conversation")
    assert parsed["turns"] == []
    assert parsed["meta"]["transcript_unavailable"] is True
    profile = agentes.perfil("antigravity")
    assert not profile.capabilities["coordinable"]
    assert (
        profile.permission_option({"question": "Allow?", "options": [{"n": 1, "text": "Yes, don't ask again"}]}) is None
    )


def test_launch_generates_cmd_without_starting_a_real_agent(tmp_path, monkeypatch):
    exe = tmp_path / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(state, "LIENZO", str(tmp_path / "lienzo-home"))
    monkeypatch.setattr(state, "load_config", lambda: {"launch_roots": [str(tmp_path)]})
    monkeypatch.setattr(launch.harness_updates, "before_launch", lambda *args: None)
    monkeypatch.setattr(launch.agent_improvements, "launch_instructions", lambda *args: ("", []))
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **kwargs: calls.append(argv))
    sid = "551ea4e6-21f8-4257-aafc-a5f20376001d"
    result = launch.launch(str(tmp_path), "Antigravity test", "antigravity", model="gemini-3.8-flash-high", resume=sid)
    assert result["ok"]
    assert result["model_applied"]
    assert result["resumed"]
    cmd = Path(result["cmd_path"]).read_text(encoding="cp1252")
    assert str(exe) in cmd
    assert "--model gemini-3.8-flash-high" in cmd
    assert f"--conversation {sid}" in cmd
    assert "--append-system-prompt" not in cmd
    assert len(calls) == 1


def test_screen_observation_uses_only_recognized_footer_and_never_asserts_a_turn():
    result = sessions.antigravity_screen_observation(
        {
            "ok": True,
            "lines": [
                "An assistant mentioned Gemini 9.9 Pro · high",
                ">",
                "? for shortcuts      Gemini 3.8 Flash · high",
                "",
            ],
        }
    )
    assert result["source"] == "screen"
    assert result["observed_at"]
    assert result["model_label"] == "Gemini 3.8 Flash · high"
    assert result["available"] is True
    assert result["activity"] == "unverified"
    assert "reply" not in result and "ended" not in result


@pytest.mark.parametrize(
    "screen",
    [
        {"ok": False, "lines": ["Gemini 3.8 Flash · high"]},
        {"ok": True, "lines": ["Gemini 3.8 Flash · high", "arbitrary assistant text"]},
        {"ok": True, "lines": ["Gemini 3.8 Flash · high"]},
        {"ok": True, "lines": []},
    ],
)
def test_missing_or_failed_footer_does_not_retain_model(screen):
    assert sessions.antigravity_screen_observation(screen)["model_label"] is None


def test_screen_poll_updates_observation_but_not_model_reply_or_state(monkeypatch):
    card = sessions.new_session("test-agy", "antigravity", "sweep")
    card.update(pid=42, alive=True, state="corriendo")
    monkeypatch.setattr(sessions, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(sessions, "touch", lambda s: None)
    monkeypatch.setattr(
        sessions, "read_screen", lambda s: {"ok": True, "lines": ["? for shortcuts     Gemini 3.8 Flash · high"]}
    )
    sessions.screen_once()
    assert card["screen_observation"]["model_label"] == "Gemini 3.8 Flash · high"
    assert card["model"] is None and card["last_reply"] == "" and card["state"] == "corriendo"
    assert sessions.public_session(card)["state_source"] == "unverified"
    monkeypatch.setattr(sessions, "read_screen", lambda s: {"ok": False})
    sessions.screen_once()
    assert card["screen_observation"]["available"] is False
    assert card["screen_observation"]["model_label"] is None
    assert card["state"] == "corriendo"


def test_identical_screen_polls_do_not_repeat_persistence_broadcast_or_capture(monkeypatch):
    card = sessions.new_session("test-agy-stable", "antigravity", "sweep")
    card.update(pid=42, alive=True, state="corriendo")
    monkeypatch.setattr(sessions, "sessions", {card["session_id"]: card})
    calls = {"save": [], "broadcast": [], "capture": []}
    monkeypatch.setattr(sessions, "save_session", lambda s: calls["save"].append(s["session_id"]))
    monkeypatch.setattr(sessions.state, "broadcast", lambda event: calls["broadcast"].append(event))
    monkeypatch.setattr(sessions.captura, "vista", lambda s: calls["capture"].append(s["session_id"]))
    ticks = iter([f"2026-10-21T02:00:{second:02d}Z" for second in range(10)])
    monkeypatch.setattr(sessions, "now", lambda: next(ticks))
    screen = {"ok": True, "lines": ["? for shortcuts     Gemini 3.8 Flash · high"]}
    monkeypatch.setattr(sessions, "read_screen", lambda s: screen)
    sessions.screen_once()
    first_published = dict(card["screen_observation"])
    sessions.screen_once()
    sessions.screen_once()
    assert card["screen_observation"] == first_published
    assert {name: len(items) for name, items in calls.items()} == {"save": 1, "broadcast": 1, "capture": 1}
    screen["lines"] = ["? for shortcuts     Gemini 3.8 Pro · high"]
    sessions.screen_once()
    assert card["screen_observation"]["model_label"] == "Gemini 3.8 Pro · high"
    assert card["screen_observation"]["observed_at"] != first_published["observed_at"]
    screen.clear()
    screen["ok"] = False
    sessions.screen_once()
    sessions.screen_once()
    assert card["screen_observation"]["available"] is False
    assert {name: len(items) for name, items in calls.items()} == {"save": 3, "broadcast": 3, "capture": 3}
