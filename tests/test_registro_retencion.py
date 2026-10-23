"""Nivel 1 del registro: depuración del crudo con la retención de 30 días que fijó Ariel (decisión 5,
2026-10-22). Sólo bases y carpetas temporales."""

import datetime as dt
import os
import sqlite3

import conocimiento as k
import pytest
import registro_niveles as registro
import research_creencias

AHORA = dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.UTC)
# el log se corta por día local: el día del corte depende de la zona horaria de la PC
DIA_CORTE = (AHORA - dt.timedelta(days=30)).astimezone().strftime("%Y-%m-%d")
TARJETA = {"session_id": "s1", "agent": "codex", "pc": "pcA"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    monkeypatch.setattr(k.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(registro.state, "LOG", str(tmp_path / "lienzo.log"))
    monkeypatch.setattr(registro.state, "EVENTS", str(tmp_path / "events"))
    k._sesion_proyecto.clear()
    k._sesion_sin_proyecto.clear()
    k.registrar_proyecto("app", "App", [], [{"pc": "pcA", "cwd": "D:/Apps/app"}])
    yield tmp_path
    k._sesion_proyecto.clear()
    k._sesion_sin_proyecto.clear()


def _captura(monkeypatch, texto, fecha):
    monkeypatch.setattr(k, "ahora", lambda: fecha)
    return k.capturar("app", "pedido", texto, TARJETA)


def _filas():
    with sqlite3.connect(k.db_path()) as con:
        return [r[0] for r in con.execute("SELECT texto FROM captura ORDER BY rowid")]


def test_capturas_viejas_se_borran_y_las_recientes_quedan(home, monkeypatch):
    # T4: la edad sola no habilita borrar. Este caso prueba capturas ya leídas.
    monkeypatch.setattr(research_creencias, "resguardo_capturas", lambda: {"app": AHORA.isoformat()})
    _captura(monkeypatch, "vieja uno", "2026-09-01T10:00:00.000Z")
    _captura(monkeypatch, "vieja dos", "2026-09-22T11:59:59.999Z")
    _captura(monkeypatch, "limite", "2026-09-22T12:00:00.000Z")
    _captura(monkeypatch, "reciente", "2026-10-21T10:00:00.000Z")
    res = registro.depurar_crudo(ahora=AHORA)
    assert _filas() == ["limite", "reciente"]
    assert res["dias"] == 30
    assert res["capturas"]["filas"] == 2
    assert res["capturas"]["bytes"] == len(b"vieja uno") + len(b"vieja dos")
    assert res["capturas"]["quedan"] == 2
    # el índice de texto completo no conserva lo borrado
    with sqlite3.connect(k.db_path()) as con:
        assert con.execute("SELECT COUNT(*) FROM captura_fts WHERE captura_fts MATCH 'vieja'").fetchone()[0] == 0
    assert registro.depurar_crudo(ahora=AHORA)["capturas"]["filas"] == 0


def test_la_ultima_captura_nunca_se_borra_para_no_reusar_su_rowid(home, monkeypatch):
    """Sin AUTOINCREMENT, borrar el rowid más alto lo reusaría y el cursor de réplica de otra PC
    saltearía las capturas nuevas."""
    monkeypatch.setattr(research_creencias, "resguardo_capturas", lambda: {"app": AHORA.isoformat()})
    _captura(monkeypatch, "vieja uno", "2026-08-01T10:00:00.000Z")
    _captura(monkeypatch, "vieja dos", "2026-08-02T10:00:00.000Z")
    with sqlite3.connect(k.db_path()) as con:
        alto = con.execute("SELECT MAX(rowid) FROM captura").fetchone()[0]
    res = registro.depurar_crudo(ahora=AHORA)
    assert res["capturas"]["filas"] == 1
    assert _filas() == ["vieja dos"]
    _captura(monkeypatch, "nueva", "2026-10-22T11:00:00.000Z")
    with sqlite3.connect(k.db_path()) as con:
        assert con.execute("SELECT rowid FROM captura WHERE texto='nueva'").fetchone()[0] > alto


def test_sin_base_no_la_crea(tmp_path, monkeypatch):
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    monkeypatch.setattr(registro.state, "LOG", str(tmp_path / "lienzo.log"))
    monkeypatch.setattr(registro.state, "EVENTS", str(tmp_path / "events"))
    res = registro.depurar_crudo(ahora=AHORA)
    assert res["capturas"]["filas"] == 0
    assert not os.path.exists(k.db_path())


def test_log_pierde_las_lineas_viejas_con_sus_continuaciones(home):
    log = home / "lienzo.log"
    log.write_text(
        "2026-09-05T12:48:01.337-03:00 barrido: viejo\n"
        "2026-09-20 10:00:00.000  error    Traceback (most recent call last):\n"
        '  File "x.py", line 1\n'
        "ValueError: viejo\n"
        f"{DIA_CORTE} 00:00:00.000  info     del dia del corte\n"
        "Traceback continuación nueva\n"
        "2026-10-21 09:00:00.000  info     reciente\n",
        encoding="utf-8",
    )
    antes = log.stat().st_size
    res = registro.depurar_crudo(ahora=AHORA)
    assert log.read_text(encoding="utf-8") == (
        f"{DIA_CORTE} 00:00:00.000  info     del dia del corte\n"
        "Traceback continuación nueva\n"
        "2026-10-21 09:00:00.000  info     reciente\n"
    )
    assert res["log"]["antes"] == antes and res["log"]["despues"] == log.stat().st_size
    assert res["log"]["lineas"] == 4
    assert registro.depurar_crudo(ahora=AHORA)["log"]["lineas"] == 0


def test_log_ausente_o_sin_viejas_no_se_toca(home):
    assert registro.depurar_crudo(ahora=AHORA)["log"] == {"lineas": 0, "antes": 0, "despues": 0}
    log = home / "lienzo.log"
    log.write_text("2026-10-21 09:00:00.000  info     reciente\n", encoding="utf-8")
    mtime = log.stat().st_mtime_ns
    assert registro.depurar_crudo(ahora=AHORA)["log"]["lineas"] == 0
    assert log.stat().st_mtime_ns == mtime


def test_log_trabado_no_rompe_ni_pierde(home, monkeypatch):
    log = home / "lienzo.log"
    log.write_text(
        "2026-09-01 00:00:00.000  info     viejo\n2026-10-21 00:00:00.000  info     nuevo\n", encoding="utf-8"
    )

    def trabado(a, b):
        raise PermissionError("en uso")

    monkeypatch.setattr(registro.os, "replace", trabado)
    res = registro.depurar_crudo(ahora=AHORA)
    assert res["log"]["error"] == "PermissionError"
    assert "viejo" in log.read_text(encoding="utf-8")
    assert [p.name for p in home.iterdir() if p.name.startswith("lienzo.log.")] == []


def test_una_base_trabada_no_frena_el_log_ni_los_eventos(home, monkeypatch):
    log = home / "lienzo.log"
    log.write_text(
        "2026-09-01 00:00:00.000  info     viejo\n2026-10-21 00:00:00.000  info     nuevo\n", encoding="utf-8"
    )

    def trabada(path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(registro.k, "_Conexion", trabada)
    res = registro.depurar_crudo(ahora=AHORA)
    assert res["capturas"] == {"error": "OperationalError: database is locked"}
    assert res["log"]["lineas"] == 1
    assert "viejo" not in log.read_text(encoding="utf-8")


def test_eventos_huerfanos_viejos(home):
    ev = home / "events"
    ev.mkdir()
    viejo = ev / "1-x-SessionStart.json.tmp"
    nuevo = ev / "2-y-SessionStart.json.tmp"
    pendiente = ev / "3-z-Stop.json"
    for p in (viejo, nuevo, pendiente):
        p.write_text("{}", encoding="utf-8")
    hace = (AHORA - dt.timedelta(days=40)).timestamp()
    os.utime(viejo, (hace, hace))
    os.utime(pendiente, (hace, hace))
    res = registro.depurar_crudo(ahora=AHORA)
    assert res["eventos"] == {"archivos": 1, "bytes": 2}
    assert sorted(p.name for p in ev.iterdir()) == [nuevo.name, pendiente.name]


def test_dias_invalidos():
    for dias in (0, -1, 3651):
        with pytest.raises(ValueError):
            registro.depurar_crudo(dias, ahora=AHORA)


def test_bucle_corre_y_registra_hasta_que_lo_paran(monkeypatch):
    import threading

    parar = threading.Event()
    vistos, logs = [], []

    def depurar(**kw):
        vistos.append(kw)
        if len(vistos) == 2:
            parar.set()
        if len(vistos) == 1:
            raise OSError("disco")
        return {"capturas": {"filas": 3}}

    monkeypatch.setattr(registro, "depurar_crudo", depurar)
    monkeypatch.setattr(registro.state, "log", logs.append)
    registro.bucle(parar, arranque_s=0, cada_s=0)
    assert len(vistos) == 2
    assert any("OSError" in m for m in logs) and any("filas" in m for m in logs)
