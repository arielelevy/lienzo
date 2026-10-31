"""`fichas_en_conflicto`: dos fichas abiertas que nombran el mismo archivo se ven antes de repartir.

Pedido de la coordinadora de openSeec (2026-10-30, fila 15 de su registro de mejoras).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def _ficha(base, nombre, hito, archivos):
    lineas = [f"# {nombre}", f"Hito: {hito}", "## Objetivo", "x", "## Archivos y dueños"]
    lineas += [f"- `{a}`: frente" for a in archivos]
    lineas += ["## Efectos compartidos", "`docs/otro.md` no es un archivo con dueño"]
    (base / f"{nombre}.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def test_dos_fichas_abiertas_con_el_mismo_archivo(tmp_path):
    base = tmp_path / ".temp" / "coordinacion" / "2026-10-30"
    base.mkdir(parents=True)
    _ficha(base, "fdd-a", "diseñado", ["lienzo/launch.py", "tests/test_launch.py"])
    _ficha(base, "encargo-B", "implementado", ["lienzo\\launch.py", "web/src/App.tsx"])
    _ficha(base, "fdd-c", "integrado", ["web/src/App.tsx"])  # cerrada: no cuenta
    (base / "informe-A.md").write_text("`lienzo/launch.py`\n", encoding="utf-8")  # no es ficha
    r = c.fichas_en_conflicto(tmp_path)
    assert r == {
        "lienzo/launch.py": [
            ".temp/coordinacion/2026-10-30/encargo-B.md",
            ".temp/coordinacion/2026-10-30/fdd-a.md",
        ]
    }


def test_sin_fichas_no_hay_conflicto(tmp_path):
    assert c.fichas_en_conflicto(tmp_path) == {}
