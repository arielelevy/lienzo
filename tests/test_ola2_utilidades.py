"""Refactor, ola 2, punto 3: utilidades compartidas. atomico.atomic_write (la unica escritura
atomica, con el reintento de Windows que a auth le faltaba), CacheEnSegundoPlano de health y el
config.json corrupto que hook.py ya no calla."""

import json
import os

import atomico
import auth
import health
import hook
import pytest
import state


def _replace_que_falla(monkeypatch, veces: int) -> list[str]:
    """os.replace levanta PermissionError las primeras `veces` (el antivirus con el archivo
    abierto); despues anda. Devuelve la lista de intentos."""
    intentos: list[str] = []
    real = os.replace

    def replace(src, dst):
        intentos.append(dst)
        if len(intentos) <= veces:
            raise PermissionError(13, "otro proceso tiene el archivo abierto")
        real(src, dst)

    monkeypatch.setattr(atomico.os, "replace", replace)
    monkeypatch.setattr(atomico.time, "sleep", lambda s: None)
    return intentos


def test_atomic_write_reintenta_ante_el_antivirus(tmp_path, monkeypatch):
    intentos = _replace_que_falla(monkeypatch, 2)
    p = tmp_path / "x.json"
    atomico.atomic_write(str(p), "hola ñandú")
    assert p.read_text(encoding="utf-8") == "hola ñandú"
    assert len(intentos) == 3
    assert os.listdir(tmp_path) == ["x.json"], "no queda ningun .tmp"


def test_atomic_write_se_rinde_y_no_deja_el_tmp(tmp_path, monkeypatch):
    _replace_que_falla(monkeypatch, 99)
    p = tmp_path / "x.json"
    with pytest.raises(PermissionError):
        atomico.atomic_write(str(p), "x")
    assert os.listdir(tmp_path) == []


def test_state_auth_y_hook_usan_la_misma_escritura(tmp_path, monkeypatch):
    """La de auth no tenia el reintento: un login podia dar 500 por el antivirus."""
    intentos = _replace_que_falla(monkeypatch, 1)
    auth._atomic(str(tmp_path / "auth.json"), {"a": 1})
    assert json.loads((tmp_path / "auth.json").read_text(encoding="utf-8")) == {"a": 1}
    state.atomic_write(str(tmp_path / "s.json"), "s")
    hook.atomic_write(str(tmp_path / "h.json"), "h")
    assert len(intentos) == 4  # el primero de auth fallo y se reintento
    assert hook.atomic_write is atomico.atomic_write


def test_atomico_es_una_hoja_liviana():
    """hook.py lo importa en cada evento: nada del lienzo ni `threading`."""
    with open(atomico.__file__, encoding="utf-8") as f:
        codigo = f.read()
    imports = {ln.split()[1] for ln in codigo.splitlines() if ln.startswith(("import ", "from "))}
    assert imports <= {"__future__", "os", "time", "_thread"}


# --- health.CacheEnSegundoPlano -------------------------------------------------------------


@pytest.fixture
def reloj_e_hilo_en_linea(monkeypatch):
    """Reloj a mano y el hilo de refresco corriendo en linea, para probar sin esperas."""
    reloj = [1000.0]
    monkeypatch.setattr(health.time, "monotonic", lambda: reloj[0])
    monkeypatch.setattr(
        health.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})()
    )
    return reloj


def test_cache_mide_al_vencer_y_si_medir_levanta_lo_loguea_y_queda_el_ultimo(reloj_e_hilo_en_linea, monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(health, "log", avisos.append)
    medidas = [41.0, RuntimeError("wmi roto"), RuntimeError("wmi roto"), 43.0]
    llamadas = []

    def medir():
        llamadas.append(1)
        m = medidas.pop(0)
        if isinstance(m, Exception):
            raise m
        return m

    c = health.CacheEnSegundoPlano("temperatura", 30, medir)
    assert c.valor(esperar_primera=True) == 41.0
    assert c.valor() == 41.0 and len(llamadas) == 1, "adentro del TTL no se mide"
    reloj_e_hilo_en_linea[0] += 31
    assert c.valor() == 41.0, "medir levanto: queda el ultimo valor"
    assert avisos == ["temperatura: falla (RuntimeError: wmi roto); queda el ultimo valor"]
    assert c.valor() == 41.0 and len(llamadas) == 2, "no reintenta en cada pedido, espera el TTL"
    reloj_e_hilo_en_linea[0] += 31
    c.valor()
    assert len(avisos) == 1, "el mismo motivo no se repite en el log"
    reloj_e_hilo_en_linea[0] += 31
    assert c.valor() == 43.0, "el refresco sigue vivo despues de una falla"
    assert avisos[-1] == "temperatura: se recupero"


def test_cache_con_hilo_de_verdad_que_levanta_no_deja_el_lock_tomado(monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(health, "log", avisos.append)

    def medir():
        raise ValueError("formato nuevo")

    c = health.CacheEnSegundoPlano("git", 0, medir)
    assert c.valor() is None
    for _ in range(100):  # el hilo es de verdad: se espera a que suelte el lock
        if c._refrescando.acquire(timeout=0.05):
            c._refrescando.release()
            break
    else:
        raise AssertionError("el hilo murio con el lock tomado")
    assert avisos == ["git: falla (ValueError: formato nuevo); queda el ultimo valor"]


def test_cache_con_otra_clave_mide_enseguida_y_no_devuelve_la_vieja(reloj_e_hilo_en_linea):
    c = health.CacheEnSegundoPlano("git", 300, lambda urls: {u: "ok" for u in urls} or None)
    assert c.valor(("https://a",)) == {"https://a": "ok"}  # con el hilo en linea, ya midio
    assert c.valor(("https://b",)) == {"https://b": "ok"}, "sin esperar los 300 s"


def test_wmi_va_por_subproc_y_un_powershell_colgado_es_una_falla_logueada(monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(health, "log", avisos.append)
    vistos = {}

    def correr(argv, **k):
        vistos.update(argv=argv, **k)
        return health.subproc.VENCIDO, "", "powershell no termino en 5 s"

    monkeypatch.setattr(health.subproc, "correr", correr)
    assert health.ZonasTermicasWMI().medir() is None
    assert vistos["argv"][0] == "powershell" and vistos["timeout"] == 5
    assert avisos == ["temperatura, fuente wmi: falla (OSError: powershell no termino en 5 s)"]


# --- hook.load_config: un config.json corrupto no se calla ---------------------------------


def _hook_en(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path))
    monkeypatch.setattr(hook, "EVENTS", str(tmp_path / "events"))


def _anotados(tmp_path) -> list[str]:
    d = tmp_path / "events"
    return [(d / n).read_text(encoding="utf-8") for n in os.listdir(d) if n.startswith("bad-")] if d.exists() else []


def test_hook_config_corrupto_queda_anotado_y_se_toma_vacio(tmp_path, monkeypatch):
    _hook_en(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text('{"wait": 30,', encoding="utf-8")
    assert hook.load_config() == {}
    [nota] = _anotados(tmp_path)
    assert "config.json" in nota and "JSONDecodeError" in nota
    assert (tmp_path / "config.json").exists(), "apartarlo es cosa del server, no del hook"


def test_hook_config_que_no_es_objeto_tambien_se_anota(tmp_path, monkeypatch):
    _hook_en(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text("[1, 2]", encoding="utf-8")
    assert hook.load_config() == {}
    [nota] = _anotados(tmp_path)
    assert "no es un objeto JSON sino list" in nota


def test_hook_config_ausente_o_bueno_no_anota_nada(tmp_path, monkeypatch):
    _hook_en(tmp_path, monkeypatch)
    assert hook.load_config() == {}
    (tmp_path / "config.json").write_text('{"wait": 30}', encoding="utf-8")
    assert hook.load_config() == {"wait": 30}
    assert _anotados(tmp_path) == []


def test_hook_config_corrupto_sin_poder_anotar_igual_devuelve_vacio(tmp_path, monkeypatch):
    _hook_en(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text("{", encoding="utf-8")

    def no_se_puede(path, text):
        raise PermissionError("disco de solo lectura")

    monkeypatch.setattr(hook, "atomic_write", no_se_puede)
    assert hook.load_config() == {}
