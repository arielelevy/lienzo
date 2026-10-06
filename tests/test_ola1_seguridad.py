"""Fase 0 del plan de refactor del 2026-10-04 (docs/plan-refactor-2026-10-04.md), lo de seguridad
y procesos: subproc.correr (0.5) y lo que cambia en el server (0.2, 0.3, 0.7, 0.11 y S8-S17)."""

import http.client
import json
import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
import federation as fed
import pantalla_coda
import state as st
import subproc

PY = sys.executable


def test_correr_devuelve_salida_codigo_y_entrada():
    rc, out, err = subproc.correr(
        [PY, "-c", "import sys; d = sys.stdin.read(); print(d.upper()); sys.stderr.write('e'); sys.exit(3)"],
        entrada="hola ñ",
        env={"PYTHONIOENCODING": "utf-8"},
        timeout=20,
    )
    assert rc == 3 and out.strip() == "HOLA Ñ" and err == "e"


def test_correr_sin_entrada_no_hereda_stdin():
    rc, out, _ = subproc.correr([PY, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout=20)
    assert rc == 0 and out.strip() == "''"


def test_correr_mata_el_arbol_al_vencer_y_no_se_cuelga():
    """El caso del Git Credential Manager: un nieto que hereda la salida y no termina. Con
    tuberías la lectura quedaba colgada aunque el hijo muriera; con archivos y el árbol muerto,
    vuelve apenas vence el plazo."""
    nieto = "import time; time.sleep(60)"
    hijo = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {nieto!r}]); print('arranco', flush=True); time.sleep(60)"
    t0 = time.monotonic()
    rc, out, err = subproc.correr([PY, "-c", hijo], timeout=1.5)
    assert time.monotonic() - t0 < 15
    assert rc == subproc.VENCIDO
    assert "arranco" in out and "no termino" in err


def test_correr_con_un_programa_que_no_existe_no_levanta():
    rc, out, err = subproc.correr(["no-existe-este-programa-lienzo"], timeout=5)
    assert rc == subproc.NO_ARRANCO and out == "" and "no se pudo lanzar" in err


def test_correr_sin_prompts_apaga_las_preguntas_de_git():
    codigo = "import os; print(os.environ.get('GIT_TERMINAL_PROMPT'), os.environ.get('GCM_INTERACTIVE'))"
    assert subproc.correr([PY, "-c", codigo], timeout=20, sin_prompts=True)[1].split() == ["0", "never"]


# --- el server: un Handler real en 127.0.0.1 y un espejo falso --------------------------------


class EspejoFalso:
    """Lo que server.py usa de mirror.MIRROR: peers, quién está vivo y forward con respuestas
    armadas por (método, ruta) -> (código, cuerpo)."""

    def __init__(self, vivos=("pcB",), muertos=(), respuestas=None):
        self.vivos, self.muertos = list(vivos), list(muertos)
        self.respuestas = respuestas or {}
        self.llamadas = []
        self.duenos = {}

    def peer_ids(self):
        return self.vivos + self.muertos

    def peers_status(self):
        return [{"pc_id": p, "alive": p in self.vivos} for p in self.peer_ids()]

    def forward(self, pc, method, path, body=None):
        self.llamadas.append((pc, method, path, body))
        if pc not in self.vivos:
            return 503, {"error": f"sin conexión con {pc}"}
        r = self.respuestas.get((pc, method, path), (200, {"ok": True}))
        return r(body) if callable(r) else r

    def owner_of(self, sid):
        return self.duenos.get(sid)

    def sessions(self):
        return []

    def pending(self):
        return []

    def links(self):
        return []

    def rules(self):
        return []

    def rule_owner(self, rid):
        return None


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(server, "CONFIG_PENDIENTE_FILE", str(tmp_path / "config_pendiente.json"))
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    logs = []
    monkeypatch.setattr(server, "log", logs.append)
    espejo = EspejoFalso()
    monkeypatch.setattr(server.mirror, "MIRROR", espejo)
    st.sessions.clear()
    yield {"tmp": tmp_path, "espejo": espejo, "logs": logs}
    st.sessions.clear()


@pytest.fixture
def srv(aislado):
    s = server.QuietServer(("127.0.0.1", 0), server.Handler)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1]
    s.shutdown()
    s.server_close()


def leer_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def pedir(port, method, path, body=None, headers=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    datos = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"X-Lienzo": "1", "Content-Type": "application/json", **(headers or {})}
    c.request(method, path, body=datos, headers=h)
    r = c.getresponse()
    texto = r.read()
    c.close()
    try:
        cuerpo = json.loads(texto) if texto else None
    except ValueError:
        cuerpo = texto
    return r.status, dict(r.getheaders()), cuerpo


# S14 + 0.3: fan_out y auto-aprobar que no llega a una PC


def test_fan_out_separa_las_que_contestaron_de_las_que_no(aislado):
    aislado["espejo"].muertos = ["pcC"]
    ok, fallaron = server.fan_out("POST", "/rules/retarget", {"old": "a", "new": "b"})
    assert set(ok) == {"pcB"} and set(fallaron) == {"pcC"} and "sin conexión" in fallaron["pcC"]


def test_put_config_auto_aprobar_dice_que_pc_no_lo_recibio_y_lo_reintenta(srv, aislado):
    """Antes contestaba 200 con el valor nuevo aunque otra PC no lo hubiera recibido: apagar
    auto-aprobar podía dejarlo prendido en una PC caída, para siempre."""
    espejo = aislado["espejo"]
    espejo.muertos = ["pcC"]
    code, _, res = pedir(srv, "PUT", "/config", {"auto_aprobar": False})
    assert code == 200 and res["auto_aprobar"] is False
    assert res["peers"]["pcB"] == "ok" and res["peers"]["pcC"].startswith("sin conexión")
    assert leer_json(aislado["tmp"] / "config_pendiente.json") == {"pcC": False}
    # pcC vuelve: el reintento le manda el valor y deja de estar pendiente
    espejo.vivos, espejo.muertos = ["pcB", "pcC"], []
    espejo.llamadas.clear()
    server.reintentar_config_peers()
    assert espejo.llamadas == [("pcC", "PUT", "/config", {"auto_aprobar": False})]
    assert leer_json(aislado["tmp"] / "config_pendiente.json") == {}


def test_put_config_sin_auto_aprobar_no_trae_peers(srv, aislado):
    code, _, res = pedir(srv, "PUT", "/config", {"auto_continue": True})
    assert code == 200 and "peers" not in res and aislado["espejo"].llamadas == []


def test_retarget_dice_que_pcs_no_contestaron(srv, aislado):
    aislado["espejo"].muertos = ["pcC"]
    aislado["espejo"].respuestas[("pcB", "POST", "/rules/retarget")] = (200, {"ok": True, "n": 2})
    code, _, res = pedir(srv, "POST", "/rules/retarget", {"old": "a", "new": "b"})
    assert code == 200 and res["n"] == 2 and res["unreachable"] == ["pcC"]


def test_restaurables_avisa_las_pcs_que_no_contestaron_en_un_header(srv, aislado):
    aislado["espejo"].muertos = ["pcC"]
    aislado["espejo"].respuestas[("pcB", "GET", "/restaurables")] = (500, {"error": "x"})
    code, headers, res = pedir(srv, "GET", "/restaurables")
    assert code == 200 and isinstance(res, list)
    assert headers.get("X-Lienzo-Unreachable") == "pcB,pcC"


# 0.2: aprobar contra la huella del comando que se juzgó

PANTALLA = ["┃ ⚠  Approval Required", "   git status   │ panel", "  ❯ Yes"]


@pytest.fixture
def coda(aislado, monkeypatch):
    sid = "c0da0000-0000-4000-8000-000000000001"
    st.sessions[sid] = {"session_id": sid, "agent": "coda", "pid": 4242, "needs": {"coda_at": "x"}}
    contestados = []
    monkeypatch.setattr(server, "read_screen", lambda s: {"ok": True, "lines": list(PANTALLA)})
    monkeypatch.setattr(server, "answer_coda_ask", lambda s, d: contestados.append(d) or (200, {"ok": True}))
    return sid, contestados


def test_approve_con_expect_que_no_coincide_da_409_y_no_teclea(srv, coda):
    sid, contestados = coda
    otra = pantalla_coda.huella_comando("gitpushoriginmain")
    code, _, res = pedir(srv, "POST", f"/sessions/{sid}/approve", {"decision": "allow", "expect": otra})
    assert code == 409 and res["error"] == "el comando en pantalla cambió" and contestados == []


def test_approve_con_expect_que_coincide_teclea(srv, coda):
    sid, contestados = coda
    buena = pantalla_coda.huella(PANTALLA)
    code, _, _ = pedir(srv, "POST", f"/sessions/{sid}/approve", {"decision": "allow", "expect": buena})
    assert code == 200 and contestados == ["allow"]


def test_approve_sin_expect_sigue_como_antes_y_expect_malformado_da_400(srv, coda):
    sid, contestados = coda
    assert pedir(srv, "POST", f"/sessions/{sid}/approve", {"decision": "deny"})[0] == 200
    assert pedir(srv, "POST", f"/sessions/{sid}/approve", {"decision": "allow", "expect": "zz"})[0] == 400
    assert contestados == ["deny"]


def test_la_huella_del_skill_y_la_del_server_son_la_misma():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "lienzo"))
    import aprobador

    assert aprobador.huella(PANTALLA) == pantalla_coda.huella(PANTALLA) == server.huella_de_pantalla(PANTALLA)


# 0.7: sin autenticar no se lee el cuerpo

TUNEL = {"CF-Connecting-IP": "203.0.113.9"}


def test_por_el_tunel_sin_cookie_todo_da_401_salvo_las_rutas_publicas(srv, monkeypatch):
    monkeypatch.setattr(server.auth, "check", lambda cookie: False)
    for method, path in (("GET", "/sessions"), ("GET", "/config"), ("POST", "/rules"), ("PUT", "/config")):
        assert pedir(srv, method, path, {}, TUNEL)[0] == 401, (method, path)
    assert pedir(srv, "DELETE", "/rules/x", None, TUNEL)[0] == 401
    for path in ("/health", "/auth"):
        assert pedir(srv, "GET", path, None, TUNEL)[0] == 200, path
    assert server.es_publica("POST", ["login"]) and server.es_publica("GET", ["assets", "x.js"])
    assert not server.es_publica("GET", ["docs", "x.md"]) and not server.es_publica("POST", ["sessions", "x", "send"])


def test_desde_la_pc_o_la_lan_no_pide_login(srv):
    assert pedir(srv, "GET", "/sessions")[0] == 200
    assert pedir(srv, "PUT", "/config", {"auto_continue": True})[0] == 200


def test_sin_autenticar_contesta_401_sin_esperar_el_cuerpo(srv, monkeypatch):
    """Antes _prepare leía hasta 8 MB (64 MB en /attach) antes de mirar la cookie: un anónimo por
    el túnel ocupaba un hilo y memoria. Ahora contesta 401 y cierra sin leer: un cuerpo declarado
    y nunca enviado ya no retiene la conexión 30 s."""
    monkeypatch.setattr(server.auth, "check", lambda cookie: False)
    s = socket.create_connection(("127.0.0.1", srv), timeout=5)
    s.sendall(
        b"POST /sessions/x/attach HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Lienzo: 1\r\n"
        b"CF-Connecting-IP: 203.0.113.9\r\nContent-Length: 60000000\r\n\r\n"
    )
    t0 = time.monotonic()
    resp = s.recv(4096)
    s.close()
    assert resp.startswith(b"HTTP/1.1 401") and time.monotonic() - t0 < 4
    assert b"Connection: close" in resp


def test_max_body_es_mayor_solo_en_attach():
    assert server.max_body("POST", ["sessions", "x", "attach"]) == server.MAX_ATTACH
    assert server.max_body("POST", ["sessions", "x", "send"]) == server.MAX_BODY


# NUEVO B y 0.7 en el listener de peers: sin firma de un peer conocido no se lee el cuerpo

CLAVE_PAR = b"k" * 32


@pytest.fixture
def peer_srv(aislado, monkeypatch):
    peers = aislado["tmp"] / "peers.json"
    monkeypatch.setattr(server, "PEERS_FILE", str(peers))
    fed.add_peer(str(peers), {"pc_id": "pcB", "name": "b", "ip": "127.0.0.1", "port": 1, "key": CLAVE_PAR.hex()})
    s = server.QuietServer(("127.0.0.1", 0), server.PeerHandler)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1]
    s.shutdown()
    s.server_close()


def crudo(port, cabecera: bytes, timeout=5):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(cabecera)
    t0 = time.monotonic()
    resp = s.recv(4096)
    s.close()
    return resp, time.monotonic() - t0


def firmado(port, method, path, body: bytes, pc="pcB", clave=CLAVE_PAR):
    ts = time.time()
    nonce = os.urandom(8).hex()
    h = {
        "X-Lienzo-Peer": pc,
        "X-Lienzo-Ts": repr(ts),
        "X-Lienzo-Nonce": nonce,
        "X-Lienzo-Sig": fed.sign(clave, method, path, body, ts, nonce),
        "Content-Type": "application/json",
    }
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    texto = r.read()
    c.close()
    return r.status, json.loads(texto) if texto else None


def test_peer_sin_headers_de_firma_da_401_sin_leer_el_cuerpo(peer_srv):
    resp, dt = crudo(peer_srv, b"POST /peer/sessions/x/attach HTTP/1.1\r\nHost: x\r\nContent-Length: 60000000\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 401") and dt < 4 and b"Connection: close" in resp


def test_peer_desconocido_da_401_sin_leer_el_cuerpo(peer_srv):
    resp, dt = crudo(
        peer_srv,
        b"POST /peer/sessions/x/send HTTP/1.1\r\nHost: x\r\nContent-Length: 5000000\r\n"
        b"X-Lienzo-Peer: intruso\r\nX-Lienzo-Ts: 1\r\nX-Lienzo-Nonce: n\r\nX-Lienzo-Sig: s\r\n\r\n",
    )
    assert resp.startswith(b"HTTP/1.1 401") and dt < 4


def test_peer_rutas_sin_firma_leen_como_maximo_max_body(peer_srv):
    largo = server.MAX_BODY + 1
    resp, _ = crudo(peer_srv, f"POST /peer/pair HTTP/1.1\r\nHost: x\r\nContent-Length: {largo}\r\n\r\n".encode())
    assert resp.startswith(b"HTTP/1.1 413")


def test_peer_firmado_sigue_andando(peer_srv):
    code, res = firmado(peer_srv, "GET", "/peer/restaurables", b"")
    assert code == 200 and "restaurables" in res
    assert firmado(peer_srv, "GET", "/peer/restaurables", b"", clave=b"z" * 32)[0] == 401


def test_peer_401_deja_el_motivo_en_el_log_una_vez_por_minuto(peer_srv, aislado, monkeypatch):
    """1.8: el 401 decía solo «firma invalida» en los dos lados; reloj corrido, replay y clave
    distinta se arreglan distinto. Al cliente le sigue llegando «firma invalida»."""
    monkeypatch.setattr(server, "_avisos_401", {})
    for _ in range(3):
        code, res = firmado(peer_srv, "GET", "/peer/restaurables", b"", clave=b"z" * 32)
        assert code == 401 and res["error"] == "firma invalida"
    motivos = [x for x in aislado["logs"] if "401" in x]
    assert len(motivos) == 1 and "clave distinta" in motivos[0]


def test_peer_json_invalido_da_400_y_no_se_toma_como_vacio(peer_srv, monkeypatch):
    """S8: `{}` en vez de 400 hacía que un envío con el cuerpo roto tecleara un Enter vacío."""
    sid = "5e000000-0000-4000-8000-000000000001"
    st.sessions[sid] = {"session_id": sid, "agent": "claude", "pid": 1}
    enviados = []
    monkeypatch.setattr(server, "send_to_session", lambda s, t, a: enviados.append(t) or (200, {"ok": True}))
    code, res = firmado(peer_srv, "POST", f"/peer/sessions/{sid}/send", b'{"text": ')
    assert code == 400 and res["error"] == "JSON invalido" and enviados == []
    assert firmado(peer_srv, "POST", f"/peer/sessions/{sid}/send", b"[1]")[0] == 400
    assert firmado(peer_srv, "POST", f"/peer/sessions/{sid}/send", b'{"text": "hola"}')[0] == 200


# 0.11 y S9: el envío entre tarjetas deja la flecha, aunque la destino sea de otra PC

SID_A = "a0000000-0000-4000-8000-00000000000a"
SID_REMOTA = "b0000000-0000-4000-8000-00000000000b"


@pytest.fixture
def links_tmp(aislado, monkeypatch):
    monkeypatch.setattr(st.links, "path", str(aislado["tmp"] / "links.json"))
    st.links.items.clear()
    yield st.links
    st.links.items.clear()


def test_envio_a_una_tarjeta_de_otra_pc_registra_la_flecha(srv, aislado, links_tmp):
    st.sessions[SID_A] = {"session_id": SID_A, "agent": "claude", "pid": 1}
    aislado["espejo"].duenos[SID_REMOTA] = "pcB"
    cuerpo = {"text": "hola", "from": SID_A}
    code, _, _ = pedir(srv, "POST", f"/sessions/{SID_REMOTA}/send", cuerpo)
    assert code == 200
    assert aislado["espejo"].llamadas[-1] == ("pcB", "POST", f"/sessions/{SID_REMOTA}/send", cuerpo)
    assert [(x["from"], x["to"], x["kind"]) for x in links_tmp.snapshot()] == [(SID_A, SID_REMOTA, "send")]


def test_envio_remoto_que_falla_no_deja_flecha(srv, aislado, links_tmp):
    st.sessions[SID_A] = {"session_id": SID_A, "agent": "claude", "pid": 1}
    aislado["espejo"].duenos[SID_REMOTA] = "pcB"
    aislado["espejo"].respuestas[("pcB", "POST", f"/sessions/{SID_REMOTA}/send")] = (409, {"error": "x"})
    assert pedir(srv, "POST", f"/sessions/{SID_REMOTA}/send", {"text": "hola", "from": SID_A})[0] == 409
    assert links_tmp.snapshot() == []


def test_envio_con_copycat_si_el_origen_se_borra_durante_el_envio(srv, aislado, links_tmp, monkeypatch):
    """S9: `src in sessions` se miraba sin el lock y después `sessions[src]`: si el origen se
    borraba durante el envío (hasta 60 s), KeyError y 500 aunque el texto ya hubiera entrado."""
    sid = "d0000000-0000-4000-8000-00000000000d"
    st.sessions[SID_A] = {"session_id": SID_A, "agent": "claude", "pid": 1}
    st.sessions[sid] = {"session_id": sid, "agent": "claude", "pid": 2}

    def enviar(s, text, attachments):
        st.sessions.pop(SID_A, None)  # lo borran mientras se teclea
        return 200, {"ok": True}

    monkeypatch.setattr(server, "send_to_session", enviar)
    monkeypatch.setattr(server, "hand_over", lambda dst, src, stop=True: {"handed": src["session_id"]})
    code, _, res = pedir(srv, "POST", f"/sessions/{sid}/send", {"text": "x", "from": SID_A, "copycat": True})
    assert code == 200 and "handed" not in res


def test_titulo_de_una_tarjeta_borrada_durante_el_cambio_da_404(srv, aislado, monkeypatch):
    """S10: set_title puede leer la transcripción (lento); si en el medio borraron la tarjeta,
    touch no la guarda (sessions.touch ya revalida) y el server no tiene que decir 200."""
    sid = "e0000000-0000-4000-8000-00000000000e"
    st.sessions[sid] = {"session_id": sid, "agent": "claude", "pid": 1, "title": "viejo"}

    def titular(s, title):
        s["title"] = title
        st.sessions.pop(sid, None)

    monkeypatch.setattr(server, "set_title", titular)
    code, _, res = pedir(srv, "PUT", f"/sessions/{sid}/title", {"title": "nuevo"})
    assert code == 404 and res["code"] == "unknown_session"


def test_dos_altas_iguales_a_la_vez_dejan_una_sola_regla(aislado, monkeypatch):
    """S11: la validación (¿ya hay una igual?) y el alta iban bajo locks separados; dos POST
    iguales a la vez pasaban los dos el chequeo de duplicado."""
    monkeypatch.setattr(st.rules, "path", str(aislado["tmp"] / "rules.json"))
    st.rules.items.clear()
    a, b = "f0000000-0000-4000-8000-00000000000a", "f0000000-0000-4000-8000-00000000000b"
    for sid in (a, b):
        st.sessions[sid] = {"session_id": sid, "agent": "claude", "pid": 1}
    original = server.find_enabled

    def lento(pred):
        r = original(pred)
        time.sleep(0.2)  # ensancha la ventana entre «no hay otra igual» y el alta
        return r

    monkeypatch.setattr(server, "find_enabled", lento)
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


def test_restaurar_que_revienta_no_devuelve_el_texto_de_la_excepcion(aislado, monkeypatch):
    """S13: el error iba tal cual al cliente (rutas, nombres de la máquina; por el túnel sale
    afuera). Ahora un id corto, y el traceback con ese id en el log."""
    sid = "9a000000-0000-4000-8000-00000000009a"
    monkeypatch.setattr(server, "restorables_local", lambda: [{"session_id": sid, "cwd": "x", "agent": "claude"}])

    def revienta(*a, **k):
        raise RuntimeError("C:/Users/secreto/ruta")

    monkeypatch.setattr(server.launch, "launch", revienta)
    code, res = server.restore_local({"session_id": sid})
    error = res["failed"][0]["error"]
    assert code == 400 and "secreto" not in error and "RuntimeError" not in error
    eid = error.split("(")[-1].rstrip(")")
    assert any(eid in x and "secreto" in x for x in aislado["logs"])


def test_lan_ip_avisa_cuando_no_hay_red(aislado, monkeypatch):
    """S17: sin red, el listener de peers quedaba en 127.0.0.1 sin ninguna línea que lo dijera.
    Desde el 2026-10-05 no se liga a localhost (no le sirve a ningún par): _lan_ip da None, lo
    dice una vez con el motivo, y ListenersDePares lo abre cuando aparece la red."""

    def sin_red(*a, **k):
        raise OSError("red inalcanzable")

    monkeypatch.setattr(st, "log", aislado["logs"].append)
    monkeypatch.setattr(st, "_avisos", {})
    monkeypatch.setattr(server.socket, "socket", sin_red)
    assert server._lan_ip() is None
    assert server._lan_ip() is None
    avisos = [x for x in aislado["logs"] if "sin IP de LAN" in x]
    assert len(avisos) == 1 and "red inalcanzable" in avisos[0]


def test_excepcion_en_cualquier_hilo_llega_al_log(aislado, monkeypatch):
    """1.1 (la parte simple): una excepción en un hilo iba a stderr (la consola del server, que
    nadie mira) y no al log propio."""
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    server.instalar_excepthook()

    def revienta():
        raise ValueError("se rompio el hilo")

    h = threading.Thread(target=revienta, name="hilo-de-prueba")
    h.start()
    h.join()
    assert any("hilo-de-prueba" in x and "ValueError: se rompio el hilo" in x for x in aislado["logs"])


def test_olvidar_un_peer_con_peers_json_ilegible_da_un_error_claro(srv, aislado, monkeypatch):
    """federation.remove_peer ahora levanta OSError si peers.json existe y no se puede leer (antes
    lo pisaba): el server contesta un error que se entiende, no 500, y no corta el espejo."""
    cortados = []
    aislado["espejo"].disconnect = cortados.append

    def ilegible(path, pc_id):
        raise OSError("peers.json corrupto")

    monkeypatch.setattr(server.federation, "remove_peer", ilegible)
    code, _, res = pedir(srv, "DELETE", "/peers/pcB")
    assert code == 409 and "peers.json" in res["error"] and cortados == []


# NUEVO A: el espejo reconecta cuando cambia la IP de un peer


class BeaconFalso:
    def __init__(self, vistos):
        self.vistos = vistos

    def seen(self):
        return self.vistos


def test_beacon_reconecta_aunque_peers_json_ya_tenga_la_ip_nueva(aislado, monkeypatch):
    """beacon.py escribe la IP nueva en peers.json antes que _beacon_sync_loop la mire, así que
    comparar contra peers.json siempre daba igual y el espejo seguía colgado de la IP vieja. Y la
    PC que ofreció la frase guarda ip "": nunca conectaba. Se compara contra la IP con la que el
    espejo está conectado."""
    peers = aislado["tmp"] / "peers.json"
    monkeypatch.setattr(server, "PEERS_FILE", str(peers))
    monkeypatch.setattr(server.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(server, "_ip_conectada", {})
    conexiones = []
    aislado["espejo"].connect = lambda pc, info, host, port, key, yo: conexiones.append((pc, host))
    aislado["espejo"].disconnect = lambda pc: None
    registro = {"pc_id": "pcB", "name": "b", "ip": "10.0.0.1", "port": 7322, "key": CLAVE_PAR.hex()}
    fed.add_peer(str(peers), registro)
    server._connect_peer_from_record(registro)
    assert conexiones == [("pcB", "10.0.0.1")]
    fed.update_peer_ip(str(peers), "pcB", "10.0.0.2")  # lo que hace beacon.py antes
    server._beacon_sync_once(BeaconFalso({"pcB": {"ip": "10.0.0.2"}}))
    assert conexiones[-1] == ("pcB", "10.0.0.2")
    server._beacon_sync_once(BeaconFalso({"pcB": {"ip": "10.0.0.2"}}))
    assert len(conexiones) == 2, "con la misma IP no se reconecta"
    # la que ofreció la frase: ip "" en peers.json, nunca se había conectado
    fed.add_peer(str(peers), {"pc_id": "pcC", "name": "c", "ip": "", "port": 7322, "key": CLAVE_PAR.hex()})
    server._beacon_sync_once(BeaconFalso({"pcC": {"ip": "10.0.0.3"}}))
    assert conexiones[-1] == ("pcC", "10.0.0.3")
