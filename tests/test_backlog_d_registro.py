import json

import pytest
import registro_niveles as registro
from tools import rtk


def test_pasos_sin_crudo_y_sin_inventar_tiempos(monkeypatch):
    page = {
        "turns": [
            {
                "id": "turn-1",
                "blocks": [
                    {"kind": "text", "text": "PRIVADO"},
                    {
                        "kind": "tool",
                        "name": "read",
                        "input": {"path": "PRIVADO"},
                        "result": {"text": "PRIVADO", "is_error": True},
                    },
                    {"kind": "tool", "name": "git", "input": {"token": "PRIVADO"}},
                ],
            }
        ],
        "has_more": True,
    }
    monkeypatch.setattr(registro.transcripts, "turns", lambda *a, **kw: page)
    monkeypatch.setattr(registro.transcripts, "leaf_of", lambda s: None)
    result = registro.herramientas({"session_id": "s", "agent": "codex", "transcript_path": "fixture"})
    assert [p["paso"] for p in result["pasos"]] == [1, 2]
    assert result["pasos"][0]["error"] is True
    assert result["pasos"][1]["error"] is None
    assert result["pasos"][1]["caracteres"] is None
    assert all(p["duracion_s"] is None for p in result["pasos"])
    assert result["hay_mas"] is True
    assert "PRIVADO" not in json.dumps(result)
    limited = registro.herramientas({"session_id": "s", "agent": "codex", "transcript_path": "fixture"}, limite=1)
    assert limited["omitidos"] == 1 and limited["pasos"][0]["paso"] == 2


def test_ausencia_y_limite():
    assert registro.herramientas({})["disponible"] is False
    with pytest.raises(ValueError):
        registro.herramientas({}, limite=0)


def test_externo_solo_agregados_sqlite(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import contextmanager

    db = tmp_path / "backlog_d.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE nodo (proyecto, tipo, estado, texto)")
        con.executemany(
            "INSERT INTO nodo VALUES (?,?,?,?)",
            [
                ("app", "hallazgo", "propuesto", "PRIVADO"),
                ("app", "sesion", "viva", "PRIVADO"),
                ("otra", "hallazgo", "vigente", "PRIVADO"),
            ],
        )

    @contextmanager
    def abrir(pid):
        with sqlite3.connect(db) as con:
            con.row_factory = sqlite3.Row
            yield con

    monkeypatch.setattr(registro.k, "_abrir", abrir)
    assert registro.externo("app") == {
        "nivel": 3,
        "proyecto": "app",
        "actividad": [{"tipo": "hallazgo", "estado": "propuesto", "cantidad": 1}],
    }
    assert registro.externo("ausente")["actividad"] == []
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM nodo").fetchone()[0] == 3


def test_rtk_base_comun(monkeypatch):
    monkeypatch.setattr(rtk, "ruta", lambda distro: "C:/rtk.exe")
    text, error = rtk._instruccion("codex", None)
    assert error is None
    for command in ("rtk read", "rtk rg", "rtk find", "rtk git", "rtk recall"):
        assert command in text
