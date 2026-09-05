"""Lectura por la cola de las transcripciones de Claude Code y Codex, y digest por turno.

Estructura comun de un turno (los dos agentes):

    {
      "id": "<promptId | turn_id>",
      "agent": "claude" | "codex",
      "ts_start": "...", "ts_end": "...",
      "prompt": "texto del pedido humano",
      "blocks": [
        {"kind": "text", "text": "...", "phase": "commentary|final"},
        {"kind": "thinking", "text": "..."},
        {"kind": "tool", "id": "...", "name": "Bash", "input": {...},
         "result": {"text": "...", "is_error": false} | None},
        {"kind": "user_text", "text": "[Request interrupted...]"},
        {"kind": "subagent", "n": 12}
      ],
      "final": "ultimo texto del asistente en el turno",
      "ended": true,
      "error": None | "mensaje",
      "usage": {...} | None,
      "extensions": 0,       # items Extension de Codex (web.search, ...) contados, sin bloque
      "from_peer": "lienzo-b7"   # solo si el pedido vino de otra sesion de Claude (<cross-session-message>)
    }
"""
from __future__ import annotations

import json
import os
import datetime as dt
import re

TAIL_BYTES = 2 * 1024 * 1024
FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
SHELL_TOOLS = {"Bash", "PowerShell", "shell", "exec", "exec_command"}
READ_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}


# --- utilidades --------------------------------------------------------------

def tail_lines(path: str, max_bytes: int = TAIL_BYTES) -> tuple[list[str], bool]:
    """Devuelve (lineas, truncado). Lee solo los ultimos max_bytes."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        truncated = size > max_bytes
        if truncated:
            f.seek(size - max_bytes)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if truncated:
        lines = lines[1:]  # primera linea parcial
    return [l.rstrip("\r") for l in lines if l.strip()], truncated


def iter_json(lines):
    for l in lines:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if isinstance(d, dict):  # `null` o listas son JSON valido pero no lineas de transcripcion
            yield d


def _short(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _first_line(s: str, n: int = 160) -> str:
    return _short((s or "").strip().split("\n", 1)[0], n)


SYSTEM_PROMPT_TAGS = ("<task-notification>", "<system-reminder>", "<local-command-", "<command-name>",
                      "<command-message>", "<bash-input>", "<bash-stdout>", "<ide_", "<user-memory-input>")


ERROR_PATTERNS = ("You've hit your", "usage limit", "session limit", "rate limit", "API Error",
                  "overloaded_error", "Request timed out", "Credit balance is too low")


def looks_like_error(text: str) -> bool:
    """Avisos de limite de uso o de API que Claude Code escribe como si fueran respuesta."""
    t = (text or "").strip()
    return 0 < len(t) < 400 and any(p.lower() in t.lower() for p in ERROR_PATTERNS)


# "try again at 7:57 PM", "try again at Sep 5th, 2026 3:08 AM", "resets 2:40pm" (Claude)
_RESET_AT_RE = re.compile(
    r"(?:try again|resets?)\s+(?:at\s+)?"
    r"(?:(?P<mon>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4}),?\s+)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>[AaPp]\.?[Mm])?", re.I)
# "try again in 2 hours 15 minutes", "resets in 45 min"
_RESET_IN_RE = re.compile(
    r"(?:try again|resets?)\s+in\s+(?:(?P<h>\d+)\s*h(?:ours?|rs?)?\b)?[\s,]*(?:(?P<m>\d+)\s*m(?:in(?:ute)?s?)?\b)?", re.I)


def limit_reset(text: str, ref: dt.datetime | None = None) -> dt.datetime | None:
    """Hora en que vuelve el cupo, sacada de un aviso de limite de uso. `ref` es cuando se
    escribio el aviso (con zona; sin ella, ahora): una hora sin fecha es la primera vez que
    ocurre desde `ref`, asi "7:57 PM" leido a las 20:10 sigue siendo las 19:57 de hoy."""
    t = text or ""
    ref = (ref or dt.datetime.now()).astimezone()
    m = _RESET_IN_RE.search(t)
    if m and (m.group("h") or m.group("m")):
        return ref + dt.timedelta(hours=int(m.group("h") or 0), minutes=int(m.group("m") or 0))
    m = _RESET_AT_RE.search(t)
    if not m:
        return None
    h, mi = int(m.group("h")), int(m.group("m") or 0)
    ap = (m.group("ampm") or "").replace(".", "").lower()
    if not ap and m.group("m") is None:
        return None  # "try again 5" no es una hora
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    if m.group("mon"):
        try:
            mon = dt.datetime.strptime(m.group("mon").title(), "%b").month
            return ref.replace(year=int(m.group("year")), month=mon, day=int(m.group("day")),
                               hour=h, minute=mi, second=0, microsecond=0)
        except ValueError:
            return None
    at = ref.replace(hour=h, minute=mi, second=0, microsecond=0)
    # la referencia es el fin del turno, que puede quedar unos minutos despues del aviso: una hora
    # apenas cumplida sigue siendo hoy, no manana
    if at < ref - dt.timedelta(minutes=10):
        at += dt.timedelta(days=1)
    return at


def is_system_prompt(text: str) -> bool:
    """Mensajes que Claude Code inyecta como 'usuario' pero no escribio el usuario
    (avisos de tareas en background, recordatorios, salida de comandos locales)."""
    t = (text or "").lstrip()
    return t.startswith(SYSTEM_PROMPT_TAGS)


_XSESSION_RE = re.compile(r"<cross-session-message\b([^>]*)>(.*?)</cross-session-message>", re.S)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def peer_message(text: str) -> tuple[str, str] | None:
    """Mensaje de otra sesion de Claude (SendMessage) que Claude Code inyecta como pedido de usuario:
    'Another Claude session sent a message:\n<cross-session-message from="..." from-name="lienzo-b7" ...>
    texto</cross-session-message>\n\nThis came from another Claude session...'. Devuelve (from_name, texto)
    o None si no tiene esa forma."""
    m = _XSESSION_RE.search(text or "")
    if not m:
        return None
    attrs = dict(_ATTR_RE.findall(m.group(1)))
    name = attrs.get("from-name") or attrs.get("from") or "otra sesión"
    return name, m.group(2).strip()


def _new_turn(agent: str, tid: str, ts: str | None, prompt: str = "") -> dict:
    return {"id": tid, "agent": agent, "ts_start": ts, "ts_end": ts, "prompt": prompt,
            "blocks": [], "final": "", "ended": False, "error": None, "usage": None, "extensions": 0}


def _content_text(content) -> str:
    """Texto de un `content` de Claude (str o lista de bloques) o de un item de Codex
    (lista de {type: "Text"|"text"|..., text}). Une los bloques que traen `text`."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def add_text(turn: dict, text: str, phase=None) -> None:
    """Texto del asistente: bloque + actualiza `final` si no esta vacio."""
    turn["blocks"].append({"kind": "text", "text": text or "", "phase": phase})
    if (text or "").strip():
        turn["final"] = text


def set_prompt(turn: dict, text: str) -> None:
    """Pedido humano; si el turno ya tenia prompt (varios UserMessage), lo acumula."""
    text = text or ""
    turn["prompt"] = (turn["prompt"] + "\n" + text).strip() if turn["prompt"] else text


# --- Claude Code -------------------------------------------------------------

def parse_claude(path: str, max_bytes: int = TAIL_BYTES) -> dict:
    lines, truncated = tail_lines(path, max_bytes)
    meta = {"agent": "claude", "title": None, "branch": None, "cwd": None, "version": None, "truncated": truncated}
    turns: list[dict] = []
    cur: dict | None = None
    tools: dict[str, dict] = {}       # tool_use_id -> bloque tool
    sidechain: dict[str | None, int] = {}   # turn id -> lineas de subagente; None = antes del primer turno

    def ensure_turn(ts):
        nonlocal cur
        if cur is None:
            cur = _new_turn("claude", "parcial", ts, "(turno anterior al corte)")
            turns.append(cur)
        return cur

    for d in iter_json(lines):
        t = d.get("type")
        if t == "ai-title":
            meta["title"] = d.get("aiTitle")
            continue
        if d.get("gitBranch"):
            meta["branch"] = d["gitBranch"]
        if d.get("cwd"):
            meta["cwd"] = d["cwd"]
        if d.get("version"):
            meta["version"] = d["version"]
        ts = d.get("timestamp")

        if t == "system":
            if d.get("subtype") == "turn_duration" and cur is not None:
                cur["ended"] = True
                cur["ts_end"] = ts or cur["ts_end"]
            continue

        if t not in ("user", "assistant"):
            continue

        if d.get("isSidechain"):
            key = cur["id"] if cur else None
            sidechain[key] = sidechain.get(key, 0) + 1
            continue

        msg = d.get("message") or {}
        content = msg.get("content")

        if t == "user":
            # pedido humano: string, o lista sin tool_result (imagen adjunta + texto, "Continue from
            # where you left off" tras compactar). Las interrupciones y avisos del sistema no abren turno.
            blocks = content if isinstance(content, list) else []
            has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
            human = content if isinstance(content, str) else (_content_text(content) if not has_result else None)
            if human is not None:
                if is_system_prompt(human) or human.startswith("[Request interrupted"):
                    turn = ensure_turn(ts)
                    turn["blocks"].append({"kind": "user_text", "text": _short(human, 300)})
                    continue
                if cur is not None:
                    cur["ended"] = True  # un pedido nuevo cierra el anterior aunque no haya turn_duration
                peer = peer_message(human)
                if peer:
                    # pedido real de otra sesion de Claude: sin el XML ni el aviso de permisos que lo envuelve
                    human = f"de {peer[0]}: {_short(peer[1], 2000)}"
                cur = _new_turn("claude", d.get("promptId") or d.get("uuid") or str(len(turns)), ts, human or "(imagen)")
                if peer:
                    cur["from_peer"] = peer[0]
                turns.append(cur)
                continue
            if isinstance(content, list):
                turn = ensure_turn(ts)
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        rc = b.get("content")
                        text = _content_text(rc) if not isinstance(rc, str) else rc
                        res = {"text": _short(text, 4000), "is_error": bool(b.get("is_error"))}
                        blk = tools.get(b.get("tool_use_id"))
                        if blk is not None:
                            blk["result"] = res
                        else:
                            turn["blocks"].append({"kind": "tool", "id": b.get("tool_use_id"), "name": "?",
                                                   "input": {}, "result": res})
                turn["ts_end"] = ts or turn["ts_end"]
            continue

        # assistant
        turn = ensure_turn(ts)
        turn["ts_end"] = ts or turn["ts_end"]
        if msg.get("usage"):
            turn["usage"] = msg["usage"]
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            k = b.get("type")
            if k == "text":
                add_text(turn, b.get("text", ""))
                if looks_like_error(b.get("text", "")):
                    turn["error"] = _short(b["text"].strip(), 300)
                    turn["ended"] = True
            elif k == "thinking":
                turn["blocks"].append({"kind": "thinking", "text": b.get("thinking", "")})
            elif k == "tool_use":
                blk = {"kind": "tool", "id": b.get("id"), "name": b.get("name", "?"),
                       "input": b.get("input") or {}, "result": None}
                tools[b.get("id")] = blk
                turn["blocks"].append(blk)

    if turns and sidechain.get(None):
        # lineas de subagente anteriores al primer pedido: van al primer turno real
        sidechain[turns[0]["id"]] = sidechain.get(turns[0]["id"], 0) + sidechain.pop(None)
    for tr in turns:
        n = sidechain.get(tr["id"])
        if n:
            tr["blocks"].append({"kind": "subagent", "n": n})
    return {"meta": meta, "turns": turns}


# --- Codex -------------------------------------------------------------------

def _codex_tool(item: dict, name: str, inp: dict, text: str = "", limit: int = 4000) -> dict:
    """Bloque tool a partir de un item de Codex: falla si status != completed."""
    failed = item.get("status") not in (None, "completed")
    return {"kind": "tool", "id": item.get("id"), "name": name, "input": inp,
            "result": {"text": _short(text or "", limit), "is_error": failed}}


def parse_codex(path: str, max_bytes: int = TAIL_BYTES) -> dict:
    lines, truncated = tail_lines(path, max_bytes)
    if truncated:
        # session_meta es siempre la linea 1 y se pierde con la cola: leerla aparte
        try:
            with open(path, "rb") as f:
                first = f.readline().decode("utf-8", errors="replace")
            if '"session_meta"' in first:
                lines.insert(0, first)
        except OSError:
            pass
    meta = {"agent": "codex", "title": None, "branch": None, "cwd": None, "version": None,
            "truncated": truncated, "originator": None, "source": None, "imported": False}
    turns: list[dict] = []
    by_id: dict[str, dict] = {}
    cur: dict | None = None

    def turn_for(tid, ts):
        nonlocal cur
        if tid and tid in by_id:
            cur = by_id[tid]
        elif tid:
            cur = _new_turn("codex", tid, ts)
            by_id[tid] = cur
            turns.append(cur)
        elif cur is None:
            cur = _new_turn("codex", "parcial", ts, "(turno anterior al corte)")
            turns.append(cur)
        cur["ts_end"] = ts or cur["ts_end"]
        return cur

    for d in iter_json(lines):
        t = d.get("type")
        p = d.get("payload") or {}
        ts = d.get("timestamp")
        if t == "session_meta":
            meta["cwd"] = p.get("cwd")
            meta["originator"] = p.get("originator")
            meta["source"] = p.get("source")
            meta["version"] = p.get("cli_version")
            meta["branch"] = (p.get("git") or {}).get("branch")
            continue
        if t == "turn_context":
            if p.get("cwd"):
                meta["cwd"] = p["cwd"]
            continue
        if t != "event_msg":
            continue
        pt = p.get("type")
        tid = p.get("turn_id")
        if isinstance(tid, str) and tid.startswith("external-import"):
            meta["imported"] = True

        if pt == "task_started":
            turn_for(tid, ts)
        elif pt == "item_completed":
            turn = turn_for(tid, ts)
            item = p.get("item") or {}
            it = item.get("type")
            if it == "UserMessage":
                set_prompt(turn, _content_text(item.get("content")))
            elif it == "AgentMessage":
                add_text(turn, _content_text(item.get("content")), item.get("phase"))
            elif it == "Reasoning":
                text = "\n".join(item.get("summary_text") or [])
                if text:
                    turn["blocks"].append({"kind": "thinking", "text": text})
            elif it == "CommandExecution":
                parsed = item.get("parsed_cmd") or []
                cmd = " ; ".join(c.get("cmd", "") for c in parsed if c.get("cmd")) or " ".join(item.get("command") or [])
                blk = _codex_tool(item, "shell", {"command": cmd, "cwd": item.get("cwd")},
                                  item.get("stdout") or item.get("stderr") or "")
                code = item.get("exit_code")
                if isinstance(code, int) and code != 0:
                    blk["result"]["is_error"] = True
                turn["blocks"].append(blk)
            elif it == "FileChange":
                changes = item.get("changes") or {}
                paths = [{"path": k, "type": (v or {}).get("type")} for k, v in changes.items()]
                turn["blocks"].append(_codex_tool(item, "apply_patch", {"paths": paths},
                                                  item.get("stdout") or item.get("stderr") or "", 2000))
            elif it == "McpToolCall":
                # {server, tool, arguments, status, result: {content: [{type: "text", text}]}, error?}
                name = "/".join(x for x in (item.get("server"), item.get("tool")) if x) or "mcp"
                res = item.get("result")
                text = _content_text(res.get("content")) if isinstance(res, dict) else ""
                err = item.get("error")
                if err and not text:
                    text = err.get("message") if isinstance(err, dict) else str(err)
                turn["blocks"].append(_codex_tool(item, name, item.get("arguments") or {}, text))
            elif it == "ImageView":
                turn["blocks"].append(_codex_tool(item, "view_image", {"path": item.get("path")}))
            elif it == "ContextCompaction":
                turn["blocks"].append({"kind": "user_text", "text": "(compactación)"})
            elif it == "Extension":     # web.search y similares: se cuentan, sin bloque
                turn["extensions"] += 1
        elif pt == "user_message":      # forma vieja / importada
            set_prompt(turn_for(tid, ts), p.get("message", ""))
        elif pt == "agent_message":
            add_text(turn_for(tid, ts), p.get("message", ""), p.get("phase"))
        elif pt == "task_complete":
            turn = turn_for(tid, ts)
            turn["ended"] = True
            if p.get("last_agent_message"):
                turn["final"] = p["last_agent_message"]
            err = p.get("error")
            if err:
                turn["error"] = err.get("message") if isinstance(err, dict) else str(err)
        elif pt == "turn_aborted":
            turn = turn_for(tid, ts)
            turn["ended"] = True
            turn["error"] = f"turno abortado ({p.get('reason')})"
        elif pt == "token_count":
            if cur is not None:
                cur["usage"] = (p.get("info") or {}).get("total_token_usage") or p.get("info")

    return {"meta": meta, "turns": turns}


def codex_title(thread_id: str) -> str | None:
    """Ultimo thread_name de ~/.codex/session_index.jsonl para ese hilo."""
    idx = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".codex", "session_index.jsonl")
    if not os.path.exists(idx):
        return None
    name = None
    try:
        lines, _ = tail_lines(idx, 512 * 1024)
        for d in iter_json(lines):
            if d.get("id") == thread_id and d.get("thread_name"):
                name = d["thread_name"]
    except OSError:
        return None
    return name


# --- API comun -----------------------------------------------------------------

def parse(agent: str, path: str, max_bytes: int = TAIL_BYTES) -> dict:
    return parse_codex(path, max_bytes) if agent == "codex" else parse_claude(path, max_bytes)


def turns(agent: str, path: str, n: int = 10, before: str | None = None, max_bytes: int = TAIL_BYTES) -> dict:
    """Ultimos n turnos (o los n anteriores a `before`)."""
    r = parse(agent, path, max_bytes)
    ts = r["turns"]
    if before:
        ids = [t["id"] for t in ts]
        if before in ids:
            ts = ts[: ids.index(before)]
    page = ts[-n:] if n else ts
    return {"meta": r["meta"], "turns": page, "has_more": len(ts) > len(page)}


def digest_turn(turn: dict) -> dict:
    files, commands, errors, questions, reads = [], [], [], [], 0
    peers: list[str] = []
    if turn.get("from_peer"):
        body = (turn.get("prompt") or "").split(": ", 1)[-1]
        peers.append(f"← {turn['from_peer']}: {_first_line(body, 100)}")
    subagents = 0
    for b in turn["blocks"]:
        k = b["kind"]
        if k == "subagent":
            subagents += b.get("n", 0)
            continue
        if k != "tool":
            continue
        name, inp, res = b.get("name"), b.get("input") or {}, b.get("result")
        if name in FILE_TOOLS:
            if "paths" in inp:
                files.extend(f"{p.get('type', '')} {p.get('path', '')}".strip() for p in inp["paths"])
            else:
                fp = inp.get("file_path") or inp.get("notebook_path")
                if fp:
                    files.append(fp)
        elif name in SHELL_TOOLS:
            cmd = inp.get("command") or inp.get("cmd") or ""
            if cmd:
                commands.append(_first_line(cmd))
        elif name in READ_TOOLS:
            reads += 1
        elif name == "AskUserQuestion":
            for q in inp.get("questions") or []:
                if isinstance(q, dict) and q.get("question"):
                    questions.append(q["question"])
        elif name in ("SendMessage", "ListAgents"):
            # canal nativo Claude<->Claude: a quien le hablo
            to = inp.get("to") or inp.get("recipient")
            if to:
                peers.append(f"→ {to}: {_first_line(str(inp.get('message') or inp.get('content') or ''), 100)}")
            elif name == "ListAgents":
                peers.append("ListAgents")
        if res and res.get("is_error"):
            errors.append(f"{name}: {_first_line(res.get('text', ''))}")
    final = (turn.get("final") or "").strip()
    if final.endswith("?") and not questions:
        questions.append(_short(final.split("\n")[-1], 200))
    if turn.get("error"):
        errors.append(turn["error"])
    # dedupe conservando orden
    files = list(dict.fromkeys(files))
    return {
        "id": turn["id"], "ts_start": turn.get("ts_start"), "ts_end": turn.get("ts_end"),
        "ended": turn.get("ended"),
        "prompt": turn.get("prompt", ""),
        "final": _short(final, 600),
        "files": files, "commands": commands[:20], "errors": errors[:10],
        "questions": questions, "peers": peers[:10], "reads": reads, "subagents": subagents,
        "extensions": turn.get("extensions", 0),
        "tools": sum(1 for b in turn["blocks"] if b["kind"] == "tool"),
    }


def digest(agent: str, path: str, n: int = 10, max_bytes: int = TAIL_BYTES) -> dict:
    r = turns(agent, path, n, None, max_bytes)
    return {"meta": r["meta"], "turns": [digest_turn(t) for t in r["turns"]], "has_more": r["has_more"]}


if __name__ == "__main__":
    import sys
    agent, path = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    out = digest(agent, path, n)
    print(json.dumps(out["meta"], ensure_ascii=False))
    for t in out["turns"]:
        print("---", t["id"], t["ts_start"], "ended" if t["ended"] else "abierto")
        print("  pedido:", _short(t["prompt"], 120))
        print("  final :", _short(t["final"], 160))
        for k in ("files", "commands", "errors", "questions"):
            if t[k]:
                print(f"  {k}:", t[k][:6])
        print(f"  tools={t['tools']} reads={t['reads']} subagentes={t['subagents']}")
