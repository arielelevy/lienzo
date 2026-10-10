"""La fuente tmux (Mac/Linux/WSL) junto a la de Windows: un pid de WSL y uno de Windows con el mismo
numero son procesos distintos, un agente fuera de tmux se ve pero no se le escribe, un pane que cambio
no recibe teclas, y la pantalla de tmux sale con la misma forma que la de screen.py. Todo con tmux
mockeado: ninguna prueba abre un pane de verdad (eso lo hace tests/tmux_smoke.py, a mano)."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401
import backend
import sessions as ses
import state as st
import tmux

PID = 4242


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "LIENZO", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    os.makedirs(st.SESSIONS, exist_ok=True)
    st.sessions.clear()
    yield tmp_path
    st.sessions.clear()


def tarjeta(sid, **campos):
    s = ses.new_session(sid, "claude", "sweep")
    s.update({"pid": PID, "alive": True, **campos})
    st.sessions[sid] = s
    return s


def test_mismo_pid_en_windows_y_en_wsl_son_procesos_distintos():
    assert backend.proc_key({"pid": PID, "backend": "tmux"}) != backend.proc_key({"pid": PID, "backend": "win32"})


def test_mismo_pid_en_dos_distros_son_procesos_distintos():
    """Sin la distro en la clave, dos agentes con el mismo numero de pid en distros distintas se
    pisarian (son maquinas distintas). Un evento de hook, que no trae distro, cae en la misma clave
    que una tarjeta sin distro."""
    assert backend.proc_key({"pid": PID, "backend": "tmux", "distro": "ubuntu"}) != backend.proc_key(
        {"pid": PID, "backend": "tmux", "distro": "debian"}
    )
    assert backend.proc_key({"pid": PID, "backend": "tmux", "distro": "ubuntu"}) == backend.proc_key(
        {"pid": PID, "backend": "tmux", "distro": "ubuntu"}
    )
    assert backend.proc_key({"pid": PID, "backend": "tmux"}) == backend.proc_key(
        {"pid": PID, "backend": "tmux", "distro": ""}
    )


def test_un_hook_de_windows_no_se_lleva_la_tarjeta_de_tmux_con_el_mismo_pid(aislado, monkeypatch):
    monkeypatch.setattr(backend._win, "is_tui", lambda pid: True)
    wsl = tarjeta("tmux-4242", backend="tmux", target="%0")
    win = ses.new_session("10000000-0000-4000-8000-000000000001", "claude", "hook")
    st.sessions[win["session_id"]] = win
    with st.lock:
        ses.claim_pid(win, {"pid": PID, "hook_event_name": "SessionStart"})
    assert st.sessions.get("tmux-4242") is wsl, "la de WSL no es un duplicado de la de Windows"
    assert win["pid"] == PID


def test_el_barrido_adopta_un_agente_de_wsl_aunque_su_pid_ya_sea_de_windows(aislado, monkeypatch):
    tarjeta("10000000-0000-4000-8000-000000000001", backend="win32", source="hook")
    wsl = {"pid": PID, "agent": "claude", "exe": "claude", "cwd": "/home/x/repo", "target": "%3", "backend": "tmux"}
    monkeypatch.setattr(ses.backend, "sweep", lambda: [wsl])
    monkeypatch.setattr(ses, "guess_transcript", lambda *a, **k: (None, None))
    monkeypatch.setattr(ses, "transcript_home", lambda d: st.HOME)
    ses.sweep_once()
    assert st.sessions["tmux-4242"]["target"] == "%3"


def test_fuera_de_tmux_se_ve_pero_no_se_le_escribe(aislado, monkeypatch):
    s = tarjeta("tmux-4242", backend="tmux", target=None, no_console=True)
    monkeypatch.setattr(backend, "_tmux_alive", lambda pid, distro=None: True)
    code, out = ses.send_blocked(s)
    assert code == 409 and "fuera de tmux" in out["error"]


def test_un_pane_que_cambio_no_recibe_teclas(aislado, monkeypatch):
    s = tarjeta("tmux-4242", backend="tmux", target="%0")
    monkeypatch.setattr(tmux, "target_valid", lambda target, pid, distro=None: False)
    enviado = []
    monkeypatch.setattr(tmux, "send", lambda *a, **k: enviado.append(a) or {"ok": True})
    code, out = ses.run_send(s, "hola")
    assert code == 409 and "pane" in out["error"]
    assert enviado == []


def test_run_send_pasa_enter_y_la_tecla_al_pane(aislado, monkeypatch):
    s = tarjeta("tmux-4242", backend="tmux", target="%0")
    monkeypatch.setattr(tmux, "target_valid", lambda target, pid, distro=None: True)
    visto = []
    monkeypatch.setattr(
        tmux,
        "send",
        lambda target, text, enter=True, key=None, distro=None: visto.append((target, text, enter, key)) or {"ok": True},
    )
    assert ses.run_send(s, "2", enter=False)[0] == 200
    assert ses.run_send(s, "", enter=False, key="escape")[0] == 200
    assert visto == [("%0", "2", False, None), ("%0", "", False, "escape")]


def test_tmux_send_con_escape_manda_la_tecla_sola(monkeypatch):
    llamadas = []
    monkeypatch.setattr(tmux, "_tmux", lambda *a, **k: llamadas.append(a) or SimpleNamespace(returncode=0, stderr=""))
    assert tmux.send("%1", "", enter=False, key="escape")["ok"] is True
    assert llamadas == [("send-keys", "-t", "%1", "Escape")]
    assert tmux.send("%1", "", key="f1")["ok"] is False


def test_tmux_send_sin_texto_con_enter_solo_confirma(monkeypatch):
    llamadas = []
    monkeypatch.setattr(tmux, "_tmux", lambda *a, **k: llamadas.append(a) or SimpleNamespace(returncode=0, stderr=""))
    assert tmux.send("%1", "", enter=True)["ok"] is True
    assert llamadas == [("send-keys", "-t", "%1", "Enter")]


def test_la_pantalla_de_tmux_tiene_la_forma_de_screen_py(aislado, monkeypatch):
    s = tarjeta("tmux-4242", backend="tmux", target="%0")
    monkeypatch.setattr(tmux, "target_valid", lambda target, pid, distro=None: True)
    texto = "Switch model?\n❯ 1. Yes\n  2. No\n"
    monkeypatch.setattr(tmux, "screen", lambda target, scrollback=0, distro=None: {"ok": True, "text": texto})
    r = ses.read_screen(s)
    assert r["lines"] == ["Switch model?", "❯ 1. Yes", "  2. No"]
    assert r["dialog"]["options"] == [{"n": 1, "text": "Yes"}, {"n": 2, "text": "No"}]
    assert "input" in r["area"]


def test_la_provisoria_del_barrido_cede_sus_reglas_a_la_sesion_con_hooks(aislado, monkeypatch):
    """Un agente recien lanzado nace como `pid-N`; cuando llega su primer hook, la regla de cableado
    hecha contra la provisoria tiene que pasar al sid real, y no quedar colgando de un id que se va."""
    monkeypatch.setattr(backend._win, "is_tui", lambda pid: True)
    monkeypatch.setattr(ses.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(ses.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(ses.rules, "items", [{"id": "r1", "kind": "on_stop", "from": f"pid-{PID}", "to": "coord"}])
    monkeypatch.setattr(ses.links, "items", [])
    tarjeta(f"pid-{PID}", backend="win32")
    real = ses.new_session("10000000-0000-4000-8000-000000000002", "claude", "hook")
    st.sessions[real["session_id"]] = real
    with st.lock:
        ses.claim_pid(real, {"pid": PID, "hook_event_name": "SessionStart"})
    assert f"pid-{PID}" not in st.sessions
    assert ses.rules.items[0]["from"] == "10000000-0000-4000-8000-000000000002"


# --- el barrido etiqueta cada agente con su distro (tarea 5) ---


def agente_falso(pid, target, comm="claude", command=None):
    return {
        "pid": pid,
        "agent": comm,
        "comm": comm,
        "command": command or comm,
        "cwd": f"/home/x/repo-{pid}",
        "target": target,
    }


def test_el_barrido_etiqueta_cada_agente_con_su_distro(monkeypatch):
    """Con dos distros, una llamada a all_agents por distro y cada tarjeta con su distro."""
    monkeypatch.setattr(tmux, "distros", lambda: ["ubuntu", "debian"])
    vistos = []

    def all_agents_falso(distro=None):
        vistos.append(distro)
        if distro == "ubuntu":
            return [agente_falso(11, "%0")]
        if distro == "debian":
            return [agente_falso(22, None, comm="codex")]
        return []

    monkeypatch.setattr(tmux, "all_agents", all_agents_falso)
    out = backend._tmux_sweep()
    por_pid = {a["pid"]: a for a in out}
    assert por_pid[11]["distro"] == "ubuntu"
    assert por_pid[22]["distro"] == "debian"
    assert por_pid[11]["backend"] == "tmux" and por_pid[11]["target"] == "%0"
    assert por_pid[11]["exe"] == "claude" and por_pid[11]["cwd"] == "/home/x/repo-11"
    assert por_pid[22]["no_console"] is True  # suelto: se ve y se lee, no se le escribe
    assert sorted(vistos) == ["debian", "ubuntu"]


def test_el_barrido_con_una_sola_distro_tambien_etiqueta(monkeypatch):
    """Con una sola distro es el camino de hoy (una llamada a all_agents, en serie), y la tarjeta
    lleva igual el nombre de la distro —tambien la default— (criterio 2.2)."""
    monkeypatch.setattr(tmux, "distros", lambda: ["ubuntu"])
    vistos = []

    def all_agents_falso(distro=None):
        vistos.append(distro)
        return [agente_falso(11, "%0")]

    monkeypatch.setattr(tmux, "all_agents", all_agents_falso)
    out = backend._tmux_sweep()
    assert vistos == ["ubuntu"]
    assert len(out) == 1 and out[0]["distro"] == "ubuntu" and out[0]["backend"] == "tmux"


def test_el_barrido_nativo_va_sin_distro(monkeypatch):
    """En Mac/Linux (o WSL ilegible) no hay distros: all_agents cae al default y las tarjetas van
    sin campo distro (criterio 2.3)."""
    monkeypatch.setattr(tmux, "distros", list)
    vistos = []

    def all_agents_falso(distro=None):
        vistos.append(distro)
        return [agente_falso(11, "%0")]

    monkeypatch.setattr(tmux, "all_agents", all_agents_falso)
    out = backend._tmux_sweep()
    assert vistos == [None]
    assert len(out) == 1 and "distro" not in out[0]


def test_alive_y_los_validadores_consultan_en_la_distro_de_la_tarjeta(monkeypatch):
    """agent_alive e is_tui pasan la distro de la tarjeta hacia tmux: un pid vivo en otra distro no
    valida como vivo aca."""
    vistos = []
    monkeypatch.setattr(tmux, "pid_alive", lambda pid, distro=None: vistos.append(("pid_alive", distro)) or True)
    monkeypatch.setattr(tmux, "cmdline", lambda pid, distro=None: "bash -lc algo")  # sin claude/codex: se consulta comm
    monkeypatch.setattr(tmux, "comm", lambda pid, distro=None: vistos.append(("comm", distro)) or "claude")
    d = {"pid": PID, "backend": "tmux", "distro": "debian"}
    assert backend.agent_alive(d) is True
    assert backend.is_tui(d) is True
    assert ("pid_alive", "debian") in vistos and ("comm", "debian") in vistos
