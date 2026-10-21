"""On-demand SQLite history. No cache, lifecycle changes or completion inference."""

import sqlite3
import time
from pathlib import Path

import antigravity_codec as codec
import antigravity_identity as identity

MAX_STEPS = 512
MAX_TOTAL_BLOB = 4 * 1024 * 1024
READ_SECONDS = 0.25
NOTE = "Historial parcial de SQLite. Fin de turno sin confirmar; no incluye razonamiento ni argumentos o resultados de herramientas."
CODEC_CONTRACT = "agy-1.4.3-gemini_coder.Step-visible-v1"


class StoreError(ValueError):
    pass


def _rows(proof):
    if identity.file_token(proof.database) != proof.database_token:
        raise StoreError("database_rotated")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(proof.database) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            identity.file_token(sidecar)
    # mode=ro retains SQLite's WAL snapshot semantics; immutable would lose live WAL.
    con = sqlite3.connect(proof.database.as_uri() + "?mode=ro", uri=True, timeout=0.1)
    try:
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * codec.MAX_BLOB + 4096)
        deadline = time.monotonic() + READ_SECONDS
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("BEGIN")
        # Views/triggers must not supply history from a different source.
        tables = dict(con.execute("SELECT name,type FROM sqlite_schema WHERE name IN ('steps','trajectory_meta')"))
        if tables != {"steps": "table", "trajectory_meta": "table"}:
            raise StoreError("unsupported_schema")
        cascades = con.execute("SELECT cascade_id FROM trajectory_meta LIMIT 2").fetchall()
        if cascades != [(proof.cascade,)]:
            raise StoreError("cascade_mismatch")
        sizes = con.execute(
            "SELECT idx,length(metadata),length(step_payload) FROM steps ORDER BY idx DESC LIMIT ?",
            (MAX_STEPS + 1,),
        ).fetchall()
        truncated = len(sizes) > MAX_STEPS
        sizes = sizes[:MAX_STEPS]
        if any(
            type(idx) is not int
            or idx < 0
            or type(a) is not int
            or type(b) is not int
            or not 0 <= a <= codec.MAX_BLOB
            or not 0 <= b <= codec.MAX_BLOB
            for idx, a, b in sizes
        ):
            raise StoreError("blob_limit")
        if sum(a + b for _, a, b in sizes) > MAX_TOTAL_BLOB:
            raise StoreError("total_blob_limit")
        rows = con.execute(
            "SELECT idx,step_type,status,step_format,metadata,step_payload FROM steps ORDER BY idx DESC LIMIT ?",
            (MAX_STEPS,),
        ).fetchall()
        if len({row[0] for row in rows}) != len(rows):
            raise StoreError("duplicate_step")
        decoded = [codec.decode_step(*row) for row in reversed(rows)]
        if time.monotonic() > deadline:
            raise StoreError("read_timeout")
        return decoded, truncated
    finally:
        con.close()


def _turns(rows, cascade):
    result, by_execution = [], {}
    for row in rows:
        execution = row["execution"]
        if execution not in by_execution:
            turn = {
                "id": f"{cascade}:{execution}",
                "agent": "antigravity",
                "ts_start": row["ts"],
                "ts_end": None,
                "prompt": "",
                "blocks": [],
                "final": "",
                "ended": False,
                "history_only": True,
                "error": None,
                "usage": None,
                "extensions": 0,
            }
            by_execution[execution] = turn
            result.append(turn)
        turn = by_execution[execution]
        if row["prompt"]:
            turn["prompt"] = "\n".join(filter(None, (turn["prompt"], row["prompt"])))
        if row["text"]:
            turn["blocks"].append({"kind": "text", "text": row["text"], "phase": "history"})
            turn["final"] = row["text"]
        if row["tool"]:
            turn["blocks"].append(
                {"kind": "tool", "id": str(row["idx"]), "name": row["tool"], "input": {}, "result": None}
            )
    return result


def history(session, n=10, before=None):
    """Fail closed, including after the read; never return a partially decoded history."""
    try:
        if type(n) is not int or not 1 <= n <= 50:
            raise StoreError("invalid_page_size")
        proof = identity.resolve(session)
        rows, truncated = _rows(proof)
        if proof != identity.resolve(session):
            raise StoreError("identity_changed")
        turns = _turns(rows, proof.cascade)
        if before is not None:
            matches = [i for i, turn in enumerate(turns) if turn["id"] == before]
            if len(matches) != 1:
                raise StoreError("cursor_outside_window")
            turns = turns[: matches[0]]
        return {
            "meta": {
                "agent": "antigravity",
                "source": "sqlite_protobuf",
                "history_only": True,
                "identity_source": "native_presence_pid_creation",
                "codec_contract": CODEC_CONTRACT,
                "executable_sha256": identity.SUPPORTED_EXE_SHA256,
                "truncated": truncated,
                "limit_steps": MAX_STEPS,
            },
            "turns": turns[-n:],
            "has_more": len(turns) > n,
            "note": NOTE,
        }
    except (identity.IdentityError, codec.CodecError, StoreError) as exc:
        code = str(exc)
    except OSError, sqlite3.Error, OverflowError:
        # SQLite/OS messages may contain paths or data: never expose or log them.
        code = "storage_unavailable"
    return {
        "meta": {"agent": "antigravity", "history_only": True, "error": code},
        "turns": [],
        "has_more": False,
        "note": "Historial no disponible: " + code + ". Fin de turno sin confirmar.",
    }
