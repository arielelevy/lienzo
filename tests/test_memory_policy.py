"""Temporales aislados y raíces autorizadas. No se borran proyectos ni se lanzan agentes reales."""

import os

import captura
import conocimiento as k
import conocimiento_api as api
import memory_policy as policy
import pytest


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ("temp-root", "tmp-root", "python-root")]
    for root in roots:
        root.mkdir()
    monkeypatch.setenv("TEMP", str(roots[0]))
    monkeypatch.setenv("TMP", str(roots[1]))
    monkeypatch.setattr(policy.tempfile, "gettempdir", lambda: str(roots[2]))
    config = {"launch_roots": []}
    monkeypatch.setattr(policy.state, "load_config", lambda: config)
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    captura.olvidar()
    yield roots, config
    captura.olvidar()


@pytest.mark.parametrize("n", range(3))
def test_cada_raiz_temporal_y_sus_descendientes_se_excluyen(entorno, n):
    roots, _ = entorno
    assert policy.excluida(str(roots[n]))
    assert policy.excluida(str(roots[n] / "benchmark" / "a"))
    assert not policy.excluida(str(roots[n]) + "-proyecto")


def test_raiz_temporal_aprobada_y_subcarpetas_generan_memoria(entorno):
    roots, config = entorno
    config["launch_roots"] = [str(roots[0] / "permitido")]
    assert not policy.excluida(str(roots[0] / "permitido"))
    assert not policy.excluida(str(roots[0] / "permitido" / "src"))
    assert policy.excluida(str(roots[0] / "permitido-otro"))


@pytest.mark.parametrize("bad", [None, "C:/", [None, "", 12]])
def test_config_invalida_no_autoriza_temporales(entorno, bad):
    roots, config = entorno
    config["launch_roots"] = bad
    assert policy.excluida(str(roots[0] / "bench"))


def test_sin_cwd_y_fuera_de_temporales_no_se_excluye(entorno, tmp_path):
    assert not policy.excluida(None)
    assert not policy.excluida("")
    assert not policy.excluida(str(tmp_path / "proyecto"))


def test_junction_no_escapa_de_la_raiz_aprobada(entorno, monkeypatch):
    roots, config = entorno
    permitido = roots[0] / "permitido"
    escape = permitido / "link"
    config["launch_roots"] = [str(permitido)]
    real = policy._physical
    monkeypatch.setattr(
        policy, "_physical", lambda p: real(str(roots[0] / "privado")) if str(p) == str(escape) else real(p)
    )
    assert policy.excluida(str(escape))  # resolución de junction simulada, sin privilegios del SO


def test_alias_externo_hacia_temp_tambien_se_excluye(entorno, tmp_path, monkeypatch):
    roots, _ = entorno
    alias = str(tmp_path / "alias")
    real = policy._physical
    monkeypatch.setattr(policy, "_physical", lambda p: real(str(roots[0] / "bench")) if p == alias else real(p))
    assert policy.excluida(alias)


@pytest.mark.skipif(os.name != "nt", reason="normalización de rutas Windows")
def test_case_y_barras_windows_no_evitan_el_filtro(entorno):
    roots, _ = entorno
    path = str(roots[0] / "bench").upper().replace("\\", "/")
    assert policy.excluida(path)


def test_no_registra_proyecto_por_api_ni_por_captura(entorno, monkeypatch):
    roots, _ = entorno
    cwd = str(roots[0] / "bench")
    tarjeta = {"session_id": "headless", "agent": "claude", "cwd": cwd}
    assert k.proyecto_de_carpeta(cwd, "pcA") is None
    assert api.dispatch("POST", ["carpeta"], {"cwd": cwd, "pc": "pcA"}, {})[1]["proyecto"] is None
    assert captura.procesar({"tipo": "pedido", "tarjeta": tarjeta, "texto": "bench"}) is None
    assert k.proyectos() == []


def test_vista_denegada_no_oculta_tarjeta_y_autorizacion_posterior_funciona(entorno, monkeypatch):
    roots, config = entorno
    s = {"session_id": "s", "agent": "codex", "cwd": str(roots[0] / "bench"), "state": "corriendo", "alive": True}
    eventos = []
    monkeypatch.setattr(captura, "encolar", eventos.append)
    captura.vista(s)
    assert captura.procesar(eventos[-1]) is None
    assert s["state"] == "corriendo" and s["alive"] is True
    config["launch_roots"] = [str(roots[0])]
    captura.vista(s)
    assert len(eventos) == 2
    assert captura.procesar(eventos[-1])["tipo"] == "sesion"


def test_revocar_excepcion_impide_capturas_aunque_haya_cache_y_proyecto(entorno, monkeypatch):
    roots, config = entorno
    cwd = str(roots[0] / "bench")
    tarjeta = {"session_id": "s", "agent": "kiro", "cwd": cwd}
    config["launch_roots"] = [str(roots[0])]
    pid = captura.proyecto_de(tarjeta)
    assert pid is not None
    config["launch_roots"] = []
    assert captura.proyecto_de(tarjeta) is None
    assert k.registrar_sesion(pid, tarjeta) is None
    assert k.capturar(pid, "respuesta", "no guardar", tarjeta) is None
    assert k.resolver_proyecto(cwd=cwd) is None
    assert pid in {p["id"] for p in k.proyectos()}  # se preserva el proyecto histórico
    assert k.capturas(pid)["total"] == 0


def test_exclusion_se_evalua_antes_de_resolver_raiz_git(entorno, monkeypatch):
    roots, _ = entorno
    monkeypatch.setattr(
        k, "carpeta_de", lambda cwd: pytest.fail("no resolver un repo antes de excluir el cwd temporal")
    )
    assert k.proyecto_de_carpeta(str(roots[0] / "worktree"), "pcA") is None


def test_adaptadores_no_mutan_sesion_legacy_en_temporal(entorno, monkeypatch):
    roots, config = entorno
    cwd = str(roots[0] / "bench")
    tarjeta = {"session_id": "s", "agent": "coda", "cwd": cwd}
    config["launch_roots"] = [str(roots[0])]
    pid = k.proyecto_de_carpeta(cwd, "pcA")
    nodo = k.registrar_sesion(pid, tarjeta)
    monkeypatch.setattr(policy.state, "sessions", {"s": tarjeta})
    config["launch_roots"] = []
    assert k._proyecto_de_sesion("s") is None
    assert k.incidente_operativo("s", "error del benchmark", herramienta="benchmark", clave="no-crear") is None
    k.sesion_cerrada("s")
    assert k.nodo(pid, nodo["id"])["estado"] == "viva"
    assert k.nodos(pid, tipo="incidente")["total"] == 0


def test_denegacion_entre_chequeos_no_deja_cache_negativa(entorno, monkeypatch):
    roots, config = entorno
    config["launch_roots"] = [str(roots[0])]
    tarjeta = {"session_id": "s", "agent": "claude", "cwd": str(roots[0] / "bench")}
    real = k.proyecto_de_carpeta
    calls = []

    def resolver(*args):
        calls.append(args)
        return None if len(calls) == 1 else real(*args)

    monkeypatch.setattr(k, "proyecto_de_carpeta", resolver)
    assert captura.proyecto_de(tarjeta) is None
    assert captura.proyecto_de(tarjeta) is not None
    assert len(calls) == 2


def test_vista_denegada_en_segundo_chequeo_puede_reintentarse(entorno, monkeypatch):
    roots, config = entorno
    config["launch_roots"] = [str(roots[0])]
    tarjeta = {"session_id": "s", "agent": "claude", "cwd": str(roots[0] / "bench")}
    real, calls, eventos = k.registrar_sesion, [], []

    def registrar(*args):
        calls.append(args)
        return None if len(calls) == 1 else real(*args)

    monkeypatch.setattr(k, "registrar_sesion", registrar)
    monkeypatch.setattr(captura, "encolar", eventos.append)
    captura.vista(tarjeta)
    assert captura.procesar(eventos[-1]) is None
    captura.vista(tarjeta)
    assert len(eventos) == 2
    assert captura.procesar(eventos[-1])["tipo"] == "sesion"
