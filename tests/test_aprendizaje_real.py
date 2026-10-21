"""Primer corte del aprendizaje real (2026-10-19): captura obligatoria, controles atados al encargo,
checklist que explica por qué no aplica, aprendizajes al crear el encargo y uso declarado."""

import datetime as dt
import json
import os
import sys

import conocimiento as k
import conocimiento_api as api
import creencias as c
import patrones_desarrollo as p
import patrones_evidencia as pe
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar


def _futuro(dias=7):
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=dias)).isoformat()


def _creencia(pid, contexto, *, fuente=None, validar=True, accion="Correr el diagnóstico focal"):
    fuente = fuente or k.crear_nodo(pid, "hallazgo", "espera observada", {}, autor="server")
    belief = c.proponer(
        pid,
        {
            "texto": "Creencia " + accion,
            "accion": accion,
            "dimension": "pruebas",
            "contexto": contexto,
            "fuentes": [fuente["id"]],
        },
        autor="server",
    )
    evidence = k.crear_nodo(pid, "evidencia", "comparación revisada", {}, autor="persona:Ariel")
    if validar:
        c.resolver(
            pid,
            belief["id"],
            {
                "por": "persona:Ariel",
                "motivo": "revisado",
                "resultado": "validada",
                "evidencia": evidence["id"],
                "vigente_hasta": _futuro(),
            },
        )
    return belief, evidence, fuente


def _estado(pid, contexto, belief):
    out = c.checklist(pid, contexto)
    return next(x for x in out["items"] + out["no_aplican"] if x["creencia"] == belief["id"])


def _ronda(pid):
    k.registrar_proyecto(pid)
    return k.abrir_ronda(pid, "aprender", autor="coordinadora:c")["id"]


def test_encargo_sin_tipo_de_trabajo_es_400_y_sin_clasificar_se_cuenta_aparte():
    pid = "real-captura"
    ronda = _ronda(pid)
    for cuerpo in ({}, {"contexto_desarrollo": {"tecnologia": "python"}}, {"contexto_desarrollo": "refactor"}):
        code, body = api.dispatch("POST", [pid, "encargos"], {"ronda": ronda, "letra": "A", "texto": "x", **cuerpo}, {})
        assert code == 400 and "tipo_trabajo" in body["error"]
    assert k.nodos(pid, tipo="encargo")["total"] == 0
    code, e = api.dispatch(
        "POST",
        [pid, "encargos"],
        {"ronda": ronda, "letra": "A", "texto": "x", "contexto_desarrollo": {"tipo_trabajo": "sin_clasificar"}},
        {},
    )
    assert code == 200 and e["datos"]["contexto_desarrollo"] == {"tipo_trabajo": "sin_clasificar"}
    assert e["aprendizajes"] == [] and e["aprendizajes_texto"] == ""
    analysis = p.analizar(pid)
    assert analysis["sin_clasificar"] == 1 and analysis["patrones"] == []


def test_encargo_recibe_lo_aplicable_y_registra_que_se_mostro():
    pid = "real-encargo"
    ronda = _ronda(pid)
    belief, evidence, _ = _creencia(pid, {"tipo_trabajo": "refactor"})
    _creencia(pid, {"tipo_trabajo": "bugfix"}, accion="Otra cosa")
    code, e = api.dispatch(
        "POST",
        [pid, "encargos"],
        {
            "ronda": ronda,
            "letra": "A",
            "texto": "Simplificar",
            "contexto_desarrollo": {"tipo_trabajo": "refactor", "tecnologia": "python"},
        },
        {},
    )
    assert code == 200
    assert [x["creencia"] for x in e["aprendizajes"]] == [belief["id"]]
    assert "Correr el diagnóstico focal" in e["aprendizajes_texto"] and evidence["id"] in e["aprendizajes_texto"]
    assert "Otra cosa" not in e["aprendizajes_texto"]
    shown = k.nodo(pid, e["id"])["datos"]["aprendizajes_mostrados"]
    assert [x["creencia"] for x in shown] == [belief["id"]]
    assert k.nodo(pid, belief["id"])["datos"].get("usos") is None  # mostrar no es usar


def test_checklist_explica_cada_motivo_sin_cambiar_estados():
    pid = "real-motivos"
    k.registrar_proyecto(pid)
    ctx = {"tipo_trabajo": "bugfix", "agente": "codex"}
    propuesta, _, _ = _creencia(pid, ctx, validar=False, accion="propuesta")
    valida, evidence, _ = _creencia(pid, ctx, accion="valida")
    assert _estado(pid, ctx, propuesta)["estado"] == "sin_veredicto"
    assert _estado(pid, ctx, valida)["estado"] == "aplicable"
    assert _estado(pid, {"tipo_trabajo": "bugfix"}, valida)["estado"] == "contexto_insuficiente"
    assert _estado(pid, {"tipo_trabajo": "bugfix", "agente": "claude"}, valida)["estado"] == "fuera_de_contexto"
    k.actualizar_datos(pid, valida["id"], {"vigente_hasta": "2000-01-01T00:00:00+00:00"}, por="persona:Ariel")
    assert _estado(pid, ctx, valida)["estado"] == "vencida"
    k.retirar_vinculo(pid, valida["id"], "apoya", evidence["id"], por="persona:Ariel", motivo="se cae")
    item = _estado(pid, ctx, valida)
    assert item["estado"] == "respaldo_retirado" and item["motivo"] == c.MOTIVOS["respaldo_retirado"]
    k.cambiar_estado(pid, valida["id"], "revertida", por="persona:Ariel", motivo="no")
    assert _estado(pid, ctx, valida)["estado"] == "refutada"
    out = c.checklist(pid, ctx)
    assert out["total"] == 0 and out["no_aplican_total"] == 2
    assert k.nodo(pid, propuesta["id"])["estado"] == "propuesta"


@pytest.mark.parametrize("roto", ["refactor", [], {"inventado": "x"}, {"tipo_trabajo": 3}, None])
def test_contexto_registrado_invalido_falla_cerrado(roto):
    pid = "real-contexto-roto"
    k.registrar_proyecto(pid)
    belief, _, _ = _creencia(pid, {}, accion="ctx " + repr(roto))
    k.actualizar_datos(pid, belief["id"], {"contexto": roto}, por="persona:Ariel")
    for ctx in ({}, {"tipo_trabajo": "refactor"}):
        item = _estado(pid, ctx, belief)
        assert item["estado"] == "contexto_invalido"
        assert item["contexto"] == (roto if isinstance(roto, dict) else {})  # el dict roto se muestra para revisarlo
        assert c.checklist(pid, ctx)["items"] == []


def test_fuente_rechazada_cae_con_su_cadena_aunque_la_creencia_siga_vigente():
    pid = "real-caida"
    k.registrar_proyecto(pid)
    ctx = {"tipo_trabajo": "feature"}
    belief, _, fuente = _creencia(pid, ctx)
    vinculos = k.nodo(pid, belief["id"])["vinculos"]["salen"]
    assert any(v["relacion"] == "motivada_por" and v["a"] == fuente["id"] for v in vinculos)
    k.cambiar_estado(pid, fuente["id"], "rechazado", por="persona:Ariel", motivo="la medición estaba mal")
    item = _estado(pid, ctx, belief)
    assert item["estado"] == "respaldo_caido"
    assert item["cadenas"][0][-1]["id"] == fuente["id"]
    assert k.nodo(pid, belief["id"])["estado"] == "vigente"  # avisar no es refutar


def test_reproponer_no_reactiva_un_vinculo_de_fuente_retirado():
    pid = "real-repropuesta"
    k.registrar_proyecto(pid)
    fuente = k.crear_nodo(pid, "hallazgo", "h", {}, autor="server")
    data = {"texto": "t", "accion": "a", "dimension": "olas", "contexto": {}, "fuentes": [fuente["id"]]}
    belief = c.proponer(pid, data, autor="server")
    k.retirar_vinculo(pid, belief["id"], "motivada_por", fuente["id"], por="persona:Ariel", motivo="no corresponde")
    assert c.proponer(pid, data, autor="server")["id"] == belief["id"]
    assert not any(v["relacion"] == "motivada_por" for v in k.nodo(pid, belief["id"])["vinculos"]["salen"])


@pytest.mark.parametrize("por", ["server", "frente:x", "persona:", "coordinadora:"])
def test_uso_solo_lo_declara_persona_o_coordinadora(por):
    pid = "real-uso-actor"
    k.registrar_proyecto(pid)
    belief, _, _ = _creencia(pid, {})
    code, _ = api.dispatch("POST", [pid, "creencias", belief["id"], "uso"], {"por": por, "resultado": "sirvio"}, {})
    assert code == 403
    assert k.nodo(pid, belief["id"])["datos"].get("usos") is None


def test_dos_no_aplico_marcan_revisar_sin_refutar():
    pid = "real-uso"
    ronda = _ronda(pid)
    ctx = {"tipo_trabajo": "refactor"}
    belief, _, _ = _creencia(pid, ctx)
    e = api.dispatch(
        "POST", [pid, "encargos"], {"ronda": ronda, "letra": "A", "texto": "x", "contexto_desarrollo": ctx}, {}
    )[1]
    assert (
        api.dispatch(
            "POST", [pid, "creencias", belief["id"], "uso"], {"por": "persona:Ariel", "resultado": "inventado"}, {}
        )[0]
        == 400
    )
    assert (
        api.dispatch(
            "POST",
            [pid, "creencias", belief["id"], "uso"],
            {"por": "persona:Ariel", "resultado": "sirvio", "encargo": belief["id"]},
            {},
        )[0]
        == 400
    )
    for _ in range(2):
        code, _ = api.dispatch(
            "POST",
            [pid, "creencias", belief["id"], "uso"],
            {"por": "coordinadora:s1", "resultado": "no_aplico", "encargo": e["id"]},
            {},
        )
        assert code == 200
    item = _estado(pid, ctx, belief)
    assert item["estado"] == "aplicable" and item["revisar"] is True
    assert item["usos"] == {"no_aplico": 2, "sirvio": 0, "ya_sabido": 0}
    assert k.nodo(pid, belief["id"])["datos"]["usos"][0]["encargo"] == e["id"]


def _informe(nodos, vinculos=()):
    bloque = json.dumps({"version": 1, "nodos": nodos, "vinculos": list(vinculos)})
    return f"## Hecho\n\n```conocimiento\n{bloque}\n```\n"


def test_control_ejecutado_del_informe_queda_atado_al_encargo():
    pid = "real-control"
    ronda = _ronda(pid)
    e = k.crear_encargo(
        pid,
        ronda,
        "A",
        "x",
        autor="coordinadora:c",
        contexto_desarrollo={"tipo_trabajo": "bugfix"},
        controles_declarados=["pruebas"],
    )
    control = {
        "id": "c1",
        "tipo": "evidencia",
        "texto": "pytest focal",
        "datos": {
            "clase": "control_desarrollo",
            "control": "pruebas",
            "estado": "ejecutada",
            "resultado": "12 pasan",
            "referencia": "pytest tests/test_x.py",
        },
    }
    inf = k.entregar(pid, e["id"], _informe([control]), revision=1, autor="frente:f")
    assert inf["datos"]["conocimiento"]["estado"] == "incorporado"
    controles = pe.controles(pid, e["id"])
    assert controles["declarados"] == ["pruebas"]
    assert [x["datos"]["resultado"] for x in controles["ejecutados"]] == ["12 pasan"]
    assert controles["verificados"] == []


def _control(lid, control="pruebas", resultado="pasa"):
    return {
        "id": lid,
        "tipo": "evidencia",
        "texto": control,
        "datos": {
            "clase": "control_desarrollo",
            "control": control,
            "estado": "ejecutada",
            "resultado": resultado,
            "referencia": "log",
        },
    }


def test_control_de_un_informe_capturado_se_ata_al_adoptarlo():
    pid = "real-adopcion"
    ronda = _ronda(pid)
    e = k.crear_encargo(pid, ronda, "A", "x", autor="coordinadora:c", contexto_desarrollo={"tipo_trabajo": "bugfix"})
    cuerpo = _informe([_control("c1")])
    capturado = k.informe_capturado(pid, "sin-encargo", cuerpo, ronda=ronda, origen={})
    assert capturado["datos"]["conocimiento"]["estado"] == "incorporado"
    assert pe.controles(pid, e["id"])["ejecutados"] == []
    adoptado = k.entregar(pid, e["id"], cuerpo, revision=1, autor="coordinadora:c")
    assert adoptado["id"] == capturado["id"]
    assert [x["datos"]["resultado"] for x in pe.controles(pid, e["id"])["ejecutados"]] == ["pasa"]


def test_un_control_redeclarado_en_otra_revision_no_se_suma():
    pid = "real-revisiones"
    ronda = _ronda(pid)
    e = k.crear_encargo(pid, ronda, "A", "x", autor="coordinadora:c", contexto_desarrollo={"tipo_trabajo": "bugfix"})
    k.entregar(
        pid,
        e["id"],
        _informe([_control("c1", resultado="falla"), _control("r1", "claude_review_local")]),
        revision=1,
        autor="frente:f",
    )
    k.entregar(pid, e["id"], _informe([_control("c1", resultado="pasa")]), revision=2, autor="frente:f")
    ejecutados = pe.controles(pid, e["id"])["ejecutados"]
    assert sorted((x["datos"]["control"], x["datos"]["resultado"]) for x in ejecutados) == [
        ("claude_review_local", "pasa"),
        ("pruebas", "pasa"),
    ]


def test_el_frente_no_ata_controles_a_un_encargo_a_mano():
    pid = "real-apoya-encargo"
    ronda = _ronda(pid)
    e = k.crear_encargo(pid, ronda, "A", "x", autor="coordinadora:c", contexto_desarrollo={"tipo_trabajo": "bugfix"})
    otro = k.crear_encargo(pid, ronda, "B", "y", autor="coordinadora:c", contexto_desarrollo={"tipo_trabajo": "bugfix"})
    cuerpo = _informe([_control("c1")], [{"de": "nodo:" + otro["id"], "relacion": "apoya", "a": "c1"}])
    inf = k.entregar(pid, e["id"], cuerpo, revision=1, autor="frente:f")
    assert inf["datos"]["conocimiento"]["estado"] == "pendiente_de_vincular"
    assert pe.controles(pid, otro["id"])["ejecutados"] == []


def test_el_frente_no_puede_declarar_un_control_verificado():
    pid = "real-control-verificado"
    ronda = _ronda(pid)
    e = k.crear_encargo(pid, ronda, "A", "x", autor="coordinadora:c", contexto_desarrollo={"tipo_trabajo": "bugfix"})
    control = {
        "id": "c1",
        "tipo": "evidencia",
        "texto": "review",
        "datos": {
            "clase": "control_desarrollo",
            "control": "claude_review_local",
            "estado": "verificada",
            "resultado": "ok",
            "referencia": "r",
            "verificada_por": "persona:Ariel",
            "verificacion": "v",
        },
    }
    inf = k.entregar(pid, e["id"], _informe([control]), revision=1, autor="frente:f")
    assert inf["datos"]["conocimiento"]["estado"] == "pendiente_de_vincular"
    assert pe.controles(pid, e["id"])["verificados"] == []


def test_coordinar_exige_tipo_y_pega_los_aprendizajes(monkeypatch):
    calls = []
    monkeypatch.setattr(coordinar, "_conocimiento", lambda *a: calls.append(a) or {"estado": "pendiente"})
    with pytest.raises(ValueError):
        coordinar.encargo("p", "r", "A", "x")
    assert calls == []
    coordinar.encargo("p", "r", "A", "x", tipo_trabajo="sin_clasificar", contexto_desarrollo={"tecnologia": "py"})
    assert calls[0][2]["contexto_desarrollo"] == {"tecnologia": "py", "tipo_trabajo": "sin_clasificar"}
    monkeypatch.setattr(coordinar, "briefing", lambda *a, **kw: {"markdown": "BRIEF"})
    texto = coordinar.preparar_encargo("p", "PEDIDO", encargo={"aprendizajes_texto": "APRENDIDO"})
    assert texto.index("PEDIDO") < texto.index("APRENDIDO") < texto.index("BRIEF")
    assert "control_desarrollo" in texto
