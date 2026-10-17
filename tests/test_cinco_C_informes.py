"""Contratos del libro de informes; sin transporte ni sesiones reales."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import entregas_informes as ledger
import pytest
import rules as rl
import state

pytest_plugins = ["test_backlog_b_informes"]


@pytest.mark.parametrize("estado", ["encolado", "enviando", "fallido", "entregado"])
def test_entrega_confirmada_no_retrocede_tras_recargar(estado):
    rule = {"to": "coordinadora", "informes": []}
    informe = ledger.conservar(rule, {"huella": "final", "texto": "ESTADO: listo"}, "t0")
    ledger.resultado(informe, 200, {"estado": "entregado", "envio_id": "q1"}, "t1")
    rule = json.loads(json.dumps(rule))
    informe = rule["informes"][0]
    ledger.resultado(informe, 200, {"estado": estado, "envio_id": "q1"}, "t2")
    assert informe["estado"] == "entregado"
    assert informe["entregado_at"] == "t1"
    assert ledger.acusar(rule, "final", "integrado", "coordinadora", "t3")[0] == 409
    assert ledger.acusar(rule, "final", "recibido", "coordinadora", "t3")[0] == 200
    assert ledger.acusar(rule, "final", "integrado", "coordinadora", "t4")[0] == 200
    assert informe["estado"] == "integrado"


def test_dos_frentes_simultaneos_persisten_sin_reenvio(entorno):
    rule, sends = entorno
    otra = {**rule, "id": "cinco-C-segunda", "from": "cinco-C-src"}
    state.rules.items.append(otra)
    state.sessions[otra["from"]] = {
        "session_id": otra["from"], "agent": "codex", "state": "termino",
        "last_reply": "ESTADO: segundo frente", "prompt_id": "otro",
    }
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(rl.fire_on_stop, [rule["from"], otra["from"]]))
        assert len(sends) == 2
        disk = json.loads(Path(state.rules.path).read_text(encoding="utf-8"))
        assert {r["id"] for r in disk} == {rule["id"], otra["id"]}
        assert all(len(r["informes"]) == 1 for r in disk)
        assert all(r["informes"][0]["estado"] == "entregado" for r in disk)
        state.rules.items[:] = disk
        assert rl.recuperar_informes() == []
        for sid in (rule["from"], otra["from"]):
            rl.fire_on_stop(sid)
        assert len(sends) == 2
    finally:
        state.sessions.pop(otra["from"], None)
