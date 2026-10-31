"""Fricción 41: espera autorizada, acotada y sin tapar trabajo nuevo ni permisos."""

import datetime as dt

import auditoria as au
import pytest


def tarjetas():
    ahora = dt.datetime.now(dt.UTC)
    frente = {
        "session_id": "a",
        "alive": True,
        "repo_key": "r",
        "state": "termino",
        "state_since": (ahora - dt.timedelta(minutes=20)).isoformat(),
        "prompt_id": "p",
    }
    coord = {**frente, "session_id": "c", "coordinator": True}
    return ahora, frente, coord


def declarar(frente, coord, ahora):
    return au.declarar_espera(
        frente,
        {"from": "c", "motivo": "suite global", "hasta": (ahora + dt.timedelta(minutes=30)).isoformat()},
        [frente, coord],
    )


def test_espera_legitima_y_vencimiento():
    ahora, frente, coord = tarjetas()
    assert declarar(frente, coord, ahora)[0] == 200
    links = [{"id": "e", "from": "a", "to": "c", "kind": "rule", "ts": frente["state_since"]}]
    h = au.clasificar([frente, coord], links, ahora)
    del_frente = [x for x in h if x["session_id"] == "a"]
    assert [x["tipo"] for x in del_frente] == ["espera_declarada"]
    assert au.filtrar(del_frente, {}, ahora)[0] == []
    h = au.clasificar([frente, coord], links, ahora + dt.timedelta(minutes=31))
    del_frente = [x for x in h if x["session_id"] == "a"]
    assert [x["tipo"] for x in del_frente] == ["bloqueo_olvidado"]
    assert len(au.filtrar(del_frente, {}, ahora + dt.timedelta(minutes=31))[0]) == 1


@pytest.mark.parametrize(
    "cambio",
    [{"coordinator": False}, {"alive": False}, {"stopped_by": "otro"}, {"repo_key": "otro"}, {"state": "muerta"}],
)
def test_solo_coordinadora_viva_del_repo(cambio):
    ahora, frente, coord = tarjetas()
    assert declarar(frente, {**coord, **cambio}, ahora)[0] == 403
    assert "espera_declarada" not in frente


@pytest.mark.parametrize("hasta", [None, "ayer", "2026-01-01T00:00:00Z", "2099-01-01T00:00:00"])
def test_rechaza_fecha_invalida(hasta):
    assert au.validar_espera({"from": "c", "motivo": "suite", "hasta": hasta})[0] == 400


@pytest.mark.parametrize(
    "cambio", [{"prompt_id": "nuevo"}, {"last_prompt": "otro"}, {"state_since": "2026-10-01T00:00:00Z"}]
)
def test_trabajo_nuevo_invalida_espera(cambio):
    ahora, frente, coord = tarjetas()
    declarar(frente, coord, ahora)
    frente.update(cambio)
    assert au.clasificar([frente, coord], [], ahora)[0]["tipo"] == "idle_evitable"


def test_cancelar_y_no_tapar_permisos_ni_errores():
    ahora, frente, coord = tarjetas()
    declarar(frente, coord, ahora)
    frente["state"] = "te_necesita"
    assert au.clasificar([frente, coord], [], ahora)[0]["tipo"] == "bloqueado_humano"
    frente.update(state="termino", last_error="error del modelo")
    assert au.clasificar([frente, coord], [], ahora)[0]["tipo"] == "turno_cortado"
    assert au.declarar_espera(frente, {"from": "c", "motivo": None}, [frente, coord])[0] == 200
    assert "espera_declarada" not in frente


def test_accion_registrada_y_cliente(monkeypatch):
    import sys
    from pathlib import Path

    import server

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "lienzo"))
    import coordinar as c

    assert ("PUT", "espera") in server.ACCIONES_SESION
    pedidos = []
    monkeypatch.setattr(c, "YO", "c")
    monkeypatch.setattr(c, "pedir", lambda *args: pedidos.append(args))
    c.declarar_espera("a", "suite", "2099-01-01T00:00:00Z")
    assert pedidos == [("PUT", "/sessions/a/espera", {"from": "c", "motivo": "suite", "hasta": "2099-01-01T00:00:00Z"})]


def test_http_real_declarar_publicar_persistir_y_cancelar(monkeypatch, tmp_path):
    import json
    import sys
    import threading
    from pathlib import Path

    import server
    import state

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "lienzo"))
    import coordinar as c

    ahora, frente, coord = tarjetas()
    frente.update(agent="claude", pid=0, title="frente")
    coord.update(agent="claude", pid=0, title="coordinadora")
    monkeypatch.setattr(state, "sessions", {"a": frente, "c": coord})
    # server y sessions importan el registro al cargar: apuntar los tres al mismo fixture.
    monkeypatch.setattr(server, "sessions", state.sessions)
    monkeypatch.setattr(server.ses, "sessions", state.sessions)
    Path(state.SESSIONS).mkdir(parents=True, exist_ok=True)
    instance = server.QuietServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    monkeypatch.setattr(c, "BASE", f"http://127.0.0.1:{instance.server_port}")
    monkeypatch.setattr(c, "YO", "c")
    try:
        code, res = c.declarar_espera("a", "suite global", (ahora + dt.timedelta(minutes=30)).isoformat())
        assert code == 200, res
        assert res["espera_declarada"]["motivo"] == "suite global"
        guardada = json.loads((Path(state.SESSIONS) / "a.json").read_text(encoding="utf-8"))
        assert guardada["espera_declarada"] == frente["espera_declarada"]
        assert server.ses.public_session(frente)["espera_declarada"] == frente["espera_declarada"]
        assert au.clasificar([frente, coord], [], ahora)[0]["tipo"] == "espera_declarada"
        assert c.declarar_espera("a")[0] == 200
        assert "espera_declarada" not in frente
        monkeypatch.setattr(c, "YO", "a")
        assert c.declarar_espera("a", "suite", "2099-01-01T00:00:00Z")[0] == 403
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(2)


@pytest.mark.parametrize("cancelar", [False, True])
def test_fallo_al_guardar_no_cambia_espera_en_memoria(monkeypatch, cancelar):
    import server

    ahora, frente, coord = tarjetas()
    anterior = None
    if cancelar:
        declarar(frente, coord, ahora)
        anterior = frente["espera_declarada"].copy()
    monkeypatch.setattr(server, "sessions", {"a": frente, "c": coord})
    monkeypatch.setattr(server, "touch", lambda s: (_ for _ in ()).throw(OSError("disco lleno")))
    cuerpo = {"from": "c", "motivo": None if cancelar else "suite", "hasta": "2099-01-01T00:00:00Z"}
    with pytest.raises(OSError, match="disco lleno"):
        server.accion_espera(frente, cuerpo)
    assert frente.get("espera_declarada") == anterior
