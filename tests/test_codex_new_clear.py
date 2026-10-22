"""Secuencia real del 2026-10-22 (PID 35236): /new y /clear en la misma TUI.

El proceso conserva abierto el rollout anterior: los handles solos nunca eligen el hilo nuevo,
lo vincula el nombre único del pie, y queue sigue rechazando una CLI en cada paso.
"""

import json
import os

import codex_identity as identity
import codex_observation as observation
import codex_queue
import pytest

A = "01a16197-8978-77a0-b8df-6edb31ba1a0e"
B = "01a16199-0952-7e22-ad20-3020b2dc399b"
START = 134371122827676006
READ_FOOTER = observation._footer  # conftest lo anula en cada prueba


@pytest.fixture
def tui(tmp_path, monkeypatch):
    """Una TUI Codex simulada: rollouts abiertos por handles y pie visible, cambiables por paso."""
    rollouts = {}
    for thread in (A, B):
        path = tmp_path / f"rollout-{thread}.jsonl"
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": thread, "originator": "codex-tui"}}) + "\n",
            encoding="utf-8",
        )
        rollouts[thread] = str(path)
    view = {"open": {rollouts[A]}, "footer": (str(tmp_path), "Responder uno"), "names": {A: "Responder uno"}}
    monkeypatch.setattr(identity.procinfo, "_WIN", True)
    monkeypatch.setattr(identity.procinfo, "process_agent", lambda pid: "codex")
    monkeypatch.setattr(identity, "_snapshot", lambda pid, observation=False: (START, set(view["open"])))
    monkeypatch.setattr(observation.procs, "creation_filetime", lambda pid: START)
    monkeypatch.setattr(observation, "_footer", lambda pid: view["footer"])

    def lookup(name):
        return [(t, str(tmp_path)) for t, n in view["names"].items() if n == name]

    class Con:
        def execute(self, sql, args):
            return type("R", (), {"fetchall": lambda _self: lookup(args[0])})()

        def close(self):
            pass

    (tmp_path / "state_5.sqlite").write_bytes(b"")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(observation.sqlite3, "connect", lambda *a, **kw: Con())
    monkeypatch.setattr(observation.codex_status, "rollout", lambda sid, home=None: rollouts.get(sid))
    import codex_status

    monkeypatch.setattr(codex_status, "discover", lambda pid: None)  # /status ya se consultó al lanzar
    monkeypatch.setattr(codex_queue, "codex_exe", lambda: "C:/codex.exe")
    monkeypatch.setattr(codex_queue.procinfo, "alive", lambda pid: True)
    return view, rollouts, tmp_path


def card(thread, rollouts):
    return {"agent": "codex", "session_id": thread, "transcript_path": rollouts[thread], "pid": 35236}


def test_new_keeps_old_handle_and_the_footer_binds_the_new_thread(tui):
    view, rollouts, folder = tui
    assert identity.transcript_identity(35236)["thread"] == A
    # /new: hilo nuevo sin rollout todavía y pie sin nombre; el handle de A sigue abierto.
    view["footer"] = None
    stale = identity.transcript_identity(35236)
    assert stale["thread"] == A and not stale["verified"]  # sólo lectura; la consola ya es del hilo nuevo
    # Primer turno del hilo nuevo: dos rollouts abiertos y el pie con su nombre.
    view["open"] = {rollouts[A], rollouts[B]}
    view["names"][B] = "Responder dos"
    view["footer"] = (str(folder), "Responder dos")
    proof = identity.transcript_identity(35236)
    assert (proof["thread"], proof["path"], proof["verified"]) == (B, rollouts[B], False)
    assert proof["process_start"] == START


def test_two_open_rollouts_without_a_unique_name_do_not_pick_the_newest(tui):
    view, rollouts, folder = tui
    view["open"] = {rollouts[A], rollouts[B]}
    view["names"][B] = "Responder uno"  # mismo nombre visible que el hilo anterior
    proof = identity.transcript_identity(35236)
    assert not proof.get("observed") and proof.get("thread") is None


@pytest.mark.parametrize("step", ["antes", "new-sin-rollout", "despues"])
def test_queue_rejects_the_cli_at_every_step_with_a_reason(tui, step):
    view, rollouts, folder = tui
    thread = A
    if step != "antes":
        view["footer"] = None
    if step == "despues":
        view["open"] = {rollouts[A], rollouts[B]}
        view["names"][B] = "Responder dos"
        view["footer"] = (str(folder), "Responder dos")
        thread = B
    plan = codex_queue.puede_enviar(card(thread, rollouts))
    assert not plan["puede"] and plan["motivo"].startswith("identidad de hilo CLI sin verificar")
    stale = codex_queue.puede_enviar(card(A, rollouts))
    assert not stale["puede"]  # el hilo viejo tampoco, ni con su rollout existente


def test_enviar_never_calls_codex_for_the_old_thread(tui, monkeypatch):
    view, rollouts, folder = tui
    view["open"] = {rollouts[A], rollouts[B]}
    calls = []
    monkeypatch.setattr(codex_queue.subproc, "correr", lambda *a, **kw: calls.append(a) or (0, "", ""))
    monkeypatch.setattr(codex_queue.state, "LIENZO", str(folder))
    result = codex_queue.enviar(card(A, rollouts), "hola", esperar=0)
    assert result["estado"] == "rechazado" and result["motivo"] and calls == []
    assert not os.path.exists(codex_queue.store_path())  # un rechazo previo no reserva nada


def test_footer_reader_forces_utf8_output(monkeypatch):
    """Server lanzado sin lienzo-server.cmd: screen.py imprimía en cp1252 y un «⚠» del pie lo rompía."""
    seen = {}

    def correr(argv, **kw):
        seen.update(kw)
        return 1, "", ""

    monkeypatch.setattr(observation.subproc, "correr", correr)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    READ_FOOTER(42)
    assert (seen.get("env") or {}).get("PYTHONIOENCODING") == "utf-8"
