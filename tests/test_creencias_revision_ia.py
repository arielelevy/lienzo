import json

import conocimiento as k
import creencias
import pytest


def seed(pid="ab"):
    k.registrar_proyecto(pid)
    source = k.crear_nodo(
        pid,
        "hallazgo",
        "tests/test_x.py: fallo reproducido",
        {
            "contexto": {
                "tecnologia": "python",
                "area": "pruebas",
                "fase": "verificacion",
                "tipo_trabajo": "bugfix",
                "agente": "codex",
                "modelo": "gpt-6.1-sol",
            },
            "archivos": ["tests/test_x.py"],
        },
        autor="server",
    )
    return creencias.proponer(
        pid,
        {"texto": "Verificar antes", "accion": "Correr pruebas", "dimension": "pruebas", "fuentes": [source["id"]]},
        autor="server",
    )


def reply(nodes, action="aceptar"):
    return {
        "items": [
            {
                "proyecto": n["proyecto"],
                "id": n["id"],
                "accion": action,
                "motivo": "La evidencia respalda la regla general",
            }
            for n in nodes
        ]
    }


def test_apply_and_undo_survives_reload():
    import creencias_revision_ia as r

    node = seed()
    result = r.revisar("ab", "claude", decidir=lambda nodes, agent: reply(nodes))
    saved = creencias.listar("ab")[0]
    assert saved["estado"] == "vigente"
    assert saved["datos"]["ia_delegada"] is True
    assert saved["datos"]["confianza"] == "veredicto IA delegada"
    assert saved["datos"]["veredicto_por"] == "persona:Ariel (delegado a IA: claude)"
    assert saved["datos"]["metadatos"]["tipo_archivo"] == [".py"]
    assert r.listar("ab")[0]["id"] == result["id"]
    r.deshacer("ab", result["id"], node["id"])
    restored = creencias.listar("ab")[0]
    assert restored["estado"] == "propuesta"
    assert restored["datos"] == node["datos"]
    with k._abrir("ab") as con:
        assert not con.execute(
            "SELECT 1 FROM vinculo WHERE de=? AND relacion='apoya' AND activo=1", (node["id"],)
        ).fetchone()


def test_failure_is_atomic_and_unknown_ids_rejected():
    import creencias_revision_ia as r

    seed()
    before = k.cambios("ab")
    with pytest.raises(k.Rechazo):
        r.revisar("ab", "claude", decidir=lambda nodes, agent: {"items": [{"id": "inventada"}]})
    assert k.cambios("ab") == before


def test_undo_refuses_later_edits():
    import creencias_revision_ia as r

    node = seed()
    batch = r.revisar("ab", "codex", decidir=lambda nodes, agent: reply(nodes))
    k.actualizar_datos("ab", node["id"], {"nota": "cambio posterior"}, por="persona:Ariel")
    with pytest.raises(k.Rechazo, match="posteriores"):
        r.deshacer("ab", batch["id"])
    assert creencias.listar("ab")[0]["datos"]["nota"] == "cambio posterior"


def test_scope_includes_only_process_from_lienzo():
    import creencias_revision_ia as r

    seed()
    ordinary = seed("lienzo")
    source = ordinary["datos"]["fuentes"][0]
    process = creencias.proponer(
        "lienzo",
        {
            "texto": "Coordinar",
            "accion": "Pedir turno",
            "dimension": "coordinacion",
            "fuentes": [source],
            "alcance": "proceso_lienzo",
        },
        autor="server",
    )
    captured = []

    def decide(nodes, agent):
        captured.extend(nodes)
        return reply(nodes, "rechazar")

    batch = r.revisar("ab", "claude", decidir=decide)
    assert {n["id"] for n in captured} == {creencias.listar("ab")[0]["id"], process["id"]}
    r.deshacer("ab", batch["id"])
    assert all(n["estado"] == "propuesta" for n in creencias.listar("lienzo"))


def test_parser_rejects_non_json():
    import creencias_revision_ia as r

    with pytest.raises(k.Rechazo):
        r.parsear("no responde")
    assert r.parsear(json.dumps({"items": []})) == {"items": []}


def test_correction_and_undo_whole_batch():
    import creencias_revision_ia as r

    old = seed()
    k.actualizar_datos("ab", old["id"], {"regla_logica": {"version": 1, "clausula": "regla anterior"}}, por="server")

    def decide(nodes, agent):
        result = reply(nodes, "corregir")
        result["items"][0].update(texto_nuevo="Principio general", accion_nueva="Verificar el caso antes de cambiar")
        return result

    batch = r.revisar("ab", "claude", decidir=decide)
    nodes = creencias.listar("ab")
    assert sorted(n["estado"] for n in nodes) == ["revertida", "vigente"]
    successor = next(n for n in nodes if n["estado"] == "vigente")
    assert successor["datos"]["ia_delegada"] is True
    assert "regla_logica" not in successor["datos"]
    r.deshacer("ab", batch["id"])
    assert {n["id"]: n["estado"] for n in creencias.listar("ab")}[successor["id"]] == "revertida"
    assert r.deshacer("ab", batch["id"])["items"][0]["deshecho"] is True


def test_merge_in_same_batch_undo_dependency_then_all():
    import creencias_revision_ia as r

    canonical = seed()
    source = canonical["datos"]["fuentes"][0]
    duplicate = creencias.proponer(
        "ab",
        {
            "texto": "Otra observación del mismo principio",
            "accion": "Correr pruebas",
            "dimension": "pruebas",
            "fuentes": [source],
        },
        autor="server",
    )

    def decide(nodes, agent):
        result = reply(nodes)
        for item in result["items"]:
            if item["id"] == duplicate["id"]:
                item.update(accion="fusionar", destino=canonical["id"])
        return result

    batch = r.revisar("ab", "claude", decidir=decide)
    with pytest.raises(k.Rechazo, match="posteriores"):
        r.deshacer("ab", batch["id"], canonical["id"])
    r.deshacer("ab", batch["id"], duplicate["id"])
    r.deshacer("ab", batch["id"])
    assert all(n["estado"] == "propuesta" for n in creencias.listar("ab"))


def test_changes_during_ai_call_refuse_entire_batch():
    import creencias_revision_ia as r

    node = seed()

    def decide(nodes, agent):
        creencias.revisar("ab", node["id"], {"por": "persona:Ariel", "accion": "rechazar"})
        return reply(nodes)

    with pytest.raises(k.Rechazo, match="cambios durante"):
        r.revisar("ab", "claude", decidir=decide)
    assert creencias.listar("ab")[0]["estado"] == "revertida"
    assert r.listar("ab") == []


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_readonly_cli_and_timeout(monkeypatch, agent):
    import creencias_revision_ia as r

    monkeypatch.setattr(r.shutil, "which", lambda value: value)
    captured = {}

    def runner(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return {"code": 1, "timed_out": True}

    with pytest.raises(k.Rechazo, match="90 s"):
        r.consultar([], {}, agent, runner=runner)
    if agent == "claude":
        assert "--restricted" in captured["argv"] and "--safe-mode" in captured["argv"]
        assert captured["argv"][captured["argv"].index("--tools") + 1] == ""
    else:
        assert captured["argv"][captured["argv"].index("--sandbox") + 1] == "read-only"
    assert captured["timeout"] == 90


def test_metadata_is_automatic_without_user_input():
    node = seed()
    metadata = node["datos"]["metadatos"]
    for field in (
        "proyecto",
        "tecnologia",
        "tipo_archivo",
        "rutas",
        "area",
        "fase",
        "tipo_trabajo",
        "agente",
        "modelo",
        "fuentes",
    ):
        assert metadata[field]
    assert metadata["agente"] == ["codex"]


def test_api_routes(monkeypatch):
    import conocimiento_api as api
    import creencias_revision_ia as r

    seed()
    monkeypatch.setattr(r, "consultar", lambda nodes, sources, agent, **kwargs: reply(nodes))
    code, batch = api.dispatch("POST", ["ab", "revision-ia"], {"agente": "claude"}, {})
    assert code == 200
    assert api.dispatch("GET", ["ab", "revision-ia"], None, {})[1][0]["id"] == batch["id"]
    assert api.dispatch("POST", ["ab", "revision-ia", batch["id"], "deshacer"], {}, {})[0] == 200


@pytest.mark.skip(
    reason="AB.3: primera contradicción de ia_delegada y espera de veredicto se implementan y prueban en AA"
)
def test_aa_first_contradiction_questions_delegated_belief():
    """Contrato pendiente de AA: usa datos.ia_delegada y evidencia clase ia_delegada de AB."""


def test_batch_limit_and_remaining(monkeypatch):
    import creencias_revision_ia as r

    canonical = seed()
    for number in range(2):
        creencias.proponer(
            "ab",
            {
                "texto": f"Regla {number}",
                "accion": f"Acción {number}",
                "dimension": "pruebas",
                "fuentes": canonical["datos"]["fuentes"],
            },
            autor="server",
        )
    monkeypatch.setattr(r, "TOPE", 2)
    batch = r.revisar("ab", "claude", decidir=lambda nodes, agent: reply(nodes))
    assert len(batch["items"]) == 2 and batch["hay_mas"]
    assert sum(n["estado"] == "propuesta" for n in creencias.listar("ab")) == 1


def test_metadata_unknown_is_empty_not_wildcard():
    import metadatos_creencias as m

    metadata = m.completar("ab", {}, [])
    assert metadata["proyecto"] == "ab"
    assert all(metadata[key] == [] for key in m.CAMPOS)


def test_human_verdict_supersedes_delegation():
    import creencias_revision_ia as r

    node = seed()
    r.revisar("ab", "claude", decidir=lambda nodes, agent: reply(nodes))
    creencias.revisar("ab", node["id"], {"por": "persona:Ariel", "accion": "aceptar"})
    current = creencias.listar("ab")[0]
    assert current["datos"]["ia_delegada"] is False
    assert current["datos"]["confianza"] == "veredicto humano"


def test_invalid_second_item_rolls_back_first():
    import creencias_revision_ia as r

    first = seed()
    creencias.proponer(
        "ab",
        {"texto": "Otra regla", "accion": "Otra acción", "dimension": "pruebas", "fuentes": first["datos"]["fuentes"]},
        autor="server",
    )
    before = k.cambios("ab")

    def decide(nodes, agent):
        result = reply(nodes)
        result["items"][-1].update(accion="fusionar", destino="inventado")
        return result

    with pytest.raises(k.Rechazo):
        r.revisar("ab", "claude", decidir=decide)
    assert k.cambios("ab") == before
