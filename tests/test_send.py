"""El Enter no se encola con texto pendiente; ninguna prueba toca una consola real."""

import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":
    pytest.skip("inyeccion Win32", allow_module_level=True)

import send


def consola(monkeypatch, pending):
    events = []
    pending = iter(pending)

    def write(_hin, records, count, written):
        written._obj.value = count
        events.append(
            ("write", "".join(r.Event.KeyEvent.uChar.UnicodeChar for r in records if r.Event.KeyEvent.bKeyDown))
        )
        return True

    def queued(_hin, count):
        count._obj.value = next(pending)
        events.append(("pending", count._obj.value))
        return True

    monkeypatch.setattr(
        send,
        "k32",
        SimpleNamespace(
            FreeConsole=lambda: True,
            AttachConsole=lambda _pid: True,
            CreateFileW=lambda *args: 42,
            CloseHandle=lambda _hin: True,
            WriteConsoleInputW=write,
            GetNumberOfConsoleInputEvents=queued,
        ),
    )
    monkeypatch.setattr(send.procs, "alive", lambda _pid: True)
    monkeypatch.setattr(send.procs, "is_tui", lambda _pid: True)
    monkeypatch.setattr(send.procs, "image_path", lambda _pid: "codex.exe")
    monkeypatch.setattr(send.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    return events


def test_codex_enter_espera_texto_consumido_y_reposo(monkeypatch):
    events = consola(monkeypatch, [4, 0])
    assert send.inject(123, "hola")["ok"]
    enter = events.index(("write", "\r"))
    assert events.index(("pending", 0)) < events.index(("sleep", 1.0)) < enter
    assert sum(e == ("write", "\r") for e in events) == 1


def test_codex_no_confirma_si_no_consume_texto(monkeypatch):
    events = consola(monkeypatch, [4])
    clock = iter([0, 11])
    monkeypatch.setattr(send.time, "monotonic", lambda: next(clock))
    result = send.inject(123, "hola")
    assert result["ok"] is False
    assert "Enter no enviado" in result["error"]
    assert ("write", "\r") not in events


def test_no_enter_no_consulta_cola_ni_publica(monkeypatch):
    events = consola(monkeypatch, [])
    assert send.inject(123, "hola", enter_presses=0)["ok"]
    assert not any(e[0] == "pending" or e == ("write", "\r") for e in events)


def test_enter_de_dialogo_no_espera_consumo_de_texto(monkeypatch):
    events = consola(monkeypatch, [])
    assert send.inject(123, "", key="enter")["ok"]
    assert events == [("write", "\r")]
