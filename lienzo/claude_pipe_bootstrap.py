"""One-shot Windows bootstrap: public address, private credential, verified Claude child."""

import ctypes
import json
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes as wt
from pathlib import Path

import procinfo


def kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = [
        wt.LPCWSTR,
        wt.DWORD,
        wt.DWORD,
        wt.DWORD,
        wt.DWORD,
        wt.DWORD,
        wt.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CreateNamedPipeW.restype = wt.HANDLE
    kernel.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    kernel.CreateFileW.restype = wt.HANDLE
    kernel.ConnectNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p]
    kernel.DisconnectNamedPipe.argtypes = [wt.HANDLE]
    kernel.GetNamedPipeClientProcessId.argtypes = [wt.HANDLE, ctypes.POINTER(wt.ULONG)]
    kernel.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.SetNamedPipeHandleState.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    kernel.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
    return kernel


def process_start(kernel, handle):
    times = [wt.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def user_security(kernel):
    """Explicit protected DACL: current user only; never use Windows' default pipe ACL."""
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wt.LPCWSTR,
        wt.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wt.DWORD),
    ]
    token = wt.HANDLE()
    if not adv.OpenProcessToken(wt.HANDLE(-1), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_string = wt.LPWSTR()
    descriptor = ctypes.c_void_p()
    try:
        size = wt.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise ctypes.WinError(ctypes.get_last_error())
        sddl = f"D:P(A;;GRGW;;;{sid_string.value})"
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return descriptor
    finally:
        if sid_string:
            kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
        kernel.CloseHandle(token)


def verified_child(client_pid, session_id):
    """Pin every ancestor and enforce creation ordering and the live session registry."""
    kernel = kernel_api()
    registry = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "sessions"
    handles = []
    previous_start = None
    visited = set()
    try:
        pid = client_pid
        for _ in range(32):
            if not pid or pid in visited:
                return False
            visited.add(pid)
            handle = procinfo.open_process(pid, 0x101000)
            if not handle:
                return False
            handles.append(handle)
            start = process_start(kernel, handle)
            if previous_start is not None and start > previous_start:
                return False
            previous_start = start
            exe = procinfo.image_path(pid)
            if not exe:
                return False
            record = registry / f"{pid}.json"
            if Path(exe).name.lower() == "claude.exe" and record.exists():
                row = json.loads(record.read_text(encoding="utf-8"))
                if row.get("sessionId") == session_id and str(row.get("procStart")) == str(start):
                    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
                    return len(handles) > 1 and kernel.WaitForSingleObject(handle, 0) == 258
            pid, _ = procinfo.proc_info(pid)
        return False
    finally:
        for handle in handles:
            procinfo.close_handle(handle)


class ClaudePipeBootstrap:
    """Owns one bounded listener. No credentials are put in the command or transcript."""

    def __init__(self, bridge, timeout=60):
        if os.name != "nt" or not 0 < timeout <= 120:
            raise ValueError("unsupported_bootstrap")
        self.bridge = bridge
        self.address = "\\\\.\\pipe\\LOCAL\\lienzo-bootstrap-" + str(uuid.uuid4())
        self.public_id = self.address.removeprefix("\\\\.\\pipe\\LOCAL\\lienzo-bootstrap-")
        self.result = "listening"
        self.rejected = 0
        self.error = None
        self.client_pid = None
        self._stop = threading.Event()
        self._kernel = kernel_api()
        self.server_pid = os.getpid()
        server_handle = procinfo.open_process(self.server_pid)
        if not server_handle:
            raise OSError("bootstrap_server_process_unavailable")
        try:
            self.server_start = process_start(self._kernel, server_handle)
        finally:
            procinfo.close_handle(server_handle)

        class Security(ctypes.Structure):
            _fields_ = [("length", wt.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wt.BOOL)]

        descriptor = user_security(self._kernel)
        security = Security(ctypes.sizeof(Security), descriptor, False)
        try:
            self._handle = self._kernel.CreateNamedPipeW(
                self.address, 3 | 0x80000, 1 | 8, 1, 65536, 65536, 0, ctypes.byref(security)
            )
        finally:
            self._kernel.LocalFree(descriptor)
        if self._handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._thread = threading.Thread(target=self._serve, args=(timeout,), daemon=True)
        self._thread.start()

    def command(self, powershell=False):
        """Public command; no bridge or Claude credential in argv."""
        script = Path(__file__).with_name("claude_pipe_adapter.py").as_posix()
        python = Path(sys.executable).as_posix()
        identity = f"{self.public_id} {self.bridge.session_id} {self.server_pid} {self.server_start}"
        if powershell:
            python = python.replace("'", "''")
            script = script.replace("'", "''")
            return f"& '{python}' '{script}' --bootstrap {identity}"
        return f'"{python}" "{script}" --bootstrap {identity}'

    def hook_settings(self):
        """Per-launch settings contain only the public bootstrap command."""
        return {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": self.command(), "timeout": 10}]}]}}

    @property
    def closed(self):
        return not self._thread.is_alive()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _serve(self, timeout):
        deadline = time.monotonic() + timeout
        kernel = self._kernel
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                connected = kernel.ConnectNamedPipe(self._handle, None)
                code = ctypes.get_last_error()
                if not connected and code not in (535,):
                    if code not in (536, 232):
                        raise ctypes.WinError(code)
                    if code == 232:
                        kernel.DisconnectNamedPipe(self._handle)
                    self._stop.wait(0.02)
                    continue
                pid = wt.ULONG()
                if not kernel.GetNamedPipeClientProcessId(self._handle, ctypes.byref(pid)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not verified_child(pid.value, self.bridge.session_id):
                    self.rejected += 1
                    kernel.DisconnectNamedPipe(self._handle)
                    continue
                self.client_pid = pid.value
                payload = json.dumps(self.bridge.environment()).encode() + b"\n"
                count = wt.DWORD()
                buffer = ctypes.create_string_buffer(payload)
                if not kernel.WriteFile(self._handle, buffer, len(payload), ctypes.byref(count), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if count.value != len(payload):
                    raise OSError("bootstrap_partial_write")
                # Keep buffer alive until client acknowledges; no blocking flush.
                ack = ctypes.create_string_buffer(1)
                while not self._stop.is_set() and time.monotonic() < deadline:
                    if kernel.ReadFile(self._handle, ack, 1, ctypes.byref(count), None) and count.value == 1:
                        if ack.raw != b"!":
                            raise ValueError("invalid_bootstrap_ack")
                        self.result = "transferred"
                        return
                    if ctypes.get_last_error() not in (232, 536):
                        raise ctypes.WinError(ctypes.get_last_error())
                    self._stop.wait(0.02)
                self.result = "unknown"
                return
            self.result = "closed" if self._stop.is_set() else "timeout"
        except (OSError, ValueError) as exc:
            self.error = getattr(exc, "winerror", None) or type(exc).__name__
            self.result = "error"
        finally:
            kernel.DisconnectNamedPipe(self._handle)
            kernel.CloseHandle(self._handle)

    def close(self):
        self._stop.set()
        self._thread.join(3)
        if self._thread.is_alive():
            raise TimeoutError("bootstrap_listener_did_not_close")


def receive_environment(address, server_pid, server_start, timeout=5):
    """Called only by the receiving session's own child; values remain in memory."""
    if not address.startswith("\\\\.\\pipe\\LOCAL\\lienzo-bootstrap-"):
        raise ValueError("invalid_bootstrap_address")
    kernel = kernel_api()
    handle = kernel.CreateFileW(address, 0xC0000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        kernel.GetNamedPipeServerProcessId.argtypes = [wt.HANDLE, ctypes.POINTER(wt.ULONG)]
        actual_pid = wt.ULONG()
        if not kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(actual_pid)):
            raise ctypes.WinError(ctypes.get_last_error())
        if actual_pid.value != server_pid:
            raise ValueError("bootstrap_server_identity_mismatch")
        server_handle = procinfo.open_process(server_pid)
        if not server_handle:
            raise OSError("bootstrap_server_process_unavailable")
        try:
            if process_start(kernel, server_handle) != server_start:
                raise ValueError("bootstrap_server_recycled")
        finally:
            procinfo.close_handle(server_handle)
        mode = wt.DWORD(1)
        if not kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(8192)
        count = wt.DWORD()
        result = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                result += buffer.raw[: count.value]
                if len(result) > 8192:
                    raise ValueError("bootstrap_oversized")
                if result.endswith(b"\n"):
                    data = json.loads(result)
                    if not isinstance(data, dict):
                        raise TypeError("bootstrap_invalid_json")
                    ack = ctypes.create_string_buffer(b"!")
                    if not kernel.WriteFile(handle, ack, 1, ctypes.byref(count), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    return data
            elif ctypes.get_last_error() not in (232, 536):
                raise ctypes.WinError(ctypes.get_last_error())
            time.sleep(0.02)
        raise TimeoutError("bootstrap_read_timeout")
    finally:
        kernel.CloseHandle(handle)
