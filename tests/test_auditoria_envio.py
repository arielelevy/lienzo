"""Regresión del 2026-10-25 (OpenSyync, 40 min con cinco frentes quietos y la 0.6.17 andando): la auditoría
detectaba, pero cada aviso salía con `sin_aviso: true` sin `from`, el server lo rechazaba con 400 y la ronda
entera fallaba (lienzo.log: «auditoria: ronda fallida (HTTPError: HTTP Error 400: Bad Request)»). Las pruebas
de antes simulaban el envío sin pasar por la validación del server; estas lo validan con `validar_send`."""

import datetime as dt
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import auditoria as au

AHORA = dt.datetime(2026, 10, 25, 13, 30, tzinfo=dt.timezone(dt.timedelta(hours=-3)))


def _iso(h, m, s=0):
    return dt.datetime(2026, 10, 25, h, m, s, tzinfo=AHORA.tzinfo).isoformat()


def _caso_opensyync():
    """El tablero real del incidente, reducido: la coordinadora quieta y cinco frentes que entregaron por regla
    entre las 12:41 y las 12:59 y no recibieron nada después (links de /links de ese día)."""
    pc = "75727ff74069"
    root = {"session_id": "ROOT", "title": "opensyync | sesión", "coordinator": True}
    frentes = [("B", 12, 41), ("C", 12, 44), ("A", 12, 47), ("E", 12, 52), ("D", 12, 59)]
    sesiones = [{**root, "state": "termino", "state_since": _iso(13, 0)}] + [
        {"session_id": x, "title": f"opensyync | encargo {x}", "state": "termino", "state_since": _iso(h, m)}
        for x, h, m in frentes
    ]
    for s in sesiones:
        s.update(alive=True, pc=pc, repo_key="github.com/arielelevy/opensyync")
    links = [{"id": f"e{x}", "from": "ROOT", "to": x, "ts": _iso(h - 1, m), "kind": "send"} for x, h, m in frentes]
    links += [{"id": f"r{x}", "from": x, "to": "ROOT", "ts": _iso(h, m, 5), "kind": "rule"} for x, h, m in frentes]
    # la coordinadora tomó el último informe y cerró su turno a las 13:00
    return pc, sesiones, links


def _servidor(monkeypatch, pc, sesiones, links, fallar=None):
    rutas = {"/sessions": sesiones, "/peers": [{"pc_id": pc, "local": True}], "/links": links}
    monkeypatch.setattr(au, "_get", lambda base, ruta: rutas[ruta])
    enviados = []

    def post(base, ruta, cuerpo):
        rechazo = server.validar_send(cuerpo)  # la misma validación que el handler de /send
        if rechazo is not None or (fallar and fallar(ruta)):
            raise urllib.error.HTTPError(base + ruta, 400, "Bad Request", None, None)
        enviados.append((ruta, cuerpo))
        return 200

    monkeypatch.setattr(au, "_post", post)
    monkeypatch.setattr(au.dt, "datetime", _Reloj)
    return enviados


class _Reloj(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return AHORA if tz is None else AHORA.astimezone(tz)


def test_caso_opensyync_el_aviso_pasa_la_validacion_del_server(monkeypatch, tmp_path):
    pc, sesiones, links = _caso_opensyync()
    enviados = _servidor(monkeypatch, pc, sesiones, links)
    r = au.ronda_local("http://x", str(tmp_path / "e.json"), enviar=True)
    assert {h["tipo"] for h in r["hallazgos"]} == {"entrega_sin_leer"}
    assert len(r["hallazgos"]) == 5 and r["fallidos"] == {}
    assert [ruta for ruta, _ in enviados] == ["/sessions/ROOT/send"]
    assert enviados[0][1]["text"].count("\n- entrega_sin_leer") == 5


def test_un_envio_fallido_no_cuenta_como_avisado_y_se_reintenta(monkeypatch, tmp_path):
    pc, sesiones, links = _caso_opensyync()
    estado = str(tmp_path / "e.json")
    _servidor(monkeypatch, pc, sesiones, links, fallar=lambda ruta: True)
    r = au.ronda_local("http://x", estado, enviar=True)
    assert r["enviados"] == [] and "ROOT" in r["fallidos"]
    # la ronda siguiente, con el server sano, avisa lo mismo (no quedó marcado como avisado)
    enviados = _servidor(monkeypatch, pc, sesiones, links)
    r = au.ronda_local("http://x", estado, enviar=True)
    assert [ruta for ruta, _ in enviados] == ["/sessions/ROOT/send"] and len(r["avisar"]) == 5
    # y la siguiente ya no repite
    enviados.clear()
    au.ronda_local("http://x", estado, enviar=True)
    assert enviados == []


def test_el_cuerpo_viejo_es_el_que_daba_400():
    assert server.validar_send({"text": "x", "sin_aviso": True}) is not None
    assert server.validar_send({"text": "x"}) is None
