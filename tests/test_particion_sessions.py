"""La particion de sessions.py (plan del frente F, 2026-10-21): lo movido vive en un solo lugar, los
modulos importan en cualquier orden y sessions no usa a los modulos nuevos al importarse."""

import ast
import subprocess
import sys
from pathlib import Path

import hooks_eventos
import pytest
import sessions

LIENZO = Path(__file__).resolve().parent.parent / "lienzo"
NUEVOS = ("hooks_eventos",)


def _definidos_arriba(path: Path) -> set[str]:
    """Lo que el modulo define arriba de todo: funciones, clases y asignaciones (constantes y estado)."""
    out = set()
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                out.update(x.id for x in ast.walk(t) if isinstance(x, ast.Name))
    return out


@pytest.mark.parametrize("nuevo", NUEVOS)
def test_lo_movido_no_quedo_en_sessions(nuevo):
    """Ni funciones ni estado (`_aplicados`, `CODA_VIVO`) en los dos lados: dos copias divergen."""
    assert _definidos_arriba(LIENZO / f"{nuevo}.py") & _definidos_arriba(LIENZO / "sessions.py") == set()


def test_server_sigue_importando_de_sessions_lo_que_salio():
    assert sessions.consume_events is hooks_eventos.consume_events
    assert sessions.coda_vivo_en_turno is hooks_eventos.coda_vivo_en_turno
    with pytest.raises(AttributeError):
        sessions.apply_event  # noqa: B018 - las pruebas y el codigo van a hooks_eventos


def test_sessions_no_usa_los_modulos_nuevos_al_importarse():
    """Si sessions leyera `hooks_eventos.X` arriba de todo (un default, un decorador, una tabla), el
    import que empieza por hooks_eventos (rules.py lo hace) cae con un modulo a medio inicializar."""
    arbol = ast.parse((LIENZO / "sessions.py").read_text(encoding="utf-8"))
    en_cuerpos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for hijo in nodo.body if isinstance(nodo.body, list) else [nodo.body]:
                en_cuerpos.update(map(id, ast.walk(hijo)))
    afuera = [
        n.lineno
        for n in ast.walk(arbol)
        if isinstance(n, ast.Name) and n.id in NUEVOS and isinstance(n.ctx, ast.Load) and id(n) not in en_cuerpos
    ]
    assert afuera == []
    desde_nuevos = [
        n.lineno
        for n in arbol.body
        if isinstance(n, ast.ImportFrom) and (n.module or "").removeprefix("lienzo.") in NUEVOS
    ]
    assert desde_nuevos == []  # `from hooks_eventos import X` arriba de sessions tambien rompe el ciclo


@pytest.mark.parametrize("orden", [["sessions"], ["hooks_eventos"], ["rules"], ["server"]])
def test_importa_en_cualquier_orden(orden):
    codigo = (
        f"import sys; sys.path.insert(0, {str(LIENZO)!r})\n"
        + "".join(f"import {m}\n" for m in orden)
        + "import sessions, hooks_eventos\n"
        "assert sessions.consume_events is hooks_eventos.consume_events\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", codigo],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert r.returncode == 0, r.stderr[-2000:]
