"""reclasificar_creencias: la lista no cambia nada; aplicarla exige persona, no reescribe veredictos y deja las
viejas leídas como reemplazadas por una propuesta pendiente que conserva su evidencia."""

import subprocess

import conocimiento as k
import creencias
import pytest
import reclasificar_creencias as rc


@pytest.fixture(autouse=True)
def sin_procesos(monkeypatch):
    try:
        import prolog_programa
    except ModuleNotFoundError:
        prolog_programa = None
    if prolog_programa is not None:
        monkeypatch.setattr(prolog_programa, "notificar", lambda *a, **kw: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("proceso externo"))


def _revertida(texto, motivo, accion="Revisar por lotes"):
    fuente = k.crear_nodo("rc", "hallazgo", f"fuente de {texto}", {}, autor="server")
    n = creencias.proponer(
        "rc", {"texto": texto, "accion": accion, "dimension": "coordinacion", "fuentes": [fuente["id"]]}, autor="server"
    )
    k.cambiar_estado("rc", n["id"], "revertida", por="persona:Ariel (delegado a IA: claude)", motivo=motivo)
    return n


def _sembrar():
    k.registrar_proyecto("rc")
    copias = [
        _revertida(f"Frentes esperando a la coordinadora: {h} h en 9 esperas (mediana 16 min)", "beneficio no medido")
        for h in ("4.1", "37.0", "39.5")
    ]
    eficacia = _revertida("Preguntar de a 5 destrabó pendientes", "No hay evidencia de que haya destrabado; consejo")
    evidencia = _revertida("Un commit con backticks ejecutó comandos", "Sin evidencia en lo provisto")
    contra = _revertida("Algo que resultó falso", "La medición nueva la contradice")
    return copias, eficacia, evidencia, contra


def test_la_lista_clasifica_y_no_cambia_nada():
    copias, eficacia, evidencia, contra = _sembrar()
    antes = len(k.cambios("rc"))
    lista = rc.plan("rc")
    assert len(k.cambios("rc")) == antes
    assert [(g["metrica"], len(g["copias"])) for g in lista["medicion_repetida"]] == [("esperas_h", 3)]
    assert {(f["id"], f["falta"]) for f in lista["reabrir"]} == {
        (eficacia["id"], "eficacia"),
        (evidencia["id"], "evidencia"),
    }
    assert [f["id"] for f in lista["mantener"]] == [contra["id"]]


def test_aplicar_exige_persona():
    _sembrar()
    with pytest.raises(k.Rechazo):
        rc.aplicar("rc", rc.plan("rc"), "server")


def test_aplicar_recupera_sin_reescribir_veredictos_y_es_idempotente():
    copias, eficacia, evidencia, contra = _sembrar()
    out = rc.aplicar("rc", rc.plan("rc"), "persona:Ariel")
    assert len(out["creadas"]) == 3
    guardadas = {n["id"]: n for n in creencias.listar("rc")}
    for vieja in [*copias, eficacia, evidencia, contra]:
        assert guardadas[vieja["id"]]["estado"] == "revertida"  # la historia no se reescribe
    vista = {x["creencia"]: x for x in creencias.vista_proyecto("rc")["proyecto"]["items"]}
    assert {vista[v["id"]]["estado"] for v in [*copias, eficacia, evidencia]} == {"reemplazada"}
    assert vista[contra["id"]]["estado"] == "refutada"
    nuevas = [vista[i] for i in out["creadas"]]
    assert sorted(x["estado"] for x in nuevas) == [
        "pendiente_evidencia",
        "pendiente_validacion",
        "pendiente_validacion",
    ]
    canonica = next(guardadas[i] for i in out["creadas"] if guardadas[i]["datos"].get("clave") == "trabajo:esperas_h")
    assert len(canonica["datos"]["fuentes"]) == 3  # la evidencia de las tres copias sigue en la nueva
    # aplicar de nuevo no crea nada
    assert rc.aplicar("rc", rc.plan("rc"), "persona:Ariel")["creadas"] == []
