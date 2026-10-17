"""Entrega fiable de las on_stop: un turno cerrado que ninguna regla evaluo se evalua igual.

Caso real (2026-10-16, regla 2054b0dd7f28): una <task-notification> reabrio el trabajo de A sin
UserPromptSubmit; la transcripcion dio el turno por terminado con la respuesta anterior (salteada por
`solo_si: "ESTADO:"`) y el Stop real, con «ESTADO:», no cambio el estado: nunca se evaluo."""

import datetime as dt

import pytest
import rules as rl
import sessions as ses
import state as st

ORIGEN = "10000000-0000-4000-8000-0000000000cc"
DESTINO = "20000000-0000-4000-8000-0000000000dd"
INTERMEDIA = "Sigo esperando el aviso de la suite completa."
FINAL = "ESTADO: implementado y verificado en local."


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl.rules, "save", lambda: None)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    monkeypatch.setattr(rl, "ON_STOP_SETTLE_S", 0)
    # la reconciliacion evalua en un hilo: en las pruebas, en el mismo para poder medir
    monkeypatch.setattr(rl, "_lanzar", rl._reconciliar_una)
    origen = ses.new_session(ORIGEN, "claude", "hook")
    destino = ses.new_session(DESTINO, "claude", "hook")
    st.sessions[ORIGEN], st.sessions[DESTINO] = origen, destino
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    enviados = []
    monkeypatch.setattr(rl, "send_to_session", lambda dst, text, att: (enviados.append(text), (200, {"ok": True}))[1])
    yield enviados
    st.sessions.pop(ORIGEN, None)
    st.sessions.pop(DESTINO, None)
    st.rules.items[:] = [r for r in st.rules.items if r.get("from") != ORIGEN]
    rl._on_stop_en_vuelo.clear()
    rl._evaluando.clear()
    rl._pendientes.clear()


def hace(segundos: float) -> str:
    return (dt.datetime.now().astimezone() - dt.timedelta(seconds=segundos)).isoformat(timespec="milliseconds")


def regla(**extra):
    r = {
        "id": "rt",
        "kind": "on_stop",
        "from": ORIGEN,
        "to": DESTINO,
        "text": "{respuesta}",
        "enabled": True,
        "repeat": True,
        "limit": "rate",
        "fired": 0,
        "solo_si": "ESTADO:",
        "created": hace(3600),
        **extra,
    }
    st.rules.items.append(r)
    return r


def turno(s, respuesta, prompt="p1", estado="termino"):
    s["last_reply"], s["prompt_id"] = respuesta, prompt
    ses.set_state(s, "corriendo") if estado == "corriendo" else None
    s["state"], s["state_since"] = estado, hace(60)


def test_stop_sin_transicion_no_pierde_la_entrega(entorno):
    """La carrera medida: el cierre falso evalua la intermedia; el Stop real no tiene transicion."""
    r = regla()
    s = st.sessions[ORIGEN]
    turno(s, INTERMEDIA)
    rl.fire_on_stop(ORIGEN)  # el cierre (falso) por transcripcion: intermedia, se saltea
    assert entorno == [] and "turno intermedio" in r["last_result"]
    s["last_reply"] = FINAL  # el hook Stop real: misma tarjeta en termino, sin transicion
    assert rl.reconciliar(ahora=1000) == []  # recien visto: espera que se quede quieto
    assert rl.reconciliar(ahora=1000 + rl.RECONCILIA_S - 1) == []
    assert rl.reconciliar(ahora=1000 + rl.RECONCILIA_S) == [ORIGEN]
    assert len(entorno) == 1 and FINAL in entorno[0] and r["fired"] == 1
    # sin bucles ni duplicados: el mismo turno no se vuelve a mandar
    for t in range(5):
        assert rl.reconciliar(ahora=2000 + t * rl.RECONCILIA_S) == []
    rl.fire_on_stop(ORIGEN)  # un Stop doble tardio del mismo turno
    assert len(entorno) == 1


def test_turno_evaluado_por_el_stop_no_se_reevalua(entorno):
    regla()
    s = st.sessions[ORIGEN]
    turno(s, FINAL)
    rl.fire_on_stop(ORIGEN)
    assert len(entorno) == 1
    for t in range(4):
        assert rl.reconciliar(ahora=t * rl.RECONCILIA_S) == []
    assert len(entorno) == 1


def test_corriendo_o_cambiando_no_se_evalua(entorno):
    regla()
    s = st.sessions[ORIGEN]
    turno(s, INTERMEDIA)
    rl.fire_on_stop(ORIGEN)
    s["state"] = "corriendo"
    s["last_reply"] = FINAL
    assert rl.reconciliar(ahora=0) == [] and rl.reconciliar(ahora=100) == []
    s["state"] = "termino"
    assert rl.reconciliar(ahora=200) == []
    s["last_reply"] = FINAL + " (sigue escribiendo)"  # cambio: reinicia la espera
    assert rl.reconciliar(ahora=200 + rl.RECONCILIA_S) == []
    assert rl.reconciliar(ahora=200 + 2 * rl.RECONCILIA_S) == [ORIGEN]
    assert len(entorno) == 1


def test_regla_nueva_no_entrega_lo_ya_contestado(entorno):
    s = st.sessions[ORIGEN]
    turno(s, FINAL)
    s["state_since"] = hace(600)
    r = regla(created=hace(60))  # se creo despues de que la sesion termino
    assert rl.reconciliar(ahora=0) == [] and rl.reconciliar(ahora=100) == []
    assert entorno == [] and r["turno_visto"] == rl.clave_turno(s)


def test_tras_reinicio_recupera_el_turno_perdido(entorno):
    """La marca queda en disco: tras un reinicio, un turno distinto del ultimo evaluado se evalua una vez."""
    r = regla(turno_visto="turno-anterior")
    turno(st.sessions[ORIGEN], FINAL)
    assert rl.reconciliar(ahora=0) == []
    assert rl.reconciliar(ahora=rl.RECONCILIA_S) == [ORIGEN]
    assert len(entorno) == 1 and r["turno_visto"] == rl.clave_turno(st.sessions[ORIGEN])
    assert rl.reconciliar(ahora=10 * rl.RECONCILIA_S) == [] and len(entorno) == 1


def test_ya_entregado_por_huella_no_se_duplica_tras_reinicio(entorno):
    s = st.sessions[ORIGEN]
    turno(s, FINAL)
    h = rl.turno_de(s)["huella"]
    regla(last_hash=h, turno_visto="turno-anterior")  # entregado, pero el Stop no dejo la marca
    rl.reconciliar(ahora=0)
    assert rl.reconciliar(ahora=rl.RECONCILIA_S) == [ORIGEN]
    assert entorno == []


def test_dos_frentes_simultaneos_sin_mezcla(entorno):
    otro = "10000000-0000-4000-8000-0000000000ee"
    st.sessions[otro] = ses.new_session(otro, "claude", "hook")
    try:
        regla(turno_visto="x")
        regla(id="rt2", turno_visto="y", **{"from": otro})
        turno(st.sessions[ORIGEN], FINAL + " A", "pa")
        turno(st.sessions[otro], FINAL + " B", "pb")
        rl.reconciliar(ahora=0)
        assert sorted(rl.reconciliar(ahora=rl.RECONCILIA_S)) == sorted([ORIGEN, otro])
        assert sorted(entorno) == sorted([FINAL + " A", FINAL + " B"])
    finally:
        st.sessions.pop(otro, None)
        st.rules.items[:] = [r for r in st.rules.items if r.get("from") != otro]


def test_no_se_cruza_con_un_fire_on_stop_en_curso(entorno):
    regla(turno_visto="turno-anterior")  # un turno pendiente de verdad: sin la reserva se evaluaria
    turno(st.sessions[ORIGEN], FINAL)
    rl._evaluando[ORIGEN] = 1
    assert rl.reconciliar(ahora=0) == [] and rl.reconciliar(ahora=100) == []
    rl._evaluando.pop(ORIGEN)
    assert entorno == []
    rl.reconciliar(ahora=200)  # suelta la reserva: ahora si se evalua, una vez
    assert rl.reconciliar(ahora=200 + rl.RECONCILIA_S) == [ORIGEN] and entorno == [FINAL]


def test_externa_y_regla_apagada_no_se_reconcilian(entorno):
    r = regla(turno_visto="turno-anterior")
    s = st.sessions[ORIGEN]
    turno(s, FINAL)
    s["external"] = {"kind": "orquestador"}
    assert rl.reconciliar(ahora=0) == [] and rl.reconciliar(ahora=100) == []
    s["external"] = None
    r["enabled"] = False
    assert rl.reconciliar(ahora=200) == [] and rl.reconciliar(ahora=300) == []
    assert entorno == []


def test_destino_ocupado_difiere_sin_perder(entorno, monkeypatch):
    """Con la coordinadora ocupada (envio anterior en vuelo) el turno queda en espera, no se pierde."""
    r = regla(turno_visto="turno-anterior")
    turno(st.sessions[ORIGEN], FINAL)
    rl._on_stop_en_vuelo.add("rt")
    rl.reconciliar(ahora=0)
    assert rl.reconciliar(ahora=rl.RECONCILIA_S) == [ORIGEN]
    assert entorno == [] and r.get("deferred")


def test_despliegue_sin_marca_no_reevalua_lo_ya_contestado(entorno):
    """Reglas anteriores a la marca: el turno que hay al desplegar se toma como visto."""
    r = regla(created=hace(3600))
    turno(st.sessions[ORIGEN], FINAL)
    for t in range(4):
        assert rl.reconciliar(ahora=t * rl.RECONCILIA_S) == []
    assert entorno == [] and r["turno_visto"] == rl.clave_turno(st.sessions[ORIGEN])


def test_regla_creada_con_la_sesion_corriendo_evalua_su_cierre(entorno):
    r = regla()
    s = st.sessions[ORIGEN]
    turno(s, "trabajando...", estado="corriendo")
    assert rl.reconciliar(ahora=0) == [] and r["turno_visto"] == rl.clave_turno(s)
    s["state"], s["last_reply"] = "termino", FINAL  # el Stop no cambio el estado (se perdio la transicion)
    rl.reconciliar(ahora=100)
    assert rl.reconciliar(ahora=100 + rl.RECONCILIA_S) == [ORIGEN] and entorno == [FINAL]


@pytest.mark.parametrize("cambio", [{"agent": "coda"}, {"agent": "codex"}, {"hooked": False}])
def test_solo_sesiones_claude_con_hooks(entorno, cambio):
    regla(turno_visto="turno-anterior")
    s = st.sessions[ORIGEN]
    turno(s, FINAL)
    s.update(cambio)
    assert rl.reconciliar(ahora=0) == [] and rl.reconciliar(ahora=100) == []
    assert entorno == []


def test_la_marca_queda_en_disco(entorno, monkeypatch):
    guardados = []
    monkeypatch.setattr(rl.rules, "save", lambda: guardados.append(1))
    regla()
    s = st.sessions[ORIGEN]
    turno(s, INTERMEDIA)
    s["last_reply"] = INTERMEDIA + "?"  # sale temprano (pregunta al usuario): igual marca y guarda
    rl.fire_on_stop(ORIGEN)
    assert guardados and st.rules.items[-1]["turno_visto"] == rl.clave_turno(s)
