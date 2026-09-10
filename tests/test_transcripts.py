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


def test_retryable_error():
    """El turno que se corto solo se reintenta; el que espera cupo o credito, no."""
    assert tr.retryable_error("API Error: The response stopped arriving. The response above may be incomplete.") is True
    assert tr.retryable_error('API Error: 500 {"type":"overloaded_error"}') is True
    assert tr.retryable_error("Request timed out.") is True
    assert tr.retryable_error("You've hit your session limit · resets 2:40pm") is False
    assert tr.retryable_error("API Error: 429 rate limit exceeded") is False
    assert tr.retryable_error("Credit balance is too low") is False
    assert tr.retryable_error("") is False


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
    final = "x" * 250 + "\nPor convención del repo las facts internas van ocultas — ¿la oculto o la dejás a la vista?"
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


# Destacados: lo que el agente fue diciendo en el turno, no solo la ultima frase


def _texto(t):
    return {"kind": "text", "text": t, "phase": None}


def _dice(textos, final=None, **k):
    """Un turno donde el agente dijo `textos` en orden; el final es el ultimo, como lo deja
    `add_text`, salvo que se pida otro."""
    blocks = [_texto(t) for t in textos]
    return tr.digest_turn(_turno(final if final is not None else (textos[-1] if textos else ""), blocks, **k))


def test_los_mensajes_previos_del_agente_llegan_en_orden_y_sin_repetir_el_final():
    d = _dice(["Miro los correos.", "Ahí está: el filtro no es sobre Dim.Marca.", "Verifico los 5 SKU."])
    assert d["says"] == ["Miro los correos.", "Ahí está: el filtro no es sobre Dim.Marca."]
    assert d["final"] == "Verifico los 5 SKU."


def test_un_turno_que_dijo_una_sola_cosa_no_repite_nada_arriba():
    """El caso mas comun (51 de 130 turnos medidos): Destacados se ve igual que antes."""
    d = _dice(["Listo, quedó en disco."])
    assert d["says"] == [] and d["final"] == "Listo, quedó en disco."


def test_los_intermedios_vacios_no_dejan_lineas_en_blanco():
    d = _dice(["Arranco.", "   ", "", "Listo."])
    assert d["says"] == ["Arranco."]


def test_vienen_todos_los_mensajes_por_muchos_que_sean():
    """El maximo medido en la maquina es 21 en un turno; no hay tope ni "y N mas"."""
    textos = [f"paso {i}" for i in range(1, 30)] + ["listo"]
    d = _dice(textos)
    assert d["says"] == textos[:-1]


# Destacados no recorta el texto del agente: lo largo lo resuelve el scroll del panel


def test_el_final_va_entero_y_sin_puntos_suspensivos():
    """El caso medido: el 63% de los finales pasaba de los 600 caracteres del recorte viejo, asi
    que la frase cortada era la regla justo en el turno que uno abre para leer que paso."""
    final = "Lo que medí: los 5 SKU existen en la dim, cargados hoy 08:32:55. " + "Detalle. " * 300
    d = _dice(["Analizado.", final])
    assert d["final"] == final.strip()
    assert "…" not in d["final"]


def test_los_mensajes_previos_tambien_van_enteros():
    largo = "y" * 3000
    d = _dice([largo, "listo"])
    assert d["says"] == [largo]


def test_los_comandos_no_tienen_tope_de_cantidad():
    """19 de 131 turnos medidos pasaban los 20 comandos del tope viejo: "comandos (20)" era el
    tope, no la cuenta."""
    blocks = [_tool("Bash", {"command": f"echo {i}"}) for i in range(35)]
    d = tr.digest_turn(_turno("listo", blocks))
    assert len(d["commands"]) == 35 and d["commands"][-1] == "echo 34"


def test_cada_comando_sigue_entrando_por_su_primera_linea():
    """La lista es para ubicarse; el comando entero se lee en Conversación."""
    d = tr.digest_turn(_turno("listo", [_tool("Bash", {"command": "python - <<PY\nprint(1)\nPY"})]))
    assert d["commands"] == ["python - <<PY"]


def test_el_final_propio_de_codex_no_se_duplica_arriba():
    """Codex fija el final en `task_complete` con `last_agent_message`: es el mismo texto del
    ultimo bloque, y tiene que salir una sola vez."""
    d = _dice(["Reviso el rollout.", "Quedó andando."], final="Quedó andando.")
    assert d["says"] == ["Reviso el rollout."] and d["final"] == "Quedó andando."


# 8. Los dos parsers y lo que de verdad comparten (encargo A6) --------------------


def _tool(name, inp, result=None):
    return {"kind": "tool", "name": name, "input": inp, "result": result, "id": "x"}


def _files(blocks):
    return tr.digest_turn(_turno("listo", blocks))["files"]


def test_una_herramienta_de_archivo_sin_ruta_no_deja_una_entrada_vacia():
    """Las dos ramas de `files` (paths de Codex, file_path de Claude) pueden quedar sin nada:
    el vacio se filtra una sola vez al deduplicar, no en cada rama."""
    assert _files([_tool("Edit", {})]) == []
    assert _files([_tool("apply_patch", {"paths": [{}]})]) == []


def test_los_dos_formatos_de_ruta_llegan_al_mismo_campo():
    assert _files([_tool("Edit", {"file_path": "lienzo/transcripts.py"})]) == ["lienzo/transcripts.py"]
    assert _files([_tool("NotebookEdit", {"notebook_path": "a.ipynb"})]) == ["a.ipynb"]
    assert _files([_tool("apply_patch", {"paths": [{"type": "M", "path": "server.py"}]})]) == ["M server.py"]


def test_los_archivos_repetidos_se_deduplican_conservando_orden():
    blocks = [
        _tool("Write", {"file_path": "a.py"}),
        _tool("Edit", {"file_path": "b.py"}),
        _tool("Edit", {"file_path": "a.py"}),
    ]
    assert _files(blocks) == ["a.py", "b.py"]


def test_los_dos_parsers_arman_el_mismo_turno(claude_path, codex_path):
    """La forma del turno es lo unico que comparten de verdad los dos parsers, y la garantiza
    _new_turn. Si un parser empieza a devolver otras claves, la mitad de web/ lee de menos."""
    base = set(tr._new_turn("claude", "t", None))
    for agent, path in (("claude", claude_path), ("codex", codex_path)):
        turns = tr.parse(agent, path)["turns"]
        assert turns, f"{agent}: sin turnos"
        for t in turns:
            assert set(t) - {"from_peer"} == base, f"{agent}: claves de mas o de menos en {t['id']}"


def test_claude_no_pone_id_de_turno_en_las_lineas_del_asistente(claude_path):
    """El motivo medido de que parse_claude no pueda indexar turnos por id como parse_codex: el
    contenido del asistente viene sin promptId, asi que el turno solo se arma por posicion. Si esto
    falla, el formato cambio y el argumento para no unificar los dos parsers hay que volver a medirlo."""
    lines, _ = tr.tail_lines(claude_path)
    asistente = [d for d in tr.iter_json(lines) if d.get("type") == "assistant"]
    assert asistente, "la transcripcion no tiene lineas de assistant"
    assert not [d for d in asistente if d.get("promptId")]


def test_codex_si_pone_id_de_turno_en_el_evento(codex_path):
    """La otra mitad: en Codex el turn_id viaja en el evento, y por eso turn_for busca por id."""
    lines, _ = tr.tail_lines(codex_path)
    eventos = [d for d in tr.iter_json(lines) if d.get("type") == "event_msg"]
    assert [d for d in eventos if (d.get("payload") or {}).get("turn_id")]


# 7. un "API Error" con trabajo despues no es el final del turno ------------------------------


def _jsonl(tmp_path, filas):
    import json

    p = tmp_path / "sesion.jsonl"
    p.write_text(chr(10).join(json.dumps(f, ensure_ascii=False) for f in filas), encoding="utf-8")
    return str(p)


def _asistente(texto=None, tool=None, ts="2026-09-10T00:41:18.775Z", **extra):
    b = (
        {"type": "text", "text": texto}
        if texto is not None
        else {"type": "tool_use", "id": "t1", "name": tool, "input": {}}
    )
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [b]}, **extra}


ERROR_API = "API Error: The response stopped arriving. The response above may be incomplete."


def test_error_de_api_con_trabajo_despues_no_cuenta(tmp_path):
    """Claude Code escribe el aviso y a veces sigue solo: medido en 88182904 el 2026-09-09, el
    error quedo 170 lineas antes del final y la tarjeta lo mostraba en rojo (y el reintento
    automatico mandaba un "Continuar" de mas) con la sesion trabajando."""
    filas = [
        {"type": "user", "timestamp": "2026-09-10T00:01:11.172Z", "message": {"role": "user", "content": "Continuar"}},
        _asistente(texto=ERROR_API, isApiErrorMessage=True),
        _asistente(tool="Bash", ts="2026-09-10T01:12:21.000Z"),
    ]
    t = tr.turns("claude", _jsonl(tmp_path, filas), 1)["turns"][-1]
    assert t["error"] is None, "el turno siguio trabajando: el aviso no fue el final"
    assert t["ended"] is False


def test_error_de_api_al_final_si_cuenta(tmp_path):
    """Sin nada despues, el turno murio ahi: es el caso que se reintenta."""
    filas = [
        {"type": "user", "timestamp": "2026-09-10T00:01:11.172Z", "message": {"role": "user", "content": "Continuar"}},
        _asistente(tool="Bash", ts="2026-09-10T00:30:00.000Z"),
        _asistente(texto=ERROR_API, isApiErrorMessage=True),
    ]
    t = tr.turns("claude", _jsonl(tmp_path, filas), 1)["turns"][-1]
    assert t["error"] == ERROR_API
    assert t["ended"] is True
    assert tr.retryable_error(t["error"]) is True
