"""Desktop registry identity must win over the generic headless command fallback."""
import json

import procs
import pytest


@pytest.mark.parametrize("filetime,entrypoint,expected", [
    (134367270783194266, "claude-desktop", "claude-desktop"),
    (134367270783194267, "claude-desktop", "batch"),
    (None, "claude-desktop", "batch"),
    (134367270783194266, "cli", "batch"),
], ids=["matching-identity", "recycled-pid", "unverified-process", "real-batch"])
def test_row_registry_priority_requires_verified_process(tmp_path, monkeypatch, filetime, entrypoint, expected):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    folder = tmp_path / "sessions"
    folder.mkdir()
    (folder / "45392.json").write_text(json.dumps({
        "pid": 45392, "sessionId": "0e35e62f-b3cd-4c1c-9fef-40903126964d",
        "procStart": "134367270783194266", "entrypoint": entrypoint,
        "kind": "interactive", "name": "Verified Desktop", "status": "idle",
    }), encoding="utf-8")
    monkeypatch.setattr(procs, "creation_filetime", lambda pid: filetime)
    row = {"pid": 45392, "exe": "C:/tools/claude.exe", "parent": "pwsh.exe",
           "cmd": "claude.exe -p --input-format stream-json --output-format stream-json"}
    assert procs.external_of_row(row)["kind"] == expected
    monkeypatch.setattr(procs.subproc, "correr", lambda *a, **k: (0, json.dumps([row]), ""))
    (observed,) = procs.sweep()
    assert observed["external"]["kind"] == expected
