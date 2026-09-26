"""lienzo/identity.py (plan multi-PC §3.1 identidad de la PC, §3.6 identidad del repo): pc_id y
pc_info sobre peer.json, y repo_key sobre el remote origin de un repo sin llamar a git."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# El orden importa: `from lienzo import server` es lo que agrega lienzo/ al sys.path (ver
# test_server.py); recien despues resuelven los imports sueltos de abajo.
from lienzo import server  # noqa: F401
import identity as idn
import state as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GITHUB_EQUIVALENTES = (
    "https://github.com/Ariel/Lienzo.git",
    "https://user:token@github.com/ariel/lienzo",
    "git@github.com:ariel/lienzo.git",
)


@pytest.fixture
def hogar(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / "estado"))
    idn._repo_cache.clear()
    return tmp_path


def _repo(dir_, remote=None):
    git = dir_ / ".git"
    git.mkdir(parents=True)
    body = "[core]\n\trepositoryformatversion = 0\n"
    if remote:
        body += f'[remote "origin"]\n\turl = {remote}\n'
    (git / "config").write_text(body, encoding="utf-8")
    return dir_


def _pc_id_en_otro_proceso(home) -> str:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from lienzo import server; import identity as idn; print(idn.pc_id())"
    )
    env = dict(os.environ)
    env["LIENZO_HOME"] = str(home)
    r = subprocess.run(
        [sys.executable, "-c", code, ROOT], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# --- pc_id / pc_info --------------------------------------------------------------------------


def test_pc_id_estable_entre_llamadas(hogar):
    a, b = idn.pc_id(), idn.pc_id()
    assert a == b
    assert len(a) == 12
    int(a, 16)  # es hex


def test_pc_id_se_crea_una_sola_vez(hogar):
    primero = idn.pc_id()
    peer = os.path.join(st.LIENZO, "peer.json")
    with open(peer, encoding="utf-8") as f:
        creado = f.read()
    assert idn.pc_id() == primero
    with open(peer, encoding="utf-8") as f:
        assert f.read() == creado


def test_peer_json_corrupto_se_regenera_sin_romper_el_arranque(hogar):
    os.makedirs(st.LIENZO, exist_ok=True)
    peer = os.path.join(st.LIENZO, "peer.json")
    with open(peer, "w", encoding="utf-8") as f:
        f.write("esto no es json valido {{{")
    nuevo = idn.pc_id()
    assert len(nuevo) == 12
    int(nuevo, 16)


def test_peer_json_sin_pc_id_tambien_se_regenera(hogar):
    os.makedirs(st.LIENZO, exist_ok=True)
    peer = os.path.join(st.LIENZO, "peer.json")
    with open(peer, "w", encoding="utf-8") as f:
        f.write('{"name": "sin id"}')
    nuevo = idn.pc_id()
    assert len(nuevo) == 12
    int(nuevo, 16)


def test_pc_info_trae_pc_id_nombre_y_color_de_la_paleta(hogar):
    info = idn.pc_info()
    assert info["pc_id"] == idn.pc_id()
    assert info["name"]
    assert info["color"] in idn.PALETTE


def test_set_name_cambia_el_nombre_sin_tocar_el_pc_id(hogar):
    antes = idn.pc_id()
    info = idn.set_name("notebook")
    assert info["name"] == "notebook"
    assert info["pc_id"] == antes
    assert idn.pc_info()["name"] == "notebook"
    assert idn.pc_id() == antes


def test_set_name_vacio_rechaza(hogar):
    with pytest.raises(ValueError):
        idn.set_name("   ")


def test_pc_id_estable_entre_procesos(hogar):
    primero = _pc_id_en_otro_proceso(st.LIENZO)
    assert primero == _pc_id_en_otro_proceso(st.LIENZO) == idn.pc_id()


def test_dos_lienzo_home_distintos_dan_pc_id_distintos(tmp_path):
    a = _pc_id_en_otro_proceso(tmp_path / "pc-a")
    b = _pc_id_en_otro_proceso(tmp_path / "pc-b")
    assert a != b
    assert a == _pc_id_en_otro_proceso(tmp_path / "pc-a")


# --- repo_key ----------------------------------------------------------------------------------


def test_repo_key_formas_equivalentes_de_github(hogar):
    claves = set()
    for i, url in enumerate(GITHUB_EQUIVALENTES):
        repo = _repo(hogar / f"repo{i}", remote=url)
        claves.add(idn.repo_key(str(repo)))
    assert claves == {"github.com/ariel/lienzo"}


def test_repo_key_ssh_uri(hogar):
    repo = _repo(hogar / "repo-ssh", remote="ssh://git@github.com/ariel/lienzo")
    assert idn.repo_key(str(repo)) == "github.com/ariel/lienzo"


def test_repo_key_sin_remote_usa_la_carpeta_raiz(hogar):
    repo = _repo(hogar / "sin-control-remoto")
    assert idn.repo_key(str(repo)) == "sin-control-remoto"


def test_repo_key_carpeta_fuera_de_un_repo(hogar):
    fuera = hogar / "no-es-un-repo"
    fuera.mkdir()
    assert idn.repo_key(str(fuera)) == "no-es-un-repo"


def test_repo_key_sin_cwd(hogar):
    assert idn.repo_key(None) == "?"


def test_repo_key_subcarpeta_del_repo(hogar):
    repo = _repo(hogar / "repo-anidado", remote="git@github.com:ariel/lienzo.git")
    sub = repo / "src" / "sub"
    sub.mkdir(parents=True)
    assert idn.repo_key(str(sub)) == "github.com/ariel/lienzo"


def test_repo_key_worktree(hogar):
    principal = _repo(hogar / "principal", remote="git@github.com:ariel/lienzo.git")
    admin = principal / ".git" / "worktrees" / "wt1"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text(os.path.relpath(str(principal / ".git"), str(admin)), encoding="utf-8")
    wt = hogar / "wt-aparte"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    assert idn.repo_key(str(wt)) == "github.com/ariel/lienzo"


def test_repo_key_recalcula_si_cambia_el_config(hogar):
    import time

    repo = _repo(hogar / "repo-cache", remote="git@github.com:ariel/uno.git")
    assert idn.repo_key(str(repo)) == "github.com/ariel/uno"
    time.sleep(0.05)
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:ariel/dos.git\n', encoding="utf-8")
    assert idn.repo_key(str(repo)) == "github.com/ariel/dos"


def test_repo_key_del_propio_lienzo(hogar):
    # el repo real de este encargo: sirve de humo end-to-end sobre un .git/config de verdad
    assert idn.repo_key(ROOT) == "github.com/arielelevy/lienzo"
