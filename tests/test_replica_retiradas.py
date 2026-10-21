"""B04: retirada local frente a activaciones demoradas, con dos bases temporales."""

import copy

import conocimiento as k
import pytest
import replica
from test_replica import Red

P = "retiros"
C = "coordinadora:b"


@pytest.fixture
def red(tmp_path, monkeypatch):
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    return Red(tmp_path, monkeypatch)


def fila(de, rel, a):
    with k._abrir(P) as con:
        return dict(con.execute("SELECT * FROM vinculo WHERE de=? AND relacion=? AND a=?", (de, rel, a)).fetchone())


@pytest.mark.parametrize("modo", ["manual", "automatica"])
@pytest.mark.parametrize("reloj_atrasado", [False, True], ids=["reloj_normal", "reloj_atrasado"])
def test_retirada_nueva_gana_a_activacion_antigua_y_converge(red, monkeypatch, modo, reloj_atrasado):
    reloj = ["2026-10-21T01:00:00.000Z"]
    monkeypatch.setattr(k, "ahora", lambda: reloj[0])
    with red.en("pcA"):
        k.registrar_proyecto(P, remotes=["github.com/pruebas/retiros"])
        if modo == "manual":
            de = k.crear_nodo(P, "hallazgo", "dato", autor=C)["id"]
            a = k.crear_nodo(P, "tema", "tema", autor=C)["id"]
            rel = "sobre"
        else:
            ronda = k.abrir_ronda(P, "ronda", autor=C)
            de = k.crear_encargo(P, ronda["id"], "B", "encargo", autor=C)["id"]
            a = k.crear_nodo(
                P, "evidencia", "control previo", {"clase": "control_desarrollo", "control": "lint"}, autor=C
            )["id"]
            rel = "apoya"
        k.vincular(P, de, rel, a, autor=C)
    red.sync("pcB", "pcA")
    # B emite una activación anterior a la retirada de A, pero su paquete todavía no llega.
    reloj[0] = "2026-10-21T01:00:01.000Z"
    with red.en("pcB"):
        k.retirar_vinculo(P, de, rel, a, por=C)
        k.vincular(P, de, rel, a, autor=C)
        anterior = copy.deepcopy(k.cambios(P, limite=500)[-1])
        assert anterior["accion"] == "vinculo"
    reloj[0] = "2026-10-21T01:00:02.000Z"
    with red.en("pcA"):
        if reloj_atrasado:
            # A conoce un evento futuro: la retirada debe usar el mismo reloj causal que su log.
            observado = {**anterior, "pc": "pcC", "seq_origen": 99, "fecha": "2026-10-21T01:00:10.000Z"}
            with k._abrir(P) as con:
                assert replica.aplicar(con, P, observado)
        if modo == "manual":
            k.retirar_vinculo(P, de, rel, a, por=C)
        else:
            inf = k.crear_nodo(P, "informe", "revisión", autor=C)["id"]
            nuevo = k.crear_nodo(
                P, "evidencia", "control nuevo", {"clase": "control_desarrollo", "control": "lint"}, autor=C
            )["id"]
            k.vincular(P, nuevo, "declarado_en", inf, autor=C)
            with k._abrir(P) as con:
                k._atar_controles(con, P, inf, de, autor=C, origen={})
        retirada = next(c for c in reversed(k.cambios(P, limite=500)) if c["accion"] == "vinculo_retirado")
        antes = fila(de, rel, a)
        assert antes["activo"] == 0
        with k._abrir(P) as con:
            assert replica.aplicar(con, P, anterior)
        assert fila(de, rel, a)["activo"] == 0, "una activación atrasada revivió el vínculo"
        assert fila(de, rel, a)["fecha"] == retirada["fecha"]
    red.sync("pcB", "pcA")
    red.sync("pcA", "pcB")
    estados = []
    for pc in ("pcA", "pcB"):
        with red.en(pc):
            estados.append((fila(de, rel, a)["activo"], fila(de, rel, a)["fecha"]))
    assert estados == [(0, retirada["fecha"])] * 2
    # Positivo: una reactivación posterior deliberada sí vuelve a viajar.
    reloj[0] = "2026-10-21T01:00:20.000Z"
    with red.en("pcA"):
        k.vincular(P, de, rel, a, autor=C)
    red.sync("pcB", "pcA")
    for pc in ("pcA", "pcB"):
        with red.en(pc):
            assert fila(de, rel, a)["activo"] == 1
