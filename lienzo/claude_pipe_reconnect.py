"""Public rendezvous only. Claude credentials stay in the pinned owner's adapter."""

import json
import os
import uuid
from ctypes import wintypes
from pathlib import Path

import procinfo
import state
from claude_pipe_bootstrap import kernel_api, process_start, receive_environment


def descriptor_path(sid):
    return Path(state.LIENZO) / "claude-channels" / (str(uuid.UUID(sid)) + ".json")


def publish(sid, owner, bootstrap):
    path = descriptor_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.atomic_write(
        str(path),
        json.dumps(
            {
                "session_id": sid,
                "owner": list(owner),
                "public_id": bootstrap.public_id,
                "server_pid": bootstrap.server_pid,
                "server_start": bootstrap.server_start,
            }
        ),
    )


def server_identity(pid, start):
    """Pin PID/FILETIME while reading image and argv; fail closed on missing evidence."""
    handle = procinfo.open_process(pid, 0x101000)
    if not handle:
        raise ValueError("reconnect_server_unavailable")
    try:
        kernel = kernel_api()
        if process_start(kernel, handle) != start:
            raise ValueError("reconnect_server_recycled")
        image, command = procinfo.image_path(pid), procinfo.command_line(pid)
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        if not image or not command or kernel.WaitForSingleObject(handle, 0) != 258:
            raise ValueError("reconnect_server_unverified")
        return os.path.normcase(image), procinfo.command_args(command)
    finally:
        procinfo.close_handle(handle)


def reconnect(sid, owner, trusted_server):
    """Never trust the public file alone; verify server OS identity before reading secrets."""
    row = json.loads(descriptor_path(sid).read_text(encoding="utf-8"))
    if row.get("session_id") != sid or row.get("owner") != list(owner):
        raise ValueError("reconnect_owner_changed")
    pid, start = row["server_pid"], row["server_start"]
    if server_identity(pid, start) != trusted_server:
        raise ValueError("reconnect_server_changed")
    public_id = str(uuid.UUID(row["public_id"]))
    received = receive_environment("\\\\.\\pipe\\LOCAL\\lienzo-bootstrap-" + public_id, pid, start)
    if received.get("LIENZO_CLAUDE_BRIDGE_SESSION") != sid:
        raise ValueError("reconnect_session_mismatch")
    return received
