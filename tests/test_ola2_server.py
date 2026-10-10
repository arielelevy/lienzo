"""Ola 2 del refactor (MEJORAS.md, «Refactor, ola 2»): las pruebas que van ANTES de juntar las
acciones de tarjeta de `Handler` (el tablero) y `PeerHandler` (lo que pide otra PC) en una tabla.

(a) Paridad por accion: con el mismo cuerpo, los dos listeners contestan lo mismo (codigo y cuerpo)
    y tocan la tarjeta igual. Lo propio del tablero (la flecha del envio, copycat) no entra: la PC
    duena solo teclea, la flecha la deja la que envia.
(b) El contrato de los 404: una tarjeta desconocida trae `code: "unknown_session"` (mirror.forward
    lo usa para detectar tarjetas fantasma, y el front para no confundirlas con una ruta vieja) y
    una ruta desconocida no lo trae.

Los dos servers corren en este proceso (como en test_ola1_seguridad.py), con el espejo falso y las
funciones de sessions reemplazadas por unas que anotan lo que se pidio: lo que se compara es el
pedido que le llega a sessions, no lo que sessions hace con el."""

import base64
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
import federation as fed
import pantalla_coda
import rules_api
import state as st

CLAVE_PAR = b"p" * 32
SID = "0a200000-0000-4000-8000-000000000001"  # la tarjeta local
NADIE = "0a200000-0000-4000-8000-0000000000ff"  # no existe en ningun lado
REMOTA = "0a200000-0000-4000-8000-0000000000bb"  # vive en pcB
RID = "req-ola2-0001"
PANTALLA = ["┃ ⚠  Approval Required", "   git status   │ panel", "  ❯ Yes"]


class EspejoFalso:
    """Lo que server.py usa de mirror.MIRROR, con forward anotado y respuestas por defecto 200."""

    def __init__(self):
        self.llamadas = []
        self.duenos = {}
        self.pendientes = []

    def peer_ids(self):
        return ["pcB"]

    def peers_status(self):
        return [{"pc_id": "pcB", "alive": True}]

    def forward(self, pc, method, path, body=None):
        self.llamadas.append((pc, method, path, body))
        return 200, {"ok": True, "reenviado": True}

    def owner_of(self, sid):
        return self.duenos.get(sid)

    def sessions(self):
        return []

    def pending(self):
        return list(self.pendientes)

    def links(self):
        return []

    def rules(self):
        return []

    def rule_owner(self, rid):
        return None


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(server, "log", lambda msg: None)
    peers = tmp_path / "peers.json"
    monkeypatch.setattr(server, "PEERS_FILE", str(peers))
    fed.add_peer(str(peers), {"pc_id": "pcB", "name": "b", "ip": "127.0.0.1", "port": 1, "key": CLAVE_PAR.hex()})
    espejo = EspejoFalso()
    monkeypatch.setattr(server.mirror, "MIRROR", espejo)

    efectos = []

    def anota(nombre, res=None):
        def f(*args, **kw):
            efectos.append((nombre, *[a["session_id"] if isinstance(a, dict) else a for a in args], kw))
            return res(*args, **kw) if callable(res) else res

        return f

    def titular(s, title):
        s["title"] = title
        s["title_source"] = "manual" if title else "auto"

    def detener(s, on):
        s["stopped_by"] = "user" if on else None
        return {"stopped": on}

    def coordinar(s, on):
        s["coordinator"] = on
        return []

    monkeypatch.setattr(server, "send_to_session", anota("send", (200, {"ok": True})))
    monkeypatch.setattr(server, "interrupt_session", anota("interrupt", (200, {"ok": True})))
    monkeypatch.setattr(server, "answer_coda_ask", anota("approve", (200, {"ok": True})))
    monkeypatch.setattr(server, "answer_dialog", anota("dialog", (200, {"ok": True})))
    monkeypatch.setattr(server, "set_title", anota("title", titular))
    monkeypatch.setattr(server, "touch", lambda s: True)
    monkeypatch.setattr(server, "set_stopped", anota("stopped", detener))
    monkeypatch.setattr(server, "set_coordinator", anota("coordinator", coordinar))
    monkeypatch.setattr(server, "save_attachment", anota("attach", lambda sid, name, data: f"C:/adjuntos/{name}"))
    monkeypatch.setattr(
        server,
        "answer_pending",
        anota("pending", lambda rid, *a: (200, {"ok": True}) if rid == RID else (410, {"ok": False, "error": "x"})),
    )
    monkeypatch.setattr(server, "read_screen", lambda s: {"ok": True, "lines": list(PANTALLA)})
    monkeypatch.setattr(server, "add_link", lambda *a, **k: None)  # la flecha es del tablero, no se compara
    monkeypatch.setattr(server, "launch", type("L", (), {"launch": staticmethod(anota("launch", {"ok": True}))}))
    monkeypatch.setattr(server, "ses_retarget_rules", anota("retarget", 0))
    monkeypatch.setattr(server, "restore_local", anota("restaurar", (200, {"restored": [], "failed": []})))

    st.sessions.clear()
    st.sessions[SID] = {"session_id": SID, "agent": "coda", "pid": 4242, "title": "viejo", "repo": "r"}

    tablero = server.QuietServer(("127.0.0.1", 0), server.Handler)
    peer = server.QuietServer(("127.0.0.1", 0), server.PeerHandler)
    for s in (tablero, peer):
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield {
        "tablero": tablero.server_address[1],
        "peer": peer.server_address[1],
        "efectos": efectos,
        "espejo": espejo,
    }
    for s in (tablero, peer):
        s.shutdown()
        s.server_close()
    st.sessions.clear()


def _leer(c):
    r = c.getresponse()
    texto = r.read()
    c.close()
    try:
        return r.status, json.loads(texto) if texto else None
    except ValueError:
        return r.status, texto


def al_tablero(port, method, path, raw: bytes, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=raw, headers={"X-Lienzo": "1", "Content-Type": "application/json", **(headers or {})})
    return _leer(c)


def al_peer(port, method, path, raw: bytes):
    ts, nonce = time.time(), os.urandom(8).hex()
    h = {
        "X-Lienzo-Peer": "pcB",
        "X-Lienzo-Ts": repr(ts),
        "X-Lienzo-Nonce": nonce,
        "X-Lienzo-Sig": fed.sign(CLAVE_PAR, method, path, raw, ts, nonce),
        "Content-Type": "application/json",
    }
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=raw, headers=h)
    return _leer(c)


def _cuerpos(accion, cuerpo):
    """(raw y headers del tablero, raw del peer) de un cuerpo logico. `bytes` viaja igual a los dos;
    el adjunto llega crudo al tablero (con X-Filename) y en base64 adentro del JSON entre PCs."""
    if isinstance(cuerpo, bytes):
        return cuerpo, {}, cuerpo
    if accion == "attach":
        data, nombre = cuerpo["data"], cuerpo["filename"]
        peer = json.dumps({"filename": nombre, "data_b64": base64.b64encode(data).decode("ascii")}).encode()
        return data, {"X-Filename": urllib.parse.quote(nombre)}, peer
    raw = json.dumps(cuerpo).encode()
    return raw, {}, raw


def por_los_dos(e, method, accion, sid, cuerpo):
    """El mismo pedido por el tablero y por el listener de peers: ((codigo, cuerpo), efectos) de cada
    uno."""
    raw_t, h_t, raw_p = _cuerpos(accion, cuerpo)
    ruta = f"/pending/{sid}" if accion == "pending" else f"/sessions/{sid}/{accion}"
    e["efectos"].clear()
    t = al_tablero(e["tablero"], method, ruta, raw_t, h_t)
    ef_t = list(e["efectos"])
    e["efectos"].clear()
    p = al_peer(e["peer"], method, "/peer" + ruta, raw_p)
    ef_p = list(e["efectos"])
    return (t, ef_t), (p, ef_p)


HUELLA = pantalla_coda.huella(PANTALLA)
OTRA_HUELLA = pantalla_coda.huella_comando("gitpushoriginmain")
ADJUNTO = {"filename": "notas ñ.txt", "data": b"hola\x00mundo"}

# (metodo, accion, cuerpos buenos, cuerpos malos). Un cuerpo bueno pasa la validacion (puede
# terminar en 409 si la consola no esta como hace falta); uno malo es un 400 en los dos lados.
CASOS = [
    (
        "POST",
        "send",
        [{"text": "hola"}, {"text": "con adjunto", "attachments": ["C:/a.png"]}, {}],
        [{"text": 5}, {"text": "x", "attachments": "C:/a.png"}, {"attachments": [1]}, b'{"text": ', b"[1]"],
    ),
    ("POST", "interrupt", [{}, b""], []),
    (
        "POST",
        "approve",
        [{"decision": "allow"}, {"decision": "deny"}, {"decision": "allow", "expect": HUELLA}],
        [{"decision": "quizas"}, {}, {"decision": "allow", "expect": "zz"}, b"no es json"],
    ),
    ("POST", "dialog", [{"choice": 2}], [{"choice": "2"}, {"choice": True}, {}, b"{"]),
    ("POST", "attach", [ADJUNTO], [{"filename": "vacio.txt", "data": b""}]),
    ("PUT", "title", [{"title": "nuevo"}, {"title": None}, {}], [{"title": 5}, b"{"]),
    ("PUT", "stopped", [{"on": True}, {"on": False}], [{"on": "si"}, {}, {"on": 1}]),
    ("PUT", "coordinator", [{"on": True}, {"on": False}], [{"on": 1}, {}, {"on": True, "scope": "pc"}]),
    ("POST", "pending", [{"decision": "allow"}, {"decision": "deny", "reason": "no"}], [{"decision": "x"}, {}]),
]


def _sid(accion):
    return RID if accion == "pending" else SID


@pytest.mark.parametrize("method,accion,buenos,malos", CASOS, ids=[c[1] for c in CASOS])
def test_paridad_con_cuerpos_buenos_mismo_efecto(entorno, method, accion, buenos, malos):
    for cuerpo in buenos:
        (t, ef_t), (p, ef_p) = por_los_dos(entorno, method, accion, _sid(accion), cuerpo)
        assert t == p, f"{accion} {cuerpo!r}: tablero {t} y peer {p}"
        assert t[0] == 200, f"{accion} {cuerpo!r}: {t}"
        assert ef_t == ef_p and ef_t, f"{accion} {cuerpo!r}: tablero {ef_t} y peer {ef_p}"


@pytest.mark.parametrize("method,accion,buenos,malos", [c for c in CASOS if c[3]], ids=[c[1] for c in CASOS if c[3]])
def test_paridad_con_cuerpos_malos_mismo_400_y_nada_tocado(entorno, method, accion, buenos, malos):
    for cuerpo in malos:
        (t, ef_t), (p, ef_p) = por_los_dos(entorno, method, accion, _sid(accion), cuerpo)
        assert t == p, f"{accion} {cuerpo!r}: tablero {t} y peer {p}"
        assert t[0] == 400 and isinstance(t[1].get("error"), str), f"{accion} {cuerpo!r}: {t}"
        assert ef_t == [] and ef_p == [], f"{accion} {cuerpo!r}: se toco algo con un cuerpo malo"


def test_aprobar_con_otra_huella_da_el_mismo_409_sin_teclear(entorno):
    (t, ef_t), (p, ef_p) = por_los_dos(entorno, "POST", "approve", SID, {"decision": "allow", "expect": OTRA_HUELLA})
    assert t == p and t[0] == 409 and t[1]["code"] == "expect_mismatch"
    assert ef_t == ef_p == []


def test_adjunto_entre_pcs_con_base64_roto_es_400(entorno):
    raw = json.dumps({"filename": "a.txt", "data_b64": "no es base64!"}).encode()
    code, res = al_peer(entorno["peer"], "POST", f"/peer/sessions/{SID}/attach", raw)
    assert code == 400 and res == {"error": "adjunto invalido"}
    assert entorno["efectos"] == []


def test_adjunto_entre_pcs_con_nombre_que_no_es_texto_no_llega_a_save_attachment(entorno):
    """Hasta la ola 2 PeerHandler le pasaba `filename` tal cual a save_attachment, que con un
    numero revienta (500); el tablero siempre le pasa un texto (sale de X-Filename)."""
    raw = json.dumps({"filename": 5, "data_b64": base64.b64encode(b"x").decode()}).encode()
    assert al_peer(entorno["peer"], "POST", f"/peer/sessions/{SID}/attach", raw)[0] == 200
    assert [ef[2] for ef in entorno["efectos"]] == ["adjunto.bin"]


ACCIONES_DE_TARJETA = [c for c in CASOS if c[1] != "pending"]


@pytest.mark.parametrize("method,accion,buenos,malos", ACCIONES_DE_TARJETA, ids=[c[1] for c in ACCIONES_DE_TARJETA])
def test_tarjeta_desconocida_da_el_mismo_404_con_unknown_session(entorno, method, accion, buenos, malos):
    (t, ef_t), (p, ef_p) = por_los_dos(entorno, method, accion, NADIE, buenos[0])
    assert t == p == (404, server.no_session())
    assert t[1]["code"] == "unknown_session"
    assert ef_t == ef_p == []


def test_pedido_de_permiso_desconocido_da_lo_mismo_en_los_dos(entorno):
    (t, _), (p, _) = por_los_dos(entorno, "POST", "pending", "req-que-no-existe", {"decision": "allow"})
    assert t == p and t[0] == 410


_POST_MALOS = [(c[0], c[1], c[3][0]) for c in ACCIONES_DE_TARJETA if c[0] == "POST" and c[3]]
_PUT_MALOS = [(c[0], c[1], c[3][0]) for c in ACCIONES_DE_TARJETA if c[0] == "PUT" and c[3]]


@pytest.mark.parametrize("method,accion,malo", _POST_MALOS, ids=[c[1] for c in _POST_MALOS])
def test_cuerpo_malo_a_tarjeta_desconocida_mismo_codigo_post(entorno, method, accion, malo):
    (t, ef_t), (p, ef_p) = por_los_dos(entorno, method, accion, NADIE, malo)
    assert t[0] == p[0], f"{accion}: tablero {t} y peer {p}"
    assert ef_t == ef_p == []


@pytest.mark.parametrize("method,accion,malo", _PUT_MALOS, ids=[c[1] for c in _PUT_MALOS])
def test_cuerpo_malo_a_tarjeta_desconocida_mismo_codigo_put(entorno, method, accion, malo):
    (t, ef_t), (p, ef_p) = por_los_dos(entorno, method, accion, NADIE, malo)
    assert t[0] == p[0], f"{accion}: tablero {t} y peer {p}"
    assert ef_t == ef_p == []


# --- reenvio a la PC duena: el formato entre PCs no cambia con el refactor -------------------

REENVIOS = [
    ("POST", "send", {"text": "hola", "from": SID}, {"text": "hola", "from": SID}),
    ("POST", "interrupt", b"", {}),
    ("POST", "approve", {"decision": "allow"}, {"decision": "allow"}),
    ("POST", "dialog", {"choice": 1}, {"choice": 1}),
    (
        "POST",
        "attach",
        ADJUNTO,
        {"filename": ADJUNTO["filename"], "data_b64": base64.b64encode(ADJUNTO["data"]).decode("ascii")},
    ),
    ("PUT", "title", {"title": "x", "otro": 1}, {"title": "x"}),
    ("PUT", "stopped", {"on": True, "otro": 1}, {"on": True}),
    ("PUT", "coordinator", {"on": True}, {"on": True}),
]


@pytest.mark.parametrize("method,accion,cuerpo,esperado", REENVIOS, ids=[r[1] for r in REENVIOS])
def test_tarjeta_de_otra_pc_se_reenvia_con_el_mismo_cuerpo(entorno, method, accion, cuerpo, esperado):
    entorno["espejo"].duenos[REMOTA] = "pcB"
    raw, h, _ = _cuerpos(accion, cuerpo)
    code, res = al_tablero(entorno["tablero"], method, f"/sessions/{REMOTA}/{accion}", raw, h)
    assert (code, res) == (200, {"ok": True, "reenviado": True})
    assert entorno["espejo"].llamadas == [("pcB", method, f"/sessions/{REMOTA}/{accion}", esperado)]
    assert entorno["efectos"] == []


def test_permiso_de_otra_pc_se_reenvia(entorno):
    entorno["espejo"].pendientes = [{"request_id": "req-remoto", "pc": "pcB"}]
    code, _ = al_tablero(entorno["tablero"], "POST", "/pending/req-remoto", json.dumps({"decision": "deny"}).encode())
    assert code == 200
    assert entorno["espejo"].llamadas == [("pcB", "POST", "/pending/req-remoto", {"decision": "deny"})]


# --- launch, retarget y restaurar: las mismas validaciones en los dos lados -------------------


def test_launch_valida_igual_y_lanza_igual(entorno):
    for malo in ({}, {"cwd": "C:/x"}, {"cwd": " ", "agent": "claude"}, {"cwd": "C:/x", "agent": "claude", "title": 5}):
        t = al_tablero(entorno["tablero"], "POST", "/sessions/launch", json.dumps(malo).encode())
        p = al_peer(entorno["peer"], "POST", "/peer/launch", json.dumps(malo).encode())
        assert t == p == (400, {"error": "cwd y agent son obligatorios"})
    bueno = {"cwd": "C:/x", "agent": "claude", "title": "t", "model": "opus"}
    entorno["efectos"].clear()
    t = al_tablero(entorno["tablero"], "POST", "/sessions/launch", json.dumps(bueno).encode())
    ef_t = list(entorno["efectos"])
    entorno["efectos"].clear()
    p = al_peer(entorno["peer"], "POST", "/peer/launch", json.dumps(bueno).encode())
    assert t == p and t[0] == 200
    assert ef_t == entorno["efectos"] == [("launch", "C:/x", "t", "claude", {"model": "opus", "distro": None})]


def test_launch_en_otra_pc_se_reenvia_con_el_mismo_cuerpo(entorno):
    d = {"pc": "pcB", "cwd": "C:/x", "agent": "claude", "title": "t", "otro": 1}
    code, _ = al_tablero(entorno["tablero"], "POST", "/sessions/launch", json.dumps(d).encode())
    assert code == 200
    assert entorno["espejo"].llamadas == [("pcB", "POST", "/launch", {"cwd": "C:/x", "title": "t", "agent": "claude"})]


def test_retarget_valida_igual(entorno):
    for malo in ({}, {"old": "a"}, {"old": 1, "new": "b"}):
        t = al_tablero(entorno["tablero"], "POST", "/rules/retarget", json.dumps(malo).encode())
        p = al_peer(entorno["peer"], "POST", "/peer/rules/retarget", json.dumps(malo).encode())
        assert t == p == (400, {"error": "hace falta old y new"})
    d = {"old": "a", "new": "b"}
    code, res = al_tablero(entorno["tablero"], "POST", "/rules/retarget", json.dumps(d).encode())
    assert code == 200 and res == {"ok": True, "n": 0, "unreachable": []}
    assert ("pcB", "POST", "/rules/retarget", d) in entorno["espejo"].llamadas
    assert al_peer(entorno["peer"], "POST", "/peer/rules/retarget", json.dumps(d).encode()) == (
        200,
        {"ok": True, "n": 0},
    )


def test_restaurar_local_y_reenviado(entorno):
    d = {"session_id": "abc"}
    t = al_tablero(entorno["tablero"], "POST", "/restaurar", json.dumps(d).encode())
    p = al_peer(entorno["peer"], "POST", "/peer/restaurar", json.dumps(d).encode())
    assert t == p and t[0] == 200
    malo = json.dumps({"pc": 5}).encode()
    assert al_tablero(entorno["tablero"], "POST", "/restaurar", malo) == (400, {"error": "pc debe ser un pc_id"})
    assert al_peer(entorno["peer"], "POST", "/peer/restaurar", malo) == (400, {"error": "pc debe ser un pc_id"})
    remoto = {"pc": "pcB", "all": True, "limit_by_memory": True, "otro": 1}
    assert al_tablero(entorno["tablero"], "POST", "/restaurar", json.dumps(remoto).encode())[0] == 200
    assert entorno["espejo"].llamadas[-1] == ("pcB", "POST", "/restaurar", {"all": True, "limit_by_memory": True})


# --- (b) el contrato de los 404 --------------------------------------------------------------


@pytest.mark.parametrize("vista", server.SESSION_VIEWS)
def test_vista_de_tarjeta_desconocida_trae_unknown_session(entorno, vista):
    assert al_tablero(entorno["tablero"], "GET", f"/sessions/{NADIE}/{vista}", b"") == (404, server.no_session())
    assert al_peer(entorno["peer"], "GET", f"/peer/sessions/{NADIE}/{vista}", b"") == (404, server.no_session())


@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
@pytest.mark.parametrize("sid", [SID, NADIE])
def test_ruta_desconocida_del_tablero_no_trae_unknown_session(entorno, method, sid):
    code, res = al_tablero(entorno["tablero"], method, f"/sessions/{sid}/no-existe", b"{}")
    assert code == 404 and res == {"error": "ruta desconocida"}


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_ruta_desconocida_suelta_no_trae_unknown_session(entorno, method):
    assert al_tablero(entorno["tablero"], method, "/no-existe", b"") == (404, {"error": "ruta desconocida"})
    assert al_peer(entorno["peer"], method, "/peer/no-existe", b"") == (404, {"error": "ruta desconocida"})


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_ruta_desconocida_entre_pcs_con_tarjeta_conocida_no_trae_unknown_session(entorno, method):
    code, res = al_peer(entorno["peer"], method, f"/peer/sessions/{SID}/no-existe", b"{}")
    assert code == 404 and res == {"error": "ruta desconocida"}


# hasta la ola 2 PeerHandler buscaba la tarjeta antes de mirar la accion, asi que una accion que
# no existe sobre una tarjeta que tampoco daba 404 con unknown_session (y mirror.forward la tomaba
# por fantasma); Handler mira la accion primero y da «ruta desconocida»
@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_ruta_desconocida_entre_pcs_con_tarjeta_desconocida_no_trae_unknown_session(entorno, method):
    code, res = al_peer(entorno["peer"], method, f"/peer/sessions/{NADIE}/no-existe", b"{}")
    assert code == 404 and res == {"error": "ruta desconocida"}


# --- la API de reglas en rules_api.py --------------------------------------------------------


def test_server_reexporta_la_api_de_reglas():
    for nombre in ("create_rule", "edit_rule", "check_rule", "at_fields", "find_enabled"):
        assert getattr(server, nombre) is getattr(rules_api, nombre)


def test_dos_altas_iguales_a_la_vez_dejan_una_sola_regla(tmp_path, monkeypatch):
    """S11 (como en test_ola1_seguridad.py, que parcha server.find_enabled: desde que la API de
    reglas vive en rules_api, ese parche ya no ensancha la ventana). El chequeo de duplicado y el
    alta, bajo un solo lock."""
    monkeypatch.setattr(st.rules, "path", str(tmp_path / "rules.json"))
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(server.mirror, "MIRROR", EspejoFalso())
    st.rules.items.clear()
    st.sessions.clear()
    a, b = "f0000000-0000-4000-8000-00000000000a", "f0000000-0000-4000-8000-00000000000b"
    for sid in (a, b):
        st.sessions[sid] = {"session_id": sid, "agent": "claude", "pid": 1}
    original = rules_api.find_enabled

    def lento(pred):
        r = original(pred)
        time.sleep(0.2)  # ensancha la ventana entre «no hay otra igual» y el alta
        return r

    monkeypatch.setattr(rules_api, "find_enabled", lento)
    d = {"kind": "on_stop", "from": a, "to": b, "text": "seguí"}
    codigos = []
    hilos = [threading.Thread(target=lambda: codigos.append(server.create_rule(dict(d))[0])) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    try:
        assert sorted(codigos) == [200, 409] and len(st.rules.items) == 1
    finally:
        st.rules.items.clear()
        st.sessions.clear()


# --- JsonHandler y el snapshot ----------------------------------------------------------------


def test_el_500_entre_pcs_trae_error_id_y_no_el_texto_de_la_excepcion(entorno, monkeypatch):
    """La base comun: antes el 500 de PeerHandler no traia `error_id` (el del tablero si)."""
    secreto = r"C:\Users\alguien\.lienzo\x.json"
    monkeypatch.setattr(server.health, "snapshot", lambda: (_ for _ in ()).throw(RuntimeError(secreto)))
    for code, res in (
        al_peer(entorno["peer"], "GET", "/peer/health", b""),
        al_tablero(entorno["tablero"], "GET", "/peers", b""),
    ):
        assert code == 500 and secreto not in json.dumps(res)
        assert len(res["error_id"]) == 8 and res["error_id"] in res["error"]


def test_snapshot_del_tablero_lleva_el_espejo_y_el_de_otra_pc_no(entorno, monkeypatch):
    monkeypatch.setattr(entorno["espejo"], "sessions", lambda: [{"session_id": REMOTA, "pc": "pcB"}])
    tablero = json.loads(server.snapshot_json(con_espejo=True))
    peer = json.loads(server.snapshot_json(con_espejo=False))
    assert tablero["type"] == peer["type"] == "snapshot" and "build" in tablero and "build" in peer
    assert [x["session_id"] for x in tablero["sessions"]] == [SID, REMOTA]
    assert [x["session_id"] for x in peer["sessions"]] == [SID]
    assert set(tablero) == set(peer) == {"type", "sessions", "pending", "links", "rules", "build"}
