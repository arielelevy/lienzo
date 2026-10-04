"""Fase 0 del plan de refactor del 2026-10-04 (docs/plan-refactor-2026-10-04.md), lo de seguridad
y procesos: subproc.correr (0.5) y lo que cambia en el server (0.2, 0.3, 0.7, 0.11 y S8-S17)."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import subproc

PY = sys.executable


def test_correr_devuelve_salida_codigo_y_entrada():
    rc, out, err = subproc.correr(
        [PY, "-c", "import sys; d = sys.stdin.read(); print(d.upper()); sys.stderr.write('e'); sys.exit(3)"],
        entrada="hola ñ",
        env={"PYTHONIOENCODING": "utf-8"},
        timeout=20,
    )
    assert rc == 3 and out.strip() == "HOLA Ñ" and err == "e"


def test_correr_sin_entrada_no_hereda_stdin():
    rc, out, _ = subproc.correr([PY, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout=20)
    assert rc == 0 and out.strip() == "''"


def test_correr_mata_el_arbol_al_vencer_y_no_se_cuelga():
    """El caso del Git Credential Manager: un nieto que hereda la salida y no termina. Con
    tuberías la lectura quedaba colgada aunque el hijo muriera; con archivos y el árbol muerto,
    vuelve apenas vence el plazo."""
    nieto = "import time; time.sleep(60)"
    hijo = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {nieto!r}]); print('arranco', flush=True); time.sleep(60)"
    t0 = time.monotonic()
    rc, out, err = subproc.correr([PY, "-c", hijo], timeout=1.5)
    assert time.monotonic() - t0 < 15
    assert rc == subproc.VENCIDO
    assert "arranco" in out and "no termino" in err


def test_correr_con_un_programa_que_no_existe_no_levanta():
    rc, out, err = subproc.correr(["no-existe-este-programa-lienzo"], timeout=5)
    assert rc == subproc.NO_ARRANCO and out == "" and "no se pudo lanzar" in err


def test_correr_sin_prompts_apaga_las_preguntas_de_git():
    codigo = "import os; print(os.environ.get('GIT_TERMINAL_PROMPT'), os.environ.get('GCM_INTERACTIVE'))"
    assert subproc.correr([PY, "-c", codigo], timeout=20, sin_prompts=True)[1].split() == ["0", "never"]
