"""Segunda revisión F: pruebas rojas por punto y pedido explícito de cart."""

from copy import deepcopy

import preguntas as p
import pytest
import sessions as ses

pytest_plugins = ["test_revision_F"]


def dialogo(question="¿Cómo seguimos?"):
    return {"question": question, "options": [{"n": 1, "text": "Continuar"}, {"n": 2, "text": "Parar"}], "selected": 1}


def test_01_terminal_question_none(caso, monkeypatch):
    src, _, _ = caso
    d = dialogo(None)
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "_dialogo_en_pantalla", lambda *a: (d, None))
    monkeypatch.setattr(ses, "_elegir_con_flechas", lambda *a: (200, {}))
    assert p._terminal(src, d, 1, None)[0] == 200


def test_01_lector_question_none(caso, monkeypatch):
    src, _, _ = caso
    src["agent"] = "coda"
    d = {**dialogo(None), "lector": "pregunta_coda"}
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": []})
    monkeypatch.setattr(p, "dialogo_coda", lambda lines: d)
    assert ses._dialogo_en_pantalla(src, d)[0] == d


@pytest.mark.parametrize("ya_abierto", [False, True])
def test_02_texto_espera_redibujo_y_no_reelige_editor(caso, monkeypatch, ya_abierto):
    src, _, _ = caso
    src["agent"] = "coda"
    d = {**dialogo(), "options": [{"n": 1, "text": "Continuar"}, {"n": 2, "text": "Type something…"}]}
    editor = {**d, "selected": 2, "input_text": ""}
    pantallas = iter([editor] if ya_abierto else [d, {**d, "selected": 2}, {**d, "selected": 2}, editor])
    monkeypatch.setattr(ses, "_dialogo_en_pantalla", lambda *a: (next(pantallas, editor), None))
    selecciones, textos = [], []
    monkeypatch.setattr(ses, "_elegir_con_flechas", lambda *a: selecciones.append(a[2]) or (200, {}))
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: textos.append(a[1]) or (200, {}))
    assert p._texto_coda(src, d, "respuesta libre")[0] == 200
    assert selecciones == ([] if ya_abierto else [2])
    assert textos == ["respuesta libre"]


def test_03_throttle_no_escribe_tarjeta(caso, monkeypatch):
    src, _, _ = caso
    src["needs"].pop("options")
    reloj, guardadas = [0], []
    monkeypatch.setattr(p, "time", lambda: reloj[0])
    monkeypatch.setattr(ses, "touch", lambda s: guardadas.append(s))
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": []})
    for t in (0, 5, 10):
        reloj[0] = t
        p.consultar(src)
    assert "consulta_lectura" not in src
    assert guardadas == []


def test_04_throttle_antes_de_buscar_coordinadora(caso, monkeypatch):
    src, _, _ = caso
    src["needs"].pop("options")
    llamadas = []
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": []})
    monkeypatch.setattr(p, "_coordinadora", lambda s: llamadas.append(s))
    p.consultar(src)
    p.consultar(src)
    assert llamadas == []


def test_05_respuestas_de_distintas_sesiones_no_se_bloquean(caso, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    src, _, _ = caso
    otra = {**deepcopy(src), "session_id": "otra-F2"}
    ses.sessions[otra["session_id"]] = otra
    inicio, liberar = Event(), Event()

    def terminal(s, *a):
        if s["session_id"] == src["session_id"]:
            inicio.set()
            assert liberar.wait(3)
        return 200, {}

    monkeypatch.setattr(p, "_terminal", terminal)
    with ThreadPoolExecutor(2) as pool:
        primera = pool.submit(p.responder, src, {"opcion": 1})
        try:
            assert inicio.wait(2)
            segunda = pool.submit(p.responder, otra, {"opcion": 1})
            assert segunda.result(timeout=1)[0] == 200
        finally:
            liberar.set()
        assert primera.result(timeout=2)[0] == 200


def test_06_responder_espera_al_barrido(caso, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Timer

    src, _, _ = caso
    inicio, liberar = Event(), Event()

    def enviar(*a):
        inicio.set()
        assert liberar.wait(3)
        return 200, {}

    monkeypatch.setattr(p, "enviar", enviar)
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    with ThreadPoolExecutor(1) as pool:
        barrido = pool.submit(p.consultar, src)
        assert inicio.wait(2)
        timer = Timer(0.2, liberar.set)
        timer.start()
        try:
            assert p.responder(src, {"opcion": 1})[0] == 200
        finally:
            liberar.set()
            timer.join()
        barrido.result(timeout=2)


def test_07_reserva_destino_remoto_entre_pasadas(entorno, monkeypatch):
    import datetime as dt

    import rules as rl
    import server

    r, _ = entorno
    t = dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC)
    r["informes"] = [
        {"id": n, "estado": "entregado", "entregado_at": (t - dt.timedelta(hours=1)).isoformat()}
        for n in ("primero", "segundo")
    ]
    monkeypatch.setattr(server, "_route_session", lambda sid: (None, "pc-remota"))
    envios = []
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *a: envios.append(a) or (200, {}))
    rl.recordar_informes(t)
    rl.recordar_informes(t + dt.timedelta(seconds=5))
    assert len(envios) == 1
    assert r["informes"][0]["recordatorio_destino"] == r["to"]


def test_08_recordatorio_usa_router_y_respeta_turno(entorno, monkeypatch):
    import datetime as dt

    import rules as rl
    import server
    import state

    r, _ = entorno
    dst = state.sessions[r["to"]]
    t = dt.datetime.now(dt.UTC)
    r["informes"] = [{"id": "aviso-F2", "estado": "entregado", "entregado_at": (t - dt.timedelta(hours=1)).isoformat()}]
    llamadas = []

    def enviar(sid, body):
        llamadas.append((sid, body))
        dst["state"] = "corriendo"  # El turno empezó entre la reserva y el transporte.
        return server.accion_send(dst, body)

    monkeypatch.setattr(p, "enviar", enviar)
    monkeypatch.setattr(server, "send_to_session", lambda *a: (200, {}))
    rl.recordar_informes(t)
    assert len(llamadas) == 1
    assert llamadas[0][1]["from"] == r["from"]
    assert llamadas[0][1]["sin_aviso"] is True
    assert not dst.get("sin_aviso")


def test_09_bucle_reglas_no_ejecuta_recordatorios(monkeypatch):
    import rules as rl

    class Fin(BaseException):
        pass

    llamadas = []
    monkeypatch.setattr(rl, "recordar_informes", lambda t: llamadas.append("bloqueante"))
    monkeypatch.setattr(rl, "reconciliar_cableado", lambda: None)
    monkeypatch.setattr(rl, "reconciliar", lambda: None)
    monkeypatch.setattr(rl, "entregas_diferidas", lambda t: [])
    monkeypatch.setattr(rl, "recuperar_informes", list)
    monkeypatch.setattr(rl.rondas, "revisar", lambda: llamadas.append("turnos"))
    monkeypatch.setattr(rl.time, "sleep", lambda t: (_ for _ in ()).throw(Fin()))
    with pytest.raises(Fin):
        rl.rules_loop()
    assert llamadas == ["turnos"]


def test_10_limpieza_solo_en_barrido(caso, monkeypatch):
    src, _, _ = caso
    src["consulta_intentada"] = ["vieja"]
    llamadas = []
    limpiar = p.limpiar
    monkeypatch.setattr(p, "limpiar", lambda s: llamadas.append(s) or limpiar(s))
    ses.set_state(src, "corriendo")
    assert llamadas == []
    p.barrer()
    assert llamadas == [src]
    assert "consulta_intentada" not in src


@pytest.mark.parametrize(
    "pregunta", ["Background server has incompatible feature settings", "Do you trust this folder?", "Switch model?"]
)
def test_cart_respuesta_explicita_cualquier_dialogo(caso, monkeypatch, pregunta):
    src, _, calls = caso
    src.update(needs={"kind": "dialog"}, dialog=dialogo(pregunta))
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    p.consultar(src)
    assert calls == []
    assert p.responder(src, {"opcion": 1})[0] == 200


def test_cart_error_dialog_open_nombra_responder(caso):
    src, _, _ = caso
    src["dialog"] = dialogo("Switch model?")
    code, out = ses.dialogo_abierto(src)
    assert code == 409 and out["code"] == "dialog_open"
    assert f"POST /sessions/{src['session_id']}/responder {{opcion: n}}" in out["error"]


def test_cart_dialogo_numerico_no_manda_enter(caso, monkeypatch):
    src, _, _ = caso
    d = dialogo("Switch model?")
    src.update(needs={"kind": "dialog"}, dialog=d)
    teclas = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "_dialogo_en_pantalla", lambda *a: (d, None))
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: teclas.append((a[1], k)) or (200, {}))
    assert p.responder(src, {"opcion": 2})[0] == 200
    assert teclas == [("2", {"enter": False})]


def test_04_no_copia_historial_ni_capturas(caso):
    src, dst, calls = caso

    class Captura:
        def __deepcopy__(self, memo):
            pytest.fail("copió historial ajeno a la pregunta")

    src["historial"] = Captura()
    dst["historial"] = Captura()
    p.consultar(src)
    assert len(calls) == 1


def test_07_reserva_destino_sobrevive_recarga(entorno, monkeypatch):
    import datetime as dt

    import rules as rl
    import server
    import state

    r, _ = entorno
    t = dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC)
    r["informes"] = [
        {"id": n, "estado": "entregado", "entregado_at": (t - dt.timedelta(hours=1)).isoformat()}
        for n in ("primero", "segundo")
    ]
    envios = []
    monkeypatch.setattr(server, "_route_session", lambda sid: (None, "remota"))
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *a: envios.append(a) or (200, {}))
    rl.recordar_informes(t)
    state.rules.load(lambda _: True)
    rl.recordar_informes(t + dt.timedelta(seconds=5))
    assert len(envios) == 1


def test_09_trabajador_propio_con_parada(monkeypatch):
    from threading import Event, Thread, current_thread

    import rules as rl

    stop, nombres = Event(), []

    def recordar(t):
        nombres.append(current_thread().name)
        stop.set()

    monkeypatch.setattr(rl, "recordar_informes", recordar)
    hilo = Thread(target=rl.recordatorios_loop, args=(stop,), name="recordatorios-prueba")
    hilo.start()
    hilo.join(2)
    assert not hilo.is_alive() and nombres == ["recordatorios-prueba"]
