"""El pie de una TUI con daemon vincula lectura, nunca autoriza queue."""

import json
import sqlite3
from contextlib import closing

import codex_observation as observation
import pytest

SID = "01a15639-8f32-7ed2-97f9-a56b81c865e3"
OTHER = "01a154f4-aa8c-7231-9867-a73c9e0b1d21"
READ_FOOTER = observation._footer


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(observation.procinfo, "_WIN", True)
    monkeypatch.setattr(observation.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(observation.procs, "creation_filetime", lambda pid: 123)
    monkeypatch.setattr(observation, "_footer", lambda pid: (str(tmp_path), "Mi sesión"))
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / f"rollout-{SID}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": SID, "originator": "codex-tui"}}), encoding="utf-8"
    )
    path = tmp_path / "state_5.sqlite"
    with closing(sqlite3.connect(path)) as con, con:
        con.execute("CREATE TABLE threads (id TEXT, cwd TEXT, name TEXT, archived INT, originator TEXT)")
        con.execute("INSERT INTO threads VALUES (?,?,?,0,'codex-tui')", (SID, str(tmp_path), "Mi sesión"))
    return path


def test_unique_full_visible_name_attaches_reading_only(database):
    proof = observation.observe(42)
    assert proof["thread"] == SID and proof["observed"] and not proof["verified"]


def test_extended_windows_path_is_the_same_folder(database):
    import os

    if os.name != "nt":
        pytest.skip("ruta extendida de Windows")
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("UPDATE threads SET cwd=?", ("\\\\?\\" + str(database.parent),))
    assert observation.observe(42)["thread"] == SID


@pytest.mark.parametrize("change", ["duplicate", "other-folder", "exec", "archived", "truncated"])
def test_uncertain_or_non_tui_name_is_not_associated(database, change):
    with closing(sqlite3.connect(database)) as con, con:
        if change == "duplicate":
            con.execute("INSERT INTO threads SELECT ?,cwd,name,archived,originator FROM threads", (OTHER,))
        elif change == "other-folder":
            con.execute("UPDATE threads SET cwd='other'")
        elif change == "exec":
            con.execute("UPDATE threads SET originator='codex_exec'")
        elif change == "archived":
            con.execute("UPDATE threads SET archived=1")
        else:
            con.execute("UPDATE threads SET name='Mi sesión completa'")
    assert observation.observe(42) is None


@pytest.mark.parametrize("change", ["pid", "footer"])
def test_process_or_visible_thread_switch_rejects_observation(database, monkeypatch, change):
    if change == "pid":
        starts = iter([123, 456])
        monkeypatch.setattr(observation.procs, "creation_filetime", lambda pid: next(starts))
    else:
        footers = iter([(str(database.parent), "Mi sesión"), (str(database.parent), "Otra sesión")])
        monkeypatch.setattr(observation, "_footer", lambda pid: next(footers))
    assert observation.observe(42) is None


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(observation.procinfo, "_WIN", True)
    monkeypatch.setattr(observation.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(observation.procs, "creation_filetime", lambda pid: 123)
    assert observation.observe(42) is None
    assert not (tmp_path / "state_5.sqlite").exists()


@pytest.mark.parametrize(
    "footer,expected",
    [
        ("  GPT-6.1-Sol low fast · D:/Apps/lienzo · Mi sesión", ("D:/Apps/lienzo", "Mi sesión")),
        ("  GPT-6.1-Sol low fast · D:/Apps/lienzo · Mi sesi…", None),
        ("  GPT-6.1-Sol low fast · D:/Apps/lienzo", None),
    ],
)
def test_footer_requires_complete_visible_name(monkeypatch, footer, expected):
    snapshot = {"ok": True, "lines": ["›", "", footer, "← for agents · ? for shortcuts"]}
    monkeypatch.setattr(observation.subproc, "correr", lambda *a, **kw: (0, json.dumps(snapshot), ""))
    assert READ_FOOTER(42) == expected
