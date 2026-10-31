"""coordinar.liberar_turno dice quién suelta el turno, para que el lienzo le avise al dueño (openSeec, 2026-10-30)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c


def test_esperar_turno_solo_retorna_con_otorgado(monkeypatch):
    respuestas = iter([(202, {"otorgado": False}), (200, {"otorgado": False}), (200, {"otorgado": True})])
    monkeypatch.setattr(c, "pedir_turno", lambda *a, **kw: next(respuestas))
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    assert c.esperar_turno("motores", "a", cada=0.01) == (200, {"otorgado": True})


@pytest.mark.parametrize("respuesta", [(202, {"otorgado": False}), (404, {"error": "sesion desconocida"})])
def test_exigir_turno_rechazado_corta_y_retira_pedido(monkeypatch, respuesta):
    retirados = []
    monkeypatch.setattr(c, "pedir_turno", lambda *a, **kw: respuesta)
    monkeypatch.setattr(c, "liberar_turno", lambda *a: (retirados.append(a), (200, {}))[1])
    with pytest.raises(RuntimeError):
        c.exigir_turno("motores", "a")
    assert retirados == [("motores", "a")]


def test_esperar_timeout_y_error_no_habilitan_motor(monkeypatch):
    ticks = iter([0, 0, 1])
    retirados = []
    monkeypatch.setattr(c.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    monkeypatch.setattr(c, "pedir_turno", lambda *a, **kw: (202, {"otorgado": False}))
    monkeypatch.setattr(c, "liberar_turno", lambda *a: (retirados.append(a), (200, {}))[1])
    with pytest.raises(TimeoutError):
        c.esperar_turno("motores", "a", timeout=1)
    assert retirados == [("motores", "a")]


def test_esperar_interrumpido_retira_pedido(monkeypatch):
    monkeypatch.setattr(c, "pedir_turno", lambda *a, **kw: (202, {"otorgado": False}))
    monkeypatch.setattr(c.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    retirados = []
    monkeypatch.setattr(c, "liberar_turno", lambda *a: (retirados.append(a), (200, {}))[1])
    with pytest.raises(KeyboardInterrupt):
        c.esperar_turno("motores", "a")
    assert retirados == [("motores", "a")]


@pytest.mark.parametrize("valor", [0, -1, float("inf"), float("nan"), True])
def test_esperar_rechaza_plazo_invalido_antes_de_pedir(monkeypatch, valor):
    monkeypatch.setattr(c, "pedir_turno", lambda *a, **kw: pytest.fail("no debe pedir"))
    with pytest.raises(ValueError):
        c.esperar_turno("motores", "a", timeout=valor)


def test_liberar_el_turno_de_otra_manda_por(monkeypatch):
    pedidos = []
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (pedidos.append(r), (200, {}))[1])
    monkeypatch.setattr(c, "YO", "coord")
    c.liberar_turno("motores", "g")
    c.liberar_turno("motores", "coord")
    assert pedidos == ["/turnos/motores?session_id=g&por=coord", "/turnos/motores?session_id=coord"]


def test_cerrar_sesion_manda_la_confirmacion(monkeypatch):
    # openSeec, 2026-10-30: /kill exige confirm=<session_id> y no había ayudante (se probó {} y {"confirmar": true})
    pedidos = []
    monkeypatch.setattr(
        c, "pedir", lambda m, r, cuerpo=None, timeout=20: (pedidos.append((m, r, cuerpo)), (200, {}))[1]
    )
    c.cerrar_sesion({"session_id": "s1"})
    assert pedidos == [("POST", "/sessions/s1/kill", {"confirm": "s1"})]


def test_un_envio_que_rebota_por_el_nombre_nativo_se_reintenta(monkeypatch):
    # openSeec 0.21: dos de cuatro encargos rebotaron con 409 «se está actualizando el nombre nativo»
    respuestas = [
        (409, {"error": "se está actualizando el nombre nativo; reintentá cuando termine"}),
        (200, {"ok": True}),
    ]
    enviados = []

    def pedir(m, r, cuerpo=None, timeout=20):
        if m == "POST":
            enviados.append(r)
            return respuestas.pop(0)
        raise AssertionError(r)

    tarjeta = {"session_id": "u1", "pc": "p", "pid": 1, "cwd": "x", "agent": "claude", "state": "termino"}
    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: [{**tarjeta, "state": "corriendo" if len(enviados) > 1 else "termino"}])
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = c.enviar_seguro(tarjeta, "leé el encargo", enlazar=False, espera=2)
    assert r["ok"] is True and len(enviados) == 2
