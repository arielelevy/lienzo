"""Read-only Windows presence ownership; fail closed on uncertainty or PID reuse."""

import ctypes as ct
import ctypes.wintypes as wt
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

MAX_LOCKS = 256
SUPPORTED_EXE_SHA256 = "b9ebbc8ae00dec96263979d2947124136cdae990811e27eafef1e7f021269192"
MAX_EXE_BYTES = 512 * 1024 * 1024


class IdentityError(ValueError):
    pass


def file_token(path):
    try:
        resolved = path.resolve(strict=True)
    except RuntimeError:
        raise IdentityError("redirected_path") from None
    if resolved != path.absolute():
        raise IdentityError("redirected_path")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise IdentityError("unsafe_file")
    if not info.st_ino:
        raise IdentityError("missing_file_identity")
    return info.st_dev, info.st_ino


def _compatible_executable(image):
    path = Path(image)
    token = file_token(path)
    if path.stat().st_size > MAX_EXE_BYTES:
        raise IdentityError("unsupported_executable")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_EXE_BYTES:
                raise IdentityError("unsupported_executable")
            digest.update(chunk)
    if file_token(path) != token or digest.hexdigest() != SUPPORTED_EXE_SHA256:
        raise IdentityError("unsupported_executable")


def _start_microseconds(started):
    try:
        value = datetime.fromisoformat(started)
        if value.tzinfo is None:
            raise ValueError
        delta = value.astimezone(UTC) - datetime(1601, 1, 1, tzinfo=UTC)
        return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    except AttributeError, TypeError, ValueError:
        raise IdentityError("missing_process_start") from None


class _IoStatus(ct.Structure):
    _fields_ = [("status", ct.c_void_p), ("information", ct.c_size_t)]


class NativeProbe:
    """Pins a process while asking NT for the PIDs owning a presence file."""

    def __init__(self, pid):
        if os.name != "nt":
            raise IdentityError("unsupported_platform")
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.nt = ct.WinDLL("ntdll")
        k = self.kernel
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcess.restype = wt.HANDLE
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
        k.CreateFileW.restype = wt.HANDLE
        k.GetProcessTimes.argtypes = [wt.HANDLE] + [ct.POINTER(wt.FILETIME)] * 4
        k.GetExitCodeProcess.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)]
        self.nt.NtQueryInformationFile.argtypes = [wt.HANDLE, ct.POINTER(_IoStatus), ct.c_void_p, wt.ULONG, wt.DWORD]
        self.nt.NtQueryInformationFile.restype = ct.c_long
        self.handle = k.OpenProcess(0x1000, False, pid)
        if not self.handle:
            raise IdentityError("process_unavailable")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.kernel.CloseHandle(self.handle)

    def process(self):
        created, exited, system, user = (wt.FILETIME() for _ in range(4))
        code, size = wt.DWORD(), wt.DWORD(32768)
        image = ct.create_unicode_buffer(size.value)
        k = self.kernel
        if not (
            k.GetProcessTimes(self.handle, ct.byref(created), ct.byref(exited), ct.byref(system), ct.byref(user))
            and k.GetExitCodeProcess(self.handle, ct.byref(code))
            and code.value == 259
            and k.QueryFullProcessImageNameW(self.handle, 0, image, ct.byref(size))
        ):
            raise IdentityError("process_unavailable")
        return (created.dwHighDateTime << 32) | created.dwLowDateTime, str(Path(image.value).resolve())

    def owners(self, path):
        handle = self.kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
        if handle == ct.c_void_p(-1).value:
            raise IdentityError("presence_unavailable")
        try:
            buffer, io = ct.create_string_buffer(16384), _IoStatus()
            status = self.nt.NtQueryInformationFile(handle, ct.byref(io), buffer, len(buffer), 47)
            if status != 0:
                raise IdentityError("presence_query_failed")
            count = ct.cast(buffer, ct.POINTER(wt.ULONG))[0]
            offset = ct.sizeof(ct.c_size_t)
            if count > (len(buffer) - offset) // ct.sizeof(ct.c_size_t):
                raise IdentityError("presence_owner_limit")
            owners = ct.cast(ct.addressof(buffer) + offset, ct.POINTER(ct.c_size_t))
            return {owners[i] for i in range(count)} - {os.getpid()}
        finally:
            self.kernel.CloseHandle(handle)


@dataclass(frozen=True)
class Identity:
    pid: int
    started: int
    image: str
    cascade: str
    database: Path
    lock_token: tuple
    database_token: tuple


def resolve(session, *, root=None, probe_factory=NativeProbe):
    try:
        pid = session.get("pid")
        if type(pid) is not int or pid <= 0 or session.get("orphan"):
            raise IdentityError("missing_process")
        expected = _start_microseconds(session.get("started"))
        base = Path(root) if root is not None else Path.home() / ".gemini/antigravity-cli"
        for directory in (base, base / "presence", base / "conversations"):
            info = directory.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
                or directory.resolve(strict=True) != directory.absolute()
            ):
                raise IdentityError("unsafe_directory")
        locks = []
        for path in (base / "presence").iterdir():
            if path.suffix != ".lock":
                continue
            if len(locks) >= MAX_LOCKS:
                raise IdentityError("presence_limit")
            try:
                if str(UUID(path.stem)) != path.stem:
                    raise ValueError
            except ValueError:
                raise IdentityError("invalid_presence_name") from None
            locks.append(path)
        with probe_factory(pid) as probe:
            start, image = probe.process()
            image_path = Path(image)
            official_dir = Path.home() / "AppData/Local/agy/bin"
            # The updater renames the running image; its known hash is still mandatory.
            if (
                start // 10 != expected
                or os.path.normcase(str(image_path.parent)) != os.path.normcase(str(official_dir))
                or re.fullmatch(r"agy\.exe(?:\.[0-9]{1,20}\.old)?", image_path.name, re.IGNORECASE) is None
            ):
                raise IdentityError("process_identity_mismatch")
            _compatible_executable(image)
            matches = []
            for path in locks:
                token = file_token(path)
                owners = probe.owners(path)
                if token != file_token(path):
                    raise IdentityError("presence_rotated")
                if pid in owners:
                    if owners != {pid}:
                        raise IdentityError("ambiguous_owners")
                    matches.append((path, token))
            if len(matches) != 1:
                raise IdentityError("ambiguous_conversation" if matches else "missing_presence")
            if probe.process() != (start, image):
                raise IdentityError("process_changed")
            path, token = matches[0]
            database = base / "conversations" / (path.stem + ".db")
            return Identity(pid, start, image, path.stem, database, token, file_token(database))
    except OSError:
        raise IdentityError("identity_io_unavailable") from None
