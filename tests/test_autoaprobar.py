"""lienzo/autoaprobar.py: con el check prendido aprueba todo lo que piden los agentes de esta PC
(hook de Claude/Codex/Pi y cartel de coda), menos las preguntas con opciones; apagado no toca nada."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import autoaprobar as au
import sessions as ses
import state as st


def _armar(monkeypatch, prendido):
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": prendido})
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(au, "_intentados", {})
    monkeypatch.setattr(
        st,
        "pending",
        {
            "r1": {"request_id": "r1", "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "rm -rf x"}},
            "q1": {
                "request_id": "q1",
                "session_id": "s2",
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "¿A o B?"}]},
            },
        },
    )
    monkeypatch.setattr(
        st,
        "sessions",
        {
            "s1": {"session_id": "s1", "agent": "claude"},
            "c1": {
                "session_id": "c1",
                "agent": "coda",
                "state": "te_necesita",
                "last_cmd": "git push",
                "needs": {"kind": "permission", "tool": "bash", "where": "terminal", "coda_at": "t1"},
            },
        },
    )
    hechos = []
    monkeypatch.setattr(
        ses, "answer_pending", lambda rid, dec, reason="": (hechos.append(("hook", rid, dec)), (200, {}))[1]
    )
    monkeypatch.setattr(
        ses, "answer_coda_ask", lambda s, dec: (hechos.append(("coda", s["session_id"], dec)), (200, {}))[1]
    )
    return hechos


def test_apagado_no_aprueba_nada(monkeypatch):
    hechos = _armar(monkeypatch, False)
    assert au.ronda(ahora=100) == [] and hechos == []


def test_prendido_aprueba_hook_y_coda_y_salta_las_preguntas(monkeypatch):
    hechos = _armar(monkeypatch, True)
    au.ronda(ahora=100)
    assert sorted(hechos) == [("coda", "c1", "allow"), ("hook", "r1", "allow")]


def test_no_repite_el_mismo_pedido_hasta_el_reintento(monkeypatch):
    hechos = _armar(monkeypatch, True)
    au.ronda(ahora=100)
    au.ronda(ahora=105)
    assert len(hechos) == 2
    au.ronda(ahora=100 + au.REINTENTO_S + 1)
    # pasado el reintento, solo el cartel de coda se vuelve a contestar (un Enter puede no hacer
    # efecto); el pendiente de hook ya contestado no se repite
    assert len(hechos) == 3 and hechos[-1][0] == "coda"


def test_un_proveedor_roto_no_frena_a_los_demas(monkeypatch):
    hechos = _armar(monkeypatch, True)

    class Roto(au.ProveedorPermisos):
        nombre = "roto"

        def abiertos(self):
            raise RuntimeError("se rompio")

        def aprobar(self, p):
            return 500, {}

    monkeypatch.setattr(au, "PROVEEDORES", [Roto(), *au.PROVEEDORES])
    au.ronda(ahora=100)
    assert len(hechos) == 2
