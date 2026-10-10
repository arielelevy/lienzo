"""Tanda 3 de PENDIENTES.md (2026-10-10): en Unix el hook encuentra el PID del agente por /proc (o ps en
macOS) y manda su pane de tmux, que pasa a ser el destino de la tarjeta sin esperar al barrido."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import backend
import procinfo
import sessions as ses
import state as st


def _proc(raiz, pid, ppid, comm):
    d = raiz / str(pid)
    d.mkdir(parents=True)
    # el comm entre parentesis con espacios y un ")" adentro, como puede venir de verdad
    (d / "stat").write_text(f"{pid} ({comm} (x)) S {ppid} 1 1 0 -1", encoding="utf-8")
    (d / "comm").write_text(comm + "\n", encoding="utf-8")


def test_fuera_de_windows_el_padre_y_el_nombre_salen_de_proc(monkeypatch, tmp_path):
    monkeypatch.setattr(procinfo, "_WIN", False)
    monkeypatch.setattr(procinfo, "_PROC", str(tmp_path))
    _proc(tmp_path, 300, 200, "python3")
    _proc(tmp_path, 200, 100, "claude")
    assert procinfo.proc_info(300) == (200, "python3")
    assert procinfo.proc_info(999) == (None, None)
    assert procinfo.agent_of("claude") == "claude" and procinfo.agent_of("python3") is None


def test_el_hook_sube_por_proc_hasta_el_agente(monkeypatch, tmp_path):
    import hook

    monkeypatch.setattr(procinfo, "_WIN", False)
    monkeypatch.setattr(procinfo, "_PROC", str(tmp_path))
    monkeypatch.setattr(hook.os, "getpid", lambda: 300)
    _proc(tmp_path, 300, 250, "python3")
    _proc(tmp_path, 250, 200, "sh")
    _proc(tmp_path, 200, 1, "claude")
    pid, exe, cadena = hook.find_agent_pid()
    assert (pid, exe) == (200, "claude") and cadena[-1] == "claude(200)"


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


def test_el_pane_del_hook_es_el_destino_de_la_tarjeta_de_tmux(aislado, monkeypatch):
    monkeypatch.setattr(backend, "NAME", "tmux")
    sid = "20000000-0000-4000-8000-000000000002"
    ses.apply_event({"session_id": sid, "hook_event_name": "SessionStart", "agent": "claude", "tmux_pane": "%7"})
    assert st.sessions[sid]["target"] == "%7"
    # un valor que no es un id de pane no se toma
    ses.apply_event({"session_id": sid, "hook_event_name": "Stop", "agent": "claude", "tmux_pane": "%7; rm -rf"})
    assert st.sessions[sid]["target"] == "%7"


def test_en_windows_el_pane_no_pisa_nada(aislado, monkeypatch):
    monkeypatch.setattr(backend, "NAME", "win32")
    sid = "20000000-0000-4000-8000-000000000003"
    ses.apply_event({"session_id": sid, "hook_event_name": "SessionStart", "agent": "claude", "tmux_pane": "%7"})
    assert st.sessions[sid]["target"] is None


def test_las_reglas_hacia_otra_pc_sobreviven_al_reinicio(aislado, monkeypatch):
    local = "30000000-0000-4000-8000-000000000001"
    monkeypatch.setattr(server, "sessions", {local: {"session_id": local}})
    guardadas = st.JsonList(str(aislado / "rules.json"), "rules")
    guardadas.items = [
        {"id": "r1", "kind": "on_stop", "from": local, "to": "sid-de-la-otra-pc", "xpc": True, "to_pc": "pcB"},
        {"id": "r2", "kind": "on_stop", "from": "una-que-ya-no-esta", "to": local},
        {"id": "r3", "kind": "on_stop", "from": local, "to": "desconocida-sin-xpc"},
        {"id": "r4", "kind": "at", "to": local, "at": "2026-10-10T10:00:00-03:00"},
    ]
    assert guardadas.save()
    # el arranque siguiente: una lista nueva que lee el mismo archivo con la regla del server
    releida = st.JsonList(guardadas.path, "rules")
    releida.load(server.conservar_regla)
    assert [r["id"] for r in releida.items] == ["r1", "r4"]
    assert releida.items[0]["to_pc"] == "pcB"
