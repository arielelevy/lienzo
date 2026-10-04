"""Cuota de los agentes por PC (pedido de Ariel, 2026-10-04): coda por su log y su base, sin gastar
tokens; claude, codex y pi por el limite de uso vigente de sus tarjetas."""

import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import health
import launch
import sessions as ses
import state as st


def _coda(tmp_path, error_iso=None, uso_ms=None):
    (tmp_path / "logs").mkdir()
    lineas = []
    if error_iso:
        lineas.append(json.dumps({"time": error_iso, "error": "Quota exceeded (code 154)", "msg": "stream error"}))
    (tmp_path / "logs" / "coda.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    con = sqlite3.connect(tmp_path / "coda.db")
    con.execute("CREATE TABLE usage (id TEXT, session_id TEXT, model TEXT, created_at INTEGER)")
    if uso_ms:
        con.execute("INSERT INTO usage VALUES ('u', 's', 'm', ?)", (uso_ms,))
    con.commit()
    con.close()


def test_clasificar_cuota():
    assert health.clasificar_cuota(None, None) == "desconocida"
    assert health.clasificar_cuota(200.0, 100.0) == "agotada"
    assert health.clasificar_cuota(100.0, 200.0) == "ok"
    assert health.clasificar_cuota(None, 200.0) == "ok"


def test_coda_agotada_si_el_error_es_mas_nuevo_que_el_ultimo_uso(tmp_path, monkeypatch):
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    uso = dt.datetime(2026, 10, 4, 2, 0, tzinfo=dt.UTC)
    _coda(tmp_path, error_iso="2026-10-04T05:29:14.109Z", uso_ms=int(uso.timestamp() * 1000))
    assert health._medir_cuota() == "agotada"


def test_launch_de_coda_sin_cuota_da_409(monkeypatch):
    monkeypatch.setattr(launch, "_cuota_coda", lambda: "agotada")
    res = launch.launch("D:/x", "t", "coda")
    assert res["ok"] is False and res["code"] == 409 and "cuota" in res["error"]


def test_cuotas_de_sesiones_toma_el_limite_vigente(monkeypatch):
    futuro = (dt.datetime.now().astimezone() + dt.timedelta(hours=2)).isoformat(timespec="seconds")
    monkeypatch.setattr(
        st,
        "sessions",
        {
            "a": {"session_id": "a", "agent": "claude", "alive": True, "limit_until": futuro},
            "b": {
                "session_id": "b",
                "agent": "codex",
                "alive": True,
                "limit_until": None,
                "last_error": "You've hit your usage limit",
            },
            "c": {"session_id": "c", "agent": "pi", "alive": True},
        },
    )
    monkeypatch.setattr(ses, "sessions", st.sessions)
    out = ses.cuotas_de_sesiones()
    assert out["claude"].startswith("agotada hasta ") and out["codex"] == "agotada" and "pi" not in out
