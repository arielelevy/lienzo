"""Integración del contraste con servicio simulado: nunca arranca WSL."""

import prolog_contraste as pc
import prolog_learning as learning
import prolog_servicio as servicio
import pytest


def test_contraste_usa_transporte_persistente(monkeypatch, tmp_path):
    engine = tmp_path / "main.pl"
    engine.write_text("% motor simulado", encoding="utf-8")
    monkeypatch.setattr(learning, "ENGINE", engine)
    monkeypatch.setattr(learning, "despertar", lambda: None)
    calls = []

    def fake(payload, **kwargs):
        calls.append((payload, kwargs))
        return {"contract": 3}

    monkeypatch.setattr(servicio, "consultar", fake)

    # El rojo anterior no debe iniciar WSL durante la pausa.
    import subprocess

    def no_proceso(*args, **kwargs):
        raise AssertionError("el contraste aún usa subprocess.run por consulta")

    monkeypatch.setattr(subprocess, "run", no_proceso)
    assert pc.run({"contract": 3}) == {"contract": 3}
    assert len(calls) == 1


def test_sin_despertar_no_inicia_servicio_dormido(monkeypatch, tmp_path):
    engine = tmp_path / "main.pl"
    engine.write_text("% motor simulado", encoding="utf-8")
    monkeypatch.setattr(learning, "ENGINE", engine)
    monkeypatch.setattr(learning, "dormido", lambda: True)
    with pytest.raises(learning.MotorError, match="dormido"):
        pc.run({"contract": 3}, despertar=False)
