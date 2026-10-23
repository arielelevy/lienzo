"""Cláusula opcional en la misma respuesta del investigador: no perder creencias."""

import copy

import pytest
import research_creencias as rc


def packet():
    return {
        "case_id": "aa",
        "fuentes": {"memoria": [{"ref": "e"}], "evidencia": [], "review": [], "coordinacion": [], "pruebas": []},
        "vueltas_previas": [],
    }


def answer():
    return {
        "case_id": "aa",
        "leido": "evidencia",
        "conclusiones": ["medir"],
        "limitaciones": ["fixture"],
        "creencias": [
            {
                "alcance": "proyecto",
                "dimension": "memoria",
                "texto": "Medir RAM",
                "accion": "Medir antes de lanzar",
                "contexto": [],
                "excepciones": "",
                "fuentes": ["e"],
            }
        ],
    }


@pytest.mark.parametrize(
    "clausula,esperada",
    [
        ("recomendar(C, memoria, medir) :- chrome_en_uso(C).", True),
        ("recomendar(C, memoria, medir) :- shell(C).", False),
        (None, False),
    ],
)
def test_clausula_valida_invalida_ausente_conservan_propuesta(clausula, esperada):
    raw = answer()
    if clausula is not None:
        raw["creencias"][0]["regla_logica"] = clausula
    out = rc.validate(copy.deepcopy(raw), packet(), None)
    assert len(out["creencias"]) == 1
    belief = out["creencias"][0]
    assert bool(belief.get("regla_logica")) == esperada
    if not esperada:
        assert belief["formalizacion"]["estado"] == "datos_insuficientes"
        assert belief["formalizacion"]["motivo"]
