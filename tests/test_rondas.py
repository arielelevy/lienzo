"""Primitivas de rondas largas (pedido de Ariel, 2026-10-16; medido en OpenSyync, olas 21-22): aviso
coordinado con confirmaciones, turno de un recurso pesado y presion de memoria."""

import datetime as dt

import pytest
import rondas
import server
import sessions as ses
import state as st

COORD = "c0000000-0000-4000-8000-0000000000e0"
A = "a0000000-0000-4000-8000-0000000000e1"
B = "b0000000-0000-4000-8000-0000000000e2"
C = "d0000000-0000-4000-8000-0000000000e3"


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(rondas, "_datos", {"avisos": {}, "turnos": {}, "politicas": {}})
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(ses, "SUCESORAS", {})
    monkeypatch.setattr(ses, "add_link", lambda *a, **k: None)
    # los envios corren en el acto, no en un hilo: lo que se mide es el estado
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *args: fn(*args))
    enviados = []
    monkeypatch.setattr(ses, "send_to_session", lambda s, t, att: (enviados.append((s["session_id"], t)), (200, {}))[1])
    st.sessions.clear()
    for sid, titulo in ((COORD, "coordinadora"), (A, "encargo A"), (B, "encargo B"), (C, "encargo C")):
        s = ses.new_session(sid, "claude", "hook")
        s.update(alive=True, title=titulo, repo="opensyync", repo_key="opensyync")
        st.sessions[sid] = s
    yield enviados
    st.sessions.clear()


def para(enviados, sid):
    return [t for s, t in enviados if s == sid]


# --- aviso coordinado ----------------------------------------------------------------------------


def test_la_coordinadora_recibe_un_solo_aviso_cuando_confirman_todos(entorno):
    code, a = rondas.crear_aviso({"texto": "subí el contrato a v3", "a": [A, B, C], "de": COORD})
    assert code == 200 and set(a["destinos"]) == {A, B, C}
    aid = a["id"]
    assert all(rondas.marca_ack(aid) in para(entorno, x)[0] for x in (A, B, C))
    assert all(x["estado"] == "enviado" for x in rondas.vista_aviso(aid)["destinos"].values())
    # A confirma por la API, B y C cerrando su respuesta con ACK <id>
    assert rondas.ack(aid, A, "listo")[0] == 200
    st.sessions[B]["last_reply"] = f"Subí la versión.\nACK {aid} v3 en backend"
    st.sessions[C]["last_reply"] = "sigo con la UI"  # todavia no
    rondas.revisar()
    assert para(entorno, COORD) == []  # falta C: ningun aviso a medias
    st.sessions[C]["last_reply"] = f"ACK {aid}"
    rondas.revisar()
    final = para(entorno, COORD)
    assert len(final) == 1 and "confirmado por los 3" in final[0] and "v3 en backend" in final[0]
    assert rondas.vista_aviso(aid)["estado"] == "completo"
    rondas.revisar()
    assert len(para(entorno, COORD)) == 1  # no se repite


def test_un_ack_mientras_trabaja_no_cuenta(entorno):
    _, a = rondas.crear_aviso({"texto": "x", "a": [A], "de": COORD})
    st.sessions[A].update(state="corriendo", last_reply=f"ACK {a['id']}")
    rondas.revisar()
    assert rondas.vista_aviso(a["id"])["destinos"][A]["estado"] == "enviado"


def test_el_aviso_vence_y_dice_quien_falta(entorno):
    _, a = rondas.crear_aviso({"texto": "x", "a": [A, B], "de": COORD, "vence_min": 1})
    rondas.ack(a["id"], A)
    rondas._datos["avisos"][a["id"]]["vence"] = (dt.datetime.now().astimezone() - dt.timedelta(seconds=1)).isoformat()
    rondas.revisar()
    msg = para(entorno, COORD)
    assert len(msg) == 1 and "vencido" in msg[0] and "encargo B" in msg[0] and "encargo A" not in msg[0]
    assert rondas.ack(a["id"], B)[0] == 409


def test_aviso_validaciones(entorno):
    assert rondas.crear_aviso({"texto": "", "a": [A]})[0] == 400
    assert rondas.crear_aviso({"texto": "x", "a": []})[0] == 400
    assert rondas.crear_aviso({"texto": "x", "a": [A, A]})[0] == 400
    assert rondas.crear_aviso({"texto": "x", "a": [A], "de": A})[0] == 400
    code, res = rondas.crear_aviso({"texto": "x", "a": [A, "no-existe"]})
    assert code == 404 and res["faltan"] == ["no-existe"]
    _, a = rondas.crear_aviso({"texto": "x", "a": [A]})
    assert rondas.ack(a["id"], B)[0] == 404 and rondas.ack("av-nada", A)[0] == 404


def test_una_restaurada_confirma_por_la_vieja(entorno, monkeypatch):
    _, a = rondas.crear_aviso({"texto": "x", "a": [A], "de": COORD})
    ses.SUCESORAS[A] = {"new": C, "ts": 0}
    assert rondas.ack(a["id"], C)[0] == 200


# --- turnos ----------------------------------------------------------------------------------------


def test_semaforo_duenio_cola_y_paso_automatico(entorno):
    code, t = rondas.pedir_turno("navegador", {"session_id": A, "motivo": "agénticas"})
    assert code == 200 and t["otorgado"] and t["session_id"] == A
    code, t = rondas.pedir_turno("navegador", {"session_id": B})
    assert code == 202 and t["posicion"] == 1 and t["dueno"]["session_id"] == A
    assert rondas.pedir_turno("navegador", {"session_id": C})[1]["posicion"] == 2
    assert rondas.pedir_turno("navegador", {"session_id": A})[1]["renovado"] is True
    assert rondas.liberar_turno("navegador", A)[0] == 200
    assert rondas._datos["turnos"]["navegador"]["dueno"]["session_id"] == B
    assert "te toca el turno de «navegador»" in para(entorno, B)[0]
    assert rondas.liberar_turno("navegador", A)[0] == 404


def test_el_turno_se_libera_si_la_duena_se_cierra_o_vence(entorno):
    rondas.pedir_turno("suite", {"session_id": A})
    rondas.pedir_turno("suite", {"session_id": B})
    st.sessions.pop(A)  # la duena se cerro
    rondas.revisar()
    assert rondas._datos["turnos"]["suite"]["dueno"]["session_id"] == B
    rondas._datos["turnos"]["suite"]["dueno"]["vence"] = "2020-01-01T00:00:00-03:00"
    rondas.revisar()
    assert rondas._datos["turnos"]["suite"]["dueno"] is None
    assert any("vencio" in t for t in para(entorno, B))


def test_la_guardia_de_memoria_espera_sin_otorgar(entorno, monkeypatch):
    assert rondas.fijar_politica("motores", {"mem_min_gb": 3})[0] == 200
    monkeypatch.setattr(rondas, "_memoria_libre", lambda: 1.0)
    code, t = rondas.pedir_turno("motores", {"session_id": A})
    assert code == 202 and "memoria libre 1.0 GB" in t["espera"]
    monkeypatch.setattr(rondas, "_memoria_libre", lambda: 4.0)
    rondas.revisar()
    assert rondas._datos["turnos"]["motores"]["dueno"]["session_id"] == A


def test_turno_validaciones(entorno):
    assert rondas.pedir_turno("Navegador!", {"session_id": A})[0] == 400
    assert rondas.pedir_turno("suite", {})[0] == 400
    assert rondas.pedir_turno("suite", {"session_id": "nadie"})[0] == 404
    assert rondas.pedir_turno("suite", {"session_id": A, "ttl_min": 999})[0] == 400
    rondas.fijar_politica("pago", {"ttl_max_min": 10})
    assert rondas.pedir_turno("pago", {"session_id": A, "ttl_min": 11})[0] == 400
    assert rondas.pedir_turno("pago", {"session_id": A})[1]["otorgado"]  # el default se ajusta al tope


# --- memoria -------------------------------------------------------------------------------------


def test_presion_sugiere_la_quieta_mas_vieja_sin_turno_ni_coordinar(entorno, monkeypatch):
    monkeypatch.setattr(rondas, "_memoria_libre", lambda: 0.7)
    st.sessions[COORD]["coordinator"] = True
    st.sessions[A].update(state="termino", state_since="2026-10-16T10:00:00-03:00")
    st.sessions[B].update(state="termino", state_since="2026-10-16T09:00:00-03:00")
    st.sessions[C].update(state="corriendo")
    rondas.pedir_turno("navegador", {"session_id": B})  # tiene un turno: no se sugiere
    p = rondas.presion()
    assert p["bajo"] is True and p["umbral_gb"] == 1.5
    assert [x["session_id"] for x in p["cerrar"]] == [A]


def test_tope_de_sesiones_por_repo_en_el_lanzamiento(entorno, monkeypatch):
    monkeypatch.setattr(rondas.identity, "repo_key", lambda cwd: "opensyync")
    todas = list(st.sessions.values())
    rechazo = rondas.tope_repo(r"D:\Apps\opensyync", todas)
    assert rechazo["code"] == "tope_repo" and len(rechazo["vivas"]) == 4
    assert rondas.tope_repo(r"D:\Apps\opensyync", todas[:3]) is None
    monkeypatch.setattr(st, "load_config", lambda: {"max_sesiones_por_repo": 0})
    assert rondas.tope_repo(r"D:\Apps\opensyync", todas) is None
    # por el tablero: 409 antes de lanzar nada; con forzar pasa a la validacion de siempre
    monkeypatch.setattr(st, "load_config", dict)
    monkeypatch.setattr(server.mirror.MIRROR, "sessions", list)
    code, res = server.accion_launch({"cwd": r"D:\Apps\opensyync", "agent": "claude"}, desde_tablero=True)
    assert code == 409 and res["code"] == "tope_repo"
