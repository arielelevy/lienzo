import os
import time
import uuid

import pytest

from lienzo.claude_pipe import ClaudePipeBridge
from lienzo.claude_pipe_bootstrap import ClaudePipeBootstrap, receive_environment, verified_child

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows kernel named pipe test")


def test_real_client_wrong_ancestry_receives_no_credential():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        bootstrap = ClaudePipeBootstrap(bridge, timeout=2)
        try:
            with pytest.raises((OSError, TimeoutError)):
                receive_environment(bootstrap.address, bootstrap.server_pid, bootstrap.server_start, timeout=1)
            deadline = time.monotonic() + 1
            while not bootstrap.rejected and time.monotonic() < deadline:
                time.sleep(0.02)
            assert bootstrap.rejected == 1
            assert bootstrap.client_pid is None
            assert not bridge.registered.is_set()
        finally:
            bootstrap.close()
        assert not bootstrap._thread.is_alive()
        assert bootstrap.error is None


def test_listener_timeout_and_closed_endpoint():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        bootstrap = ClaudePipeBootstrap(bridge, timeout=0.1)
        bootstrap._thread.join(2)
        assert bootstrap.result == "timeout"
        bootstrap.close()
        with pytest.raises(OSError):
            receive_environment(bootstrap.address, bootstrap.server_pid, bootstrap.server_start, timeout=0.1)


def test_client_rejects_wrong_server_process_identity():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        bootstrap = ClaudePipeBootstrap(bridge, timeout=2)
        try:
            with pytest.raises(ValueError, match="bootstrap_server_identity_mismatch"):
                receive_environment(bootstrap.address, bootstrap.server_pid + 1, bootstrap.server_start)
        finally:
            bootstrap.close()


def test_listener_explicit_close_is_bounded():
    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        bootstrap = ClaudePipeBootstrap(bridge)
        bootstrap.close()
        assert bootstrap.result == "closed"
        assert not bootstrap._thread.is_alive()


def test_wrong_session_identity_rejected_by_real_process_inspection():
    assert not verified_child(os.getpid(), str(uuid.uuid4()))


def test_bootstrap_settings_are_public_and_context_closes_listener():
    import json

    with ClaudePipeBridge(str(uuid.uuid4())) as bridge:
        with ClaudePipeBootstrap(bridge) as bootstrap:
            public = json.dumps(bootstrap.hook_settings())
            assert bridge.environment()["LIENZO_CLAUDE_BRIDGE_SECRET"] not in public
            assert "CLAUDE_CODE_MESSAGING_TOKEN" not in public
            assert bootstrap.public_id in public
            assert str(bootstrap.server_start) in public
            assert bootstrap.command(powershell=True).startswith("& '")
        assert bootstrap.closed
