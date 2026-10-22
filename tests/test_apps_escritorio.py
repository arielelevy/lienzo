"""Apps de escritorio (ronda 2026-10-17): Claude Desktop y Codex desktop se ven como tarjetas de solo
lectura, marcadas `external` con `desktop: True`. Las rutas son las medidas en esta PC; el barrido y
las CLI siguen como antes."""

import json
import os
import time

import agentes
import backend
import hooks_eventos
import procs
import pytest
import sessions
import state

# medidas: el SessionStart de Claude Desktop del 2026-09-14 (ruta real del paquete MSIX), la ruta
# virtualizada que cita docs/desktop-apps.md, y las CLI que corren hoy en esta PC
MOTOR_DESKTOP = (
    r"C:\Users\ArielLevy\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
    r"\claude-code\2.1.260\claude.exe"
)
MOTOR_VIRTUAL = r"C:\Users\ArielLevy\AppData\Roaming\Claude\claude-code\2.1.284\claude.exe"
APP_CLAUDE = r"C:\Program Files\WindowsApps\Claude_2.16120.0.0_x64__pzs8sxrjxfjjc\app\Claude.exe"
APP_CODEX = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1007.9446.0_x64__2p2nqsd0c76g0\app\Codex.exe"
CLI_CLAUDE = r"C:\Users\ArielLevy\.local\bin\claude.exe"
CLI_CODEX = r"C:\Users\ArielLevy\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe"
EXT_VSCODE = r"C:\Users\x\.vscode\extensions\anthropic.claude-code-2.0\native-binary\claude.exe"


@pytest.fixture(autouse=True)
def _tarjetas_limpias():
    os.makedirs(state.SESSIONS, exist_ok=True)  # touch() guarda la tarjeta
    antes = dict(state.sessions)
    state.sessions.clear()
    yield
    state.sessions.clear()
    state.sessions.update(antes)


# 1. reconocer la app por la ruta ----------------------------------------------------------------


@pytest.mark.parametrize(
    "exe,app",
    [
        (MOTOR_DESKTOP, "claude-desktop"),
        (MOTOR_VIRTUAL, "claude-desktop"),
        (MOTOR_DESKTOP.upper(), "claude-desktop"),
        (APP_CLAUDE, "claude-desktop"),
        (APP_CODEX, "codex-desktop"),
        (CLI_CLAUDE, None),
        (CLI_CODEX, None),  # la CLI de Codex vive bajo OpenAI\Codex, no es la app
        (EXT_VSCODE, None),  # anthropic.claude-code-..., no \Claude\claude-code\
        (None, None),
    ],
)
def test_desktop_app_por_ruta(exe, app):
    assert procs.desktop_app(exe) == app


def _arbol(monkeypatch, arbol, cmd="claude"):
    monkeypatch.setattr(procs, "proc_info", lambda pid: arbol.get(pid, (None, None)))
    monkeypatch.setattr(procs, "image_path", lambda pid: arbol.get(pid, (None, None))[1])
    monkeypatch.setattr(procs.procinfo, "command_line", lambda pid: cmd)


def test_external_origin_del_motor_de_desktop(monkeypatch):
    _arbol(monkeypatch, {10: (11, MOTOR_DESKTOP), 11: (12, APP_CLAUDE), 12: (1, r"C:\Windows\explorer.exe")})
    assert procs.external_origin(10) == {"kind": "claude-desktop", "via": "ruta", "desktop": True}


def test_external_origin_por_el_padre_si_el_motor_esta_en_otra_carpeta(monkeypatch):
    _arbol(monkeypatch, {10: (11, r"C:\otra\claude.exe"), 11: (12, APP_CLAUDE)})
    assert procs.external_origin(10) == {"kind": "claude-desktop", "via": "proceso", "desktop": True}


def test_external_origin_de_la_cli_sigue_personal(monkeypatch):
    _arbol(monkeypatch, {10: (11, CLI_CLAUDE), 11: (12, r"C:\p\pwsh.exe"), 12: (1, r"C:\w\WindowsTerminal.exe")})
    assert procs.external_origin(10) is None


def test_is_tui_no_toma_el_motor_de_desktop(monkeypatch):
    _arbol(monkeypatch, {10: (11, MOTOR_DESKTOP), 11: (1, APP_CLAUDE)})
    monkeypatch.setattr(procs.procinfo, "process_agent", lambda pid: "claude")
    assert procs.is_tui(10) is False
    _arbol(monkeypatch, {10: (11, CLI_CLAUDE), 11: (1, r"C:\p\pwsh.exe")})
    assert procs.is_tui(10) is True


def test_fila_del_barrido_de_desktop_es_externa():
    assert procs.external_of_row({"exe": MOTOR_DESKTOP, "parent": "Claude.exe"})["kind"] == "claude-desktop"
    fila = {"exe": r"C:\otra\claude.exe", "parent": "Claude.exe", "parent_exe": APP_CLAUDE}
    assert procs.external_of_row(fila) == {"kind": "claude-desktop", "via": "proceso", "desktop": True}
    assert procs.external_of_row({"exe": CLI_CLAUDE, "parent": "pwsh.exe", "cmd": "claude"}) is None


# 2. barrido: regresion con un arbol que mezcla CLI, motor de Desktop, Electron y app-server ------


def test_barrido_mezclado(monkeypatch):
    filas = [
        {
            "pid": 1,
            "exe": CLI_CLAUDE,
            "cmd": '"claude.exe"',
            "parent": "pwsh.exe",
            "grandparent": "WindowsTerminal.exe",
        },
        {"pid": 2, "exe": CLI_CODEX, "cmd": '"codex.exe" -c x=1', "parent": "cmd.exe", "grandparent": "Code.exe"},
        {
            "pid": 3,
            "exe": MOTOR_DESKTOP,
            "cmd": '"claude.exe" --output-format stream-json',
            "parent": "Claude.exe",
            "parent_exe": APP_CLAUDE,
        },
        {"pid": 4, "exe": APP_CLAUDE, "cmd": '"Claude.exe"', "parent": "explorer.exe"},
        {"pid": 5, "exe": APP_CLAUDE, "cmd": '"Claude.exe" --type=renderer', "parent": "Claude.exe"},
        {"pid": 6, "exe": CLI_CODEX, "cmd": '"codex.exe" app-server', "parent": "Codex.exe"},
    ]
    monkeypatch.setattr(procs.subproc, "correr", lambda *a, **k: (0, json.dumps(filas), ""))
    vistos = {p["pid"]: p for p in procs.sweep()}
    assert sorted(vistos) == [1, 2, 3]  # la app Electron y el app-server siguen afuera
    assert vistos[1]["external"] is None and vistos[2]["external"] is None
    assert vistos[2]["in_vscode"] is True
    assert vistos[3]["external"] == {"kind": "claude-desktop", "via": "ruta", "desktop": True}


def test_adoptar_el_motor_de_desktop_deja_tarjeta_de_solo_lectura(monkeypatch):
    monkeypatch.setattr(sessions.backend, "cwd_of", lambda p: r"C:\prueba-desktop")
    monkeypatch.setattr(sessions, "guess_transcript", lambda *a, **k: (None, None))
    p = {"pid": 77, "agent": "claude", "exe": MOTOR_DESKTOP, "external": procs.external_of_row({"exe": MOTOR_DESKTOP})}
    sessions.adopt_process(p)
    (s,) = state.sessions.values()
    assert s["external"]["kind"] == "claude-desktop" and s["no_console"] is True


# 3. hooks: la tarjeta que nace por evento sale de solo lectura ----------------------------------


def test_claim_pid_del_motor_de_desktop(monkeypatch):
    _arbol(monkeypatch, {90: (91, MOTOR_DESKTOP), 91: (1, APP_CLAUDE)})
    monkeypatch.setattr(procs.procinfo, "process_agent", lambda pid: "claude")
    monkeypatch.setattr(backend, "is_tmux", lambda d: False)
    s = sessions.new_session("dddd", "claude", "hook")
    hooks_eventos.claim_pid(s, {"pid": 90, "agent_exe": MOTOR_DESKTOP})
    assert s["external"]["kind"] == "claude-desktop" and s["no_console"] is True


def test_envio_y_acciones_a_una_de_desktop_explican_por_que_no(monkeypatch):
    s = sessions.new_session("eeee", "claude", "hook")
    s.update(pid=4242, external={"kind": "claude-desktop", "via": "ruta", "desktop": True}, no_console=True)
    state.sessions["eeee"] = s
    monkeypatch.setattr(sessions.backend, "agent_alive", lambda d: True)
    code, body = sessions.send_blocked(s)
    assert code == 409 and "app de escritorio (Claude Desktop)" in body["error"]
    code, body = sessions.external_blocked(s, "cerrarla")
    assert code == 409 and "no se puede cerrarla" in body["error"]


# 4. Codex desktop: hilos por rollout, sin proceso -----------------------------------------------


def _rollout(home, nombre, originator, sid, cwd=r"D:\prueba-desktop", cerrado=True, mtime=None):
    d = os.path.join(home, ".codex", "sessions", "2026", "10", "17")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"rollout-2026-10-17T11-00-00-{nombre}.jsonl")
    ts = "2026-10-17T14:00:00.000Z"
    filas = [
        {
            "timestamp": ts,
            "type": "session_meta",
            "payload": {
                "id": sid,
                "session_id": sid,
                "cwd": cwd,
                "originator": originator,
                "source": "vscode",
                "timestamp": ts,
            },
        },
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}},
        {
            "timestamp": ts,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "revisá el README"}],
            },
        },
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "user_message", "message": "revisá el README"}},
    ]
    if cerrado:
        filas += [
            {
                "timestamp": ts,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Listo, revisado."}],
                },
            },
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "agent_message", "message": "Listo, revisado."}},
            {
                "timestamp": ts,
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "t1", "last_agent_message": "Listo, revisado."},
            },
        ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in filas) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(agentes, "_cabeceras", {})
    monkeypatch.setattr(agentes, "_importados", (-1.0, frozenset()))
    return str(tmp_path)


def test_hilos_de_la_app_sin_importados_ni_cli(home):
    _rollout(home, "a", "codex_work_desktop", "hilo-app")
    _rollout(home, "b", "Codex Desktop", "importado")
    _rollout(home, "c", "Codex Desktop", "app-vieja-sin-importar")
    _rollout(home, "d", "codex-tui", "tui")
    _rollout(home, "e", "codex_exec", "exec")
    _rollout(home, "f", "codex_work_desktop", "dormido", mtime=time.time() - 3 * 86400)
    roto = _rollout(home, "g", "codex_work_desktop", "roto")
    with open(roto, "w", encoding="utf-8") as f:
        f.write('{"timestamp": "2026-10-17T14:00:00Z", "type": "session_me')  # a medio escribir
    with open(os.path.join(home, ".codex", "external_agent_session_imports.json"), "w", encoding="utf-8") as f:
        json.dump({"records": [{"imported_thread_id": "importado", "source_path": "x.jsonl"}]}, f)
    hilos = agentes.codex_desktop_threads(time.time() - 3600, os.path.join(home, ".codex"))
    assert sorted(h["id"] for h in hilos) == ["app-vieja-sin-importar", "hilo-app"]
    assert {h["cwd"] for h in hilos} == {r"D:\prueba-desktop"}


def test_import_ilegible_no_rompe_y_conserva_el_ultimo(home):
    _rollout(home, "b", "Codex Desktop", "importado")
    imports = os.path.join(home, ".codex", "external_agent_session_imports.json")
    with open(imports, "w", encoding="utf-8") as f:
        json.dump({"records": [{"imported_thread_id": "importado"}]}, f)
    assert agentes.codex_desktop_threads(0, os.path.join(home, ".codex")) == []
    with open(imports, "w", encoding="utf-8") as f:
        f.write("{roto")
    os.utime(imports, (time.time() + 5, time.time() + 5))
    assert agentes.codex_desktop_threads(0, os.path.join(home, ".codex")) == []


def test_guess_codex_sigue_sin_tomar_hilos_de_la_app(home):
    _rollout(home, "a", "codex_work_desktop", "hilo-app")
    assert agentes.guess_codex(r"D:\prueba-desktop", time.time() - 3600, home) == (None, None)


def test_adopt_desktop_threads_arma_retira_y_no_pisa(home, monkeypatch):
    path = _rollout(home, "a", "codex_work_desktop", "hilo-app")
    hilos = [
        {
            "id": "hilo-app",
            "path": path,
            "cwd": r"D:\prueba-desktop",
            "originator": "codex_work_desktop",
            "started": "2026-10-17T14:00:00.000Z",
            "mtime": time.time(),
        }
    ]
    monkeypatch.setattr(sessions, "codex_desktop_threads", lambda since: list(hilos))
    sessions.adopt_desktop_threads()
    s = state.sessions["hilo-app"]
    assert s["agent"] == "codex" and s["pid"] is None and s["source"] == "desktop"
    assert s["external"] == {"kind": "codex-desktop", "via": "rollout", "desktop": True} and s["no_console"]
    assert s["state"] == "termino" and s["last_prompt"] == "revisá el README"
    assert s["last_reply"] == "Listo, revisado."
    sessions.adopt_desktop_threads()  # idempotente
    assert list(state.sessions) == ["hilo-app"]

    # la liveness la deja viva aunque no tenga pid, y relee el rollout cuando crece
    sessions.check_liveness("hilo-app")
    assert s["alive"] is True and s["state"] == "termino"
    _rollout(home, "a", "codex_work_desktop", "hilo-app", cerrado=False)
    os.utime(path, (time.time() + 10, time.time() + 10))
    sessions.check_liveness("hilo-app")
    assert s["state"] == "corriendo"

    hilos.clear()  # sin escribir en DESKTOP_THREAD_TTL_S
    sessions.adopt_desktop_threads()
    assert "hilo-app" not in state.sessions


def test_un_hilo_con_tarjeta_propia_no_se_reemplaza(home, monkeypatch):
    tui = sessions.new_session("hilo-app", "codex", "sweep")
    tui["pid"] = 55
    state.sessions["hilo-app"] = tui
    path = _rollout(home, "a", "codex_work_desktop", "hilo-app")
    monkeypatch.setattr(
        sessions,
        "codex_desktop_threads",
        lambda since: [
            {
                "id": "hilo-app",
                "path": path,
                "cwd": "x",
                "originator": "codex_work_desktop",
                "started": None,
                "mtime": 0,
            }
        ],
    )
    sessions.adopt_desktop_threads()
    assert state.sessions["hilo-app"] is tui and tui["external"] is None
    monkeypatch.setattr(sessions, "codex_desktop_threads", lambda since: [])
    sessions.adopt_desktop_threads()
    assert state.sessions["hilo-app"] is tui  # solo se retiran las que armo el lector


# 5. registro de Claude Code (~/.claude/sessions/<pid>.json), medido 2026-10-17 -------------------


def _registro(tmp_path, monkeypatch, pid=3568, entrypoint="claude-desktop", proc_start="134367221876782859", **extra):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    d = tmp_path / "claude" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    reg = {
        "pid": pid,
        "sessionId": "5d0f9e6b-ccc4-4f30-a58d-9284886b0f56",
        "procStart": proc_start,
        "kind": "interactive",
        "entrypoint": entrypoint,
        "name": "Sesión de prueba",
        "status": "idle",
        "messagingSocketPath": r"\.\pipe\LOCAL\cc-msg-x",
        "hostSessionId": "local_x",
        **extra,
    }
    (d / f"{pid}.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    (d / f"{pid}.abc.key").write_text("secreto", encoding="utf-8")
    return reg


def test_claude_registro_solo_del_mismo_proceso_y_sin_el_pipe(tmp_path, monkeypatch):
    _registro(tmp_path, monkeypatch)
    reg = agentes.claude_registro(3568, 134367221876782859)
    assert reg == {
        "sessionId": "5d0f9e6b-ccc4-4f30-a58d-9284886b0f56",
        "entrypoint": "claude-desktop",
        "name": "Sesión de prueba",
        "kind": "interactive",
        "status": "idle",
    }
    assert agentes.claude_registro(3568, 1) is None  # pid reciclado: otro procStart
    assert agentes.claude_registro(3568, None) is None  # sin poder verificarlo no se usa
    assert agentes.claude_registro(4000, 134367221876782859) is None  # sin archivo
    (tmp_path / "claude" / "sessions" / "3568.json").write_text("{roto", encoding="utf-8")
    assert agentes.claude_registro(3568, 134367221876782859) is None


def test_external_origin_prefiere_el_registro_y_trae_el_canal(tmp_path, monkeypatch):
    _registro(tmp_path, monkeypatch)
    monkeypatch.setattr(procs, "creation_filetime", lambda pid: 134367221876782859)
    _arbol(monkeypatch, {3568: (5060, r"C:\cualquier\claude.exe"), 5060: (1, r"C:\Windows\explorer.exe")})
    assert procs.external_origin(3568) == {
        "kind": "claude-desktop",
        "via": "registro",
        "desktop": True,
        "canal": "Sesión de prueba",
    }
    _registro(tmp_path, monkeypatch, entrypoint="cli")
    assert procs.external_origin(3568) is None  # una CLI con registro sigue personal


def test_barrido_toma_el_registro_antes_que_la_ruta(tmp_path, monkeypatch):
    _registro(tmp_path, monkeypatch, pid=3)
    monkeypatch.setattr(procs, "creation_filetime", lambda pid: 134367221876782859)
    filas = [{"pid": 3, "exe": MOTOR_VIRTUAL, "cmd": '"claude.exe" --input-format stream-json', "parent": "claude.exe"}]
    monkeypatch.setattr(procs.subproc, "correr", lambda *a, **k: (0, json.dumps(filas), ""))
    (fila,) = procs.sweep()
    assert fila["external"]["via"] == "registro" and fila["external"]["canal"] == "Sesión de prueba"


def test_envio_a_desktop_nombra_el_canal(monkeypatch):
    s = sessions.new_session("ffff", "claude", "hook")
    s.update(
        pid=3568,
        no_console=True,
        external={"kind": "claude-desktop", "via": "registro", "desktop": True, "canal": "Sesión de prueba"},
    )
    monkeypatch.setattr(sessions.backend, "agent_alive", lambda d: True)
    code, body = sessions.send_blocked(s)
    assert code == 409 and "canal nativo" in body["error"] and "SendMessage a «Sesión de prueba»" in body["error"]
    s["external"].pop("canal")
    assert "su nombre en ListAgents" in sessions.send_blocked(s)[1]["error"]


# 6. la misma sesion vista o retomada en Desktop ------------------------------------------------


def test_desktop_no_le_quita_la_tarjeta_a_una_cli_viva(monkeypatch):
    desktop = {"kind": "claude-desktop", "via": "registro", "desktop": True, "canal": "x"}
    vivos = {100: True}
    monkeypatch.setattr(backend, "agent_alive", lambda d: vivos.get(d.get("pid"), False))
    monkeypatch.setattr(backend, "external_origin", lambda d: desktop if d.get("pid") == 200 else None)
    monkeypatch.setattr(backend, "is_tui", lambda d: d.get("pid") == 100)
    s = sessions.new_session("gggg", "claude", "hook")
    state.sessions["gggg"] = s
    hooks_eventos.claim_pid(s, {"pid": 100, "agent_exe": CLI_CLAUDE})
    hooks_eventos.claim_pid(s, {"pid": 200, "agent_exe": MOTOR_VIRTUAL})  # Desktop con la CLI viva
    assert s["pid"] == 100 and s["external"] is None and s["no_console"] is False
    assert list(state.sessions) == ["gggg"]  # sin duplicado
    vivos[100] = False  # `claude --desktop --resume`: la CLI se cierra y la retoma la app
    hooks_eventos.claim_pid(s, {"pid": 200, "agent_exe": MOTOR_VIRTUAL})
    assert s["pid"] == 200 and s["external"] == desktop and s["no_console"] is True
    vivos[300] = True  # y `claude --resume` en una terminal la vuelve personal
    hooks_eventos.claim_pid(s, {"pid": 300, "agent_exe": CLI_CLAUDE})
    assert s["pid"] == 300 and s["external"] is None


def test_barrido_reclasifica_una_tarjeta_vieja_de_desktop(monkeypatch):
    vieja = sessions.new_session("5d0f9e6b", "claude", "hook")
    vieja.update(pid=3568, external=None, no_console=False)  # como la tomaba el lienzo antes
    orq = sessions.new_session("orq1", "claude", "hook")
    orq.update(pid=3600, external={"kind": "orquestador", "via": "proceso"}, no_console=True)
    state.sessions.update({"5d0f9e6b": vieja, "orq1": orq})
    desktop = {"kind": "claude-desktop", "via": "registro", "desktop": True, "canal": "Sesión de prueba"}
    monkeypatch.setattr(
        sessions.backend,
        "sweep",
        lambda: [
            {"pid": 3568, "agent": "claude", "exe": MOTOR_VIRTUAL, "external": dict(desktop)},
            {"pid": 3600, "agent": "claude", "exe": MOTOR_VIRTUAL, "external": dict(desktop)},
        ],
    )
    monkeypatch.setattr(sessions, "codex_desktop_threads", lambda since: [])
    sessions.sweep_once()
    assert vieja["external"] == desktop and vieja["no_console"] is True
    assert orq["external"]["kind"] == "orquestador"  # la marca de un orquestador no se pisa
