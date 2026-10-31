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
