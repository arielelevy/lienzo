"""Limpieza de <LIENZO_HOME>/launch/ al lanzar (2026-10-22: 288 .cmd acumulados, nunca se borraban).

Sólo los .cmd/.json de nombre propio con más de 7 días; nunca el del lanzamiento en curso ni otro
archivo de la carpeta.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401
import launch
import state as st

DIA = 86400


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / ".lienzo"))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: None)
    d = tmp_path / ".lienzo" / "launch"
    d.mkdir(parents=True)
    return d


def archivo(d, nombre, dias):
    ruta = d / nombre
    ruta.write_text("x", encoding="utf-8")
    viejo = time.time() - dias * DIA
    os.utime(ruta, (viejo, viejo))
    return ruta


def test_al_lanzar_se_borran_solo_los_lanzamientos_viejos_propios(carpeta):
    viejos = [archivo(carpeta, "0123456789ab.cmd", 8), archivo(carpeta, "0123456789ab.json", 8)]
    quedan = [
        archivo(carpeta, "aaaaaaaaaaaa.cmd", 6),  # reciente
        archivo(carpeta, "aaaaaaaaaaaa.json", 6),
        archivo(carpeta, "11111111-2222-4333-8444-555555555555.claude-settings.json", 30),  # claude_pipe
        archivo(carpeta, "ABCDEF012345.cmd", 30),  # no lo escribe token_hex
        archivo(carpeta, "notas.txt", 30),
        archivo(carpeta, "0123456789ab.cmd.bak", 30),
    ]
    res = launch._launch_cmd(str(carpeta.parent), "t", sys.executable, [], agent="codex")
    assert not any(p.exists() for p in viejos)
    assert all(p.exists() for p in quedan)
    assert os.path.isfile(res["cmd_path"]) and os.path.isfile(os.path.splitext(res["cmd_path"])[0] + ".json")


def test_el_lanzamiento_en_curso_no_se_borra_aunque_parezca_viejo(carpeta):
    en_curso = [archivo(carpeta, "fedcba987654.cmd", 30), archivo(carpeta, "fedcba987654.json", 30)]
    otro = archivo(carpeta, "000000000000.cmd", 30)
    assert launch._limpiar_viejos(str(carpeta), "fedcba987654") == 1
    assert all(p.exists() for p in en_curso) and not otro.exists()


def test_carpeta_ausente_o_archivo_trabado_no_frenan(carpeta, monkeypatch):
    assert launch._limpiar_viejos(str(carpeta / "no-existe"), "x") == 0
    archivo(carpeta, "0123456789ab.cmd", 8)

    def trabado(path):
        raise PermissionError("en uso")

    monkeypatch.setattr(launch.os, "remove", trabado)
    assert launch._limpiar_viejos(str(carpeta), "x") == 0
