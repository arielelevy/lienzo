"""Consulta entre investigadores (lienzo/consulta.py, .kiro/specs/consulta-investigadores)."""

import datetime as dt

import consulta
import pytest
import state as st


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    """Tarjetas armadas a mano, un envio falso que anota y teclea la marca en `last_prompt`."""
    monkeypatch.setattr(consulta, "DIR", str(tmp_path / "consultas"))
    monkeypatch.setattr(consulta, "CONSULTAS", {})
    monkeypatch.setattr(consulta, "_ultima_vigilancia", 0.0)
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    tarjetas = {
        "A" * 8: {"session_id": "A" * 8, "agent": "claude", "model": "opus", "state": "termino", "alive": True},
        "B" * 8: {"session_id": "B" * 8, "agent": "codex", "model": "gpt-5.4", "state": "termino", "alive": True},
        "R" * 8: {"session_id": "R" * 8, "agent": "claude", "model": "", "state": "termino", "alive": True},
        "K" * 8: {"session_id": "K" * 8, "agent": "claude", "state": "termino", "alive": True},
    }
    envios = []

    def enviar(sid, texto, de, cid):
        envios.append({"sid": sid, "texto": texto, "de": de, "cid": cid})
        t = tarjetas[sid]
        t["last_prompt"] = texto[:500]
        t["state"] = "corriendo"
        return 200, {"ok": True}

    monkeypatch.setattr(consulta, "enviar", enviar)
    monkeypatch.setattr(consulta, "tarjeta", lambda sid: tarjetas.get(sid))
    return tarjetas, envios


def _contesta(tarjetas, sid, texto):
    t = tarjetas[sid]
    t["state"] = "termino"
    t["state_since"] = (dt.datetime.now().astimezone() + dt.timedelta(seconds=1)).isoformat()
    consulta.turno_cerrado(t, texto)


A, B, R, K = "A" * 8, "B" * 8, "R" * 8, "K" * 8


def test_una_consulta_completa_con_revisor_aparte(mundo):
    tarjetas, envios = mundo
    code, out = consulta.abrir({"pregunta": "¿P = NP?", "investigadores": [A, B], "revisor": R, "coordinador": K})
    assert code == 200 and out["tope_turnos"] == 2 * 2 + 1 + 2
    cid = out["id"]
    assert [e["sid"] for e in envios] == [A, B] or sorted(e["sid"] for e in envios) == [A, B]
    assert all(e["texto"].startswith(f"[consulta {cid} · vuelta 1]") and e["de"] == K for e in envios)
    assert "NO edites" in envios[0]["texto"]

    # lo que la persona escribe por la caja no cuenta (2.6)
    tarjetas[A]["last_prompt"] = "che, otra cosa"
    _contesta(tarjetas, A, "no es de la consulta")
    assert consulta.ver(cid)["respuestas"] == {}
    tarjetas[A]["last_prompt"] = f"[consulta {cid} · vuelta 1] ..."

    envios.clear()
    _contesta(tarjetas, A, "A dice sí")
    assert envios == []  # falta B
    _contesta(tarjetas, B, "B dice no")
    # vuelta 2: cada uno recibe la del otro, con la flecha desde el otro y con nombre
    por = {e["sid"]: e for e in envios}
    assert por[A]["de"] == B and "Codex (gpt-5.4)" in por[A]["texto"] and "B dice no" in por[A]["texto"]
    assert por[B]["de"] == A and "Claude (opus)" in por[B]["texto"] and "A dice sí" in por[B]["texto"]
    assert "Refuto" in por[A]["texto"] and consulta.ver(cid)["vuelta"] == 2

    envios.clear()
    _contesta(tarjetas, A, "A corregida")
    _contesta(tarjetas, B, "B corregida")
    assert [e["sid"] for e in envios] == [R] and "· síntesis]" in envios[0]["texto"]
    assert "A corregida" in envios[0]["texto"] and consulta.ver(cid)["estado"] == "sintetizando"

    envios.clear()
    _contesta(tarjetas, R, "Acuerdos: ... Desacuerdos: ...")
    assert sorted(e["sid"] for e in envios) == [A, B] and consulta.ver(cid)["estado"] == "revisando"
    assert all(e["de"] == R for e in envios)

    envios.clear()
    _contesta(tarjetas, A, consulta.REPRESENTA)
    _contesta(tarjetas, B, "No: yo dije que Q no equivale a #82")
    c = consulta.ver(cid)
    assert c["estado"] == "cerrada" and c["objeciones"][B].startswith("No:")
    assert [e["sid"] for e in envios] == [K] and "Objeciones" in envios[0]["texto"]
    with open(f"{consulta.DIR}/{cid}/sintesis.md", encoding="utf-8") as f:
        sintesis = f.read()
    assert "Q no equivale" in sintesis and "REPRESENTA" not in sintesis


def test_validaciones_al_abrir(mundo):
    tarjetas, envios = mundo
    assert consulta.abrir({"pregunta": "x", "investigadores": [A]})[0] == 400
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, A]})[0] == 400
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, "nadie"]})[0] == 400
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, B], "revisor": A})[0] == 400
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, B], "vueltas": 4})[0] == 400
    tarjetas[B]["stopped_by"] = "x"
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, B]})[0] == 400
    tarjetas[B]["stopped_by"] = None
    tarjetas[B]["state"] = "corriendo"
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, B]})[0] == 409
    assert envios == []
    tarjetas[B]["state"] = "termino"
    assert consulta.abrir({"pregunta": "x", "investigadores": [A, B]})[0] == 200
    assert consulta.abrir({"pregunta": "y", "investigadores": [A, R]})[0] == 400  # A ya está en una abierta


def test_converge_por_sin_cambios_y_sigue_desde_una_vuelta_1_hecha_a_mano(mundo):
    tarjetas, envios = mundo
    code, out = consulta.abrir(
        {"pregunta": "x", "investigadores": [A, B], "vueltas": 3, "vuelta1": {A: "a1", B: "b1"}, "revisar_sintesis": False}
    )
    cid = out["id"]
    assert code == 200 and sorted(e["sid"] for e in envios) == [A, B]
    assert all("· vuelta 2]" in e["texto"] for e in envios)
    envios.clear()
    _contesta(tarjetas, A, "SIN CAMBIOS\nsigo igual")
    _contesta(tarjetas, B, "sin cambios")
    # convergió en la vuelta 2 de 3: síntesis sin vuelta 3, y sin revisor aparte la hace el primero
    assert [e["sid"] for e in envios] == [A] and "· síntesis]" in envios[0]["texto"]
    _contesta(tarjetas, A, "síntesis")
    assert consulta.ver(cid)["estado"] == "cerrada"


def test_respuesta_por_adjunto_y_vigilancia(mundo, tmp_path):
    tarjetas, envios = mundo
    cid = consulta.abrir({"pregunta": "x", "investigadores": [A, B, R], "revisor": K})[1]["id"]
    # un mensaje largo se teclea como «Leé el archivo adjunto…»: la marca está en el mensaje.md
    adj = tmp_path / "mensaje.md"
    adj.write_text(f"[consulta {cid} · vuelta 1]\n\nla pregunta", encoding="utf-8")
    tarjetas[A]["last_prompt"] = f"Leé el archivo adjunto y respondé: Adjunto: {adj}"
    _contesta(tarjetas, A, "a1")
    assert A in consulta.ver(cid)["respuestas"]["1"]
    # B contestó con el server caído: lo toma vigilar() por la tarjeta
    tarjetas[B].update(state="termino", state_since=(dt.datetime.now().astimezone() + dt.timedelta(seconds=1)).isoformat())
    # R murió: sale, y con dos que quedan sigue
    tarjetas[R]["state"] = "muerta"
    consulta.vigilar(ahora=10**10, leer_respuesta=lambda s: "b1 entera")
    c = consulta.ver(cid)
    assert c["respuestas"]["1"][B]["texto"] == "b1 entera" and R in c["fuera"] and c["vuelta"] == 2


def test_cancela_con_menos_de_dos_y_avisa(mundo):
    tarjetas, envios = mundo
    cid = consulta.abrir({"pregunta": "x", "investigadores": [A, B], "coordinador": K})[1]["id"]
    envios.clear()
    tarjetas[B]["state"] = "muerta"
    consulta.vigilar(ahora=10**10)
    c = consulta.ver(cid)
    assert c["estado"] == "cancelada" and "menos de dos" in c["motivo"]
    assert [e["sid"] for e in envios] == [K] and "cancelada" in envios[0]["texto"]
    assert consulta.cancelar(cid)[0] == 409


def test_cancelar_y_recargar_de_disco(mundo, monkeypatch):
    tarjetas, envios = mundo
    cid = consulta.abrir({"pregunta": "x", "investigadores": [A, B]})[1]["id"]
    monkeypatch.setattr(consulta, "CONSULTAS", {})
    consulta.cargar()
    assert consulta.ver(cid)["estado"] == "abierta" and consulta.espera(A)
    assert consulta.de_tarjeta(B)["id"] == cid
    assert consulta.cancelar(cid)[0] == 200 and not consulta.espera(A)
    assert consulta.listar()[0]["estado"] == "cancelada"
