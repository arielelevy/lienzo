"""Tests minimos de lienzo/transcripts.py contra datos reales de esta maquina."""

import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import transcripts as tr

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude", "projects", "D--Apps-lienzo")
CODEX_DIR = os.path.join(HOME, ".codex", "sessions", "2026", "09", "05")


def _newest(pattern):
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


@pytest.fixture(scope="module")
def claude_path():
    p = _newest(os.path.join(CLAUDE_DIR, "*.jsonl"))
    if not p:
        pytest.skip(f"sin transcripciones de Claude en {CLAUDE_DIR}")
    return p


@pytest.fixture(scope="module")
def codex_path():
    files = sorted(glob.glob(os.path.join(CODEX_DIR, "rollout-*.jsonl")), key=os.path.getmtime, reverse=True)
    if not files:
        pytest.skip(f"sin rollouts de Codex en {CODEX_DIR}")
    for p in files:
        if not tr.parse_codex(p)["meta"]["imported"]:
            return p
    pytest.skip("todos los rollouts de Codex del dia son importados")


# 1. parse_claude ---------------------------------------------------------------


def test_parse_claude_turnos_y_tools(claude_path):
    r = tr.parse_claude(claude_path)
    assert r["meta"]["agent"] == "claude"
    turns = r["turns"]
    assert turns, "no devolvio turnos"
    assert turns[-1]["prompt"].strip(), "el ultimo turno tiene prompt vacio"

    tools = [b for t in turns for b in t["blocks"] if b["kind"] == "tool"]
    assert tools, "la transcripcion no tiene tool_use"
    # cada tool_use conocido (name != '?') con resultado lo tiene enlazado por id
    with_result = [b for b in tools if b["name"] != "?" and b["result"] is not None]
    assert with_result, "ningun tool_use quedo enlazado a su tool_result"
    for b in with_result:
        assert b["id"], "bloque tool sin id"
        assert set(b["result"]) == {"text", "is_error"}
    # tool_result huerfanos (sin tool_use previo) solo pueden aparecer en el turno parcial del corte
    orphans = [(t["id"], b) for t in turns for b in t["blocks"] if b["kind"] == "tool" and b["name"] == "?"]
    assert all(tid == "parcial" for tid, _ in orphans), f"tool_result sin tool_use fuera del corte: {orphans[:3]}"


# 2. parse_codex ----------------------------------------------------------------


def test_parse_codex_turn_id_y_task_complete(codex_path):
    lines, _ = tr.tail_lines(codex_path)
    events = [d for d in tr.iter_json(lines) if d.get("type") == "event_msg"]
    turn_ids = {(d.get("payload") or {}).get("turn_id") for d in events} - {None}
    completed = {
        (d.get("payload") or {}).get("turn_id")
        for d in events
        if (d.get("payload") or {}).get("type") == "task_complete"
    } - {None}
    if not turn_ids:
        pytest.skip("el rollout no tiene event_msg con turn_id")

    r = tr.parse_codex(codex_path)
    assert r["meta"]["agent"] == "codex"
    assert r["meta"]["imported"] is False
    turns = r["turns"]
    assert turns, "no devolvio turnos"
    by_id = {t["id"] for t in turns}
    assert turn_ids <= by_id, f"turn_id sin turno: {turn_ids - by_id}"
    if not completed:
        pytest.skip("el rollout no tiene task_complete")
    for t in turns:
        if t["id"] in completed:
            assert t["ended"] is True, f"turno {t['id']} con task_complete no quedo ended"


# 3. digest --------------------------------------------------------------------


def test_digest_forma(claude_path):
    out = tr.digest("claude", claude_path, n=5)
    assert out["turns"]
    for t in out["turns"]:
        assert isinstance(t["files"], list)
        assert isinstance(t["commands"], list)
        assert isinstance(t["errors"], list)
        assert "peers" in t and isinstance(t["peers"], list)


def test_is_system_prompt():
    assert tr.is_system_prompt("<task-notification>x") is True
    assert tr.is_system_prompt("  <system-reminder>algo") is True
    assert tr.is_system_prompt("hola, arreglame el parser") is False


# 4. tail_lines ----------------------------------------------------------------


def test_tail_lines_truncado_descarta_parcial(tmp_path):
    p = tmp_path / "t.jsonl"
    rows = [f'{{"i": {i}, "pad": "{"x" * 50}"}}' for i in range(20)]
    p.write_bytes(("\n".join(rows) + "\n").encode("utf-8"))  # LF puro, como los .jsonl reales
    lines, truncated = tr.tail_lines(str(p), max_bytes=200)
    assert truncated is True
    assert lines, "cola vacia"
    assert all(l.startswith("{") and l.endswith("}") for l in lines), "quedo una linea parcial"
    assert lines[-1] == rows[-1]
    assert len(lines) < len(rows)

    lines_all, truncated_all = tr.tail_lines(str(p), max_bytes=10**6)
    assert truncated_all is False
    assert lines_all == rows


# 5. looks_like_error ------------------------------------------------------------


def test_looks_like_error():
    assert tr.looks_like_error("You've hit your session limit · resets 2:40pm") is True
    assert tr.looks_like_error("Listo, la tabla quedo actualizada con 611 filas.") is False
    assert tr.looks_like_error("") is False


# 6. limit_reset -----------------------------------------------------------------


def test_limit_reset():
    import datetime as dt

    ref = dt.datetime(2026, 9, 5, 15, 28, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
    at = tr.limit_reset(
        "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
        "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 7:57 PM.",
        ref,
    )
    assert at == ref.replace(hour=19, minute=57, second=0, microsecond=0)
    # la referencia (fin del turno) puede quedar unos minutos despues de la hora: sigue siendo hoy
    late = ref.replace(hour=20, minute=5)
    assert tr.limit_reset("try again at 7:57 PM.", late) == ref.replace(hour=19, minute=57, second=0, microsecond=0)
    # hora ya pasada respecto del aviso: es manana
    at = tr.limit_reset("try again at 2:36 PM.", ref)
    assert (at.day, at.hour, at.minute) == (6, 14, 36)
    at = tr.limit_reset("try again at Sep 5th, 2026 3:08 AM.", ref)
    assert (at.year, at.month, at.day, at.hour, at.minute) == (2026, 9, 5, 3, 8)
    assert tr.limit_reset("try again in 2 hours 15 minutes", ref) == ref + dt.timedelta(hours=2, minutes=15)
    assert tr.limit_reset("You've hit your session limit · resets 2:40pm", ref).hour == 14
    assert tr.limit_reset("try again in a moment. If it persists, check https://status.claude.com.", ref) is None
    assert tr.limit_reset("resets in `visualStyles` at level 2:", ref) is None
    assert tr.limit_reset("Listo, la tabla quedo actualizada.", ref) is None
    assert tr.limit_reset("", ref) is None


# Destacados: la pregunta con la que cierra un turno, sin repetir la respuesta (encargo Y3)


def _turno(final, blocks=None, **k):
    return {"id": "t", "blocks": blocks or [], "final": final, "ended": True, "prompt": "prueba", **k}


def _preguntas(final, blocks=None):
    return tr.digest_turn(_turno(final, blocks))["questions"]


def test_un_final_corto_que_es_la_pregunta_no_se_repite():
    """El caso medido: la tarjeta mostraba la misma frase como respuesta y como pregunta."""
    assert _preguntas("Hola, funciona todo bien. ¿Qué necesitás?") == []


def test_un_final_largo_deja_solo_la_ultima_oracion():
    final = (
        "Corregido y desplegado, con las capas donde corresponde. "
        + "Detalle del cambio. " * 12
        + "Con eso la matriz se abre por taxonomía. ¿Las relaciones las hacés vos o las creo yo?"
    )
    assert _preguntas(final) == ["¿Las relaciones las hacés vos o las creo yo?"]


def test_el_corte_es_por_oracion_y_no_por_el_signo_de_apertura():
    """El '¿' suele abrir despues del contexto que hace entendible la pregunta: cortar ahi lo pierde."""
    final = (
        "x" * 250 + "\nPor convención del repo las facts internas van ocultas — " "¿la oculto o la dejás a la vista?"
    )
    assert _preguntas(final) == [
        "Por convención del repo las facts internas van ocultas — ¿la oculto o la dejás a la vista?"
    ]


def test_un_final_largo_de_una_sola_oracion_tampoco_se_repite():
    final = "¿Querés que " + "siga con el backend o que arranque por el front, " * 6 + "o lo dejamos acá?"
    assert len(final) > tr.QUESTION_MAX
    assert _preguntas(final) == [], "si el final es una sola oracion, la seccion es el final otra vez"


def test_el_punto_pegado_a_un_cierre_tambien_corta():
    final = "x" * 250 + "\nLo dejé andando (ya probado). ¿Sigo con el resto?"
    assert _preguntas(final) == ["¿Sigo con el resto?"]
    final = "x" * 250 + '\nMe dijo "listo." ¿Le creo?'
    assert _preguntas(final) == ["¿Le creo?"]


def test_askuserquestion_manda_y_no_se_toca():
    """Las preguntas explicitas de la herramienta se quedan como estan, aunque el final pregunte."""
    ask = {
        "kind": "tool",
        "name": "AskUserQuestion",
        "input": {"questions": [{"question": "¿Opción A o B?"}]},
        "result": None,
    }
    assert _preguntas("x" * 300 + " ¿Y esto otro?", [ask]) == ["¿Opción A o B?"]


def test_un_final_que_no_pregunta_no_agrega_nada():
    assert _preguntas("x" * 300 + " Listo, quedó todo en disco.") == []


def test_la_pregunta_se_recorta_a_QUESTION_MAX():
    final = "x" * 300 + "\n¿" + "y" * 400 + "?"
    q = _preguntas(final)
    assert len(q) == 1 and len(q[0]) == tr.QUESTION_MAX
