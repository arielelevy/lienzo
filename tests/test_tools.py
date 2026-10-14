"""Catalogo de tools (lienzo/tools/): integraciones que usan repos o servicios externos, por tipo y modo."""

import agent_improvements as improvements
import pytest
import state
import tools
from tools import rea, rtk


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(rtk.shutil, "which", lambda name: None)
    monkeypatch.setattr(rea.shutil, "which", lambda name: None)
    monkeypatch.delenv("REA_HOME", raising=False)
    return tmp_path


def test_catalogo_ids_unicos_tipos_y_origen():
    cat = tools.catalogo()
    ids = [t.id for t in cat]
    assert ids == ["breve", "rtk", "jev", "pruebas-agenticas", "rea"] and len(set(ids)) == len(ids)
    assert all(t.origen and t.tipo in tools.TIPOS for t in cat)
    assert {t.id: t.tipo for t in cat} == {
        "breve": "mejora",
        "rtk": "mejora",
        "jev": "evaluacion",
        "pruebas-agenticas": "pruebas",
        "rea": "trabajo",
    }
    assert tools.por_id("jev").costo == "pago" and tools.por_id("rtk").version == rtk.VERSION
    with pytest.raises(ValueError):
        tools.Tool(id="x", nombre="x", tipo="raro", origen="o", descripcion="d")


def test_resumen_no_se_corta_por_una_tool_rota(aislado, monkeypatch):
    rota = tools.Tool(id="rota", nombre="Rota", tipo="mejora", origen="o", descripcion="d", estado=lambda d: 1 / 0)
    breve = tools.por_id("breve")
    monkeypatch.setattr(tools, "_catalogo", lambda: [rota, breve])
    res = tools.resumen()
    assert res[0]["estado"]["disponible"] is False and "no se pudo verificar" in res[0]["estado"]["detalle"]
    assert res[1]["estado"]["disponible"] is True


def test_mejoras_solo_con_su_preferencia(aislado):
    assert tools.instrucciones("claude", None, {"brief": False, "rtk": False}) == ("", [])
    texto, avisos = tools.instrucciones("claude", None, {"brief": True, "rtk": False})
    assert "Responde breve" in texto and not avisos
    texto, avisos = tools.instrucciones("claude", None, {"brief": False, "rtk": True})
    assert not texto and "RTK no esta instalado" in avisos[0]


def test_rea_solo_en_modo_ingenieria_reversa(aislado, monkeypatch):
    prefs = {"brief": False, "rtk": False}
    assert tools.instrucciones("codex", None, prefs) == ("", [])  # general: REA no aparece
    texto, avisos = tools.instrucciones("codex", None, prefs, "ingenieria-reversa")
    assert not texto and "REA no esta instalada" in avisos[0]  # sin instalar: se avisa, no se inventa
    monkeypatch.setattr(rea.shutil, "which", lambda name: "C:/bin/rea.cmd" if name == "rea" else None)
    texto, avisos = tools.instrucciones("codex", None, prefs, "ingenieria-reversa")
    assert "ingenieria reversa" in texto and "C:/bin/rea.cmd" in texto and not avisos
    with pytest.raises(ValueError):
        tools.instrucciones("codex", None, prefs, "otro-modo")


def test_agente_sin_instrucciones_verificadas(aislado):
    texto, avisos = tools.instrucciones("kiro", None, {"brief": True, "rtk": False})
    assert texto == "" and "kiro no admite" in avisos[0]


def test_status_de_mejoras_trae_el_catalogo(aislado):
    st = improvements.status()
    assert st["preferences"] == {"brief": False, "rtk": False}
    assert [t["id"] for t in st["tools"]] == ["breve", "rtk", "jev", "pruebas-agenticas", "rea"]
    assert next(t for t in st["tools"] if t["id"] == "rea")["modos"] == ["ingenieria-reversa"]


def test_lanzamiento_rechaza_modo_desconocido():
    import server

    code, body = server.accion_launch({"cwd": "D:/x", "agent": "claude", "modo": "magia"}, desde_tablero=True)
    assert code == 400 and "modo desconocido" in body["error"]


def test_reinicio_verifica_sintaxis_del_catalogo():
    from pathlib import Path

    import server

    stamp = server._source_stamp()
    archivo = str(Path(server.HERE) / "tools" / "rtk.py")
    assert archivo in stamp
    assert server._syntax_error([archivo]) is None


def test_modo_reversa_conserva_mejoras_y_no_anuncia_rea_windows_en_wsl(aislado, monkeypatch):
    monkeypatch.setattr(rea.shutil, "which", lambda name: "C:/bin/rea.cmd" if name == "rea" else None)
    monkeypatch.setattr(rtk.subproc, "correr", lambda *a, **k: (0, "/usr/local/bin/rtk\n", ""))
    texto, avisos = tools.instrucciones("codex", "Ubuntu", {"brief": True, "rtk": True}, "ingenieria-reversa")
    assert "Responde breve" in texto and "/usr/local/bin/rtk" in texto
    assert "C:/bin/rea.cmd" not in texto and "REA en WSL no verificada" in avisos[0]
    assert rea._estado("Ubuntu")["disponible"] is False


@pytest.mark.parametrize("out", ["rtk\n", "/bin/rtk\n/bin/otro\n"])
def test_rtk_wsl_rechaza_ruta_no_absoluta_o_multiple(monkeypatch, out):
    monkeypatch.setattr(rtk.subproc, "correr", lambda *a, **k: (0, out, ""))
    with pytest.raises(ValueError, match="ruta absoluta"):
        rtk.ruta("Ubuntu")
