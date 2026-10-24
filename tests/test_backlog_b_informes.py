"""Continuidad B: transporte simulado, estado real serializado, sin sesiones pagas."""

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import entregas_informes as ledger
import pytest
import rules as rl
import rules_api as api
import state


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl, "ON_STOP_SETTLE_S", 0)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    monkeypatch.setattr(rl, "find_session", lambda sid: state.sessions.get(sid))
    monkeypatch.setattr(rl, "full_reply", lambda s, cap=6000: s.get("last_reply", "")[:cap])
    state.sessions["backlog-b-src"] = {
        "session_id": "backlog-b-src",
        "agent": "codex",
        "state": "termino",
        "last_reply": "ESTADO: informe uno",
        "prompt_id": "p1",
    }
    state.sessions["backlog-b-dst"] = {"session_id": "backlog-b-dst", "agent": "codex", "state": "termino"}
    r = {
        "id": "backlog-b",
        "kind": "on_stop",
        "from": "backlog-b-src",
        "to": "backlog-b-dst",
        "text": "{regla_id}/{informe_id}\n{respuesta}",
        "enabled": True,
        "repeat": True,
        "limit": "rate",
        "solo_si": "ESTADO:",
    }
    state.rules.items.append(r)
    sends = []

    def send(dst, text, attachments):
        sends.append(text)
        return 200, {"estado": "entregado", "envio_id": str(len(sends))}

    monkeypatch.setattr(rl, "send_to_session", send)
    # Los recordatorios usan el router de producción; sólo se sustituye el teclado.
    import preguntas
    import server

    monkeypatch.setattr(server, "send_to_session", lambda *a: rl.send_to_session(*a))
    monkeypatch.setattr(server, "_route_session", lambda sid: (state.sessions.get(sid), None))
    monkeypatch.setattr(
        preguntas, "enviar", lambda sid, body: server.atender_accion("POST", sid, "send", body, desde_tablero=True)
    )
    yield r, sends
    state.sessions.pop("backlog-b-src", None)
    state.sessions.pop("backlog-b-dst", None)
    rl._on_stop_en_vuelo.clear()
    rl._fotos.clear()


@pytest.mark.parametrize("ocupada", [False, True])
def test_final_intermedia_y_acuses(entorno, ocupada):
    r, sends = entorno
    state.sessions[r["to"]]["state"] = "corriendo" if ocupada else "termino"
    src = state.sessions[r["from"]]
    src["last_reply"] = "Sigo investigando"
    rl.fire_on_stop(r["from"])
    assert not sends and not r.get("informes")
    src["last_reply"] = "ESTADO: informe final"
    rl.fire_on_stop(r["from"])
    informe = r["informes"][0]
    assert len(sends) == 1 and informe["estado"] == "entregado"
    assert informe["id"] in sends[0]
    assert api.acuse_informe(r["id"], informe["id"], {"estado": "integrado", "session_id": r["to"]})[0] == 409
    for estado in ("recibido", "integrado", "recibido"):
        assert api.acuse_informe(r["id"], informe["id"], {"estado": estado, "session_id": r["to"]})[0] == 200
    assert informe["estado"] == "integrado"
    rl.fire_on_stop(r["from"])
    assert len(sends) == 1


def test_dos_informes_diferidos_reinicio(entorno):
    r, sends = entorno
    ahora = dt.datetime.now().astimezone()
    with state.lock:
        for h in ("uno", "dos"):
            rl._diferir(r, ahora, "ocupada", {"texto": "ESTADO: " + h, "huella": h})
        state.rules.save(strict=True)
    disk = json.loads(Path(state.rules.path).read_text(encoding="utf-8"))
    state.rules.items[:] = disk
    r = state.rules.items[0]
    assert [x["id"] for x in r["informes"]] == ["uno", "dos"]
    for paso in range(2):
        due = rl.entregas_diferidas(ahora + dt.timedelta(hours=paso + 1))
        assert len(due) == 1
        rl.fire_rule(due[0][0], due[0][1])
        rl._on_stop_en_vuelo.clear()
        r.pop("last_fired", None)
        r["recent_fires"] = []
    assert len(sends) == 2 and "ESTADO: uno" in sends[0] and "ESTADO: dos" in sends[1]
    assert not r["deferred"]


def test_recupera_sin_intento_no_reenvia_incierto(entorno, monkeypatch):
    r, sends = entorno
    ledger.conservar(r, {"texto": "ESTADO: persistido", "huella": "persistido"}, state.now())
    state.rules.save(strict=True)
    state.rules.items[:] = json.loads(Path(state.rules.path).read_text(encoding="utf-8"))
    r = state.rules.items[0]
    monkeypatch.setattr(rl, "send_to_session", lambda *args: (200, {"estado": "encolado", "envio_id": "q1"}))
    assert rl.recuperar_informes() == [r]
    rl.fire_rule(r)
    rl._on_stop_en_vuelo.clear()
    assert r["informes"][0]["estado"] == "pendiente"
    assert rl.recuperar_informes() == []
    assert r["informes"][0]["respuesta"] == "ESTADO: persistido"


def test_disco_falla_no_envia(entorno, monkeypatch):
    r, sends = entorno
    monkeypatch.setattr(state.rules, "save", lambda **kwargs: False)
    with pytest.raises(OSError, match="conservar"):
        rl.fire_on_stop(r["from"])
    assert not sends


def test_acuse_invalido_no_muta(entorno):
    r, _ = entorno
    i = ledger.conservar(r, {"texto": "ESTADO: prueba", "huella": "x"}, state.now())
    assert ledger.acusar(r, "x", "recibido", "intruso", state.now())[0] == 403
    assert ledger.acusar(r, "x", "inventado", r["to"], state.now())[0] == 400
    assert ledger.acusar(r, "ausente", "recibido", r["to"], state.now())[0] == 404
    assert i["estado"] == "pendiente"


def test_stop_simultaneo_no_duplica(entorno):
    r, sends = entorno
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(rl.fire_on_stop, [r["from"], r["from"]]))
    assert len(sends) == 1
    assert len(r["informes"]) == 1


def test_confirmacion_tardia_no_revierte_acuses(entorno):
    r, _ = entorno
    i = ledger.conservar(r, {"texto": "ESTADO: listo", "huella": "tardia"}, state.now())
    ledger.resultado(i, 200, {"estado": "encolado", "envio_id": "q2"}, state.now())
    assert ledger.confirmar_envio(r, "q2", {"estado": "entregado", "envio_id": "q2"}, state.now())
    assert i["estado"] == "entregado"
    ledger.acusar(r, "tardia", "recibido", r["to"], state.now())
    ledger.acusar(r, "tardia", "integrado", r["to"], state.now())
    ledger.resultado(i, 200, {"estado": "encolado", "envio_id": "q2"}, state.now())
    assert i["estado"] == "integrado"
    assert not ledger.confirmar_envio(r, "otro", {}, state.now())


def test_recupera_informe_sin_tarjeta_origen(entorno):
    r, sends = entorno
    ledger.conservar(r, {"texto": "ESTADO: fuente cerrada", "huella": "sin-src"}, state.now())
    state.sessions.pop(r["from"])
    assert rl.recuperar_informes() == [r]
    rl.fire_rule(r)
    assert "ESTADO: fuente cerrada" in sends[0]


def test_conserva_informe_largo_antes_del_recorte(entorno):
    r, sends = entorno
    texto = "ESTADO: " + "a" * 10000
    state.sessions[r["from"]]["last_reply"] = texto
    rl.fire_on_stop(r["from"])
    assert r["informes"][0]["respuesta"] == texto
    assert len(sends[0]) < len(texto)


def test_purga_federada_conserva_pendientes(entorno):
    r, _ = entorno
    r.update(xpc=True, parked_to=r["to"], parked_since="2020-01-01T00:00:00+00:00")
    i = ledger.conservar(r, {"texto": "ESTADO: retenido", "huella": "retencion"}, state.now())
    rl.purge_stale_xpc(lambda sid: False, lambda sid: False)
    assert r in state.rules.items and i["estado"] == "pendiente"
    i["estado"] = "integrado"
    rl.purge_stale_xpc(lambda sid: False, lambda sid: False)
    assert r not in state.rules.items


def test_acuse_disco_fallido_no_cambia_estado(entorno, monkeypatch):
    r, _ = entorno
    ledger.conservar(r, {"texto": "ESTADO: retenido", "huella": "sin-disco"}, state.now())

    def falla(**kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(state.rules, "save", falla)
    with pytest.raises(OSError, match="disco lleno"):
        api.acuse_informe(r["id"], "sin-disco", {"estado": "recibido", "session_id": r["to"]})
    assert r["informes"][0]["estado"] == "pendiente"
