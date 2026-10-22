"""Confianza de Kiro: sólo se autoriza una carpeta permitida por launch."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import autoaprobar as au
import launch
import screen
import sessions as ses
import state


PANTALLA = """ Trust this workspace?
 ──────────────────────
 d:/apps/opensyync

 This folder can contain hooks, agents, MCP servers and workflows that run commands on your machine. Only trust folders
 you know.

 Trusting lets Kiro use this workspace's configuration. Kiro will be able to read, edit, and execute files here.

 ❯ Trust, continue
   Don't trust, exit
"""


def test_pantalla_real():
    d = screen.dialog(PANTALLA.splitlines())
    assert d is not None
    assert d["question"] == "Trust this workspace?"
    assert d["detail"] == "d:/apps/opensyync"
    assert d["options"] == [{"n": 1, "text": "Trust, continue"}, {"n": 2, "text": "Don't trust, exit"}]
    assert d["selected"] == 1
    assert d["teclas"] == "flechas"


@pytest.mark.parametrize(
    "alteracion",
    [
        ("❯ Trust, continue", "  Trust, continue"),
        ("Don't trust, exit", "❯ Don't trust, exit"),
        ("d:/apps/opensyync", ""),
        ("Trust, continue", "Trust everything"),
    ],
)
def test_incompleto_no_es_confianza(alteracion):
    d = screen.dialog(PANTALLA.replace(*alteracion).splitlines())
    assert d is None or au.opcion_de_permiso(d, "kiro") is None


@pytest.mark.parametrize("permitida", [True, False])
def test_autoaprobar_respeta_raices(monkeypatch, tmp_path, permitida):
    root = tmp_path / "permitida"
    root.mkdir()
    folder = root / "repo" if permitida else tmp_path / "afuera"
    folder.mkdir()
    d = screen.dialog(PANTALLA.replace("d:/apps/opensyync", str(folder)).splitlines())
    tarjeta = {
        "session_id": "T",
        "agent": "kiro",
        "state": "te_necesita",
        "dialog": d,
        "needs": {"kind": "dialog", "since": "ahora"},
    }
    monkeypatch.setattr(state, "load_config", lambda: {"auto_aprobar": True, "launch_roots": [str(root)]})
    monkeypatch.setattr(state, "sessions", {"T": tarjeta})
    monkeypatch.setattr(state, "pending", {})
    monkeypatch.setattr(state, "log", lambda _: None)
    monkeypatch.setattr(au, "_intentados", {})
    enviados = []
    monkeypatch.setattr(ses, "answer_dialog", lambda s, n: (enviados.append(n), (200, {}))[1])
    assert ses.lo_contesta_el_auto_aprobar(tarjeta, d) is permitida
    au.ronda(100)
    assert enviados == ([1] if permitida else [])
    if not permitida:
        assert "launch_roots" in tarjeta[au.OMITIDO]
    else:
        assert tarjeta.get(au.OMITIDO) is None
        assert tarjeta[au.APROBADO]["via"] == "dialogo"


def test_revalida_antes_de_contestar(monkeypatch, tmp_path):
    d = screen.dialog(PANTALLA.replace("d:/apps/opensyync", str(tmp_path)).splitlines())
    tarjeta = {"session_id": "T", "agent": "kiro", "state": "te_necesita", "dialog": d, "needs": {"kind": "dialog"}}
    config = {"launch_roots": [str(tmp_path)]}
    monkeypatch.setattr(state, "load_config", lambda: config)
    monkeypatch.setattr(state, "sessions", {"T": tarjeta})
    proveedor = au.DialogoDePermiso()
    (pedido,) = proveedor.abiertos()
    config["launch_roots"] = []
    monkeypatch.setattr(ses, "answer_dialog", lambda *_: pytest.fail("no debe contestar"))
    assert proveedor.aprobar(pedido)[0] == 409


def test_usa_validador_fisico_de_launch(monkeypatch):
    d = {
        "question": "Trust this workspace?",
        "detail": "d:/apps/opensyync",
        "options": [{"n": 1, "text": "Trust, continue"}, {"n": 2, "text": "Don't trust, exit"}],
    }
    llamadas = []
    monkeypatch.setattr(launch, "_allowed_roots", lambda: ["raiz"])
    monkeypatch.setattr(launch, "_cwd_allowed", lambda cwd, roots: llamadas.append((cwd, roots)) or False)
    assert au.opcion_de_permiso(d, "kiro") is None
    assert llamadas == [("d:/apps/opensyync", ["raiz"])]


def test_pantalla_lleva_tarjeta_a_te_necesita(monkeypatch):
    os.makedirs(state.SESSIONS, exist_ok=True)
    tarjeta = {"session_id": "T", "agent": "kiro", "pid": 1, "alive": True, "state": "corriendo"}
    monkeypatch.setattr(state, "sessions", {"T": tarjeta})
    monkeypatch.setattr(ses, "sessions", state.sessions)
    monkeypatch.setattr(state, "load_config", lambda: {"auto_aprobar": False})
    monkeypatch.setattr(ses, "read_screen", lambda _: {"ok": True, "dialog": screen.dialog(PANTALLA.splitlines())})
    monkeypatch.setattr(ses, "read_transcript", lambda _: {})
    ses.screen_once()
    assert tarjeta["state"] == "te_necesita"
    assert tarjeta["needs"]["kind"] == "dialog"
    assert tarjeta["needs"]["detail"] == "Trust this workspace?"


def test_cursor_en_salir_siempre_elige_confiar(monkeypatch, tmp_path):
    texto = PANTALLA.replace("d:/apps/opensyync", str(tmp_path))
    texto = texto.replace("❯ Trust, continue", "  Trust, continue").replace(
        "   Don't trust, exit", " ❯ Don't trust, exit"
    )
    d = screen.dialog(texto.splitlines())
    monkeypatch.setattr(state, "load_config", lambda: {"launch_roots": [str(tmp_path)]})
    assert d["selected"] == 2
    assert au.opcion_de_permiso(d, "kiro") == 1
