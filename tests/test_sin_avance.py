"""Una coda esperó casi 3 horas en un diálogo de su terminal con la tarjeta en «corriendo» (ar-it33940,
2026-10-23) y nadie se enteró. Dos arreglos: el barrido de coda reconoce sus preguntas que no son permisos,
y toda tarjeta «corriendo» sin ningún avance en SIN_AVANCE_S le avisa a quien la tiene cableada."""

import datetime as dt

import pantalla_coda
import pytest
import rules as rl
import sessions as ses
import state as st

from lienzo import server  # noqa: F401

# la pantalla de la coda D, tal como se leyó (la columna derecha es el panel lateral de coda)
PANTALLA_D = [
    "  [unknown] Invalid arguments for tool 'grep': missing required 'pattern' (expected string) │ Window         34.4k/200k",
    "                                                                                            │",
    "┃ Set up permission rules?                                                                  │",
    "                                                                                            │ ───────────────────────",
    "  I noticed you don't have any allow rules configured. Do you want me to help you configure │ Waiting for approval…",
    "  them? You can also do it later with the /init-rules skill.                                │ mainzo",
    "                                                                                            │ ───────────────────────",
    "  > Yes                                                                                     │ D:/apps/lienzo",
    "    No                                                                                      │ · CODA 1.5.0",
    "                                                                                            │ · clients",
    "  ↑↓ move · Enter confirm · y/n · Esc to dismiss                                           █│ · Logged In: API Key",
]
PROMPT = [
    "┃ Ask anything... (/ commands · ? shortcuts · Alt+V image)                                  │",
    "┃ GLM-5.3-Flash  via Globant DGX                                                            │",
]
SID = "32a4579c-223f-4142-91d3-10e2ecb41b84"


def test_la_pregunta_de_coda_se_reconoce_y_un_permiso_o_el_prompt_no():
    assert pantalla_coda.pregunta_visible(PANTALLA_D) == "Set up permission rules?"
    assert pantalla_coda.pregunta_visible(PROMPT) is None
    # el cartel de permiso tiene otro pie («Esc deny»): lo sigue tomando coda_ask_open, no esta
    assert pantalla_coda.pregunta_visible(["Approval Required", "  Enter confirm · Esc deny"]) is None


@pytest.fixture
def coda(monkeypatch):
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(ses, "touch", lambda s: True)
    s = ses.new_session(SID, "coda", "hook")
    s.update(pid=57308, state="corriendo", alive=True)
    monkeypatch.setattr(st, "sessions", {SID: s})
    monkeypatch.setattr(ses, "sessions", st.sessions)
    return s


def test_la_tarjeta_pasa_a_te_necesita_con_la_pregunta_y_vuelve_al_cerrarse(coda, monkeypatch):
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PANTALLA_D})
    assert ses.coda_dialogo_en_pantalla(coda)
    assert coda["state"] == "te_necesita"
    assert coda["needs"]["kind"] == "question" and coda["needs"]["detail"] == "Set up permission rules?"
    # con la pregunta abierta se la sigue mirando, aunque haya `needs`
    monkeypatch.setattr(ses, "_pantalla_mirada", {})
    coda["state_since"] = "2026-01-01T00:00:00.000-03:00"
    assert ses.coda_mirar_pantalla(coda)
    # se contestó en la terminal: la tarjeta vuelve a «corriendo»
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PROMPT})
    assert not ses.coda_dialogo_en_pantalla(coda)
    assert coda["state"] == "corriendo" and not coda["needs"]
    # una lectura fallida no la da por contestada
    coda.update(state="corriendo", needs=None)
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": PANTALLA_D})
    ses.coda_dialogo_en_pantalla(coda)
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": False, "error": "sin consola"})
    ses.coda_dialogo_en_pantalla(coda)
    assert coda["needs"]["kind"] == "question"


def _hace(minutos):
    return (dt.datetime.now().astimezone() - dt.timedelta(minutes=minutos)).isoformat(timespec="milliseconds")


def test_sin_avance_avisa_una_vez_por_racha(coda, monkeypatch):
    avisos = []
    monkeypatch.setattr(ses, "en_hilo", lambda f, *a: avisos.append(a) if f is ses.on_sin_avance else None)
    coda.update(state_since=_hace(170), last_event_ts=_hace(165), avance_at=None)
    ses.sin_avance(coda)
    ses.sin_avance(coda)  # la misma racha no vuelve a avisar
    assert len(avisos) == 1 and avisos[0][0] == SID
    coda["avance_at"] = _hace(5)  # avanzó: todavía no
    ses.sin_avance(coda)
    assert len(avisos) == 1
    coda["avance_at"] = _hace(st.SIN_AVANCE_S // 60 + 1)  # otra racha larga: vuelve a avisar
    ses.sin_avance(coda)
    assert len(avisos) == 2
    # una tarjeta que espera algo ya está en «te necesita»: no hace falta este aviso
    coda.update(state="te_necesita", avance_at=_hace(500))
    ses.sin_avance(coda)
    assert len(avisos) == 2


def test_el_aviso_va_a_quien_la_tiene_cableada(coda, monkeypatch):
    coord = ses.new_session("cccccccc-0000-4000-8000-0000000000c1", "claude", "hook")
    st.sessions[coord["session_id"]] = coord
    monkeypatch.setattr(
        rl.rules,
        "items",
        [
            {
                "id": "r",
                "kind": "on_stop",
                "from": SID,
                "to": coord["session_id"],
                "text": "{respuesta}",
                "enabled": True,
            },
        ],
    )
    monkeypatch.setattr(rl, "sessions", st.sessions)
    enviados = []
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    monkeypatch.setattr(
        rl, "send_to_session", lambda dst, texto, adj: (enviados.append((dst["session_id"], texto)), (200, {}))[1]
    )
    rl.aviso_sin_avance(SID, _hace(40))
    assert [d for d, _ in enviados] == [coord["session_id"]]
    assert "sin ningún avance" in enviados[0][1] and f"/sessions/{SID}/screen" in enviados[0][1]
