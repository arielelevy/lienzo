"""Ejecuciones externas: agentes que lanza un orquestador (registrado por un plugin local) o un
`claude -p` suelto. Se ven en el tablero, pero no se les teclea, ni se las mata, ni las mueven
reglas; una sesion personal no cambia."""

import datetime as dt

import procinfo
import procs
import pytest
import rules
import sessions
import state


@pytest.fixture(autouse=True)
def _runner_de_prueba(monkeypatch):
    monkeypatch.setattr(procinfo, "EXTERNAL_RUNNERS", {"orq.exe": "orquestador"})


def test_claude_batch_reconoce_print_y_no_la_tui():
    assert procinfo.claude_batch(["--print", "--verbose", "--output-format", "stream-json"])
    assert procinfo.claude_batch(["-p", "hola"])
    assert not procinfo.claude_batch(["--model", "opus"])
    assert not procinfo.claude_batch(["--", "-p"])  # despues de -- es texto, no una opcion
    assert procinfo.external_runner(r"C:\x\bin\orq.exe") == "orquestador"
    assert procinfo.external_runner(r"C:\x\orq-helper.exe") is None


def test_repo_sin_plugins_no_conoce_lanzadores(monkeypatch):
    monkeypatch.setattr(procinfo, "EXTERNAL_RUNNERS", {})
    assert procinfo.external_runner(r"C:\x\orq.exe") is None


def test_fila_del_barrido_hija_de_un_orquestador_o_claude_p_es_externa():
    assert procs.external_of_row({"parent": "orq.exe", "exe": "claude.exe", "cmd": "claude"})["kind"] == "orquestador"
    assert (
        procs.external_of_row({"parent": "cmd.exe", "grandparent": "orq.exe", "exe": "c.exe"})["kind"] == "orquestador"
    )
    assert (
        procs.external_of_row({"parent": "pwsh.exe", "exe": r"C:\b\claude.exe", "cmd": "claude --print x"})["kind"]
        == "batch"
    )
    assert procs.external_of_row({"parent": "pwsh.exe", "exe": r"C:\b\claude.exe", "cmd": "claude"}) is None


def test_external_origin_sube_por_los_padres(monkeypatch):
    arbol = {10: (11, r"C:\b\claude.exe"), 11: (12, r"C:\b\cmd.exe"), 12: (1, r"C:\u\bin\orq.exe")}
    monkeypatch.setattr(procs, "proc_info", lambda pid: arbol.get(pid, (None, None)))
    monkeypatch.setattr(procs, "image_path", lambda pid: arbol.get(pid, (None, None))[1])
    monkeypatch.setattr(procs.procinfo, "command_line", lambda pid: "claude")
    assert procs.external_origin(10) == {"kind": "orquestador", "runner_pid": 12, "via": "proceso"}
    arbol[11] = (1, r"C:\b\pwsh.exe")
    assert procs.external_origin(10) is None  # una terminal personal
    monkeypatch.setattr(procs.procinfo, "command_line", lambda pid: '"C:\\b\\claude.exe" -p "hola"')
    assert procs.external_origin(10) == {"kind": "batch", "via": "comando"}


def test_claim_pid_marca_externa_y_sin_consola(monkeypatch):
    import backend

    monkeypatch.setattr(
        backend, "external_origin", lambda d: {"kind": "orquestador", "runner_pid": 7, "via": "proceso"}
    )
    monkeypatch.setattr(backend, "is_tui", lambda d: True)
    s = sessions.new_session("aaaa", "claude", "hook")
    sessions.claim_pid(s, {"pid": 99, "agent_exe": "claude.exe"})
    assert s["external"]["kind"] == "orquestador" and s["no_console"] is True


def test_claim_pid_de_una_sesion_personal_no_cambia(monkeypatch):
    import backend

    monkeypatch.setattr(backend, "external_origin", lambda d: None)
    monkeypatch.setattr(backend, "is_tui", lambda d: True)
    s = sessions.new_session("bbbb", "claude", "hook")
    sessions.claim_pid(s, {"pid": 98, "agent_exe": "claude.exe"})
    assert s["external"] is None and s["no_console"] is False


def test_retomar_en_terminal_propia_vuelve_personal(monkeypatch):
    import backend

    origen = {"v": {"kind": "orquestador", "runner_pid": 7, "via": "proceso"}}
    monkeypatch.setattr(backend, "external_origin", lambda d: origen["v"])
    monkeypatch.setattr(backend, "is_tui", lambda d: origen["v"] is None)
    s = sessions.new_session("cccc", "claude", "hook")
    sessions.claim_pid(s, {"pid": 500, "agent_exe": "claude.exe"})
    assert s["external"]["kind"] == "orquestador"
    origen["v"] = None  # el mismo proceso: la marca (de un plugin o del arbol) se conserva
    sessions.claim_pid(s, {"pid": 500, "agent_exe": "claude.exe"})
    assert s["external"] is not None
    sessions.claim_pid(s, {"pid": 501, "agent_exe": "claude.exe"})  # `claude --resume` en una terminal
    assert s["external"] is None and s["no_console"] is False


def _externa(sid="ext1"):
    s = sessions.new_session(sid, "claude", "hook")
    s.update(pid=4242, external={"kind": "orquestador", "via": "session_id", "run_id": "run-1"}, no_console=True)
    state.sessions[sid] = s
    return s


@pytest.fixture(autouse=True)
def _limpiar_tarjetas():
    antes = dict(state.sessions)
    yield
    state.sessions.clear()
    state.sessions.update(antes)


def test_send_y_run_send_rechazan_una_externa(monkeypatch):
    s = _externa()
    monkeypatch.setattr(sessions.backend, "agent_alive", lambda d: True)
    llamado = []
    monkeypatch.setattr(sessions.subprocess, "run", lambda *a, **k: llamado.append(a))
    code, body = sessions.send_blocked(s)
    assert code == 409 and "orquestador" in body["error"]
    assert sessions.run_send(s, "hola")[0] == 409
    assert sessions.run_send(s, "", enter=False, key="escape")[0] == 409
    assert llamado == []  # send.py nunca se lanzo


def test_acciones_de_tarjeta_sobre_una_externa(monkeypatch):
    import os

    import server

    _externa("ext2")
    hechas = []
    for nombre in ("kill", "send", "interrupt", "approve", "dialog", "native", "stopped", "coordinator"):
        metodo = "PUT" if nombre in ("stopped", "coordinator") else "POST"
        monkeypatch.setitem(
            server.ACCIONES_SESION,
            (metodo, nombre),
            server.AccionSesion(lambda d: None, lambda s, d, n=nombre: (hechas.append(n), (200, {}))[1]),
        )
        code, body = server.atender_accion(metodo, "ext2", nombre, {}, desde_tablero=False)
        assert code == 409, nombre
        assert body["external"]["kind"] == "orquestador"
    assert hechas == []
    os.makedirs(state.SESSIONS, exist_ok=True)  # el title guarda la tarjeta en la carpeta temporal
    code, _ = server.atender_accion("PUT", "ext2", "title", {"title": "corrida externa"}, desde_tablero=False)
    assert code == 200  # ponerle nombre si se puede


def test_on_stop_y_continuar_no_mueven_una_externa(monkeypatch):
    _externa("ext3")
    disparadas = []
    monkeypatch.setattr(rules, "fire_rule", lambda r, **k: disparadas.append(r["id"]))
    monkeypatch.setattr(rules.captura, "respuesta", lambda s: None)
    state.rules.items.append(
        {"id": "r1", "kind": "on_stop", "from": "ext3", "to": "otra", "text": "seguí", "enabled": True}
    )
    rules.fire_on_stop("ext3")
    assert disparadas == []
    antes = len(state.rules.items)
    rules.schedule_continue(state.sessions["ext3"], dt.datetime.now().astimezone(), "sin cupo")
    assert len(state.rules.items) == antes


def test_externa_no_queda_restaurable(monkeypatch):
    s = _externa("ext4")
    s.update(hooked=True, alive=True)
    recordadas = []
    monkeypatch.setattr(sessions.restore, "remember_live", lambda v: recordadas.extend(v))
    monkeypatch.setattr(sessions.restore, "live_due", lambda sid: True)
    sessions.remember_live_cards()
    assert recordadas == []
    olvidadas = []
    monkeypatch.setattr(sessions.restore, "remember", lambda *a, **k: recordadas.append(a))
    monkeypatch.setattr(sessions.restore, "forget", lambda sid: olvidadas.append(sid))
    sessions.restore_on_drop(dict(s), muerta=True)
    assert recordadas == [] and olvidadas == ["ext4"]
