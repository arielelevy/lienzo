"""Ningun test barre el tmux de verdad: en una PC con WSL, backend.sweep() sumaria los panes reales y
las pruebas del barrido contarian tarjetas que no armaron. La fuente tmux se prueba con tmux
mockeado (test_backend_tmux.py) o a mano (tmux_smoke.py)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import backend


@pytest.fixture(autouse=True)
def _sin_tmux_real(monkeypatch):
    monkeypatch.setattr(backend, "HAS_TMUX", False)


@pytest.fixture(autouse=True)
def _restaurar_en_tmp(tmp_path, monkeypatch):
    """Ningun test toca el ~/.lienzo/restaurar.json de verdad: sessions.drop_session y el barrido lo
    escriben solos. test_restore.py usa este mismo archivo temporal."""
    import restore

    monkeypatch.setattr(restore, "path", lambda: str(tmp_path / "restaurar.json"))
    restore._last_live.clear()


@pytest.fixture(autouse=True)
def _sin_estado_real(tmp_path, monkeypatch):
    """Ninguna prueba lee ni escribe el ~/.lienzo ni el ~/.coda de verdad (medido el 2026-10-04: las
    de health leian el config.json real y salian a la red con un git ls-remote; las de launch veian
    la cuota real de coda; y el log de pytest terminaba en el lienzo.log de la PC). CODA_HOME y
    LIENZO_HOME apuntan a carpetas temporales vacias, el log va a un archivo temporal, y las caches
    de health arrancan limpias."""
    import health
    import state

    monkeypatch.setenv("CODA_HOME", str(tmp_path / "coda-home"))
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path / "lienzo-home"))
    monkeypatch.setattr(state, "LOG", str(tmp_path / "lienzo.log"))
    monkeypatch.setattr(state, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(state.links, "path", str(tmp_path / "links.json"))
    monkeypatch.setattr(state.rules, "path", str(tmp_path / "rules.json"))
    monkeypatch.setattr(state.links, "items", [])
    monkeypatch.setattr(state.rules, "items", [])
    for cache in ("_cuota", "_git", "_temp"):
        c = getattr(health, cache, None)
        if c is not None and hasattr(c, "limpiar"):
            c.limpiar()
