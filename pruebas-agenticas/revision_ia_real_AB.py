"""Un veredicto con Claude real sobre evidencia real, aplicado y deshecho en copia aislada.

La memoria en uso se abre mode=ro y se copia con backup SQLite; nunca se le aplican veredictos.
No forma parte de la suite automática (consume una llamada de la suscripción).
"""

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lienzo"))
original = Path.home() / ".lienzo" / "conocimiento.sqlite"
out = ROOT / ".temp/resultados/2026-10-22-AB/ia-real.json"

with tempfile.TemporaryDirectory(prefix="lienzo-AB-12096-real-") as work:
    home = Path(work)
    with (
        closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(home / "conocimiento.sqlite")) as copy,
    ):
        source.backup(copy)
    os.environ["LIENZO_HOME"] = work
    import creencias
    import creencias_revision_ia as r

    (home / "proyectos/lienzo").mkdir(parents=True)
    r.TOPE = 1  # una sola llamada y una sola propuesta; conserva el plazo de producción
    before = {n["id"]: n for n in creencias.listar("lienzo")}
    result = r.revisar("lienzo", "claude")
    assert result["id"] and len(result["items"]) == 1
    undone = r.deshacer("lienzo", result["id"])
    assert undone["items"][0]["deshecho"]
    current = {n["id"]: n for n in creencias.listar("lienzo")}
    nid = result["items"][0]["id"]
    assert current[nid]["datos"] == before[nid]["datos"]
    assert current[nid]["estado"] == before[nid]["estado"]
    out.write_text(
        json.dumps(
            {
                "fuente": "copia consistente de memoria real, fuente mode=ro",
                "tanda": result,
                "deshecha": undone,
                "memoria_en_uso_modificada": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "propuestas": len(result["items"]),
                "accion": result["items"][0]["accion"],
                "deshacer": True,
                "evidencia": str(out),
            },
            ensure_ascii=True,
        )
    )
