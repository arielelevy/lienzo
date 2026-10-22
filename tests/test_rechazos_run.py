"""Registro de rechazos (decisión 2 de Ariel, 2026-10-22) y log por comando de POST /run (decisión 10).

Cada pedido que el server rechaza (401, 403, Host no válido) deja una línea con hora, origen, ruta,
método y motivo, sin cuerpos, query ni secretos, en un archivo rotado que se lee con GET /rechazos.
Cada POST /peer/run deja una línea en su propio registro, que se lee con GET /run/log."""

import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer

import pytest
import state

from lienzo import server

SECRETO = "s3cr3t0-que-no-debe-quedar"


def _servir(handler):
    listener = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    return listener, thread


def _pedir(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _sin_agrupar_previo():
    import bitacora

    bitacora._vistos.clear()
    yield
    bitacora._vistos.clear()


@pytest.fixture
def tablero(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(server, "sessions", {})
    listener, thread = _servir(server.Handler)
    yield listener.server_port
    listener.shutdown()
    listener.server_close()
    thread.join(5)


def test_csrf_rechazado_queda_registrado_sin_cuerpo_ni_query(tablero):
    body = json.dumps({"text": SECRETO}).encode()
    code, _ = _pedir(
        tablero,
        "POST",
        f"/rules?token={SECRETO}",
        body,
        {"Content-Type": "application/json", "Origin": "http://evil.example", "User-Agent": "Dot/1.0"},
    )
    assert code == 403
    code, res = _pedir(tablero, "GET", "/rechazos")
    assert code == 200
    assert len(res["rechazos"]) == 1
    e = res["rechazos"][0]
    assert e["codigo"] == 403 and e["metodo"] == "POST" and e["ruta"] == "/rules"
    assert e["listener"] == "tablero" and e["ip"] == "127.0.0.1"
    assert "X-Lienzo" in e["motivo"] and e["origin"] == "http://evil.example" and e["agente"] == "Dot/1.0"
    assert e["hora"]
    with open(os.path.join(state.LIENZO, "rechazos.jsonl"), encoding="utf-8") as f:
        crudo = f.read()
    assert SECRETO not in crudo and SECRETO not in json.dumps(res)


def test_host_no_valido_tambien_se_registra(tablero):
    code, _ = _pedir(tablero, "GET", "/health", headers={"Host": "rebind.example"})
    assert code == 400
    _, res = _pedir(tablero, "GET", "/rechazos")
    assert [e["motivo"] for e in res["rechazos"]] == ["Host no valido"]


def test_un_200_o_un_404_no_son_rechazos(tablero):
    assert _pedir(tablero, "GET", "/health")[0] == 200
    assert _pedir(tablero, "GET", "/no-existe")[0] == 404
    assert _pedir(tablero, "GET", "/rechazos")[1]["rechazos"] == []


def test_rechazos_solo_desde_la_lan(tablero, monkeypatch):
    monkeypatch.setattr(server.Handler, "_is_local", lambda self: False)
    monkeypatch.setattr(server.Handler, "_authed", lambda self: True)
    code, res = _pedir(tablero, "GET", "/rechazos")
    assert code == 403 and "rechazos" not in res


def test_rotacion_acota_el_archivo(tmp_path, monkeypatch):
    import bitacora

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(bitacora, "TOPE_BYTES", 2000)
    for i in range(200):
        bitacora.anexar("prueba", {"i": i, "relleno": "x" * 40})
    actual = tmp_path / "prueba.jsonl"
    assert actual.stat().st_size <= 2000 + 200
    assert (tmp_path / "prueba.jsonl.1").exists()
    assert not (tmp_path / "prueba.jsonl.2").exists()
    ultimas = bitacora.ultimas("prueba", 5)
    assert [e["i"] for e in ultimas] == [195, 196, 197, 198, 199]


def test_campos_se_recortan_y_sin_control(tmp_path, monkeypatch):
    import bitacora

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    bitacora.rechazo(listener="tablero", metodo="GET", ruta="/a\r\nb" + "z" * 900, ip="1.2.3.4", codigo=401, motivo="m")
    (e,) = bitacora.ultimas(bitacora.RECHAZOS, 10)
    assert "\n" not in e["ruta"] and "\r" not in e["ruta"] and len(e["ruta"]) <= 200


def test_peer_sin_firma_queda_registrado(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(server, "PEERS_FILE", str(tmp_path / "peers.json"))
    listener, thread = _servir(server.PeerHandler)
    try:
        body = json.dumps({"command": "status", "cwd": SECRETO}).encode()
        code, _ = _pedir(
            listener.server_port,
            "POST",
            "/peer/run",
            body,
            {"X-Lienzo-Peer": "pc-desconocida", "X-Lienzo-Sig": SECRETO},
        )
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(5)
    assert code == 401
    import bitacora

    (e,) = bitacora.ultimas(bitacora.RECHAZOS, 10)
    assert e["listener"] == "peer" and e["ruta"] == "/peer/run" and e["peer"] == "pc-desconocida"
    assert SECRETO not in json.dumps(e)


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push", "-fu", "origin", "main"],
        ["git", "fetch", "--upload-pack=calc"],
        ["git", "push", "--receive-pack", "calc"],
        ["git", "push", "--exec=calc"],
        ["git", "-c", "core.sshCommand=calc", "fetch"],
    ],
)
def test_permitted_cierra_force_combinado_y_programas_inyectados(argv):
    import remote_run

    assert not remote_run.permitted(argv)


@pytest.mark.parametrize("argv", [["git", "push", "-u", "origin", "main"], ["git", "log", "-1", "--format=%H"]])
def test_permitted_sigue_aceptando_lo_normal(argv):
    import remote_run

    assert remote_run.permitted(argv)


def test_cada_run_deja_su_linea(tmp_path, monkeypatch):
    import bitacora
    import remote_run

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    raiz = tmp_path / "repos"
    raiz.mkdir()
    monkeypatch.setattr(
        state,
        "load_config",
        lambda: {"launch_roots": [str(raiz)], "run_allowlist": {"tests": ["py", "-m", "pytest", "-q"]}},
    )
    monkeypatch.setattr(remote_run.subproc, "correr", lambda *a, **k: (1, SECRETO, "fallo " + SECRETO))
    assert remote_run.run({"command": "tests", "cwd": str(raiz)}, "pc-b")[0] == 200
    assert remote_run.run({"command": "borrar", "cwd": str(raiz)}, "pc-b")[0] == 403
    assert remote_run.run({"command": "tests", "cwd": str(tmp_path)}, "pc-b")[0] == 403
    ok, negado, afuera = bitacora.ultimas(bitacora.RUN, 10)
    assert ok["peer"] == "pc-b" and ok["comando"] == "tests" and ok["codigo"] == 200
    assert ok["exit_code"] == 1 and ok["stdout_caracteres"] == len(SECRETO) and ok["duracion_s"] >= 0
    assert ok["cwd"] == str(raiz)
    assert negado["codigo"] == 403 and negado["exit_code"] is None and negado["motivo"]
    assert afuera["codigo"] == 403 and "launch_roots" in afuera["motivo"]
    assert SECRETO not in (tmp_path / "remote_run.jsonl").read_text(encoding="utf-8")


def test_get_run_log(tablero):
    import bitacora

    bitacora.anexar(bitacora.RUN, {"comando": "status", "codigo": 200})
    code, res = _pedir(tablero, "GET", "/run/log?n=5")
    assert code == 200 and res["run"][-1]["comando"] == "status"


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "fetch", "--upload-pac=calc"],
        ["git", "push", "--rece=calc"],
        ["git", "tag", "--forc", "v1"],
        ["git", "log", "--output=C:/x.bat"],
        ["git", "log", "--out", "C:/x.bat"],
        ["git", "cherry-pick", "--strat=evil", "abc"],
    ],
)
def test_permitted_cierra_abreviaturas_de_git(argv):
    import remote_run

    assert not remote_run.permitted(argv)


def test_mismo_rechazo_repetido_se_agrupa(tmp_path, monkeypatch):
    import bitacora

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    reloj = [1000.0]
    monkeypatch.setattr(bitacora.time, "monotonic", lambda: reloj[0])
    datos = {"listener": "peer", "metodo": "POST", "ruta": "/peer/x", "ip": "1.1.1.1", "codigo": 401, "motivo": "m"}
    for _ in range(5):
        bitacora.rechazo(**datos)
    bitacora.rechazo(**{**datos, "ruta": "/peer/y"})
    reloj[0] += bitacora.AGRUPAR_S + 1
    bitacora.rechazo(**datos)
    lineas = bitacora.ultimas(bitacora.RECHAZOS, 10)
    assert [e["ruta"] for e in lineas] == ["/peer/x", "/peer/y", "/peer/x"]
    assert lineas[-1]["omitidos"] == 4 and "omitidos" not in lineas[0]


def test_peer_no_cree_el_header_del_tunel(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(server, "PEERS_FILE", str(tmp_path / "peers.json"))
    listener, thread = _servir(server.PeerHandler)
    try:
        code, _ = _pedir(listener.server_port, "POST", "/peer/run", b"{}", {"CF-Connecting-IP": "8.8.8.8"})
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(5)
    import bitacora

    (e,) = bitacora.ultimas(bitacora.RECHAZOS, 10)
    assert code == 401 and e["ip"] == "127.0.0.1" and e["tunel"] is False


def test_falla_del_registro_no_tumba_el_rechazo(tablero, monkeypatch):
    import bitacora

    def rota(**_):
        raise RuntimeError("bitacora rota")

    monkeypatch.setattr(bitacora, "rechazo", rota)
    assert _pedir(tablero, "POST", "/rules", b"{}")[0] == 403


def test_n_raro_no_da_500(tablero):
    assert _pedir(tablero, "GET", "/rechazos?n=%C2%B2")[0] == 200


def test_ruta_con_doble_barra_queda_como_se_ruteo(tablero):
    # http.server colapsa la doble barra inicial antes de rutear; el registro no la reinterpreta como host
    _pedir(tablero, "POST", "//evil/admin", b"{}")
    _, res = _pedir(tablero, "GET", "/rechazos")
    assert res["rechazos"][-1]["ruta"] == "/evil/admin"


def test_run_que_explota_igual_deja_linea(tmp_path, monkeypatch):
    import bitacora
    import remote_run

    monkeypatch.setattr(state, "LIENZO", str(tmp_path))

    def rota():
        raise RuntimeError("config rota")

    monkeypatch.setattr(state, "load_config", rota)
    with pytest.raises(RuntimeError):
        remote_run.run({"command": "status", "cwd": str(tmp_path)}, "pc-b")
    (e,) = bitacora.ultimas(bitacora.RUN, 10)
    assert e["codigo"] == 500 and e["comando"] == "status"
