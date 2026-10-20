"""Contrato tabs con HOST falso: nunca abre Chrome ni toca sesiones del usuario."""

import base64
import io
import json
import queue
import threading
import time
from itertools import pairwise
from types import SimpleNamespace

import browser_remote
import browser_stream as module
import federation
import pytest
import ws


def test_broker_dispatches_out_of_order_and_ignores_old_id():
    host = browser_remote.CDPHost()
    process = SimpleNamespace(
        stdout=io.StringIO(
            "\n".join(
                json.dumps(x)
                for x in [
                    {"requestId": 999, "wrong": True},
                    {"requestId": 2, "value": "input"},
                    {"requestId": 1, "value": "frame"},
                ]
            )
        )
    )
    one, two = queue.Queue(1), queue.Queue(1)
    host.pending = {1: (process, one), 2: (process, two)}
    host._read(process, None)
    assert one.get_nowait() == {"value": "frame"}
    assert two.get_nowait() == {"value": "input"}


@pytest.fixture
def tab_worker(monkeypatch):
    gate = threading.Event()
    capturing = threading.Event()
    input_done = threading.Event()
    frame_done = threading.Event()
    calls, output = [], []

    def request(data):
        calls.append(data)
        if data["action"] == "snapshot":
            capturing.set()
            assert gate.wait(3), "fixture no liberado"
            return 200, {"image": base64.b64encode(b"jpeg" + bytes([len(calls) % 256])).decode()}
        if data["action"] in ("input", "release-input"):
            input_done.set()
        return 200, {"tabs": []}

    def deliver(kind, payload):
        output.append((kind, payload))
        if kind == ws.BINARY:
            frame_done.set()
        elif json.loads(payload).get("input"):
            input_done.set()

    monkeypatch.setattr(browser_remote.HOST, "request", request)
    worker = module.TabWorker(deliver, lambda: None)
    try:
        yield worker, gate, capturing, input_done, frame_done, calls, output
    finally:
        worker.close()
        gate.set()
        for thread in worker.threads:
            thread.join(3)
            assert not thread.is_alive()


def send(worker, **data):
    worker.send(json.dumps(data).encode())


def wait_message(output, predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        for kind, payload in list(output):
            if kind == ws.TEXT and predicate(json.loads(payload)):
                return json.loads(payload)
        time.sleep(0.005)
    pytest.fail("Faltó respuesta del worker")


def test_capture_does_not_block_input_and_ack_is_exact(tab_worker):
    worker, gate, capturing, input_done, frame_done, calls, output = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(worker, t="input", n=1, generation=1, events=[{"kind": "text", "text": "a"}])
    assert input_done.wait(1), "input dependió de la captura bloqueada"
    assert not frame_done.is_set()
    gate.set()
    assert frame_done.wait(1)
    packet = next(payload for kind, payload in output if kind == ws.BINARY)
    assert module.TAB_FRAME.unpack(packet[:12]) == (1, 1, 800, 600)
    send(worker, t="ack", generation=1, n=99)
    assert worker.awaiting == (1, 1)
    send(worker, t="ack", generation=2, n=1)
    assert worker.awaiting == (1, 1)
    send(worker, t="pause")
    send(worker, t="ack", generation=1, n=1)
    assert worker.awaiting is None
    assert len([c for c in calls if c["action"] == "snapshot"]) == 1


def test_tab_key_separates_transport_modes():
    assert module.channel_key(bytes(32), "a" * 32) != module.channel_key(bytes(32), "a" * 32, "tabs")


def test_relay_tab_mode_is_in_signed_path_and_old_peer_rejected(monkeypatch):
    from types import SimpleNamespace

    calls, sent = [], []
    conn = SimpleNamespace(key=bytes(32), host="fixture", port=1, self_pc_id="local")
    monkeypatch.setattr(module.mirror.MIRROR, "conn_of", lambda pc: conn)
    monkeypatch.setattr(module.mirror.MIRROR, "supports", lambda pc, cap: calls.append(cap) or True)

    def connect(host, port, path, headers):
        assert path.startswith("/peer/browser/stream/tabs/") and "?" not in path
        timestamp = float(headers["X-Lienzo-Ts"])
        nonce, signature = headers["X-Lienzo-Nonce"], headers["X-Lienzo-Sig"]
        assert federation.sign(conn.key, "GET", path, b"", timestamp, nonce) == signature
        window_path = path.replace("/tabs/", "/")
        assert federation.sign(conn.key, "GET", window_path, b"", timestamp, nonce) != signature
        raise ConnectionError("fixture no socket")

    monkeypatch.setattr(module.ws, "client_connect", connect)
    sock = SimpleNamespace(send=lambda kind, payload: sent.append(payload))
    module._relay(sock, "peer", "tabs")
    assert calls == ["browser.tabs.stream.v1"]
    assert b"fixture no socket" in sent[-1]
    monkeypatch.setattr(module.mirror.MIRROR, "supports", lambda pc, cap: None)
    monkeypatch.setattr(module.ws, "client_connect", lambda *args: pytest.fail("peer sin capability"))
    module._relay(sock, "old", "tabs")
    assert b"Actualiz" in sent[-1]


def test_immediate_acks_do_not_exceed_ten_fps(tab_worker):
    worker, gate, _, _, frame_done, calls, output = tab_worker
    started = []
    original = browser_remote.HOST.request

    def request(data):
        if data["action"] == "snapshot":
            started.append(time.monotonic())
        return original(data)

    browser_remote.HOST.request = request
    gate.set()
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    for n in range(1, 5):
        assert frame_done.wait(1)
        frame_done.clear()
        send(worker, t="ack", generation=1, n=n)
    assert len(started) >= 4
    assert all(right - left >= 0.095 for left, right in pairwise(started))


def test_owner_stays_reserved_until_inflight_capture_finishes(tab_worker):
    worker, gate, capturing, *_ = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    worker.close()
    assert module._tab_owners["a"] is worker
    gate.set()
    worker.wait_closed()
    assert "a" not in module._tab_owners


def test_switch_discards_old_capture_and_rejects_stale_input(tab_worker):
    worker, gate, capturing, input_done, frame_done, calls, output = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(worker, t="open", tab="b", generation=2, width=900, height=700)
    send(worker, t="input", n=1, generation=1, events=[{"kind": "text", "text": "old"}])
    assert input_done.wait(1)
    assert not any(c["action"] == "input" for c in calls)
    gate.set()
    assert frame_done.wait(1)
    frames = [module.TAB_FRAME.unpack(p[:12]) for kind, p in output if kind == ws.BINARY]
    assert frames and all(frame[0] == 2 for frame in frames)


def test_duplicate_target_rejected_without_new_host(tab_worker):
    worker, _, capturing, *_ = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    output = []
    other = module.TabWorker(lambda *args: output.append(args), lambda: None)
    try:
        send(other, t="open", tab="a", generation=1, width=800, height=600)
        assert "ya tiene un visor" in wait_message(output, lambda m: m["t"] == "error")["message"]
    finally:
        other.close()
        for thread in other.threads:
            thread.join(3)


def test_release_input_is_ordered_before_open_and_rejects_old_generation(tab_worker):
    worker, _, capturing, _, _, calls, output = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    key = {"kind": "key", "type": "keyDown", "key": "Control", "code": "ControlLeft", "keyCode": 17, "modifiers": 2}
    send(worker, t="input", n=1, generation=1, events=[key])
    wait_message(output, lambda m: m["t"] == "input" and m["n"] == 1)
    send(worker, t="release-input", n=2, generation=1)
    send(worker, t="open", tab="b", generation=2, width=900, height=700)
    released = wait_message(output, lambda m: m.get("n") == 2)
    assert released == {"t": "input", "n": 2, "generation": 1}
    wait_message(output, lambda m: m["t"] == "opened" and m["generation"] == 2)
    actions = [c for c in calls if c["action"] in ("input", "release-input", "viewport")]
    assert [c["action"] for c in actions] == ["viewport", "input", "release-input", "viewport"]
    assert actions[2]["tab"] == "a" and actions[2]["events"][0]["type"] == "keyUp"
    send(worker, t="release-input", n=3, generation=1)
    rejected = wait_message(output, lambda m: m.get("n") == 3)
    assert rejected["outcome"] == "rejected"
    assert len([c for c in calls if c["action"] in ("input", "release-input")]) == 2


def test_open_and_close_release_only_own_mouse_downs(tab_worker):
    worker, gate, capturing, _, _, calls, output = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    mouse = {
        "kind": "mouse",
        "type": "mousePressed",
        "button": "left",
        "buttons": 1,
        "x": 10,
        "y": 20,
        "modifiers": 0,
        "clickCount": 1,
    }
    send(worker, t="input", n=1, generation=1, events=[mouse])
    wait_message(output, lambda m: m.get("n") == 1)
    send(worker, t="open", tab="b", generation=2, width=800, height=600)
    wait_message(output, lambda m: m["t"] == "opened" and m["generation"] == 2)
    assert any(
        c["action"] == "release-input" and c["tab"] == "a" and c["events"][0]["type"] == "mouseReleased" for c in calls
    )
    send(worker, t="input", n=2, generation=2, events=[mouse])
    wait_message(output, lambda m: m.get("n") == 2)
    worker.close()
    assert calls[-1]["tab"] == "b" and calls[-1]["events"][0]["type"] == "mouseReleased"
    gate.set()


def test_uncertain_down_is_released_without_replaying_down(tab_worker, monkeypatch):
    worker, _, capturing, _, _, calls, output = tab_worker
    original = browser_remote.HOST.request

    def request(data):
        if data["action"] == "input" and data["events"][0]["type"] == "keyDown":
            calls.append(data)
            return 504, {"error": "respuesta perdida"}
        return original(data)

    monkeypatch.setattr(browser_remote.HOST, "request", request)
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(
        worker,
        t="input",
        n=1,
        generation=1,
        events=[{"kind": "key", "type": "keyDown", "key": "a", "code": "KeyA", "keyCode": 65, "modifiers": 0}],
    )
    assert wait_message(output, lambda m: m.get("n") == 1)["outcome"] == "uncertain"
    send(worker, t="release-input", n=2, generation=1)
    assert wait_message(output, lambda m: m.get("n") == 2)["t"] == "input"
    assert [c["events"][0]["type"] for c in calls if c["action"] in ("input", "release-input")] == ["keyDown", "keyUp"]


def test_release_failure_is_visible_and_does_not_change_target(tab_worker, monkeypatch):
    worker, _, capturing, _, _, calls, output = tab_worker
    original = browser_remote.HOST.request

    def request(data):
        if data["action"] == "release-input" and data["events"][0].get("type") == "keyUp":
            return 504, {"error": "release incierto"}
        return original(data)

    monkeypatch.setattr(browser_remote.HOST, "request", request)
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(
        worker,
        t="input",
        n=1,
        generation=1,
        events=[{"kind": "key", "type": "keyDown", "key": "a", "code": "KeyA", "keyCode": 65, "modifiers": 0}],
    )
    wait_message(output, lambda m: m.get("n") == 1)
    send(worker, t="open", tab="b", generation=2, width=800, height=600)
    assert (
        "release incierto" in wait_message(output, lambda m: m["t"] == "error" and m.get("generation") == 2)["message"]
    )
    assert worker.target == "a"
    assert not any(c["action"] == "viewport" and c["tab"] == "b" for c in calls)


def test_open_does_not_override_viewer_pause(tab_worker):
    worker, _, capturing, _, _, _, output = tab_worker
    send(worker, t="pause")
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    wait_message(output, lambda m: m["t"] == "opened")
    assert not capturing.wait(0.1)
    send(worker, t="resume")
    assert capturing.wait(1)


def test_owner_not_freed_while_close_release_ack_is_pending(tab_worker, monkeypatch):
    worker, capture_gate, capturing, _, _, _, output = tab_worker
    release_started, release_gate = threading.Event(), threading.Event()
    original = browser_remote.HOST.request

    def request(data):
        if data["action"] == "release-input" and data["events"][0].get("type") == "keyUp":
            release_started.set()
            assert release_gate.wait(3)
        return original(data)

    monkeypatch.setattr(browser_remote.HOST, "request", request)
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(
        worker,
        t="input",
        n=1,
        generation=1,
        events=[{"kind": "key", "type": "keyDown", "key": "a", "code": "KeyA", "keyCode": 65, "modifiers": 0}],
    )
    wait_message(output, lambda m: m.get("n") == 1)
    closing = threading.Thread(target=worker.close)
    closing.start()
    try:
        assert release_started.wait(1)
        capture_gate.set()
        for thread in worker.threads:
            thread.join(1)
            assert not thread.is_alive()
        assert module._tab_owners.get("a") is worker
        assert not worker.release_finished
    finally:
        release_gate.set()
        closing.join(3)
        assert not closing.is_alive()
    assert "a" not in module._tab_owners


def test_mouse_release_uses_last_move_and_zero_click_count(tab_worker):
    worker, _, capturing, _, _, calls, output = tab_worker
    send(worker, t="open", tab="a", generation=1, width=800, height=600)
    assert capturing.wait(1)
    send(
        worker,
        t="input",
        n=1,
        generation=1,
        events=[
            {
                "kind": "mouse",
                "type": "mousePressed",
                "button": "left",
                "buttons": 1,
                "x": 10,
                "y": 20,
                "modifiers": 0,
                "clickCount": 1,
            }
        ],
    )
    wait_message(output, lambda m: m.get("n") == 1)
    send(
        worker,
        t="input",
        n=2,
        generation=1,
        events=[
            {
                "kind": "mouse",
                "type": "mouseMoved",
                "button": "none",
                "buttons": 1,
                "x": 300,
                "y": 300,
                "modifiers": 0,
                "clickCount": 0,
            }
        ],
    )
    wait_message(output, lambda m: m.get("n") == 2)
    send(worker, t="release-input", n=3, generation=1)
    wait_message(output, lambda m: m.get("n") == 3)
    release = next(c for c in calls if c["action"] == "release-input")["events"][0]
    assert (release["x"], release["y"], release["clickCount"]) == (300, 300, 0)
