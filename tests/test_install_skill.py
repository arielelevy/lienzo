"""Tests de install.link_skills: el skill lienzo enlazado en la carpeta de skills de cada CLI (Claude
Code y Kiro no leen ~/.agents/skills). Usa carpetas temporales y enlaces reales; nunca toca el HOME."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import install


def _dirs(tmp_path):
    return {cli: str(tmp_path / cli / "skills") for cli in ("claude", "kiro", "agents")}


def test_enlaza_en_todas_y_se_lee_el_skill(tmp_path):
    dirs = _dirs(tmp_path)
    r = install.link_skills(False, dirs=dirs)
    assert [e for _, _, e in r] == ["enlazado"] * 3
    for base in dirs.values():
        with open(os.path.join(base, "lienzo", "SKILL.md"), encoding="utf-8") as f:
            assert f.read().startswith("---\nname: lienzo")


def test_idempotente(tmp_path):
    dirs = _dirs(tmp_path)
    install.link_skills(False, dirs=dirs)
    assert [e for _, _, e in install.link_skills(False, dirs=dirs)] == ["ya enlazado"] * 3


def test_no_pisa_otro_skill_lienzo(tmp_path):
    dirs = _dirs(tmp_path)
    ajeno = os.path.join(dirs["kiro"], "lienzo")
    os.makedirs(ajeno)
    with open(os.path.join(ajeno, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("copia vieja")
    r = {cli: e for cli, _, e in install.link_skills(False, dirs=dirs)}
    assert r["kiro"] == "otro skill lienzo, no se toca"
    with open(os.path.join(ajeno, "SKILL.md"), encoding="utf-8") as f:
        assert f.read() == "copia vieja"
    # desinstalar tampoco la borra: no apunta a este repo
    r = {cli: e for cli, _, e in install.link_skills(True, dirs=dirs)}
    assert r["kiro"] == "sin cambios" and os.path.isdir(ajeno)


def test_desinstalar_quita_solo_el_enlace(tmp_path):
    dirs = _dirs(tmp_path)
    install.link_skills(False, dirs=dirs)
    assert [e for _, _, e in install.link_skills(True, dirs=dirs)] == ["quitado"] * 3
    assert not any(os.path.lexists(os.path.join(b, "lienzo")) for b in dirs.values())
    assert os.path.isfile(os.path.join(install.SKILL, "SKILL.md"))  # el skill del repo sigue


def test_dry_run_no_escribe(tmp_path):
    dirs = _dirs(tmp_path)
    assert [e for _, _, e in install.link_skills(False, dry_run=True, dirs=dirs)] == ["enlazado"] * 3
    assert not any(os.path.exists(b) for b in dirs.values())
