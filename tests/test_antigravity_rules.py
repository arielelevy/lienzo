"""No prometer informes sin un fin de turno verificable; sin tocar reglas reales."""

from copy import deepcopy
from types import SimpleNamespace

import agentes
import mirror
import pytest
import rules_api as api
import sessions
import state


@pytest.fixture
def registry(monkeypatch):
    local = {"target": {"session_id": "target", "agent": "claude", "alive": True}}
    remote = []
    calls = []
    writes = []
    monkeypatch.setattr(api, "sessions", local)
    monkeypatch.setattr(sessions, "sessions", local)
    monkeypatch.setattr(sessions, "mirror", mirror)
    monkeypatch.setattr(
        mirror,
        "MIRROR",
        SimpleNamespace(
            sessions=lambda: remote,
            owner_of=lambda sid: "other-pc" if any(s["session_id"] == sid for s in remote) else None,
            rules=list,
            supports=lambda pc, cap: True,
            forward=lambda *args: calls.append(args) or (200, {"id": "remote-rule"}),
        ),
    )
    monkeypatch.setattr(state.rules, "items", [])
    monkeypatch.setattr(state.rules, "save", lambda **kw: writes.append("save"))
    monkeypatch.setattr(state.rules, "publish", lambda: writes.append("publish"))
    monkeypatch.setattr(state, "log", lambda *args: None)
    return local, remote, calls, writes


def add_source(registry, agent, remote):
    local, peers, _, _ = registry
    source = {"session_id": "source", "agent": agent, "alive": True}
    if remote:
        peers.append(source)
    else:
        local["source"] = source


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("agent", ["antigravity", "future-cli", None, ["invalid"]])
def test_create_rejects_terminal_only_or_unknown_source_without_mutation(registry, agent, remote):
    add_source(registry, agent, remote)
    pending = {"id": "retained", "informes": [{"id": "pending", "estado": "pendiente"}]}
    state.rules.items.append(deepcopy(pending))
    code, body = api.create_rule({"kind": "on_stop", "from": "source", "to": "target", "text": "report"})
    assert code == 409
    assert body["code"] == ("unsupported_on_stop" if agent == "antigravity" else "unverified_on_stop_source")
    assert state.rules.items == [pending]
    assert registry[2] == [] and registry[3] == []


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize(
    "agent", [name for name, profile in agentes.AGENTES.items() if not profile.capabilities.get("terminalOnly")]
)
def test_other_agents_keep_creation_semantics(registry, agent, remote):
    add_source(registry, agent, remote)
    code, body = api.create_rule({"kind": "on_stop", "from": "source", "to": "target", "text": "report"})
    assert code == 200
    if remote:
        assert body == {"id": "remote-rule"}
        assert len(registry[2]) == 1
    else:
        assert body["kind"] == "on_stop" and body["enabled"]


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize(
    "agent", [name for name, profile in agentes.AGENTES.items() if not profile.capabilities.get("terminalOnly")]
)
def test_other_agents_keep_reenable_semantics_and_reports(registry, agent, remote):
    add_source(registry, agent, remote)
    reports = [{"id": "pending", "estado": "pendiente"}]
    state.rules.items.append(
        {
            "id": "old",
            "kind": "on_stop",
            "from": "source",
            "to": "target",
            "enabled": False,
            "repeat": False,
            "limit": "rate",
            "informes": deepcopy(reports),
        }
    )
    code, rule = api.edit_rule("old", {"enabled": True})
    assert code == 200 and rule["enabled"] is True and rule["informes"] == reports


def test_remote_owner_without_source_metadata_is_not_permission(registry, monkeypatch):
    monkeypatch.setattr(mirror.MIRROR, "owner_of", lambda sid: "pcB" if sid == "source" else None)
    code, body = api.create_rule({"kind": "on_stop", "from": "source", "to": "target", "text": "report"})
    assert code == 409 and body["code"] == "unverified_on_stop_source"
    assert registry[2] == [] and registry[3] == []


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("changes", [{"enabled": True}, {"repeat": True}, {"limit": "rate"}, {"text": "edited"}])
@pytest.mark.parametrize("agent", ["antigravity", "unknown"])
def test_reenable_explicit_or_implicit_rejects_before_changing_pending_reports(registry, remote, changes, agent):
    add_source(registry, agent, remote)
    rule = {
        "id": "old",
        "kind": "on_stop",
        "from": "source",
        "to": "target",
        "enabled": False,
        "repeat": True,
        "limit": "rate",
        "disabled_at": "2026-10-20T00:00:00Z",
        "text": "original",
        "informes": [{"id": "pending", "estado": "pendiente", "respuesta": "conservar"}],
    }
    state.rules.items.append(rule)
    before = deepcopy(rule)
    assert api.edit_rule("old", changes)[0] == 409
    assert rule == before and state.rules.items == [before]
    assert registry[2] == [] and registry[3] == []


def test_disabling_preserves_pending_reports_for_old_terminal_rule(registry):
    add_source(registry, "antigravity", False)
    reports = [{"id": "pending", "estado": "pendiente", "respuesta": "conservar"}]
    state.rules.items.append(
        {
            "id": "old",
            "kind": "on_stop",
            "from": "source",
            "to": "target",
            "enabled": True,
            "repeat": False,
            "limit": "rate",
            "text": "original",
            "informes": deepcopy(reports),
        }
    )
    code, rule = api.edit_rule("old", {"enabled": False})
    assert code == 200 and rule["enabled"] is False
    assert rule["informes"] == reports


@pytest.mark.parametrize("agent", ["antigravity", "unknown"])
def test_at_rules_do_not_depend_on_source_agent(registry, agent):
    add_source(registry, agent, False)
    code, rule = api.create_rule(
        {"kind": "at", "from": "source", "to": "target", "text": "hello", "at": "2099-10-20T00:00:00Z"}
    )
    assert code == 200
    rule["enabled"] = False
    code, result = api.edit_rule(rule["id"], {"enabled": True})
    assert code == 200 and result["enabled"] is True
