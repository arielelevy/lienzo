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
