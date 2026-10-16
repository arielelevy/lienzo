"""Build de las infografías del lienzo (skills/lienzo-infografias), con el kit de anatomy real."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "lienzo-infografias"
VERSIONADAS = REPO / "docs" / "img" / "infografias"


def _anatomy() -> Path | None:
    for base in (
        os.environ.get("ANATOMY_DIR"),
        Path.home() / ".claude" / "skills" / "anatomy",
        Path.home() / ".agents" / "skills" / "anatomy",
    ):
        if base and (Path(base) / "kit" / "iso-kit.mjs").exists():
            return Path(base)
    return None


con_anatomy = pytest.mark.skipif(
    shutil.which("node") is None or _anatomy() is None, reason="hace falta node y la skill anatomy"
)


def _build(tmp_path: Path, *args: str, skill: Path = SKILL, env: dict | None = None, timeout: int = 120):
    entorno = {
        **os.environ,
        "LIENZO_INFOGRAFIAS_IMG": str(tmp_path / "img"),
        "LIENZO_INFOGRAFIAS_PREVIEW": str(tmp_path / "prev"),
        **(env or {}),
    }
    return subprocess.run(
        ["node", str(skill / "build.mjs"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=entorno,
        timeout=timeout,
    )


def _check(tmp_path: Path, *args: str, **kwargs):
    """--check necesita Chrome; la herramienta es opcional, así que sin Chrome se saltea."""
    hecho = _build(tmp_path, *args, "--check", timeout=300, **kwargs)
    if "No Chrome found" in hecho.stdout + hecho.stderr:
        pytest.skip("--check necesita Chrome o Chromium (o CHROME_PATH)")
    return hecho


@con_anatomy
def test_build_por_nombre_escribe_svg_estaticos_en_los_dos_temas(tmp_path):
    hecho = _build(tmp_path, "centralita")
    assert hecho.returncode == 0, hecho.stderr
    for tema in ("dark", "light"):
        svg = (tmp_path / "img" / f"centralita-{tema}.svg").read_text(encoding="utf-8")
        assert svg.startswith("<svg") and f'data-theme="{tema}"' in svg
        assert "<style>" in svg  # suelto: lleva sus estilos para verse en GitHub
        assert 'role="img"' in svg and "centralita telefónica" in svg
        assert "<script" not in svg and " onload=" not in svg and "requestAnimationFrame" not in svg
        assert (tmp_path / "prev" / f"centralita-{tema}.html").exists()
    assert not (VERSIONADAS.parent / "centralita-dark.svg").exists()


@con_anatomy
def test_los_svg_versionados_coinciden_con_el_build(tmp_path):
    hecho = _build(tmp_path)
    assert hecho.returncode == 0, hecho.stderr
    for armado in sorted((tmp_path / "img").glob("*.svg")):
        versionado = VERSIONADAS / armado.name
        assert versionado.exists(), f"falta versionar {armado.name}"
        assert armado.read_bytes() == versionado.read_bytes(), f"{armado.name} quedó viejo: correr build.mjs"


@con_anatomy
def test_nombre_inexistente_sale_2_y_lista_las_figuras(tmp_path):
    hecho = _build(tmp_path, "no-existe")
    assert hecho.returncode == 2
    assert "No existe la figura no-existe" in hecho.stderr and "centralita" in hecho.stderr
    assert not (tmp_path / "img").exists()


@con_anatomy
def test_opcion_desconocida_sale_2_sin_armar(tmp_path):
    hecho = _build(tmp_path, "centralita", "--chek")
    assert hecho.returncode == 2
    assert "No conozco --chek" in hecho.stderr
    assert not (tmp_path / "img").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")
def test_sin_anatomy_sale_2_con_la_instruccion(tmp_path):
    casa = tmp_path / "casa"
    casa.mkdir()
    hecho = _build(tmp_path, env={"ANATOMY_DIR": str(tmp_path / "vacio"), "USERPROFILE": str(casa), "HOME": str(casa)})
    assert hecho.returncode == 2
    assert "No encuentro la skill anatomy" in hecho.stderr and "ANATOMY_DIR" in hecho.stderr


@con_anatomy
def test_check_pasa_con_la_centralita(tmp_path):
    hecho = _check(tmp_path, "centralita")
    assert hecho.returncode == 0, hecho.stdout + hecho.stderr
    for tema in ("dark", "light"):
        assert f"centralita {tema}: console: clean · line ends: 0 " in hecho.stdout
        assert (tmp_path / "prev" / f"centralita-{tema}.png").stat().st_size > 10_000


@con_anatomy
def test_check_falla_si_una_linea_queda_suelta(tmp_path):
    copia = tmp_path / "skills" / "lienzo-infografias"
    shutil.copytree(SKILL, copia)
    (copia / "figuras" / "rota.mjs").write_text(
        'import { k, write } from "../kit.mjs";\n'
        "const P = k.fitProjection([[0, 0, 0], [40, 40, 20], [80, 60, 30]], 200, 160);\n"
        'const body = [k.solidSvg(k.slabOf({ x: 0, y: 0, w: 40, d: 40, r: 2 }, 0, 10, P), { tone: "mid" }),\n'
        '  k.lineSvg(k.segment([60, 60, 30], [80, 60, 30], P), { tone: "mid" })];\n'
        'export const build = () => write("rota", { width: 200, height: 160, label: "rota", body, card: { fig: "Fig 0", title: "Rota" } });\n',
        encoding="utf-8",
    )
    hecho = _check(tmp_path, "rota", skill=copia)
    assert hecho.returncode == 1, hecho.stdout + hecho.stderr
    assert "line ends: 0 " not in hecho.stdout and "line ends: 2 " in hecho.stdout
