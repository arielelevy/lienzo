"""Clave OpenRouter privada: DPAPI del usuario en Windows, 0600 en POSIX."""

from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path

import state


def path() -> Path:
    return Path(state.LIENZO) / "private" / ("jev.dpapi" if os.name == "nt" else "jev.key")


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
    else:
        fn = crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("no se pudo proteger/abrir la credencial con DPAPI")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def store(key: str) -> None:
    if not isinstance(key, str) or not key.strip() or len(key) > 4096 or any(c.isspace() for c in key):
        raise ValueError("credencial invalida")
    payload = key.encode()
    if os.name == "nt":
        payload = _dpapi(payload)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load() -> str:
    target = path()
    if not target.is_file():
        raise ValueError("Jev no tiene credencial en esta PC")
    if os.name != "nt" and target.stat().st_mode & 0o077:
        raise ValueError("la credencial debe tener permisos 0600")
    data = target.read_bytes()
    if os.name == "nt":
        data = _dpapi(data, decrypt=True)
    key = data.decode("utf-8")
    if not key or len(key) > 4096 or any(c.isspace() for c in key):
        raise ValueError("credencial Jev invalida")
    return key


def available() -> bool:
    # Solo presencia: no descifrar un secreto ni hacer red por cada GET.
    return path().is_file()
