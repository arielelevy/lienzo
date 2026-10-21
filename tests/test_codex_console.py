"""Codex CLI targets the visible console; uncertain thread identity never calls queue."""

import datetime as dt
from types import SimpleNamespace

import pytest
import send
import sessions as ses


@pytest.fixture
def cli(tmp_path, monkeypatch):
    card = ses.new_session("old-thread", "codex", "sweep")
    card.update(pid=4242, alive=True, state="termino", codex_console_start=123)
    monkeypatch.setattr(ses, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses.captura, "envio", lambda *a, **kw: None)
    monkeypatch.setattr(ses.captura, "pedido", lambda *a, **kw: None)
    monkeypatch.setattr(ses, "_mirror_owner", lambda sid: None)
    monkeypatch.setattr(ses.codex_queue, "puede_enviar", lambda *a: pytest.fail("CLI does not use queue"))
    monkeypatch.setattr(ses.codex_queue, "enviar", lambda *a: pytest.fail("no hidden turn"))
    return card


@pytest.mark.parametrize("transition", ["normal", "/new", "/clear"])
def test_thread_changes_do_not_send_to_old_rollout(cli, monkeypatch, transition):
    typed = []
    monkeypatch.setattr(ses, "run_send", lambda s, text: typed.append((s["pid"], text)) or (200, {"ok": True}))
    cli["codex_identity_reason"] = f"old rollout retained after {transition}"
    assert ses.puede_enviar(cli) == {"puede": True, "motivo": None, "transporte": "tecleo"}
    code, result = ses.send_to_session(cli, "mensaje", [])
    assert code == 200 and result["estado"] == "encolado"
    assert typed == [(4242, "mensaje")]
    assert cli["state"] == "termino" and cli["envio_pendiente"]
    ses.send_to_session(cli, "mensaje", [])
    assert len(typed) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"stopped_by": "user"},
        {"pending_id": "permission"},
        {"no_console": True},
        {"orphan": True},
        {"external": {"kind": "runner"}},
    ],
)
def test_existing_guards_remain_active(cli, monkeypatch, change):
    cli.update(change)
    monkeypatch.setattr(ses, "run_send", lambda *a: pytest.fail("must not type"))
    assert not ses.puede_enviar(cli)["puede"]
    assert ses.send_to_session(cli, "mensaje", [])[0] == 409


def test_process_incarnation_is_passed_to_injector_and_recycled_pid_rejects(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ses.procs, "creation_filetime", lambda pid: 123)
    monkeypatch.setattr(
        ses.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0, stdout='{"ok":true}'),
    )
    assert ses.run_send(cli, "hola")[0] == 200
    assert calls[0][calls[0].index("--expected-start") + 1] == "123"
    monkeypatch.setattr(ses.procs, "creation_filetime", lambda pid: 124)
    assert ses.run_send(cli, "hola")[0] == 409
    assert len(calls) == 1


def test_receipt_requires_new_matching_user_turn(cli, monkeypatch):
    monkeypatch.setattr(ses, "run_send", lambda *a: (200, {"ok": True}))
    ses.send_to_session(cli, "hola", [])
    receipt = cli["envio_codex"]
    for offset, message, expected in [(-10, "hola", "encolado"), (1, "otro", "encolado"), (1, "hola", "entregado")]:
        started = dt.datetime.fromtimestamp(receipt["at"] + offset, dt.UTC).isoformat()
        ses.apply_turn_unhooked(cli, {"id": "new-turn", "prompt": message, "ts_start": started, "ended": False})
        assert receipt["estado"] == expected
    assert cli["sent_mark"] is None and cli["envio_pendiente"] is None


def test_same_120_character_prefix_is_not_delivery(cli, monkeypatch):
    monkeypatch.setattr(ses, "run_send", lambda *a: (200, {"ok": True}))
    requested = "x" * 125 + " original"
    ses.send_to_session(cli, requested, [])
    receipt = cli["envio_codex"]
    started = dt.datetime.fromtimestamp(receipt["at"] + 1, dt.UTC).isoformat()
    turn = {"id": "new", "prompt": "x" * 125 + " diferente", "ts_start": started, "ended": False}
    ses.apply_turn_unhooked(cli, turn)
    assert receipt["estado"] == "encolado"
    ses.apply_turn_unhooked(cli, {**turn, "prompt": requested})
    assert receipt["estado"] == "entregado"


def test_uncertain_write_is_not_replayed(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ses, "run_send", lambda *a: calls.append(a) or (500, {"ok": False, "error": "partial input"}))
    assert ses.send_to_session(cli, "hola", [])[0] == 500
    assert ses.send_to_session(cli, "hola", [])[1]["estado"] == "sin_confirmacion"
    assert len(calls) == 1


def test_unicode_message_is_preserved_in_attachment(cli, monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(ses, "ADJUNTOS", str(tmp_path / "attachments"))
    typed = []
    monkeypatch.setattr(ses, "run_send", lambda s, text: typed.append(text) or (200, {"ok": True}))
    original = "revisión 🙂\nsegunda línea"
    assert ses.send_to_session(cli, original, [])[0] == 200
    assert typed[0].startswith(ses.ATTACH_WRAPPER)
    assert not any(ord(ch) > 0xFFFF for ch in typed[0])
    path = typed[0].split("Adjunto: ", 1)[1]
    assert Path(path).read_text(encoding="utf-8") == original


def test_native_rejects_unrepresentable_text_before_any_input(monkeypatch):
    from test_send import consola

    events = consola(monkeypatch, [])
    assert not send.inject(123, "hola 🙂")["ok"]
    assert not events


@pytest.mark.parametrize("alive", [False, True])
def test_native_guard_checks_owner_before_console_write(monkeypatch, alive):
    from test_send import consola

    events = consola(monkeypatch, [])
    monkeypatch.setattr(send.k32, "GetConsoleProcessList", lambda members, size: _members(members), raising=False)
    result = send._inject(123, "hola", enter_presses=0, owner_alive=lambda: alive)
    assert result["ok"] is alive
    assert any(event[0] == "write" for event in events) is alive


def _members(members):
    members[0] = 123
    return 1


def test_native_guard_rejects_shared_console(monkeypatch):
    from test_send import consola

    events = consola(monkeypatch, [])

    def members(array, size):
        array[0], array[1] = 123, 456
        return 2

    monkeypatch.setattr(send.k32, "GetConsoleProcessList", members, raising=False)
    assert not send._inject(123, "hola", owner_alive=lambda: True)["ok"]
    assert not any(event[0] == "write" for event in events)


def test_owner_dying_after_text_prevents_enter(monkeypatch):
    from test_send import consola

    events = consola(monkeypatch, [0])
    alive = iter([True, False])
    monkeypatch.setattr(send.k32, "GetConsoleProcessList", lambda members, size: _members(members), raising=False)
    assert not send._inject(123, "hola", owner_alive=lambda: next(alive))["ok"]
    assert ("write", "hola") in events and ("write", "\r") not in events


@pytest.mark.parametrize("actual_start", [123, 124])
def test_pinned_process_checks_creation_and_closes_handle(monkeypatch, actual_start):
    closed, calls = [], []

    def times(handle, created, *args):
        created._obj.dwLowDateTime = actual_start
        return True

    monkeypatch.setattr(send.procinfo, "open_process", lambda *a: 99)
    monkeypatch.setattr(send.procinfo, "close_handle", closed.append)
    monkeypatch.setattr(send.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(send.k32, "GetProcessTimes", times)
    monkeypatch.setattr(send.k32, "WaitForSingleObject", lambda *args: 258)
    monkeypatch.setattr(send, "_inject", lambda *a, **kw: calls.append(kw["owner_alive"]()) or {"ok": True})
    assert send.inject(123, "hola", expected_start=123)["ok"] is (actual_start == 123)
    assert closed == [99]
    assert calls == ([True] if actual_start == 123 else [])
