"""El prefijo de los comandos de tmux se arma por pedido: sin distro el argv es el de hoy (en
Windows `wsl.exe tmux ...`, en Mac/Linux `tmux ...`), y con distro va `wsl.exe -d <distro> tmux ...`
para que cada comando llegue al tmux de la distro correcta. En nativo una distro pedida se ignora
(sin wsl.exe no hay distros). Todo mockeado: ninguna prueba corre wsl.exe de verdad."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
import launch
import tmux

FMT = "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}"


@pytest.fixture
def wsl(monkeypatch):
    """Windows con WSL, deterministico en cualquier SO donde corran las pruebas."""
    monkeypatch.setattr(tmux, "_PREFIX", ["wsl.exe"])
    monkeypatch.setattr(tmux, "_VIA_WSL", True)


@pytest.fixture
def nativo(monkeypatch):
    """Mac/Linux: prefijo vacio, sin WSL."""
    monkeypatch.setattr(tmux, "_PREFIX", [])
    monkeypatch.setattr(tmux, "_VIA_WSL", False)


@pytest.fixture
def tmux_llamadas(monkeypatch):
    """Captura los argv que _tmux manda por subproc.correr (rc 0, salida vacia)."""
    vistos = []

    def correr(argv, entrada=None, timeout=None):
        vistos.append(list(argv))
        return 0, "", ""

    monkeypatch.setattr(tmux.subproc, "correr", correr)
    return vistos


def test_argv_sin_distro_es_el_de_hoy(wsl):
    assert tmux._argv() == ["wsl.exe"]


def test_argv_nativo_es_vacio(nativo):
    assert tmux._argv() == []


def test_argv_con_distro_prefija_wsl_exe_d(wsl):
    assert tmux._argv("ubuntu") == ["wsl.exe", "-d", "ubuntu"]


def test_en_nativo_la_distro_se_ignora(nativo):
    assert tmux._argv("ubuntu") == []


def test_send_sin_distro_usa_el_argv_de_hoy(wsl, tmux_llamadas):
    assert tmux.send("%0", "hola")["ok"] is True
    assert tmux_llamadas == [
        ["wsl.exe", "tmux", "send-keys", "-t", "%0", "-l", "--", "hola"],
        ["wsl.exe", "tmux", "send-keys", "-t", "%0", "Enter"],
    ]


def test_send_con_distro_prefija_wsl_exe_d(wsl, tmux_llamadas):
    assert tmux.send("%0", "hola", distro="ubuntu")["ok"] is True
    assert tmux_llamadas == [
        ["wsl.exe", "-d", "ubuntu", "tmux", "send-keys", "-t", "%0", "-l", "--", "hola"],
        ["wsl.exe", "-d", "ubuntu", "tmux", "send-keys", "-t", "%0", "Enter"],
    ]


def test_send_de_tecla_con_distro(wsl, tmux_llamadas):
    assert tmux.send("%1", "", enter=False, key="escape", distro="debian")["ok"] is True
    assert tmux_llamadas == [["wsl.exe", "-d", "debian", "tmux", "send-keys", "-t", "%1", "Escape"]]


def test_send_nativo_no_prefija_nada_aunque_venga_distro(nativo, tmux_llamadas):
    assert tmux.send("%0", "hola", distro="ubuntu")["ok"] is True
    assert tmux_llamadas == [
        ["tmux", "send-keys", "-t", "%0", "-l", "--", "hola"],
        ["tmux", "send-keys", "-t", "%0", "Enter"],
    ]


def test_screen_con_y_sin_distro(wsl, tmux_llamadas):
    assert tmux.screen("%0")["ok"] is True
    assert tmux.screen("%0", scrollback=5, distro="ubuntu")["ok"] is True
    assert tmux_llamadas == [
        ["wsl.exe", "tmux", "capture-pane", "-p", "-t", "%0"],
        ["wsl.exe", "-d", "ubuntu", "tmux", "capture-pane", "-p", "-t", "%0", "-S", "-5"],
    ]


def test_list_panes_con_y_sin_distro(wsl, tmux_llamadas):
    tmux.list_panes()
    tmux.list_panes(distro="ubuntu")
    assert tmux_llamadas == [
        ["wsl.exe", "tmux", "list-panes", "-a", "-F", FMT],
        ["wsl.exe", "-d", "ubuntu", "tmux", "list-panes", "-a", "-F", FMT],
    ]


def test_list_panes_nativo(nativo, tmux_llamadas):
    tmux.list_panes(distro="ubuntu")
    assert tmux_llamadas == [["tmux", "list-panes", "-a", "-F", FMT]]


def test_ps_corre_en_la_distro_pedida(wsl, monkeypatch):
    """pid_alive, cmdline y comm van por la foto de `ps`, que debe correr en la distro de la tarjeta."""
    vistos = []

    def run(argv, **_k):
        vistos.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "  1  1  bash  bash\n", "")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    assert tmux.pid_alive(1, distro="ubuntu") is True
    assert tmux.cmdline(1, distro="ubuntu") == "bash"
    assert tmux.comm(1, distro="ubuntu") == "bash"
    assert vistos == [["wsl.exe", "-d", "ubuntu", "ps", "-axo", "pid=,ppid=,comm=,command="]] * 3


def test_proc_cwd_lee_readlink_en_la_distro_pedida(wsl, tmux_llamadas):
    assert tmux.proc_cwd(7, distro="ubuntu") == ""
    assert tmux_llamadas == [["wsl.exe", "-d", "ubuntu", "readlink", "/proc/7/cwd"]]


def test_all_agents_propaga_la_distro(wsl, monkeypatch):
    vistos = []
    monkeypatch.setattr(tmux, "_ps_all", lambda distro=None: vistos.append(("ps", distro)) or {})
    monkeypatch.setattr(tmux, "list_panes", lambda distro=None: vistos.append(("panes", distro)) or [])
    monkeypatch.setattr(tmux, "proc_cwd", lambda pid, distro=None: "")
    assert tmux.all_agents(distro="ubuntu") == []
    assert vistos == [("ps", "ubuntu"), ("panes", "ubuntu")]


def test_pane_pid_y_target_valid_consultan_en_la_distro(wsl, monkeypatch):
    """Un %0 de otra distro no valida: la consulta va al tmux de la distro de la tarjeta."""
    monkeypatch.setattr(tmux, "_ps_all", lambda distro=None: {})
    panes = [{"target": "%0", "pane_pid": 5, "cmd": "bash", "cwd": "/x"}]

    def list_panes_falso(distro=None):
        return panes if distro == "ubuntu" else []

    monkeypatch.setattr(tmux, "list_panes", list_panes_falso)
    assert tmux.pane_pid("%0", distro="ubuntu") == 5
    assert tmux.pane_pid("%0") is None
    assert tmux.target_valid("%0", 5, distro="ubuntu") is True
    assert tmux.target_valid("%0", 5) is False


def test_plataforma_no_win32_sin_codigo_de_distros_activo(nativo, tmux_llamadas):
    """En Mac/Linux el argv no trae wsl.exe ni -d, aunque una tarjeta vieja traiga distro."""
    tmux.send("%0", "hola", distro="ubuntu")
    tmux.screen("%0", distro="ubuntu")
    tmux.list_panes(distro="ubuntu")
    assert all(argv[0] == "tmux" and "-d" not in argv for argv in tmux_llamadas)


# --- distros(): descubrir las distros de WSL (tarea 2) ---


@pytest.fixture(autouse=True)
def distros_limpias():
    """Cada prueba arranca sin caché de distros (el módulo la comparte entre pruebas)."""
    tmux.invalidar_distros()
    yield
    tmux.invalidar_distros()


@pytest.fixture
def wsl_llamadas(monkeypatch):
    """Captura los argv que distros() manda por subproc.correr, con (rc, out) configurables."""
    vistos = []
    estado = {"rc": 0, "out": ""}

    def correr(argv, entrada=None, timeout=None):
        vistos.append({"argv": list(argv), "timeout": timeout})
        return estado["rc"], estado["out"], ""

    monkeypatch.setattr(tmux.subproc, "correr", correr)
    return vistos, estado


def _utf16(texto: str) -> str:
    """`wsl.exe -l -q` como llega a subproc.correr: bytes UTF-16-le decodificados como UTF-8."""
    return texto.encode("utf-16-le").decode("utf-8", "replace")


def test_distros_parsea_salida_utf16(wsl, wsl_llamadas):
    vistos, estado = wsl_llamadas
    estado["out"] = _utf16("ubuntu\r\ndebian\r\n")
    assert tmux.distros() == ["ubuntu", "debian"]
    assert vistos == [{"argv": ["wsl.exe", "-l", "-q"], "timeout": 15}]


def test_distros_descarta_vacias_y_placeholder(wsl, wsl_llamadas):
    vistos, estado = wsl_llamadas
    estado["out"] = _utf16("\r\nWindows Subsystem for Linux\r\nubuntu\r\n\r\n")
    assert tmux.distros() == ["ubuntu"]


def test_distros_salida_vacia(wsl, wsl_llamadas):
    _vistos, estado = wsl_llamadas
    estado["out"] = _utf16("\r\n")
    assert tmux.distros() == []


def test_distros_binario_ausente_devuelve_vacio(wsl, wsl_llamadas):
    vistos, estado = wsl_llamadas
    estado["rc"] = 127  # NO_ARRANCO: wsl.exe no existe
    assert tmux.distros() == []
    assert len(vistos) == 1


def test_distros_error_sin_levantar(wsl, wsl_llamadas):
    _vistos, estado = wsl_llamadas
    estado["rc"] = 124  # VENCIDO: wsl.exe colgado, el árbol fue matado
    assert tmux.distros() == []


def test_distros_nativo_sin_llamar_a_wsl(nativo, monkeypatch):
    """En Mac/Linux no hay WSL: [] y ni una llamada a wsl.exe."""

    def correr(argv, **_k):
        raise AssertionError(f"no se debia llamar a subproc.correr con {argv}")

    monkeypatch.setattr(tmux.subproc, "correr", correr)
    assert tmux.distros() == []


def test_distros_cache_dos_consultas_una_llamada(wsl, wsl_llamadas):
    vistos, estado = wsl_llamadas
    estado["out"] = _utf16("ubuntu\r\n")
    assert tmux.distros() == ["ubuntu"]
    assert tmux.distros() == ["ubuntu"]
    assert len(vistos) == 1


def test_distros_ttl_vencido_re_parsea(wsl, wsl_llamadas, monkeypatch):
    vistos, estado = wsl_llamadas
    estado["out"] = _utf16("ubuntu\r\n")
    assert tmux.distros() == ["ubuntu"]
    # Se vence el TTL sin tocar el reloj real: la verdad cacheada queda vieja.
    vieja = tmux._distros_cache
    vieja["ts"] -= tmux.DISTROS_TTL_S + 1.0
    estado["out"] = _utf16("ubuntu\r\ndebian\r\n")
    assert tmux.distros() == ["ubuntu", "debian"]
    assert len(vistos) == 2


def test_invalidar_distros_fuerza_re_parseo(wsl, wsl_llamadas):
    vistos, estado = wsl_llamadas
    estado["out"] = _utf16("ubuntu\r\n")
    assert tmux.distros() == ["ubuntu"]
    tmux.invalidar_distros()
    assert tmux.distros() == ["ubuntu"]
    assert len(vistos) == 2


# --- list_panes_todas(): unir los panes de todas las distros (tarea 3) ---


def test_list_panes_todas_une_dos_distros(wsl, monkeypatch):
    """Con mas de una distro, una llamada por distro (en paralelo) y los resultados unidos."""
    monkeypatch.setattr(tmux, "distros", lambda: ["ubuntu", "debian"])
    panes = {
        "ubuntu": [{"target": "%0", "pane_pid": 5, "cmd": "bash", "cwd": "/a"}],
        "debian": [{"target": "%1", "pane_pid": 6, "cmd": "bash", "cwd": "/b"}],
    }
    vistos = []

    def list_panes_falso(distro=None):
        vistos.append(distro)
        return panes[distro]

    monkeypatch.setattr(tmux, "list_panes", list_panes_falso)
    assert sorted(tmux.list_panes_todas(), key=lambda p: p["target"]) == panes["ubuntu"] + panes["debian"]
    assert sorted(vistos) == ["debian", "ubuntu"]


def test_list_panes_todas_distro_que_falla_salteada(wsl, monkeypatch):
    """Una distro que no corre (rc != 0, list_panes devuelve []) o levanta: se saltea sin excepcion
    y las demas aparecen."""
    monkeypatch.setattr(tmux, "distros", lambda: ["ubuntu", "rota"])
    vivas = [{"target": "%0", "pane_pid": 5, "cmd": "bash", "cwd": "/x"}]

    def list_panes_falso(distro=None):
        if distro == "rota":
            raise RuntimeError("wsl.exe -d rota exploto")
        return vivas

    monkeypatch.setattr(tmux, "list_panes", list_panes_falso)
    assert tmux.list_panes_todas() == vivas  # sin excepcion, la viva aparece


def test_list_panes_todas_una_sola_distro_camino_de_hoy(wsl, tmux_llamadas, monkeypatch):
    """Con 0 o 1 distro es el camino de hoy: list_panes() directo, en serie, sin -d."""
    monkeypatch.setattr(tmux, "distros", lambda: ["ubuntu"])
    assert tmux.list_panes_todas() == []
    assert tmux_llamadas == [["wsl.exe", "tmux", "list-panes", "-a", "-F", FMT]]


def test_list_panes_todas_sin_distros_camino_de_hoy(wsl, tmux_llamadas, monkeypatch):
    """Sin distros descubiertas (o en nativo), tambien el camino de hoy: list_panes() directo."""
    monkeypatch.setattr(tmux, "distros", list)
    assert tmux.list_panes_todas() == []
    assert tmux_llamadas == [["wsl.exe", "tmux", "list-panes", "-a", "-F", FMT]]


# --- wsl_unc_home(): la home UNC por distro (tarea 4) ---

BASH_PRINTF = 'printf "%s\\n%s" "$WSL_DISTRO_NAME" "$HOME"'


@pytest.fixture
def unc_homes_limpias():
    """Cada prueba arranca sin caché de homes UNC (el módulo la comparte entre pruebas)."""
    tmux._unc_home_cache.clear()
    yield
    tmux._unc_home_cache.clear()


@pytest.fixture
def bash_llamadas(monkeypatch):
    """Captura los argv de `bash -lc` que wsl_unc_home manda por subprocess.run, con salida configurable."""
    vistos = []
    estado = {"rc": 0, "out": ""}

    def run(argv, **_k):
        vistos.append(list(argv))
        return subprocess.CompletedProcess(argv, estado["rc"], estado["out"], "")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    return vistos, estado


def test_wsl_unc_home_con_distro_resuelve_la_de_esa_distro(wsl, bash_llamadas, unc_homes_limpias):
    vistos, estado = bash_llamadas
    estado["out"] = "otra-distro\n/home/pepe\n"
    assert tmux.wsl_unc_home("otra-distro") == "\\\\wsl.localhost\\otra-distro\\home\\pepe"
    assert vistos == [["wsl.exe", "-d", "otra-distro", "bash", "-lc", BASH_PRINTF]]


def test_wsl_unc_home_sin_argumento_argv_de_hoy(wsl, bash_llamadas, unc_homes_limpias):
    """Sin distro, el argv es el de hoy: wsl.exe bash -lc ... (la home de la distro default)."""
    vistos, estado = bash_llamadas
    estado["out"] = "ubuntu\n/home/u\n"
    assert tmux.wsl_unc_home() == "\\\\wsl.localhost\\ubuntu\\home\\u"
    assert vistos == [["wsl.exe", "bash", "-lc", BASH_PRINTF]]


def test_wsl_unc_home_cache_por_distro(wsl, bash_llamadas, unc_homes_limpias):
    """Dos consultas de la misma distro corren bash una sola vez; otra distro, la suya."""
    vistos, estado = bash_llamadas
    estado["out"] = "ubuntu\n/home/u\n"
    primera = tmux.wsl_unc_home("ubuntu")
    assert tmux.wsl_unc_home("ubuntu") == primera
    assert len(vistos) == 1
    estado["out"] = "debian\n/home/d\n"
    assert tmux.wsl_unc_home("debian") == "\\\\wsl.localhost\\debian\\home\\d"
    assert len(vistos) == 2


def test_wsl_unc_home_distro_que_no_contesta_cachea_none(wsl, bash_llamadas, unc_homes_limpias):
    vistos, estado = bash_llamadas
    estado["rc"] = 1
    assert tmux.wsl_unc_home("rota") is None
    assert tmux.wsl_unc_home("rota") is None  # el None queda cacheado: sin segunda llamada
    assert len(vistos) == 1


def test_wsl_unc_home_nativo_none_sin_llamar_bash(nativo, monkeypatch, unc_homes_limpias):
    def run(argv, **_k):
        raise AssertionError(f"no se debia llamar a subprocess.run con {argv}")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    assert tmux.wsl_unc_home("ubuntu") is None
    assert tmux.wsl_unc_home() is None


# --- send/screen con la distro de la tarjeta (tarea 6) --------------------------------------


def test_run_send_a_tarjeta_con_distro_argv_con_d(wsl, tmux_llamadas, monkeypatch):
    import sessions as ses
    import state as st

    s = ses.new_session("wsl-4242", "claude", "sweep")
    s.update({"pid": 4242, "alive": True, "backend": "tmux", "target": "%0", "distro": "debian"})
    st.sessions[s["session_id"]] = s
    monkeypatch.setattr(tmux, "pane_pid", lambda target, distro=None: 4242 if target == "%0" else None)
    codigo, r = ses.run_send(s, "hola")
    assert codigo == 200
    assert tmux_llamadas[0][:4] == ["wsl.exe", "-d", "debian", "tmux"]


def test_run_send_a_tarjeta_sin_distro_argv_de_hoy(wsl, tmux_llamadas, monkeypatch):
    import sessions as ses
    import state as st

    s = ses.new_session("tmux-4242", "claude", "sweep")
    s.update({"pid": 4242, "alive": True, "backend": "tmux", "target": "%0"})
    st.sessions[s["session_id"]] = s
    monkeypatch.setattr(tmux, "pane_pid", lambda target, distro=None: 4242 if target == "%0" else None)
    codigo, _ = ses.run_send(s, "hola")
    assert codigo == 200
    assert tmux_llamadas[0][:2] == ["wsl.exe", "tmux"]


def test_adjunto_a_agente_de_wsl_ruta_traducida(wsl, tmp_path, monkeypatch):
    import sessions as ses

    adj = tmp_path / "a.md"
    adj.write_text("x", encoding="utf-8")
    monkeypatch.setattr(ses, "ADJUNTOS", str(tmp_path))
    tipeado, _, _ = ses.compose_send("x", "leelo", [str(adj)], agent="claude", wsl=True)
    assert "Adjunto: /mnt/" in tipeado


# --- lanzar eligiendo la distro (tarea 8) ----------------------------------------------------

from typing import ClassVar


class FakePopenDistros:
    """subprocess.Popen mockeado para launch: registra el argv, no abre ninguna terminal."""

    calls: ClassVar[list[list[str]]] = []

    def __init__(self, argv, *a, **k):
        FakePopenDistros.calls.append(list(argv))


@pytest.fixture
def aislado_launch(tmp_path, monkeypatch):
    """launch aislado: Popen mockeado, exes falsos, carpetas que prueban creadas."""
    import state as st
    import launch as mod_launch

    monkeypatch.setattr(st, "LIENZO", str(tmp_path / ".lienzo"))
    monkeypatch.setattr(st, "HOME", str(tmp_path / "home"))
    monkeypatch.setattr(mod_launch.subprocess, "Popen", FakePopenDistros)
    monkeypatch.setattr(mod_launch, "_existe", lambda p: True)
    bin_dir = tmp_path / "home" / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for exe in mod_launch.AGENT_EXES.values():
        (bin_dir / exe).write_text("")
    FakePopenDistros.calls = []
    yield tmp_path


def con_roots_launch(monkeypatch, *roots) -> None:
    import state as st

    monkeypatch.setattr(st, "load_config", lambda: {"launch_roots": [str(r) for r in roots]})


def test_launch_con_distro_spawn_por_wsl_exe_d(aislado_launch, monkeypatch):
    con_roots_launch(monkeypatch, aislado_launch / "repos")
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(tmux, "en_distro", lambda d, prog: d == "debian" and prog == "claude")
    res = launch.launch(str(aislado_launch / "repos" / "x"), "titulo", "claude", distro="debian")
    assert res.get("ok") is True
    assert res["distro"] == "debian"
    argv = FakePopenDistros.calls[-1]
    assert argv[:3] == ["wsl.exe", "-d", "debian"]
    assert "new-session" in argv
    assert any(a == "-c" and "/mnt/" in argv[i + 1] for i, a in enumerate(argv[:-1]))
    # adentro de WSL corre el binario de Linux por su nombre, no la ruta del .exe de Windows
    assert "claude" in argv and not any(a.lower().endswith(".exe") and "\\" in a for a in argv[3:])


def test_launch_con_distro_sin_el_agente_en_la_distro_no_lanza(aislado_launch, monkeypatch):
    con_roots_launch(monkeypatch, aislado_launch / "repos")
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(tmux, "en_distro", lambda d, prog: False)
    res = launch.launch(str(aislado_launch / "repos" / "x"), "titulo", "claude", distro="debian")
    assert res.get("ok") is False and "en la distro debian" in res["error"] and FakePopenDistros.calls == []


def test_accion_launch_en_otra_pc_no_valida_la_distro_contra_las_locales(monkeypatch):
    """La distro la valida la PC dueña: esta PC no tiene «arch», la otra sí."""
    monkeypatch.setattr(tmux, "distros", lambda: ["Ubuntu"])
    monkeypatch.setattr(server.identity, "pc_id", lambda: "esta")
    enviado = {}
    monkeypatch.setattr(
        server.mirror.MIRROR,
        "forward",
        lambda pc, m, ruta, cuerpo: enviado.update(pc=pc, cuerpo=cuerpo) or (200, {"ok": True}),
    )
    codigo, _ = server.accion_launch(
        {"cwd": "C:/x", "agent": "claude", "distro": "arch", "pc": "otra"}, desde_tablero=True
    )
    assert codigo == 200 and enviado["pc"] == "otra" and enviado["cuerpo"]["distro"] == "arch"


def test_la_salud_de_la_pc_trae_sus_distros(monkeypatch):
    """El selector del diálogo de lanzar las lee de GET /peers, que arma la salud con protocol.info."""
    import protocol

    monkeypatch.setattr(tmux, "distros", lambda: ["Ubuntu", "Debian"])
    assert protocol.info()["distros_wsl"] == ["Ubuntu", "Debian"]


def test_launch_sin_distro_spawn_de_hoy(aislado_launch, monkeypatch):
    con_roots_launch(monkeypatch, aislado_launch / "repos")
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    res = launch.launch(str(aislado_launch / "repos" / "x"), "titulo", "claude")
    assert res.get("ok") is True
    assert "distro" not in res
    argv = FakePopenDistros.calls[-1]
    assert argv[0] != "wsl.exe"


def test_launch_nativo_ignora_la_distro(aislado_launch, monkeypatch):
    con_roots_launch(monkeypatch, aislado_launch / "repos")
    monkeypatch.setattr(launch, "WINDOWS", False)
    monkeypatch.setattr(tmux, "_VIA_WSL", False)
    res = launch.launch(str(aislado_launch / "repos" / "x"), "titulo", "claude", distro="debian")
    assert res.get("ok") is True
    argv = FakePopenDistros.calls[-1]
    assert argv[0] == "tmux"


def test_accion_launch_distro_desconocida_400_sin_tarjeta(monkeypatch):
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    monkeypatch.setattr(tmux, "distros", lambda: ["debian"])
    llamadas = {"n": 0}

    def correr_falso(*a, **k):
        llamadas["n"] += 1
        raise AssertionError("no se debia intentar lanzar")

    monkeypatch.setattr(launch, "launch", correr_falso)
    codigo, r = server.accion_launch({"cwd": "C:/x", "agent": "claude", "distro": "rota"}, desde_tablero=False)
    assert codigo == 400
    assert "distro desconocida" in r["error"]
    assert llamadas["n"] == 0


def test_accion_launch_distro_valida_llega_a_launch(monkeypatch):
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    monkeypatch.setattr(tmux, "distros", lambda: ["debian"])
    recibida = {}

    def launch_falso(cwd, title, agent, model=None, distro=None):
        recibida.update(distro=distro)
        return {"ok": True}

    monkeypatch.setattr(launch, "launch", launch_falso)
    codigo, _ = server.accion_launch({"cwd": "C:/x", "agent": "claude", "distro": "debian"}, desde_tablero=False)
    assert codigo == 200
    assert recibida["distro"] == "debian"


def test_accion_launch_sin_distro_llega_none(monkeypatch):
    monkeypatch.setattr(tmux, "_VIA_WSL", True)
    recibida = {}

    def launch_falso(cwd, title, agent, model=None, distro=None):
        recibida.update(distro=distro)
        return {"ok": True}

    monkeypatch.setattr(launch, "launch", launch_falso)
    codigo, _ = server.accion_launch({"cwd": "C:/x", "agent": "claude"}, desde_tablero=False)
    assert codigo == 200
    assert recibida["distro"] is None
