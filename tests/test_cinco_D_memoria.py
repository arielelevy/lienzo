"""Regresiones D: reutilización transaccional y contrato JSON hostil."""

import aprendizaje as ap
import conocimiento as k
import plugin_manifest as manifest
import pytest


@pytest.mark.parametrize("tipo", [[], {}, ["texto"], {"tipo": "texto"}])
def test_tipo_de_campo_no_hashable_se_reporta(tipo):
    result = manifest.validar(
        {
            "id": "prueba",
            "nombre": "Prueba",
            "version": "1.0.0",
            "compatibilidad": {"contrato": 1},
            "permisos": {},
            "configuracion": {"campos": [{"clave": "dato", "tipo": tipo}]},
        }
    )
    assert result["manifiesto"] is None
    assert any("configuracion.campos[0]" in error for error in result["errores"])


def test_lote_reutiliza_componente_y_relee_tras_retiro(monkeypatch):
    pid = "cinco-d"
    coord = "coordinadora:test"
    k.registrar_proyecto(pid)
    with k._abrir(pid) as con:
        incidentes = [k.crear_nodo(pid, "incidente", f"episodio {i}", {}, autor="f", con=con)["id"] for i in range(4)]
        for nuevo, viejo in zip(incidentes[1:], incidentes):
            k.vincular(pid, nuevo, "repite", viejo, autor=coord, con=con)
        for i, origen in enumerate(incidentes[:3]):
            regla = k.crear_nodo(pid, "regla", f"regla {i}", {"ambito": "proyecto"}, autor="f", con=con)
            k.vincular(pid, regla["id"], "derivada_de", origen, autor="f", con=con)
            k.cambiar_estado(pid, regla["id"], "vigente", por=coord, con=con)
            k.actualizar_datos(
                pid, regla["id"], {"vigente_desde": "2020-01-01T00:00:00Z"}, por=coord, motivo="medición", con=con
            )
    original = ap._grupo
    llamadas = []

    def contar(*args):
        llamadas.append(args[2])
        return original(*args)

    monkeypatch.setattr(ap, "_grupo", contar)
    cuestionadas = ap.cuestionar(pid)
    assert len(cuestionadas) == 3 and all(x["recien"] for x in cuestionadas)
    assert all(x["recurrencias"] == 3 for x in cuestionadas)
    assert len(llamadas) == 2  # una lectura bajo BEGIN IMMEDIATE y otra ficha en snapshot nuevo
    llamadas.clear()
    k.retirar_vinculo(pid, incidentes[3], "repite", incidentes[2], por=coord, motivo="distinta causa")
    releidas = ap.reglas_cuestionadas(pid)
    assert len(releidas) == 3 and all(x["recurrencias"] == 2 for x in releidas)
    assert len(llamadas) == 1
