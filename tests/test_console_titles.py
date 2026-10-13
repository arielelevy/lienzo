"""Títulos por proyecto, con consola y procesos simulados."""

import console_title
import console_titles as ct
import pytest
import sessions
import state


@pytest.fixture(autouse=True)
def isolated_title_attempts(monkeypatch):
    monkeypatch.setattr(ct, "_attempted", {})


@pytest.mark.parametrize(
    "title,repo,expected",
    [
        ("Agrega validaciones", "lienzo", "lienzo | Agrega validaciones"),
        ("Lienzo - encargo A", "lienzo", "lienzo | encargo A"),
        ("lienzo - revisar", "lienzo", "lienzo | revisar"),
        ("chesstudia - encargo B - revisar", "chess", "chesstudia | encargo B - revisar"),
        ("chesstudia - coordinadora - ECO", "chess", "chesstudia | coordinadora - ECO"),
        ("encargo B - revisar", "chess", "chess | encargo B - revisar"),
        ("revisar · copycat", "lienzo", "lienzo | revisar · copycat"),
        ("Proyecto", None, "Proyecto"),
        (None, "lienzo", "lienzo | sesión"),
        ("Lienzo - lienzo | encargo A - pruebas", "lienzo", "lienzo | encargo A - pruebas"),
        ("Lienzo - Lienzo | encargo A - pruebas", "lienzo", "lienzo | encargo A - pruebas"),
        ("lienzo | lienzo | tarea", "lienzo", "lienzo | tarea"),
        ("encargo A - pruebas | lienzo", "lienzo", "lienzo | encargo A - pruebas"),
        ("LIENZO | encargo B - Caveman RTK y Jev", "LIENZO", "lienzo | encargo B - Caveman RTK y Jev"),
        ("CHESSTUDIA - encargo B - ECO", "chess", "chesstudia | encargo B - ECO"),
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
    assert card["title"] == "lienzo | Agrega validaciones"
    assert card["title_source"] == "prompt"
    assert len(saved) == 1 and renamed == [(42, card["title"])]
    ct.sync_once()
    assert len(saved) == 1  # no duplicar el prefijo ni guardar otra vez la tarjeta
    assert len(renamed) == 1  # no volver a escribir por el ciclo periódico
    card["title"] = "lienzo | encargo A - RTK/Jev"
    ct.sync_once()
    assert renamed[-1] == (42, card["title"]) and len(renamed) == 2
    card["pid"] = 43
    ct.sync_once()
    assert renamed[-1] == (43, card["title"]) and len(renamed) == 3


def test_failed_title_is_visible_and_not_retried_until_change(monkeypatch):
    card = {"session_id": "s", "pid": 42, "alive": True, "agent": "codex", "repo": "lienzo", "title": "tarea"}
    monkeypatch.setattr(state, "sessions", {"s": card})
    monkeypatch.setattr(sessions, "touch", lambda s: None)
    calls, notices = [], []
    monkeypatch.setattr(
        ct, "native_title", lambda s, title: calls.append(title) or {"ok": False, "error": "fixture error"}
    )
    monkeypatch.setattr(state, "avisar_si_cambia", lambda key, error: notices.append(error))
    ct.sync_once()
    ct.sync_once()
    assert calls == ["lienzo | tarea"] and notices == ["fixture error"]
    card["title"] = "nueva tarea"
    ct.sync_once()
    assert calls == ["lienzo | tarea", "lienzo | nueva tarea"]


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


def test_manual_sync_reapplies_title_after_cached_attempt(monkeypatch):
    card = {"session_id": "s", "pid": 42, "alive": True, "agent": "codex", "repo": "lienzo", "title": "tarea"}
    monkeypatch.setattr(state, "sessions", {"s": card})
    monkeypatch.setattr(sessions, "touch", lambda s: None)
    calls = []
    monkeypatch.setattr(ct, "native_title", lambda s, title: calls.append(title) or {"ok": True})
    ct.sync_once()
    ct.sync_once()
    ct.sync_once(force=True)
    assert calls == ["lienzo | tarea", "lienzo | tarea"]
    assert card["title"] == "lienzo | tarea"


def test_manual_rescan_discovers_before_retitling(monkeypatch):
    from lienzo import server

    calls = []
    monkeypatch.setattr(server, "sweep_once", lambda: calls.append("sweep"))
    monkeypatch.setattr(ct, "sync_once", lambda **kwargs: calls.append(kwargs))
    server.rescan_once()
    assert calls == ["sweep", {"force": True}]


def test_manual_rescan_reports_worker_failure(monkeypatch):
    from lienzo import server

    def fail():
        raise RuntimeError("fixture rescan failure")

    messages = []
    monkeypatch.setattr(server, "sweep_once", fail)
    monkeypatch.setattr(server, "log", messages.append)
    monkeypatch.setattr(ct, "sync_once", lambda **kwargs: pytest.fail("no se debe retitular sin barrer"))
    server.rescan_once()
    assert len(messages) == 1 and "fixture rescan failure" in messages[0]


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
