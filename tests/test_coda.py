"""CODA: parser sobre la base SQLite, identidad por el log, modo batch e instalador."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install
from lienzo import coda, procinfo, transcripts

SID = "11111111-2222-4333-8444-555555555555"
CHILD = "66666666-7777-4888-9999-aaaaaaaaaaaa"


def base(tmp_path, rows, sessions=((SID, "root", "Revisión de prueba"), (CHILD, "agent", "subagente"))):
    """Una coda.db con el esquema real (las columnas que se leen) y las filas dadas."""
    path = tmp_path / "coda.db"
    c = sqlite3.connect(path)
    c.execute(
        "create table sessions (id text primary key, relationship text not null default 'root',"
        " project_dir text not null, title text, model text not null, created_at int, updated_at int)"
    )
    c.execute(
        "create table messages (id text primary key, session_id text not null, parent_id text,"
        " role text not null, content text not null, created_at integer not null)"
    )
    for sid, rel, title in sessions:
        c.execute("insert into sessions values (?, ?, 'D:\\Apps\\demo', ?, 'm', 0, 0)", (sid, rel, title))
    for i, (sid, role, content, parent, ts) in enumerate(rows):
        c.execute("insert into messages values (?, ?, ?, ?, ?, ?)", (f"m{i}", sid, parent, role, content, ts))
    c.commit()
    c.close()
    return str(path)


def asistente(*parts):
    return json.dumps(list(parts), ensure_ascii=False)


def llamada(cid, name, args):
    return {"type": "tool-call", "toolCallId": cid, "toolName": name, "args": args}


def test_turnos_herramientas_y_resultados(tmp_path):
    t0 = 1790265830000
    path = base(
        tmp_path,
        [
            (SID, "user", "hola", None, t0),
            (SID, "assistant", asistente({"type": "text", "text": "\n\n¡Hola!"}), None, t0 + 1),
            (SID, "user", "revisá el repo", None, t0 + 10),
            (
                SID,
                "assistant",
                asistente(
                    {"type": "text", "text": "Mapeo."},
                    llamada("b", "bash", {"command": "pytest"}),
                    llamada("r", "read", {"path": "D:\\Apps\\demo\\a.py"}),
                ),
                None,
                t0 + 11,
            ),
            (SID, "tool", "2 failed\n[exit code: 1]", "b", t0 + 11),
            (SID, "tool", "contenido", "r", t0 + 11),
            (SID, "user", "[CODA SYSTEM MESSAGE] Tool 'ask_user' was not executed", None, t0 + 11),
            (SID, "assistant", asistente({"type": "text", "text": "Listo, dos fallas."}), None, t0 + 12),
            (CHILD, "user", "tarea del subagente", None, t0 + 13),
        ],
    )
    r = transcripts.digest("coda", path, 10, leaf_id=SID)
    assert r["meta"]["title"] == "Revisión de prueba"
    assert r["meta"]["cwd"] == "D:\\Apps\\demo"
    hola, repo = r["turns"]
    assert hola["prompt"] == "hola" and hola["final"] == "¡Hola!" and hola["ended"]
    assert repo["prompt"] == "revisá el repo"  # el aviso del sistema no abre turno
    assert repo["final"] == "Listo, dos fallas." and repo["ended"]
    assert repo["commands"] == ["pytest"]
    assert repo["reads"] == 1
    assert repo["errors"] == ["bash: 2 failed"]
    assert repo["tools"] == 2


def test_turno_en_curso_e_interrumpido(tmp_path):
    t0 = 1790266000000
    path = base(
        tmp_path,
        [
            (SID, "user", "auditá", None, t0),
            (SID, "assistant", asistente(llamada("x", "read", {"path": "a.md"})), None, t0 + 1),
            (SID, "tool", "texto", "x", t0 + 1),
            (SID, "user", "[Request interrupted by user]", None, t0 + 1),
            (SID, "user", "seguí", None, t0 + 50),
        ],
    )
    auditar, seguir = transcripts.turns("coda", path, 10, leaf_id=SID)["turns"]
    assert auditar["ended"]
    assert auditar["blocks"][-1] == {"kind": "user_text", "text": "[Request interrupted by user]"}
    # CODA guarda el pedido al mandarlo y el resto al cerrar el turno: sin respuesta, sigue abierto
    assert seguir["prompt"] == "seguí" and not seguir["ended"]


def test_sin_sesion_no_lee_nada(tmp_path):
    path = base(tmp_path, [(SID, "user", "hola", None, 1)])
    assert transcripts.turns("coda", path, 10, leaf_id=None)["turns"] == []
    assert transcripts.leaf_of({"agent": "coda", "session_id": SID, "pi_leaf_id": "x"}) == SID
    assert transcripts.leaf_of({"agent": "pi", "session_id": SID, "pi_leaf_id": "x"}) == "x"


def test_identidad_por_log_ignora_subagentes(tmp_path, monkeypatch):
    base(tmp_path, [])
    (tmp_path / "logs").mkdir()
    lineas = [
        {"pid": 4242, "sessionId": "vieja", "clientName": "cli", "msg": "prompt started"},
        {"pid": 4242, "sessionId": SID, "clientName": "cli", "msg": "authorization.decision"},
        {"pid": 4242, "sessionId": CHILD, "clientName": "agent", "msg": "authorization.decision"},
        {"pid": 5151, "sessionId": "otra", "clientName": "cli", "msg": "prompt started"},
    ]
    (tmp_path / "logs" / "coda.log").write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    assert coda.session_of_pid(4242) == SID  # la ultima de la TUI, no la del subagente
    assert coda.identity(4242) == (SID, str(tmp_path / "coda.db"))
    assert coda.identity(5151) is None  # el log la nombra pero la base no la tiene
    assert coda.is_root(CHILD) is False


def test_modo_batch_y_subcomandos_no_son_tui():
    exe = r"C:\Users\x\.coda\bin\coda.exe"
    assert procinfo.agent_of(exe, f'"{exe}"') == "coda"
    assert procinfo.agent_of(exe, f'"{exe}" --lastsession') == "coda"
    assert procinfo.agent_of(exe, f'"{exe}" -p "corré los tests"') is None
    assert procinfo.agent_of(exe, f'"{exe}" --prompt-file p.md') is None
    assert procinfo.agent_of(exe, f'"{exe}" logs --follow') is None


def test_instalador_forma_exec_e_idempotente(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"model": "m", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "otro"}]}]}}))
    for _ in range(2):
        install.merge_hooks(str(cfg), "coda", install.CODA_EVENTS, False)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["model"] == "m"
    stop = data["hooks"]["Stop"]
    assert len(stop) == 2 and stop[0]["hooks"][0]["command"] == "otro"
    nuestro = stop[1]["hooks"][0]
    assert nuestro["args"] == [install.HOOK, "coda"] and nuestro["async"] is True
    install.merge_hooks(str(cfg), "coda", install.CODA_EVENTS, True, prune=True)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "otro"}]}]}


def test_pretooluse_muestra_el_avance_en_la_tarjeta():
    # server primero: arma sys.path y engancha los modulos sueltos (ver test_server.py)
    from lienzo import server  # noqa: F401, I001
    import sessions as ses

    s = ses.new_session(SID, "coda", "hook")
    s["state"] = "corriendo"
    ses.coda_tool(s, {"tool_name": "bash", "tool_input": {"command": "cd /mnt/d/x && ruff check\n."}})
    ses.coda_tool(s, {"tool_name": "read", "tool_input": {"path": r"D:\Apps\demo\docs\02.md"}}, sub=True)
    ses.coda_tool(s, {"tool_name": "edit", "tool_input": {"path": "a.py"}})
    assert s["tool_count"] == 3
    assert s["last_cmd"] == "ruff check ."
    assert s["last_files"] == ["a.py", "02.md"]
    assert s["last_reply"] == "usando edit"
    ses.coda_tool(s, {"tool_name": "grep", "tool_input": {}}, sub=True)
    assert s["last_reply"] == "usando grep (subagente)"


def test_pretooluse_despues_del_cierre_reabre_el_turno():
    from lienzo import server  # noqa: F401, I001
    import sessions as ses

    s = ses.new_session(SID, "coda", "hook")
    s["state"], s["state_since"] = "termino", "2026-09-25T00:27:37.000-03:00"
    # PreToolUse del turno anterior que llega tarde: no reabre nada
    ses.coda_tool(s, {"tool_name": "bash", "host_ts": "2026-09-25T00:27:30.000-03:00", "tool_input": {}})
    assert s["state"] == "termino"
    # sin UserPromptSubmit, una herramienta posterior es un turno en curso
    ses.coda_tool(s, {"tool_name": "read", "host_ts": "2026-09-25T00:28:00.000-03:00", "tool_input": {}})
    assert s["state"] == "corriendo"
    assert s["last_reply"] == "usando read"


def test_actividad_del_log_sin_hooks(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    lineas = [
        {"pid": 4242, "clientName": "cli", "msg": "prompt started"},
        {"pid": 4242, "clientName": "cli", "msg": "authorization.decision", "toolName": "bash"},
        {"pid": 4242, "clientName": "cli", "msg": "prompt complete"},
        {"pid": 4242, "clientName": "cli", "msg": "prompt started"},
        {"pid": 4242, "clientName": "cli", "msg": "authorization.decision", "toolName": "skills"},
        {"pid": 4242, "clientName": "agent", "msg": "authorization.decision", "toolName": "read"},
        {"pid": 999, "clientName": "cli", "msg": "authorization.decision", "toolName": "grep"},
    ]
    (tmp_path / "logs" / "coda.log").write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    assert coda.activity(4242) == {"running": True, "tools": 2, "last_tool": "read", "sub": True, "asking": None}
    assert coda.activity(1234) is None


def test_pedido_de_permiso_abierto_y_contestado(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "coda.log"
    ask = {"pid": 4242, "clientName": "cli", "sessionId": SID, "msg": "authorization.decision"}
    lineas = [
        {"pid": 4242, "clientName": "cli", "msg": "prompt started"},
        {**ask, "toolName": "bash", "decision": "ask", "askCause": "command-policy", "time": "t1"},
        {**ask, "toolName": "read", "decision": "allow"},  # siguio: el primero se contesto
        {**ask, "toolName": "wait_agents", "decision": "ask", "time": "t2"},
        # un subagente que sigue trabajando no contesta el pedido de la TUI
        {"pid": 4242, "clientName": "agent", "sessionId": CHILD, "msg": "authorization.decision", "toolName": "read"},
    ]
    log.write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    assert coda.activity(4242)["asking"] == {"tool": "wait_agents", "cause": None, "sub": False, "at": "t2"}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**ask, "msg": "turn complete"}) + "\n")
    assert coda.activity(4242)["asking"] is None
