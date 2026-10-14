"""Un envio del lienzo no es 'corriendo' hasta que el agente lo confirma (2026-10-14).

Bug medido: send devolvia ok y la tarjeta pasaba a 'corriendo' mientras el texto seguia en el editor
de la terminal (el Enter se tomo como parte del pegado); hubo que apretar Enter a mano. Ahora, en una
tarjeta con hooks, 'corriendo' lo pone el UserPromptSubmit; sin el, a los ENVIO_SIN_CONFIRMAR_S con
el agente libre, la tarjeta pasa a "te necesita" con el aviso."""

import json
import time
from types import SimpleNamespace

import pytest
import sessions as ses
import state as st


@pytest.fixture
def tarjeta(monkeypatch, tmp_path):
    import os

    os.makedirs(st.SESSIONS, exist_ok=True)
    monkeypatch.setattr(ses.backend, "agent_alive", lambda d: True)
    salida = {"ok": True}
    monkeypatch.setattr(
        ses.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(salida), stderr="")
    )
    s = ses.new_session("e0e0e0e0-0000-4000-8000-00000000e001", "claude", "hook")
    s.update(pid=4242, state="termino", last_event="Stop", alive=True)
    st.sessions[s["session_id"]] = s
    yield s, salida
    st.sessions.pop(s["session_id"], None)


def _hace(s, segundos):
    s["envio_pendiente"]["at"] -= segundos
    viejo = time.time() - segundos
    import datetime as dt

    s["state_since"] = dt.datetime.fromtimestamp(viejo).astimezone().isoformat(timespec="milliseconds")


def test_sin_confirmacion_no_figura_corriendo_y_avisa(tarjeta):
    s, _ = tarjeta
    code, _ = ses.send_to_session(s, "hacé el informe", [])
    assert code == 200 and s["state"] == "termino" and s["envio_pendiente"]
    assert not ses.envio_sin_confirmar(s, time.time())  # todavia dentro del plazo
    _hace(s, ses.ENVIO_SIN_CONFIRMAR_S + 1)
    assert ses.envio_sin_confirmar(s, time.time())
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "sin_enviar"
    assert "hacé el informe" in s["needs"]["detail"] and s["envio_pendiente"] is None


def test_el_user_prompt_submit_confirma(tarjeta):
    s, _ = tarjeta
    ses.send_to_session(s, "hola", [])
    ses.hook_prompt_submit(s, {"prompt": "hola"})
    assert s["state"] == "corriendo" and s["envio_pendiente"] is None and s["prompt_via"] == "lienzo"
    _hace_desde = time.time() + ses.ENVIO_SIN_CONFIRMAR_S + 5
    assert not ses.envio_sin_confirmar(s, _hace_desde)


def test_hook_antes_de_que_vuelva_send(tarjeta, monkeypatch):
    s, _ = tarjeta
    real = ses.run_send

    def con_hook_en_el_medio(s2, final, **kw):
        out = real(s2, final, **kw)
        ses.hook_prompt_submit(s2, {"prompt": final})  # el UserPromptSubmit llega antes que la respuesta
        return out

    monkeypatch.setattr(ses, "run_send", con_hook_en_el_medio)
    ses.send_to_session(s, "rapido", [])
    assert s["state"] == "corriendo" and s["envio_pendiente"] is None


def test_con_el_agente_trabajando_espera_a_que_termine(tarjeta):
    s, _ = tarjeta
    s["state"] = "corriendo"  # turno anterior en curso: el mensaje queda en cola
    ses.send_to_session(s, "en cola", [])
    s["envio_pendiente"]["at"] -= 300
    assert not ses.envio_sin_confirmar(s, time.time())  # trabajando: no se avisa
    ses.set_state(s, "termino")  # cerro el turno y no tomo la cola
    assert not ses.envio_sin_confirmar(s, time.time())  # se cuenta desde que quedo libre
    _hace(s, ses.ENVIO_SIN_CONFIRMAR_S + 1)
    assert ses.envio_sin_confirmar(s, time.time()) and s["needs"]["kind"] == "sin_enviar"


def test_sin_hooks_sigue_como_antes(tarjeta):
    s, _ = tarjeta
    s["hooked"] = False
    ses.send_to_session(s, "hola", [])
    assert s["state"] == "corriendo" and s["envio_pendiente"] is None


def test_envio_fallido_no_deja_pendiente(tarjeta):
    s, salida = tarjeta
    salida["ok"] = False
    salida["error"] = "WriteConsoleInputW fallo"
    code, _ = ses.send_to_session(s, "hola", [])
    assert code == 500 and s["envio_pendiente"] is None and s["sent_mark"] is None


def test_consola_que_no_consumio_queda_registrada(tarjeta):
    s, salida = tarjeta
    salida["enter_sin_consumo"] = True
    ses.send_to_session(s, "hola", [])
    assert s["envio_pendiente"]["sin_consumo"] is True


def test_enter_a_mano_despues_del_aviso_lo_limpia(tarjeta):
    s, _ = tarjeta
    ses.send_to_session(s, "quedo en el editor", [])
    _hace(s, ses.ENVIO_SIN_CONFIRMAR_S + 1)
    assert ses.envio_sin_confirmar(s, time.time())
    ses.hook_prompt_submit(s, {"prompt": "quedo en el editor"})  # Ariel aprieta Enter en la terminal
    assert s["state"] == "corriendo" and s["needs"] is None
