"""Ruteo y confidencialidad del navegador; sin abrir Chrome ni tocar perfiles reales."""

import json
from types import SimpleNamespace

import browser_api as api
import browser_remote
import pytest
import secretos


@pytest.fixture
def channel(monkeypatch):
    key = bytes(range(32))
    calls = []
    monkeypatch.setattr(api.identity, "pc_id", lambda: "local")
    monkeypatch.setattr(api.mirror.MIRROR, "conn_of", lambda pc: SimpleNamespace(key=key) if pc == "remote" else None)
    monkeypatch.setattr(api.mirror.MIRROR, "supports", lambda *args: True)
    monkeypatch.setattr(browser_remote.HOST, "request", lambda data: (calls.append(data) or 200, {"ok": True}))
    return key, calls


def test_requires_explicit_destination(channel):
    assert api.dispatch({"action": "start"})[0] == 400
    assert api.dispatch({"pc": "gone", "action": "start"})[0] == 404
    assert channel[1] == []


def test_local_only_receives_command(channel):
    assert api.dispatch({"pc": "local", "action": "start"}) == (200, {"ok": True})
    assert channel[1] == [{"action": "start"}]


def test_remote_encrypts_input_and_checks_reply(channel, monkeypatch):
    key, calls = channel

    def forward(pc, method, path, body, **kwargs):
        assert (pc, method, path) == ("remote", "POST", "/browser")
        assert "private-input-123" not in json.dumps(body)
        return api.from_peer(body, key)

    monkeypatch.setattr(api.mirror.MIRROR, "forward", forward)
    command = {"action": "input", "events": [{"kind": "text", "text": "private-input-123"}]}
    assert api.dispatch({"pc": "remote", **command}) == (200, {"ok": True})
    assert calls == [command]


def test_replayed_response_rejected(channel, monkeypatch):
    key, calls = channel
    old = secretos.cifrar(api.channel_key(key), json.dumps({"id": "0" * 32, "status": 200, "result": {"ok": True}}))
    monkeypatch.setattr(api.mirror.MIRROR, "forward", lambda *a, **k: (200, old))
    assert api.dispatch({"pc": "remote", "action": "state"})[0] == 502
    assert not calls


def test_missing_capability_does_not_start_local_browser(channel, monkeypatch):
    monkeypatch.setattr(api.mirror.MIRROR, "supports", lambda *args: False)
    assert api.dispatch({"pc": "remote", "action": "start"})[0] == 409
    assert channel[1] == []


def test_uncertain_network_failure_is_not_retried(channel, monkeypatch):
    sent = []

    def forward(*args, **kwargs):
        sent.append(args)
        return 503, {"error": "timeout"}

    monkeypatch.setattr(api.mirror.MIRROR, "forward", forward)
    assert api.dispatch({"pc": "remote", "action": "new"}) == (503, {"error": "timeout"})
    assert len(sent) == 1 and channel[1] == []


@pytest.mark.parametrize("body", [{}, {"nonce": "wrong"}, {"action": "start"}])
def test_peer_rejects_plaintext_or_damaged_data(channel, body):
    assert api.from_peer(body, channel[0])[0] == 400
    assert channel[1] == []


def test_closed_browser_state_does_not_spawn(monkeypatch):
    host = browser_remote.BrowserHost()
    monkeypatch.setattr(host, "_start", lambda: pytest.fail("no debe iniciar Chrome"))
    assert host.request({"action": "state"}) == (200, {"running": False, "tabs": []})
    assert host.request({"action": "input"})[0] == 409


def test_oversized_input_rejected_before_spawn(channel):
    assert api.dispatch({"pc": "local", "action": "input", "text": "x" * 66000})[0] == 400
    assert not channel[1]


def test_encryption_large_frame_roundtrip():
    key = bytes(range(32))
    frame = "pixel-" * 25000
    assert secretos.descifrar(key, secretos.cifrar(key, frame)) == frame
