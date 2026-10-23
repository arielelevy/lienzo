"""Z2: entrega intercalada en Codex y reconstrucción del estado desde su rollout."""

import datetime as dt
import hashlib

import hooks_eventos
import pytest
import sessions as ses


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.UTC).isoformat()


@pytest.fixture
def card(monkeypatch):
    s = ses.new_session("Z2-24968", "codex", "sweep")
    s.update(
        alive=True,
        state="termino",
        state_since=iso(130),
        sent_mark=ses.prompt_mark("pedido enviado"),
        envio_pendiente={"at": 110},
        envio_codex={
            "at": 110,
            "envio_id": "Z2-send",
            "estado": "encolado",
            "transporte": "tecleo",
            "prompt_sha256": hashlib.sha256(b"pedido enviado").hexdigest(),
        },
    )
    monkeypatch.setattr(hooks_eventos.time, "time", lambda: 140)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    monkeypatch.setattr(ses, "en_hilo", lambda *a, **kw: None)
    monkeypatch.setattr(ses.captura, "pedido", lambda *a, **kw: None)
    return s


@pytest.mark.parametrize("hooked", [False, True])
@pytest.mark.parametrize("prompt", ["pedido enviado", "pedido original\npedido enviado\nmensaje intercalado"])
def test_codex_input_after_send_confirms_even_inside_same_task(card, hooked, prompt):
    card["hooked"] = hooked
    turn = {"ts_start": iso(90), "prompt_ts": iso(111), "prompt": prompt, "ended": True, "ts_end": iso(130)}
    (ses.apply_turn_hooked if hooked else ses.apply_turn_unhooked)(card, turn)
    assert card["envio_codex"]["estado"] == "entregado"
    assert card["envio_codex"]["confirmacion_final"] is True
    assert card["sent_mark"] is None and card["envio_pendiente"] is None
    assert not hooks_eventos.envio_sin_confirmar(card, 200)


def test_timeout_does_not_report_failure_after_observed_prompt(card):
    card["prompt_ts"] = iso(120)
    assert hooks_eventos.envio_sin_confirmar(card, 200)
    assert card["envio_codex"]["estado"] == "entregado"
    assert card["needs"] is None


@pytest.mark.parametrize("hooked", [False, True])
@pytest.mark.parametrize("trigger", ["ended", "ttl"])
def test_old_notice_restores_real_phase_even_when_input_precedes_notice(card, hooked, trigger):
    card.update(state="te_necesita", needs={"kind": "sin_enviar", "since": iso(140)})
    card["envio_codex"]["at"] = 120  # no confirma: se prueba cierre/TTL de forma independiente
    turn = {
        "ts_start": iso(90),
        "prompt_ts": iso(111),
        "prompt": "pedido combinado",
        "ended": True,
        "ts_end": iso(150 if trigger == "ended" else 130),
    }
    monkey_time = 321 if trigger == "ttl" else 151
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(hooks_eventos.time, "time", lambda: monkey_time)
        (ses.apply_turn_hooked if hooked else ses.apply_turn_unhooked)(card, turn)
    assert card["needs"] is None
    assert card["state"] == "termino"


@pytest.mark.parametrize("at", [None, True, "110", float("nan"), float("inf"), float("-inf"), 120])
def test_invalid_or_later_receipt_not_confirmed(card, at):
    card["envio_codex"]["at"] = at
    assert not hooks_eventos.confirmar_codex_desde_turno(card, {"prompt": "pedido", "prompt_ts": iso(111)})
    assert card["envio_codex"]["estado"] == "encolado"


def test_receipt_only_change_is_published(card):
    parsed = {"meta": {}, "title": None, "turns": [{"prompt": "pedido", "prompt_ts": iso(111), "ended": False}]}
    ses.apply_transcript(card, parsed)
    card["envio_codex"].update(estado="sin_confirmacion", confirmacion_final=False)
    assert ses.apply_transcript(card, parsed) is True
    assert card["envio_codex"]["estado"] == "entregado"
    assert ses.apply_transcript(card, parsed) is False


@pytest.mark.parametrize("kind", ["permission", "question", "denied"])
def test_real_blocking_notice_not_expired(card, kind):
    card.update(state="te_necesita", needs={"kind": kind, "since": iso(1)})
    ses.apply_turn_unhooked(card, {"prompt": "posterior", "prompt_ts": iso(120), "ended": True, "ts_end": iso(500)})
    assert card["needs"]["kind"] == kind and card["state"] == "te_necesita"


def test_expired_notice_forces_reconstruction_without_file_growth(card, tmp_path, monkeypatch):
    path = tmp_path / "Z2-24968.jsonl"
    path.write_text("fixture parsed explicitly", encoding="utf-8")
    card.update(transcript_path=str(path), state="te_necesita", needs={"kind": "sin_enviar", "since": iso(1)})
    stat = path.stat()
    monkeypatch.setattr(hooks_eventos.time, "time", lambda: 300)
    monkeypatch.setattr(ses, "sessions", {card["session_id"]: card})
    monkeypatch.setattr(ses, "transcript_stat", {card["session_id"]: (stat.st_size, int(stat.st_mtime))})
    monkeypatch.setattr(ses, "refresh_alive", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_pantalla", lambda s: False)
    monkeypatch.setattr(ses, "coda_mirar_fondo", lambda s: None)
    monkeypatch.setattr(
        ses,
        "read_transcript",
        lambda s: {
            "meta": {},
            "title": None,
            "turns": [
                {"prompt": "pedido", "prompt_ts": iso(90), "ts_start": iso(90), "ts_end": iso(130), "ended": True}
            ],
        },
    )
    monkeypatch.setattr(ses.state, "broadcast", lambda event: None)
    ses.check_liveness(card["session_id"])
    assert card["state"] == "termino" and card["needs"] is None
