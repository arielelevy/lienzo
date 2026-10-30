"""Las creencias llegan a cada sesión (2026-10-30): el texto por proyecto, el archivo que lee el hook, el
contexto de SessionStart, los controles de PreToolUse y el registro de hooks en cada perfil de Claude."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lienzo"))
sys.path.insert(0, ROOT)

import conocimiento as k
import contexto_sesion as cs
import creencias as c
import hook
import identity

import install

P = "ctx-test"
HASTA = "2999-01-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def proyecto(monkeypatch, tmp_path):
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    k.registrar_proyecto(P, "Ctx", [], [{"pc": identity.pc_id(), "cwd": "D:/Apps/ctx"}])
    monkeypatch.setattr(hook, "LIENZO", os.environ.get("LIENZO_HOME") or str(tmp_path))


def _vigente(texto, accion, **extra):
    ev = k.crear_nodo(P, "evidencia", "ev", {}, autor="persona:Ariel")
    n = c.proponer(
        P, {"dimension": "pruebas", "texto": texto, "accion": accion, "fuentes": [ev["id"]], **extra}, autor="t"
    )
    c.resolver(
        P,
        n["id"],
        {
            "por": "persona:Ariel",
            "motivo": "ok",
            "resultado": "validada",
            "evidencia": ev["id"],
            "vigente_hasta": HASTA,
        },
    )
    return n["id"]


def test_sin_creencias_no_hay_texto():
    assert cs.texto(P) is None


def test_texto_con_las_vigentes_del_proyecto():
    _vigente("pytest | tail ocultó una falla", "Correr las pruebas con set -o pipefail")
    propuesta_ev = k.crear_nodo(P, "evidencia", "ev", {}, autor="persona:Ariel")
    c.proponer(
        P,
        {"dimension": "pruebas", "texto": "sin veredicto", "accion": "No sale", "fuentes": [propuesta_ev["id"]]},
        autor="t",
    )
    texto = cs.texto(P)
    assert "Correr las pruebas con set -o pipefail" in texto and "No sale" not in texto
    assert f"De este proyecto ({P})" in texto


def test_archivo_hook_contexto_y_control():
    nid = _vigente(
        "pytest | tail ocultó una falla", "Correr las pruebas con set -o pipefail", control="pipefail_pruebas"
    )
    data = cs.escribir()
    assert data["carpetas"]["d:/apps/ctx"] == P and P in data["textos"]
    assert [x["creencia"] for x in data["controles"]] == [nid] and data["controles"][0]["proyecto"] == P
    # SessionStart en una subcarpeta del proyecto
    inicio = hook.contexto_inicio({"cwd": "D:\\Apps\\ctx\\web"})
    assert "pipefail" in inicio["hookSpecificOutput"]["additionalContext"]
    assert hook.contexto_inicio({"cwd": "D:/Apps/otra"}) is None
    # PreToolUse: frena el pipe sin pipefail, deja pasar con pipefail, sin pipe o en otro proyecto
    ev = {"cwd": "D:/Apps/ctx", "tool_name": "Bash"}
    frena = hook.control_previo({**ev, "tool_input": {"command": "python -m pytest -q | tail -5"}})
    assert frena["hookSpecificOutput"]["permissionDecision"] == "deny" and nid[:8] in str(frena)
    assert hook.control_previo({**ev, "tool_input": {"command": "set -o pipefail; pytest | tail -5"}}) is None
    assert hook.control_previo({**ev, "tool_input": {"command": "pytest -q"}}) is None
    assert hook.control_previo({**ev, "cwd": "D:/Apps/otra", "tool_input": {"command": "pytest | tail"}}) is None
    assert hook.control_previo({**ev, "tool_name": "Read", "tool_input": {"command": "pytest | tail"}}) is None


def test_control_desconocido_se_rechaza():
    ev = k.crear_nodo(P, "evidencia", "ev", {}, autor="persona:Ariel")
    with pytest.raises(k.Rechazo, match="control desconocido"):
        c.proponer(
            P, {"dimension": "pruebas", "texto": "t", "accion": "a", "fuentes": [ev["id"]], "control": "x"}, autor="t"
        )


def test_sin_archivo_el_hook_no_hace_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path / "vacio"))
    assert hook.contexto_inicio({"cwd": "D:/Apps/ctx"}) is None
    assert (
        hook.control_previo({"cwd": "D:/Apps/ctx", "tool_name": "Bash", "tool_input": {"command": "pytest | tail"}})
        is None
    )


def test_instalador_registra_en_cada_perfil_con_matcher(tmp_path, monkeypatch):
    home, lienzo, perfil = tmp_path / "home", tmp_path / "lienzo", tmp_path / "perfil"
    (home / ".claude").mkdir(parents=True)
    perfil.mkdir()
    lienzo.mkdir()
    (lienzo / "config.json").write_text(json.dumps({"claude_config_dirs": [{"root": "D:/Apps", "dir": str(perfil)}]}))
    monkeypatch.setattr(install, "HOME", str(home))
    monkeypatch.setattr(install, "LIENZO_HOME", str(lienzo))
    rutas = install.claude_settings()
    assert rutas == [os.path.join(str(home), ".claude", "settings.json"), os.path.join(str(perfil), "settings.json")]
    install.merge_hooks(rutas[1], "claude", install.CLAUDE_EVENTS, False)
    hooks = json.loads((perfil / "settings.json").read_text())["hooks"]
    assert hooks["PreToolUse"][0]["matcher"] == "Bash" and "async" not in hooks["PreToolUse"][0]["hooks"][0]
    assert "async" not in hooks["SessionStart"][0]["hooks"][0]
    assert "async" in hooks["Stop"][0]["hooks"][0]
