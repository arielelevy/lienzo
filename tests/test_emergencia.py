"""Tests de lienzo/emergencia.py (decisión 24 de Ariel, 2026-10-22): cuando un par no responde, la
tira de PCs ofrece el canal de emergencia que haya, Tailscale (anda en ariel) o Tailchrome (anda en
ar-it33940, que no tiene el cliente). Sin red ni registro: los canales propios y los del par se
pasan a mano."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import emergencia as em
import health

ARIEL = {"tailscale": "100.81.147.100", "tailchrome": True}
OFICINA_SOLO_TAILCHROME = {"tailscale": None, "tailchrome": True}
OFICINA_TAILSCALE = {"tailscale": "100.70.1.2", "tailchrome": False}
NADA = {"tailscale": None, "tailchrome": False}


def test_las_dos_con_tailscale_ofrece_tailscale_sin_enlace():
    c = em.canal(ARIEL, OFICINA_TAILSCALE, "oficina")
    assert c["canal"] == "tailscale"
    assert c["url"] is None, "Tailscale conecta solo: no hay página que abrir acá"
    assert "100.70.1.2" in c["texto"] and "oficina" in c["texto"]


def test_desde_ariel_hacia_la_pc_que_solo_tiene_tailchrome():
    """El caso real: ar-it33940 perdió el cliente de Tailscale. El puente se activa allá y apunta a
    la IP de Tailscale de esta PC; el enlace no sirve desde acá (la página sólo atiende localhost)."""
    c = em.canal(ARIEL, OFICINA_SOLO_TAILCHROME, "ar-it33940")
    assert c["canal"] == "tailchrome"
    assert c["url"] is None
    assert "ar-it33940" in c["texto"] and "100.81.147.100" in c["texto"] and "/tailchrome" in c["texto"]


def test_desde_la_pc_con_tailchrome_hacia_la_que_tiene_tailscale_da_el_enlace_local():
    c = em.canal(OFICINA_SOLO_TAILCHROME, ARIEL, "ariel")
    assert c == {
        "canal": "tailchrome",
        "url": "/tailchrome",
        "texto": "Tailchrome: abrí el puente en esta PC hacia ariel (100.81.147.100)",
    }


def test_par_sin_salud_conocida_usa_el_canal_propio():
    assert em.canal(ARIEL, None, "nueva")["canal"] == "tailscale"
    c = em.canal(OFICINA_SOLO_TAILCHROME, None, "nueva")
    assert (c["canal"], c["url"]) == ("tailchrome", "/tailchrome")


def test_dos_pcs_solo_con_extension_no_estan_cubiertas():
    c = em.canal(OFICINA_SOLO_TAILCHROME, OFICINA_SOLO_TAILCHROME, "otra")
    assert c["canal"] is None
    assert "Tailscale" in c["texto"]


def test_sin_ningun_canal_lo_dice():
    c = em.canal(NADA, NADA, "otra")
    assert c == {
        "canal": None,
        "url": None,
        "texto": "sin canal de emergencia: instalá Tailscale en alguna de las dos PCs",
    }


def test_salud_del_par_rota_no_rompe():
    assert em.canal(ARIEL, {"tailscale": 5, "tailchrome": "si"}, "x")["canal"] == "tailscale"
    assert em.canal(NADA, "basura", "x")["canal"] is None  # type: ignore[arg-type]


def test_propia_cachea_y_no_levanta(monkeypatch):
    llamadas = []
    monkeypatch.setattr(em.red, "tailscale_propia", lambda: llamadas.append(1) or "100.1.2.3")

    def sin_helper():
        raise RuntimeError("no hay helper")

    monkeypatch.setattr(em.tailchrome_native, "installed_helper", sin_helper)
    em._cache = (0.0, None)
    assert em.propia(ahora=1000.0) == {"tailscale": "100.1.2.3", "tailchrome": False}
    assert em.propia(ahora=1010.0) == {"tailscale": "100.1.2.3", "tailchrome": False}
    assert llamadas == [1], "se cachea: lo piden la salud y /peers cada 15 s"
    em.propia(ahora=1000.0 + em.CACHE_S + 1)
    assert llamadas == [1, 1]


def test_la_salud_anuncia_los_canales_propios(monkeypatch):
    monkeypatch.setattr(health.emergencia, "propia", lambda: {"tailscale": "100.9.9.9", "tailchrome": False})
    assert health.snapshot()["emergencia"] == {"tailscale": "100.9.9.9", "tailchrome": False}
