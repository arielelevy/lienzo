"""El proyecto de una tarjeta sale de su carpeta; una raíz de disco no se ve como «?» (2026-10-22)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lienzo"))

import state


def test_carpeta_comun_usa_su_nombre():
    assert state.repo_of("D:/Apps/lienzo") == "lienzo"
    assert state.repo_of("D:\\Apps\\lienzo\\") == "lienzo"


def test_raiz_de_disco_muestra_la_ruta_en_vez_de_signo():
    assert state.repo_of("D:\\") == "D:\\"
    assert state.repo_of("C:/") == "C:/"


def test_ruta_sin_nombre_se_corta_a_20():
    assert state.repo_of("\\\\servidor-con-nombre-largo\\") == "\\\\servidor-con-nombr"[:20]
    assert len(state.repo_of("/" * 30)) <= 20


def test_sin_carpeta_sigue_el_signo():
    assert state.repo_of(None) == "?"
    assert state.repo_of("") == "?"
