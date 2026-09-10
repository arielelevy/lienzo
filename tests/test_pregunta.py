"""Pregunta con opciones (AskUserQuestion) contestada desde el lienzo.

AskUserQuestion viaja por el hook de permisos igual que cualquier herramienta -- medido el
2026-09-08 sobre una sesion real: llega con tool_name AskUserQuestion, el tool_input con las
preguntas y sus opciones, y tool_use_id en null -- pero no es un permiso. Permitir devolvia la
pregunta al selector de la terminal y a los 60 s el pedido vencia (PermissionTimeout), asi que
desde el tablero no habia forma de contestarla. La respuesta elegida viaja en `answers` del propio
tool_input, que es donde la deja el selector de la consola.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401  (agrega lienzo/ al sys.path y engancha los modulos)
import hook
import sessions as ses
import state as st

SID = "3f2b7c10-0000-4000-8000-000000000000"
PREGUNTA = '¿Qué querés decir con "en análisis"?'
OTRA = "¿Qué escribo en Planner?"

PEDIDO = {
    "hook_event_name": "PermissionRequest",
    "session_id": SID,
    "agent": "claude",
    "tool_name": "AskUserQuestion",
    "tool_use_id": None,
    "tool_input": {
        "questions": [
            {
                "question": PREGUNTA,
                "header": "En análisis",
                "multiSelect": False,
                "options": [
                    {"label": 'Crear bucket "En análisis"', "description": "Agregar un bucket nuevo al plan."},
                    {"label": "Marcar estado, sin bucket nuevo", "description": "Dejar los buckets como están."},
                ],
            },
            {
                "question": OTRA,
                "header": "Alcance",
                "multiSelect": True,
                "options": [{"label": "Crear las 3 tareas nuevas"}, {"label": "Actualizar descripciones"}],
            },
        ]
    },
}


@pytest.fixture
def pendiente(tmp_path, monkeypatch):
    """Un pedido esperando respuesta, con el buzon de respuestas en tmp."""
    monkeypatch.setattr(ses, "ANSWERS", str(tmp_path))
    monkeypatch.setattr(st, "log", lambda msg: None)
    d = {"request_id": "req-1", "nonce": "n" * 8, **PEDIDO}
    st.pending.clear()
    st.pending["req-1"] = d
    yield tmp_path
    st.pending.clear()


def respuesta(tmp_path) -> dict:
    with open(os.path.join(tmp_path, "req-1.json"), encoding="utf-8") as f:
        return json.load(f)


# 1. que se puede contestar ------------------------------------------------------


def test_solo_las_preguntas_del_pedido_y_solo_texto():
    d = {"request_id": "req-1", **PEDIDO}
    elegido = ses.question_answers(
        d,
        {
            PREGUNTA: "Marcar estado, sin bucket nuevo",
            "otra pregunta que nadie hizo": "algo",
            OTRA: 7,  # no es texto
        },
    )
    assert elegido == {PREGUNTA: "Marcar estado, sin bucket nuevo"}


def test_un_permiso_comun_no_lleva_respuestas():
    d = {"request_id": "req-1", "tool_name": "Bash", "tool_input": {"command": "git push"}}
    assert ses.question_answers(d, {"lo que sea": "si"}) == {}


def test_la_respuesta_sale_sin_caracteres_de_control():
    """Igual que todo lo que el lienzo le manda a una sesion: sin ESC, Tab ni saltos de linea."""
    elegido = ses.question_answers({"request_id": "x", **PEDIDO}, {PREGUNTA: "dale\x1b\tya"})
    assert elegido == {PREGUNTA: "daleya"}


# 2. lo que queda en el buzon ----------------------------------------------------


def test_contestar_deja_la_opcion_elegida_en_el_buzon(pendiente):
    code, res = ses.answer_pending("req-1", "allow", "", {PREGUNTA: 'Crear bucket "En análisis"'})
    assert (code, res) == (200, {"ok": True})
    r = respuesta(pendiente)
    assert r["decision"] == "allow"
    assert r["answers"] == {PREGUNTA: 'Crear bucket "En análisis"'}


def test_permitir_sin_elegir_nada_es_el_permiso_de_siempre(pendiente):
    """Es la escapatoria "contestar en la terminal": libera al agente y decide la consola."""
    ses.answer_pending("req-1", "allow")
    assert "answers" not in respuesta(pendiente)


def test_denegar_no_arrastra_respuestas(pendiente):
    ses.answer_pending("req-1", "deny", "", {PREGUNTA: 'Crear bucket "En análisis"'})
    r = respuesta(pendiente)
    assert r["decision"] == "deny" and "answers" not in r


def test_varias_opciones_en_una_multiSelect(pendiente):
    ses.answer_pending("req-1", "allow", "", {OTRA: "Crear las 3 tareas nuevas, Actualizar descripciones"})
    assert respuesta(pendiente)["answers"] == {OTRA: "Crear las 3 tareas nuevas, Actualizar descripciones"}


# 3. lo que el hook le devuelve al agente ----------------------------------------


def test_el_hook_mete_la_respuesta_en_el_input_de_la_herramienta():
    upd = hook.answered_input(PEDIDO, {"decision": "allow", "answers": {PREGUNTA: "Marcar estado, sin bucket nuevo"}})
    assert upd["answers"] == {PREGUNTA: "Marcar estado, sin bucket nuevo"}
    assert upd["questions"] == PEDIDO["tool_input"]["questions"]  # el resto del input va igual
    salida = hook.decision_json("allow", "", upd)
    assert salida["hookSpecificOutput"]["decision"]["updatedInput"] is upd
    assert salida["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_sin_respuestas_el_allow_sale_pelado_como_antes():
    assert hook.answered_input(PEDIDO, {"decision": "allow"}) is None
    body = hook.decision_json("allow")["hookSpecificOutput"]["decision"]
    assert body == {"behavior": "allow"}


def test_un_permiso_comun_nunca_lleva_updatedInput():
    pedido = {"tool_name": "Bash", "tool_input": {"command": "git push"}}
    assert hook.answered_input(pedido, {"decision": "allow", "answers": {"x": "y"}}) is None


# 4. la tarjeta --------------------------------------------------------------------


def test_la_tarjeta_dice_pregunta_y_no_permiso(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    st.sessions.clear()
    ses.apply_event(dict(PEDIDO))
    needs = st.sessions[SID]["needs"]
    assert st.sessions[SID]["state"] == "te_necesita"
    assert needs["kind"] == "question"
    assert needs["detail"].startswith("¿Qué querés decir") and needs["detail"].endswith("(+1)")
    st.sessions.clear()


def test_un_posttooluse_sin_id_no_borra_la_pregunta(tmp_path, monkeypatch):
    """AskUserQuestion pide permiso con tool_use_id null: sin ese resguardo, el PostToolUse de
    cualquier otra herramienta que tampoco lo traiga daba el aviso por atendido."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    st.sessions.clear()
    ses.apply_event(dict(PEDIDO))
    ses.apply_event({"hook_event_name": "PostToolUse", "session_id": SID, "agent": "claude", "tool_use_id": None})
    assert st.sessions[SID]["state"] == "te_necesita"
    st.sessions.clear()
