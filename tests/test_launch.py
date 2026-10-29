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
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(launch.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(launch, "_existe", lambda p: True)
    monkeypatch.setattr(launch, "_physical_path", lambda p: os.path.normcase(os.path.normpath(p)))
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
    assert "title proyecto ^| mi sesion" in cuerpo
    assert f'cd /d "{cwd}"' in cuerpo
    exe_esperado = os.path.join(st.HOME, ".local", "bin", "claude.exe")
    assert f'"{exe_esperado}"' in cuerpo
    assert "\r\n" in cuerpo
    assert FakePopen.calls == [["explorer.exe", cmd_path]]


def test_codex_deja_titulo_a_lienzo_solo_en_la_invocacion(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "lienzo"), "Lienzo - Lienzo | encargo A - prueba", "codex")
    with open(res["cmd_path"], encoding="cp1252") as archivo:
        cuerpo = archivo.read()
    assert "title lienzo ^| encargo A - prueba" in cuerpo
    assert "-c tui.terminal_title=[]" in cuerpo
    assert cuerpo.count("tui.terminal_title") == 1
    assert "-c tui.notifications=false" in cuerpo


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
    assert "^|" in linea_titulo  # el separador queda literal, no crea un pipeline de cmd
    assert "^" not in linea_titulo.replace("^|", "")


def test_titulo_vacio_no_deja_la_linea_en_blanco(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "proyecto"), "   ", "claude")
    assert res["ok"] is True
    with open(res["cmd_path"], encoding="cp1252") as f:
        cuerpo = f.read()
    assert "title proyecto ^| sesión" in cuerpo


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
        "miapp | encargo A rm -rf",
        "-c",
        str(root / "proyecto"),
    ]
    exe = os.path.join(st.HOME, ".local", "bin", "claude")
    # el nombre corto para el canal nativo, sin el & ni nada que se interprete
    assert argv[9] == "env" and argv[-5:] == [exe, "-n", "miapp-A-rm--rf", "--remote-control", "miapp-A-rm--rf"]
    assert ["-u", "CLAUDECODE"] == argv[10:12], "un claude hijo con CLAUDECODE se cree anidado y se apaga"
    assert res["native_name"] == "miapp-A-rm--rf"


def test_nombre_corto_para_el_canal_nativo():
    assert launch.nombre_corto("chesstudia - encargo I - pasaje formateado") == "chesstudia-I"
    assert launch.nombre_corto("chesstudia - coordinadora - ronda 1006") == "chesstudia-coordinadora"
    assert launch.nombre_corto("chesstudia - encargo Ñ - la Biblioteca") == "chesstudia-N"
    assert launch.nombre_corto("Canal nativo entre PCs") == "Canal-nativo-entre-PCs"
    assert launch.nombre_corto("") == ""
    # solo claude se deja nombrar; sin titulo no hay nombre
    assert launch._nombre_args("codex", "app - encargo A - x") == []
    assert launch._nombre_args("claude", "") == []


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
    assert " --resume 0a1de326-0f51-41f4-8ca7-4807e11950f3 --model opus -n t --remote-control t\r\n" in cuerpo


def test_dialogo_de_remote_control_nunca_elige_desconectar():
    import sessions as ses

    apagado = {
        "question": "Remote Control",
        "options": [
            {"n": 1, "text": "Enable Remote Control  Opens a secure connection"},
            {"n": 2, "text": "Never mind"},
        ],
    }
    prendido = {
        "question": "Remote Control",
        "options": [{"n": 1, "text": "Disconnect this session"}, {"n": 2, "text": "Keep it"}],
    }
    otro = {"question": "Switch model?", "options": [{"n": 1, "text": "Yes"}]}
    assert ses._opcion_remote_control(apagado) == 1
    assert ses._opcion_remote_control(prendido) == 2
    assert ses._opcion_remote_control(otro) is None


def test_exe_path_encuentra_pi_cmd_y_kiro_en_program_files(tmp_path, monkeypatch):
    """pi.dev en Windows deja pi.cmd en ~/.pi/agent/bin, y Kiro con admin queda en Program Files
    (ar-it33940, 2026-10-09): Lanzar CLI decia «no encuentro pi.exe»."""
    monkeypatch.setattr(launch.state, "HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    assert launch._exe_path("pi.exe") is None
    pi = tmp_path / ".pi" / "agent" / "bin" / "pi.cmd"
    pi.parent.mkdir(parents=True)
    pi.write_text("@echo off\n")
    assert launch._exe_path("pi.exe") == str(pi)
    kiro = tmp_path / "pf" / "Kiro-Cli" / "kiro-cli.exe"
    kiro.parent.mkdir(parents=True)
    kiro.write_text("")
    assert launch._exe_path("kiro-cli.exe") == str(kiro)
    # un .cmd de npm en el PATH, si no hay .exe
    monkeypatch.setattr(launch.shutil, "which", lambda name: "C:/npm/codex.cmd" if name == "codex.cmd" else None)
    assert launch._exe_path("codex.exe") == "C:/npm/codex.cmd"


def test_codex_official_installation_wins_over_old_local_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    old = tmp_path / ".local" / "bin" / "codex.exe"
    old.parent.mkdir(parents=True)
    old.write_text("old")
    managed = tmp_path / "local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    managed.parent.mkdir(parents=True)
    managed.write_text("managed")
    assert launch._exe_path("codex.exe") == str(managed)


def test_chrome_suma_dash_dash_chrome_solo_si_se_pide(aislado, monkeypatch):
    root = aislado / "repos"
    con_roots(monkeypatch, root)
    assert "--chrome" not in _cuerpo_del_cmd(launch.launch(str(root / "p"), "t", "claude"))
    res = launch.launch(str(root / "p"), "t", "claude", chrome=True)
    assert res["ok"] is True and " --chrome\r\n" in _cuerpo_del_cmd(res)


@pytest.mark.parametrize(("agent", "distro"), [("codex", None), ("claude", "Ubuntu")])
def test_chrome_fuera_de_claude_en_windows_se_rechaza_sin_lanzar(aislado, monkeypatch, agent, distro):
    con_roots(monkeypatch, aislado / "repos")
    res = launch.launch(str(aislado / "repos" / "p"), "t", agent, distro=distro, chrome=True)
    assert res == {"ok": False, "error": "chrome requiere una sesión Claude en Windows nativo"}
    assert FakePopen.calls == []


# --- claude_config_dirs: la cuenta de Claude según la carpeta (pedido de Ariel, 2026-10-29) -----


def con_cuentas(monkeypatch, roots, rules) -> None:
    config = {"launch_roots": [str(r) for r in roots], "claude_config_dirs": rules}
    monkeypatch.setattr(st, "load_config", lambda: config)


def test_claude_bajo_la_raiz_nace_con_el_perfil_de_la_regla(aislado, monkeypatch):
    root = aislado / "repos"
    con_cuentas(monkeypatch, [root], [{"root": str(root / "apps"), "dir": "~/.claude-smartbi"}])
    res = launch.launch(str(root / "apps" / "opensyync"), "t", "claude")
    perfil = os.path.join(st.HOME, ".claude-smartbi")
    assert res["ok"] is True and res["claude_config_dir"] == perfil
    cuerpo = _cuerpo_del_cmd(res)
    assert f'set "CLAUDE_CONFIG_DIR={perfil}"\r\n"' in cuerpo
    assert cuerpo.index("cd /d") < cuerpo.index('set "CLAUDE_CONFIG_DIR') < cuerpo.index('.exe"')


def test_fuera_de_la_raiz_y_otros_agentes_no_cambian_de_perfil(aislado, monkeypatch):
    root = aislado / "repos"
    con_cuentas(monkeypatch, [root], [{"root": str(root / "apps"), "dir": "~/.claude-smartbi"}])
    for cwd, agent in ((root / "otro", "claude"), (root / "apps" / "x", "codex")):
        res = launch.launch(str(cwd), "t", agent)
        assert res["ok"] is True and "claude_config_dir" not in res
        assert "CLAUDE_CONFIG_DIR" not in _cuerpo_del_cmd(res)


def test_gana_la_raiz_mas_larga(aislado, monkeypatch):
    root = aislado / "repos"
    rules = [
        {"root": str(root / "apps" / "cliente"), "dir": str(aislado / "perfil-cliente")},
        {"root": str(root / "apps"), "dir": str(aislado / "perfil-apps")},
    ]
    con_cuentas(monkeypatch, [root], rules)
    assert launch.launch(str(root / "apps" / "cliente" / "p"), "t", "claude")["claude_config_dir"] == str(
        aislado / "perfil-cliente"
    )
    assert launch.launch(str(root / "apps" / "p"), "t", "claude")["claude_config_dir"] == str(aislado / "perfil-apps")


@pytest.mark.parametrize(
    ("dir_", "error"),
    [
        (None, "claude_config_dirs: la regla no tiene dir"),
        ("C:/perfil%USERNAME%", "claude_config_dirs: dir con caracteres inseguros para cmd"),
        ('C:/a" & calc', "claude_config_dirs: dir con caracteres inseguros para cmd"),
        ("relativo/perfil", None),
    ],
)
def test_regla_que_aplica_y_esta_mal_no_lanza_con_otra_cuenta(aislado, monkeypatch, dir_, error):
    root = aislado / "repos"
    con_cuentas(monkeypatch, [root], [{"root": str(root), "dir": dir_}])
    res = launch.launch(str(root / "p"), "t", "claude")
    assert res["ok"] is False
    assert res["error"] == error if error else res["error"].startswith("claude_config_dirs: no existe")
    assert FakePopen.calls == []


def test_perfil_inexistente_no_lanza(aislado, monkeypatch):
    root = aislado / "repos"
    con_cuentas(monkeypatch, [root], [{"root": str(root), "dir": str(aislado / "no-esta")}])
    monkeypatch.setattr(launch, "_existe", lambda p: "no-esta" not in p)
    res = launch.launch(str(root / "p"), "t", "claude")
    assert res["ok"] is False and res["error"].startswith("claude_config_dirs: no existe")
    assert FakePopen.calls == []


@pytest.mark.parametrize(
    ("opciones", "error"),
    [
        ({"distro": "Ubuntu"}, "claude_config_dirs aplica sólo a Claude fuera de WSL"),
        ({"claude_pipe": True}, "claude_pipe todavía no soporta claude_config_dirs"),
    ],
)
def test_wsl_y_claude_pipe_con_regla_se_rechazan(aislado, monkeypatch, opciones, error):
    root = aislado / "repos"
    con_cuentas(monkeypatch, [root], [{"root": str(root), "dir": "~/.claude-smartbi"}])
    assert launch.launch(str(root / "p"), "t", "claude", **opciones) == {"ok": False, "error": error}
    assert FakePopen.calls == []


def test_retomar_una_sesion_del_perfil_de_siempre_no_la_pierde(aislado, monkeypatch):
    root = aislado / "repos"
    sid = "0a1de326-0f51-41f4-8ca7-4807e11950f3"
    con_cuentas(monkeypatch, [root], [{"root": str(root), "dir": "~/.claude-smartbi"}])
    default = aislado / "home" / ".claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(default))
    (default / "projects" / "D--repos-p").mkdir(parents=True)
    (default / "projects" / "D--repos-p" / f"{sid}.jsonl").write_text("")
    res = launch.launch(str(root / "p"), "t", "claude", resume=sid)
    assert res["ok"] is True and res["resumed"] is True and "claude_config_dir" not in res
    assert "CLAUDE_CONFIG_DIR" not in _cuerpo_del_cmd(res)
    assert "perfil de Claude donde está guardada" in res["aviso"]
    smartbi = aislado / "home" / ".claude-smartbi" / "projects" / "D--repos-p"
    smartbi.mkdir(parents=True)
    (smartbi / f"{sid}.jsonl").write_text("")
    res = launch.launch(str(root / "p"), "t", "claude", resume=sid)
    assert res["claude_config_dir"] == os.path.join(st.HOME, ".claude-smartbi")


def test_tmux_pasa_el_perfil_por_env(aislado, monkeypatch):
    res = launch._launch_tmux("/home/a/apps/p", "t", "/usr/bin/claude", [], config_dir="/home/a/.claude-smartbi")
    argv = FakePopen.calls[-1]
    assert res["ok"] is True
    assert argv[argv.index("env") :][-2:] == ["CLAUDE_CONFIG_DIR=/home/a/.claude-smartbi", "/usr/bin/claude"]
