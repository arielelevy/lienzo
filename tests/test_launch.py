"""Plan multi-PC, ronda 2, encargo B (F3): lienzo/launch.py escribe el .cmd para lanzar una sesion
nueva en esta PC y lo abre con explorer.exe (nunca una terminal de verdad: subprocess.Popen queda
mockeado en todo el archivo). Rechaza un cwd fuera de launch_roots (vacia = no se lanza nada) y un
agente desconocido, y sanea el titulo antes de escribirlo (nunca se interpreta como comando). Ver
docs/ronda2/encargo-B.md."""

import os
import sys
from typing import ClassVar

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401
import launch
import state as st


class FakePopen:
    """subprocess.Popen mockeado: registra el argv, no abre ninguna terminal de verdad."""

    calls: ClassVar[list[list[str]]] = []

    def __init__(self, argv, *a, **k):
        FakePopen.calls.append(list(argv))


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / ".lienzo"))
    monkeypatch.setattr(st, "HOME", str(tmp_path / "home"))
    monkeypatch.setattr(launch.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(launch, "_existe", lambda p: True)
    bin_dir = tmp_path / "home" / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for exe in launch.AGENT_EXES.values():
        (bin_dir / exe).write_text("")
    FakePopen.calls = []
    yield tmp_path


def con_roots(monkeypatch, *roots) -> None:
    monkeypatch.setattr(st, "load_config", lambda: {"launch_roots": [str(r) for r in roots]})


def sin_roots(monkeypatch) -> None:
    monkeypatch.setattr(st, "load_config", dict)


# --- agente desconocido y cwd fuera de launch_roots: rechazo sin tocar nada -------------------


def test_agente_desconocido_se_rechaza(aislado, monkeypatch):
    con_roots(monkeypatch, aislado / "repos")
    res = launch.launch(str(aislado / "repos" / "x"), "titulo", "gemini")
    assert res == {"ok": False, "error": "agente desconocido: 'gemini'"}
    assert FakePopen.calls == []


def test_launch_roots_vacia_no_lanza_nada(aislado, monkeypatch):
    sin_roots(monkeypatch)
    res = launch.launch(str(aislado / "cualquiera"), "titulo", "claude")
    assert res["ok"] is False
    assert FakePopen.calls == []
    assert not os.path.isdir(os.path.join(st.LIENZO, "launch"))


def test_cwd_fuera_de_launch_roots_se_rechaza(aislado, monkeypatch):
    con_roots(monkeypatch, aislado / "repos")
    res = launch.launch(str(aislado / "otra-cosa" / "proyecto"), "titulo", "claude")
    assert res["ok"] is False
    assert FakePopen.calls == []


def test_cwd_dentro_de_un_subdirectorio_de_launch_roots_se_acepta(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    cwd = root / "proyecto" / "sub"
    res = launch.launch(str(cwd), "titulo", "claude")
    assert res["ok"] is True


def test_cwd_con_comilla_se_rechaza(aislado, monkeypatch):
    # una comilla en el cwd podria cerrar la de `cd /d "..."` antes de tiempo en el .cmd
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root) + '\\raro"', "titulo", "claude")
    assert res["ok"] is False
    assert FakePopen.calls == []


# --- lanzamiento normal: .cmd escrito y abierto con explorer.exe, nunca una terminal real ------


def test_launch_escribe_el_cmd_y_lo_abre_con_explorer(aislado, monkeypatch):
    root = aislado / "repos"
    cwd = root / "proyecto"
    con_roots(monkeypatch, root)
    res = launch.launch(str(cwd), "mi sesion", "claude")
    assert res["ok"] is True
    cmd_path = res["cmd_path"]
    assert os.path.isfile(cmd_path)
    assert cmd_path.startswith(os.path.join(st.LIENZO, "launch"))
    with open(cmd_path, encoding="cp1252", newline="") as f:
        cuerpo = f.read()  # newline="": sin traduccion universal, para ver el CRLF tal cual se escribio
    assert "chcp 1252" in cuerpo
    assert "title mi sesion" in cuerpo
    assert f'cd /d "{cwd}"' in cuerpo
    exe_esperado = os.path.join(st.HOME, ".local", "bin", "claude.exe")
    assert f'"{exe_esperado}"' in cuerpo
    assert "\r\n" in cuerpo
    assert FakePopen.calls == [["explorer.exe", cmd_path]]


@pytest.mark.parametrize(
    "agent,exe", [("claude", "claude.exe"), ("codex", "codex.exe"), ("pi", "pi.exe"), ("coda", "coda.exe")]
)
def test_cada_agente_usa_su_ejecutable(aislado, monkeypatch, agent, exe):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "proyecto"), "t", agent)
    assert res["ok"] is True
    with open(res["cmd_path"], encoding="cp1252") as f:
        cuerpo = f.read()
    assert os.path.join(st.HOME, ".local", "bin", exe) in cuerpo


# --- el titulo se sanea: nunca se interpreta como comando --------------------------------------


def test_titulo_con_metacaracteres_se_limpia(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "proyecto"), 'hola & del /f * "x" % raro ^ mas', "claude")
    assert res["ok"] is True
    with open(res["cmd_path"], encoding="cp1252") as f:
        cuerpo = f.read()
    linea_titulo = next(l for l in cuerpo.splitlines() if l.startswith("title "))
    assert "&" not in linea_titulo
    assert '"' not in linea_titulo
    assert "%" not in linea_titulo
    assert "^" not in linea_titulo


def test_titulo_vacio_no_deja_la_linea_en_blanco(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "proyecto"), "   ", "claude")
    assert res["ok"] is True
    with open(res["cmd_path"], encoding="cp1252") as f:
        cuerpo = f.read()
    assert "title lienzo" in cuerpo


def test_cwd_que_no_existe_se_rechaza(aislado, monkeypatch):
    monkeypatch.setattr(launch, "_existe", os.path.isdir)
    con_roots(monkeypatch, aislado / "repos")
    res = launch.launch(str(aislado / "repos" / "no-esta"), "titulo", "claude")
    assert res["ok"] is False
    assert FakePopen.calls == []


def test_cwd_con_porcentaje_se_rechaza(aislado, monkeypatch):
    # adentro del .cmd, %PATH% se expande aunque vaya entre comillas
    con_roots(monkeypatch, aislado / "repos")
    res = launch.launch(str(aislado / "repos" / "%PATH%"), "titulo", "claude")
    assert res["ok"] is False
    assert FakePopen.calls == []


def test_ejecutable_que_no_esta_se_informa(aislado, monkeypatch):
    con_roots(monkeypatch, aislado / "repos")
    os.remove(os.path.join(st.HOME, ".local", "bin", "coda.exe"))
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    res = launch.launch(str(aislado / "repos" / "x"), "titulo", "coda")
    assert res == {"ok": False, "error": "no encuentro coda.exe en esta PC"}


# --- Mac/Linux/WSL: adentro de tmux, o el lienzo la ve pero no le puede escribir ------------------


def test_fuera_de_windows_lanza_adentro_de_tmux_sin_el_entorno_de_claude(aislado, monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", False)
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    (aislado / "home" / ".local" / "bin" / "claude").write_text("")
    res = launch.launch(str(root / "proyecto"), "miapp - encargo A & rm -rf", "claude")
    assert res["ok"] is True and res["tmux_session"].startswith("lienzo-")
    assert not os.path.exists(os.path.join(st.LIENZO, "launch")), "sin .cmd fuera de Windows"
    (argv,) = FakePopen.calls
    assert argv[:9] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        res["tmux_session"],
        "-n",
        "miapp - encargo A rm -rf",
        "-c",
        str(root / "proyecto"),
    ]
    assert argv[9] == "env" and argv[-1] == os.path.join(st.HOME, ".local", "bin", "claude")
    assert ["-u", "CLAUDECODE"] == argv[10:12], "un claude hijo con CLAUDECODE se cree anidado y se apaga"


def test_fuera_de_windows_busca_el_ejecutable_sin_exe(aislado, monkeypatch):
    monkeypatch.setattr(launch, "WINDOWS", False)
    con_roots(monkeypatch, aislado / "repos")
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    res = launch.launch(str(aislado / "repos" / "x"), "titulo", "codex")
    assert res == {"ok": False, "error": "no encuentro codex en esta PC"}
    assert FakePopen.calls == []


def _cuerpo_del_cmd(res):
    with open(res["cmd_path"], encoding="cp1252", newline="") as f:
        return f.read()


def test_modelo_va_como_dash_dash_model_en_coda(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "coda", model="globant_dgx/GLM-5.3-Flash")
    assert res["ok"] is True and res["model_applied"] is True
    assert " --model globant_dgx/GLM-5.3-Flash\r\n" in _cuerpo_del_cmd(res)


def test_sin_modelo_la_respuesta_no_trae_model_applied(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "coda")
    assert "model_applied" not in res and "--model" not in _cuerpo_del_cmd(res)


@pytest.mark.parametrize("malo", ["x & calc", "a b", 'x"y', "x|y", "%PATH%", "x^y", "", "a" * 81, "x\r\ncalc"])
def test_modelo_con_metacaracteres_no_entra_al_cmd(aislado, monkeypatch, malo):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "coda", model=malo)
    assert res["ok"] is True and res["model_applied"] is False
    cuerpo = _cuerpo_del_cmd(res)
    assert "--model" not in cuerpo and "calc" not in cuerpo.lower().replace("coda", "")


def test_pi_no_recibe_modelo(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "pi", model="algo")
    assert res["model_applied"] is False and "--model" not in _cuerpo_del_cmd(res)


def test_modelo_y_resume_se_combinan(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "claude", resume="0a1de326-0f51-41f4-8ca7-4807e11950f3", model="opus")
    cuerpo = _cuerpo_del_cmd(res)
    assert res["resumed"] is True and res["model_applied"] is True
    assert " --resume 0a1de326-0f51-41f4-8ca7-4807e11950f3 --model opus\r\n" in cuerpo
