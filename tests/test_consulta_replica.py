"""El endpoint replica (lienzo/consulta.py, docs/specs/consulta-replica): valida 404/409/400, manda el
pedido con la marca «· réplica», no toca pendientes ni saca a nadie si el envío falla, y anota en
c["replicas"] (con setdefault para las consultas viejas de disco)."""

import consulta
import pytest
import state as st


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    """Tarjetas armadas a mano y un envio falso que anota (igual que test_consulta.py)."""
    monkeypatch.setattr(consulta, "DIR", str(tmp_path / "consultas"))
    monkeypatch.setattr(consulta, "CONSULTAS", {})
    monkeypatch.setattr(consulta, "_ultima_vigilancia", 0.0)
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    tarjetas = {
        "A" * 8: {"session_id": "A" * 8, "agent": "claude", "model": "opus", "state": "termino", "alive": True},
        "B" * 8: {"session_id": "B" * 8, "agent": "codex", "model": "gpt-5.4", "state": "termino", "alive": True},
        "R" * 8: {"session_id": "R" * 8, "agent": "claude", "model": "", "state": "termino", "alive": True},
    }
    envios = []

    def enviar(sid, texto, de, cid):
        envios.append({"sid": sid, "texto": texto, "de": de, "cid": cid})
        return 200, {"ok": True}

    monkeypatch.setattr(consulta, "enviar", enviar)
    monkeypatch.setattr(consulta, "tarjeta", lambda sid: tarjetas.get(sid))
    return tarjetas, envios


A, B, R = "A" * 8, "B" * 8, "R" * 8


def _abrir(mundo, **extra):
    tarjetas, envios = mundo
    code, out = consulta.abrir(
        {"pregunta": "¿P = NP?", "investigadores": [A, B], "revisor": R, "vuelta1": {A: "a1", B: "b1"}, **extra}
    )
    assert code == 200
    envios.clear()
    with consulta.lock:  # A ya contestó la vuelta 2: se le puede replicar (a quien contesta, no: ver abajo)
        consulta.CONSULTAS[out["id"]]["pendientes"].pop(A, None)
    return out["id"]


def _responder(mundo, cid, sid, texto):
    """Deja una respuesta de `sid` en c["respuestas"]["1"] sin pasar por el gancho de rules."""
    tarjetas, _ = mundo
    with consulta.lock:
        c = consulta.CONSULTAS[cid]
        c["respuestas"].setdefault("1", {})[sid] = {"texto": texto, "ts": consulta.now(), "agente": "x", "modelo": "y"}


def test_validaciones(mundo):
    tarjetas, envios = mundo
    assert consulta.replica("no-existe", {"para": A, "de": B, "vuelta": 1})[0] == 404
    cid = _abrir(mundo)
    assert consulta.replica(cid, {"para": A, "de": B, "vuelta": 0})[0] == 400
    assert consulta.replica(cid, {"para": A, "de": B, "vuelta": True})[0] == 400
    assert consulta.replica(cid, {"para": A, "de": B, "vuelta": "1"})[0] == 400
    assert consulta.replica(cid, {"para": "nadie", "de": B, "vuelta": 1})[0] == 400
    assert consulta.replica(cid, {"para": A, "de": B, "vuelta": 2})[0] == 400  # nadie respondio la vuelta 2
    assert envios == []  # nada se mando
    # cerrada: 409
    with consulta.lock:
        consulta.CONSULTAS[cid]["estado"] = "cerrada"
    assert consulta.replica(cid, {"para": A, "de": B, "vuelta": 1})[0] == 409


def test_manda_con_marca_propia_y_anota(mundo):
    tarjetas, envios = mundo
    cid = _abrir(mundo)
    _responder(mundo, cid, B, "B dice no")
    with consulta.lock:  # la vuelta 2 ya esta en curso (vuelta1 + _avanzar): A ya contestó, B no
        consulta.CONSULTAS[cid]["pendientes"].pop(A, None)
        antes = dict(consulta.CONSULTAS[cid]["pendientes"])
        vuelta_antes = consulta.CONSULTAS[cid]["vuelta"]
    code, out = consulta.replica(cid, {"para": A, "de": B, "vuelta": 1})
    assert code == 200 and out["ok"] is True
    assert len(envios) == 1
    e = envios[0]
    assert e["sid"] == A and e["de"] == B and e["cid"] == cid
    assert e["texto"].startswith(f"[consulta {cid} · réplica]")
    assert "B dice no" in e["texto"] and "NO edites" in e["texto"]
    c = consulta.ver(cid)
    assert c["replicas"] == [{"para": A, "de": B, "vuelta": 1, "ts": c["replicas"][0]["ts"]}]
    assert c["pendientes"] == antes  # sin pendiente nuevo para A
    assert c["estado"] == "abierta" and c["vuelta"] == vuelta_antes  # no avanza


def test_envio_fallido_no_saca_a_nadie(mundo):
    tarjetas, envios = mundo
    cid = _abrir(mundo)
    _responder(mundo, cid, B, "B dice no")
    with consulta.lock:
        antes = dict(consulta.CONSULTAS[cid]["pendientes"])

    def enviar_roto(sid, texto, de, cid):
        return 500, {"error": "boom"}

    consulta.enviar = enviar_roto
    code, out = consulta.replica(cid, {"para": A, "de": B, "vuelta": 1})
    assert code == 502 and out["ok"] is False and "el envío falló" in out["error"]
    c = consulta.ver(cid)
    assert c["replicas"] == [] and c["fuera"] == {} and c["pendientes"] == antes
    assert c["estado"] == "abierta" and not c.get("motivo")


def test_consulta_vieja_de_disco_sin_replicas(mundo):
    tarjetas, envios = mundo
    cid = _abrir(mundo)
    _responder(mundo, cid, B, "B dice no")
    with consulta.lock:  # una consulta vieja de disco: sin la clave
        del consulta.CONSULTAS[cid]["replicas"]
    code, out = consulta.replica(cid, {"para": A, "de": B, "vuelta": 1})
    assert code == 200 and out["ok"] is True
    assert len(consulta.ver(cid)["replicas"]) == 1


def test_no_se_replica_a_quien_esta_contestando(mundo):
    """La réplica pisaría su último pedido y su respuesta a la vuelta ya no se reconocería."""
    cid = _abrir(mundo)
    c = consulta.CONSULTAS[cid]
    para = c["investigadores"][0]
    c["pendientes"][para] = {"marca": f"[consulta {cid} · vuelta 2]", "enviado": "2026-10-10T00:00:00-03:00"}
    code, out = consulta.replica(cid, {"para": para, "de": c["investigadores"][1], "vuelta": 1})
    assert code == 409 and "está contestando" in out["error"]
