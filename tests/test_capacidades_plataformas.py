"""Las plataformas de cada agente salen de `windowsOnly` en agent-capabilities.json, el mismo dato que lee
el front (PENDIENTES, «Integración uniforme de CLI»: Kiro V3 limitado explícitamente a Windows)."""

import json
from pathlib import Path

from agentes import AGENTES

CAPS = json.loads((Path(__file__).parents[1] / "lienzo" / "agent-capabilities.json").read_text(encoding="utf-8"))


def test_kiro_y_antigravity_solo_windows_y_los_demas_en_todas():
    assert AGENTES["kiro"].supported_platforms == ("win32",)
    assert AGENTES["antigravity"].supported_platforms == ("win32",)
    for agente in ("claude", "codex", "pi", "coda"):
        assert set(AGENTES[agente].supported_platforms) == {"win32", "linux", "darwin"}


def test_python_y_el_front_leen_el_mismo_dato():
    for agente, perfil in AGENTES.items():
        assert (perfil.supported_platforms == ("win32",)) is bool(CAPS[agente].get("windowsOnly")), agente
