import conocimiento as k
import optimization_memory as m
import pytest


@pytest.fixture
def project():
    k.registrar_proyecto("optimization-test", nombre="Optimization")
    return "optimization-test"


def test_real_memory_proposal_is_idempotent_linked_and_not_confirmed(project):
    source = k.crear_nodo(project, "incidente", "error", {"herramienta": "shell", "agente": "codex"}, autor="server")
    assert m.sources(project) == [source["id"]]
    first = m.propose(project, source["id"])
    assert m.propose(project, source["id"]) == first
    node = k.nodo(project, first)
    assert node["tipo"] == "decision" and node["estado"] == "propuesta"
    assert node["datos"]["contexto"]["modelo"] is None
    assert node["datos"]["resultado"] == "experimento no ejecutado"
    assert node["datos"]["presupuesto_usd"] is None
    assert node["vinculos"]["salen"][0]["a"] == source["id"]


def test_cross_project_source_rejected(project):
    k.registrar_proyecto("other-optimization")
    source = k.crear_nodo("other-optimization", "incidente", "x", {"herramienta": "shell"}, autor="server")
    with pytest.raises(ValueError):
        m.propose(project, source["id"])


def test_unknown_tool_does_not_invent_hypothesis(project):
    source = k.crear_nodo(project, "incidente", "x", {"herramienta": "unknown"}, autor="server")
    assert m.propose(project, source["id"]) is None


def test_analysis_evidence_is_in_same_memory_and_never_quality_pass(project):
    evidence = m.record_analysis(project, "job", 0, [])
    assert m.record_analysis(project, "job", 0, []) == evidence
    node = k.nodo(project, evidence)
    assert node["tipo"] == "evidencia"
    assert node["datos"]["experimentos_ejecutados"] == 0
    assert node["datos"]["calidad"] == "no evaluada"


def test_context_uses_cited_session_without_copying_prompt(project):
    k.crear_nodo(
        project,
        "sesion",
        "source",
        {"pc": "source-pc", "modelo": "model", "prompt": "PRIVATE"},
        autor="server",
        clave_ingesta="sesion:sid",
    )
    source = k.crear_nodo(
        project, "incidente", "source", {"herramienta": "bash"}, autor="server", origen={"session_id": "sid"}
    )
    node = k.nodo(project, m.propose(project, source["id"]))
    assert node["datos"]["contexto"]["pc"] == "source-pc"
    assert "PRIVATE" not in str(node)


def test_source_version_ignores_generated_hypotheses_and_changes_for_new_incident(project):
    source = k.crear_nodo(project, "incidente", "x", {"herramienta": "shell"}, autor="server")
    before = m.source_snapshot(project)
    m.propose(project, source["id"])
    assert m.source_snapshot(project) == before
    k.crear_nodo(project, "incidente", "y", {"herramienta": "shell"}, autor="server")
    assert m.source_snapshot(project)["version"] != before["version"]
