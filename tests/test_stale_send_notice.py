"""A stale send notice can clear after later user input without confirming delivery.
No real process, model, console, transcript or session is contacted.
"""

import copy
import datetime as dt
import hashlib
import json

import pytest
import sessions as ses
import transcripts


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.UTC).isoformat()


@pytest.fixture
def card(monkeypatch):
    row = ses.new_session("stale-send-fixture", "codex", "sweep")
    row.update(
        state="te_necesita", alive=True,
        needs={"kind": "sin_enviar", "since": iso(100), "detail": "pedido anterior"},
        envio_codex={"envio_id": "later", "at": 110, "estado": "entregado", "confirmacion_final": True,
                     "transporte": "tecleo", "prompt_sha256": hashlib.sha256(b"nuevo pedido").hexdigest()},
        last_reply="revisión terminada",
    )
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses, "en_hilo", lambda *a, **k: None)
    monkeypatch.setattr(ses.captura, "pedido", lambda *a, **k: None)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("notice repair must not replay console input"))
    monkeypatch.setattr(ses.codex_queue, "enviar", lambda *a, **k: pytest.fail("notice repair must not enqueue"))
    return row


def test_later_confirmed_delivery_clears_only_stale_notice_without_claiming_turn_end(card):
    receipt = copy.deepcopy(card["envio_codex"])
    assert ses.clear_stale_send_notice(card) is True
    assert card["needs"] is None
    assert card["envio_codex"] == receipt
    assert card["state"] == "te_necesita"  # a receipt alone is not proof of the execution phase
    assert ses.clear_stale_send_notice(card) is False


def test_reported_card_uses_notice_offset_and_original_send_timestamp(card):
    card["needs"]["since"] = "2026-10-18T11:47:43.553-03:00"
    card["envio_codex"].update(envio_id="df66b2f1382606928efebdf4", at=1792334976.2462003)
    assert ses.clear_stale_send_notice(card) is True
    assert card["needs"] is None


@pytest.mark.parametrize("changes", [{"alive": False}, {"state": "muerta"}, {"agent": "claude"}])
def test_dead_or_non_codex_card_is_not_changed(card, changes):
    card.update(changes)
    before = copy.deepcopy(card)
    assert ses.clear_stale_send_notice(card) is False
    assert card == before


@pytest.mark.parametrize("kind", ["permission", "question", "denied", "idle"])
def test_real_permission_or_question_is_preserved(card, kind):
    card["needs"]["kind"] = kind
    before = copy.deepcopy(card)
    assert ses.clear_stale_send_notice(card) is False
    assert card == before


def test_pending_permission_is_preserved_even_if_notice_shape_is_stale(card):
    card["pending_id"] = "actual-permission"
    before = copy.deepcopy(card)
    assert ses.clear_stale_send_notice(card) is False
    assert card == before


@pytest.mark.parametrize("sent_at", [99, 100])
def test_failure_newer_than_or_equal_to_receipt_is_preserved(card, sent_at):
    card["envio_codex"]["at"] = sent_at
    before = copy.deepcopy(card)
    assert ses.clear_stale_send_notice(card) is False
    assert card == before


@pytest.mark.parametrize("changes", [
    {"estado": "encolado"}, {"estado": "sin_confirmacion"}, {"estado": "rechazado"},
    {"confirmacion_final": False}, {"envio_id": None}, {"at": None}, {"at": True},
    {"at": "110"}, {"at": float("nan")}, {"at": float("inf")},
])
def test_uncertain_or_invalid_receipt_does_not_clear_notice(card, changes):
    card["envio_codex"].update(changes)
    notice = copy.deepcopy(card["needs"])
    assert ses.clear_stale_send_notice(card) is False
    assert card["needs"] == notice


@pytest.mark.parametrize("since", [None, "invalid"])
def test_notice_without_valid_time_is_preserved(card, since):
    card["needs"]["since"] = since
    assert ses.clear_stale_send_notice(card) is False
    assert card["needs"] is not None


@pytest.mark.parametrize("ended,phase", [(False, "corriendo"), (True, "termino")])
def test_exact_new_user_turn_clears_old_notice_and_uses_real_turn_phase(card, ended, phase):
    card["envio_codex"].update(estado="encolado", confirmacion_final=False)
    card["sent_mark"] = ses.prompt_mark("nuevo pedido")
    card["envio_pendiente"] = {"at": 110}
    ses.apply_turn_unhooked(card, {"id": "new", "prompt": "nuevo pedido", "ts_start": iso(111), "ended": ended})
    assert card["envio_codex"]["estado"] == "entregado"
    assert card["needs"] is None and card["state"] == phase
    assert card["sent_mark"] is None and card["envio_pendiente"] is None


def test_same_prefix_different_full_hash_never_confirms_or_clears(card):
    requested, received = "x" * 125 + " original", "x" * 125 + " diferente"
    card["envio_codex"].update(estado="encolado", confirmacion_final=False,
                             prompt_sha256=hashlib.sha256(requested.encode()).hexdigest())
    card["sent_mark"] = ses.prompt_mark(requested)
    card["needs"]["since"] = iso(112)  # este fallo es posterior al turno leído
    ses.apply_turn_unhooked(card, {"id": "new", "prompt": received, "ts_start": iso(111), "ended": False})
    assert card["envio_codex"]["estado"] == "encolado"
    assert card["needs"]["kind"] == "sin_enviar"


@pytest.mark.parametrize("hooked", [False, True])
@pytest.mark.parametrize("ended,phase", [(False, "corriendo"), (True, "termino")])
def test_later_user_input_clears_old_notice_without_confirming_unmatched_send(card, hooked, ended, phase):
    card["envio_codex"].update(estado="encolado", confirmacion_final=False)
    receipt = copy.deepcopy(card["envio_codex"])
    card["sent_mark"] = ses.prompt_mark("texto que no coincide")
    turn = {"id": "later", "ts_start": iso(90), "prompt_ts": iso(120),
            "prompt": "te apruebo el baseline\npushea\narreglá ese aviso", "ended": ended}
    (ses.apply_turn_hooked if hooked else ses.apply_turn_unhooked)(card, turn)
    assert card["needs"] is None and card["state"] == phase
    assert card["envio_codex"] == receipt
    assert card["sent_mark"] == ses.prompt_mark("texto que no coincide")


@pytest.mark.parametrize("entered", [None, "invalid", iso(99), iso(100)])
def test_old_or_unverifiable_input_does_not_clear_unconfirmed_notice(card, entered):
    card["envio_codex"].update(estado="sin_confirmacion", confirmacion_final=False)
    assert not ses.clear_stale_send_notice(card, {"prompt": "pedido", "prompt_ts": entered, "ts_start": iso(120)})
    assert card["needs"]["kind"] == "sin_enviar"


@pytest.mark.parametrize("prompt", ["", "(turno anterior al corte)", "<system-reminder>recordatorio</system-reminder>"])
def test_background_or_missing_prompt_does_not_clear_notice(card, prompt):
    card["envio_codex"].update(estado="sin_confirmacion", confirmacion_final=False)
    assert not ses.clear_stale_send_notice(card, {"prompt": prompt, "prompt_ts": iso(120)})


@pytest.mark.parametrize("kind", ["permission", "question", "denied", "idle"])
def test_later_input_does_not_clear_a_different_kind_of_notice(card, kind):
    card["needs"]["kind"] = kind
    assert not ses.clear_stale_send_notice(card, {"prompt": "nuevo pedido", "prompt_ts": iso(120)})


def test_later_input_does_not_clear_pending_permission(card):
    card["pending_id"] = "permission-still-open"
    assert not ses.clear_stale_send_notice(card, {"prompt": "nuevo pedido", "prompt_ts": iso(120)})


@pytest.mark.parametrize("legacy", [False, True])
def test_codex_uses_timestamp_of_last_human_input_not_later_tools(tmp_path, legacy):
    def event(at, **payload):
        return {"timestamp": iso(at), "type": "event_msg", "payload": {"turn_id": "same-turn", **payload}}

    def user(at, text):
        if legacy:
            return event(at, type="user_message", message=text)
        return event(at, type="item_completed", item={"type": "UserMessage", "content": [{"text": text}]})

    rows = [event(90, type="task_started"), user(95, "pedido anterior"),
            user(120, "arreglá ese aviso"), user(130, "<system-reminder>recordatorio</system-reminder>"),
            event(150, type="agent_message", message="sigo trabajando")]
    path = tmp_path / "merged.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    turn = transcripts.parse_codex(str(path))["turns"][-1]
    assert turn["ts_start"] == iso(90) and turn["prompt_ts"] == iso(120) and turn["ts_end"] == iso(150)
    assert "pedido anterior\narreglá ese aviso" in turn["prompt"]


def test_refresh_publishes_notice_only_change_even_when_already_running(card):
    card["envio_codex"].update(estado="encolado", confirmacion_final=False)
    receipt = copy.deepcopy(card["envio_codex"])
    notice = copy.deepcopy(card["needs"])
    card.update(state="corriendo", needs=None)
    parsed = {"meta": {}, "title": None, "turns": [
        {"id": "current", "prompt": "pedido posterior", "prompt_ts": iso(120), "ended": False}]}
    ses.apply_transcript(card, parsed)
    card["needs"] = notice
    assert ses.apply_transcript(card, parsed) is True
    assert card["needs"] is None and card["state"] == "corriendo"
    assert card["envio_codex"] == receipt
    assert ses.apply_transcript(card, parsed) is False


def test_unconfirmed_send_after_later_input_never_recreates_enter_warning(card):
    card.update(state="termino", state_since=iso(130), needs=None, prompt_ts=iso(120),
                sent_mark="unmatched", envio_pendiente={"at": 110})
    card["envio_codex"].update(estado="encolado", confirmacion_final=False)
    assert ses.envio_sin_confirmar(card, 200) is True
    assert card["needs"] is None and card["state"] == "termino"
    assert card["envio_codex"]["estado"] == "sin_confirmacion"
    assert card["envio_codex"]["confirmacion_final"] is False
    assert card["envio_pendiente"] is None


@pytest.mark.parametrize("kind", ["permission", "question", "denied"])
def test_old_send_timeout_never_replaces_a_real_blocking_notice(card, kind):
    card.update(state_since=iso(100), sent_mark="unmatched", envio_pendiente={"at": 110})
    card["needs"]["kind"] = kind
    before = copy.deepcopy(card)
    assert ses.envio_sin_confirmar(card, 200) is False
    assert card == before


def test_old_send_timeout_never_replaces_a_pending_permission(card):
    card.update(state_since=iso(100), sent_mark="unmatched", envio_pendiente={"at": 110},
                pending_id="still-open")
    before = copy.deepcopy(card)
    assert ses.envio_sin_confirmar(card, 200) is False
    assert card == before


def test_liveness_reads_later_input_before_expiring_old_send(card, tmp_path, monkeypatch):
    transcript = tmp_path / "later.jsonl"
    transcript.write_text("synthetic transcript", encoding="utf-8")
    card.update(transcript_path=str(transcript), hooked=False, state_since=iso(100),
                sent_mark="unmatched", envio_pendiente={"at": 110})
    card["envio_codex"].update(estado="encolado", confirmacion_final=False)
    monkeypatch.setattr(ses, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(ses, "transcript_stat", {})
    monkeypatch.setattr(ses, "refresh_alive", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_pantalla", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_fondo", lambda s: None)
    monkeypatch.setattr(ses, "read_transcript", lambda s: {"meta": {}, "title": None, "turns": [
        {"id": "new", "prompt": "pedido nuevo combinado", "prompt_ts": iso(120), "ended": False}]})
    monkeypatch.setattr(ses.state, "broadcast", lambda event: None)
    ses.check_liveness(card["session_id"])
    assert card["needs"] is None and card["state"] == "corriendo"
    assert ses.parse_ts(card["prompt_ts"]) == ses.parse_ts(iso(120))
    assert card["envio_codex"]["confirmacion_final"] is False


@pytest.mark.parametrize("ended,phase", [(False, "corriendo"), (True, "termino")])
@pytest.mark.parametrize("hooked", [False, True])
def test_liveness_repairs_loaded_card_without_transcript_growth(card, tmp_path, monkeypatch, ended, phase, hooked):
    transcript = tmp_path / "already-read.jsonl"
    transcript.write_text("synthetic, parsed by the explicit read_transcript double")
    card["transcript_path"] = str(transcript)
    card["hooked"] = hooked
    stat = transcript.stat()
    monkeypatch.setattr(ses, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(ses, "transcript_stat", {card["session_id"]: (stat.st_size, int(stat.st_mtime))})
    monkeypatch.setattr(ses, "refresh_alive", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_pantalla", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_fondo", lambda s: None)
    reads, published = [], []
    monkeypatch.setattr(ses, "read_transcript", lambda s: reads.append(s["session_id"]) or {"ended": ended})

    def apply(s, turn):
        (ses.apply_turn_hooked if hooked else ses.apply_turn_unhooked)(s, turn)
        return True

    monkeypatch.setattr(ses, "apply_transcript", apply)
    monkeypatch.setattr(ses.state, "broadcast", published.append)
    ses.check_liveness(card["session_id"])
    assert reads == [card["session_id"]]
    assert card["needs"] is None and card["state"] == phase
    assert published[-1]["type"] == "transcript"
