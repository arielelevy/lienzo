"""Contadores publicados, sin red ni CLIs reales. Los números esperados son fixtures explícitas."""

import json
import sqlite3

import pytest
import turn_usage as u

END = "2026-10-25T12:00:10+00:00"


def source(agent, path, **kw):
    return {
        "agent": agent,
        "session_id": "session-abcdefgh",
        "transcript_path": str(path),
        "state_since": END,
        "transcript_turn_id": "t",
        **kw,
    }


def write(tmp_path, rows):
    path = tmp_path / "turnos.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def user(tid):
    return {"type": "user", "uuid": tid, "message": {"content": "pedido"}}


def assistant(mid, usage, **kw):
    return {"type": "assistant", "message": {"id": mid, "usage": usage}, **kw}


def cu(i, o, cr=0, cw=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}


def event(kind, **kw):
    return {"type": "event_msg", "payload": {"type": kind, **kw}}


def totals(i, o, cr=0, r=0):
    return event(
        "token_count",
        info={
            "total_token_usage": {
                "input_tokens": i,
                "output_tokens": o,
                "cached_input_tokens": cr,
                "reasoning_output_tokens": r,
            }
        },
    )


def test_claude_suma_llamadas_deduplica_bloques_y_separa_otro_turno(tmp_path):
    path = write(
        tmp_path,
        [
            user("t"),
            assistant("m1", cu(10, 2, 30, 4)),
            assistant("m1", cu(10, 3, 30, 4)),
            assistant("sub", cu(999, 999), isSidechain=True),
            assistant("m2", cu(20, 5, 40, 6)),
            user("otro"),
            assistant("m3", cu(999, 999)),
        ],
    )
    assert u.medir(source("claude", path)) == {
        "input": 1029,
        "output": 1007,
        "cache_read": 70,
        "cache_write": 10,
        "reasoning": None,
    }


def test_claude_prefiere_prompt_id_al_turno_viejo(tmp_path):
    path = write(tmp_path, [user("viejo"), assistant("old", cu(99, 99)), user("t"), assistant("new", cu(1, 2))])
    assert u.medir(source("claude", path, prompt_id="t", transcript_turn_id="viejo"))["input"] == 1


def test_claude_campos_ausentes_no_se_convierten_en_cero(tmp_path):
    path = write(tmp_path, [user("t"), assistant("m", {"input_tokens": 4, "output_tokens": 2})])
    assert u.medir(source("claude", path)) == {
        "input": 4,
        "output": 2,
        "cache_read": None,
        "cache_write": None,
        "reasoning": None,
    }


def test_claude_no_atribuye_suma_parcial_si_una_llamada_no_publico_usage(tmp_path):
    path = write(tmp_path, [user("t"), assistant("m", cu(4, 2)), assistant("n", None)])
    assert u.medir(source("claude", path)) is None


def test_codex_resta_acumulados_y_no_duplica_cache_ni_reinicios_de_evento(tmp_path):
    path = write(
        tmp_path,
        [
            event("task_started", turn_id="viejo"),
            totals(100, 20, 40, 10),
            event("task_complete", turn_id="viejo"),
            event("task_started", turn_id="t"),
            totals(180, 40, 70, 15),
            event("task_started", turn_id="t"),
            totals(250, 70, 100, 30),
            event("task_complete", turn_id="t"),
            event("task_started", turn_id="nuevo"),
            totals(999, 999, 100, 99),
        ],
    )
    assert u.medir(source("codex", path)) == {
        "input": 90,
        "output": 50,
        "cache_read": 60,
        "cache_write": None,
        "reasoning": 20,
    }


def test_codex_primer_turno_completo_y_cero_medido(tmp_path):
    path = write(tmp_path, [event("task_started", turn_id="t"), totals(0, 0), event("task_complete", turn_id="t")])
    assert u.medir(source("codex", path)) == {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": None,
        "reasoning": 0,
    }


def test_codex_contadores_reiniciados_no_se_clampean_a_cero(tmp_path):
    path = write(
        tmp_path,
        [
            event("task_started", turn_id="old"),
            totals(100, 100, 50, 50),
            event("task_started", turn_id="t"),
            totals(1, 1, 1, 1),
            event("task_complete", turn_id="t"),
        ],
    )
    assert u.medir(source("codex", path)) is None


def test_codex_un_contador_que_baja_invalida_los_otros_deltas(tmp_path):
    path = write(tmp_path, [event("task_started", turn_id="old"), totals(100, 100, 50, 50), event("task_started", turn_id="t"), totals(200, 200, 1, 100), event("task_complete", turn_id="t")])
    assert u.medir(source("codex", path)) is None


def test_codex_sin_muestra_previa_no_inventa_baseline_de_turno_posterior(tmp_path):
    path = write(
        tmp_path,
        [
            event("task_started", turn_id="old"),
            event("task_started", turn_id="t"),
            totals(100, 20),
            event("task_complete", turn_id="t"),
        ],
    )
    assert u.medir(source("codex", path)) is None


def test_codex_turno_abierto_o_sin_total_no_se_mide(tmp_path):
    path = write(tmp_path, [event("task_started", turn_id="t"), totals(10, 2)])
    assert u.medir(source("codex", path)) is None
    path = write(
        tmp_path,
        [
            event("task_started", turn_id="t"),
            event("token_count", info={"last_token_usage": {"input_tokens": 10}}),
            event("task_complete", turn_id="t"),
        ],
    )
    assert u.medir(source("codex", path)) is None


def test_pi_solo_rama_capturada_y_todas_sus_llamadas(tmp_path):
    rows = [{"type": "message", "id": "t", "parentId": None, "message": {"role": "user"}}]
    for mid, parent, inp in [("a", "t", 4), ("b", "a", 6), ("rama", "t", 999)]:
        rows.append(
            {
                "type": "message",
                "id": mid,
                "parentId": parent,
                "message": {"role": "assistant", "usage": {"input": inp, "output": 2, "cacheRead": 3, "cacheWrite": 1}},
            }
        )
    path = write(tmp_path, rows)
    assert u.medir(source("pi", path, pi_leaf_id="b")) == {
        "input": 10,
        "output": 4,
        "cache_read": 6,
        "cache_write": 2,
        "reasoning": None,
    }
    assert u.medir(source("pi", path, pi_leaf_id="no-existe")) is None


def test_pi_no_mezcla_un_turno_posterior(tmp_path):
    path = write(
        tmp_path,
        [
            {"id": "t", "type": "message", "message": {"role": "user"}},
            {"id": "next", "parentId": "t", "type": "message", "message": {"role": "user"}},
        ],
    )
    assert u.medir(source("pi", path)) is None


def test_coda_suma_usage_del_turno_y_no_del_siguiente_ni_otra_sesion(tmp_path):
    path = tmp_path / "coda #datos.db"
    start = 1792929600000  # 2026-10-25 12:00 UTC
    with sqlite3.connect(path) as con:
        con.executescript(
            "CREATE TABLE messages(session_id TEXT, role TEXT, content TEXT, created_at INTEGER); CREATE TABLE usage(session_id TEXT, input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, reasoning INTEGER, created_at INTEGER);"
        )
        con.executemany(
            "INSERT INTO messages VALUES (?,?,?,?)",
            [
                ("session-abcdefgh", "user", "pedido", start),
                ("session-abcdefgh", "user", "[CODA SYSTEM MESSAGE] aviso", start + 500),
                ("session-abcdefgh", "user", "siguiente", start + 2000),
            ],
        )
        con.executemany(
            "INSERT INTO usage VALUES (?,?,?,?,?,?,?)",
            [
                ("session-abcdefgh", 10, 2, 3, 4, 1, start + 1000),
                ("session-abcdefgh", 20, 3, 4, 5, 2, start + 1500),
                ("session-abcdefgh", 999, 999, 999, 999, 999, start + 2000),
                ("otra", 999, 999, 999, 999, 999, start + 1000),
            ],
        )
    assert u.medir(source("coda", path, transcript_turn_id=f"session--{start}")) == {
        "input": 30,
        "output": 5,
        "cache_read": 7,
        "cache_write": 9,
        "reasoning": 3,
    }


@pytest.mark.parametrize("value", [True, -1, 1.2, "4", None])
def test_valores_invalidos_son_desconocidos_no_estimados(tmp_path, value):
    path = write(tmp_path, [user("t"), assistant("m", {"input_tokens": value, "output_tokens": 2})])
    assert u.medir(source("claude", path))["input"] is None


def test_falta_archivo_o_agente_sin_tokens_no_interrumpe_captura(tmp_path, monkeypatch):
    logs = []
    monkeypatch.setattr(u.state, "log", logs.append)
    assert u.medir(source("claude", tmp_path / "no-existe")) is None
    assert len(logs) == 1 and "FileNotFoundError" in logs[0]
    assert u.medir(source("kiro", tmp_path / "no-existe")) is None


def test_no_suma_eventos_posteriores_a_la_ventana_cerrada(tmp_path):
    path = write(
        tmp_path,
        [
            user("t"),
            assistant("a", cu(1, 2), timestamp="2026-10-25T12:00:09Z"),
            assistant("b", cu(999, 999), timestamp="2026-10-25T12:00:16Z"),
        ],
    )
    assert u.medir(source("claude", path))["input"] == 1


def test_lee_comienzo_de_turno_fuera_de_cola_ui(tmp_path):
    path = write(
        tmp_path, [user("t"), {"type": "system", "padding": "x" * (2 * 1024 * 1024 + 100)}, assistant("a", cu(7, 3))]
    )
    assert u.medir(source("claude", path))["input"] == 7


def test_transcript_corrupto_no_se_presenta_como_consumo_completo(tmp_path, monkeypatch):
    path = write(tmp_path, [user("t"), assistant("a", cu(7, 3))])
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"type": "assistant",')
    logs = []
    monkeypatch.setattr(u.state, "log", logs.append)
    assert u.medir(source("claude", path)) is None
    assert logs and "ValueError" in logs[0]


def test_limite_de_lectura_no_sigue_append_de_otro_turno(tmp_path):
    path = write(tmp_path, [user("t"), assistant("a", cu(7, 3))])
    rows = u.filas(str(path), None)
    assert next(rows)["uuid"] == "t"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(assistant("futuro", cu(999, 999))) + "\n")
    assert len(list(rows)) == 1


def test_snapshot_ya_reabierto_no_atribuye_tokens_de_otro_cierre(tmp_path):
    path = write(tmp_path, [user("t"), assistant("a", cu(7, 3))])
    assert u.medir(source("claude", path, state="corriendo")) is None
