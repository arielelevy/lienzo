"""Envíos de a uno por sesión (2026-10-25): dos `send_to_session` casi juntos a la misma consola no se
teclean intercalados; a sesiones distintas siguen en paralelo; el que espera demasiado recibe 409."""

import itertools
import threading
import time

import sessions


def _registrar(monkeypatch, demora=0.2):
    tramos = []

    def local(s, text, attachments):
        t0 = time.monotonic()
        time.sleep(demora)
        tramos.append((s["session_id"], text, t0, time.monotonic()))
        return 200, {"ok": True}

    monkeypatch.setattr(sessions, "_mirror_owner", lambda sid: None)
    monkeypatch.setattr(sessions, "_send_to_session_local", local)
    return tramos


def _en_paralelo(llamadas):
    out = [None] * len(llamadas)

    def correr(i, s, texto):
        out[i] = sessions.send_to_session(s, texto, [])

    hilos = [threading.Thread(target=correr, args=(i, s, t)) for i, (s, t) in enumerate(llamadas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return out


def test_misma_sesion_no_se_solapan(monkeypatch):
    tramos = _registrar(monkeypatch)
    s = {"session_id": "cola-a"}
    assert [c for c, _ in _en_paralelo([(s, "uno"), (s, "dos"), (s, "tres")])] == [200, 200, 200]
    tramos.sort(key=lambda x: x[2])
    assert all(a[3] <= b[2] for a, b in itertools.pairwise(tramos))


def test_sesiones_distintas_van_en_paralelo(monkeypatch):
    tramos = _registrar(monkeypatch, demora=0.3)
    t0 = time.monotonic()
    _en_paralelo([({"session_id": "cola-b"}, "x"), ({"session_id": "cola-c"}, "y")])
    assert time.monotonic() - t0 < 0.55 and len(tramos) == 2


def test_espera_demasiado_da_409(monkeypatch):
    _registrar(monkeypatch)
    monkeypatch.setattr(sessions, "ENVIO_COLA_S", 0.05)
    cola = sessions._cola_envio("cola-d")
    cola.acquire()
    try:
        code, out = sessions.send_to_session({"session_id": "cola-d"}, "x", [])
    finally:
        cola.release()
    assert code == 409 and "en curso" in out["error"]


def test_la_cola_se_suelta_si_el_envio_falla(monkeypatch):
    monkeypatch.setattr(sessions, "_mirror_owner", lambda sid: None)

    def falla(s, text, attachments):
        raise RuntimeError("consola cerrada")

    monkeypatch.setattr(sessions, "_send_to_session_local", falla)
    try:
        sessions.send_to_session({"session_id": "cola-e"}, "x", [])
    except RuntimeError:
        pass
    assert sessions._cola_envio("cola-e").acquire(timeout=0.1)
    sessions._cola_envio("cola-e").release()
