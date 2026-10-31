"""Encargo G (2026-10-30): un informe rechazado sin teclear nada se vuelve a mandar."""

import rules as rl
import state
from test_backlog_b_informes import entorno  # noqa: F401


def test_informe_rechazado_por_nombre_nativo_se_reenvia(entorno, monkeypatch):  # noqa: F811
    # 18 informes de openSeec quedaron con un intento y el 409 de «se está actualizando el nombre nativo»:
    # ese 409 sale antes de teclear, pero el informe se trataba como envío incierto y no salía más
    r, sends = entorno
    respuestas = [
        (409, {"ok": False, "code": "native_sync_busy", "no_enviado": True, "error": "nombre nativo"}),
        (200, {"estado": "entregado", "envio_id": "1"}),
    ]
    monkeypatch.setattr(rl, "send_to_session", lambda dst, text, att: (sends.append(text), respuestas.pop(0))[1])
    rl.fire_on_stop(r["from"])
    informe = r["informes"][0]
    assert (informe["estado"], informe["intentos"]) == ("pendiente", 0)
    r.pop("last_fired", None)
    r["recent_fires"] = []
    assert rl.recuperar_informes() == [r]
    rl.fire_rule(r)
    rl._on_stop_en_vuelo.clear()
    assert informe["estado"] == "entregado" and len(sends) == 2


def test_informe_incierto_sigue_sin_reenviarse(entorno, monkeypatch):  # noqa: F811
    r, sends = entorno
    monkeypatch.setattr(rl, "send_to_session", lambda dst, text, att: (409, {"ok": False, "error": "otra cosa"}))
    rl.fire_on_stop(r["from"])
    r.pop("last_fired", None)
    r["recent_fires"] = []
    assert r["informes"][0]["intentos"] == 1 and rl.recuperar_informes() == []
    assert state.rules.items[0] is r


def test_mismo_informe_a_otro_pedido_no_se_entrega_dos_veces(entorno):  # noqa: F811
    # openSeec F, 2026-10-30: el informe salió a las 22:38:11; un «no respondas» de la coordinadora cerró otro
    # turno con la misma respuesta y salió de nuevo a las 22:38:57 (la huella lleva el pedido)
    r, sends = entorno
    src = state.sessions[r["from"]]
    src["last_reply"] = "ESTADO: entregado - informe F"
    rl.fire_on_stop(r["from"])
    assert len(sends) == 1
    src["prompt_id"] = "p2"
    r.pop("last_fired", None)
    r["recent_fires"] = []
    rl.fire_on_stop(r["from"])
    assert len(sends) == 1 and "ya se entregó" in r["last_result"]
