"""Tokens emitidos por el agente, ligados al turno cerrado. Sin tarifas ni estimaciones."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

import state
import transcripts

FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")
CLAUDE = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_write": "cache_creation_input_tokens",
}
CODEX = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cached_input_tokens",
    "reasoning": "reasoning_output_tokens",
}
PI = {
    "input": "input",
    "output": "output",
    "cache_read": "cacheRead",
    "cache_write": "cacheWrite",
    "reasoning": "reasoning",
}


def numero(n):
    return n if type(n) is int and n >= 0 else None


def fecha(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def sumar(usages: list, campos: dict) -> dict | None:
    if not usages:
        return None
    out = {}
    for key in FIELDS:
        values = [numero(u.get(campos.get(key))) for u in usages]
        out[key] = sum(values) if all(v is not None for v in values) else None
    return out if any(v is not None for v in out.values()) else None


def filas(path: str, hasta):
    """Lectura completa en streaming: el comienzo del turno puede estar fuera de la cola de UI."""
    with open(path, "rb") as stream:
        remaining = os.fstat(stream.fileno()).st_size
        while remaining > 0:
            line = stream.readline(remaining)
            if not line:
                raise OSError("transcript truncado durante la medición")
            remaining -= len(line)
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError, UnicodeError:
                raise ValueError("transcript incompleto o inválido para medir usage") from None
            if not isinstance(row, dict):
                raise TypeError("fila de transcript inválida para medir usage")
            at = fecha(row.get("timestamp"))
            if hasta is not None and at is not None and at > hasta:
                continue
            yield row


def _humano(row: dict) -> bool:
    if row.get("type") != "user" or row.get("isSidechain"):
        return False
    msg = row.get("message")
    if not isinstance(msg, dict):
        raise TypeError("pedido sin estructura de mensaje reconocida")
    content = msg.get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = transcripts._content_text(content)
    return not transcripts.is_system_prompt(text) and not text.startswith("[Request interrupted")


def claude(source: dict, rows) -> dict | None:
    target = source.get("prompt_id") or source.get("transcript_turn_id")
    if not target:
        return None
    active, found, messages = False, False, {}
    for row in rows:
        if _humano(row):
            active = target in (row.get("promptId"), row.get("uuid"))
            if found and not active:
                break
            found |= active
        if not active or row.get("type") != "assistant":
            continue
        msg = row.get("message")
        if not isinstance(msg, dict):
            raise TypeError("respuesta sin estructura de mensaje reconocida")
        usage = msg.get("usage")
        key = msg.get("id") or row.get("uuid")
        if key:
            if isinstance(usage, dict):
                messages.setdefault(key, {}).update(usage)  # una llamada; última lectura emitida de cada contador
            else:
                messages.setdefault(key, {})
        else:
            raise ValueError("mensaje sin identidad para deduplicar usage")
    return sumar(list(messages.values()), CLAUDE) if found else None


def _delta(end: dict, start: dict | None, primera: bool) -> dict:
    for raw in CODEX.values():
        a, b = numero((start or {}).get(raw)), numero(end.get(raw))
        if a is not None and b is not None and b < a:
            return dict.fromkeys(FIELDS)  # un acumulador reiniciado invalida la comparación completa
    out = {}
    for key in FIELDS:
        raw = CODEX.get(key)
        a = 0 if primera else numero((start or {}).get(raw))
        b = numero(end.get(raw))
        out[key] = b - a if a is not None and b is not None and b >= a else None
    if out["input"] is not None and out["cache_read"] is not None:
        out["input"] = numero(out["input"] - out["cache_read"])
    else:
        out["input"] = None
    return out


def codex(source: dict, rows) -> dict | None:
    target = source.get("transcript_turn_id")
    if not target:
        return None
    previous, start, end = None, None, None
    active, primera, turns, closed = False, False, set(), False
    for row in rows:
        if row.get("type") != "event_msg":
            continue
        p = row.get("payload")
        if not isinstance(p, dict):
            continue
        if p.get("type") == "task_started":
            if p.get("turn_id") in turns:
                continue
            if active and closed:
                break
            turns.add(p.get("turn_id"))
            active = p.get("turn_id") == target
            if active:
                start, primera = previous, len(turns) == 1 and previous is None
        if p.get("type") == "token_count":
            info = p.get("info")
            usage = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(usage, dict):
                previous = usage
                if active:
                    end = usage
        if active and p.get("type") in ("task_complete", "turn_aborted") and p.get("turn_id") == target:
            closed = True
    if end is None or not closed:
        return None
    out = _delta(end, start, primera)
    return out if any(v is not None for v in out.values()) else None


def pi(source: dict, rows) -> dict | None:
    target = source.get("transcript_turn_id")
    if not target:
        return None
    nodes = {}
    captured_leaf = source.get("pi_leaf_id")
    for row in rows:
        if row.get("id") and row.get("type") != "session":
            msg = row.get("message")
            msg = msg if isinstance(msg, dict) else {}
            nodes[row["id"]] = (row.get("parentId"), msg.get("role"), msg.get("usage"))
            if row["id"] == captured_leaf:
                break
    leaf = source.get("pi_leaf_id")
    if leaf is None:
        leaf = next(reversed(nodes), None)
    usages, seen = [], set()
    while leaf in nodes and leaf not in seen:
        seen.add(leaf)
        parent, role, usage = nodes[leaf]
        if leaf == target and role == "user":
            return sumar(usages, PI)
        if role == "user":
            return None  # otra rama o turno: no atribuir tokens de un pedido posterior
        if role == "assistant":
            usages.append(usage if isinstance(usage, dict) else {})
        leaf = parent
    return None


def coda(source: dict) -> dict | None:
    sid, target = source.get("session_id"), source.get("transcript_turn_id")
    if not isinstance(target, str) or not sid or not target.startswith(sid[:8] + "-"):
        return None
    try:
        start = int(target[len(sid[:8]) + 1 :])
    except ValueError:
        return None
    until = fecha(source.get("state_since"))
    if until is None:
        return None
    stop = int((until + dt.timedelta(seconds=5)).timestamp() * 1000)
    uri = Path(source["transcript_path"]).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=2) as con:
        pedidos = con.execute(
            "SELECT created_at, content FROM messages WHERE session_id=? AND role='user' AND created_at>=? ORDER BY created_at",
            (sid, start),
        ).fetchall()
        reales = [
            at
            for at, text in pedidos
            if not str(text).startswith(("[CODA SYSTEM MESSAGE]", "[Request interrupted"))
            and not transcripts.is_system_prompt(str(text))
        ]
        if reales.count(start) != 1:
            return None
        siguiente = next((at for at in reales if at > start), None)
        if siguiente is not None:
            stop = min(stop, siguiente - 1)
        columns = ",".join(FIELDS)
        rows = con.execute(
            f"SELECT {columns} FROM usage WHERE session_id=? AND created_at>=? AND created_at<=?", (sid, start, stop)
        ).fetchall()
    return sumar([dict(zip(FIELDS, row)) for row in rows], {k: k for k in FIELDS})


def medir(source: dict) -> dict | None:
    """Sólo la PC dueña, fuera del lock de sesiones. Ausencia de contadores no significa cero."""
    agent, path = source.get("agent"), source.get("transcript_path")
    if not path or source.get("state") == "corriendo":
        return None
    try:
        if agent == "coda":
            return coda(source)
        parser = {"claude": claude, "codex": codex, "pi": pi}.get(agent)
        if parser is None:
            return None  # Kiro observado publica créditos/contexto, no tokens por turno
        until = fecha(source.get("state_since"))
        if until is None:
            return None
        return parser(source, filas(path, until + dt.timedelta(seconds=5)))
    except (OSError, ValueError, TypeError, sqlite3.Error) as e:
        state.log(f"captura: usage no disponible para {str(source.get('session_id'))[:8]} ({type(e).__name__})")
        return None
