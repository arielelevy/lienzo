"""Consultas de trabajo: destino, identidad y respuesta sin teclas tardías."""

import pytest
import sessions as ses


def test_responder_registrado():
    import server

    assert ("POST", "responder") in server.ACCIONES_SESION


def test_valida_respuesta():
    import preguntas

    for d in ({}, {"opcion": True}, {"opcion": 0}, {"texto": ""}, {"texto": "x", "opcion": 1}):
        assert preguntas.validar(d)[0] == 400
    assert preguntas.validar({"opcion": 2}) is None


def test_pregunta_cerrada_no_teclea(monkeypatch):
    import preguntas

    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("tecla tardía"))
    assert preguntas.responder({"session_id": "F", "needs": None}, {"opcion": 1})[0] == 409


def test_envia_una_vez_a_repo(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "repo_key": "repo-F",
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy", "detail": "¿Seguir?", "options": [{"n": 1, "text": "Sí"}]},
    }
    dst = {"session_id": "coord-F", "repo_key": "repo-F", "coordinator": True, "alive": True, "title": "★ F"}
    monkeypatch.setattr(ses, "sessions", {"F": src, "coord-F": dst})
    monkeypatch.setattr(ses, "_mirror_sessions", list)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    import server

    calls = []
    monkeypatch.setattr(server, "atender_accion", lambda *a, **k: calls.append(a) or (200, {}))
    monkeypatch.setattr(
        preguntas, "enviar", lambda sid, d: server.atender_accion("POST", sid, "send", d, desde_tablero=True)
    )
    preguntas.consultar(src)
    preguntas.consultar(src)
    assert len(calls) == 1
    assert calls[0][1] == "coord-F"
    assert calls[0][3]["from"] == "F"
    assert calls[0][3]["sin_aviso"] is True


@pytest.mark.parametrize("resultado", [(200, {}), (500, {"error": "incierto"})])
def test_coordinadora_con_dialogo_espera_sin_duplicar(monkeypatch, resultado):
    import preguntas

    src = {
        "session_id": "F",
        "repo_key": "repo-F",
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy", "detail": "¿Seguir?", "options": [{"n": 1, "text": "Sí"}]},
    }
    dst = {"session_id": "coord-F", "repo_key": "repo-F", "coordinator": True, "alive": True}
    monkeypatch.setattr(ses, "sessions", {"F": src, "coord-F": dst})
    monkeypatch.setattr(ses, "_mirror_sessions", list)
    monkeypatch.setattr(ses, "touch", lambda s: None)
    reloj = [0]
    monkeypatch.setattr(preguntas, "time", lambda: reloj[0])
    calls = []

    def enviar(*a):
        calls.append(a)
        return (409, {"code": "dialog_open"}) if len(calls) == 1 else resultado

    monkeypatch.setattr(preguntas, "enviar", enviar)
    preguntas.consultar(src)
    preguntas.consultar(src)
    assert len(calls) == 1
    reloj[0] = 15
    preguntas.consultar(src)
    preguntas.consultar(src)
    assert len(calls) == 2


@pytest.mark.parametrize("coordinadora", [None, "otro-repo", "propia", "muerta", "detenida"])
def test_sin_destino_valido_no_envia(monkeypatch, coordinadora):
    import preguntas

    src = {
        "session_id": "F",
        "repo_key": "repo-F",
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy", "detail": "¿Seguir?", "options": [{"n": 1, "text": "Sí"}]},
    }
    dst = {"session_id": "coord", "repo_key": "repo-F", "coordinator": True, "alive": True}
    if coordinadora == "otro-repo":
        dst["repo_key"] = "otro"
    if coordinadora == "propia":
        src.update(coordinator=True, alive=True)
    if coordinadora == "muerta":
        dst["alive"] = False
    if coordinadora == "detenida":
        dst["stopped_by"] = "user"
    monkeypatch.setattr(ses, "sessions", {"F": src, **({"coord": dst} if coordinadora not in (None, "propia") else {})})
    monkeypatch.setattr(ses, "_mirror_sessions", list)
    monkeypatch.setattr(preguntas, "enviar", lambda *a: pytest.fail("destino incorrecto"))
    preguntas.consultar(src)


def test_hook_opcion_y_doble_respuesta(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy"},
        "pending_id": "hook-F",
    }
    p = {
        "request_id": "hook-F",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "¿Seguir?", "options": [{"label": "Sí"}, {"label": "No"}]}]},
    }
    monkeypatch.setattr(ses, "pending", {"hook-F": p})
    monkeypatch.setattr(ses, "touch", lambda s: None)
    calls = []
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: calls.append((a, k)) or (200, {}))
    assert preguntas.responder(src, {"opcion": 2})[0] == 200
    assert calls[0][1]["answers"] == {"¿Seguir?": "No"}
    assert preguntas.responder(src, {"opcion": 2})[0] == 409
    assert len(calls) == 1


def test_hook_vence_durante_respuesta_es_conflicto(monkeypatch):
    import preguntas

    d = {"pending_id": "hook-F", "answers": {}, "questions": [{"question": "F"}], "question": "F"}
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: (410, {"error": "el pedido ya vencio o fue contestado"}))
    assert preguntas._hook({}, d, "VERDE") == (409, {"error": "el pedido ya vencio o fue contestado"})


def test_otra_pregunta_mismas_opciones_no_teclea(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy"},
        "dialog": {"question": "¿Primera?", "options": [{"n": 1, "text": "Sí"}, {"n": 2, "text": "No"}], "selected": 1},
    }
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["¿Otra?", "> 1. Sí", "  2. No"]})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("tecla a otra pregunta"))
    assert preguntas.responder(src, {"opcion": 2})[0] == 409


def test_responder_remoto(monkeypatch):
    import server

    calls = []
    monkeypatch.setattr(server, "_route_session", lambda sid: (None, "pc-F"))
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *a: calls.append(a) or (200, {"ok": True}))
    assert server.atender_accion("POST", "remota-F", "responder", {"opcion": 2}, desde_tablero=True)[0] == 200
    assert calls == [("pc-F", "POST", "/sessions/remota-F/responder", {"opcion": 2})]


def test_coda_panel_lateral_y_numero_solo():
    import preguntas

    d = preguntas.dialogo_coda(
        [
            "PRUEBA F │ Metrics",
            "",
            "  1. ROJO │ Cost $0.00",
            " │ Details",
            "> 2. VERDE │",
            "",
            "  3. AZUL │ Changes",
            "",
            "  4. Type something… │",
            "↑↓ select · Enter confirm · 1–9 jump │",
        ]
    )
    assert d == {
        "question": "PRUEBA F",
        "options": [
            {"n": 1, "text": "ROJO"},
            {"n": 2, "text": "VERDE"},
            {"n": 3, "text": "AZUL"},
            {"n": 4, "text": "Type something…"},
        ],
        "selected": 2,
        "teclas": "flechas",
        "lector": "pregunta_coda",
    }
    assert preguntas.dialogo_coda(["PRUEBA F", "> 1. ROJO", "2. VERDE"]) is None


def test_texto_coda_revalida_editor(monkeypatch):
    import preguntas

    d = {"question": "F", "options": [{"n": 1, "text": "UNO"}, {"n": 2, "text": "Type something…"}], "selected": 1}
    src = {"agent": "coda"}
    moved, typed = [], []
    pantallas = iter([d, {**d, "selected": 2, "input_text": ""}])
    monkeypatch.setattr(ses, "_elegir_con_flechas", lambda *a: moved.append(a[2]) or (200, {}))
    monkeypatch.setattr(ses, "_dialogo_en_pantalla", lambda *a: (next(pantallas), None))
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: typed.append((a, k)) or (200, {}))
    assert preguntas._texto_coda(src, d, "TEXTO-F-LIBRE")[0] == 200
    assert moved == [2]
    assert typed[0][0][1] == "TEXTO-F-LIBRE"
    assert typed[0][1] == {"enter": True}
    monkeypatch.setattr(ses, "_dialogo_en_pantalla", lambda *a: ({**d, "selected": 2, "input_text": "de Ariel"}, None))
    assert preguntas._texto_coda(src, d, "otro")[0] == 409
    assert len(typed) == 1


def test_coda_pregunta_y_opcion_partidas():
    import preguntas

    d = preguntas.dialogo_coda(
        [
            "salida anterior │",
            "",
            "¿Denegaste el probe │",
            "y cómo seguimos? │",
            " █│",
            "> 1. Seguir con │",
            "los restantes │",
            "",
            "2. Parar │",
            "↑↓ select · Enter confirm · 1–9 jump │",
        ]
    )
    assert d["question"] == "¿Denegaste el probe y cómo seguimos?"
    assert d["options"][0] == {"n": 1, "text": "Seguir con los restantes"}


def test_hook_varias_preguntas_conserva_answers(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "state": "te_necesita",
        "needs": {"kind": "question", "since": "hoy"},
        "pending_id": "hook-F",
    }
    p = {
        "request_id": "hook-F",
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {"question": "¿Color?", "options": [{"label": "VERDE"}]},
                {"question": "¿Lugar?", "options": [{"label": "ARRIBA"}]},
            ]
        },
    }
    monkeypatch.setattr(ses, "pending", {"hook-F": p})
    monkeypatch.setattr(ses, "touch", lambda s: None)
    calls = []
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: calls.append(k) or (200, {}))
    assert preguntas.responder(src, {"opcion": 1}) == (200, {"ok": True, "restantes": 1})
    assert calls == []
    assert preguntas.obtener(src)["question"] == "¿Lugar?"
    assert preguntas.responder(src, {"texto": "ABAJO"})[0] == 200
    assert calls == [{"answers": {"¿Color?": "VERDE", "¿Lugar?": "ABAJO"}}]


def test_permiso_vencido_con_dialogo_en_pantalla_se_contesta_por_la_terminal(monkeypatch):
    # openSeec 0.21-B, 2026-10-31: AskUserQuestion con PermissionTimeout; el Notification posterior dejó
    # needs.kind «permission» sin pending_id, el diálogo seguía en pantalla y responder daba 409
    import preguntas

    dialogo = {"question": "¿Primera?", "options": [{"n": 1, "text": "Sí"}, {"n": 2, "text": "No"}], "selected": 1}
    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": None,
        "needs": {"kind": "permission", "detail": "Claude needs your permission", "where": "terminal"},
        "dialog": dialogo,
    }
    tecleado = []
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["¿Primera?", "> 1. Sí", "  2. No"]})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "run_send", lambda s, texto, **k: (tecleado.append(k.get("key")), (200, {"ok": True}))[1])
    assert preguntas.responder(src, {"opcion": 1})[0] == 200
    assert tecleado == ["enter"]  # la marcada: sólo Enter, con la pantalla revalidada
    # sin diálogo leído, un permiso sigue sin contestarse por acá
    otro = {**src, "dialog": None, "pregunta_respondida": None}
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["nada"]})
    assert preguntas.responder(otro, {"opcion": 1})[0] == 409


def test_notification_permission_no_bloquea_cuatro_preguntas_hook(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "state": "te_necesita",
        "pending_id": "hook-F",
        "needs": {"kind": "permission", "where": "terminal"},
    }
    qs = [
        {"question": nombre, "options": [{"label": "Sí"}, {"label": "No"}]}
        for nombre in ("Motor", "K8s", "Helm", "Ausencias")
    ]
    p = {"request_id": "hook-F", "tool_name": "AskUserQuestion", "tool_input": {"questions": qs}}
    monkeypatch.setattr(ses, "pending", {"hook-F": p})
    monkeypatch.setattr(ses, "touch", lambda s: None)
    calls = []
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: (calls.append(k), (200, {}))[1])
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("hook vivo: no teclear"))
    assert preguntas.obtener(src)["question"] == "Motor"  # también se puede derivar a la coordinadora
    for nombre in ("Motor", "K8s", "Helm", "Ausencias"):
        assert preguntas.obtener(src, explicito=True)["question"] == nombre
        assert preguntas.responder(src, {"opcion": 2})[0] == 200
    assert calls == [{"answers": {q["question"]: "No" for q in qs}}]


@pytest.mark.parametrize("residual", [None, "ausente", "vencido"])
def test_pending_residual_no_encierra_responder_entre_dos_409(monkeypatch, residual):
    import preguntas

    dialogo = {"question": "Motor", "options": [{"n": 1, "text": "Sí"}, {"n": 2, "text": "No"}], "selected": 1}
    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": residual,
        "needs": {"kind": "permission", "where": "terminal"},
        "dialog": dialogo,
    }
    p = {
        "request_id": "vencido",
        "tool_name": "AskUserQuestion",
        "expires_at": "2026-01-01T00:00:00Z",
        "tool_input": {"questions": [{"question": "Motor", "options": [{"label": "Sí"}, {"label": "No"}]}]},
    }
    monkeypatch.setattr(ses, "pending", {"vencido": p})
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["Motor", "> 1. Sí", "  2. No"]})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: pytest.fail("no contestar al hook vencido"))
    tecleado = []
    monkeypatch.setattr(ses, "run_send", lambda s, t, **k: (tecleado.append(k.get("key")), (200, {}))[1])
    assert preguntas.responder(src, {"opcion": 1})[0] == 200
    assert tecleado == ["enter"]


def test_pregunta_vencida_sin_dialogo_no_elige_recomendada(monkeypatch):
    import preguntas

    src = {
        "session_id": "G",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": "vencido",
        "needs": {"kind": "permission", "where": "terminal"},
    }
    p = {
        "request_id": "vencido",
        "tool_name": "AskUserQuestion",
        "expires_at": "2026-01-01T00:00:00Z",
        "tool_input": {"questions": [{"question": "Motor", "options": [{"label": "Sí (Recommended)"}]}]},
    }
    monkeypatch.setattr(ses, "pending", {"vencido": p})
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["Working..."]})
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("no elegir una recomendada sin diálogo"))
    monkeypatch.setattr(ses, "answer_pending", lambda *a, **k: pytest.fail("hook vencido"))
    assert preguntas.responder(src, {"opcion": 1})[0] == 409


def test_cuatro_pestanas_vencidas_con_igual_encabezado_no_son_un_duplicado(monkeypatch):
    import preguntas

    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": "ausente",
        "needs": {"kind": "permission", "where": "terminal"},
    }
    monkeypatch.setattr(ses, "pending", {})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    tecleado = []
    monkeypatch.setattr(ses, "run_send", lambda s, t, **k: (tecleado.append(k.get("key")), (200, {}))[1])
    for nombre in ("Motor", "K8s", "Helm", "Ausencias"):
        lineas = ["Motor K8s Helm Ausencias", nombre, "> 1. Sí", "  2. No"]
        src["dialog"] = ses.screen.dialog(lineas)
        monkeypatch.setattr(ses, "read_screen", lambda s, lines=lineas: {"ok": True, "lines": lines})
        assert preguntas.responder(src, {"opcion": 1})[0] == 200
    assert tecleado == ["enter"] * 4


def test_cambio_de_pestana_con_iguales_opciones_no_teclea(monkeypatch):
    import preguntas

    anterior = ses.screen.dialog(["Motor K8s Helm Ausencias", "Motor", "> 1. Sí", "  2. No"])
    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": "ausente",
        "needs": {"kind": "permission"},
        "dialog": anterior,
    }
    monkeypatch.setattr(ses, "pending", {})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(
        ses, "read_screen", lambda s: {"ok": True, "lines": ["Motor K8s Helm Ausencias", "K8s", "> 1. Sí", "  2. No"]}
    )
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("no responder otra pestaña"))
    assert preguntas.responder(src, {"opcion": 1})[0] == 409


@pytest.mark.parametrize("barrera", [{"stopped_by": "otro"}, {"pid": None}])
def test_pendiente_residual_no_salta_guardas_de_terminal(monkeypatch, barrera):
    import preguntas

    src = {
        "session_id": "F",
        "agent": "claude",
        "pid": 999,
        "state": "te_necesita",
        "pending_id": "ausente",
        "needs": {"kind": "permission"},
        "dialog": {"question": "Motor", "options": [{"n": 1, "text": "Sí"}, {"n": 2, "text": "No"}], "selected": 1},
        **barrera,
    }
    monkeypatch.setattr(ses, "pending", {})
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: pytest.fail("guarda omitida"))
    assert preguntas.responder(src, {"opcion": 1})[0] == 409


def test_responder_http_sale_del_bucle_409_con_pending_vencido(monkeypatch):
    import sys
    import threading
    from pathlib import Path

    import server
    import state

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "lienzo"))
    import coordinar as c

    src = ses.new_session("F", "claude", "hook")
    lineas = ["Motor K8s Helm Ausencias", "Motor", "> 1. Sí", "  2. No"]
    src.update(
        alive=True,
        pid=999,
        state="te_necesita",
        pending_id="vencido",
        needs={"kind": "permission", "where": "terminal"},
        dialog=ses.screen.dialog(lineas),
    )
    registro = {"F": src}
    monkeypatch.setattr(server, "sessions", registro)
    monkeypatch.setattr(ses, "sessions", registro)
    monkeypatch.setattr(
        ses,
        "pending",
        {
            "vencido": {
                "request_id": "vencido",
                "expires_at": "2026-01-01T00:00:00Z",
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Motor", "options": [{"label": "Sí"}]}]},
            }
        },
    )
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": lineas})
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    tecleado = []
    monkeypatch.setattr(ses, "run_send", lambda s, t, **k: (tecleado.append(k.get("key")), (200, {}))[1])
    Path(state.SESSIONS).mkdir(parents=True, exist_ok=True)
    instance = server.QuietServer(("127.0.0.1", 0), server.Handler)
    hilo = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    hilo.start()
    monkeypatch.setattr(c, "BASE", f"http://127.0.0.1:{instance.server_port}")
    monkeypatch.setattr(c, "YO", "")
    try:
        assert c.responder("F", opcion=1)[0] == 200
        assert tecleado == ["enter"]
        assert src["respuesta_coordinadora"]["texto"] == "Sí"
    finally:
        instance.shutdown()
        instance.server_close()
        hilo.join(2)
