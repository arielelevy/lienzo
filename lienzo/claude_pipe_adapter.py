"""Child-only adapter. Claude token never leaves this process or enters files."""

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from pathlib import Path


def owner_handle(session_id):
    """Pin the currently registered Claude process; a recycled PID cannot revive it."""
    registry = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "sessions"
    for record in registry.glob("*.json"):
        try:
            row = json.loads(record.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        if row.get("sessionId") == session_id:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x101000, False, int(record.stem))
            if not handle:
                raise OSError("owner_process_unavailable")
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)
            ):
                kernel.CloseHandle(handle)
                raise OSError("owner_time_unavailable")
            start = (created.dwHighDateTime << 32) | created.dwLowDateTime
            if str(start) != str(row.get("procStart")):
                kernel.CloseHandle(handle)
                raise ValueError("owner_process_recycled")
            return kernel, handle
    raise ValueError("owner_not_registered")


def write_pipe(address, token, session_id, message_id, text, timeout_ms=3000):
    """Overlapped Windows write with bounded wait and cancellation; no delivery claim."""
    if os.name != "nt" or not address.startswith("\\\\.\\pipe\\LOCAL\\cc-msg-"):
        raise ValueError("unsupported_pipe")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(Overlapped),
    ]
    kernel.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(address, 0x40000000, 0, None, 3, 0x40000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "pipe_open_failed")
    event = kernel.CreateEventW(None, True, False, None)
    try:
        if not event:
            raise OSError(ctypes.get_last_error(), "event_failed")
        payload = (
            json.dumps({"type": "auth", "token": token})
            + "\n"
            + json.dumps(
                {
                    "msgV": 1,
                    "msg_id": message_id,
                    "type": "user",
                    "message": {"role": "user", "content": text},
                    "priority": "next",
                    "session_id": session_id,
                }
            )
            + "\n"
        ).encode()
        buffer = ctypes.create_string_buffer(payload)
        operation = Overlapped(hEvent=event)
        count = wintypes.DWORD()
        ok = kernel.WriteFile(handle, buffer, len(payload), ctypes.byref(count), ctypes.byref(operation))
        if not ok:
            if ctypes.get_last_error() != 997:
                raise OSError(ctypes.get_last_error(), "pipe_write_failed")
            if kernel.WaitForSingleObject(event, timeout_ms) != 0:
                kernel.CancelIoEx(handle, ctypes.byref(operation))
                kernel.GetOverlappedResult(handle, ctypes.byref(operation), ctypes.byref(count), True)
                raise TimeoutError("pipe_write_timeout")
            if not kernel.GetOverlappedResult(handle, ctypes.byref(operation), ctypes.byref(count), False):
                raise OSError(ctypes.get_last_error(), "pipe_result_failed")
        if count.value != len(payload):
            raise OSError("partial_pipe_write")
    finally:
        if event:
            kernel.CloseHandle(event)
        kernel.CloseHandle(handle)


def run_adapter(metadata):
    expected = os.environ["LIENZO_CLAUDE_BRIDGE_SESSION"]
    if metadata["session_id"] != expected:
        raise ValueError("session_mismatch")
    url = os.environ["LIENZO_CLAUDE_BRIDGE_URL"]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path:
        raise ValueError("bridge_not_loopback")
    secret = os.environ.pop("LIENZO_CLAUDE_BRIDGE_SECRET")
    token = os.environ.pop("CLAUDE_CODE_MESSAGING_TOKEN")
    address = os.environ["CLAUDE_CODE_MESSAGING_SOCKET"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(route, data):
        data["session_id"] = expected
        req = urllib.request.Request(
            url + route,
            json.dumps(data).encode(),
            {"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
        )
        with opener.open(req, timeout=4) as response:
            return json.load(response)

    kernel, owner = owner_handle(expected)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    ready = False
    try:
        # Poll failures terminate this private adapter; no reconnect/replay loop.
        while kernel.WaitForSingleObject(owner, 0) == 258:
            job = request("/poll", {"adapter_pid": os.getpid()})
            if job.get("stop"):
                return
            if not ready:
                print("claude_pipe_adapter_ready", flush=True)
                ready = True
            if not job:
                continue
            if kernel.WaitForSingleObject(owner, 0) != 258:
                return
            try:
                write_pipe(address, token, expected, job["id"], job["text"])
                status = "pipe_written"
            except OSError, ValueError, TimeoutError:
                status = "unknown"
            request("/result", {"id": job["id"], "status": status})
    finally:
        kernel.CloseHandle(owner)


def launch_adapter(metadata, timeout=8):
    """Success means the child authenticated its first poll, not merely Popen."""
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    responses = queue.Queue(maxsize=1)
    reader = threading.Thread(target=lambda: responses.put(child.stdout.readline(128)), daemon=True)
    reader.start()
    try:
        child.stdin.write(json.dumps(metadata).encode())
        child.stdin.close()
        try:
            response = responses.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("adapter_start_timeout") from None
        if response != b"claude_pipe_adapter_ready\n" and response != b"claude_pipe_adapter_ready\r\n":
            raise ValueError("adapter_start_failed")
    except BaseException:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        raise
    finally:
        reader.join(5)
        child.stdin.close()
        child.stdout.close()


def main():
    if sys.argv[1:2] == ["--bootstrap"] and len(sys.argv) != 6:
        raise ValueError("bootstrap_requires_server_identity")
    if len(sys.argv) == 6 and sys.argv[1] == "--bootstrap":
        from claude_pipe_bootstrap import receive_environment

        if not all(os.environ.get(key) for key in ("CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_MESSAGING_SOCKET")):
            raise ValueError("claude_messaging_environment_missing")
        public_id = str(uuid.UUID(sys.argv[2]))
        received = receive_environment(
            "\\\\.\\pipe\\LOCAL\\lienzo-bootstrap-" + public_id, int(sys.argv[4]), int(sys.argv[5])
        )
        if received.get("LIENZO_CLAUDE_BRIDGE_SESSION") != sys.argv[3]:
            raise ValueError("bootstrap_session_mismatch")
        os.environ.update(received)
        metadata = {"session_id": sys.argv[3]}
        launch_child = True
    else:
        metadata = json.load(sys.stdin)
        launch_child = sys.argv[1:] == ["--hook"]
    if launch_child:
        if metadata["session_id"] != os.environ.get("LIENZO_CLAUDE_BRIDGE_SESSION"):
            raise ValueError("session_mismatch")
        launch_adapter(metadata)
        return
    if sys.argv[1:] != ["--serve"]:
        raise ValueError("invalid_mode")
    run_adapter(metadata)


def cli():
    try:
        main()
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        # Do not print exception bodies: HTTP/environment errors can contain secrets.
        message = "claude_pipe_adapter_failed"
        if sys.argv[1:2] == ["--bootstrap"]:
            if isinstance(error, ValueError) and error.args == ("claude_messaging_environment_missing",):
                print(message + ": esta ejecución no heredó el canal de Claude. Ejecutá el comando desde una herramienta de esa conversación de Claude; abrir el canal en otra consola no lo conecta.", file=sys.stderr)
                return 2
            stale_identity = isinstance(error, ValueError) and error.args in (
                ("bootstrap_server_identity_mismatch",),
                ("bootstrap_server_recycled",),
                ("bootstrap_server_process_unavailable",),
            )
            missing_pipe = isinstance(error, OSError) and getattr(error, "winerror", None) in (2, 3, 109, 231)
            if stale_identity or missing_pipe or isinstance(error, TimeoutError):
                message += ": bootstrap vencido o servidor reiniciado. Generá un comando nuevo con «Conectar esta sesión Claude» y ejecutalo en esa conversación de Claude."
            else:
                message += ": no se pudo validar la conexión. Generá un comando nuevo con «Conectar esta sesión Claude» y ejecutalo en esa conversación de Claude."
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli())
