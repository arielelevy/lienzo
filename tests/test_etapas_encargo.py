"""Etapas por encargo (Prime Agent, decision 15 de Ariel del 2026-10-22): pendiente -> implementacion ->
revision -> verificacion -> aprobado. Un turno cerrado o una respuesta del agente solo llevan a
revision: pasar a verificacion y aprobar es de la coordinadora o de una persona, con evidencia vinculada
en esa etapa; un fallo devuelve el encargo a implementacion con motivo. Sobre un LIENZO_HOME temporal."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import conocimiento_api as api
from conocimiento import Rechazo

C = "coordinadora:sid-coord"


@pytest.fixture
def proy():
    return k.registrar_proyecto("teorema", "Teorema", ["github.com/arielelevy/teorema"], [])


def _entregado(letra="A"):
    r = k.abrir_ronda("teorema", "ronda de etapas", autor=C)
    e = k.crear_encargo("teorema", r["id"], letra, f"# Encargo {letra}", autor=C)
    k.encargo_enviado("teorema", e["id"], {"session_id": f"sid-frente-{letra}", "agent": "claude"})
    k.entregar("teorema", e["id"], "## Informe r1\n\nlisto", revision=1, autor=f"frente:sid-frente-{letra}")
    assert k.nodo("teorema", e["id"])["estado"] == "entregado"
    return e["id"]


def _evidencia(eid, nombre):
    ev = k.recibir_evidencia("teorema", nombre, nombre.encode(), clase="revision", autor=C)
    k.vincular("teorema", eid, "apoya", ev["id"], autor=C)
    return ev["id"]


def test_etapa_de_cada_estado():
    assert [k.etapa_encargo(x) for x in ("pendiente", "enviado", "entregado", "verificando", "aprobado")] == [
        "pendiente",
        "implementacion",
        "revision",
        "verificacion",
        "aprobado",
    ]
    assert k.etapa_encargo("sin_entrega") == "sin_entrega"
    assert k.ETAPAS_ENCARGO == ("pendiente", "implementacion", "revision", "verificacion", "aprobado")


def test_recorrido_completo_con_evidencia_por_etapa(proy):
    eid = _entregado()
    _evidencia(eid, "code-review-L.md")
    assert k.cambiar_estado("teorema", eid, "verificando", por=C, motivo="revision ok")["estado"] == "verificando"
    _evidencia(eid, "pruebas-L.json")
    n = k.cambiar_estado("teorema", eid, "aprobado", por="persona:Ariel", motivo="verificado")
    assert n["estado"] == "aprobado" and k.etapa_encargo(n["estado"]) == "aprobado"
    estados = [c["nuevo"].get("estado") for c in k.nodo("teorema", eid)["cambios"] if c["accion"] == "estado"]
    assert estados[-3:] == ["entregado", "verificando", "aprobado"]


def test_sin_evidencia_de_la_etapa_no_avanza(proy):
    eid = _entregado()
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "verificando", por=C)
    assert x.value.codigo == 409 and "evidencia" in str(x.value)
    _evidencia(eid, "code-review-L.md")
    k.cambiar_estado("teorema", eid, "verificando", por=C)
    # la evidencia de la revision no sirve para aprobar: la verificacion trae la suya
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "aprobado", por=C)
    assert x.value.codigo == 409
    # un veredicto puede citar la evidencia en origen, como corregido_en; citar otra cosa no sirve
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "aprobado", por=C, origen={"evidencia": eid})
    assert x.value.codigo == 409 and "no es una evidencia" in str(x.value)
    ev = k.recibir_evidencia("teorema", "suite.txt", b"verde", clase="prueba", autor=C)
    assert k.cambiar_estado("teorema", eid, "aprobado", por=C, origen={"evidencia": ev["id"]})["estado"] == "aprobado"


@pytest.mark.parametrize("por", ["frente:sid-frente-A", "server"])
def test_ni_el_frente_ni_el_server_avanzan_ni_aprueban(proy, por):
    eid = _entregado()
    _evidencia(eid, "code-review-L.md")
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "verificando", por=por)
    assert x.value.codigo == 403
    k.cambiar_estado("teorema", eid, "verificando", por=C)
    _evidencia(eid, "pruebas-L.json")
    for nuevo in ("aprobado", "enviado"):
        with pytest.raises(Rechazo) as x:
            k.cambiar_estado("teorema", eid, nuevo, por=por, motivo="lo digo yo")
        assert x.value.codigo == 403
    assert k.nodo("teorema", eid)["estado"] == "verificando"


def test_aprobado_no_vuelve_atras_ni_salta_etapas(proy):
    eid = _entregado()
    ev = k.recibir_evidencia("teorema", "x.md", b"x", clase="revision", autor=C)
    with pytest.raises(Rechazo) as x:  # de revision no se salta a aprobado
        k.cambiar_estado("teorema", eid, "aprobado", por=C, origen={"evidencia": ev["id"]})
    assert x.value.codigo == 409
    k.cambiar_estado("teorema", eid, "verificando", por=C, origen={"evidencia": ev["id"]})
    ev2 = k.recibir_evidencia("teorema", "y.txt", b"y", clase="prueba", autor=C)
    k.cambiar_estado("teorema", eid, "aprobado", por=C, origen={"evidencia": ev2["id"]})
    with pytest.raises(Rechazo):
        k.cambiar_estado("teorema", eid, "enviado", por=C, motivo="reabrir")


def test_evidencia_citada_es_del_proyecto_y_de_esta_etapa(proy):
    eid = _entregado()
    k.registrar_proyecto("otro", "Otro", [], [])
    ajena = k.recibir_evidencia("otro", "ajena.md", b"ajena", clase="revision", autor=C)
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "verificando", por=C, origen={"evidencia": ajena["id"]})
    assert x.value.codigo == 409 and "no es una evidencia del proyecto" in str(x.value)
    rev = k.recibir_evidencia("teorema", "rev.md", b"rev", clase="revision", autor=C)
    k.cambiar_estado("teorema", eid, "verificando", por=C, origen={"evidencia": rev["id"]})
    # la misma evidencia de la revision, citada otra vez, no aprueba la verificacion
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "aprobado", por=C, origen={"evidencia": [rev["id"]]})
    assert x.value.codigo == 409 and "de antes de esta etapa" in str(x.value)


def test_veredicto_vincula_y_avanza_en_el_mismo_lote(proy):
    import veredictos

    eid = _entregado()
    ev = k.recibir_evidencia("teorema", "rev.md", b"rev", clase="revision", autor=C)
    items = [{"de": eid, "relacion": "apoya", "a": ev["id"]}, {"nodo": eid, "estado": "verificando"}]
    veredictos.veredicto("teorema", items, por=C, motivo="revision ok")
    assert k.nodo("teorema", eid)["estado"] == "verificando"
    ev2 = k.recibir_evidencia("teorema", "suite.txt", b"verde", clase="prueba", autor=C)
    veredictos.veredicto("teorema", [{"nodo": eid, "estado": "aprobado"}], por=C, evidencia=[ev2["id"]])
    assert k.nodo("teorema", eid)["estado"] == "aprobado"


def test_entrega_tardia_del_informe_viejo_no_vuelve_a_revision(proy):
    eid = _entregado()
    k.cambiar_estado("teorema", eid, "enviado", por=C, motivo="falta la prueba en rojo")
    k.cambiar_estado("teorema", eid, "sin_entrega", por=C, motivo="vencio")
    k.entregar("teorema", eid, "## Informe r1\n\nlisto", revision=1, autor=C)
    assert k.nodo("teorema", eid)["estado"] == "sin_entrega"
    k.entregar("teorema", eid, "## Informe r2\n\ncon la prueba", revision=2, autor=C)
    assert k.nodo("teorema", eid)["estado"] == "entregado"


def test_fallo_de_verificacion_devuelve_a_implementacion_con_motivo(proy):
    eid = _entregado()
    _evidencia(eid, "code-review-L.md")
    k.cambiar_estado("teorema", eid, "verificando", por=C)
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado("teorema", eid, "enviado", por=C)
    assert x.value.codigo == 400 and "motivo" in str(x.value)
    n = k.cambiar_estado("teorema", eid, "enviado", por=C, motivo="la suite focal falla en test_x")
    assert n["estado"] == "enviado" and n["datos"]["devuelto_revision"] == 1
    assert k.etapa_encargo(n["estado"]) == "implementacion"
    # reenviar el informe viejo (o que el turno lo vuelva a capturar) no lo saca de implementacion
    k.entregar("teorema", eid, "## Informe r1\n\nlisto", revision=1, autor="frente:sid-frente-A")
    assert k.nodo("teorema", eid)["estado"] == "enviado"
    # un informe nuevo, aunque llegue solo al cerrar el turno, lo lleva a revision y nada mas
    k.entregar("teorema", eid, "## Informe r2\n\narreglado", revision=None, revision_siguiente=True, autor="server")
    assert k.nodo("teorema", eid)["estado"] == "entregado"


def test_revision_tambien_devuelve(proy):
    eid = _entregado()
    n = k.cambiar_estado("teorema", eid, "enviado", por=C, motivo="code review: 2 hallazgos")
    assert n["estado"] == "enviado" and n["datos"]["devuelto_revision"] == 1


def test_api_estado_respeta_roles_y_respaldo(proy):
    eid = _entregado()
    ruta = ["teorema", "encargos", eid, "estado"]
    assert api.dispatch("POST", ruta, {"estado": "verificando", "por": "frente:sid-frente-A"}, {})[0] == 403
    assert api.dispatch("POST", ruta, {"estado": "verificando", "por": C}, {})[0] == 409
    _evidencia(eid, "code-review-L.md")
    code, n = api.dispatch("POST", ruta, {"estado": "verificando", "por": C}, {})
    assert code == 200 and n["estado"] == "verificando"
    assert api.dispatch("POST", ruta, {"estado": "enviado", "por": C}, {})[0] == 400
    assert api.dispatch("POST", ruta, {"estado": "enviado", "por": C, "motivo": "falla"}, {})[0] == 200
