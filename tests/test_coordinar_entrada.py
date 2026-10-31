"""El encargo entró al agente, no sólo al server: transcript o pantalla, y un reenvío si no se ve en ninguno.

Caso real (ronda de cierre 0.18.0 de openSeec): un coda recién lanzado recibió el `send` (200) antes de
terminar de arrancar y quedó 30 min en su portada con la entrada vacía. El server pone `last_prompt` y
`corriendo` al teclear, así que la tarjeta parecía haberlo tomado.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def _tarjeta(sid, **kw):
    return {"session_id": sid, "pc": "pcB", "pid": 100, "cwd": r"D:\apps\x", "agent": "coda", "state": "termino", **kw}


def _server(monkeypatch, entra_en=None, pantalla_con=None, prompts_previos=()):
    """Un server falso: el POST siempre contesta 200 y la tarjeta pasa a `corriendo` (lo que hace el
    server al teclear). `entra_en` es el número de envío (1, 2…) desde el que el texto aparece en el
    transcript; `pantalla_con` lo que se ve en la consola."""
    enviados = []

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "POST":
            enviados.append(cuerpo["text"])
            return 200, {"ok": True}
        if r.endswith("/screen"):
            return 200, {"lines": ["coda v3", *(pantalla_con or [])]}
        if "/digest" in r:
            turnos = [{"prompt": p} for p in prompts_previos]
            if entra_en and len(enviados) >= entra_en:
                turnos.append({"prompt": enviados[-1]})
            return 200, {"turns": turnos}
        raise AssertionError(r)

    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: [_tarjeta("u1", state="corriendo" if enviados else "termino")])
    monkeypatch.setattr("time.sleep", lambda s: None)
    return enviados


def test_sin_confirmar_un_corriendo_del_server_basta_como_antes(monkeypatch):
    enviados = _server(monkeypatch)
    assert c.enviar_seguro(_tarjeta("u1"), "hola", enlazar=False, espera=2)["ok"] is True
    assert enviados == ["hola"]


def test_confirmar_ve_el_texto_en_el_transcript(monkeypatch):
    enviados = _server(monkeypatch, entra_en=1)
    r = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True)
    assert r["ok"] is True and r["entrada"] == "transcript" and r["reenviado"] is False
    assert enviados == ["leé el encargo F"]


def test_confirmar_reenvia_una_vez_si_no_aparece_en_ningun_lado(monkeypatch):
    enviados = _server(monkeypatch, entra_en=2)  # el primero se perdió en la portada
    r = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True)
    assert r["ok"] is True and r["entrada"] == "transcript" and r["reenviado"] is True
    assert enviados == ["leé el encargo F"] * 2


def test_confirmar_no_reenvia_mas_de_una_vez(monkeypatch):
    enviados = _server(monkeypatch)  # nunca aparece
    r = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True)
    assert r["ok"] is False and r["entrada"] is None and r["reenviado"] is True
    assert "no aparece" in r["motivo"] and len(enviados) == 2


def test_confirmar_no_reenvia_si_el_texto_esta_en_pantalla(monkeypatch):
    # tecleado pero sin pedido en el transcript (quizá sin Enter): reenviarlo lo duplicaría
    enviados = _server(monkeypatch, pantalla_con=["> leé el   encargo F"])
    r = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True)
    assert r["ok"] is True and r["entrada"] == "pantalla" and r["reenviado"] is False
    assert enviados == ["leé el encargo F"]


def test_un_pedido_igual_anterior_no_cuenta_como_entrada(monkeypatch):
    enviados = _server(monkeypatch, entra_en=2, prompts_previos=["leé el encargo F"])
    r = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True)
    assert r["reenviado"] is True and r["entrada"] == "transcript" and len(enviados) == 2


def test_un_texto_largo_se_busca_por_el_aviso_de_adjunto(monkeypatch):
    largo = "linea 1\nlinea 2"  # viaja como «Leé el archivo adjunto y respondé: Adjunto: …»
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, {"turns": [{"prompt": "x"}]}))
    previos = c._prompts("u1")
    monkeypatch.setattr(
        c,
        "pedir",
        lambda m, r, cuerpo=None, timeout=20: (
            200,
            {"turns": [{"prompt": "x"}, {"prompt": "Leé el archivo adjunto y respondé: Adjunto: C:\\m.md"}]},
        ),
    )
    assert c.entro(_tarjeta("u1"), largo, previos) == "transcript"


def test_lanzar_y_titular_con_texto_manda_el_encargo_y_lo_confirma(monkeypatch):
    c.YO = "coord"
    nueva = _tarjeta("pid-9", pid=9)
    vistas = [[], [nueva]]
    monkeypatch.setattr(c, "sesiones", lambda: vistas.pop(0) if len(vistas) > 1 else vistas[0])
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (200, {"ok": True}))
    monkeypatch.setattr("time.sleep", lambda s: None)
    llamadas = []
    monkeypatch.setattr(
        c, "enviar_seguro", lambda s, t, **kw: llamadas.append((s["session_id"], t, kw)) or {"ok": True}
    )
    r = c.lanzar_y_titular("pcB", r"D:\apps\x", "t", "coda", espera=5, texto="leé tu encargo")
    assert r["session_id"] == "pid-9" and r["encargo_envio"] == {"ok": True}
    assert llamadas[0][:2] == ("pid-9", "leé tu encargo") and llamadas[0][2]["confirmar"] is True


def _server_pid_a_uuid(monkeypatch, cwd_nuevo):
    """Coda lanzada a mano (openSeec P y Q, 2026-10-30): nace `pid-100`; tras el envío su primer hook la pasa
    a su UUID. Su pantalla y su transcript no muestran el texto con el formato que se busca."""
    enviados = []

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "POST":
            enviados.append(r)
            return (404, {"error": "no existe"}) if "/pid-" in r and enviados[:-1] else (200, {"ok": True})
        if r.endswith("/screen"):
            return 200, {"lines": ["coda v3"]}
        if "/digest" in r:
            return 200, {"turns": []}
        raise AssertionError(r)

    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(
        c,
        "sesiones",
        lambda: [_tarjeta("uuid-1", cwd=cwd_nuevo, state="corriendo")] if enviados else [_tarjeta("pid-100")],
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    return enviados


def test_confirmar_toma_el_paso_de_pid_a_uuid_como_entrada(monkeypatch):
    enviados = _server_pid_a_uuid(monkeypatch, r"D:\apps\x")
    r = c.enviar_seguro(_tarjeta("pid-100"), "leé el encargo P", enlazar=False, espera=2, confirmar=True)
    assert (r["ok"], r["entrada"], r["sid"], r["reenviado"]) == (True, "hook", "uuid-1", False)
    assert enviados == ["/sessions/pid-100/send"]


def test_reubicar_no_distingue_barras_ni_mayusculas_en_la_carpeta(monkeypatch):
    enviados = _server_pid_a_uuid(monkeypatch, "d:/Apps/x/")
    r = c.enviar_seguro(_tarjeta("pid-100"), "leé el encargo Q", enlazar=False, espera=2, confirmar=True)
    assert (r["ok"], r["sid"]) == (True, "uuid-1")
    assert enviados == ["/sessions/pid-100/send"]


def test_sin_aviso_se_conserva_al_reenviar_confirmacion(monkeypatch):
    enviados = _server(monkeypatch, entra_en=2)
    original = c.pedir
    cuerpos = []

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "POST":
            cuerpos.append(cuerpo)
        return original(m, r, cuerpo, timeout=timeout)

    monkeypatch.setattr(c, "YO", "coord")
    monkeypatch.setattr(c, "pedir", pedir)
    res = c.enviar_seguro(_tarjeta("u1"), "leé el encargo F", enlazar=False, espera=2, confirmar=True, sin_aviso=True)
    assert res["ok"] and len(enviados) == 2
    assert all(x["sin_aviso"] == "coord" for x in cuerpos)


def test_seguro_sin_aviso_exige_yo(monkeypatch):
    import pytest

    _server(monkeypatch)
    monkeypatch.setattr(c, "YO", "")
    with pytest.raises(ValueError, match="sin_aviso necesita c.YO"):
        c.enviar_seguro(_tarjeta("u1"), "sin acuse", sin_aviso=True)
