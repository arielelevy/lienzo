"""Encargo O (2026-10-22): Kiro sin tarjeta fantasma, con el auto-aprobar visible en la tarjeta y con
«te necesita» cuando termina el turno con una pregunta (no tiene el hook idle_prompt de Claude)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import autoaprobar as au
import procinfo
import sessions as ses
import state as st

KIRO = r"C:\Users\x\AppData\Local\Kiro-Cli\kiro-cli.exe"
# medido el 2026-10-22 en D:\Globant\source: la TUI (pid 16132) y su ayudante (pid 10960, hijo de bun)
TUI = f'"{KIRO}" --v3'
AYUDANTE = (
    f"{KIRO} chat _ windows-kas-process -- C:\\Users\\x\\AppData\\Local\\Kiro-Cli\\node.exe "
    "--experimental-wasm-modules C:\\Users\\x\\AppData\\Local\\Kiro-Cli\\kas\\2.33.1\\node_modules\\@kiro\\agent"
    "\\dist\\server\\acp-server.js --transport=stdio --auth=acp-callback"
)


def test_el_ayudante_del_motor_no_es_una_sesion_y_la_tui_si():
    assert procinfo.agent_of(KIRO, TUI) == "kiro"
    assert procinfo.agent_of(KIRO, AYUDANTE) is None
    assert procinfo.agent_of(KIRO, f'"{KIRO}" --v3 --resume-id sess_1') == "kiro"
    assert procinfo.agent_of(KIRO, f'"{KIRO}" chat') == "kiro"
    for sub in ("login", "whoami", "update", "serve", "mcp"):
        assert procinfo.agent_of(KIRO, f'"{KIRO}" {sub}') is None, sub


def test_process_agent_lee_el_comando_de_kiro(monkeypatch):
    """agent_alive y is_tui van por process_agent: el ayudante no puede contar como la sesion viva."""
    monkeypatch.setattr(procinfo, "image_path", lambda pid: KIRO)
    monkeypatch.setattr(procinfo, "command_line", lambda pid: {1: TUI, 2: AYUDANTE}.get(pid))
    assert procinfo.process_agent(1) == "kiro"
    assert procinfo.process_agent(2) is None
    # sin comando legible sigue contando: marcar muerta la TUI viva es peor que dejar pasar al ayudante
    assert procinfo.process_agent(3) == "kiro"
    # binario renombrado por el auto-update: tambien se lee el comando
    monkeypatch.setattr(procinfo, "image_path", lambda pid: KIRO + ".old.123")
    assert procinfo.process_agent(2) is None


def test_el_valor_de_una_opcion_no_se_lee_como_subcomando():
    assert procinfo.agent_of(KIRO, f'"{KIRO}" --agent mcp') == "kiro"
    assert procinfo.agent_of(KIRO, f'"{KIRO}" --model x login') is None
    assert procinfo.agent_of(KIRO, f'"{KIRO}" acp') is None


DIALOGO_KIRO = {
    "question": "Build core.api solution requires approval",
    "detail": "shell → dotnet build",
    "options": [
        {"n": 1, "text": "Allow"},
        {"n": 2, "text": "Always allow"},
        {"n": 3, "text": "Deny"},
        {"n": 4, "text": "Always deny"},
    ],
    "selected": 1,
    "teclas": "flechas",
}


def _armar_kiro(monkeypatch, code):
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": True})
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(st, "pending", {})
    monkeypatch.setattr(au, "_intentados", {})
    monkeypatch.setattr(ses, "touch", lambda s: True)
    s = {
        "session_id": "sess_k",
        "agent": "kiro",
        "state": "corriendo",
        "needs": None,
        "dialog": DIALOGO_KIRO,
        "dialog_at": "t1",
    }
    monkeypatch.setattr(st, "sessions", {"sess_k": s})
    monkeypatch.setattr(ses, "answer_dialog", lambda s, n: (code, {"ok": code == 200}))
    return s


def test_el_permiso_que_contesta_el_auto_aprobar_queda_en_la_tarjeta(monkeypatch):
    s = _armar_kiro(monkeypatch, 200)
    au.ronda(ahora=100)
    hecho = s.get("auto_aprobado")
    assert hecho and hecho["via"] == "dialogo" and hecho["at"]
    assert hecho["que"].startswith("Build core.api solution requires approval")


def test_un_intento_que_no_entro_no_se_anota_como_aprobado(monkeypatch):
    s = _armar_kiro(monkeypatch, 409)
    au.ronda(ahora=100)
    assert not s.get("auto_aprobado")


def test_apagar_el_auto_aprobar_borra_lo_anotado(monkeypatch):
    s = _armar_kiro(monkeypatch, 200)
    au.ronda(ahora=100)
    assert s.get("auto_aprobado")
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": False})
    au.ronda(ahora=200)
    assert not s.get("auto_aprobado")


def _tarjeta(agent="kiro", **extra):
    return {
        "session_id": "sess_k",
        "agent": agent,
        "state": "corriendo",
        "needs": None,
        "hooked": False,
        "last_reply": None,
        "last_prompt": None,
        **extra,
    }


def _turno(final, ended=True, tid="e1"):
    return {"id": tid, "prompt": "hacé algo", "final": final, "ended": ended, "blocks": []}


def _sin_efectos(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "en_hilo", lambda *a, **k: None)
    monkeypatch.setattr(ses.captura, "pedido", lambda *a, **k: None)


def test_kiro_que_termina_preguntando_pasa_a_te_necesita_una_vez(monkeypatch):
    _sin_efectos(monkeypatch)
    s = _tarjeta()
    ses.apply_turn_unhooked(s, _turno("¿Sigo con el otro proyecto?"))
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "idle"
    assert s["needs"]["detail"] == "¿Sigo con el otro proyecto?"
    # se lo saca (le escriben desde el lienzo) y se relee el mismo turno: no vuelve a pedir
    ses.set_state(s, "termino")
    ses.apply_turn_unhooked(s, _turno("¿Sigo con el otro proyecto?"))
    assert s["state"] == "termino" and not s.get("needs")


def test_kiro_contestado_en_la_terminal_vuelve_a_corriendo(monkeypatch):
    _sin_efectos(monkeypatch)
    s = _tarjeta()
    ses.apply_turn_unhooked(s, _turno("¿Sigo?"))
    assert s["state"] == "te_necesita"
    ses.apply_turn_unhooked(s, _turno("", ended=False, tid="e2"))
    assert s["state"] == "corriendo" and not s.get("needs")


def test_kiro_que_termina_sin_pregunta_y_otros_agentes_quedan_en_termino(monkeypatch):
    _sin_efectos(monkeypatch)
    s = _tarjeta()
    ses.apply_turn_unhooked(s, _turno("Listo, compila."))
    assert s["state"] == "termino" and not s.get("needs")
    s = _tarjeta(agent="codex")
    ses.apply_turn_unhooked(s, _turno("¿Sigo?"))
    assert s["state"] == "termino" and not s.get("needs")


def test_kiro_no_pisa_un_dialogo_de_pantalla(monkeypatch):
    _sin_efectos(monkeypatch)
    s = _tarjeta(state="te_necesita", needs={"kind": "dialog", "where": "terminal"})
    ses.apply_turn_unhooked(s, _turno("", ended=False))
    assert s["needs"]["kind"] == "dialog"


def test_kiro_con_otro_turno_ya_cerrado_entre_dos_lecturas_no_queda_en_la_pregunta_vieja(monkeypatch):
    """Code review 2026-10-22: si el turno siguiente arranca y termina entre dos lecturas, no se ve
    ningun turno abierto; la tarjeta quedaba para siempre en la pregunta anterior."""
    _sin_efectos(monkeypatch)
    s = _tarjeta()
    ses.apply_turn_unhooked(s, _turno("¿Sigo?"))
    ses.apply_turn_unhooked(s, _turno("Listo.", tid="e2"))
    assert s["state"] == "termino" and not s.get("needs")
    ses.apply_turn_unhooked(s, _turno("¿Y ahora el otro?", tid="e3"))
    assert s["state"] == "te_necesita" and s["needs"]["detail"] == "¿Y ahora el otro?"


def test_kiro_pregunta_con_negrita_y_turno_sin_id(monkeypatch):
    _sin_efectos(monkeypatch)
    s = _tarjeta()
    ses.apply_turn_unhooked(s, {"prompt": "x", "final": "**¿Sigo?**", "ended": True, "blocks": []})
    assert s["state"] == "te_necesita"


def test_un_dialogo_en_pantalla_reemplaza_la_pregunta_vieja_de_kiro(monkeypatch):
    """Code review 2026-10-22: con la pregunta del fin de turno puesta, el barrido no tomaba un
    permiso nuevo (pedia `needs` vacio) y Kiro esperaba sin que nadie lo viera."""
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": False})
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    monkeypatch.setattr(ses, "en_hilo", lambda *a, **k: None)
    monkeypatch.setattr(ses, "read_transcript", lambda s: {})
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "area": None, "dialog": DIALOGO_KIRO})
    s = _tarjeta(pid=1, alive=True, state="te_necesita", needs={"kind": "idle", "where": "terminal"}, dialog=None)
    monkeypatch.setattr(st, "sessions", {"sess_k": s})
    monkeypatch.setattr(ses, "sessions", st.sessions)
    ses.screen_once()
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "dialog"


# medido por Ariel el 2026-10-22: un subagente de Kiro pide permiso y la TUI lo junta en este cartel,
# con opciones por letra y sin numero
PENDIENTES = [
    "  • Orchestrating (1 agent)",
    "    esc to cancel",
    "    ctrl+g open agent monitor",
    "    • Enumerate every HL general-task-execution Read ⚠ tool approval needed",
    "  ─────────────────────────────────────────",
    "   ⚠ 1 tool approval pending",
    "   ❯ (a) Approve all pending",
    "     (f) Approve all pending and auto-approve future subagent requests",
    "     (c) Configure individually (agent monitor)",
    "     (x) Exit (cancel subagents)",
]


def test_el_cartel_de_aprobaciones_pendientes_de_subagentes_es_un_dialogo():
    import screen

    d = screen.dialog(PENDIENTES)
    assert d and d["question"] == "1 tool approval pending"
    assert [o["text"] for o in d["options"]][:2] == [
        "(a) Approve all pending",
        "(f) Approve all pending and auto-approve future subagent requests",
    ]
    assert d["selected"] == 1 and len(d["options"]) == 4


def test_el_auto_aprobar_elige_aprobar_y_auto_aprobar_lo_futuro():
    """Ariel, 2026-10-22: con «(f)» Kiro deja de preguntar por los subagentes; si no está, «(a)»."""
    import screen

    d = screen.dialog(PENDIENTES)
    assert au.opcion_de_permiso(d, "kiro") == 2
    # con el cursor en otra opcion elige igual (f)
    otra = [l.replace("❯", " ") for l in PENDIENTES]
    otra[7] = "   ❯ (f) Approve all pending and auto-approve future subagent requests"
    d = screen.dialog(otra)
    assert d and d["selected"] == 2 and au.opcion_de_permiso(d, "kiro") == 2
    # sin (f), (a)
    sin_f = [l for l in PENDIENTES if "(f)" not in l]
    assert au.opcion_de_permiso(screen.dialog(sin_f), "kiro") == 1
    assert au.opcion_de_permiso(screen.dialog(PENDIENTES), "claude") is None
