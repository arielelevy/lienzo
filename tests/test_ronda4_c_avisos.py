"""Un emisor restaurado sigue siendo la misma persona destinataria del aviso."""

import pytest
import rondas


@pytest.mark.parametrize("sender", ["old", "new"])
@pytest.mark.parametrize("destination", ["old", "new"])
def test_emisor_y_sucesora_no_se_mandan_aviso(monkeypatch, sender, destination):
    monkeypatch.setattr(rondas, "_sesion", lambda sid: ("new", {"session_id": "new"}))

    def forbidden(*args, **kwargs):
        pytest.fail("un aviso a la misma sesion no debe guardarse ni enviarse")

    monkeypatch.setattr(rondas, "_guardar", forbidden)
    monkeypatch.setattr(rondas, "_publicar", forbidden)
    code, result = rondas.crear_aviso({"texto": "contrato", "de": sender, "a": [destination]})
    assert code == 400
    assert result == {"error": "quien manda el aviso no puede ser destino"}
