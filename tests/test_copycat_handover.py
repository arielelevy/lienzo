"""Traslado Pi → Codex sin escribir en terminales ni contactar PCs reales."""

import os

import pytest

# ruff: noqa: I001
from lienzo import server
import sessions as ses
import state as st


@pytest.fixture
def cards(monkeypatch):
    os.makedirs(st.SESSIONS, exist_ok=True)
    origin = ses.new_session("pi-origin", "pi", "hook")
    target = ses.new_session("pid-42", "codex", "sweep")
    origin.update(title="chess - trabajo", state="termino", pid=10)
    target.update(state="corriendo", pid=42)
    monkeypatch.setattr(st, "sessions", {origin["session_id"]: origin, target["session_id"]: target})
    monkeypatch.setattr(ses, "sessions", st.sessions)
    monkeypatch.setattr(server, "sessions", st.sessions)
    monkeypatch.setattr(server, "registrar_envio", lambda sid, data: origin)
    monkeypatch.setattr(ses, "_mirror_rules", list)
    monkeypatch.setattr(ses, "stopped_recipients", lambda card: [])
    monkeypatch.setattr(server.mirror.MIRROR, "rules", list)
    monkeypatch.setattr(server.mirror.MIRROR, "sessions", list)
    return origin, target


def test_remote_owner_is_retargeted_even_without_cached_rules(cards, monkeypatch):
    origin, target = cards
    monkeypatch.setattr(
        server.mirror.MIRROR,
        "sessions",
        lambda: [
            {"session_id": origin["session_id"], "pc": "owner"},
        ],
    )
    assert server.peers_del_traspaso(origin["session_id"], target["session_id"]) == ["owner"]


def test_inactive_remote_rule_does_not_block_handover(cards, monkeypatch):
    origin, target = cards
    monkeypatch.setattr(
        server.mirror.MIRROR,
        "rules",
        lambda: [
            {"pc": "unrelated", "enabled": False, "from": "remote", "to": origin["session_id"]},
        ],
    )
    assert server.peers_del_traspaso(origin["session_id"], target["session_id"]) == []


def test_local_rule_conflict_is_visible_without_stopping_origin(cards):
    origin, target = cards
    st.rules.items[:] = [
        {"id": "conflict", "enabled": True, "kind": "on_stop", "from": origin["session_id"], "to": target["session_id"]}
    ]
    result = {"ok": True}
    server.envio_del_tablero(target["session_id"], target, {"copycat": True, "from": origin["session_id"]}, result)
    assert "misma sesión" in result["handover_error"]
    assert origin["stopped_by"] is None
    assert target["copycat_of"] == origin["session_id"]


def test_post_send_uses_current_destination_id(cards, monkeypatch):
    origin, target = cards
    st.sessions.pop(target["session_id"])
    target["session_id"] = "codex-real"
    st.sessions[target["session_id"]] = target
    registered = []
    monkeypatch.setattr(server, "registrar_envio", lambda sid, data: registered.append(sid) or origin)
    result = {"ok": True}
    server.envio_del_tablero("pid-42", target, {"copycat": True, "from": origin["session_id"]}, result)
    assert registered == ["codex-real"]
    assert origin["stopped_by"] == "codex-real"


def test_unrelated_unreachable_peer_does_not_block_local_copycat(cards, monkeypatch):
    origin, target = cards
    contacted = []
    monkeypatch.setattr(server.mirror.MIRROR, "peer_ids", lambda: ["unrelated"])

    def forward(pc, *args):
        contacted.append(pc)
        return 503, {"error": "timeout"}

    monkeypatch.setattr(server.mirror.MIRROR, "forward", forward)
    result = {"ok": True}
    server.envio_del_tablero(target["session_id"], target, {"copycat": True, "from": origin["session_id"]}, result)
    assert contacted == []
    assert target["copycat_of"] == origin["session_id"]
    assert target["title"] == "chess - trabajo · copycat"
    assert origin["stopped_by"] == target["session_id"]
    assert "handover_error" not in result


def test_relevant_peer_failure_keeps_copycat_and_reports_pending_transfer(cards, monkeypatch):
    origin, target = cards
    monkeypatch.setattr(server.mirror.MIRROR, "peer_ids", lambda: ["related"])
    monkeypatch.setattr(
        server.mirror.MIRROR,
        "rules",
        lambda: [
            {"pc": "related", "enabled": True, "from": "remote", "to": origin["session_id"]},
        ],
    )
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *args: (503, {"error": "timeout"}))
    result = {"ok": True}
    server.envio_del_tablero(target["session_id"], target, {"copycat": True, "from": origin["session_id"]}, result)
    assert target["copycat_of"] == origin["session_id"]
    assert target["title"].endswith(" · copycat")
    assert origin["stopped_by"] is None
    assert "related" in result["handover_error"]


def test_copycat_identity_follows_provisional_destination(cards, monkeypatch):
    origin, target = cards
    origin["stopped_by"] = target["session_id"]
    target["copycat_of"] = origin["session_id"]
    saved = []
    monkeypatch.setattr(ses, "touch", lambda card: saved.append(card["session_id"]))
    ses.repoint_refs(target["session_id"], "codex-real")
    assert origin["stopped_by"] == "codex-real"
    assert saved == [origin["session_id"]]


def test_copycat_identity_follows_provisional_origin(cards, monkeypatch):
    origin, target = cards
    target["copycat_of"] = origin["session_id"]
    monkeypatch.setattr(ses, "touch", lambda card: None)
    ses.repoint_refs(origin["session_id"], "pi-real")
    assert target["copycat_of"] == "pi-real"


def test_reference_save_failure_rolls_back_ids_and_rules(cards, monkeypatch):
    origin, target = cards
    origin["stopped_by"] = target["session_id"]
    st.rules.items[:] = [{"id": "r", "from": "other", "to": target["session_id"]}]

    def save(card):
        if card.get("stopped_by") == "codex-real":
            raise OSError("disco lleno")

    monkeypatch.setattr(ses, "touch", save)
    with pytest.raises(OSError, match="disco lleno"):
        ses.repoint_refs(target["session_id"], "codex-real")
    assert origin["stopped_by"] == target["session_id"]
    assert st.rules.items[0]["to"] == target["session_id"]
