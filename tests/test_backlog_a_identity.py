"""P0: no encolar a un hilo inferido del PID/cwd. Sin CLI ni mensajes externos."""

import json

import agentes
import codex_queue as cq
import pytest

REAL_PROBE = cq.codex_identity.probe


@pytest.fixture
def cli(tmp_path, monkeypatch):
    rollout = tmp_path / "old.jsonl"
    rollout.write_text("", encoding="utf-8")
    monkeypatch.setattr(cq, "codex_exe", lambda: "codex.exe")
    monkeypatch.setattr(cq.procinfo, "alive", lambda pid: True)
    monkeypatch.setattr(cq.codex_identity, "probe", lambda pid: {"verified": False, "reason": "sin prueba actual"})
    monkeypatch.setattr(cq, "store_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(cq.subproc, "correr", lambda *a, **kw: pytest.fail("no debe encolar"))
    return {"agent": "codex", "pid": 4242, "cwd": str(tmp_path),
                "session_id": "01a14774-aa3f-7062-b3f3-aa996a33ff35", "transcript_path": str(rollout)}


@pytest.mark.parametrize("transition", ["/new", "/clear", "pid-reciclado", "exec-paralelo"])
def test_live_pid_is_not_current_thread_evidence(cli, transition):
    # Misma tarjeta persistida en las cuatro situaciones: liveness no las distingue.
    snapshot = dict(cli)
    result = cq.enviar(cli, transition, esperar=0)
    assert result["estado"] == "rechazado"
    assert "identidad de hilo CLI sin verificar" in result["motivo"]
    assert cli == snapshot
    assert not cq.store_path().exists()


def test_two_clis_and_newer_exec_rollout_in_same_repo_do_not_select_a_thread(cli, tmp_path):
    newest = tmp_path / "newest.jsonl"
    newest.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "01a14a6b-1acc-7db2-9dbb-b7faf4033e22", "cwd": cli["cwd"], "originator": "codex_exec"}}),
        encoding="utf-8")
    other = {**cli, "pid": 4243, "session_id": "01a14a6b-1acc-7db2-9dbb-b7faf4033e22",
             "transcript_path": str(newest)}
    for card in (cli, other):
        assert cq.puede_enviar(card)["puede"] is False
        assert cq.enviar(card, "mensaje", esperar=0)["estado"] == "rechazado"


def test_uncertain_old_send_is_preserved_without_replay(cli):
    record = {"estado": "sin_confirmacion", "at": 1, "thread": cli["session_id"],
                  "rollout": cli["transcript_path"], "sha256": cq._sha("mensaje"), "desde": cq._iso(1)}
    cq._save({"old": record})
    before = cq.store_path().read_bytes()
    assert cq.enviar(cli, "mensaje", {"envio_id": "old"}, esperar=0)["estado"] == "rechazado"
    assert cq.store_path().read_bytes() == before
    assert cq.confirmar("old")["estado"] == "sin_confirmacion"
    assert cq._load()["old"]["thread"] == cli["session_id"]


def test_desktop_keeps_its_existing_contract(cli, monkeypatch):
    card = {**cli, "pid": None, "external": {"kind": "codex-desktop", "via": "rollout"}}
    monkeypatch.setattr(cq, "app_running", lambda: True)
    assert cq.puede_enviar(card)["transporte"] == "codex_queue"
    monkeypatch.setattr(cq, "app_running", lambda: False)
    assert cq.puede_enviar(card)["puede"] is False


def test_measured_identity_allows_cli_but_rejects_recycled_pid_and_new_thread(cli, monkeypatch):
    proof = {"verified": True, "pid": cli["pid"], "process_start": 123,
                 "thread": cli["session_id"], "path": cli["transcript_path"]}
    monkeypatch.setattr(cq.codex_identity, "probe", lambda pid: proof)
    cli["codex_process_start"] = 123
    assert cq.puede_enviar(cli)["puede"] is True
    proof["process_start"] = 124
    assert "PID reciclado" in cq.puede_enviar(cli)["motivo"]
    proof["process_start"] = 123
    proof["thread"] = "01a14a6b-1acc-7db2-9dbb-b7faf4033e22"
    assert "otro rollout activo" in cq.puede_enviar(cli)["motivo"]


def test_discovery_never_assigns_previous_rollout_by_120s_margin(cli, tmp_path, monkeypatch):
    assert agentes.guess_codex(cli["cwd"], 0, str(tmp_path)) == (None, None)
    assert agentes.perfil("codex").guess(cli["cwd"], None, str(tmp_path)) == (None, None)
    proof = {"verified": True, "thread": cli["session_id"], "path": cli["transcript_path"]}
    monkeypatch.setattr(cq.codex_identity, "probe", lambda pid: proof)
    assert agentes.perfil("codex").identity({"pid": cli["pid"]}, {}) == (cli["session_id"], cli["transcript_path"])


@pytest.mark.parametrize("paths", [set(), {"old", "new"}])
def test_handle_probe_rejects_missing_or_multiple_rollouts(monkeypatch, paths):
    monkeypatch.setattr(cq.procinfo, "_WIN", True)
    monkeypatch.setattr(cq.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(cq.codex_identity, "_snapshot", lambda pid: (123, paths))
    assert REAL_PROBE(1)["verified"] is False


def test_two_measured_clis_same_cwd_remain_distinct(cli, tmp_path, monkeypatch):
    other_path = tmp_path / "rollout-other.jsonl"
    other_path.write_text("", encoding="utf-8")
    other = {**cli, "pid": 4243, "session_id": "01a14a6b-1acc-7db2-9dbb-b7faf4033e22",
             "transcript_path": str(other_path), "codex_process_start": 124}
    cli["codex_process_start"] = 123
    proofs = {s["pid"]: {"verified": True, "process_start": s["codex_process_start"],
                             "thread": s["session_id"], "path": s["transcript_path"]} for s in (cli, other)}
    monkeypatch.setattr(cq.codex_identity, "probe", proofs.__getitem__)
    assert cq.puede_enviar(cli)["puede"]
    assert cq.puede_enviar(other)["puede"]
    assert not cq.puede_enviar({**cli, "pid": other["pid"]})["puede"]


@pytest.mark.parametrize("header", [[], {"type": "session_meta", "payload": {}},
    {"type": "session_meta", "payload": {"id": "x", "originator": "codex_exec"}}])
def test_probe_rejects_malformed_or_exec_headers(cli, monkeypatch, header):
    from pathlib import Path

    Path(cli["transcript_path"]).write_text(json.dumps(header), encoding="utf-8")
    monkeypatch.setattr(cq.procinfo, "_WIN", True)
    monkeypatch.setattr(cq.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(cq.codex_identity, "_snapshot", lambda pid: (123, {cli["transcript_path"]}))
    assert REAL_PROBE(cli["pid"])["verified"] is False
