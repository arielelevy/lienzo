"""Criterio E: entrega, persistencia y recordatorio sin acuse; sin consolas reales."""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
import rules as rl
import state

pytest_plugins = ["test_backlog_b_informes"]


@pytest.mark.parametrize("estado", ["corriendo", "termino"])
def test_intermedia_final_y_recarga(entorno, estado):
    r, sends = entorno
    state.sessions[r["to"]]["state"] = estado
    src = state.sessions[r["from"]]
    src["last_reply"] = "Sigo verificando"
    rl.fire_on_stop(r["from"])
    assert not sends and not r.get("informes")
    src["last_reply"] = "ESTADO: final verificado"
    rl.fire_on_stop(r["from"])
    state.rules.load(lambda _: True)
    loaded = state.rules.items[0]
    assert len(loaded["informes"]) == 1
    assert loaded["informes"][0]["estado"] == "entregado"
    assert rl.recuperar_informes() == []
    rl.fire_on_stop(r["from"])
    assert len(sends) == 1


def test_dos_frentes_a_misma_coordinadora(entorno):
    r, sends = entorno
    otro = {**r, "id": "encargo-E-otro", "from": "encargo-E-src"}
    state.rules.items.append(otro)
    state.sessions[otro["from"]] = {**state.sessions[r["from"]], "session_id": otro["from"]}
    try:
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(rl.fire_on_stop, [r["from"], otro["from"]]))
        state.rules.load(lambda _: True)
        assert len(sends) == 2
        assert all(len(x["informes"]) == 1 for x in state.rules.items)
        assert rl.recuperar_informes() == []
    finally:
        state.sessions.pop(otro["from"])


def entregado(entorno):
    r, sends = entorno
    rl.fire_on_stop(r["from"])
    i = r["informes"][0]
    i["entregado_at"] = "2026-10-24T00:00:00+00:00"
    sends.clear()
    return r, i, sends


@pytest.mark.parametrize("estado", ["corriendo", "te_necesita", "muerta"])
def test_no_despierta_coordinadora_no_quieta(entorno, estado):
    r, _, sends = entregado(entorno)
    state.sessions[r["to"]]["state"] = estado
    rl.recordar_informes(dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC))
    assert sends == []


def test_recordatorio_limite_unico_persistido_y_sin_bucle(entorno):
    r, i, sends = entregado(entorno)
    inicio = dt.datetime(2026, 10, 24, tzinfo=dt.UTC)
    rl.recordar_informes(inicio + dt.timedelta(seconds=state.INFORME_SIN_ACUSE_S - 1))
    assert not sends
    rl.recordar_informes(inicio + dt.timedelta(seconds=state.INFORME_SIN_ACUSE_S))
    assert len(sends) == 1
    assert r["from"] in sends[0] and "integra" in sends[0] and "bloqueo" in sends[0]
    assert f"/rules/{r['id']}/informes/{i['id']}/acuse" in sends[0]
    assert state.sessions[r["to"]]["sin_aviso"]["a"] == r["from"]
    state.rules.load(lambda _: True)
    rl.recordar_informes(inicio + dt.timedelta(hours=2))
    assert len(sends) == 1
    # El turno creado por el recordatorio no devuelve una on_stop al frente.
    dst = state.sessions[r["to"]]
    dst.update(last_prompt=sends[0], last_reply="ESTADO: integrado", prompt_id="recordatorio")
    inversa = {**r, "id": "encargo-E-inversa", "from": r["to"], "to": r["from"], "informes": []}
    state.rules.items[:] = [inversa]
    rl.fire_on_stop(r["to"])
    assert len(sends) == 1 and "sin_aviso" in inversa["last_result"]


@pytest.mark.parametrize("estado", ["pendiente", "recibido", "integrado"])
def test_solo_entregado_sin_acuse(entorno, estado):
    _, i, sends = entregado(entorno)
    i["estado"] = estado
    rl.recordar_informes(dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC))
    assert not sends


def test_fallo_persistencia_impide_recordatorio(entorno, monkeypatch):
    _, _, sends = entregado(entorno)
    monkeypatch.setattr(state.rules, "save", lambda **kwargs: False)
    rl.recordar_informes(dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC))
    assert not sends


def test_transporte_falla_no_reintenta_y_conserva_informe(entorno, monkeypatch):
    r, i, _ = entregado(entorno)
    calls = []

    def fallar(*args):
        calls.append(args)
        return 409, {"error": "destino ocupado"}

    monkeypatch.setattr(rl, "send_to_session", fallar)
    t = dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC)
    rl.recordar_informes(t)
    state.rules.load(lambda _: True)
    rl.recordar_informes(t)
    assert len(calls) == 1 and i["estado"] == "entregado"
    assert i["recordatorio_resultado"]["codigo"] == 409
    assert not state.sessions[r["to"]].get("sin_aviso")


def test_recordatorio_remoto_reenvia_sin_aviso(entorno, monkeypatch):
    import server

    r, _, _ = entregado(entorno)
    monkeypatch.setattr(server, "_route_session", lambda _: (None, "pc-remota"))
    calls = []

    def forward(*args):
        calls.append(args)
        return 200, {"estado": "entregado"}

    monkeypatch.setattr(server.mirror.MIRROR, "forward", forward)
    rl.recordar_informes(dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC))
    assert len(calls) == 1
    assert calls[0][2] == f"/sessions/{r['to']}/send"
    assert calls[0][3]["sin_aviso"] is True
    assert calls[0][3]["from"] == r["from"]


def test_recordatorios_concurrentes_no_duplican(entorno):
    _, _, sends = entregado(entorno)
    t = dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(rl.recordar_informes, [t, t]))
    assert len(sends) == 1
