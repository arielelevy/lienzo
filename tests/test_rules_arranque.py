"""B02: la migración de arranque no habilita reglas inseguras ni usa peers reales."""

import copy
import json

import pytest
import rules as rl
import rules_api as api
import sessions as ses
import state as st

A, B = "inicio-A", "inicio-B"


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(st, "sessions", {A: {"agent": "claude"}, B: {"agent": "codex"}})
    monkeypatch.setattr(rl, "sessions", st.sessions)
    monkeypatch.setattr(api, "sessions", st.sessions)
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    monkeypatch.setattr(api, "find_session", lambda sid: st.sessions.get(sid))
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.rules, "save", lambda: None)
    monkeypatch.setattr(st.rules, "publish", lambda: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(rl, "send_to_session", lambda *a, **kw: pytest.fail("envío no autorizado"))
    monkeypatch.setattr(ses, "_mirror_forward", lambda *a, **kw: pytest.fail("peer real no autorizado"))


def agotada(**extra):
    r = {
        "id": "vieja",
        "kind": "on_stop",
        "from": A,
        "to": B,
        "text": "informe",
        "repeat": True,
        "enabled": False,
        "max_fires": 30,
        "fired": 30,
        "last_fired": "2026-10-21T00:00:00.000Z",
        "disabled_at": "2026-10-21T00:00:00.001Z",
        "informes": [{"id": "pendiente", "estado": "pendiente"}],
        **extra,
    }
    st.rules.items.append(r)
    return r


def comprobar_bloqueada(r, antes):
    assert not r["enabled"]
    assert r["disabled_at"] == antes["disabled_at"]
    assert r["informes"] == antes["informes"]
    assert r.get("disabled_reason") and r.get("last_result")


def test_arranque_con_inversa_activa_no_habilita(entorno):
    r = agotada()
    st.rules.items.append({"id": "inversa", "kind": "on_stop", "from": B, "to": A, "enabled": True})
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)


def test_dos_agotadas_inversas_no_se_habilitan_juntas(entorno):
    una = agotada()
    otra = agotada(id="otra", **{"from": B, "to": A})
    assert rl.reactivar_agotadas_por_tope_viejo() == 1
    assert una["enabled"] and not otra["enabled"]
    assert otra.get("disabled_reason")


def test_arranque_ve_inversa_espejada(entorno, monkeypatch):
    r = agotada()
    monkeypatch.setattr(
        ses,
        "_mirror_rules",
        lambda: [{"id": "remota", "kind": "on_stop", "from": B, "to": A, "enabled": True, "pc": "pcB"}],
    )
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)


@pytest.mark.parametrize("agente", ["antigravity", "desconocido", None])
def test_arranque_rechaza_origen_sin_fin_confirmado(entorno, agente):
    st.sessions[A] = {"agent": agente}
    r = agotada()
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)


@pytest.mark.parametrize("contenido", ["{", "[]", json.dumps({"pcB": {"pc_id": "pcB"}})])
def test_federacion_no_acreditada_queda_apagada_con_motivo(entorno, contenido):
    from pathlib import Path

    Path(st.LIENZO).mkdir(parents=True)
    peers = Path(st.LIENZO) / "peers.json"
    peers.write_text(contenido, encoding="utf-8")
    r = agotada()
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)
    assert peers.read_text(encoding="utf-8") == contenido


def test_destino_remoto_o_desconocido_no_se_asume_local(entorno):
    r = agotada(to="no-local", xpc=True)
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)


def test_sin_conflicto_preserva_informes_y_at_no_cambia(entorno):
    r = agotada()
    at = agotada(id="hora", kind="at")
    at_antes = copy.deepcopy(at)
    informes = r["informes"]
    assert rl.reactivar_agotadas_por_tope_viejo() == 1
    assert r["enabled"] and "disabled_at" not in r
    assert r["informes"] is informes and at == at_antes


def test_diferida_puede_habilitarse_explicita_tras_acreditar_topologia(entorno, monkeypatch):
    from pathlib import Path

    Path(st.LIENZO).mkdir(parents=True)
    (Path(st.LIENZO) / "peers.json").write_text('{"pcB": {}}', encoding="utf-8")
    r = agotada()
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    # La comprobación explícita posterior usa la guardia de API y un espejo ya acreditado.
    monkeypatch.setattr(api.mirror.MIRROR, "rules", list)
    monkeypatch.setattr(api, "check_remote_destination", lambda *a: None)
    code, res = api.edit_rule(r["id"], {"enabled": True})
    assert code == 200 and res["enabled"]
    assert "disabled_reason" not in r and r["informes"][0]["estado"] == "pendiente"


def test_peers_ilegible_no_acredita_ausencia_de_federacion(entorno, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("peers fixture ilegible")

    monkeypatch.setattr(rl, "open", denied, raising=False)
    r = agotada()
    antes = copy.deepcopy(r)
    assert rl.reactivar_agotadas_por_tope_viejo() == 0
    comprobar_bloqueada(r, antes)
    assert "peers.json" in r["disabled_reason"]
