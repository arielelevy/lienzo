"""Reglas on_stop repetidas limitadas por frecuencia (pedido de Ariel, 2026-10-14).

Caso real: en OpenSyync 7 reglas con max_fires=30 (el default de coordinar.py) llegaron a 30 en una
sesion larga, se apagaron solas y la coordinadora dejo de recibir entregas sin aviso. Ahora una
on_stop repetida no tiene tope total salvo `limit: "total"` explicito; lo que excede el enfriamiento
o la ventana se demora, queda visible en la regla y sale agrupado. Nada se descarta callado."""

import datetime as dt

import pytest
import rules as rl
import rules_api
import sessions as ses
import state as st

ORIGEN = "10000000-0000-4000-8000-0000000000aa"
DESTINO = "20000000-0000-4000-8000-0000000000bb"


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl.rules, "save", lambda: None)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    origen = ses.new_session(ORIGEN, "claude", "hook")
    origen["last_reply"] = "listo"
    destino = ses.new_session(DESTINO, "claude", "hook")
    st.sessions[ORIGEN], st.sessions[DESTINO] = origen, destino
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    enviados = []
    monkeypatch.setattr(rl, "send_to_session", lambda dst, text, att: (enviados.append(text), (200, {"ok": True}))[1])
    yield enviados
    st.sessions.pop(ORIGEN, None)
    st.sessions.pop(DESTINO, None)
    rl._on_stop_en_vuelo.clear()


def regla(**extra):
    r = {
        "id": "rf",
        "kind": "on_stop",
        "from": ORIGEN,
        "to": DESTINO,
        "text": "{respuesta}",
        "enabled": True,
        "repeat": True,
        "max_fires": 2,
        "fired": 0,
        **extra,
    }
    st.rules.items.append(r)
    return r


def _sin_enfriamiento(r):
    """Corre el ultimo disparo hacia atras: simula que pasaron los 30 s entre turnos."""
    last = rl.local_dt(r["last_fired"]) - dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1)
    r["last_fired"] = last.isoformat(timespec="seconds")
    r["recent_fires"] = [
        last.isoformat(timespec="seconds") if x == r["recent_fires"][-1] else x for x in r["recent_fires"]
    ]


def test_regla_vieja_sin_limit_no_se_apaga_por_el_tope(entorno):
    r = regla()  # como las de OpenSyync: repeat, max_fires chico, sin `limit`
    for _ in range(5):
        rl.fire_on_stop(ORIGEN)
        _sin_enfriamiento(r)
    assert len(entorno) == 5 and r["enabled"] is True and r["fired"] == 5


def test_tope_total_solo_si_se_pide(entorno):
    r = regla(limit="total")
    for _ in range(4):
        rl.fire_on_stop(ORIGEN)
        if r.get("last_fired"):
            _sin_enfriamiento(r)
    assert len(entorno) == 2 and r["enabled"] is False


def test_stop_en_enfriamiento_queda_en_espera_y_sale_agrupado(entorno):
    r = regla()
    rl.fire_on_stop(ORIGEN)
    st.sessions[ORIGEN]["last_reply"] = "segundo"
    rl.fire_on_stop(ORIGEN)
    st.sessions[ORIGEN]["last_reply"] = "tercero"
    rl.fire_on_stop(ORIGEN)
    assert entorno == ["listo"]
    assert r["deferred"]["count"] == 2 and "en espera" in r["last_result"]
    ahora = dt.datetime.now().astimezone()
    assert rl.entregas_diferidas(ahora) == []  # todavia en enfriamiento: no sale ni se pierde
    despues = ahora + dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1)
    listas = rl.entregas_diferidas(despues)
    assert [(x["id"], n) for x, n in listas] == [("rf", 2)] and r["deferred"] is None
    rl.fire_rule(r, agrupados=2)
    rl._on_stop_en_vuelo.discard("rf")
    assert "2 avisos agrupados" in entorno[-1] and entorno[-1].endswith("tercero")


def test_la_ventana_corta_el_bucle_sin_apagar_la_regla(entorno):
    r = regla(rate_max=3, rate_window_s=600)
    for _ in range(6):
        rl.fire_on_stop(ORIGEN)
        if r.get("last_fired") and not r.get("deferred"):
            _sin_enfriamiento(r)
    assert len(entorno) == 3  # proteccion de bucle: 3 en la ventana
    assert r["enabled"] is True and r["deferred"]["count"] == 3
    hasta = rl.local_dt(r["deferred"]["until"])
    primero = min(rl.local_dt(x) for x in r["recent_fires"])
    assert abs((hasta - (primero + dt.timedelta(seconds=600))).total_seconds()) < 2
    assert "limite de 3 cada 10 min" in r["last_result"]
    # antes de que se libere la ventana, sigue esperando (con la hora corrida), no se descarta
    assert rl.entregas_diferidas(hasta - dt.timedelta(seconds=5)) == []
    assert [n for _, n in rl.entregas_diferidas(hasta + dt.timedelta(seconds=1))] == [3]


def test_stop_con_envio_en_curso_no_se_pierde(entorno):
    r = regla()
    rl._on_stop_en_vuelo.add("rf")
    rl.fire_on_stop(ORIGEN)
    assert entorno == [] and r["deferred"]["count"] == 1 and "envio anterior en curso" in r["last_result"]
    rl._on_stop_en_vuelo.discard("rf")
    later = dt.datetime.now().astimezone() + dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1)
    assert [n for _, n in rl.entregas_diferidas(later)] == [1]


def test_un_stop_durante_la_entrega_diferida_abre_otra_espera(entorno):
    r = regla()
    r["deferred"] = {"since": st.now(), "count": 2, "until": st.now()}
    listas = rl.entregas_diferidas(dt.datetime.now().astimezone() + dt.timedelta(seconds=1))
    assert r["deferred"] is None and listas
    rl.fire_on_stop(ORIGEN)  # llega mientras la diferida esta reservada (en vuelo)
    assert r["deferred"]["count"] == 1  # nueva espera: no la borra el envio en curso
    rl.fire_rule(r, agrupados=2)
    assert r["deferred"]["count"] == 1


def test_api_on_stop_por_defecto_frecuencia_y_total_explicito(monkeypatch):
    monkeypatch.setattr(rules_api, "find_enabled", lambda pred: None)
    monkeypatch.setattr(rules_api.rules, "add", lambda r, cap=500: None)
    d = {"kind": "on_stop", "from": ORIGEN, "to": DESTINO, "repeat": True, "max_fires": 30}
    code, r = rules_api._alta_on_stop(d, "x", None, rules_api.on_stop_limits(d)[0])
    assert code == 200 and r["limit"] == "rate" and r["max_fires"] is None
    lim, err = rules_api.on_stop_limits({"limit": "total"})
    assert err is None and lim["limit"] == "total"
    assert rules_api.on_stop_limits({"limit": "mucho"})[1]
    assert rules_api.on_stop_limits({"rate_max": 0})[1]
    assert rules_api.on_stop_limits({"rate_window_s": 10})[1]
    assert rules_api.on_stop_limits({"rate_max": True})[1]


def test_editar_una_agotada_por_el_tope_viejo_la_reactiva(monkeypatch):
    monkeypatch.setattr(rules_api.rules, "save", lambda: None)
    monkeypatch.setattr(rules_api.rules, "publish", lambda: None)
    r = {
        "id": "vieja",
        "kind": "on_stop",
        "from": ORIGEN,
        "to": DESTINO,
        "text": "x",
        "repeat": True,
        "max_fires": 30,
        "fired": 30,
        "enabled": False,
        "disabled_at": st.now(),
    }
    st.rules.items.append(r)
    code, out = rules_api.edit_rule("vieja", {"limit": "rate"})
    assert code == 200 and out["enabled"] is True and "disabled_at" not in out
    code, out = rules_api.edit_rule("vieja", {"limit": "total"})
    assert code == 200 and out["limit"] == "total"
