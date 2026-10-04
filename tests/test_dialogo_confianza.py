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
