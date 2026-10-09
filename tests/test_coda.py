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


def test_pretooluse_ask_user_es_una_pregunta_no_un_permiso():
    """ask_user auto-aprobado por el hook (tiene que correr para preguntar) dejaba la tarjeta en
    corriendo mientras CODA preguntaba en su terminal (medido el 2026-10-09 en ar-it33940)."""
    from lienzo import server  # noqa: F401, I001
    import sessions as ses

    s = ses.new_session(SID, "coda", "hook")
    s["state"] = "corriendo"
    ev = {
        "tool_name": "ask_user",
        "auto_aprobado": True,
        "host_ts": "2026-10-09T12:18:38.000-03:00",
        "tool_input": {"question": "¿Seguimos con Kiro o con Pi?", "options": ["kiro", "pi"]},
    }
    ses.coda_tool(s, ev)
    assert s["state"] == "te_necesita"
    assert s["needs"]["kind"] == "question"
    assert s["needs"]["tool"] == "ask_user"
    assert s["needs"]["detail"] == "¿Seguimos con Kiro o con Pi?"
    assert s["needs"]["where"] == "terminal" and s["needs"]["via"] == "tool"
    assert s["needs"]["coda_at"] == "tool:2026-10-09T12:18:38.000-03:00"
    # la herramienta siguiente es la respuesta ya dada: vuelve a corriendo
    ses.coda_tool(s, {"tool_name": "bash", "tool_input": {"command": "kiro-cli"}})
    assert s["state"] == "corriendo" and s["needs"] is None
    # un subagente que pregunta no le pregunta al usuario
    ses.coda_tool(s, {"tool_name": "ask_user", "tool_input": {"question": "x"}}, sub=True)
    assert s["state"] == "corriendo"


def test_ask_user_sin_auto_aprobar_vuelve_a_la_pregunta_tras_el_permiso(monkeypatch):
    """Sin auto-aprobar, el log de CODA muestra el permiso de ask_user despues del PreToolUse: la
    tarjeta pide el permiso y, contestado, vuelve a la pregunta en vez de pasar a corriendo."""
    from lienzo import server  # noqa: F401, I001
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    ask = {"cause": None, "tool": "ask_user", "sub": False, "at": "2026-10-09T15:18:39.000Z"}
    act = {"running": True, "asking": ask, "last_at": None, "last_tool": "ask_user", "tools": 1, "sub": False}
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = ses.new_session(SID, "coda", "hook")
    s["pid"], s["state"] = 1, "corriendo"
    ses.coda_tool(s, {"tool_name": "ask_user", "tool_input": {"question": "¿Kiro o Pi?"}})
    assert s["needs"]["kind"] == "question"
    ses.coda_log_activity(s)
    assert s["needs"]["kind"] == "permission" and s["needs"]["tool"] == "ask_user"
    act["asking"] = None  # se permitio: el `ask` deja el log
    ses.coda_log_activity(s)
    assert s["state"] == "te_necesita"
    assert s["needs"]["kind"] == "question" and s["needs"]["detail"] == "¿Kiro o Pi?"
    # la pregunta se contesta en la terminal: la herramienta siguiente vuelve a corriendo
    ses.coda_tool(s, {"tool_name": "bash", "tool_input": {"command": "kiro-cli"}})
    assert s["state"] == "corriendo"


def test_ask_user_abierto_antes_del_reinicio_se_ve_en_la_relectura(monkeypatch):
    """La tarjeta restaurada quedo en corriendo con «usando ask_user» y ningun evento despues: la
    relectura del log de coda la pasa a «Te hace una pregunta» (2026-10-09, ar-it33940)."""
    from lienzo import server  # noqa: F401, I001
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    act = {"running": True, "asking": None, "last_at": None, "last_tool": "ask_user", "tools": 1, "sub": False}
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = ses.new_session(SID, "coda", "hook")
    s.update(pid=1, state="corriendo", last_event="PreToolUse", last_reply="usando ask_user")
    s["last_event_ts"] = "2026-10-09T12:21:32.000-03:00"
    ses.coda_log_activity(s)
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "question" and s["needs"]["tool"] == "ask_user"
    ses.coda_log_activity(s)  # la siguiente relectura no la toca
    assert s["needs"]["kind"] == "question"
    # otra herramienta en curso, o un turno cerrado: nada que preguntar
    for ultimo, corre in (("usando bash", True), ("usando ask_user", False)):
        s2 = ses.new_session(SID, "coda", "hook")
        s2.update(pid=1, state="corriendo", last_event="PreToolUse", last_reply=ultimo)
        act["running"] = corre
        ses.coda_log_activity(s2)
        assert s2["needs"] is None, ultimo
    act["running"] = True


def test_el_turno_abierto_de_coda_muestra_en_vivo_lo_que_vio_el_hook():
    """CODA guarda el turno al cerrarlo: el digest del turno abierto se completa con las
    herramientas del hook desde que empezo; uno cerrado no se toca (2026-10-09)."""
    from lienzo import server  # noqa: F401, I001
    import sessions as ses

    ses.CODA_VIVO.pop(SID, None)
    s = ses.new_session(SID, "coda", "hook")
    s["state"] = "corriendo"
    viejo = {
        "tool_name": "bash",
        "host_ts": "2026-10-09T12:00:00.000-03:00",
        "tool_input": {"command": "turno anterior"},
    }
    ses.coda_tool(s, viejo)
    for ev in (
        {
            "tool_name": "bash",
            "host_ts": "2026-10-09T12:21:10.000-03:00",
            "tool_input": {"command": "winget search kiro"},
        },
        {
            "tool_name": "read",
            "host_ts": "2026-10-09T12:21:20.000-03:00",
            "tool_input": {"path": "D:/apps/lienzo/README.md"},
        },
        {
            "tool_name": "ask_user",
            "host_ts": "2026-10-09T12:21:32.000-03:00",
            "tool_input": {"question": "¿Kiro o Pi?"},
        },
    ):
        ses.coda_tool(s, ev)
    abierto = {
        "ts_start": "2026-10-09T12:21:04.659-03:00",
        "ended": False,
        "prompt": "y pi dev",
        "tools": 0,
        "says": [],
    }
    t = ses.coda_vivo_en_turno(SID, abierto)
    assert t["tools"] == 3 and t["commands"] == ["winget search kiro"]
    assert t["files"] == ["D:/apps/lienzo/README.md"] and t["questions"] == ["¿Kiro o Pi?"]
    assert t["says"][-1] == "en vivo: 3 herramientas, la última ask_user"
    assert ses.coda_vivo_en_turno(SID, {**abierto, "ended": True}) == {**abierto, "ended": True}
    ses.CODA_VIVO.pop(SID, None)


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
        {
            "pid": 4242,
            "clientName": "agent",
            "msg": "authorization.decision",
            "toolName": "read",
            "time": "2026-09-25T03:36:28.816Z",
        },
        {"pid": 999, "clientName": "cli", "msg": "authorization.decision", "toolName": "grep"},
    ]
    (tmp_path / "logs" / "coda.log").write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    act = coda.activity(4242)
    assert act.pop("last_at") == "2026-09-25T03:36:28.816Z"
    assert act == {"running": True, "tools": 2, "last_tool": "read", "sub": True, "asking": None}
    assert coda.activity(1234) is None


def test_corte_de_cuota_temporal_no_queda_en_la_tarjeta(tmp_path, monkeypatch):
    """«coda sin cuota» quedaba para siempre aunque coda siguiera trabajando (2026-10-09)."""
    from lienzo import server  # noqa: F401, I001
    import sessions as ses

    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "coda.log"
    lineas = [
        {"pid": 4242, "clientName": "cli", "msg": "prompt started"},
        {"pid": 4242, "clientName": "cli", "msg": "llm error", "detail": "Quota exceeded (code 154)"},
    ]
    log.write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODA_HOME", str(tmp_path))
    assert coda.activity(4242)["error"].startswith("coda sin cuota")
    s = ses.new_session(SID, "coda", "hook")
    s.update(pid=4242, state="corriendo")
    ses.coda_log_activity(s)
    assert s["last_error"].startswith("coda sin cuota")
    # siguio corriendo herramientas en el mismo turno: el corte fue temporal
    lineas.append({"pid": 4242, "clientName": "cli", "msg": "authorization.decision", "toolName": "bash"})
    log.write_text("\n".join(json.dumps(d) for d in lineas) + "\n", encoding="utf-8")
    assert "error" not in coda.activity(4242)
    ses.coda_log_activity(s)
    assert s["last_error"] is None


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


def test_el_permiso_de_coda_se_detecta_aunque_el_titulo_se_salga_de_la_pantalla():
    import sessions as ses

    titulo = "  Approval Required\n  bash\n  echo hola\n  ❯ Yes\n    No\n  ↑↓ move · Enter confirm · Esc deny"
    largo = (
        "\n".join(f"  linea {i} de un heredoc" for i in range(40))
        + "\n  ❯ Yes\n    No\n  ↑↓ move · Enter confirm · Esc deny"
    )
    assert ses.coda_ask_open(titulo) is True
    assert ses.coda_ask_open(largo) is True  # el titulo ya no se ve, el pie sí
    assert ses.coda_ask_open("  Ask anything... (/ for commands ? for shortcuts)") is False
    assert ses.coda_ask_open("Enter confirm  sin el otro texto") is False


def test_compactacion_de_coda_no_cuenta_como_fin_de_turno(monkeypatch):
    """PreCompact marca la sesion; un Stop en medio no la deja en `termino`, y la marca vence."""
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    s = {"session_id": "a" * 36, "agent": "coda", "state": "corriendo", "state_since": "x", "needs": None}
    s["compacting"] = ses.time.time()
    ses.hook_stop(s, {"last_assistant_message": "resumen"})
    assert s["state"] == "corriendo" and not s.get("last_reply")
    s["compacting"] = ses.time.time() - ses.COMPACTING_MAX_S - 1  # PostCompact nunca llego
    ses.hook_stop(s, {"last_assistant_message": "listo"})
    assert s["state"] == "termino" and s["last_reply"] == "listo"
    assert "PreCompact" in __import__("install").CODA_EVENTS and "PostCompact" in __import__("install").CODA_EVENTS


def test_permiso_enviado_que_sigue_abierto_devuelve_los_botones(monkeypatch):
    """Tras Permitir/Denegar la tarjeta queda `enviado`; si el log sigue mostrando el permiso abierto
    pasado CODA_SENT_RETRY_S (el Enter no hizo efecto), vuelve a `terminal` y muestra los botones."""
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    ask = {"cause": "command-policy", "tool": "bash", "sub": False, "at": "2026-10-03T01:03:27.675Z"}
    act = {"running": True, "asking": ask, "last_at": None, "last_tool": "bash", "tools": 3, "sub": False}
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = {
        "session_id": "b" * 36,
        "agent": "coda",
        "pid": 1,
        "state": "te_necesita",
        "state_since": "x",
        "hooked": True,
        "needs": {
            "kind": "permission",
            "tool": "bash",
            "where": "enviado",
            "coda_at": ask["at"],
            "sent_ts": ses.time.time(),
        },
    }
    ses.coda_log_activity(s)
    assert s["needs"]["where"] == "enviado"  # recien enviado: se espera
    s["needs"]["sent_ts"] = ses.time.time() - ses.CODA_SENT_RETRY_S - 1
    ses.coda_log_activity(s)
    assert s["needs"]["where"] == "terminal"


def test_una_denegacion_de_coda_llega_a_la_tarjeta_una_sola_vez(monkeypatch):
    import sessions as ses
    import state as st

    logs = []
    monkeypatch.setattr(st, "log", logs.append)
    den = {"tool": "bash", "cause": "command-policy", "sub": False, "at": "2026-10-04T01:00:00Z"}
    act = {
        "running": True,
        "asking": None,
        "last_at": None,
        "last_tool": "bash",
        "tools": 2,
        "sub": False,
        "denied": den,
    }
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = {
        "session_id": "d" * 36,
        "agent": "coda",
        "pid": 1,
        "state": "corriendo",
        "state_since": "x",
        "hooked": True,
        "needs": None,
        "last_cmd": "git push --force",
    }
    ses.coda_log_activity(s)
    assert s["last_denied"]["tool"] == "bash" and s["last_denied"]["detalle"] == "git push --force"
    assert "comando que pide" in s["last_denied"]["motivo"]
    ses.coda_log_activity(s)
    assert sum("DENEGADO" in x for x in logs) == 1


def test_la_denegacion_del_turno_anterior_no_vuelve_despues_de_un_pedido_nuevo(monkeypatch):
    """Medido el 2026-10-04 en ar-it33940: cada «Autorizar y que reintente» borraba la marca (pedido
    nuevo) y la lectura siguiente del log, que todavia no tenia el «prompt started» del turno nuevo,
    volvia a poner la denegacion del turno anterior: el boton no se iba y Ariel lo apreto 15 veces."""
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    den = {"tool": "bash", "cause": "command-policy", "sub": False, "at": "2026-10-04T23:59:56Z"}
    act = {
        "running": True,
        "asking": None,
        "last_at": None,
        "last_tool": "bash",
        "tools": 2,
        "sub": False,
        "denied": den,
    }
    monkeypatch.setattr(ses.coda, "activity", lambda pid: act)
    s = {
        "session_id": "e" * 36,
        "agent": "coda",
        "pid": 1,
        "state": "corriendo",
        "state_since": "x",
        "hooked": True,
        "needs": None,
        "last_cmd": None,
        "last_denied": None,  # el pedido nuevo la acaba de borrar
        "prompt_ts": "2026-10-04T21:00:00.349-03:00",  # 00:00:00 UTC: despues de la denegacion
    }
    ses.coda_log_activity(s)
    assert s["last_denied"] is None
    # una denegacion del turno en curso si llega
    act["denied"] = {**den, "at": "2026-10-05T00:00:05Z"}
    ses.coda_log_activity(s)
    assert s["last_denied"] and s["last_denied"]["tool"] == "bash"


def test_propose_policy_de_coda_pone_la_tarjeta_en_te_necesita_y_la_siguiente_herramienta_la_libera(monkeypatch):
    """Medido el 2026-10-04: propose_policy abre «Approval Required» sin dejar un ask en el log; la
    tarjeta seguia en corriendo y ni el tablero ni el auto-aprobar lo veian."""
    import sessions as ses
    import state as st

    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    s = {"session_id": "e" * 36, "agent": "coda", "state": "corriendo", "state_since": "x", "needs": None}
    ses.coda_tool(s, {"tool_name": "propose_policy", "tool_input": {"rule": "git reset --hard"}, "host_ts": "t1"})
    n = s["needs"]
    assert s["state"] == "te_necesita" and n["kind"] == "permission" and n["where"] == "terminal" and n["coda_at"]
    assert "git reset --hard" in n["detail"]
    # el log no muestra un ask: igual no se limpia (lo cierra la proxima herramienta)
    monkeypatch.setattr(
        ses.coda,
        "activity",
        lambda pid: {
            "running": True,
            "asking": None,
            "last_at": None,
            "last_tool": "propose_policy",
            "tools": 1,
            "sub": False,
        },
    )
    s["pid"], s["hooked"] = 1, True
    ses.coda_log_activity(s)
    assert s["state"] == "te_necesita"
    ses.coda_tool(s, {"tool_name": "bash", "tool_input": {"command": "ls"}, "host_ts": "t2"})
    assert s["state"] == "corriendo" and s["needs"] is None


def test_un_permiso_cuyo_inicio_de_turno_quedo_fuera_de_la_ventana_igual_se_ve(tmp_path, monkeypatch):
    """Medido el 2026-10-04: el «prompt started» quedo antes del ultimo MB del log (compartido por
    todas las codas) y el «ask» de npm run build no se veia: ni el tablero ni el auto-aprobar."""
    import json as _json

    import coda

    logs = tmp_path / "logs"
    logs.mkdir()
    linea = {
        "pid": 77,
        "clientName": "cli",
        "sessionId": "s1",
        "msg": "authorization.decision",
        "toolName": "bash",
        "decision": "ask",
        "askCause": "command-policy",
        "time": "t1",
    }
    (logs / "coda.log").write_text(_json.dumps(linea) + "\n", encoding="utf-8")
    monkeypatch.setattr(coda, "home", lambda: str(tmp_path))
    act = coda.activity(77)
    assert act is not None and act["running"] and act["asking"]["tool"] == "bash"
