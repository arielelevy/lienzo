"""Regresiones de los diez hallazgos, en el orden de la revisión."""

import preguntas as p
import pytest
import sessions as ses

pytest_plugins = ["test_backlog_b_informes"]


@pytest.fixture
def caso(monkeypatch):
    src = {
        "session_id": "rev-F",
        "agent": "claude",
        "repo_key": "repo-F",
        "state": "te_necesita",
        "needs": {
            "kind": "question",
            "since": "hora",
            "detail": "¿Cómo seguimos?",
            "options": [{"n": 1, "text": "Continuar"}, {"n": 2, "text": "Parar"}],
        },
    }
    dst = {"session_id": "coord-F", "repo_key": "repo-F", "coordinator": True, "alive": True, "title": "★ F"}
    monkeypatch.setattr(ses, "sessions", {src["session_id"]: src, dst["session_id"]: dst})
    monkeypatch.setattr(ses, "_mirror_sessions", list)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    calls = []
    monkeypatch.setattr(p, "enviar", lambda *a: calls.append(a) or (200, {}))
    return src, dst, calls


@pytest.mark.parametrize(
    "agent,question,options",
    [
        ("claude", "Do you trust the files in this folder?", ["Yes", "No"]),
        ("claude", "Switch model?", ["Sonnet", "Opus"]),
        ("kiro", "Kiro requiere permiso (comando parcialmente visible)", ["Deny", "Always deny"]),
        ("claude", "Desconocido", ["Uno", "Dos"]),
    ],
)
def test_01_reservados_no_se_consultan(caso, agent, question, options):
    src, _, calls = caso
    src.update(
        agent=agent,
        needs={"kind": "dialog", "since": "hora"},
        auto_aprobar_omitido="omitido",
        dialog={"question": question, "options": [{"n": i, "text": t} for i, t in enumerate(options, 1)]},
    )
    p.consultar(src)
    assert calls == []


def test_02_scan_pending_no_hace_io_de_consultas(caso, monkeypatch):
    monkeypatch.setattr(ses, "read_pending", dict)
    monkeypatch.setattr(ses, "pending", {})
    monkeypatch.setattr(p, "barrer", lambda: pytest.fail("consulta dentro del barrido de permisos"))
    ses.scan_pending_once()


def test_02_excepcion_no_corta_otra_tarjeta(caso, monkeypatch):
    src, _, _ = caso
    otra = {**src, "session_id": "otra-F"}
    ses.sessions[otra["session_id"]] = otra
    vistas = []

    def consultar(s):
        vistas.append(s["session_id"])
        if s is src:
            raise RuntimeError("fallo deliberado")

    monkeypatch.setattr(p, "consultar", consultar)
    p.barrer()
    assert vistas == [src["session_id"], "otra-F"]


def test_03_cerrar_limpia_metadatos(caso):
    src, _, _ = caso
    p.consultar(src)
    src["respuesta_coordinadora"] = {"por": "alguien", "texto": "viejo"}
    ses.set_state(src, "corriendo")
    p.barrer()
    assert "consulta_coordinadora" not in src
    assert "respuesta_coordinadora" not in src


def test_03_nueva_pregunta_no_hereda_conflicto(caso, monkeypatch):
    src, _, _ = caso
    p.consultar(src)
    src["needs"] = {**src["needs"], "since": "nueva", "detail": "¿Qué hacemos ahora?"}
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    assert p.responder(src, {"opcion": 1})[0] == 200


def test_07_guardado_fallido_no_corta_siguiente_informe(entorno, monkeypatch):
    import datetime as dt

    import rules as rl
    import state

    r, sends = entorno
    i = {"id": "falla", "estado": "entregado", "entregado_at": "2026-10-24T00:00:00+00:00"}
    r["informes"] = [i]
    otro = {**r, "id": "otra-regla", "to": "otro-destino", "informes": [{**i, "id": "sigue"}]}
    state.rules.items.append(otro)
    state.sessions["otro-destino"] = {"session_id": "otro-destino", "state": "termino"}
    saves, publicaciones = [], []

    def guardar(**kw):
        saves.append(kw)
        if len(saves) == 1:
            raise OSError("disco deliberado")
        return True

    monkeypatch.setattr(rl.rules, "save", guardar)
    monkeypatch.setattr(rl.rules, "publish", lambda: publicaciones.append(True))
    rl.recordar_informes(dt.datetime(2026, 10, 24, 1, tzinfo=dt.UTC))
    assert len(sends) == 1 and "sigue" in sends[0]
    assert "recordatorio_at" not in i
    assert all(kw == {"strict": True} for kw in saves)
    assert len(publicaciones) == 2


@pytest.mark.parametrize(
    "autor,esperado", [(None, "tablero"), ("otro-sin-titulo", "otro-sin"), ("otro-con-titulo", "Revisor")]
)
def test_08_autor_real_de_la_respuesta(caso, monkeypatch, autor, esperado):
    src, _, _ = caso
    p.consultar(src)
    if autor:
        ses.sessions[autor] = {"session_id": autor, "title": "Revisor" if autor.endswith("con-titulo") else None}
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    body = {"opcion": 1, **({"from": autor} if autor else {})}
    assert p.responder(src, body)[0] == 200
    assert src["respuesta_coordinadora"]["por"] == esperado


@pytest.mark.parametrize("codigo", [503, 409, 404])
def test_09_reintento_con_espera_y_sucesora(caso, monkeypatch, codigo):
    src, dst, calls = caso
    reloj = [0]
    monkeypatch.setattr(p, "time", lambda: reloj[0])
    nueva = {**dst, "session_id": "nueva-coord"}

    def enviar(sid, body):
        calls.append(sid)
        if len(calls) == 1:
            return codigo, ({"sucesora": nueva["session_id"]} if codigo == 404 else {"error": "ocupada"})
        return 200, {}

    monkeypatch.setattr(p, "enviar", enviar)
    p.consultar(src)
    if codigo == 404:
        ses.sessions[nueva["session_id"]] = nueva
    p.consultar(src)
    assert len(calls) == 1
    reloj[0] = 15
    p.consultar(src)
    assert len(calls) == 2
    assert calls[-1] == (nueva["session_id"] if codigo == 404 else dst["session_id"])


def test_09_reintentos_crecientes_con_tope(caso, monkeypatch):
    src, _, calls = caso
    reloj = [0]
    monkeypatch.setattr(p, "time", lambda: reloj[0])
    monkeypatch.setattr(p, "enviar", lambda *a: calls.append(reloj[0]) or (503, {"error": "caído"}))
    for t in (0, 1, 14, 15, 16, 44, 45, 46, 104, 105, 106, 225, 1000):
        reloj[0] = t
        p.consultar(src)
    assert calls == [0, 15, 45, 105]


@pytest.mark.parametrize("hora", [None, "misma"])
def test_10_pregunta_nueva_no_colisiona_sin_hora(caso, hora):
    src, _, calls = caso
    src["needs"]["since"] = hora
    p.consultar(src)
    src["needs"]["detail"] = "¿Qué hacemos con el siguiente lote?"
    p.consultar(src)
    p.consultar(src)
    assert len(calls) == 2


def test_10_reenvoltura_no_duplica(caso):
    src, _, calls = caso
    p.consultar(src)
    src["needs"]["detail"] = "¿Cómo\n  seguimos?"
    p.consultar(src)
    assert len(calls) == 1


def test_01_dialogo_de_trabajo_si_se_consulta(caso):
    src, _, calls = caso
    src.update(
        needs={"kind": "dialog", "since": "hora"},
        auto_aprobar_omitido="no es permiso",
        dialog={"question": "¿Cómo seguimos?", "options": [{"n": 1, "text": "Continuar"}, {"n": 2, "text": "Parar"}]},
    )
    p.consultar(src)
    assert len(calls) == 1


def test_06_envio_concurrente_y_cambio_durante_io(caso, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import state

    src, _, calls = caso
    iniciado, liberar = Event(), Event()

    def enviar(*a):
        calls.append(a)
        iniciado.set()
        assert liberar.wait(3)
        return 200, {}

    monkeypatch.setattr(p, "enviar", enviar)
    with ThreadPoolExecutor(1) as pool:
        trabajo = pool.submit(p.consultar, src)
        try:
            assert iniciado.wait(3)
            assert p.consultar(src)[0] == 409
            assert state.lock.acquire(timeout=1)
            try:
                src["needs"] = {**src["needs"], "since": "nueva", "detail": "Otra pregunta"}
            finally:
                state.lock.release()
        finally:
            liberar.set()
        trabajo.result(timeout=3)
    assert len(calls) == 1
    assert "consulta_coordinadora" not in src


def test_02_bucle_tiene_parada_y_trabajador_propio(monkeypatch):
    from threading import Event, Thread, current_thread

    stop = Event()
    nombres = []

    def barrer():
        nombres.append(current_thread().name)
        stop.set()

    monkeypatch.setattr(p, "barrer", barrer)
    hilo = Thread(target=p.bucle, args=(stop,), name="preguntas-prueba")
    hilo.start()
    hilo.join(timeout=3)
    assert not hilo.is_alive() and nombres == ["preguntas-prueba"]


def test_03_cambio_sin_coordinadora_limpia_vista(caso):
    src, dst, _ = caso
    p.consultar(src)
    src["respuesta_coordinadora"] = {"por": "antes", "texto": "viejo"}
    dst["coordinator"] = False
    src["needs"] = {**src["needs"], "since": "otra", "detail": "¿Qué hacemos después?"}
    p.consultar(src)
    assert "consulta_coordinadora" not in src and "respuesta_coordinadora" not in src


def test_03_pregunta_ya_no_visible_limpia_vista(caso, monkeypatch):
    src, _, _ = caso
    reloj = [0]
    monkeypatch.setattr(p, "time", lambda: reloj[0])
    p.consultar(src)
    src["needs"].pop("options")
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": []})
    p.consultar(src)
    assert "consulta_coordinadora" not in src


def test_08_cliente_y_http_conservan_autor(caso, monkeypatch):
    import importlib.util
    from pathlib import Path
    from threading import Thread

    import server

    src, _, _ = caso
    monkeypatch.setattr(server, "sessions", ses.sessions)
    path = Path(__file__).resolve().parents[1] / "skills/lienzo/coordinar.py"
    spec = importlib.util.spec_from_file_location("cliente_revision_F", path)
    cliente = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cliente)
    ses.sessions["autor-real"] = {"session_id": "autor-real", "title": "Otro coordinador"}
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    http = server.QuietServer(("127.0.0.1", 0), server.Handler)
    hilo = Thread(target=http.serve_forever, daemon=True)
    hilo.start()
    try:
        cliente.BASE = f"http://127.0.0.1:{http.server_port}"
        cliente.YO = "autor-real"
        code, out = cliente.responder(src["session_id"], opcion=1)
        assert code == 200, out
        assert src["respuesta_coordinadora"]["de"] == "autor-real"
        assert src["respuesta_coordinadora"]["por"] == "Otro coordinador"
    finally:
        http.shutdown()
        http.server_close()
        hilo.join(timeout=3)


def test_06_reemplazo_de_tarjeta_durante_lectura_no_envia(caso, monkeypatch):
    from copy import deepcopy

    import state

    src, _, calls = caso
    src["needs"].pop("options")
    reemplazo = deepcopy(src)

    def leer(s):
        with state.lock:
            ses.sessions[src["session_id"]] = reemplazo
        return {"ok": True, "lines": ["¿Cómo seguimos?", "> 1. Continuar", "  2. Parar"]}

    monkeypatch.setattr(ses, "read_screen", leer)
    p.consultar(src)
    assert calls == []
    assert "consulta_intentada" not in reemplazo


def test_04_dialogo_legacy_no_rechaza_reenvoltura(caso, monkeypatch):
    src, _, _ = caso
    visto = {"question": "Do you want to\nproceed?", "options": src["needs"]["options"]}
    actual = {**visto, "question": "Do you want to proceed?", "selected": 1}
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": []})
    monkeypatch.setattr(ses.screen, "dialog", lambda lines: actual)
    assert ses._dialogo_en_pantalla(src, visto)[0] == actual


def test_05_pantalla_ilegible_tiene_espera(caso, monkeypatch):
    src, _, _ = caso
    src["needs"].pop("options")
    reloj = [0]
    monkeypatch.setattr(p, "time", lambda: reloj[0])
    lecturas = []
    monkeypatch.setattr(ses, "read_screen", lambda s: lecturas.append(s) or {"ok": False, "error": "no legible"})
    for _ in range(10):
        p.consultar(src)
    assert len(lecturas) == 1
    reloj[0] = 5
    p.consultar(src)
    assert len(lecturas) == 2


def test_06_mutacion_con_lock_io_sin_lock(caso, monkeypatch):
    import state

    src, _, calls = caso
    guardadas = []

    def guardar(s):
        assert state.lock._lock._is_owned(), "mutación/publicación sin state.lock"
        guardadas.append(s)

    def enviar(*args):
        assert not state.lock._lock._is_owned(), "I/O bajo state.lock"
        calls.append(args)
        return 200, {}

    monkeypatch.setattr(ses, "touch", guardar)
    monkeypatch.setattr(p, "enviar", enviar)
    p.consultar(src)
    assert len(calls) == 1 and guardadas
    monkeypatch.setattr(p, "_terminal", lambda *a: (200, {}))
    assert p.responder(src, {"opcion": 1})[0] == 200


def test_un_envio_bueno_corta_la_racha_de_fallos():
    """Code review 2026-10-24: los fallos de una pregunta pasaban a la siguiente y la mandaban a la persona antes."""
    import preguntas

    s = {"session_id": "s1", "consulta_fallos": 3, "consulta_reintentar_en": 1.0}
    preguntas._resultado_envio(
        s, {"session_id": "c1", "title": "coord"}, {"question": "¿sigo?", "options": []}, 200, {}
    )
    assert "consulta_fallos" not in s and "consulta_reintentar_en" not in s
    assert s["consulta_coordinadora"]["a"] == "c1"
