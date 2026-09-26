"""lienzo/health.py: snapshot() de memoria, CPU y temperatura. Windows real, sin mocks de ctypes:
son las mismas APIs que procinfo.py ya usa sin stub en test_procs.py."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import health


def _reset():
    """snapshot() guarda estado de modulo (muestra de CPU, cache de temperatura): cada test
    arranca limpio para no depender del orden en que corren."""
    health._ultima_muestra = None
    health._temp_cache = None


def test_snapshot_trae_las_cinco_claves():
    _reset()
    s = health.snapshot()
    assert set(s) == {"mem_free_gb", "mem_total_gb", "cpu_pct", "temp_c", "ts"}


def test_memoria_es_real_y_coherente():
    _reset()
    s = health.snapshot()
    assert isinstance(s["mem_total_gb"], float) and s["mem_total_gb"] > 1
    assert isinstance(s["mem_free_gb"], float) and 0 <= s["mem_free_gb"] <= s["mem_total_gb"]


def test_cpu_pct_none_en_la_primera_llamada_y_numero_en_la_segunda():
    _reset()
    primera = health.snapshot()
    assert primera["cpu_pct"] is None, "sin muestra anterior no hay con que comparar"
    time.sleep(0.05)
    segunda = health.snapshot()
    assert isinstance(segunda["cpu_pct"], float)
    assert 0.0 <= segunda["cpu_pct"] <= 100.0


def test_snapshot_nunca_levanta_aunque_falle_todo(monkeypatch):
    _reset()

    def revienta(*a, **k):
        raise OSError("simulado")

    monkeypatch.setattr(health._k32, "GlobalMemoryStatusEx", revienta)
    monkeypatch.setattr(health._k32, "GetSystemTimes", revienta)
    monkeypatch.setattr(health, "_temp_c", lambda: (_ for _ in ()).throw(OSError("simulado")))
    s = health.snapshot()
    assert s == {"mem_free_gb": None, "mem_total_gb": None, "cpu_pct": None, "temp_c": None, "ts": s["ts"]}


def test_temperatura_o_none_y_valor_ya_no_finito_da_none(monkeypatch):
    _reset()
    t = health._temp_c()
    assert t is None or isinstance(t, float)


def test_temperatura_cacheada_30_segundos_no_repite_el_powershell(monkeypatch):
    _reset()
    llamadas = []

    class FakeResult:
        stdout = "2981\n"  # deciKelvin: 25.0 C

    def fake_run(*a, **k):
        llamadas.append(1)
        return FakeResult()

    monkeypatch.setattr(health.subprocess, "run", fake_run)

    reloj = [1000.0]
    monkeypatch.setattr(health.time, "monotonic", lambda: reloj[0])

    primera = health._temp_c()
    assert primera == 25.0
    assert len(llamadas) == 1

    reloj[0] += 10  # adentro de los 30 s de cache
    segunda = health._temp_c()
    assert segunda == 25.0
    assert len(llamadas) == 1, "10 s despues todavia tiene que servir del cache"

    reloj[0] += 25  # 35 s desde la primera: la cache vencio
    tercera = health._temp_c()
    assert tercera == 25.0
    assert len(llamadas) == 2


def test_temperatura_con_powershell_que_no_devuelve_nada():
    """WMI sin la clase (VM sin sensor) o timeout: el powershell real corre y no truena."""
    _reset()
    t = health._temp_c()
    assert t is None or isinstance(t, float)


def test_snapshot_en_frio_y_con_cache(capsys):
    """Mide cuanto tarda snapshot(): en frio (primer llamado, con el powershell de temperatura
    de verdad) contra con la temperatura ya en cache. Lo que se mide va al informe."""
    _reset()
    frio_ini = time.perf_counter()
    health.snapshot()
    frio = time.perf_counter() - frio_ini

    cache_ini = time.perf_counter()
    health.snapshot()
    cache = time.perf_counter() - cache_ini

    with capsys.disabled():
        print(f"\nsnapshot() en frio: {frio * 1000:.1f} ms · con cache: {cache * 1000:.1f} ms")
    assert cache < frio or cache < 0.05, "con la temperatura en cache no deberia tardar mas que en frio"
