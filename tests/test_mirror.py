"""Tests de lienzo/mirror.py (plan-multi-pc-2026-09-26.md §3.3/§3.4): snapshot y eventos del SSE
de un peer, owner_of, la union sessions/pending/links/rules con `pc` tageado, salud cada
HEALTH_EVERY_S, y el enrutado de comandos (forward). Todo con un transporte doble (sin red ni
threads reales): `subscribe` guarda los callbacks para que el test dispare los eventos a mano, y
`request`/`get` devuelven lo que el test configuro (o levantan OSError, para simular el peer
caido)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# El orden importa: `from lienzo import server` es lo que agrega lienzo/ al sys.path (ver
# test_server.py); recien despues resuelven los imports sueltos de abajo.
from lienzo import server  # noqa: F401
import federation as fed
import mirror as mi


class FakeClient:
    def __init__(self):
        self.stopped = False
        self.reconnects = 0

    def reconnect(self):
        self.reconnects += 1

    def stop(self, timeout=5.0):
        self.stopped = True


class FakeTransport:
    """Doble de federation.Transport: sin red, con lo que el test configura de antemano."""

    def __init__(self, health=None, raise_on_health=False, request_responses=None, raise_on_request=False):
        self.health = health if health is not None else {"mem_free_gb": 4.0, "cpu_pct": 10.0, "temp_c": 50.0}
        self.raise_on_health = raise_on_health
        self.request_responses = request_responses or {}
        self.raise_on_request = raise_on_request
        self.subscribed: list[dict] = []
        self.health_calls = 0

    def get(self, peer, path):
        if path == "/peer/health":
            self.health_calls += 1
            if self.raise_on_health:
                raise OSError("peer caido")
            return self.health
        raise NotImplementedError(path)

    def post(self, peer, path, body):
        raise NotImplementedError

    def put(self, peer, path, body):
        raise NotImplementedError

    def delete(self, peer, path):
        raise NotImplementedError

    def request(self, peer, method, path, body=None):
        if self.raise_on_request:
            raise OSError("peer caido")
        try:
            return self.request_responses[(method, path)]
        except KeyError:
            raise AssertionError(f"el doble no tiene configurada ({method}, {path})") from None

    def subscribe(self, peer, path, on_event, on_reconnect=None, backoff=None):
        c = FakeClient()
        self.subscribed.append(
            {"peer": peer, "path": path, "on_event": on_event, "on_reconnect": on_reconnect, "client": c}
        )
        return c


def _mirror(transport=None):
    return mi.Mirror(transport=transport or FakeTransport())


def _connect(m, transport, pc_id="p1", name="notebook", color="#4C6EF5", host="10.0.0.5", port=7322):
    m.connect(pc_id, {"name": name, "color": color}, host, port, b"k" * 32, "yo")
    return transport.subscribed[-1]


# --- conexion ------------------------------------------------------------------------------


def test_connect_se_suscribe_a_peer_events_con_la_conexion_firmada():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1", host="10.0.0.5", port=7322)
    assert sub["path"] == "/peer/events"
    assert sub["peer"] == fed.PeerConn(host="10.0.0.5", port=7322, key=b"k" * 32, self_pc_id="yo")
    assert m.peer_ids() == ["p1"]


def test_connect_de_nuevo_reemplaza_y_para_el_cliente_viejo():
    t = FakeTransport()
    m = _mirror(t)
    _connect(m, t, pc_id="p1", port=7322)
    viejo = t.subscribed[-1]["client"]
    _connect(m, t, pc_id="p1", port=7331)  # el mismo pc_id, otra vez (reconexion manual)
    assert viejo.stopped is True
    assert m.peer_ids() == ["p1"]


def test_disconnect_saca_el_peer_y_para_su_cliente():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    m.disconnect("p1")
    assert m.peer_ids() == []
    assert sub["client"].stopped is True


# --- snapshot y eventos ----------------------------------------------------------------------


def test_snapshot_llena_sesiones_pendientes_links_y_reglas():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"](
        {
            "type": "snapshot",
            "sessions": [{"session_id": "a", "pc": "p1", "title": "algo"}],
            "pending": [{"request_id": "r1", "session_id": "a", "pc": "p1"}],
            "links": [{"id": "l1", "pc": "p1"}],
            "rules": [{"id": "ru1", "pc": "p1"}],
        }
    )
    assert [s["session_id"] for s in m.sessions()] == ["a"]
    assert [p["request_id"] for p in m.pending()] == ["r1"]
    assert [l["id"] for l in m.links()] == ["l1"]
    assert [r["id"] for r in m.rules()] == ["ru1"]


def test_session_event_agrega_o_actualiza_una_sola_tarjeta():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "snapshot", "sessions": [{"session_id": "a", "pc": "p1"}]})
    sub["on_event"]({"type": "session", "session": {"session_id": "b", "pc": "p1", "title": "nueva"}})
    ids = {s["session_id"] for s in m.sessions()}
    assert ids == {"a", "b"}
    sub["on_event"]({"type": "session", "session": {"session_id": "a", "pc": "p1", "title": "cambio"}})
    a = next(s for s in m.sessions() if s["session_id"] == "a")
    assert a["title"] == "cambio"


def test_removed_event_saca_la_tarjeta():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "snapshot", "sessions": [{"session_id": "a", "pc": "p1"}]})
    sub["on_event"]({"type": "removed", "session_id": "a"})
    assert m.sessions() == []


def test_pending_links_rules_reemplazan_la_lista_entera_no_se_acumulan():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "pending", "pending": [{"request_id": "r1", "session_id": "a"}]})
    sub["on_event"]({"type": "pending", "pending": [{"request_id": "r2", "session_id": "a"}]})
    assert [p["request_id"] for p in m.pending()] == ["r2"]
    sub["on_event"]({"type": "links", "links": [{"id": "l1"}, {"id": "l2"}]})
    sub["on_event"]({"type": "links", "links": [{"id": "l3"}]})
    assert [l["id"] for l in m.links()] == ["l3"]


def test_tag_completa_pc_si_el_item_no_lo_trae():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "pending", "pending": [{"request_id": "r1", "session_id": "a"}]})
    sub["on_event"]({"type": "links", "links": [{"id": "l1"}]})
    sub["on_event"]({"type": "rules", "rules": [{"id": "ru1"}]})
    assert m.pending()[0]["pc"] == "p1"
    assert m.links()[0]["pc"] == "p1"
    assert m.rules()[0]["pc"] == "p1"


def test_ping_actualiza_last_seen_sin_tocar_nada_mas():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "snapshot", "sessions": [{"session_id": "a", "pc": "p1"}]})
    antes = m._peers["p1"].last_seen
    time.sleep(0.01)
    sub["on_event"]({"type": "ping", "build": "x"})
    assert m._peers["p1"].last_seen > antes
    assert [s["session_id"] for s in m.sessions()] == ["a"]  # no lo toco


def test_on_change_se_llama_en_cada_evento_que_cambia_algo():
    llamadas = []
    t = FakeTransport()
    m = mi.Mirror(transport=t, on_change=lambda: llamadas.append(1))
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "snapshot", "sessions": []})
    assert len(llamadas) == 1
    sub["on_event"]({"type": "ping"})
    assert len(llamadas) == 1, "un ping no es un cambio: no dispara on_change"


# --- owner_of ------------------------------------------------------------------------------


def test_owner_of_encuentra_la_sesion_en_su_peer():
    t = FakeTransport()
    m = _mirror(t)
    sub = _connect(m, t, pc_id="p1")
    sub["on_event"]({"type": "snapshot", "sessions": [{"session_id": "a", "pc": "p1"}]})
    assert m.owner_of("a") == "p1"


def test_owner_of_desconocida_da_none():
    m = _mirror()
    assert m.owner_of("no-existe") is None


# --- salud -----------------------------------------------------------------------------------


def test_poll_health_guarda_la_salud_y_actualiza_last_seen():
    t = FakeTransport(health={"mem_free_gb": 2.0, "cpu_pct": 50.0, "temp_c": 70.0})
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    m._poll_health("p1")
    assert m._peers["p1"].health == {"mem_free_gb": 2.0, "cpu_pct": 50.0, "temp_c": 70.0}
    assert t.health_calls == 1


def test_poll_health_con_peer_caido_no_revienta_y_no_actualiza_nada():
    t = FakeTransport(raise_on_health=True)
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    m._poll_health("p1")  # no debe levantar
    assert m._peers["p1"].health is None


def test_poll_health_que_falla_lo_avisa_una_vez_y_avisa_cuando_vuelve():
    """Un peer que no contesta la salud no puede fallar en silencio, pero tampoco llenar el log
    con la misma linea cada 15 s."""
    t = FakeTransport(raise_on_health=True)
    m = _mirror(t)
    avisos: list[str] = []
    m.log = avisos.append
    _connect(m, t, pc_id="p1", name="oficina")
    m._poll_health("p1")
    m._poll_health("p1")
    assert avisos == ["→ oficina GET /health: OSError: peer caido"]
    t.raise_on_health = False
    m._poll_health("p1")
    m._poll_health("p1")
    assert avisos[1:] == ["→ oficina GET /health: responde de nuevo"]


def test_peers_status_recien_conectado_sin_salud_previa_no_esta_vivo():
    t = FakeTransport()
    m = _mirror(t)
    _connect(m, t, pc_id="p1", name="oficina", color="#111111")
    estado = m.peers_status()
    assert estado == [
        {
            "pc_id": "p1",
            "name": "oficina",
            "color": "#111111",
            "alive": False,
            "last_seen": None,
            "local": False,
            "health": None,
        }
    ]


def test_peers_status_vivo_tras_salud_reciente():
    t = FakeTransport(health={"mem_free_gb": 3.0, "cpu_pct": 20.0, "temp_c": 60.0})
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    m._poll_health("p1")
    estado = m.peers_status()[0]
    assert estado["alive"] is True
    assert estado["health"] == {"mem_free_gb": 3.0, "cpu_pct": 20.0, "temp_c": 60.0}
    assert estado["last_seen"] is not None


def test_peers_status_caido_por_falta_de_actividad_no_muestra_salud_vieja():
    t = FakeTransport(health={"mem_free_gb": 3.0, "cpu_pct": 20.0, "temp_c": 60.0})
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    m._poll_health("p1")
    m._peers["p1"].last_seen = time.time() - (mi.PEER_TIMEOUT_S + 1)
    estado = m.peers_status()[0]
    assert estado["alive"] is False
    assert estado["health"] is None, "salud vieja de un peer caido no se muestra: son datos viejos"


# --- forward (enrutado de comandos) -----------------------------------------------------------


def test_forward_agrega_el_prefijo_peer_y_devuelve_codigo_y_cuerpo_tal_cual():
    t = FakeTransport(request_responses={("POST", "/peer/sessions/a/send"): (200, {"ok": True})})
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    code, body = m.forward("p1", "POST", "/sessions/a/send", {"text": "hola"})
    assert (code, body) == (200, {"ok": True})


def test_forward_propaga_un_409_del_peer_tal_cual():
    t = FakeTransport(
        request_responses={("POST", "/peer/sessions/a/interrupt"): (409, {"ok": False, "error": "no corre"})}
    )
    m = _mirror(t)
    _connect(m, t, pc_id="p1")
    assert m.forward("p1", "POST", "/sessions/a/interrupt") == (409, {"ok": False, "error": "no corre"})


def test_forward_a_un_peer_desconocido_da_503():
    m = _mirror()
    code, body = m.forward("no-existe", "GET", "/sessions/a/screen")
    assert code == 503
    assert "error" in body


def test_forward_a_un_peer_caido_da_503_con_su_nombre():
    t = FakeTransport(raise_on_request=True)
    m = _mirror(t)
    _connect(m, t, pc_id="p1", name="notebook")
    code, body = m.forward("p1", "GET", "/sessions/a/screen")
    assert code == 503
    assert "notebook" in body["error"]
