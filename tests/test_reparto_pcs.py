"""Reparto entre PCs como sugerencia con OK de Ariel (decisión 23, 2026-10-22): `coordinar.repartir`
arma el plan con módulos disjuntos, una PC commiter por PC y la rama `ronda-<fecha>`;
`coordinar.sincronizar_ronda` hace `pull --rebase` y `push` sin `--force`, y ante conflicto o
archivos fuera de lo repartido frena y avisa. El git es real: un remoto bare y dos clones, uno por
PC, en temporales fuera del repo."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c

MODULOS = {
    "emergencia": ["lienzo/emergencia.py", "web/src/components/PcStrip.tsx"],
    "reparto": ["skills/lienzo/coordinar.py"],
    "linux": ["docs/linux.md", "lienzo/hooks"],
}


def test_repartir_es_sugerencia_disjunta_y_pareja():
    plan = c.repartir("lienzo", MODULOS, ["ariel", "ar-it33940"], fecha="2026-10-22")
    assert plan["aprobado"] is False, "es una sugerencia: hasta el OK de Ariel no se aplica"
    assert plan["rama"] == "ronda-2026-10-22"
    asignados = [m for pc in plan["pcs"].values() for m in pc["modulos"]]
    assert sorted(asignados) == sorted(MODULOS), "cada módulo en una sola PC"
    assert {pc: d["commiter"] for pc, d in plan["pcs"].items()} == {"ariel": "ariel", "ar-it33940": "ar-it33940"}
    cargas = sorted(len(d["archivos"]) for d in plan["pcs"].values())
    assert cargas == [2, 3], "carga pareja: 2 y 2, y el de una ruta a la primera"
    texto = " ".join(" ".join(paso) for d in plan["pcs"].values() for paso in d["pasos"])
    assert "--rebase" in texto
    assert "--force" not in texto and " -f" not in texto and "+" not in texto


def test_repartir_rechaza_modulos_que_se_pisan():
    with pytest.raises(ValueError, match="lienzo/hooks/x.py"):
        c.repartir("lienzo", {**MODULOS, "otro": ["lienzo/hooks/x.py"]}, ["a", "b"], fecha="2026-10-22")
    with pytest.raises(ValueError, match="se pisan"):
        c.repartir("lienzo", {"a": ["web/src"], "b": ["./web/src/App.tsx"]}, ["a", "b"], fecha="2026-10-22")


def test_repartir_valida_entradas():
    with pytest.raises(ValueError, match="PC"):
        c.repartir("lienzo", MODULOS, [], fecha="2026-10-22")
    with pytest.raises(ValueError, match="repetida"):
        c.repartir("lienzo", MODULOS, ["a", "a"], fecha="2026-10-22")
    with pytest.raises(ValueError, match="fuera"):
        c.repartir("lienzo", {"m": ["../otro/x.py"]}, ["a"], fecha="2026-10-22")
    with pytest.raises(ValueError, match="fecha"):
        c.repartir("lienzo", MODULOS, ["a"], fecha="22/10; rm -rf")


def test_fuera_de_reparto():
    plan = c.repartir("lienzo", MODULOS, ["ariel", "ar-it33940"], fecha="2026-10-22")
    pc = next(p for p, d in plan["pcs"].items() if "linux" in d["modulos"])
    assert c.fuera_de_reparto(plan, pc, ["lienzo/hooks/claude.py", "docs/linux.md"]) == []
    assert c.fuera_de_reparto(plan, pc, ["lienzo/hooks2.py", "README.md"]) == ["lienzo/hooks2.py", "README.md"]


# --- git real -----------------------------------------------------------------------------------


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def dos_pcs(tmp_path):
    remoto = tmp_path / "remoto.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remoto))
    semilla = tmp_path / "semilla"
    _git(tmp_path, "clone", str(remoto), str(semilla))
    for d in (semilla,):
        _git(d, "config", "user.email", "t@t")
        _git(d, "config", "user.name", "t")
    (semilla / "a.py").write_text("a = 1\n", encoding="utf-8")
    (semilla / "b.py").write_text("b = 1\n", encoding="utf-8")
    (semilla / "comun.md").write_text("uno\n", encoding="utf-8")
    _git(semilla, "add", ".")
    _git(semilla, "commit", "-m", "base")
    _git(semilla, "push", "origin", "HEAD:main")
    pcs = {}
    for nombre in ("pc1", "pc2"):
        d = tmp_path / nombre
        _git(tmp_path, "clone", str(remoto), str(d))
        _git(d, "config", "user.email", f"{nombre}@t")
        _git(d, "config", "user.name", nombre)
        pcs[nombre] = d
    plan = c.aprobar_reparto(c.repartir("x", {"A": ["a.py"], "B": ["b.py"]}, ["pc1", "pc2"], fecha="2026-10-22"))
    asignado = {pc: d["archivos"][0] for pc, d in plan["pcs"].items()}
    return remoto, pcs, plan, asignado


def _commit(d, archivo, texto):
    (d / archivo).write_text(texto, encoding="utf-8")
    _git(d, "add", archivo)
    _git(d, "commit", "-m", f"cambio {archivo}")


def test_sin_ok_no_sincroniza(dos_pcs):
    _remoto, pcs, _plan, _ = dos_pcs
    plan = c.repartir("x", {"A": ["a.py"]}, ["pc1"], fecha="2026-10-22")
    with pytest.raises(PermissionError, match="OK de Ariel"):
        c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")


def test_dos_pcs_disjuntas_suben_las_dos_sin_force(dos_pcs, monkeypatch):
    remoto, pcs, plan, asignado = dos_pcs
    vistos = []
    real = c._git_ronda
    monkeypatch.setattr(c, "_git_ronda", lambda cwd, *a: vistos.append(a) or real(cwd, *a))
    for pc in ("pc1", "pc2"):
        _commit(pcs[pc], asignado[pc], f"# {pc}\n")
    r1 = c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")
    r2 = c.sincronizar_ronda(str(pcs["pc2"]), plan, "pc2")
    assert r1["ok"] and r2["ok"], (r1, r2)
    log = _git(remoto, "log", "--format=%s", "ronda-2026-10-22")
    assert f"cambio {asignado['pc1']}" in log and f"cambio {asignado['pc2']}" in log
    planos = [" ".join(a) for a in vistos]
    assert any("pull --rebase" in p for p in planos)
    assert not any("--force" in p or " -f" in p or "+" in p for p in planos), planos


def test_conflicto_frena_aborta_el_rebase_y_no_sube(dos_pcs):
    """Las dos tocan el mismo archivo (no debería pasar con un reparto disjunto): la segunda frena,
    deja su commit local intacto, el rebase abortado y el remoto sin tocar."""
    remoto, pcs, plan, _ = dos_pcs
    plan["pcs"]["pc1"]["archivos"].append("comun.md")
    plan["pcs"]["pc2"]["archivos"].append("comun.md")  # forzado a mano: el plan lo habría rechazado
    _commit(pcs["pc1"], "comun.md", "pc1\n")
    _commit(pcs["pc2"], "comun.md", "pc2\n")
    assert c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")["ok"]
    antes = _git(remoto, "rev-parse", "ronda-2026-10-22")
    r = c.sincronizar_ronda(str(pcs["pc2"]), plan, "pc2")
    assert r["ok"] is False
    assert r["conflicto"] == ["comun.md"]
    assert "frená" in r["aviso"] or "conflicto" in r["aviso"]
    assert _git(remoto, "rev-parse", "ronda-2026-10-22") == antes
    assert not (pcs["pc2"] / ".git" / "rebase-merge").exists(), "el rebase quedó abortado"
    assert _git(pcs["pc2"], "log", "-1", "--format=%s") == "cambio comun.md"


def test_archivos_fuera_de_lo_repartido_frenan_antes_de_subir(dos_pcs):
    remoto, pcs, plan, asignado = dos_pcs
    ajeno = asignado["pc2"]
    _commit(pcs["pc1"], ajeno, "pc1 se metió\n")
    r = c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")
    assert r["ok"] is False and r["fuera"] == [ajeno]
    ramas = _git(remoto, "branch", "--list", "ronda-2026-10-22")
    assert ramas == "", "no subió nada"


def test_arbol_sucio_frena(dos_pcs):
    _remoto, pcs, plan, asignado = dos_pcs
    (pcs["pc1"] / asignado["pc1"]).write_text("sin commit\n", encoding="utf-8")
    r = c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")
    assert r["ok"] is False and "sin commitear" in r["aviso"]


def test_rutas_con_acentos_no_se_toman_por_ajenas(dos_pcs):
    """git cita y escapa las rutas no ASCII («docs/decisi\303\263n.md») sin core.quotePath=false."""
    _remoto, pcs, plan, _ = dos_pcs
    plan["pcs"]["pc1"]["archivos"].append("docs")
    (pcs["pc1"] / "docs").mkdir()
    _commit(pcs["pc1"], "docs/decisión.md", "hola\n")
    r = c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")
    assert r["ok"], r


def test_un_renombre_desde_lo_ajeno_frena(dos_pcs):
    """Con detección de renombres, `git mv b.py mio.py` lista sólo el destino y el borrado de lo
    ajeno pasaba sin control."""
    remoto, pcs, plan, asignado = dos_pcs
    ajeno = asignado["pc2"]
    plan["pcs"]["pc1"]["archivos"].append("mio.py")
    _git(pcs["pc1"], "mv", ajeno, "mio.py")
    _git(pcs["pc1"], "commit", "-m", "renombre")
    r = c.sincronizar_ronda(str(pcs["pc1"]), plan, "pc1")
    assert r["ok"] is False and r["fuera"] == [ajeno]
