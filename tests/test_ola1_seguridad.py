"""Fase 0 del plan de refactor del 2026-10-04 (docs/plan-refactor-2026-10-04.md), lo de seguridad
y procesos: subproc.correr (0.5) y lo que cambia en el server (0.2, 0.3, 0.7, 0.11 y S8-S17)."""

import http.client
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
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
