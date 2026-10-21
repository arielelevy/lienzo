"""B02: rehabilitar valida la topología sin envíos ni peers reales."""

import copy
import threading
from types import SimpleNamespace

import pytest
import rules as rl
import rules_api as api
import sessions as ses
import state as st

A, B = "sesion-A", "sesion-B"


@pytest.fixture
def entorno(monkeypatch):
    remote = SimpleNamespace(owners={}, visible=[], destination=[], calls=[], during=None)

    def forward(pc, method, path, body=None):
        remote.calls.append((pc, method, path, copy.deepcopy(body)))
        if remote.during:
            remote.during()
        if path == "/rules/check":
            return 200, {"conflict": rl._rule_clash(body["rule"], remote.destination)}
        assert path == "/rules/lock"
        return 200, {"conflict": rl.loop_conflict(body["rule"], [], remote.destination)}

    fake = SimpleNamespace(owner_of=lambda sid: remote.owners.get(sid), rules=lambda: remote.visible, forward=forward)
    monkeypatch.setattr(api.mirror, "MIRROR", fake)
    monkeypatch.setattr(ses, "mirror", SimpleNamespace(MIRROR=fake))
    monkeypatch.setattr(api.identity, "pc_id", lambda: "bbbbbbbbbbbb")
    monkeypatch.setattr(api, "sessions", {A: {"agent": "claude"}, B: {"agent": "codex"}})
    monkeypatch.setattr(api, "find_session", lambda sid: {"agent": "claude"} if sid == A else None)
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.rules, "save", lambda: None)
    monkeypatch.setattr(st.rules, "publish", lambda: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(rl, "_reservations", {})
    monkeypatch.setattr(rl, "send_to_session", lambda *a, **kw: pytest.fail("envío no autorizado"))
    return remote


def regla(**extra):
    r = {
        "id": "vieja",
        "kind": "on_stop",
        "from": A,
        "to": B,
        "text": "original",
        "enabled": False,
        "repeat": True,
        "limit": "total",
        "max_fires": 3,
        "disabled_at": "2026-10-20T00:00:00Z",
        "fired": 3,
        "informes": [{"id": "pendiente", "estado": "pendiente"}],
        **extra,
    }
    st.rules.items.append(r)
    return r


def inversa():
    return {"id": "inversa", "kind": "on_stop", "from": B, "to": A, "enabled": True, "text": "otra"}


@pytest.mark.parametrize("patch", [{"enabled": True}, {"limit": "rate"}], ids=["explicita", "implicita"])
@pytest.mark.parametrize("ubicacion", ["local", "federada"])
def test_rehabilitar_rechaza_la_inversa_sin_mutacion(entorno, patch, ubicacion):
    r = regla()
    if ubicacion == "local":
        st.rules.items.append(inversa())
    else:
        entorno.visible.append(inversa())
    antes = copy.deepcopy(r)
    code, _ = api.edit_rule(r["id"], {**patch, "text": "no debe guardarse"})
    assert code == 409
    assert r == antes


@pytest.mark.parametrize("patch", [{"enabled": True}, {"limit": "rate"}], ids=["explicita", "implicita"])
def test_consulta_destino_y_arbitro_aunque_el_espejo_aun_no_ve_la_inversa(entorno, patch):
    r = regla()
    api.sessions.pop(B)
    entorno.owners[B] = "aaaaaaaaaaaa"
    entorno.destination.append(inversa())
    antes = copy.deepcopy(r)
    code, _ = api.edit_rule(r["id"], patch)
    assert code == 409
    assert [c[2] for c in entorno.calls] == ["/rules/check", "/rules/lock"]
    assert r == antes


def test_rehabilitar_rechaza_duplicada_y_preserva_informes(entorno):
    r = regla()
    st.rules.items.append({**r, "id": "duplicada", "enabled": True})
    antes = copy.deepcopy(r)
    assert api.edit_rule(r["id"], {"enabled": True})[0] == 409
    assert r == antes


@pytest.mark.parametrize("remoto", [False, True])
def test_sin_conflicto_habilita_y_preserva_objeto_de_informes(entorno, remoto):
    r = regla()
    informes = r["informes"]
    if remoto:
        api.sessions.pop(B)
        entorno.owners[B] = "aaaaaaaaaaaa"
    code, res = api.edit_rule(r["id"], {"limit": "rate"})
    assert code == 200 and res is r and r["enabled"] is True
    assert "disabled_at" not in r
    assert r["informes"] is informes
    assert [c[2] for c in entorno.calls] == (["/rules/check", "/rules/lock"] if remoto else [])


def test_revalida_la_inversa_creada_durante_consulta_remota(entorno):
    r = regla()
    api.sessions.pop(B)
    entorno.owners[B] = "aaaaaaaaaaaa"
    antes = copy.deepcopy(r)
    entorno.during = lambda: st.rules.items.append(inversa())
    assert api.edit_rule(r["id"], {"enabled": True})[0] == 409
    assert r == antes


def test_una_edicion_concurrente_no_se_pisa(entorno):
    r = regla()
    api.sessions.pop(B)
    entorno.owners[B] = "aaaaaaaaaaaa"
    entorno.during = lambda: r.update(text="edición concurrente")
    assert api.edit_rule(r["id"], {"enabled": True, "text": "mi edición"})[0] == 409
    assert r["text"] == "edición concurrente" and not r["enabled"]
    assert r["informes"][0]["estado"] == "pendiente"


def test_consulta_remota_no_retiene_el_lock(entorno):
    r = regla()
    api.sessions.pop(B)
    entorno.owners[B] = "aaaaaaaaaaaa"

    def comprobar():
        libre = threading.Event()

        def tomar():
            with st.lock:
                libre.set()

        hilo = threading.Thread(target=tomar, daemon=True)
        hilo.start()
        assert libre.wait(2), "la red se invocó reteniendo el lock compartido"
        hilo.join(2)

    entorno.during = comprobar
    assert api.edit_rule(r["id"], {"enabled": True})[0] == 200


def test_at_y_desactivar_no_consultan_topologia(entorno, monkeypatch):
    monkeypatch.setattr(api, "check_remote_destination", lambda *a: pytest.fail("consulta fuera de alcance"))
    r = regla(kind="at", at="2026-10-20T00:00:00Z", every_s=None, repeat=False)
    assert api.edit_rule(r["id"], {"enabled": True})[0] == 200
    assert api.edit_rule(r["id"], {"enabled": False})[0] == 200
    assert not r["enabled"] and r["informes"][0]["estado"] == "pendiente"


@pytest.mark.parametrize("datos", [{"enabled": 1}, {"at": "no es fecha"}, {"text": 7}, {"max_fires": "x"}])
def test_validacion_sigue_siendo_anterior_a_buscar_la_regla(entorno, datos):
    assert api.edit_rule("desconocida", datos)[0] == 400
    assert api.edit_rule("desconocida", {})[0] == 404
