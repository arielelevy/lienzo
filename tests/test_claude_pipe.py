import json
import threading
import time
import urllib.error
import urllib.request
import uuid

import pytest

from lienzo.claude_pipe import ClaudePipeBridge


def request(bridge, route, data, secret=None):
    env = bridge.environment()
    data = {"session_id": bridge.session_id, **data}
    req = urllib.request.Request(
        env["LIENZO_CLAUDE_BRIDGE_URL"] + route,
        json.dumps(data).encode(),
        {"Authorization": "Bearer " + (env["LIENZO_CLAUDE_BRIDGE_SECRET"] if secret is None else secret)},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def test_authenticated_roundtrip_and_dedup():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        key = str(uuid.uuid4())
        results = []
        worker = threading.Thread(target=lambda: results.append(bridge.send("hola", key)))
        worker.start()
        job = request(bridge, "/poll", {})
        assert job == {"id": key, "text": "hola"}
        request(bridge, "/result", {"id": key, "status": "pipe_written"})
        worker.join(3)
        assert results == [{"id": key, "status": "pipe_written"}]
        assert bridge.send("hola", key) == results[0]
        assert request(bridge, "/poll", {}) == {}
        with pytest.raises(ValueError, match="message_id_conflict"):
            bridge.send("otro", key)


def test_invalid_auth_and_session_never_register():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(bridge, "/poll", {}, secret="invalid")
        assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(bridge, "/poll", {"session_id": str(uuid.uuid4())})
        assert exc.value.code == 409
        assert not bridge.registered.is_set()


def test_timeout_before_pickup_is_not_sent_later():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        key = str(uuid.uuid4())
        assert bridge.send("no entregar", key, timeout=0.01)["status"] == "unknown"
        assert bridge.send("no entregar", key)["status"] == "unknown"
        assert request(bridge, "/poll", {}) == {}


def test_timeout_after_pickup_no_retry_and_late_result():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        key = str(uuid.uuid4())
        results = []
        worker = threading.Thread(target=lambda: results.append(bridge.send("hola", key, timeout=0.2)))
        worker.start()
        assert request(bridge, "/poll", {})["id"] == key
        worker.join(2)
        assert results[0]["status"] == "unknown"
        assert bridge.send("hola", key)["status"] == "unknown"
        request(bridge, "/result", {"id": key, "status": "pipe_written"})
        assert bridge.send("hola", key)["status"] == "pipe_written"
        assert request(bridge, "/poll", {}) == {}


def test_close_unblocks_waiter():
    bridge = ClaudePipeBridge(str(uuid.uuid4()))
    results = []
    worker = threading.Thread(target=lambda: results.append(bridge.send("hola", str(uuid.uuid4()))))
    worker.start()
    time.sleep(0.02)
    bridge.close()
    worker.join(2)
    assert results[0]["status"] == "unknown"


def test_registration_expires_and_close_removes_capability():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        assert not bridge.available
        request(bridge, "/poll", {})
        assert bridge.registered.is_set() and bridge.available
        bridge.last_poll -= 4
        assert bridge.registered.is_set() and not bridge.available
    assert not bridge.available


def test_unknown_write_is_not_failed_or_retried():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        key = str(uuid.uuid4())
        results = []
        worker = threading.Thread(target=lambda: results.append(bridge.send("hola", key)))
        worker.start()
        request(bridge, "/poll", {})
        request(bridge, "/result", {"id": key, "status": "unknown"})
        worker.join(2)
        assert results[0]["status"] == "unknown"
        assert request(bridge, "/poll", {}) == {}


def test_authenticated_nonobject_json_rejected_without_registering():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        env = bridge.environment()
        req = urllib.request.Request(
            env["LIENZO_CLAUDE_BRIDGE_URL"] + "/poll",
            b"[]",
            {"Authorization": "Bearer " + env["LIENZO_CLAUDE_BRIDGE_SECRET"]},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req, timeout=2)
        assert error.value.code == 400
        assert not bridge.registered.is_set()
