"""Avisos on_stop sin duplicados ni turnos intermedios (pedido de Ariel, 2026-10-16).

Medido en OpenSyync (olas 21-22): la coordinadora recibia la misma respuesta varias veces (un
«aviso demorado» con texto identico al ya entregado) y turnos sin novedad («sigo esperando»), y
gastaba un turno por cada uno. Ahora cada regla recuerda la huella de lo ultimo que entrego, puede
pedir un marcador (`solo_si: "ESTADO:"`) y la espera guarda la foto del turno que paso el filtro."""

import datetime as dt

import pytest
import rules as rl
import rules_api
import sessions as ses
import state as st

ORIGEN = "10000000-0000-4000-8000-0000000000ca"
DESTINO = "20000000-0000-4000-8000-0000000000cb"


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl.rules, "save", lambda: None)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    origen = ses.new_session(ORIGEN, "claude", "hook")
    origen["last_reply"] = "listo"
    st.sessions[ORIGEN], st.sessions[DESTINO] = origen, ses.new_session(DESTINO, "claude", "hook")
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    enviados = []
    monkeypatch.setattr(rl, "send_to_session", lambda dst, text, att: (enviados.append(text), (200, {"ok": True}))[1])
    yield enviados
    st.sessions.pop(ORIGEN, None)
    st.sessions.pop(DESTINO, None)
    st.rules.items[:] = [r for r in st.rules.items if r.get("from") != ORIGEN]
    rl._on_stop_en_vuelo.clear()
    rl._fotos.clear()


def regla(**extra):
    r = {"id": "dd", "kind": "on_stop", "from": ORIGEN, "to": DESTINO, "text": "{respuesta}"}
    r.update(enabled=True, repeat=True, fired=0, **extra)
    st.rules.items.append(r)
    return r


def responder(texto):
    st.sessions[ORIGEN]["last_reply"] = texto


def enfriar(r):
    """Corre el ultimo disparo 31 s atras: simula que paso el enfriamiento entre turnos."""
    last = rl.local_dt(r["last_fired"]) - dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1)
    r["last_fired"] = last.isoformat(timespec="seconds")
    r["recent_fires"] = [last.isoformat(timespec="seconds")]


def test_la_misma_respuesta_no_se_entrega_dos_veces(entorno):
    r = regla()
    rl.fire_on_stop(ORIGEN)
    enfriar(r)
    rl.fire_on_stop(ORIGEN)  # un Stop doble del mismo turno
    assert entorno == ["listo"] and r["fired"] == 1
    assert "misma respuesta" in r["last_result"]
    responder("otra cosa")
    rl.fire_on_stop(ORIGEN)
    assert entorno == ["listo", "otra cosa"]


def test_demorado_sin_turno_nuevo_no_repite_lo_ya_entregado(entorno):
    """El caso de OpenSyync: una espera que, al salir, leia otra vez la respuesta ya entregada."""
    r = regla()
    r["deferred"] = {"since": st.now(), "count": 1, "until": st.now()}
    r["last_hash"] = rl.huella("listo")
    listas = rl.entregas_diferidas(dt.datetime.now().astimezone() + dt.timedelta(seconds=1))
    for x, n in listas:
        rl.fire_rule(x, agrupados=n)
    assert entorno == [] and "misma respuesta" in r["last_result"]


def test_solo_si_saltea_los_turnos_intermedios(entorno):
    r = regla(solo_si="ESTADO:")
    responder("sigo esperando la mutación")
    rl.fire_on_stop(ORIGEN)
    assert entorno == [] and "turno intermedio" in r["last_result"] and not r.get("deferred")
    responder("Listo.\nESTADO: entregado")
    rl.fire_on_stop(ORIGEN)
    assert entorno == ["Listo.\nESTADO: entregado"]


def test_la_espera_guarda_el_turno_con_marcador(entorno):
    """Un turno intermedio que cierra mientras espera no reemplaza al que traia ESTADO:."""
    r = regla(solo_si="ESTADO:")
    responder("A\nESTADO: hecho A")
    rl.fire_on_stop(ORIGEN)
    responder("B\nESTADO: hecho B")
    rl.fire_on_stop(ORIGEN)  # en enfriamiento: espera con la foto de B
    responder("espero la suite")
    rl.fire_on_stop(ORIGEN)  # intermedio: se saltea, no toca la espera
    assert r["deferred"]["count"] == 1
    listas = rl.entregas_diferidas(dt.datetime.now().astimezone() + dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1))
    for x, n in listas:
        rl.fire_rule(x, agrupados=n)
    assert len(entorno) == 2 and entorno[-1].endswith("ESTADO: hecho B")


def test_un_stop_repetido_en_espera_no_suma(entorno):
    r = regla()
    rl.fire_on_stop(ORIGEN)
    responder("segundo")
    rl.fire_on_stop(ORIGEN)
    rl.fire_on_stop(ORIGEN)  # el mismo turno otra vez, mientras espera
    assert r["deferred"]["count"] == 1


def test_dedupe_false_vuelve_al_comportamiento_anterior(entorno):
    r = regla(dedupe=False)
    rl.fire_on_stop(ORIGEN)
    enfriar(r)
    rl.fire_on_stop(ORIGEN)
    assert entorno == ["listo", "listo"]


def test_api_valida_solo_si_y_dedupe():
    lim, err = rules_api.on_stop_limits({"solo_si": "ESTADO:", "dedupe": False})
    assert err is None and lim["solo_si"] == "ESTADO:" and lim["dedupe"] is False
    assert rules_api.on_stop_limits({})[0]["solo_si"] is None
    assert rules_api.on_stop_limits({"solo_si": "x" * 65})[1]
    assert rules_api.on_stop_limits({"solo_si": 3})[1]
    assert rules_api.on_stop_limits({"dedupe": "si"})[1]
    # editar sin mandarlos conserva lo que tenia
    lim, _ = rules_api.on_stop_limits({}, {"solo_si": "ESTADO:", "dedupe": False})
    assert lim["solo_si"] == "ESTADO:" and lim["dedupe"] is False
    # "" lo borra
    assert rules_api.on_stop_limits({"solo_si": ""}, {"solo_si": "ESTADO:"})[0]["solo_si"] is None
