"""`frentes` encuentra las tarjetas con el título que deja el server y `lanzar_y_titular` cablea con `solo_si`.

Pedido de la coordinadora de openSeec (2026-10-30): las tarjetas pasan a «openseec | encargo X»
(`work_titles.project_title`) y `frentes()` buscaba sólo « - encargo »; y las reglas que crea
`lanzar_y_titular` no usaban `solo_si="ESTADO:"`, así que los turnos intermedios llegaban como entregas.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def _t(sid, title, **kw):
    return {"session_id": sid, "title": title, "alive": True, "pc": "pcA", **kw}


@pytest.mark.parametrize(
    "titulo",
    [
        "openSeec - encargo F - mejoras de uso",
        "openseec | encargo F - mejoras de uso",
        "openseec | encargo F",
        "openseec | encargo F @notebook - mejoras",
        "openseec | encargo F - mejoras · copycat",
    ],
)
def test_frentes_reconoce_el_titulo_viejo_y_el_del_server(monkeypatch, titulo):
    monkeypatch.setattr(c, "sesiones", lambda: [_t("u1", titulo)])
    assert list(c.frentes("openSeec")) == ["F"]


def test_frentes_reconoce_el_proyecto_largo_cortado_al_medio(monkeypatch):
    # work_titles.corto_medio: más de 24 caracteres se corta al medio con «…»
    monkeypatch.setattr(c, "sesiones", lambda: [_t("u1", "cliente-pro…-grande-2026 | encargo B - x")])
    assert list(c.frentes("cliente-proyecto-muy-grande-2026")) == ["B"]


def test_frentes_reconoce_la_letra_con_la_version_de_la_ronda(monkeypatch):
    # openSeec titula `encargo 0.20-F` (2026-10-30): la clave es la letra entera, versión incluida
    titulos = [
        "openseec | encargo 0.20-F - analizar Go",
        "openseec | encargo 0.19-D - prioridad",
        "openseec | encargo G",
    ]
    monkeypatch.setattr(c, "sesiones", lambda: [_t(f"u{i}", t) for i, t in enumerate(titulos)])
    assert sorted(c.frentes("openseec")) == ["0.19-D", "0.20-F", "G"]


@pytest.mark.parametrize(
    "titulo",
    ["openseec | coordinadora - ronda", "openseec2 | encargo F - x", "otro | encargo F - x", "openseec | encargo F1"],
)
def test_frentes_no_confunde_otros_titulos(monkeypatch, titulo):
    monkeypatch.setattr(c, "sesiones", lambda: [_t("u1", titulo)])
    assert c.frentes("openseec") == {}


def test_lanzar_y_titular_cablea_solo_los_turnos_con_estado(monkeypatch):
    c.YO = "coord"
    nueva = {"session_id": "pid-9", "pid": 9, "pc": "pcB", "cwd": r"D:\apps\x", "agent": "coda"}
    vistas = [[], [nueva]]
    monkeypatch.setattr(c, "sesiones", lambda: vistas.pop(0) if len(vistas) > 1 else vistas[0])
    reglas = []
    monkeypatch.setattr(
        c, "pedir", lambda m, r, cuerpo=None, timeout=20: (r == "/rules" and reglas.append(cuerpo)) or (200, {})
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    c.lanzar_y_titular("pcB", r"D:\apps\x", "t", "coda", espera=5)
    assert reglas[-1]["solo_si"] == "ESTADO:"
    vistas[:] = [[], [nueva]]
    c.lanzar_y_titular("pcB", r"D:\apps\x", "t", "coda", espera=5, solo_si=None)
    assert "solo_si" not in reglas[-1]
