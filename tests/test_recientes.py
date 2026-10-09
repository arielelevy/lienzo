"""Carpetas abiertas estos dias: lienzo/recientes.py (registro en ~/.lienzo/recientes.json, siempre en
una ruta temporal por el fixture autouse de conftest.py), su alimentacion desde la liveness local
(sessions.remember_live_cards) y desde el espejo (mirror._apply_event), y GET /recientes."""

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
import mirror
import recientes
import sessions as ses
import state as st
from test_server import aislado  # noqa: F401


def tarjeta(cwd, pc=None, alive=True, repo=None, sid=None):
    return {"session_id": sid or cwd, "cwd": cwd, "pc": pc, "alive": alive, "repo": repo}


def test_recordar_guarda_una_entrada_por_pc_y_carpeta_con_la_pc_local_por_defecto(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    n = recientes.recordar_tarjetas(
        [
            tarjeta("D:\\Apps\\lienzo", repo="lienzo"),
            tarjeta("d:/apps/lienzo/", repo="lienzo", sid="otra"),  # misma carpeta, otra escritura
            tarjeta("E:\\Repos\\demo", pc="pcB"),  # sin repo: el nombre de la carpeta
            tarjeta("D:\\Apps\\muerta", alive=False),
            {"session_id": "sin-cwd", "cwd": None, "alive": True},
        ]
    )
    assert n == 2
    lista = recientes.listar()
    assert sorted((e["cwd"], e["repo"], e["pc"]) for e in lista) == [
        ("D:\\Apps\\lienzo", "lienzo", "pcA"),
        ("E:\\Repos\\demo", "demo", "pcB"),
    ]
    assert all(st.parse_ts(e["last"]) for e in lista)
    assert [e["cwd"] for e in recientes.listar("pcB")] == ["E:\\Repos\\demo"]
    assert os.path.isfile(recientes.path())


def test_debounce_no_reescribe_y_pc_del_espejo_manda_sobre_la_local(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    reloj = [1000.0]
    monkeypatch.setattr(recientes.time, "monotonic", lambda: reloj[0])
    assert recientes.recordar_tarjetas([tarjeta("D:\\x")]) == 1
    assert recientes.recordar_tarjetas([tarjeta("D:\\x")]) == 0  # dentro del debounce: ni mira el disco
    reloj[0] += recientes.DEBOUNCE_S + 1
    antes = os.path.getmtime(recientes.path())
    assert recientes.recordar_tarjetas([tarjeta("D:\\x")]) == 0  # ya marcada hoy: no se reescribe
    assert os.path.getmtime(recientes.path()) == antes
    # marcada ayer: pasado el debounce, se actualiza a hoy
    ayer = (dt.datetime.now().astimezone() - dt.timedelta(days=1)).isoformat()
    with open(recientes.path(), "w", encoding="utf-8") as f:
        json.dump([{"cwd": "D:\\x", "repo": "x", "pc": "pcA", "last": ayer}], f)
    reloj[0] += recientes.DEBOUNCE_S + 1
    assert recientes.recordar_tarjetas([tarjeta("D:\\x")]) == 1
    assert len(recientes.listar()) == 1
    assert st.parse_ts(recientes.listar()[0]["last"]).date() == dt.datetime.now().astimezone().date()
    # la tarjeta sin pc que trae el espejo es de la PC del espejo, no de esta
    assert recientes.recordar_tarjetas([tarjeta("D:\\x")], pc="pcB") == 1
    assert sorted(e["pc"] for e in recientes.listar()) == ["pcA", "pcB"]


def test_poda_lo_de_mas_de_14_dias_y_el_tope(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    vieja = (dt.datetime.now().astimezone() - dt.timedelta(days=recientes.MAX_AGE_DAYS + 1)).isoformat()
    justa = (dt.datetime.now().astimezone() - dt.timedelta(days=recientes.MAX_AGE_DAYS - 1)).isoformat()
    items = [
        {"cwd": "D:\\vieja", "repo": "vieja", "pc": "pcA", "last": vieja},
        {"cwd": "D:\\justa", "repo": "justa", "pc": "pcA", "last": justa},
    ]
    items += [
        {"cwd": f"D:\\n{i}", "repo": f"n{i}", "pc": "pcA", "last": st.now()} for i in range(recientes.MAX_ENTRIES + 5)
    ]
    os.makedirs(os.path.dirname(recientes.path()), exist_ok=True)
    with open(recientes.path(), "w", encoding="utf-8") as f:
        json.dump(items, f)
    lista = recientes.listar()
    assert len(lista) == recientes.MAX_ENTRIES
    assert "D:\\vieja" not in {e["cwd"] for e in lista}
    assert "D:\\justa" not in {e["cwd"] for e in lista}  # la mas vieja de las vivas cae por el tope
    # una escritura nueva deja el archivo podado
    recientes.recordar_tarjetas([tarjeta("D:\\nueva")])
    with open(recientes.path(), encoding="utf-8") as f:
        assert len(json.load(f)) == recientes.MAX_ENTRIES


def test_archivo_roto_o_con_basura_no_frena(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    os.makedirs(os.path.dirname(recientes.path()), exist_ok=True)
    with open(recientes.path(), "w", encoding="utf-8") as f:
        f.write("{no es una lista")
    assert recientes.listar() == []
    with open(recientes.path(), "w", encoding="utf-8") as f:
        json.dump([{"cwd": "D:\\ok", "pc": "pcA", "last": st.now()}, {"cwd": 3}, "x", {"pc": "pcA"}], f)
    assert [e["cwd"] for e in recientes.listar()] == ["D:\\ok"]
    # una falla adentro no levanta: la liveness sigue
    monkeypatch.setattr(recientes, "_write", lambda items: (_ for _ in ()).throw(OSError("disco")))
    assert recientes.recordar_tarjetas([tarjeta("D:\\otra")]) == 0


def test_la_liveness_local_alimenta_el_registro_con_y_sin_hooks(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    with ses.lock:
        ses.sessions.clear()
        a = ses.new_session("pid-1", "codex", "sweep")  # barrido, sin hooks: cuenta igual
        a["cwd"], a["repo"] = "D:\\Apps\\chess", "chess"
        b = ses.new_session("0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", "claude", "hook")
        b["cwd"], b["repo"] = "D:\\Apps\\lienzo", "lienzo"
        ses.sessions.update({a["session_id"]: a, b["session_id"]: b})
    try:
        ses.remember_live_cards()
    finally:
        with ses.lock:
            ses.sessions.clear()
    assert sorted(e["repo"] for e in recientes.listar("pcA")) == ["chess", "lienzo"]


def test_el_espejo_alimenta_el_registro_con_la_pc_del_peer(monkeypatch):
    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    m = mirror.Mirror(transport=None)
    pm = mirror._PeerMirror("pcB", {"name": "notebook"}, None)
    m._peers["pcB"] = pm
    m.on_change = lambda: None
    m._apply_event(
        pm,
        {
            "type": "snapshot",
            "sessions": [{"session_id": "s1", "cwd": "E:\\Repos\\demo", "repo": "demo", "alive": True}],
        },
    )
    m._apply_event(
        pm,
        {
            "type": "session",
            "session": {"session_id": "s2", "cwd": "E:\\Repos\\otro", "repo": "otro", "alive": True, "pc": "pcB"},
        },
    )
    m._apply_event(
        pm,
        {
            "type": "session",
            "session": {"session_id": "s3", "cwd": "E:\\Repos\\muerta", "repo": "muerta", "alive": False},
        },
    )
    assert sorted((e["repo"], e["pc"]) for e in recientes.listar()) == [("demo", "pcB"), ("otro", "pcB")]


def test_get_recientes_lista_y_filtra_por_pc(aislado, monkeypatch):  # noqa: F811
    """GET /recientes contra el server de verdad en un puerto libre: la lista entera y ?pc=."""
    import http.client
    import threading

    monkeypatch.setattr(recientes.identity, "pc_id", lambda: "pcA")
    recientes.recordar_tarjetas(
        [tarjeta("D:\\Apps\\lienzo", repo="lienzo"), tarjeta("E:\\Repos\\demo", pc="pcB", repo="demo")]
    )
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        salidas = []
        for path, headers in (
            ("/recientes", {"X-Lienzo": "1"}),
            ("/recientes?pc=pcB", {"X-Lienzo": "1"}),
        ):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
            c.request("GET", path, headers=headers)
            r = c.getresponse()
            salidas.append((r.status, json.loads(r.read() or b"null")))
            c.close()
    finally:
        srv.shutdown()
    assert salidas[0][0] == 200 and sorted(e["repo"] for e in salidas[0][1]) == ["demo", "lienzo"]
    assert salidas[1][0] == 200 and [e["repo"] for e in salidas[1][1]] == ["demo"]
