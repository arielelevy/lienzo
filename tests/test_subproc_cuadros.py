"""El server apaga los cuadros de error de Windows para sus hijos (git-remote-https 0xc0000142, 2026-10-21)."""

import ast
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lienzo"))

import subproc

AQUI = os.path.dirname(__file__)


@pytest.mark.skipif(sys.platform != "win32", reason="SetErrorMode es de Windows")
def test_hijo_hereda_el_modo_sin_cuadros():
    # en un proceso aparte: no cambiar el modo del proceso de pytest
    codigo = (
        "import sys, ctypes, subprocess; sys.path.insert(0, sys.argv[1]); import subproc;"
        "m = subproc.sin_cuadros_de_error();"
        "hijo = subprocess.run([sys.executable, '-c', 'import ctypes; print(ctypes.windll.kernel32.GetErrorMode())'],"
        " capture_output=True, text=True, creationflags=subproc.CREATE_NO_WINDOW);"
        "print(m, hijo.stdout.strip())"
    )
    r = subprocess.run(
        [sys.executable, "-c", codigo, os.path.join(AQUI, "..", "lienzo")],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stderr
    propio, hijo = (int(x) for x in r.stdout.split())
    assert propio & subproc.SIN_CUADROS == subproc.SIN_CUADROS
    assert int(hijo) & subproc.SEM_FAILCRITICALERRORS


def test_fuera_de_windows_no_hace_nada(monkeypatch):
    monkeypatch.setattr(subproc, "WINDOWS", False)
    assert subproc.sin_cuadros_de_error() is None


def test_main_del_server_lo_llama_antes_de_lanzar_nada():
    with open(os.path.join(AQUI, "..", "lienzo", "server.py"), encoding="utf-8") as f:
        src = f.read()
    main = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    llamadas = [ast.unparse(n.func) for n in ast.walk(main) if isinstance(n, ast.Call)]
    assert "subproc.sin_cuadros_de_error" in llamadas
    assert llamadas.index("subproc.sin_cuadros_de_error") < llamadas.index("ap.parse_args")
