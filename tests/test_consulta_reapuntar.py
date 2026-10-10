"""Una tarjeta que cambia de id (la provisoria `pid-N` al llegar su primer hook) sigue en su consulta:
consulta.reapuntar la traslada y la vigilancia ya no la saca por muerta (Teorema, 2026-10-10)."""

import consulta
import pytest
import state as st

A, P, R, U = "A" * 8, "pid-1096", "R" * 8, "01a1272c-ed42-70a1-b06e-546a228fb59e"


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setattr(consulta, "DIR", str(tmp_path / "consultas"))
    monkeypatch.setattr(consulta, "CONSULTAS", {})
    monkeypatch.setattr(consulta, "_ultima_vigilancia", 0.0)
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    tarjetas = {
        A: {"session_id": A, "agent": "claude", "model": "opus", "state": "termino", "alive": True},
        P: {"session_id": P, "agent": "codex", "model": "", "state": "termino", "alive": True},
        R: {"session_id": R, "agent": "claude", "model": "", "state": "termino", "alive": True},
    }
    monkeypatch.setattr(consulta, "enviar", lambda sid, texto, de, cid: (200, {"ok": True}))
    monkeypatch.setattr(consulta, "tarjeta", lambda sid: tarjetas.get(sid))
    return tarjetas


def test_el_cambio_de_id_no_es_muerte(mundo):
    code, out = consulta.abrir({"pregunta": "¿P = NP?", "investigadores": [A, P], "revisor": R})
    assert code == 200
    cid = out["id"]
    # el primer hook: la provisoria se va del tablero y aparece la tarjeta con su id real
    mundo[U] = {**mundo.pop(P), "session_id": U}
    assert consulta.reapuntar(P, U) == 1
    consulta.vigilar(ahora=1e12)
    c = consulta.ver(cid)
    assert c["estado"] == "abierta" and c["fuera"] == {}
    assert c["investigadores"] == [A, U] and U in c["pendientes"] and U in c["nombres"]
    assert P not in c["pendientes"] and P not in c["nombres"]


def test_sin_reapuntar_la_vigilancia_la_saca(mundo):
    """El comportamiento de antes, para que la prueba de arriba mida algo."""
    code, out = consulta.abrir({"pregunta": "¿P = NP?", "investigadores": [A, P], "revisor": R})
    mundo.pop(P)
    consulta.vigilar(ahora=1e12)
    assert consulta.ver(out["id"])["estado"] == "cancelada"


def test_no_toca_consultas_cerradas_ni_ajenas(mundo):
    code, out = consulta.abrir({"pregunta": "¿P = NP?", "investigadores": [A, P], "revisor": R})
    with consulta.lock:
        consulta.CONSULTAS[out["id"]]["estado"] = "cerrada"
    assert consulta.reapuntar(P, U) == 0
    assert consulta.reapuntar("otro", U) == 0
    assert consulta.ver(out["id"])["investigadores"] == [A, P]
