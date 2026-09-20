"""Regresiones de transporte y Pi. No inyectan teclas ni usan el servidor real."""

import io
import json
from email.message import Message
from types import SimpleNamespace

import pytest

# El fixture existente inicializa los modulos del servidor y aisla el estado en tmp.
from test_server import aislado, server, ses, st  # noqa: F401

pytestmark = pytest.mark.usefixtures("aislado")


def handler(headers=(), raw=b""):
    h = object.__new__(server.Handler)
    h.path = "/sessions/test/send"
    h.headers = Message()
    for name, value in headers:
        h.headers.add_header(name, value)
    h.rfile = io.BytesIO(raw)
    h.close_connection = False
    return h


@pytest.mark.parametrize(
    "headers,raw",
    [
        ([("Content-Length", "-1")], b""),
        ([("Content-Length", "1"), ("Content-Length", "1")], b"x"),
        ([("Content-Length", "hello")], b""),
        ([("Transfer-Encoding", "chunked")], b""),
        ([("Content-Length", "4")], b"x"),
        ([("Content-Length", str(server.MAX_BODY + 1))], b""),
    ],
)
def test_reject_invalid_http_framing(headers, raw):
    h = handler(headers, raw)
    with pytest.raises(server.RequestError):
        h._route()
    assert h.close_connection


@pytest.mark.parametrize("raw", [b"{", b"[]", b"null", b"true"])
def test_json_requires_object(raw):
    h = handler()
    h.raw = raw
    with pytest.raises(server.RequestError):
        h._json_body()


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, '{"ok": true}'),
        (0, '{"ok": false}'),
        (0, "{}"),
        (0, "[]"),
        (0, '{"ok": "true"}'),
        (0, "not json"),
    ],
)
def test_send_failure_is_not_reported_as_success(monkeypatch, returncode, stdout):
    monkeypatch.setattr(
        ses.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    )
    code, out = ses.run_send("test", 42, "hola")
    assert code == 500 and out["ok"] is False


@pytest.mark.parametrize(
    "origin,target",
    [
        ("pi", "claude"),
        ("pi", "codex"),
        ("claude", "pi"),
        ("codex", "pi"),
    ],
)
def test_cross_agent_text_transport(monkeypatch, origin, target):
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    typed = []

    def run(cmd, **kw):
        typed.append(cmd[cmd.index("--text") + 1])
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(ses.subprocess, "run", run)
    s = ses.new_session("destination", target, "hook")
    s.update(pid=42, state="termino", last_event="Stop")
    st.sessions[s["session_id"]] = s
    text = f"Mensaje de {origin}: revisión lista, código y acentos."
    code, out = ses.send_to_session(s, text, [])
    assert code == 200 and out["ok"]
    assert typed == [text]
    assert s["state"] == "corriendo"


def test_pi_dialog_blocks_injection(monkeypatch):
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    s = ses.new_session("pi-dialog", "pi", "hook")
    s.update(pid=42, needs={"kind": "pi_dialog"})
    assert ses.send_blocked(s)[0] == 409


def test_pi_only_settled_event_closes_turn(monkeypatch):
    completed = []
    monkeypatch.setattr(ses, "on_turn_end", completed.append)
    sid = "pi-lifecycle"

    def event(name, **extra):
        ses.apply_event({"agent": "pi", "session_id": sid, "hook_event_name": name, **extra})

    event("SessionStart", pi_idle=True)
    event("PiBusy")
    event("UserPromptSubmit", prompt="Revisar")
    event("PiProgress")
    assert st.sessions[sid]["state"] == "corriendo"
    assert not completed
    event("PiPromptStart", message="Elegir")
    assert st.sessions[sid]["needs"]["kind"] == "pi_dialog"
    event("PiPromptEnd", pi_idle=False)
    assert st.sessions[sid]["state"] == "corriendo"
    assert not completed
    event("Stop", last_assistant_message="Listo")
    assert st.sessions[sid]["state"] == "termino"
    assert completed == [sid]


def test_pi_reload_binds_exact_log_and_replaces_sweep_card(tmp_path, monkeypatch):
    from test_pi import message, text, transcript

    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    monkeypatch.setattr(ses.procs, "is_tui", lambda pid: True)
    placeholder = ses.new_session("pid-42", "pi", "sweep")
    placeholder["pid"] = 42
    st.sessions["pid-42"] = placeholder
    path = transcript(
        tmp_path,
        [
            message("u", None, "user", text("Conversación existente")),
            message("a", "u", "assistant", text("Respuesta del log"), stopReason="stop"),
        ],
    )
    ses.apply_event(
        {
            "agent": "pi",
            "session_id": "pi-session",
            "hook_event_name": "SessionStart",
            "pid": 42,
            "transcript_path": path,
            "pi_leaf_id": "a",
            "pi_idle": True,
        }
    )
    assert "pid-42" not in st.sessions
    s = st.sessions["pi-session"]
    assert s["hooked"] and s["transcript_path"] == path and s["pid"] == 42
    assert s["last_prompt"] == "Conversación existente"
    assert s["last_reply"] == "Respuesta del log"


def test_pi_sweep_binds_child_log_without_claiming_hook_or_firing_rules(tmp_path, monkeypatch):
    from test_pi import message, text, transcript

    completed = []
    monkeypatch.setattr(ses, "on_turn_end", completed.append)
    monkeypatch.setattr(ses.procs, "cwd_of", lambda pid: str(tmp_path))
    path = transcript(
        tmp_path,
        [
            message("u", None, "user", text("Trabajo existente")),
            message("a", "u", "assistant", text("Respuesta completa"), stopReason="stop"),
        ],
    )
    s = ses.new_session("pid-42", "pi", "sweep")
    s.update(pid=42, state="corriendo")
    st.sessions["pid-42"] = s
    ses.attach_transcript(s, ("pi-session", path))
    assert st.sessions["pi-session"] is s and "pid-42" not in st.sessions
    assert not s["hooked"] and s["source"] == "sweep"
    assert s["last_prompt"] == "Trabajo existente" and s["last_reply"] == "Respuesta completa"
    assert not completed
    # Un shell viejo no puede pisar lo que ya identifico la extension.
    s["hooked"] = True
    ses.attach_transcript(s, ("stale-session", path))
    assert s["session_id"] == "pi-session"


def test_pi_activity_discovery_finds_resumed_log_without_shell(tmp_path, monkeypatch):
    from test_pi import HEADER, message, text, transcript

    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path))
    # La cabecera puede ser anterior al proceso: /resume reutiliza ese mismo JSONL.
    path = transcript(tmp_path, [message("u", None, "user", text("Trabajo reanudado"))])
    import os

    os.utime(path, (200, 200))
    stale = tmp_path / "stale.jsonl"
    stale.write_text(json.dumps({**HEADER, "id": "old"}) + "\n", encoding="utf-8")
    os.utime(stale, (100, 100))
    assert ses.guess_pi(HEADER["cwd"], 150) == (HEADER["id"], path)
    assert ses.guess_pi(HEADER["cwd"], 201) == (None, None)
    assert ses.guess_pi("D:/other", 150) == (None, None)
    os.utime(stale, (200, 200))
    assert ses.guess_pi(HEADER["cwd"], 150) == (None, None)


def test_pi_shared_project_never_guesses_by_activity(monkeypatch):
    monkeypatch.setattr(ses.procs, "cwd_of", lambda pid: "D:/shared")
    monkeypatch.setattr(
        ses.procs,
        "sweep",
        lambda: [{"pid": pid, "agent": "pi", "exe": "node.exe", "created": st.now()} for pid in (42, 43)],
    )
    monkeypatch.setattr(ses, "guess_pi", lambda *args: pytest.fail("dos Pi en un cwd: identidad ambigua"))
    ses.sweep_once()
    assert len(st.sessions) == 2
    assert all(s["transcript_path"] is None for s in st.sessions.values())


@pytest.mark.parametrize("hooked,expected", [(False, "/reload"), (True, "primer turno")])
def test_pi_missing_log_is_not_reported_as_empty_conversation(hooked, expected):
    h = handler()
    h._session = lambda sid: {"agent": "pi", "hooked": hooked, "transcript_path": None}
    results = []
    h._json = lambda status, body: results.append((status, body))
    h._session_view("pi", "digest")
    assert results[0][0] == 200
    assert expected in results[0][1]["note"]
