"""Estados de una creencia que no son refutación (pedido de Ariel, 2026-10-25): en `lienzo` las 20 «refutadas»
eran 7 reemplazadas, 10 copias de 2 observaciones con eficacia sin medir y 3 sin evidencia provista; ninguna
tenía evidencia en contra. Refutada queda para la evidencia en contra; lo demás se ve como lo que es."""

import subprocess

import conocimiento as k
import creencias
import pytest
from test_creencias_revision_ia import reply, seed


@pytest.fixture(autouse=True)
def sin_procesos(monkeypatch):
    try:
        import prolog_programa
    except ModuleNotFoundError:
        prolog_programa = None
    if prolog_programa is not None:
        monkeypatch.setattr(prolog_programa, "notificar", lambda *a, **kw: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("proceso externo"))


def _estados(pid="ab"):
    return {x["creencia"]: x for x in creencias.vista_proyecto(pid)["proyecto"]["items"]}


def _pendiente(falta):
    def decide(nodes, agent):
        out = reply(nodes, "pendiente")
        for item in out["items"]:
            item.update(falta=falta, motivo="La medición está respaldada; el beneficio de la acción no está medido")
        return out

    return decide


def test_ia_deja_pendiente_de_validar_sin_refutar():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=_pendiente("eficacia"))
    guardada = creencias.listar("ab")[0]
    assert guardada["estado"] == "propuesta" and guardada["datos"]["pendiente"]["falta"] == "eficacia"
    item = _estados()[node["id"]]
    assert item["estado"] == "pendiente_validacion" and item["pendiente"]["falta"] == "eficacia"
    assert item["motivo"] == creencias.MOTIVOS["pendiente_validacion"]


def test_falta_de_evidencia_es_pendiente_de_evidencia():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=_pendiente("evidencia"))
    assert _estados()[node["id"]]["estado"] == "pendiente_evidencia"


def test_pendiente_no_se_revisa_de_nuevo_hasta_que_llega_evidencia():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=_pendiente("eficacia"))
    vistas = []
    out = r.revisar("ab", "claude", decidir=lambda nodes, agent: vistas.append(nodes) or reply(nodes))
    assert vistas == [] and out["id"] is None  # sin evidencia nueva no gasta otra consulta
    nueva = k.crear_nodo("ab", "medicion", "La acción bajó la espera a la mitad", {}, autor="server")
    k.actualizar_datos("ab", node["id"], {"fuentes": [*node["datos"]["fuentes"], nueva["id"]]}, por="server")
    r.revisar("ab", "claude", decidir=lambda nodes, agent: vistas.append(nodes) or reply(nodes))
    assert [n["id"] for n in vistas[0]] == [node["id"]]
    assert creencias.listar("ab")[0]["estado"] == "vigente"
    assert creencias.listar("ab")[0]["datos"]["pendiente"] is None


def test_pendiente_sin_falta_es_invalida_y_no_cambia_nada():
    import creencias_revision_ia as r

    seed()

    def mala(nodes, agent):
        return reply(nodes, "pendiente")

    with pytest.raises(k.Rechazo):
        r.revisar("ab", "claude", decidir=mala)
    assert creencias.listar("ab")[0]["datos"].get("pendiente") is None


def test_rechazar_sigue_siendo_refutada():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=lambda nodes, agent: reply(nodes, "rechazar"))
    assert _estados()[node["id"]]["estado"] == "refutada"


def test_una_revertida_con_sucesora_se_lee_reemplazada():
    # las de antes del cambio: revertida + `reemplaza` que llega, sin reescribir su estado guardado
    vieja = seed()
    k.cambiar_estado("ab", vieja["id"], "revertida", por="persona:Ariel", motivo="corregida antes del cambio")
    sucesora = creencias.proponer(
        "ab",
        {
            "texto": "Versión corregida",
            "accion": "Verificar",
            "dimension": "pruebas",
            "fuentes": vieja["datos"]["fuentes"],
        },
        autor="server",
    )
    k.vincular("ab", sucesora["id"], "reemplaza", vieja["id"], autor="persona:Ariel", motivo="corrección")
    assert _estados()[vieja["id"]]["estado"] == "reemplazada"


def test_fusionar_deja_la_repetida_reemplazada():
    import creencias_revision_ia as r

    canonica = seed()
    repetida = creencias.proponer(
        "ab",
        {
            "texto": "Otra observación",
            "accion": "Correr pruebas",
            "dimension": "pruebas",
            "fuentes": canonica["datos"]["fuentes"],
        },
        autor="server",
    )
    with k._abrir("ab") as con:
        con.execute("BEGIN IMMEDIATE")
        r.fusionar(con, "ab", repetida["id"], canonica["id"], "persona:Ariel", "misma regla")
    assert {n["id"]: n["estado"] for n in creencias.listar("ab")}[repetida["id"]] == "reemplazada"
    assert _estados()[repetida["id"]]["estado"] == "reemplazada"


def _hallazgo(texto):
    return k.crear_nodo("ab", "hallazgo", texto, {}, autor="server")


def _medicion(texto, fuente):
    return creencias.proponer(
        "ab",
        {
            "texto": texto,
            "accion": "Revisar entregas por lotes",
            "dimension": "coordinacion",
            "fuentes": [fuente["id"]],
            "clave": "trabajo:espera_coordinadora",
        },
        autor="server",
    )


def test_la_misma_medicion_suma_a_la_creencia_abierta():
    k.registrar_proyecto("ab")
    primera = _medicion("Frentes esperando: 4.1 h en 9 esperas", _hallazgo("día 1"))
    segunda = _medicion("Frentes esperando: 37.0 h en 11 esperas", _hallazgo("día 2"))
    tercera = _medicion("Frentes esperando: 39.5 h en 18 esperas", _hallazgo("día 3"))
    assert segunda["id"] == tercera["id"] == primera["id"] and not tercera["creado"]
    unica = creencias.listar("ab")
    assert len(unica) == 1
    datos = unica[0]["datos"]
    assert len(datos["fuentes"]) == 3 and len(datos["observaciones"]) == 2
    assert datos["ultima_observacion"] == "Frentes esperando: 39.5 h en 18 esperas"
    item = _estados()[primera["id"]]
    assert item["observaciones"] == 3 and item["ultima_observacion"].startswith("Frentes esperando: 39.5")


def test_repetir_la_misma_fuente_no_cambia_nada():
    k.registrar_proyecto("ab")
    h = _hallazgo("día 1")
    a = _medicion("Frentes esperando: 4.1 h", h)
    antes = len(k.cambios("ab"))
    _medicion("Frentes esperando: 4.1 h", h)
    assert len(k.cambios("ab")) == antes and len(creencias.listar("ab")) == 1 and a["creado"]


def test_despues_de_refutada_una_medicion_nueva_abre_otra():
    k.registrar_proyecto("ab")
    primera = _medicion("Frentes esperando: 4.1 h", _hallazgo("día 1"))
    k.cambiar_estado("ab", primera["id"], "revertida", por="persona:Ariel", motivo="evidencia en contra")
    otra = _medicion("Frentes esperando: 40 h", _hallazgo("día 9"))
    assert otra["id"] != primera["id"] and otra["creado"]


def test_aceptada_por_ia_sin_clausula_es_pendiente_de_formalizar_y_no_entra_al_checklist():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=lambda nodes, agent: reply(nodes))
    item = _estados()[node["id"]]
    assert item["estado"] == "pendiente_formalizacion"
    assert item["motivo"] == creencias.MOTIVOS["pendiente_formalizacion"]
    assert all(x["creencia"] != node["id"] for x in creencias.checklist("ab", {})["items"])


def test_el_prompt_ofrece_pendiente_y_no_manda_rechazar_por_falta_de_beneficio(monkeypatch):
    import creencias_revision_ia as r

    monkeypatch.setattr(r.shutil, "which", lambda value: value)
    vistos = {}

    def runner(argv, **kwargs):
        vistos["prompt"] = kwargs["stdin_text"]
        return {"code": 0, "stdout": '{"items": []}'}

    r.consultar([], {}, "claude", runner=runner)
    prompt = vistos["prompt"]
    assert "pendiente" in prompt and "falta=eficacia" in prompt and "falta=evidencia" in prompt
    assert "rechazá consejos sin evidencia" not in prompt
