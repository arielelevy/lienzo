"""El dialogo de confianza de Claude («Do you trust the files in this folder?») se dibuja en un
recuadro: no se reconocia, el encargo + Enter elegia «No, exit» y la sesion moria (medido el
2026-10-04: los encargos G, H e I de la otra PC)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path
from lienzo import server  # noqa: F401
import screen
import sessions as ses
import state as st

PANTALLA = [
    "╭──────────────────────────────────────────────────────────╮",
    "│ Do you trust the files in this folder?                   │",
    "│                                                          │",
    "│ D:\apps\ai-development-students                          │",
    "│                                                          │",
    "│ ❯ 1. No, exit                                            │",
    "│   2. Yes, proceed                                        │",
    "╰──────────────────────────────────────────────────────────╯",
]


def test_el_dialogo_en_un_recuadro_se_reconoce():
    d = screen.dialog(PANTALLA)
    assert d is not None
    assert d["question"] == "Do you trust the files in this folder?"
    assert [o["text"] for o in d["options"]] == ["No, exit", "Yes, proceed"] and d["selected"] == 1


def test_send_no_teclea_con_el_dialogo_abierto(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    tecleado = []
    monkeypatch.setattr(ses, "run_send", lambda s, txt, **k: (tecleado.append(txt), (200, {}))[1])
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PANTALLA})
    s = {"session_id": "pid-51624", "agent": "claude", "pid": 51624, "hooked": False, "dialog": None}
    monkeypatch.setitem(st.sessions, s["session_id"], s)
    code, res = ses.send_to_session(s, "hacé el encargo G", [])
    assert code == 409 and res["code"] == "dialog_open" and "confianza" in res["error"]
    assert tecleado == [] and s["dialog"]["options"][1]["text"] == "Yes, proceed"


# la variante sin recuadro y sin numeros (medido el 2026-10-04 en ar-it33940): `dialog` daba None,
# `enviar_seguro` mando el encargo, el Enter eligio «No, exit» y la sesion murio como pid-6844
PANTALLA_FLECHAS = [
    "────────────────────────────────────────────────────────────────────────",
    " Accessing workspace:",
    "",
    r" D:\apps\chess",
    "",
    " Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source",
    " project, or work from your team). If not, take a moment to review what's in this folder first.",
    "",
    " Claude Code'll be able to read, edit, and execute files here.",
    "",
    " Security guide",
    "",
    " > No, exit",
    "   Yes, I trust this folder",
    "",
    " Enter to confirm · Esc to cancel",
]


def _con_cursor_en(n: int) -> list[str]:
    opciones = ["No, exit", "Yes, I trust this folder"]
    return (
        PANTALLA_FLECHAS[:12]
        + [(" > " if i == n else "   ") + t for i, t in enumerate(opciones, 1)]
        + PANTALLA_FLECHAS[14:]
    )


def test_el_dialogo_sin_numeros_se_reconoce_y_va_con_flechas():
    d = screen.dialog(PANTALLA_FLECHAS)
    assert d is not None and d["teclas"] == "flechas"
    assert d["question"] == "Accessing workspace:"
    assert d["options"] == [{"n": 1, "text": "No, exit"}, {"n": 2, "text": "Yes, I trust this folder"}]
    assert d["selected"] == 1


def test_una_lista_cualquiera_sin_el_pie_no_es_dialogo():
    assert screen.dialog(PANTALLA_FLECHAS[:-1]) is None
    sin_cursor = [l.replace(" > ", "   ") for l in PANTALLA_FLECHAS]
    assert screen.dialog(sin_cursor) is None


def test_send_no_teclea_con_el_dialogo_sin_numeros(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    tecleado = []
    monkeypatch.setattr(ses, "run_send", lambda s, txt, **k: (tecleado.append(txt), (200, {}))[1])
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PANTALLA_FLECHAS})
    s = {"session_id": "pid-42072", "agent": "claude", "pid": 42072, "hooked": False, "dialog": None}
    monkeypatch.setitem(st.sessions, s["session_id"], s)
    code, res = ses.send_to_session(s, "hacé el frente 1", [])
    assert code == 409 and res["code"] == "dialog_open" and "confianza" in res["error"]
    assert tecleado == []


def test_contestar_el_dialogo_sin_numeros_baja_relee_y_confirma(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    monkeypatch.setattr(ses.time, "sleep", lambda x: None)
    cursor = [1]
    teclas = []

    def run_send(s, txt, enter=True, key=None):
        teclas.append(key or txt)
        if key == "down":
            cursor[0] += 1
        return 200, {"ok": True}

    monkeypatch.setattr(ses, "run_send", run_send)
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": _con_cursor_en(cursor[0])})
    s = {"session_id": "pid-42072", "agent": "claude", "pid": 42072, "dialog": screen.dialog(PANTALLA_FLECHAS)}
    code, res = ses.answer_dialog(s, 2)
    assert code == 200 and res["text"] == "Yes, I trust this folder"
    assert teclas == ["down", "enter"]  # nunca el «2»: en este dialogo el numero no elige


def test_sin_el_cursor_en_la_elegida_no_confirma(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses.time, "sleep", lambda x: None)
    teclas = []
    monkeypatch.setattr(ses, "run_send", lambda s, txt, enter=True, key=None: (teclas.append(key), (200, {}))[1])
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PANTALLA_FLECHAS})  # la flecha no llego
    s = {"session_id": "pid-42072", "agent": "claude", "pid": 42072, "dialog": screen.dialog(PANTALLA_FLECHAS)}
    code, res = ses.answer_dialog(s, 2)
    assert code == 409 and "enter" not in teclas
