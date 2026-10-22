"""/status vuelve a servir tras /new o /clear, sin teclear de más (2026-10-22, PID 35236).

Antes la consulta se tecleaba una sola vez por proceso: al minuto devolvía None para siempre y,
después de /new, el único camino que quedaba era el nombre del pie.
"""

import json
from types import SimpleNamespace

import codex_status as status
import pytest

A = "01a16197-8978-77a0-b8df-6edb31ba1a0e"
B = "01a16199-0952-7e22-ad20-3020b2dc399b"


@pytest.fixture
def tui(monkeypatch):
    status._cache.clear()
    status._running.clear()
    getattr(status, "_estado", {}).clear()  # no existe antes del arreglo: el rojo es de conducta
    view = {"clock": 0, "open": frozenset(), "thread": A, "tecleo": True, "calls": 0}
    monkeypatch.setattr(status.procinfo, "_WIN", True)
    monkeypatch.setattr(status.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(status.procs, "creation_filetime", lambda pid: 123)
    monkeypatch.setattr(status.time, "monotonic", lambda: view["clock"])
    monkeypatch.setattr(status, "rollout", lambda sid: f"rollout-{sid}.jsonl")
    monkeypatch.setattr(status, "_rollouts", lambda pid: view["open"], raising=False)

    def run(*a, **kw):
        view["calls"] += 1
        typed = view["tecleo"]
        answer = {"thread": view["thread"] if typed else None, "tecleo": typed}
        return SimpleNamespace(returncode=0, stdout=json.dumps(answer))

    monkeypatch.setattr(status.subprocess, "run", run)
    yield view
    status._cache.clear()
    status._running.clear()
    getattr(status, "_estado", {}).clear()


def at(view, tick):
    view["clock"] = tick
    return status.discover(42)


def test_new_rollout_allows_one_more_status_and_finds_the_new_thread(tui):
    tui["open"] = frozenset({"A"})
    assert at(tui, 0)["thread"] == A
    assert at(tui, 61) is None and tui["calls"] == 1  # mismo inventario: no se teclea de nuevo
    tui["open"], tui["thread"] = frozenset({"A", "B"}), B  # /new y su primer turno
    assert at(tui, 62)["thread"] == B and tui["calls"] == 2
    for tick in (63, 200, 3600):
        at(tui, tick)
    assert tui["calls"] == 2


def test_closed_rollout_or_unknown_inventory_never_types_again(tui):
    tui["open"] = frozenset({"A", "B"})
    at(tui, 0)
    tui["open"] = frozenset({"B"})
    at(tui, 100)
    tui["open"] = None  # handles ilegibles
    at(tui, 200)
    assert tui["calls"] == 1


def test_busy_console_keeps_the_permission_and_retries_slowly(tui):
    tui["open"] = frozenset({"A"})
    at(tui, 0)
    tui["open"], tui["thread"], tui["tecleo"] = frozenset({"A", "B"}), B, False  # TUI ocupada
    assert at(tui, 100) is None and tui["calls"] == 2
    assert at(tui, 105) is None and tui["calls"] == 2  # antes de REINTENTO_S no hay otro intento
    tui["tecleo"] = True
    assert at(tui, 100 + status.REINTENTO_S)["thread"] == B and tui["calls"] == 3
    at(tui, 500)
    assert tui["calls"] == 3


def test_first_query_without_inventory_learns_a_base_without_typing(tui):
    tui["open"] = None
    at(tui, 0)
    tui["open"] = frozenset({"A"})
    at(tui, 100)  # aprende la base, no teclea
    assert tui["calls"] == 1
    tui["open"], tui["thread"] = frozenset({"A", "B"}), B
    assert at(tui, 200)["thread"] == B and tui["calls"] == 2


def test_console_reports_whether_it_typed(monkeypatch):
    import screen
    import send

    monkeypatch.setattr(status.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(status.procs, "creation_filetime", lambda pid: 123)
    monkeypatch.setattr(status.time, "sleep", lambda _: None)
    busy = {"ok": True, "lines": ["• Working (2s • esc to interrupt)", "", "›", "", "GPT", "? for shortcuts"]}
    monkeypatch.setattr(screen, "read_screen", lambda pid: busy)
    monkeypatch.setattr(send, "inject", lambda *a, **kw: pytest.fail("no debe teclear"))
    info = {"tecleo": False}
    assert status.query_console(42, 123, info) is None and info == {"tecleo": False}
