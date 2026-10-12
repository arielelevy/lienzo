"""Títulos por proyecto, con consola y procesos simulados."""

import console_title
import console_titles as ct
import pytest
import sessions
import state


@pytest.mark.parametrize(
    "title,repo,expected",
    [
        ("Agrega validaciones", "lienzo", "Lienzo - Agrega validaciones"),
        ("Lienzo - encargo A", "lienzo", "Lienzo - encargo A"),
        ("lienzo - revisar", "lienzo", "lienzo - revisar"),
        ("chesstudia - encargo B - revisar", "chess", "chesstudia - encargo B - revisar"),
        ("chesstudia - coordinadora - ECO", "chess", "chesstudia - coordinadora - ECO"),
        ("encargo B - revisar", "chess", "Chess - encargo B - revisar"),
        ("revisar · copycat", "lienzo", "Lienzo - revisar · copycat"),
        ("Proyecto", None, "Proyecto"),
        (None, "lienzo", "lienzo"),
    ],
)
def test_project_prefix(title, repo, expected):
    assert ct.project_title({"title": title, "repo": repo}) == expected
    assert ct.project_title({"title": expected, "repo": repo}) == expected


def test_sync_updates_card_and_console_without_sending(monkeypatch):
    card = {
        "session_id": "s",
        "agent": "codex",
        "pid": 42,
        "alive": True,
        "repo": "lienzo",
        "title": "Agrega validaciones",
        "title_source": "prompt",
    }
    monkeypatch.setattr(state, "sessions", {"s": card})
    saved, renamed = [], []
    monkeypatch.setattr(sessions, "touch", lambda s: saved.append(dict(s)))
    monkeypatch.setattr(ct, "native_title", lambda s, title: renamed.append((s["pid"], title)) or {"ok": True})
    monkeypatch.setattr(sessions, "send_to_session", lambda *a: pytest.fail("no debe enviar teclas"))
    ct.sync_once()
    assert card["title"] == "Lienzo - Agrega validaciones"
    assert card["title_source"] == "prompt"
    assert len(saved) == 1 and renamed == [(42, card["title"])]
    ct.sync_once()
    assert len(saved) == 1  # no duplicar el prefijo ni guardar otra vez la tarjeta
    assert len(renamed) == 2  # seguir corrigiendo un título que la TUI reescriba


def test_read_only_and_dead_sessions_are_not_renamed(monkeypatch):
    monkeypatch.setattr(
        state,
        "sessions",
        {
            "a": {"alive": False, "pid": 1},
            "b": {"alive": True, "pid": 2, "no_console": True},
            "c": {"alive": True, "pid": 3, "orphan": True},
        },
    )
    monkeypatch.setattr(ct, "native_title", lambda *a: pytest.fail("no debe cambiar la consola"))
    ct.sync_once()


def test_native_helper_uses_pid_and_title_as_arguments(monkeypatch):
    monkeypatch.setattr(ct.backend, "is_tmux", lambda s: False)
    monkeypatch.setattr(ct.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(ct.subproc, "correr", lambda argv, **kwargs: calls.append(argv) or (0, '{"ok":true}', ""))
    title = 'Lienzo - comando & "literal"'
    assert ct.native_title({"pid": 42, "agent": "codex"}, title)["ok"]
    assert calls[0][-1] == title and "--pid" in calls[0]
    assert not any(arg in ("cmd", "powershell", "-Command") for arg in calls[0])


def test_helper_refuses_wrong_agent_before_attach(monkeypatch):
    monkeypatch.setattr(console_title.sys, "platform", "win32")
    monkeypatch.setattr(console_title.procinfo, "process_agent", lambda pid: "pi")
    monkeypatch.setattr(console_title.ctypes, "WinDLL", lambda *a, **k: pytest.fail("no debe adjuntar"), raising=False)
    assert "PID" in console_title.update(42, "codex", "Lienzo - trabajo")["error"]


def test_tmux_checks_owner_and_renames_without_shell(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ct.backend, "is_tmux", lambda s: True)
    monkeypatch.setattr(ct.tmux, "target_valid", lambda *a: True)
    calls = []
    monkeypatch.setattr(
        ct.tmux, "_tmux", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0, stderr="")
    )
    assert ct.native_title({"target": "%2", "pid": 42, "distro": "Ubuntu"}, "Chess - trabajo")["ok"]
    assert calls == [(("rename-window", "-t", "%2", "Chess - trabajo"), {"distro": "Ubuntu"})]
