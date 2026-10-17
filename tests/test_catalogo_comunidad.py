"""Capacidades de comunidad: disponibilidad comprobable, sin ejecución ni instalaciones."""

import json
from types import SimpleNamespace

import agent_improvements
import plugins
import pytest
import tools
from tools import anatomy
from tools import better_claude as bc


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def install(home, *, enabled=True, scope="user"):
    folder = home / "cache/commit/.claude-plugin"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text('{"name":"commit"}', encoding="utf-8")
    (home / "plugins").mkdir()
    (home / "plugins/installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {"commit@better-claude": [{"scope": scope, "installPath": str(folder.parent)}]},
            }
        ),
        encoding="utf-8",
    )
    (home / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"commit@better-claude": enabled}}), encoding="utf-8"
    )


def test_missing_install_does_not_create_state(claude_home):
    assert bc._estado("commit", None)["disponible"] is False
    assert list(claude_home.iterdir()) == []


@pytest.mark.parametrize(
    "enabled,scope,ready", [(True, "user", True), (False, "user", False), (True, "project", False)]
)
def test_installation_enabled_and_scope_are_different(claude_home, enabled, scope, ready):
    install(claude_home, enabled=enabled, scope=scope)
    before = {str(p): p.read_bytes() for p in claude_home.rglob("*") if p.is_file()}
    result = bc._estado("commit", None)
    assert result["disponible"] is ready
    assert {str(p): p.read_bytes() for p in claude_home.rglob("*") if p.is_file()} == before
    assert bc._estado("commit", "Ubuntu")["disponible"] is False


def test_stale_registry_and_corrupt_settings_are_visible(claude_home):
    install(claude_home)
    manifest = claude_home / "cache/commit/.claude-plugin/plugin.json"
    manifest.unlink()
    assert "ausentes" in bc._estado("commit", None)["detalle"]
    manifest.write_text('{"name":"commit"}', encoding="utf-8")
    (claude_home / "settings.json").write_text("not-json", encoding="utf-8")
    entry = next(t for t in tools.resumen() if t["id"] == "commit")
    assert entry["estado"]["disponible"] is False
    assert "settings.json" in entry["estado"]["detalle"]


@pytest.mark.parametrize("body", ['{"name":"otro"}', "not-json"])
def test_manifest_is_validated_before_claiming_installation(claude_home, body):
    install(claude_home)
    (claude_home / "cache/commit/.claude-plugin/plugin.json").write_text(body, encoding="utf-8")
    entry = next(t for t in tools.resumen() if t["id"] == "commit")
    assert entry["estado"]["disponible"] is False
    assert "no se pudo verificar" in entry["estado"]["detalle"]


# Manifiestos publicados (midudev/better-claude a817804, 2026-10-16), en el registro que escribe Claude Code
UPSTREAM = {"commit": "0.2.0", "sub-meter": "0.1.0"}


def test_upstream_manifests_are_recognized_with_installed_version(claude_home):
    registry = {}
    for name, version in UPSTREAM.items():
        folder = claude_home / f"plugins/cache/better-claude/{name}/{version}"
        (folder / ".claude-plugin").mkdir(parents=True)
        manifest = {"name": name, "version": version, "author": {"name": "midudev"}, "license": "MIT"}
        (folder / ".claude-plugin/plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        registry[f"{name}@better-claude"] = [
            {"scope": "user", "installPath": str(folder), "version": version, "gitCommitSha": "a817804"}
        ]
    (claude_home / "plugins/installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": registry}), encoding="utf-8"
    )
    (claude_home / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"commit@better-claude": True, "sub-meter@better-claude": False}}),
        encoding="utf-8",
    )
    states = {t["id"]: t["estado"] for t in tools.resumen() if t["id"] in UPSTREAM}
    # Sub Meter (e Image Preview) se usan en Claude Code pero no son fichas de Lienzo
    assert list(states) == ["commit"]
    assert states["commit"]["version_instalada"] == "0.2.0" and states["commit"]["disponible"] is True
    assert states["commit"]["instalado"] is True
    assert bc._estado("sub-meter", None)["disponible"] is False  # instalado pero deshabilitado


def test_stale_record_does_not_hide_a_valid_one(claude_home):
    install(claude_home)
    registry = claude_home / "plugins/installed_plugins.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    records = data["plugins"]["commit@better-claude"]
    records.insert(0, {"scope": "user", "installPath": "relativa"})
    registry.write_text(json.dumps(data), encoding="utf-8")
    assert bc._estado("commit", None)["disponible"] is True
    del records[1]
    registry.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="ruta absoluta"):
        bc._estado("commit", None)


def test_metadata_preserves_limits_and_does_not_inject_or_run(claude_home):
    for tool in bc.TOOLS:
        assert tool.formato == "plugin-claude" and tool.compatible_con == ("claude",)
        assert tool.preferencia is None and tool.instruccion is None
    commit = tools.por_id("commit")
    assert any("commit y push" in limit for limit in commit.limitaciones)
    assert any("rama nueva también hace push" in limit for limit in commit.limitaciones)
    assert "--scope user" in commit.instalar


def test_anatomy_reuses_existing_kit_and_does_not_claim_wsl(tmp_path, monkeypatch):
    monkeypatch.setenv("ANATOMY_DIR", str(tmp_path))
    assert anatomy._estado(None)["disponible"] is False
    for name in ("SKILL.md", "kit/iso-kit.mjs", "kit/tube.mjs", "kit/lathe.mjs"):
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("fixture", encoding="utf-8")
    assert anatomy._estado(None)["disponible"] is True
    assert anatomy._estado("Ubuntu")["disponible"] is False


def test_local_plugin_without_tools_is_separate_and_readonly(monkeypatch, claude_home):
    def forbidden(*args):
        raise AssertionError("inventario no puede llamar al plugin")

    monkeypatch.setattr(
        plugins, "_cargados", {"stepwise": SimpleNamespace(get=forbidden, post=forbidden, iniciar=forbidden)}
    )
    monkeypatch.setattr(plugins, "_fichas", {})
    monkeypatch.setattr(plugins, "_vista", lambda nombre: False)
    status = agent_improvements.status()
    (local,) = status["plugins"]
    assert local["id"] == "stepwise" and local["cargado"] is True
    assert "tools" not in local
    assert "stepwise" not in [t["id"] for t in status["tools"]]
    # legacy: sin manifiesto no se inventan permisos ni salud
    assert local["manifiesto"] == "ausente" and local["estado"] == "cargado"
    assert local["permisos"] is None and local["salud"] is None
    assert local["puntos"] == ["get", "post"] and local["ciclo_de_vida"] == ["iniciar"]
    assert "no acredita conexión" in local["detalle"]
