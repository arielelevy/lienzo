"""Tests minimos de lienzo/procinfo.py y lienzo/procs.py (Windows, ctypes)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import procinfo, procs  # noqa: E402


def test_agent_of():
    assert procs.agent_of("claude.exe") == "claude"
    assert procs.agent_of(r"C:\Users\x\.local\bin\claude.exe") == "claude"
    assert procs.agent_of("claude.exe.old.123") == "claude", "el binario renombrado por el auto-update"
    assert procs.agent_of("codex.exe") == "codex"
    assert procs.agent_of("CODEX.EXE") == "codex"
    assert procs.agent_of("notepad.exe") is None
    assert procs.agent_of("claude.exex") is None
    assert procs.agent_of(None) is None
    assert procs.agent_of is procinfo.agent_of, "procs re-exporta la funcion de procinfo"


def test_is_impostor():
    assert procs.is_impostor(r"C:\Program Files\WindowsApps\Claude_1.0_x64__abc\claude.exe", None) is True
    assert procs.is_impostor(r"C:\Users\x\.vscode\extensions\anthropic.claude-code-2.0\native-binary\claude.exe", "") is True
    assert procs.is_impostor(r"C:\Users\x\.local\bin\codex.exe", "codex.exe app-server --listen") is True
    assert procs.is_impostor(r"C:\Users\x\.local\bin\claude.exe", "claude.exe --type=renderer") is True
    assert procs.is_impostor(r"C:\Users\x\.local\bin\claude.exe", "claude.exe --resume") is False
    assert procs.is_impostor(r"C:\Users\x\.local\bin\codex.exe", None) is False


def test_alive():
    assert procs.alive(os.getpid()) is True
    assert procs.alive(999999) is False, "los PID de Windows son multiplos de 4: 999999 nunca existe"
    assert procs.alive(None) is False
    assert procs.alive(0) is False


def test_agent_alive_rechaza_pid_de_otro_programa():
    # python.exe esta vivo pero no es un agente
    assert procs.agent_alive(os.getpid()) is False


def test_proc_info_e_image_path():
    parent, exe = procinfo.proc_info(os.getpid())
    assert parent and parent != os.getpid()
    assert exe and os.path.basename(exe).lower().startswith("python")
    assert procinfo.image_path(os.getpid()) == exe
    assert procinfo.proc_info(999999) == (None, None)
    assert procinfo.image_path(999999) is None


def test_cwd_of_propio_proceso():
    got = procs.cwd_of(os.getpid())
    assert got is not None
    assert os.path.normcase(got) == os.path.normcase(os.getcwd())
    assert procs.cwd_of(999999) is None
