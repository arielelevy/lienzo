import datetime as dt

import conocimiento as k
import conocimiento_api as api
import creencias as c
import patrones_desarrollo as p
import pytest


def test_normal_task_api_feeds_patterns_without_promoting_beliefs():
    pid = "learning-entry"
    k.registrar_proyecto(pid)
    round_id = k.abrir_ronda(pid, "Revisar cambios", autor="coordinadora:c")["id"]
    for letter in ("A", "B"):
        code, task = api.dispatch(
            "POST",
            [pid, "encargos"],
            {
                "ronda": round_id,
                "letra": letter,
                "texto": "Simplificar código",
                "contexto_desarrollo": {"tipo_trabajo": "refactor", "tecnologia": "python"},
                "controles_declarados": ["pruebas", "pruebas", "auditoria_skill"],
            },
            {},
        )
        assert code == 200 and task["estado"] == "pendiente"
        assert task["datos"]["controles_declarados"] == ["pruebas", "auditoria_skill"]
    analysis = api.dispatch("GET", [pid, "patrones-desarrollo"], None, {})[1]
    assert analysis["sin_clasificar"] == 0
    assert len(analysis["patrones"]) == 1
    pattern = analysis["patrones"][0]
    assert pattern["encargos"] == 2 and pattern["contexto"]["tipo_trabajo"] == "refactor"
    assert pattern["controles_declarados"] == {"pruebas": 2, "auditoria_skill": 2}
    assert c.listar(pid) == []
    assert c.checklist(pid, {"tipo_trabajo": "refactor"})["items"] == []


@pytest.mark.parametrize(
    "fields",
    [
        {"contexto_desarrollo": {}},
        {"contexto_desarrollo": {"tipo_trabajo": "inventado"}},
        {"contexto_desarrollo": {"tipo_trabajo": "bugfix", "desconocido": "x"}},
        {"contexto_desarrollo": []},
        {"controles_declarados": "pruebas"},
        {"controles_declarados": ["aprobado"]},
        {"controles_declarados": [{}]},
    ],
)
def test_invalid_task_labels_leave_no_task_or_file(fields):
    from pathlib import Path

    pid = "learning-invalid"
    k.registrar_proyecto(pid)
    round_id = k.abrir_ronda(pid, "Revisar cambios", autor="coordinadora:c")["id"]
    before = k.cambios(pid)
    code, _ = api.dispatch(
        "POST",
        [pid, "encargos"],
        {
            "ronda": round_id,
            "letra": "A",
            "texto": "Cambio",
            **fields,
        },
        {},
    )
    assert code == 400
    assert k.cambios(pid) == before
    assert k.nodos(pid, tipo="encargo")["total"] == 0
    assert not (Path(k._carpeta(pid)) / "rondas" / round_id / "encargo-A.md").exists()


@pytest.fixture
def setup():
    k.registrar_proyecto("belief-test")
    source = k.crear_nodo("belief-test", "hallazgo", "espera observada", {}, autor="server")
    evidence = k.crear_nodo("belief-test", "evidencia", "comparación revisada", {}, autor="persona:Ariel")
    data = {
        "texto": "Los bugfix pequeños necesitan diagnóstico focal",
        "accion": "Revisar el diagnóstico y su prueba",
        "dimension": "pruebas",
        "contexto": {"tipo_trabajo": "bugfix", "agente": "codex"},
        "fuentes": [source["id"]],
        "excepciones": "Cambios transversales requieren revisar arquitectura",
    }
    belief = c.proponer("belief-test", data, autor="server")
    verdict = {
        "por": "persona:Ariel",
        "motivo": "comparación y revisiones verificadas",
        "resultado": "validada",
        "evidencia": evidence["id"],
        "vigente_hasta": (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat(),
    }
    return "belief-test", data, belief, verdict


def test_proposal_is_persistent_deduplicated_and_not_a_rule(setup):
    pid, data, belief, _ = setup
    assert c.proponer(pid, data, autor="server")["id"] == belief["id"]
    assert c.listar(pid)[0]["estado"] == "propuesta"
    assert c.checklist(pid, data["contexto"])["items"] == []


def test_validated_contextual_checklist_and_refutation(setup):
    pid, data, belief, verdict = setup
    c.resolver(pid, belief["id"], verdict)
    c.resolver(pid, belief["id"], verdict)
    assert c.checklist(pid, {})["items"] == []
    assert c.checklist(pid, {"tipo_trabajo": "feature", "agente": "codex"})["items"] == []
    (item,) = c.checklist(pid, data["contexto"])["items"]
    assert item["accion"] == data["accion"] and item["evidencia"] == verdict["evidencia"]
    assert k.nodos(pid, tipo="regla")["total"] == 0  # el checklist es una vista, no una regla duplicada
    c.resolver(pid, belief["id"], {**verdict, "resultado": "refutada"})
    assert c.checklist(pid, data["contexto"])["items"] == []
    assert c.listar(pid)[0]["estado"] == "revertida"
    with pytest.raises(k.Rechazo):
        c.resolver(pid, belief["id"], verdict)


def test_refutation_keeps_state_history(setup):
    pid, _, belief, verdict = setup
    c.resolver(pid, belief["id"], verdict)
    c.resolver(pid, belief["id"], {**verdict, "resultado": "refutada", "motivo": "la comparación no se repitió"})
    estados = [x for x in k.nodo(pid, belief["id"])["cambios"] if x["accion"] == "estado"]
    assert [(x["anterior"]["estado"], x["nuevo"]["estado"]) for x in estados] == [
        ("propuesta", "vigente"),
        ("vigente", "revertida"),
    ]
    assert estados[-1]["autor"] == "persona:Ariel" and estados[-1]["motivo"] == "la comparación no se repitió"


def test_belief_reverted_outside_the_verdict_leaves_checklist(setup):
    pid, data, belief, verdict = setup
    c.resolver(pid, belief["id"], verdict)
    k.cambiar_estado(pid, belief["id"], "revertida", por="persona:Ariel", motivo="se retira")
    assert c.checklist(pid, data["contexto"])["items"] == []


def test_verdict_requires_an_evidence_node(setup):
    pid, data, belief, verdict = setup
    with pytest.raises(k.Rechazo):
        c.resolver(pid, belief["id"], {**verdict, "evidencia": data["fuentes"][0]})
    assert c.listar(pid)[0]["estado"] == "propuesta"


@pytest.mark.parametrize("actor", ["server", "coordinadora:a", "frente:b", "persona:"])
def test_nonhuman_verdict_cannot_promote(setup, actor):
    pid, _, belief, verdict = setup
    with pytest.raises(k.Rechazo) as error:
        c.resolver(pid, belief["id"], {**verdict, "por": actor})
    assert error.value.codigo == 403
    assert c.listar(pid)[0]["estado"] == "propuesta"


def test_invalid_expiry_rolls_back_evidence_and_data(setup):
    pid, _, belief, verdict = setup
    with pytest.raises(k.Rechazo):
        c.resolver(pid, belief["id"], {**verdict, "vigente_hasta": "2020-01-01"})
    node = k.nodo(pid, belief["id"])
    assert node["estado"] == "propuesta" and "resultado" not in node["datos"]
    # sólo queda la fuente que motivó la propuesta; el veredicto fallido no dejó apoyo
    assert [v["relacion"] for v in node["vinculos"]["salen"]] == ["motivada_por"]


def test_expired_or_removed_support_never_enters_checklist(setup):
    pid, data, belief, verdict = setup
    c.resolver(pid, belief["id"], verdict)
    with k._abrir(pid) as con:
        con.execute("UPDATE vinculo SET activo=0 WHERE de=? AND relacion='apoya'", (belief["id"],))
    assert c.checklist(pid, data["contexto"])["items"] == []
    c.resolver(pid, belief["id"], verdict)
    k.actualizar_datos(pid, belief["id"], {"vigente_hasta": "2000-01-01T00:00:00Z"}, por="persona:Ariel")
    assert c.checklist(pid, data["contexto"])["items"] == []


def test_only_the_verdict_evidence_supports_the_checklist(setup):
    pid, data, belief, verdict = setup
    c.resolver(pid, belief["id"], verdict)
    other = k.crear_nodo(pid, "evidencia", "otra lectura", {}, autor="server")
    k.vincular(pid, belief["id"], "apoya", other["id"], autor="server")
    with k._abrir(pid) as con:
        con.execute("UPDATE vinculo SET activo=0 WHERE de=? AND a=?", (belief["id"], verdict["evidencia"]))
    assert c.checklist(pid, data["contexto"])["items"] == []


def test_cross_project_sources_and_evidence_rejected(setup):
    pid, data, belief, verdict = setup
    k.registrar_proyecto("other-belief")
    other = k.crear_nodo("other-belief", "evidencia", "other", {}, autor="server")
    with pytest.raises(k.Rechazo):
        c.proponer(pid, {**data, "fuentes": [other["id"]]}, autor="server")
    with pytest.raises(k.Rechazo):
        c.resolver(pid, belief["id"], {**verdict, "evidencia": other["id"]})


@pytest.mark.parametrize("field,value", [("dimension", []), ("fuentes", []), ("contexto", {"inventado": "x"})])
def test_bad_proposal_returns_http_400(setup, field, value):
    pid, data, _, _ = setup
    code, body = api.dispatch("POST", [pid, "creencias"], {**data, field: value}, {})
    assert code == 400 and "error" in body


def test_http_lifecycle_and_query_validation(setup):
    pid, data, belief, verdict = setup
    assert api.dispatch("GET", [pid, "creencias"], None, {})[0] == 200
    assert api.dispatch("POST", [pid, "creencias", belief["id"], "veredicto"], verdict, {})[0] == 200
    code, body = api.dispatch("GET", [pid, "checklist"], None, {k: [v] for k, v in data["contexto"].items()})
    assert code == 200 and body["total"] == 1
    assert api.dispatch("GET", [pid, "checklist"], None, {"limite": "0"})[0] == 400


def test_patterns_are_separate_unknown_stays_unknown_and_reviews_are_only_declared(setup):
    pid, _, _, _ = setup
    for kind in ["bugfix", "bugfix", "feature", None]:
        data = (
            {
                "contexto_desarrollo": {"tipo_trabajo": kind},
                "controles_declarados": ["claude_review_local", "auditoria_skill", "pruebas"],
            }
            if kind
            else {}
        )
        k.crear_nodo(pid, "encargo", "trabajo", data, autor="server")
    analysis = p.analizar(pid)
    assert analysis["revisados"] == 4 and analysis["sin_clasificar"] == 1
    bugfix, feature = analysis["patrones"]
    assert bugfix["encargos"] == 2 and feature["encargos"] == 1
    assert bugfix["controles_declarados"]["claude_review_local"] == 2
    before = len(c.listar(pid))
    ids = p.registrar(pid, analysis)
    assert p.registrar(pid, analysis) == ids
    assert len(c.listar(pid)) == before + 1
    assert c.checklist(pid, {"tipo_trabajo": "bugfix"})["items"] == []
    assert api.dispatch("GET", [pid, "patrones-desarrollo"], None, {})[1] == analysis
