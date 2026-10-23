"""Regresiones del encargo B, 2026-10-23. Sin teclas en sesiones reales."""

import pytest
import sessions as ses


@pytest.mark.parametrize("lectura", [{"ok": True, "lines": []}, {"ok": False, "error": "sin consola"}])
def test_dialogo_numerico_cerrado_no_teclea(monkeypatch, lectura):
    tarjeta = {
        "session_id": "b-dialog",
        "agent": "claude",
        "dialog": {"question": "Do you want to proceed?", "options": [{"n": 1, "text": "Yes"}]},
    }
    enviados = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "read_screen", lambda s: lectura)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses.state, "log", lambda m: None)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: (enviados.append((a, k)), (200, {}))[1])
    assert ses.answer_dialog(tarjeta, 1)[0] == 409
    assert enviados == []


@pytest.mark.parametrize(
    "lectura",
    [
        {"ok": True, "lines": ["──────────", "❯ 11", "──────────"]},
        {"ok": False, "error": "sin consola"},
        {"ok": True, "lines": []},
    ],
)
def test_nombre_nativo_relee_caja_aunque_typing_este_viejo(monkeypatch, lectura):
    tarjeta = {"session_id": "b-native", "agent": "claude", "state": "termino", "typing": False}
    enviados = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "dialogo_abierto", lambda s: None)
    monkeypatch.setattr(ses, "_menu_remote_control_abierto", lambda s: False)
    monkeypatch.setattr(ses, "read_screen", lambda s: lectura)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses.state, "log", lambda m: None)
    monkeypatch.setattr(ses.time, "sleep", lambda n: None)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: (enviados.append((a, k)), (200, {}))[1])
    code, out = ses._nombrar_nativo(tarjeta, "lienzo-B", 0)
    assert code == 409 and out["code"] == "native_deferred"
    assert enviados == []


def test_nombre_nativo_caja_vacia_si_envia(monkeypatch):
    tarjeta = {"session_id": "b-native", "agent": "claude", "state": "termino", "typing": False}
    enviados = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "dialogo_abierto", lambda s: None)
    monkeypatch.setattr(ses, "_menu_remote_control_abierto", lambda s: False)
    monkeypatch.setattr(
        ses,
        "read_screen",
        lambda s: {
            "ok": True,
            "lines": ["──────────", "❯ ", "──────────"],
        },
    )
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses.state, "log", lambda m: None)
    monkeypatch.setattr(ses.time, "sleep", lambda n: None)
    monkeypatch.setattr(ses, "run_send", lambda s, text, **k: (enviados.append(text), (200, {}))[1])
    assert ses._nombrar_nativo(tarjeta, "lienzo-B", 0)[0] == 200
    assert enviados == ["/rename lienzo-B", "/remote-control"]


RENOMBRADA = [
    " ▐▛███▛█   Claude Code v2.1.309",
    "> /rename lienzo",
    "  ⎿  Session renamed to: lienzo",
    "─" * 111 + " lienzo ─",
    "> {caja}",
    "─" * 120,
    "  ⏵⏵ auto mode on (shift+tab to cycle)",
]


@pytest.mark.parametrize("caja,nombra", [("", True), ("11", False)])
def test_nombre_nativo_en_una_sesion_ya_renombrada(monkeypatch, caja, nombra):
    """Pantalla de ar-it33940 (2026-10-23): la raya de arriba lleva el nombre adentro. Sin reconocerla, la
    caja no se encontraba: con «11» adentro se la daba por vacia, y vacia el nombre se diferia para siempre."""
    tarjeta = {"session_id": "b-native", "agent": "claude", "state": "termino", "typing": False}
    enviados = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "dialogo_abierto", lambda s: None)
    monkeypatch.setattr(ses, "_menu_remote_control_abierto", lambda s: False)
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": [l.format(caja=caja) for l in RENOMBRADA]})
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses.state, "log", lambda m: None)
    monkeypatch.setattr(ses.time, "sleep", lambda n: None)
    monkeypatch.setattr(ses, "run_send", lambda s, text, **k: (enviados.append(text), (200, {}))[1])
    code, _ = ses._nombrar_nativo(tarjeta, "lienzo-A", 0)
    assert (code == 200) is nombra
    assert enviados == (["/rename lienzo-A", "/remote-control"] if nombra else [])


def test_input_area_lee_la_caja_de_una_sesion_renombrada():
    import screen

    area = screen.input_area([l.format(caja="11") for l in RENOMBRADA])
    assert area["input"] == "11" and not area["placeholder"]
    assert not screen.es_regla("── texto suelto que no es raya")
