"""El titulo pedido en POST /sessions/launch llega a la tarjeta del proceso lanzado (2026-10-22).

Medido: la Codex lanzada como «lienzo | D-repro codex /new (descartable)» salio «sesion sin
transcripcion identificada» y despues con su primer pedido; una Claude lanzada desde ar-it33940,
«lienzo | sesión». El titulo solo llegaba a la ventana del .cmd.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401
import launch
import sessions as ses
import state as st
import titulo_lanzado

PID, CMD_PID = 40001, 40000
TOKEN = "46a5ca363c6f"
TITLE = "lienzo | D-repro codex /new (descartable)"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "LIENZO", str(tmp_path / ".lienzo"))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    os.makedirs(st.SESSIONS, exist_ok=True)
    os.makedirs(titulo_lanzado.carpeta(), exist_ok=True)
    st.sessions.clear()
    st.transcript_stat.clear()
    yield tmp_path
    st.sessions.clear()
    st.transcript_stat.clear()


def lanzado(monkeypatch, agent="codex", title=TITLE, carpeta=None, padres=None):
    """Proceso PID hijo de `cmd.exe /c "<carpeta>\\<TOKEN>.cmd"`, como lo deja explorer.exe."""
    carpeta = carpeta or titulo_lanzado.carpeta()
    cmd_path = os.path.join(carpeta, f"{TOKEN}.cmd")
    titulo_lanzado.guardar(cmd_path, title, agent)
    padres = padres or {PID: (CMD_PID, "x.exe"), CMD_PID: (1, "cmd.exe"), 1: (0, None)}
    lineas = {CMD_PID: f'C:\\WINDOWS\\system32\\cmd.exe /c ""{cmd_path}" "'}
    monkeypatch.setattr(titulo_lanzado.procinfo, "_WIN", True)
    monkeypatch.setattr(titulo_lanzado.procinfo, "proc_info", lambda pid: padres.get(pid, (None, None)))
    monkeypatch.setattr(titulo_lanzado.procinfo, "command_line", lambda pid: lineas.get(pid))
    return cmd_path


def test_el_titulo_pedido_sale_del_cmd_padre(aislado, monkeypatch):
    lanzado(monkeypatch)
    assert titulo_lanzado.pedido(PID, "codex") == TITLE


@pytest.mark.parametrize("caso", ["otro-agente", "otra-carpeta", "sin-json", "json-roto", "sin-padre"])
def test_sin_lanzamiento_propio_no_titula(aislado, monkeypatch, caso):
    if caso == "otra-carpeta":
        ajena = aislado / "ajena" / "launch"
        ajena.mkdir(parents=True)
        lanzado(monkeypatch, carpeta=str(ajena))
    else:
        cmd_path = lanzado(monkeypatch, padres={PID: (0, None)} if caso == "sin-padre" else None)
        sidecar = os.path.splitext(cmd_path)[0] + ".json"
        if caso == "sin-json":
            os.remove(sidecar)
        elif caso == "json-roto":
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write("{")
    agent = "claude" if caso == "otro-agente" else "codex"
    assert titulo_lanzado.pedido(PID, agent) is None


def test_un_titulo_del_usuario_no_se_pisa(aislado, monkeypatch):
    lanzado(monkeypatch)
    s = {"pid": PID, "agent": "codex", "title": "renombrada", "title_source": "user"}
    assert titulo_lanzado.aplicar(s) is False and s["title"] == "renombrada"


def test_launch_guarda_el_titulo_junto_al_cmd(aislado, monkeypatch):
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: None)
    res = launch._launch_cmd(str(aislado), TITLE, sys.executable, [], agent="codex")
    with open(os.path.splitext(res["cmd_path"])[0] + ".json", encoding="utf-8") as f:
        assert json.load(f) == {"title": TITLE, "agent": "codex"}


def test_la_tarjeta_del_barrido_nace_con_el_titulo_pedido(aislado, monkeypatch):
    lanzado(monkeypatch)
    monkeypatch.setattr(ses.backend._win, "cwd_of", lambda pid: str(aislado))
    monkeypatch.setattr(ses, "guess_transcript", lambda agent, cwd_, started, home=None: (None, None))
    ses.adopt_process({"pid": PID, "agent": "claude", "exe": "claude.exe", "created": st.now()})
    assert st.sessions[f"pid-{PID}"]["title"] == "sesion sin transcripcion identificada"  # agente distinto
    st.sessions.clear()
    lanzado(monkeypatch, agent="claude")
    ses.adopt_process({"pid": PID, "agent": "claude", "exe": "claude.exe", "created": st.now()})
    s = st.sessions[f"pid-{PID}"]
    assert (s["title"], s["title_source"]) == (TITLE, "user")


def test_la_tarjeta_del_hook_toma_el_titulo_pedido(aislado, monkeypatch):
    lanzado(monkeypatch, agent="claude")
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses.backend, "external_origin", lambda s: None)
    sid = "10000000-0000-4000-8000-000000000001"
    try:  # la particion de F lo mueve a hooks_eventos
        from hooks_eventos import apply_event
    except ImportError:
        apply_event = ses.apply_event
    apply_event(
        {
            "hook_event_name": "SessionStart",
            "session_id": sid,
            "agent": "claude",
            "pid": PID,
            "agent_exe": "claude.exe",
            "cwd": str(aislado),
            "host_ts": st.now(),
        }
    )
    s = st.sessions[sid]
    assert (s["title"], s["title_source"]) == (TITLE, "user")
