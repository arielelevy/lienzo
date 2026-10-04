"""Ola 2 del refactor, registro de agentes: pruebas de referencia (golden) de transcripts.parse con una
transcripcion minima por agente, armada con las formas que ya usan test_transcripts, test_pi y
test_coda. Fijan la salida ANTES de mover el despacho a lienzo/agentes.py: si el registro cambia
que parser corre o con que argumentos, estas pruebas lo dicen."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401, I001
import transcripts as tr

PI_HEADER = {"type": "session", "id": "pi-session", "version": 3, "cwd": "D:/Apps/lienzo"}
CODA_SID = "11111111-2222-4333-8444-555555555555"


def _jsonl(tmp_path, nombre, filas):
    p = tmp_path / nombre
    p.write_text("\n".join(json.dumps(f, ensure_ascii=False) for f in filas) + "\n", encoding="utf-8")
    return str(p)


def claude_transcript(tmp_path):
    return _jsonl(
        tmp_path,
        "claude.jsonl",
        [
            {"type": "ai-title", "aiTitle": "Revisar el repo"},
            {
                "type": "user",
                "timestamp": "2026-09-10T00:01:11.172Z",
                "message": {"role": "user", "content": "revisá el repo"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-09-10T00:01:15.000Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [
                        {"type": "text", "text": "Corro las pruebas."},
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-09-10T00:01:20.000Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "2 passed"}],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-09-10T00:01:25.000Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Listo, todo pasa."}]},
            },
        ],
    )


def codex_transcript(tmp_path):
    ts = "2026-09-10T00:02:00.000Z"
    return _jsonl(
        tmp_path,
        "rollout-codex.jsonl",
        [
            {
                "type": "session_meta",
                "timestamp": ts,
                "payload": {
                    "id": "codex-id",
                    "cwd": "D:\\Apps\\lienzo",
                    "originator": "codex-tui",
                    "cli_version": "0.1",
                    "git": {"branch": "main"},
                },
            },
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "task_started", "turn_id": "tu1"}},
            {
                "type": "event_msg",
                "timestamp": ts,
                "payload": {
                    "type": "item_completed",
                    "turn_id": "tu1",
                    "item": {"type": "UserMessage", "content": [{"type": "text", "text": "revisá el repo"}]},
                },
            },
            {
                "type": "event_msg",
                "timestamp": ts,
                "payload": {
                    "type": "item_completed",
                    "turn_id": "tu1",
                    "item": {
                        "type": "CommandExecution",
                        "id": "c1",
                        "command": ["pytest"],
                        "cwd": "D:\\Apps\\lienzo",
                        "stdout": "1 failed",
                        "exit_code": 1,
                    },
                },
            },
            {
                "type": "event_msg",
                "timestamp": ts,
                "payload": {"type": "task_complete", "turn_id": "tu1", "last_agent_message": "Falla una."},
            },
        ],
    )


def _pi_msg(id, parent, role, content, **extra):
    return {
        "type": "message",
        "id": id,
        "parentId": parent,
        "timestamp": "2026-09-10T10:00:00Z",
        "message": {"role": role, "content": content, **extra},
    }


def pi_transcript(tmp_path):
    return _jsonl(
        tmp_path,
        "pi.jsonl",
        [
            PI_HEADER,
            {"type": "session_info", "id": "name", "parentId": None, "name": "Revisión Pi"},
            _pi_msg("u", "name", "user", [{"type": "text", "text": "Revisá esto"}]),
            _pi_msg(
                "a",
                "u",
                "assistant",
                [
                    {"type": "text", "text": "Voy a revisar"},
                    {"type": "toolCall", "id": "b", "name": "bash", "arguments": {"command": "pytest"}},
                ],
                stopReason="toolUse",
            ),
            _pi_msg("rb", "a", "toolResult", [{"type": "text", "text": "ok"}], toolCallId="b", toolName="bash"),
            _pi_msg("end", "rb", "assistant", [{"type": "text", "text": "Listo."}], stopReason="stop"),
        ],
    )


def coda_transcript(tmp_path):
    path = tmp_path / "coda.db"
    c = sqlite3.connect(path)
    c.execute(
        "create table sessions (id text primary key, relationship text not null default 'root',"
        " project_dir text not null, title text, model text not null, created_at int, updated_at int)"
    )
    c.execute(
        "create table messages (id text primary key, session_id text not null, parent_id text,"
        " role text not null, content text not null, created_at integer not null)"
    )
    c.execute("insert into sessions values (?, 'root', 'D:\\Apps\\demo', 'Revisión coda', 'm', 0, 0)", (CODA_SID,))
    t0 = 1790265830000
    filas = [
        ("user", "revisá el repo", None, t0),
        (
            "assistant",
            json.dumps(
                [
                    {"type": "text", "text": "Mapeo."},
                    {"type": "tool-call", "toolCallId": "b", "toolName": "bash", "args": {"command": "pytest"}},
                ]
            ),
            None,
            t0 + 1,
        ),
        ("tool", "1 passed\n[exit code: 0]", "b", t0 + 2),
        ("assistant", json.dumps([{"type": "text", "text": "Listo."}]), None, t0 + 3),
    ]
    for i, (role, content, parent, ts) in enumerate(filas):
        c.execute("insert into messages values (?, ?, ?, ?, ?, ?)", (f"m{i}", CODA_SID, parent, role, content, ts))
    c.commit()
    c.close()
    return str(path)


FIXTURES = {
    "claude": (claude_transcript, None),
    "codex": (codex_transcript, None),
    "pi": (pi_transcript, None),
    "coda": (coda_transcript, CODA_SID),
}


def _normal(r: dict, tmp_path) -> dict:
    """La salida en JSON, con la ruta temporal reemplazada para que la referencia no dependa de ella.
    Las horas de CODA salen de milisegundos en la zona local de la PC: se sacan (y se exige que
    esten) para que la referencia valga igual en la notebook."""
    r = json.loads(json.dumps(r, ensure_ascii=False).replace(json.dumps(str(tmp_path))[1:-1], "<TMP>"))
    if r["meta"].get("agent") == "coda":
        for t in r["turns"]:
            assert t.pop("ts_start") and t.pop("ts_end")
    return r


# --- referencias: generadas una vez con el despacho de antes del registro (commit de las pruebas) ---

GOLDEN: dict[str, dict] = {
    "claude": {
        "meta": {
            "agent": "claude",
            "branch": None,
            "cwd": None,
            "title": "Revisar el repo",
            "truncated": False,
            "version": None,
        },
        "turns": [
            {
                "agent": "claude",
                "blocks": [
                    {"kind": "text", "phase": None, "text": "Corro las pruebas."},
                    {
                        "id": "t1",
                        "input": {"command": "pytest"},
                        "kind": "tool",
                        "name": "Bash",
                        "result": {"is_error": False, "text": "2 passed"},
                    },
                    {"kind": "text", "phase": None, "text": "Listo, todo pasa."},
                ],
                "ended": False,
                "error": None,
                "extensions": 0,
                "final": "Listo, todo pasa.",
                "id": "0",
                "prompt": "revisá el repo",
                "ts_end": "2026-09-10T00:01:25.000Z",
                "ts_start": "2026-09-10T00:01:11.172Z",
                "usage": None,
            }
        ],
    },
    "coda": {
        "meta": {
            "agent": "coda",
            "branch": None,
            "cwd": "D:\\Apps\\demo",
            "title": "Revisión coda",
            "truncated": False,
            "version": None,
        },
        "turns": [
            {
                "agent": "coda",
                "blocks": [
                    {"kind": "text", "phase": None, "text": "Mapeo."},
                    {
                        "id": "b",
                        "input": {"command": "pytest"},
                        "kind": "tool",
                        "name": "bash",
                        "result": {"is_error": False, "text": "1 passed\n[exit code: 0]"},
                    },
                    {"kind": "text", "phase": None, "text": "Listo."},
                ],
                "ended": True,
                "error": None,
                "extensions": 0,
                "final": "Listo.",
                "id": "11111111-1790265830000",
                "prompt": "revisá el repo",
                "usage": None,
            }
        ],
    },
    "codex": {
        "meta": {
            "agent": "codex",
            "branch": "main",
            "cwd": "D:\\Apps\\lienzo",
            "imported": False,
            "originator": "codex-tui",
            "source": None,
            "title": None,
            "truncated": False,
            "version": "0.1",
        },
        "turns": [
            {
                "agent": "codex",
                "blocks": [
                    {
                        "id": "c1",
                        "input": {"command": "pytest", "cwd": "D:\\Apps\\lienzo"},
                        "kind": "tool",
                        "name": "shell",
                        "result": {"is_error": True, "text": "1 failed"},
                    }
                ],
                "ended": True,
                "error": None,
                "extensions": 0,
                "final": "Falla una.",
                "id": "tu1",
                "prompt": "revisá el repo",
                "ts_end": "2026-09-10T00:02:00.000Z",
                "ts_start": "2026-09-10T00:02:00.000Z",
                "usage": None,
            }
        ],
    },
    "pi": {
        "meta": {
            "agent": "pi",
            "branch": None,
            "cwd": "D:/Apps/lienzo",
            "title": "Revisión Pi",
            "truncated": False,
            "version": 3,
        },
        "turns": [
            {
                "agent": "pi",
                "blocks": [
                    {"kind": "text", "phase": "commentary", "text": "Voy a revisar"},
                    {
                        "id": "b",
                        "input": {"command": "pytest"},
                        "kind": "tool",
                        "name": "bash",
                        "result": {"is_error": False, "text": "ok"},
                    },
                    {"kind": "text", "phase": "final", "text": "Listo."},
                ],
                "ended": True,
                "error": None,
                "extensions": 0,
                "final": "Listo.",
                "id": "u",
                "prompt": "Revisá esto",
                "ts_end": "2026-09-10T10:00:00Z",
                "ts_start": "2026-09-10T10:00:00Z",
                "usage": None,
            }
        ],
    },
}


@pytest.mark.parametrize("agent", sorted(FIXTURES))
def test_parse_golden_por_agente(agent, tmp_path):
    hacer, leaf = FIXTURES[agent]
    r = tr.parse(agent, hacer(tmp_path), leaf_id=leaf)
    assert _normal(r, tmp_path) == GOLDEN[agent]


@pytest.mark.parametrize("agent", sorted(FIXTURES))
def test_turns_usa_el_mismo_parser(agent, tmp_path):
    hacer, leaf = FIXTURES[agent]
    r = tr.turns(agent, hacer(tmp_path), 10, leaf_id=leaf)
    assert _normal({"meta": r["meta"], "turns": r["turns"]}, tmp_path) == GOLDEN[agent]


@pytest.mark.xfail(reason="hasta el paso 3: un agente desconocido caia a parse_claude sin aviso", strict=True)
def test_agente_desconocido_es_un_error_explicito(tmp_path):
    path = claude_transcript(tmp_path)
    with pytest.raises(ValueError, match="agente desconocido"):
        tr.parse("gemini", path)
