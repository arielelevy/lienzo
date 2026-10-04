"""Cuota de los agentes por PC (pedido de Ariel, 2026-10-04): coda por su log y su base, sin gastar
tokens; claude, codex y pi por el limite de uso vigente de sus tarjetas."""

import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
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


def test_el_server_contesta_el_409_de_launch_y_no_un_400(monkeypatch):
    """La revision de DISENO (2026-10-04) encontro que accion_launch contestaba 400 a todo fallo."""
    monkeypatch.setattr(server, "validate_launch", lambda d: ("D:/x", "coda", "t"))
    monkeypatch.setattr(server.launch, "launch", lambda *a, **k: {"ok": False, "code": 409, "error": "coda sin cuota"})
    code, res = server.accion_launch({"cwd": "D:/x", "agent": "coda"}, desde_tablero=True)
    assert code == 409 and res == {"ok": False, "error": "coda sin cuota"}
    monkeypatch.setattr(server.launch, "launch", lambda *a, **k: {"ok": False, "error": "cwd fuera de launch_roots"})
    assert server.accion_launch({"cwd": "D:/x", "agent": "coda"}, desde_tablero=True)[0] == 400


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


def test_coda_viva_solo_con_una_tarjeta_viva_de_coda(monkeypatch):
    monkeypatch.setattr(
        ses, "sessions", {"1": {"alive": False, "agent": "coda"}, "2": {"alive": True, "agent": "claude"}}
    )
    assert ses.coda_viva() is False
    ses.sessions["3"] = {"alive": True, "agent": "coda"}
    assert ses.coda_viva() is True
