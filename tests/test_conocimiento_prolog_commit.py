"""Condiciones explícitas de Ariel para el hook poscommit AA."""

import sqlite3
import time
from pathlib import Path

import conocimiento as k
import prolog_programa as p
import pytest


def test_notifica_despues_de_commit_y_close_solo_proyectos_tocados(monkeypatch):
    for pid in ("aa-uno", "aa-dos", "aa-intacto"):
        k.registrar_proyecto(pid)
    calls = []

    def notify(pids, **kwargs):
        assert kwargs["base"] == k.db_path()
        assert set(pids) == {"aa-uno", "aa-dos"}
        # La conexión vieja ya no sirve; una nueva ve el commit.
        with pytest.raises(sqlite3.ProgrammingError):
            used.execute("SELECT 1")
        with sqlite3.connect(k.db_path()) as fresh:
            assert fresh.execute("SELECT count(*) FROM nodo WHERE texto='AA committed'").fetchone()[0] == 2
        calls.append(pids)

    monkeypatch.setattr(p, "notificar", notify)
    with k._abrir("aa-uno") as used:
        for pid in ("aa-uno", "aa-dos"):
            k.crear_nodo(pid, "evidencia", "AA committed", {}, autor="server:AA", con=used)
    assert len(calls) == 1


def test_lectura_y_rollback_no_notifican(monkeypatch):
    k.registrar_proyecto("aa-no-sync")
    calls = []
    monkeypatch.setattr(p, "notificar", lambda *args, **kwargs: calls.append(args))
    with k._abrir("aa-no-sync") as con:
        con.execute("SELECT 1").fetchone()
    with pytest.raises(RuntimeError), k._abrir("aa-no-sync") as con:
        k.crear_nodo("aa-no-sync", "evidencia", "rollback", {}, autor="server:AA", con=con)
        raise RuntimeError("rollback")
    assert calls == []


def test_fallo_sync_se_loguea_y_no_rechaza_escritura(monkeypatch):
    k.registrar_proyecto("aa-error")
    messages = []
    monkeypatch.setattr(k.state, "log", messages.append)

    def fail(*args, **kwargs):
        raise OSError("AA disco ocupado")

    monkeypatch.setattr(p, "notificar", fail)
    saved = k.crear_nodo("aa-error", "evidencia", "confirmada", {}, autor="server:AA")
    with sqlite3.connect(k.db_path()) as con:
        assert con.execute("SELECT texto FROM nodo WHERE id=?", (saved["id"],)).fetchone()[0] == "confirmada"
    assert any("AA disco ocupado" in m and "Prolog" in m for m in messages)


def test_fallo_del_worker_deja_error_en_log_principal(monkeypatch):
    k.registrar_proyecto("aa-async")
    if p._worker:
        p._worker.join(timeout=2)

    def fail(*args, **kwargs):
        raise OSError("AA exportación falló")

    monkeypatch.setattr(p, "sincronizar", fail)
    p.notificar(["aa-async"], base=k.db_path())
    worker = p._worker
    if worker:
        worker.join(timeout=2)
    assert "AA exportación falló" in Path(k.state.LOG).read_text(encoding="utf-8")


def test_hook_encola_sin_exportar_en_hilo_de_escritura(monkeypatch):
    k.registrar_proyecto("aa-latencia")
    calls = []
    real_notify = p.notificar
    notify_ms = []

    def measured(*args, **kw):
        start = time.perf_counter()
        real_notify(*args, **kw)
        notify_ms.append((time.perf_counter() - start) * 1000)
        calls.append(time.perf_counter())

    monkeypatch.setattr(p, "notificar", measured)
    samples = []
    for n in range(10):
        start = time.perf_counter()
        k.crear_nodo("aa-latencia", "evidencia", f"latencia {n}", {}, autor="server:AA")
        samples.append(time.perf_counter() - start)
    assert len(calls) == 10
    assert sorted(samples)[5] < 0.05
    if p._worker:
        p._worker.join(timeout=2)
    print(
        {
            "n": len(samples),
            "escritura_p50_ms": round(sorted(samples)[5] * 1000, 3),
            "escritura_p95_ms": round(max(samples) * 1000, 3),
            "notificacion_p50_ms": round(sorted(notify_ms)[5], 3),
            "notificacion_p95_ms": round(max(notify_ms), 3),
        }
    )
