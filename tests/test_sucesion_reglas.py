"""Restaurar una sesion conserva su cableado (pedido de Ariel, 2026-10-16).

Medido en OpenSyync: tras reiniciar la PC y restaurar los frentes cambiaron sus session_id, los
envios a los ids viejos dieron 404 y las reglas «cuando termine» de cada frente se perdieron (al
morir la tarjeta se borraban las suyas, y la sucesion de las que le avisaban vivia solo en memoria).
Ahora las dos puntas se estacionan, la sucesion se guarda en sucesion.json y la sesion restaurada
hereda reglas y titulo; un envio al id viejo contesta 404 con `sucesora`."""

import os
import time

import pytest
import rules as rl
import server
import sessions as ses
import state as st

VIEJA = "aaaaaaaa-0000-4000-8000-0000000000d1"
NUEVA = "bbbbbbbb-0000-4000-8000-0000000000d2"
COORD = "cccccccc-0000-4000-8000-0000000000d3"
OTRA = "dddddddd-0000-4000-8000-0000000000d4"
CWD = r"D:\Apps\opensyync"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    os.makedirs(st.SESSIONS, exist_ok=True)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(rl.rules, "path", str(tmp_path / "rules.json"))
    monkeypatch.setattr(rl.rules, "items", [])
    monkeypatch.setattr(ses, "DEAD_TARGETS", {})
    monkeypatch.setattr(ses, "SUCESORAS", {})
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(ses, "restore_on_drop", lambda card, muerta: None)
    st.sessions.clear()
    yield
    st.sessions.clear()


def tarjeta(sid, titulo=None, cwd=CWD):
    s = ses.new_session(sid, "claude", "hook")
    s["cwd"] = cwd
    if titulo:
        s["title"], s["title_source"] = titulo, "user"
    st.sessions[sid] = s
    return s


def reglas_de_un_frente():
    st.rules.items.extend(
        [
            {"id": "informe", "kind": "on_stop", "from": VIEJA, "to": COORD, "text": "{respuesta}", "enabled": True},
            {"id": "aviso", "kind": "on_stop", "from": COORD, "to": VIEJA, "text": "seguí", "enabled": True},
        ]
    )


def test_la_restaurada_con_otro_id_hereda_sus_reglas_y_su_titulo(entorno):
    tarjeta(COORD)
    tarjeta(VIEJA, "opensyync - encargo A - motor")
    reglas_de_un_frente()
    ses.drop_session(VIEJA, "muerta hace mas de 60 s", muerta=True)
    informe = next(r for r in st.rules.items if r["id"] == "informe")
    assert informe["parked_from"] == VIEJA and informe["enabled"] is False  # antes se borraba

    nueva = tarjeta(NUEVA)
    assert ses.adopt_dead_target(dict(nueva)) == VIEJA
    por_id = {r["id"]: r for r in st.rules.items}
    assert por_id["informe"]["from"] == NUEVA and por_id["informe"]["enabled"] is True
    assert "parked_from" not in por_id["informe"] and "parked_since" not in por_id["informe"]
    assert por_id["aviso"]["to"] == NUEVA and por_id["aviso"]["enabled"] is True
    assert nueva["title"] == "opensyync - encargo A - motor"
    assert ses.sucesora_de(VIEJA) == NUEVA


def test_resume_con_el_mismo_id_vuelve_a_prender_sus_reglas(entorno):
    tarjeta(COORD)
    tarjeta(VIEJA)
    reglas_de_un_frente()
    ses.drop_session(VIEJA, "muerta", muerta=True)
    vuelta = tarjeta(VIEJA)  # claude --resume conserva el id
    assert ses.adopt_dead_target(dict(vuelta)) == VIEJA
    assert all(r["enabled"] for r in st.rules.items)
    assert ses.sucesora_de(VIEJA) is None  # no hay otro id al que mandar


def test_la_sucesion_sobrevive_al_reinicio_del_server(entorno, monkeypatch):
    tarjeta(COORD)
    tarjeta(VIEJA, "opensyync - encargo B - ui")
    reglas_de_un_frente()
    ses.drop_session(VIEJA, "muerta", muerta=True)
    monkeypatch.setattr(ses, "DEAD_TARGETS", {})  # el server se reinicio
    assert ses.cargar_sucesion() == 1 and ses.DEAD_TARGETS[VIEJA]["title"] == "opensyync - encargo B - ui"
    # al cargar rules.json, las estacionadas de una muerta que espera sucesora se conservan
    informe = next(r for r in st.rules.items if r["id"] == "informe")
    assert server.conservar_regla(informe) is True
    orphan = {**informe, "parked_from": None}
    assert server.conservar_regla(orphan) is True
    assert not orphan["enabled"]


def test_con_dos_frentes_en_la_carpeta_gana_la_restaurada(entorno):
    tarjeta(COORD)
    tarjeta(VIEJA, "opensyync - encargo A - motor")
    tarjeta(OTRA, "opensyync - encargo B - ui")
    st.rules.items.extend(
        [
            {"id": "a", "kind": "on_stop", "from": VIEJA, "to": COORD, "text": "x", "enabled": True},
            {"id": "b", "kind": "on_stop", "from": OTRA, "to": COORD, "text": "y", "enabled": True},
        ]
    )
    ses.drop_session(VIEJA, "muerta", muerta=True)
    time.sleep(0.01)
    ses.drop_session(OTRA, "muerta", muerta=True)  # la mas nueva: antes ganaba esta
    server.preparar_sucesion({"session_id": VIEJA, "cwd": CWD, "agent": "claude", "title": None})
    nueva = tarjeta(NUEVA)
    assert ses.adopt_dead_target(dict(nueva)) == VIEJA
    assert nueva["title"] == "opensyync - encargo A - motor"
    assert next(r for r in st.rules.items if r["id"] == "b")["enabled"] is False  # B sigue esperando


def test_preparar_sucesion_da_de_baja_la_muerta_que_sigue_en_el_tablero(entorno):
    tarjeta(COORD)
    vieja = tarjeta(VIEJA)
    vieja["alive"], vieja["state"] = False, "muerta"
    reglas_de_un_frente()
    server.preparar_sucesion({"session_id": VIEJA, "cwd": CWD, "agent": "claude", "title": "t"})
    assert VIEJA not in st.sessions and ses.DEAD_TARGETS[VIEJA]["restaurada"]
    assert next(r for r in st.rules.items if r["id"] == "informe")["parked_from"] == VIEJA


def test_un_envio_a_un_id_viejo_contesta_404_con_la_sucesora(entorno):
    ses.SUCESORAS[VIEJA] = {"new": NUEVA, "ts": time.time()}
    code, res = server.atender_accion("POST", VIEJA, "send", {"text": "hola"}, desde_tablero=False)
    assert code == 404 and res["code"] == "unknown_session" and res["sucesora"] == NUEVA
    code, res = server.atender_accion("POST", OTRA, "send", {"text": "hola"}, desde_tablero=False)
    assert code == 404 and "sucesora" not in res


def test_borrada_a_mano_sus_reglas_se_van_como_antes(entorno):
    tarjeta(COORD)
    tarjeta(VIEJA)
    reglas_de_un_frente()
    ses.drop_session(VIEJA, "borrada desde la UI")
    assert st.rules.items == [] and ses.DEAD_TARGETS == {}
