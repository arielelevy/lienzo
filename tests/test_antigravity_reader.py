"""Synthetic contracts. No agy launch, send, live account or completion claims."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import antigravity_codec as codec
import antigravity_identity as identity
import antigravity_store as store
import pytest

CASCADE = "751aecc3-a2f6-474e-8029-ef5191048f81"
EXEC = "551ea4e6-21f8-4257-aafc-a5f20376001d"
STARTED = "2026-10-20T21:40:20.185745+00:00"
SESSION = {"agent": "antigravity", "pid": 20088, "started": STARTED}


def vi(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def f(number, value):
    if isinstance(value, int):
        return vi(number << 3) + vi(value)
    if isinstance(value, str):
        value = value.encode()
    return vi((number << 3) | 2) + vi(len(value)) + value


def row(idx=0, kind=14, text="hola", extra=b"", execution=EXEC, status=3):
    metadata = f(12, execution) + f(1, f(1, 1792540000))
    nested = f(19 if kind == 14 else 20, f(1, text) + extra) if kind in (14, 15) else b""
    payload = f(1, kind) + f(4, status) + f(5, metadata) + nested
    return idx, kind, status, 0, metadata, payload


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / (CASCADE + ".db")
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE trajectory_meta(cascade_id TEXT); CREATE TABLE steps(idx INTEGER PRIMARY KEY, step_type INTEGER,status INTEGER,step_format INTEGER,metadata BLOB,step_payload BLOB);"
    )
    con.execute("INSERT INTO trajectory_meta VALUES (?)", (CASCADE,))
    con.executemany("INSERT INTO steps VALUES (?,?,?,?,?,?)", [row(), row(1, 15, "respuesta")])
    con.commit()
    con.close()
    proof = identity.Identity(20088, 123, "agy.exe", CASCADE, path, (1, 2), identity.file_token(path))
    monkeypatch.setattr(identity, "resolve", lambda _: proof)
    return path, proof


def test_visible_allowlist_and_redaction():
    data = row(
        0, 15, "token=abcdef123456", f(3, "PRIVATE_THINKING") + f(16, "PRIVATE_RAW") + f(7, f(3, "PRIVATE_ARGS"))
    )
    decoded = codec.decode_step(*data)
    exported = json.dumps(decoded)
    assert "abcdef123456" not in exported
    assert "PRIVATE" not in exported


@pytest.mark.parametrize(
    "blob", [b"\x00", b"\x0a\x05a", b"\x08" + b"\xff" * 10, b"\x0b", b"\x0dabc", b"\x09abc", b"\x80", b"\x08\x01" * 513]
)
def test_malformed_wire(blob):
    with pytest.raises(codec.CodecError):
        codec.fields(blob)


def test_duplicate_sensitive_field_rejected():
    r = list(row())
    r[-1] += f(19, f(1, "second"))
    with pytest.raises(codec.CodecError, match="ambiguous_field"):
        codec.decode_step(*r)


@pytest.mark.parametrize("change", ["format", "type", "metadata", "execution"])
def test_unknown_contract_fails_closed(change):
    r = list(row(execution="invalid" if change == "execution" else EXEC))
    if change == "format":
        r[3] = 1
    elif change == "type":
        r[1] = 999
    elif change == "metadata":
        r[4] = b""
    with pytest.raises(codec.CodecError):
        codec.decode_step(*r)


def test_history_never_certifies_completion(database):
    result = store.history(SESSION)
    assert result["meta"]["source"] == "sqlite_protobuf"
    assert len(result["turns"]) == 1
    turn = result["turns"][0]
    assert turn["prompt"] == "hola" and turn["final"] == "respuesta"
    assert turn["history_only"] and not turn["ended"] and turn["ts_end"] is None
    assert SESSION == {"agent": "antigravity", "pid": 20088, "started": STARTED}


def test_wal_uncheckpointed_and_same_index_update(database):
    path, _ = database
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE steps SET metadata=?,step_payload=? WHERE idx=1", row(1, 15, "WAL_VISIBLE")[4:])
        writer.commit()
        assert Path(str(path) + "-wal").stat().st_size > 0
        assert store.history(SESSION)["turns"][0]["final"] == "WAL_VISIBLE"
        writer.execute("UPDATE steps SET metadata=?,step_payload=? WHERE idx=1", row(1, 15, "SAME_INDEX_UPDATED")[4:])
        writer.commit()
        assert store.history(SESSION)["turns"][0]["final"] == "SAME_INDEX_UPDATED"


def test_query_only_mode(database, monkeypatch):
    original = sqlite3.connect
    seen = []

    def connect(database_uri, **kwargs):
        assert database_uri.endswith("?mode=ro") and "immutable" not in database_uri
        con = original(database_uri, **kwargs)
        con.set_trace_callback(seen.append)
        return con

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert store.history(SESSION)["turns"]
    assert "PRAGMA query_only=ON" in seen
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in seen)


@pytest.mark.parametrize("change", ["pid", "started", "cascade", "lock_token", "database_token"])
def test_post_read_identity_rotation_rejects_all(database, monkeypatch, change):
    _, proof = database
    values = {"pid": 42, "started": 999, "cascade": EXEC, "lock_token": (3, 4), "database_token": (5, 6)}
    proofs = iter([proof, replace(proof, **{change: values[change]})])
    monkeypatch.setattr(identity, "resolve", lambda _: next(proofs))
    result = store.history(SESSION)
    assert not result["turns"] and result["meta"]["error"] == "identity_changed"


def test_bad_cursor_and_cascade(database):
    path, _ = database
    assert store.history(SESSION, before="missing")["meta"]["error"] == "cursor_outside_window"
    with sqlite3.connect(path) as con:
        con.execute("UPDATE trajectory_meta SET cascade_id=?", (EXEC,))
    assert store.history(SESSION)["meta"]["error"] == "cascade_mismatch"


def test_blob_bound_before_decode(database):
    path, _ = database
    with sqlite3.connect(path) as con:
        con.execute("UPDATE steps SET step_payload=? WHERE idx=1", (b"x" * (codec.MAX_BLOB + 1),))
    assert store.history(SESSION)["meta"]["error"] == "blob_limit"


def test_truncated_window_explicit(database, monkeypatch):
    monkeypatch.setattr(store, "MAX_STEPS", 1)
    result = store.history(SESSION)
    assert result["meta"]["truncated"] and not result["turns"][0]["prompt"]


def test_sqlite_error_does_not_expose_details(database, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("PRIVATE_SECRET")

    monkeypatch.setattr(sqlite3, "connect", fail)
    result = store.history(SESSION)
    assert "PRIVATE_SECRET" not in json.dumps(result) and not result["turns"]


@pytest.mark.parametrize(
    "image_name,accepted",
    [
        ("agy.exe", True),
        ("agy.exe.1792586409122112700.old", True),
        ("agy.exe.old", False),
        ("agy.exe.123.old.exe", False),
        ("agy.exe.other.old", False),
        ("agy.exe.123.old/agy.exe", False),
        ("../other/agy.exe", False),
        ("agy.exe.123456789012345678901.old", False),
    ],
)
def test_identity_ownership_ambiguity_rotation_and_pid_reuse(tmp_path, monkeypatch, image_name, accepted):
    checked_images = []
    monkeypatch.setattr(identity, "_compatible_executable", checked_images.append)
    (tmp_path / "presence").mkdir()
    (tmp_path / "conversations").mkdir()
    (tmp_path / "presence" / (CASCADE + ".lock")).touch()
    (tmp_path / "conversations" / (CASCADE + ".db")).touch()

    class Probe:
        owners_value: ClassVar = {20088}
        start = identity._start_microseconds(STARTED) * 10

        def __init__(self, pid):
            assert pid == 20088

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def process(self):
            return self.start, str((Path.home() / "AppData/Local/agy/bin" / image_name).resolve())

        def owners(self, path):
            return self.owners_value

    if not accepted:
        with pytest.raises(identity.IdentityError, match="process_identity_mismatch"):
            identity.resolve(SESSION, root=tmp_path, probe_factory=Probe)
        assert checked_images == []
        return
    assert identity.resolve(SESSION, root=tmp_path, probe_factory=Probe).cascade == CASCADE
    assert checked_images == [str((Path.home() / "AppData/Local/agy/bin" / image_name).resolve())]
    Probe.start += 10
    with pytest.raises(identity.IdentityError, match="process_identity_mismatch"):
        identity.resolve(SESSION, root=tmp_path, probe_factory=Probe)
    Probe.start -= 10
    Probe.owners_value = {20088, 99}
    with pytest.raises(identity.IdentityError, match="ambiguous_owners"):
        identity.resolve(SESSION, root=tmp_path, probe_factory=Probe)
    Probe.owners_value = set()
    with pytest.raises(identity.IdentityError, match="missing_presence"):
        identity.resolve(SESSION, root=tmp_path, probe_factory=Probe)
    Probe.owners_value = {20088}
    (tmp_path / "presence" / (EXEC + ".lock")).touch()
    with pytest.raises(identity.IdentityError, match="ambiguous_conversation"):
        identity.resolve(SESSION, root=tmp_path, probe_factory=Probe)


@pytest.mark.parametrize("n", ["x", "0", "51", "-1"])
def test_api_invalid_pagination(n):
    import server

    assert server.session_view_response(SESSION, "turns", {"n": [n]})[0] == 400


def test_api_digest_preserves_unknown_end(database):
    import server

    status, result = server.session_view_response(SESSION, "digest", {})
    assert status == 200 and result["turns"][0]["history_only"]
    assert result["turns"][0]["final"] == "respuesta" and not result["turns"][0]["ended"]


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12])
def test_synthetic_status_transitions_do_not_end_turn(status):
    # Synthetic only: these states have NOT been observed live by this integration.
    decoded = codec.decode_step(*row(status=status))
    assert not store._turns([decoded], CASCADE)[0]["ended"]


@pytest.mark.parametrize("name", ["agy.exe", "agy.exe.1792586409122112700.old"])
def test_executable_upgrade_unknown_closed(tmp_path, monkeypatch, name):
    import hashlib

    exe = tmp_path / name
    exe.write_bytes(b"synthetic known executable")
    monkeypatch.setattr(identity, "SUPPORTED_EXE_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest())
    identity._compatible_executable(str(exe))
    exe.write_bytes(b"synthetic upgrade")
    with pytest.raises(identity.IdentityError, match="unsupported_executable"):
        identity._compatible_executable(str(exe))


def test_executable_replacement_during_fingerprint_closed(tmp_path, monkeypatch):
    exe = tmp_path / "agy.exe"
    exe.write_bytes(b"synthetic")
    tokens = iter([(1, 1), (1, 2)])
    monkeypatch.setattr(identity, "file_token", lambda _: next(tokens))
    with pytest.raises(identity.IdentityError, match="unsupported_executable"):
        identity._compatible_executable(str(exe))


def test_redirected_ancestor_closed(tmp_path, monkeypatch):
    path = tmp_path / "presence.lock"
    path.touch()
    # Synthetic junction resolution: Windows junction creation can require privileges.
    original = Path.resolve
    monkeypatch.setattr(
        Path, "resolve", lambda self, **kw: tmp_path / "redirect" / self.name if self == path else original(self, **kw)
    )
    with pytest.raises(identity.IdentityError, match="redirected_path"):
        identity.file_token(path)


@pytest.mark.parametrize("n", [0, -1, 51, "10", None])
def test_store_page_size_closed(n):
    assert store.history(SESSION, n)["meta"]["error"] == "invalid_page_size"


def test_database_file_id_replaced_before_open(database, monkeypatch):
    monkeypatch.setattr(identity, "file_token", lambda _: (0, 0))
    assert store.history(SESSION)["meta"]["error"] == "database_rotated"


def test_total_blob_limit(database, monkeypatch):
    monkeypatch.setattr(store, "MAX_TOTAL_BLOB", 1)
    assert store.history(SESSION)["meta"]["error"] == "total_blob_limit"


def test_read_timeout_closed(database, monkeypatch):
    monkeypatch.setattr(store, "READ_SECONDS", -1)
    result = store.history(SESSION)
    assert not result["turns"] and result["meta"]["error"] in ("read_timeout", "storage_unavailable")


def test_null_blob_closed(database):
    with sqlite3.connect(database[0]) as con:
        con.execute("UPDATE steps SET metadata=NULL WHERE idx=1")
    assert store.history(SESSION)["meta"]["error"] == "blob_limit"
