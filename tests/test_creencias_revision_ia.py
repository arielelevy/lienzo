import hashlib
import json
import subprocess
from pathlib import Path

import conocimiento as k
import creencias
import pytest

TOKEN = "sk-proj-" + "V" * 30


@pytest.fixture(autouse=True)
def no_external_processes(monkeypatch):
    """Focal de revisión: sin IA real, navegador ni SWI/WSL; AA se verifica en sus propios casos."""
    try:
        import prolog_programa
    except ModuleNotFoundError:  # sin AA integrado no hay notificación que aislar
        prolog_programa = None
    if prolog_programa is not None:
        monkeypatch.setattr(prolog_programa, "notificar", lambda *a, **kw: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("proceso externo fuera del focal IA"))


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_ai_redacts_prompt_and_response(monkeypatch, agent):
    import creencias_revision_ia as r

    monkeypatch.setattr(r.shutil, "which", lambda value: value)
    nodes = [{"texto": f"Authorization: Bearer {'V' * 30}", "datos": {"api_key": TOKEN}}]
    sources = {"n": [{"texto": "https://usuario:claveprivada@ejemplo.test/a"}]}
    candidates = [{"texto": "password=secreto_sintetico", "datos": {"api_key": "clave_sin_formato"}}]
    original = json.dumps([nodes, sources, candidates])

    def runner(argv, **kwargs):
        prompt = kwargs["stdin_text"]
        for secret in (TOKEN, "V" * 30, "claveprivada", "secreto_sintetico", "clave_sin_formato"):
            assert secret not in prompt
        raw = json.dumps({"items": [{"motivo": TOKEN}]})
        if agent == "codex":
            Path(argv[argv.index("-o") + 1]).write_text(raw, encoding="utf-8")
        return {"code": 0, "stdout": raw}

    result = r.consultar(nodes, sources, agent, runner=runner, candidatos=candidates)
    assert TOKEN not in json.dumps(result)
    assert "[redactado:" in result["items"][0]["motivo"]
    assert json.dumps([nodes, sources, candidates]) == original


def test_ai_redacts_before_persisting_verdict():
    import creencias_revision_ia as r

    node = seed()

    def decide(nodes, agent):
        result = reply(nodes)
        result["items"][0]["motivo"] = f"Confirmado con {TOKEN}"
        return result

    batch = r.revisar("ab", "claude", decidir=decide)
    assert TOKEN not in json.dumps(batch)
    assert TOKEN not in json.dumps(k.cambios("ab"))
    assert TOKEN not in json.dumps(creencias.listar("ab")[0]["datos"])
    assert creencias.listar("ab")[0]["id"] == node["id"]


def attachment_belief(body=b"Medicion: 7 fallas de 10 ejecuciones."):
    node = seed()
    source = k.recibir_evidencia("ab", "medicion.md", body, clase="medicion", autor="server")
    k.actualizar_datos("ab", node["id"], {"fuentes": [source["id"]]}, por="server")
    path = Path(k._carpeta("ab")) / source["datos"]["referencia"]
    return node, source, path


def test_ai_reads_redacted_attachment_and_records_hash(monkeypatch):
    import creencias_revision_ia as r

    body = f"Medicion: 7 fallas de 10 ejecuciones. Authorization: Bearer {TOKEN}".encode()
    node, source, path = attachment_belief(body)

    def consult(nodes, sources, agent, **kwargs):
        attached = sources[node["id"]][0]["adjunto"]
        assert "7 fallas de 10" in attached["contenido"]
        assert TOKEN not in attached["contenido"]
        assert attached["hash"] == hashlib.sha256(body).hexdigest()
        assert attached["truncado"] is False and attached["estado"] == "leido"
        return reply(nodes)

    monkeypatch.setattr(r, "consultar", consult)
    batch = r.revisar("ab", "claude")
    assert batch["lecturas"][0]["nodo"] == source["id"]
    assert batch["lecturas"][0]["hash"] == hashlib.sha256(body).hexdigest()
    assert "contenido" not in batch["lecturas"][0]
    assert r.listar("ab")[0]["lecturas"] == batch["lecturas"]
    assert path.read_bytes() == body


@pytest.mark.parametrize(
    "fault",
    ["ausente", "hash", "ruta", "sin_referencia", "sin_hash", "absoluta", "binario", "truncado", "demasiado_grande"],
)
def test_ai_missing_or_incomplete_attachment_is_not_evaluable(monkeypatch, fault):
    import creencias_revision_ia as r

    node, source, path = attachment_belief()
    if fault == "ausente":
        path.unlink()
    elif fault == "hash":
        path.write_bytes(b"Medicion cambiada sin actualizar el nodo")
    elif fault == "ruta":
        k.actualizar_datos("ab", source["id"], {"referencia": "../../fuera.md"}, por="server")
    elif fault == "sin_referencia":
        k.actualizar_datos("ab", source["id"], {"referencia": ""}, por="server")
    elif fault == "sin_hash":
        k.actualizar_datos("ab", source["id"], {"hash": None}, por="server")
    elif fault == "absoluta":
        k.actualizar_datos("ab", source["id"], {"referencia": str(path.resolve())}, por="server")
    else:
        body = (
            b"\x00binario"
            if fault == "binario"
            else b"x" * (1_000_001 if fault == "demasiado_grande" else r.ADJUNTO_CHARS + 1)
        )
        path.write_bytes(body)
        k.actualizar_datos("ab", source["id"], {"hash": hashlib.sha256(body).hexdigest()}, por="server")
    before = k.cambios("ab")
    monkeypatch.setattr(r, "consultar", lambda *a, **kw: pytest.fail("no llamar IA sin evidencia completa"))
    with pytest.raises(k.Rechazo, match="no evaluable") as error:
        r.revisar("ab", "claude")
    assert error.value.codigo == 422
    with k._abrir("ab") as con:
        audit = k._fila(
            con.execute("SELECT * FROM nodo WHERE json_extract(datos,'$.clase')='revision_ia_no_evaluable'").fetchone()
        )
    assert audit["datos"]["lecturas"][0]["estado"] != "leido"
    assert creencias.listar("ab")[0]["estado"] == "propuesta"
    assert k.cambios("ab")[: len(before)] == before
    assert all(c["nodo_id"] == audit["id"] for c in k.cambios("ab")[len(before) :])
    assert r.listar("ab") == []


@pytest.mark.parametrize("offset,evaluable", [(-1, True), (0, True), (1, False)])
def test_ai_attachment_text_boundary(offset, evaluable):
    import creencias_revision_ia as r

    node, source, path = attachment_belief(b"a" * (r.ADJUNTO_CHARS + offset))
    attached = r._adjunto(source, r.TANDA_BYTES, r.TANDA_CHARS)
    assert (attached["estado"] == "leido") is evaluable
    assert attached["truncado"] is not evaluable
    assert attached["hash"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_unreadable_attachment_skips_only_the_proposals_that_rely_on_it(monkeypatch):
    import creencias_revision_ia as r

    node, source, path = attachment_belief()
    path.unlink()
    hallazgo = k.crear_nodo("ab", "hallazgo", "lanzar con poca memoria trabó Chrome", {}, autor="server")
    other = creencias.proponer(
        "ab",
        {
            "texto": "Medir memoria antes de lanzar",
            "accion": "Mirar /memoria",
            "dimension": "pruebas",
            "fuentes": [hallazgo["id"]],
        },
        autor="server",
    )

    def consult(nodes, sources, agent, **kwargs):
        assert [n["id"] for n in nodes] == [other["id"]]
        return reply(nodes)

    monkeypatch.setattr(r, "consultar", consult)
    batch = r.revisar("ab", "claude")
    assert [i["id"] for i in batch["items"]] == [other["id"]]
    assert [x["id"] for x in batch["no_evaluables"]] == [node["id"]]
    estados = {c["id"]: c["estado"] for c in creencias.listar("ab")}
    assert estados[node["id"]] == "propuesta" and estados[other["id"]] != "propuesta"


def test_ai_not_evaluable_is_visible_as_api_error(monkeypatch):
    import conocimiento_api as api
    import creencias_revision_ia as r

    node, source, path = attachment_belief()
    path.unlink()
    monkeypatch.setattr(r, "consultar", lambda *a, **kw: pytest.fail("no llamar IA"))
    code, result = api.dispatch("POST", ["ab", "revision-ia"], {"agente": "claude"}, {})
    assert code == 422 and "no evaluable" in result["error"]
    assert creencias.listar("ab")[0]["estado"] == "propuesta"


def test_ai_attachment_changed_during_call_refuses_verdict(monkeypatch):
    import creencias_revision_ia as r

    node, source, path = attachment_belief()

    def consult(nodes, sources, agent, **kwargs):
        path.write_bytes(b"Otro resultado sin cambiar metadatos")
        return reply(nodes)

    monkeypatch.setattr(r, "consultar", consult)
    before = k.cambios("ab")
    with pytest.raises(k.Rechazo, match="adjunto"):
        r.revisar("ab", "claude")
    assert k.cambios("ab") == before
    assert creencias.listar("ab")[0]["estado"] == "propuesta"


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
