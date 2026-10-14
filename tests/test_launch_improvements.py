import json
import os
import subprocess
import sys
from pathlib import Path

import launch
import pytest
import state


def test_codex_append_preserves_user_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('developer_instructions = "Conservar instrucciones del usuario"')
    args = launch._improvement_args("codex", "Responde breve", str(tmp_path / "project"))
    assert args == ["-c", "developer_instructions=Conservar instrucciones del usuario Responde breve"]


def test_windows_argument_quote_and_injection_boundaries():
    assert launch._cmd_arg("hello world") == '"hello world"'
    for value in ("%PATH%", "a&b", "a\nb", 'a"b', "!variable!", "unicode😀"):
        with pytest.raises(ValueError):
            launch._cmd_arg(value)


def test_appended_prompt_cmd_is_one_argument_and_keeps_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: None)
    result = launch._launch_cmd(
        "D:/repo",
        "Test",
        "D:/bin/claude.exe",
        ["--resume", "s1", "--append-system-prompt", "Responde breve con pruebas"],
    )
    body = Path(result["cmd_path"]).read_text(encoding="cp1252")
    assert '--resume s1 --append-system-prompt "Responde breve con pruebas"' in body


def test_posix_prompt_is_data_not_shell(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **k: seen.append(argv))
    prompt = "instructions; $(must not execute)"
    result = launch._launch_tmux(str(tmp_path), "Title", "pi", ["--append-system-prompt", prompt])
    assert result["ok"] and seen[0][-1] == prompt
    assert "sh" not in seen[0]


def test_wsl_codex_reads_target_config_and_preserves_literal_text(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('developer_instructions = "Texto de WSL"')
    calls = []

    def paths(cwd, distro):
        calls.append(distro)
        return [config]

    monkeypatch.setattr(launch, "_codex_config_paths", paths)
    result = launch._improvement_args("codex", 'Responde breve & conserva "quotes"', "D:/repo", distro="Ubuntu")
    assert calls == ["Ubuntu"]
    assert result[-1] == 'developer_instructions=Texto de WSL Responde breve & conserva "quotes"'


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe solo en Windows")
def test_native_cmd_delivers_one_literal_instruction_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    real_popen = subprocess.Popen
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: None)
    script = tmp_path / "argument reader.py"
    script.write_text("import json,sys; print(json.dumps(sys.argv[1:]))")
    text = "developer_instructions=Responde breve; conserva pruebas y errores"
    generated = launch._launch_cmd(str(tmp_path), "Test", sys.executable, [str(script), "-c", text])
    monkeypatch.setattr(launch.subprocess, "Popen", real_popen)
    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", generated["cmd_path"]],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.strip()) == ["-c", text]


def test_wsl_configuration_timeout_does_not_block_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(launch, "_allowed_roots", lambda: [os.path.normcase(os.path.normpath(str(tmp_path)))])
    monkeypatch.setattr(launch.tmux, "en_distro", lambda *a: True)
    monkeypatch.setattr(launch.harness_updates, "before_launch", lambda *a: None)
    monkeypatch.setattr(launch.agent_improvements, "launch_instructions", lambda *a: ("brief", []))
    monkeypatch.setattr(launch, "_launch_tmux", lambda *a, **k: {"ok": True})

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(["wsl.exe"], 5)

    monkeypatch.setattr(launch, "_improvement_args", timed_out)
    result = launch.launch(str(tmp_path), "Test", "codex", distro="Ubuntu")
    assert result["ok"] and "mejoras no aplicadas" in result["aviso"]
