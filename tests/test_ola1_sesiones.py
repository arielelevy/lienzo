"""Fase 1 del plan de refactor (docs/plan-refactor-2026-10-04.md), parte sessions/state: errores que
se perdian en silencio y escrituras que no respetaban la regla del lock. Cada prueba reproduce el
caso que el plan describe antes de que se arreglara."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# `from lienzo import server` agrega lienzo/ al sys.path y engancha rules a sessions (ver test_server)
from lienzo import server  # noqa: F401
import sessions as ses
import state as st


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp, sin SSE; el log queda en una lista para mirarlo."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    logs: list[str] = []
    monkeypatch.setattr(st, "log", logs.append)
    st.sessions.clear()
    st.transcript_stat.clear()
    yield logs
    st.sessions.clear()
    st.transcript_stat.clear()


def esperar(cond, s=2.0) -> bool:
    fin = time.monotonic() + s
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# 1.1 excepciones de los hilos ------------------------------------------------------------------


def test_en_hilo_manda_el_traceback_al_log(aislado):
    def rompe(x):
        raise ValueError(f"se rompio {x}")

    t = ses.en_hilo(rompe, 7)
    t.join(2)
    assert any("Traceback" in m and "se rompio 7" in m and "rompe" in m for m in aislado)


def test_el_cierre_de_turno_que_falla_queda_en_el_log(aislado, monkeypatch):
    """Antes el hilo de on_turn_end moria y el traceback iba a stderr, no a lienzo.log."""

    def rompe(sid):
        raise RuntimeError("regla rota")

    monkeypatch.setattr(ses, "on_turn_end", rompe)
    s = ses.new_session("a" * 8, "claude", "hook")
    s["state"] = "corriendo"
    ses.set_state(s, "termino")
    assert esperar(lambda: any("regla rota" in m for m in aislado))


def test_un_gancho_sin_cablear_avisa_una_sola_vez(aislado):
    gancho = ses._gancho_sin_cablear("on_prueba")
    gancho("x")
    gancho("y", "z")
    assert len([m for m in aislado if "on_prueba" in m]) == 1
