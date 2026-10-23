"""Regresiones del encargo U: decisiones 5 y 24 y reparación de marcas antiguas."""

import datetime as dt
import json

import conocimiento as k
import emergencia
import federation
import mirror
import pytest
import registro_niveles
import sessions


def _crudo(monkeypatch, rows):
    for project in {p for p, _, _ in rows}:
        k.registrar_proyecto(project, project, [], [])
    for i, (project, date, size) in enumerate(rows):
        monkeypatch.setattr(k, "ahora", lambda date=date: date)
        k.capturar(project, "pedido", str(i) * size, {"session_id": "u", "agent": "claude"})


def test_retencion_respeta_cursor_por_proyecto(tmp_path, monkeypatch):
    monkeypatch.setattr(k, "db_path", lambda: str(tmp_path / "crudo.db"))
    cursor = tmp_path / "research" / "creencias-cursor.json"
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({"leido": {"capturas_hasta": "2026-09-10T09:00:00-03:00"}}), encoding="utf-8")
    monkeypatch.setattr(k.state, "LIENZO", str(tmp_path))
    _crudo(
        monkeypatch,
        [
            ("leido", "2026-09-10T11:59:59.999Z", 10),
            ("leido", "2026-09-10T12:00:00.000Z", 20),
            ("leido", "2026-09-10T12:00:00.001Z", 30),
            ("sin_cursor", "2026-09-01T00:00:00.000Z", 40),
            ("sin_cursor", "2026-10-22T00:00:00.000Z", 50),
        ],
    )
    result = registro_niveles._depurar_capturas(dt.datetime(2026, 9, 22, tzinfo=dt.UTC))
    with k._Conexion(k.db_path()) as con:
        assert [r[0] for r in con.execute("SELECT bytes FROM captura ORDER BY rowid")] == [30, 40, 50]
    assert result["filas"] == 2 and result["bytes"] == 30 and result["quedan"] == 3


def test_sin_ningun_cursor_no_borra_crudo(tmp_path, monkeypatch):
    monkeypatch.setattr(k, "db_path", lambda: str(tmp_path / "crudo.db"))
    monkeypatch.setattr(k.state, "LIENZO", str(tmp_path))
    _crudo(monkeypatch, [("sin_cursor", "2026-08-01T00:00:00.000Z", 10)] * 2)
    result = registro_niveles._depurar_capturas(dt.datetime(2026, 9, 22, tzinfo=dt.UTC))
    assert result["filas"] == 0 and result["quedan"] == 2


@pytest.mark.parametrize("hasta", ["fecha rota", "2026-09-10T12:00:00"])
def test_cursor_invalido_no_borra_crudo(tmp_path, monkeypatch, hasta):
    monkeypatch.setattr(k, "db_path", lambda: str(tmp_path / "crudo.db"))
    cursor = tmp_path / "research" / "creencias-cursor.json"
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({"app": {"capturas_hasta": hasta}}), encoding="utf-8")
    monkeypatch.setattr(k.state, "LIENZO", str(tmp_path))
    _crudo(monkeypatch, [("app", "2026-08-01T00:00:00.000Z", 10)] * 2)
    result = registro_niveles._parte(registro_niveles._depurar_capturas, dt.datetime(2026, 9, 22, tzinfo=dt.UTC))
    assert "error" in result
    with k._Conexion(k.db_path()) as con:
        assert con.execute("SELECT COUNT(*) FROM captura").fetchone()[0] == 2


@pytest.mark.parametrize(
    "health,canal",
    [
        ({"emergencia": {"tailscale": None, "tailchrome": True}}, "tailchrome"),
        (None, "tailscale"),
    ],
)
def test_pc_caida_desde_arranque_ofrece_emergencia(monkeypatch, health, canal):
    m = mirror.Mirror()
    pm = mirror._PeerMirror(
        "oficina", {"name": "ar-it33940"}, federation.PeerConn("192.168.1.63", 7322, b"k" * 32, "yo")
    )
    pm.diagnostico = "la PC cambió de red"
    pm.health = health
    m._peers["oficina"] = pm
    monkeypatch.setattr(emergencia, "propia", lambda: {"tailscale": "100.81.147.100", "tailchrome": True})
    row = m.peers_status()[0]
    assert row["alive"] is False and row["last_seen"] is None
    assert row["emergencia"]["canal"] == canal
    assert "ar-it33940" in row["emergencia"]["texto"]


@pytest.mark.parametrize(
    "command,external,expected",
    [
        ("claude.exe --model opus", None, True),
        ("claude.exe -p hola", {"kind": "batch", "via": "comando"}, False),
        ("claude.exe --print hola", {"kind": "batch", "via": "comando"}, False),
        (None, None, False),
        ("claude.exe --model opus", {"kind": "orquestador", "via": "proceso"}, False),
    ],
)
def test_barrido_limpia_solo_batch_viejo_interactivo(tmp_path, monkeypatch, command, external, expected):
    monkeypatch.setattr(sessions.state, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(sessions.state, "broadcast", lambda ev: None)
    logs = []
    monkeypatch.setattr(sessions.state, "log", logs.append)
    monkeypatch.setattr(sessions, "sessions", {})
    card = sessions.new_session("u", "claude", "hook")
    card.update(pid=123, external={"kind": "batch", "via": "comando"}, no_console=True, transcript_path="u.jsonl")
    sessions.sessions["u"] = card
    observed = {"pid": 123, "agent": "claude", "external": external, "no_console": False}
    monkeypatch.setattr(sessions.backend, "sweep", lambda: [observed])
    monkeypatch.setattr(sessions, "adopt_desktop_threads", lambda: None)
    monkeypatch.setattr(sessions.procs.procinfo, "command_line", lambda pid: command)
    sessions.sweep_once()
    assert (card["external"] is None) is expected
    assert card["no_console"] is (not expected)
    assert bool(logs) is expected
    if expected:
        assert sessions.external_blocked(card) is None
        assert json.loads((tmp_path / "u.json").read_text(encoding="utf-8"))["external"] is None
