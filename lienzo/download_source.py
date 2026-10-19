"""Sólo la carpeta Descargas: inventario reciente y bloques con identidad estable."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
from pathlib import Path

import state
import xfer

CHUNK = 256 * 1024
_key = secrets.token_bytes(32)
_partial = (".crdownload", ".part", ".tmp", ".parte", ".parte.diario", ".download")


def folder() -> Path:
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            ) as key:
                path, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            return Path(os.path.expandvars(path))
        except FileNotFoundError:
            pass  # perfil sin redirección de Descargas: ubicación estándar de Windows
    return Path.home() / "Downloads"


def allowed_folder():
    root = folder()
    if xfer.permitido(str(root)) is None:
        raise PermissionError(f"La carpeta Descargas no está habilitada para transferir: {root}")
    return root


def _enable():
    """Autorización explícita: agrega sólo la carpeta Descargas real a copy_roots."""
    root = folder()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("No se encontró una carpeta Descargas válida")
    try:
        data = json.loads(Path(state.CONFIG_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("copy_roots", []), list):
        raise ValueError("La configuración de transferencias no es válida; no se modificó")  # noqa: TRY004
    if xfer.permitido(str(root)) is None:
        data["copy_roots"] = [*data.get("copy_roots", []), str(root)]
        state.atomic_write(state.CONFIG_FILE, json.dumps(data, ensure_ascii=False, indent=1))
    return {"folder": str(root), "enabled": True}


def enable():
    with state.lock:
        return _enable()


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _token(name, info):
    raw = json.dumps({"name": name, "fingerprint": fingerprint(info)}, ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(hmac.digest(_key, raw, "sha256") + raw).decode()


def _unpack(token):
    if not isinstance(token, str) or len(token) > 8192:
        raise ValueError("Identificador de descarga inválido")
    raw = base64.b64decode(token, altchars=b"-_", validate=True)
    if len(raw) <= 32 or not hmac.compare_digest(raw[:32], hmac.digest(_key, raw[32:], "sha256")):
        raise ValueError("La lista de descargas cambió; actualizala")
    data = json.loads(raw[32:])
    name = data["name"]
    if not isinstance(name, str) or not xfer.rel_ok(name) or "/" in name:
        raise ValueError("Nombre de descarga inválido")
    return data


def recent():
    root = allowed_folder()
    files = []
    with os.scandir(root) as entries:
        for entry in entries:
            if (
                not entry.is_file(follow_symlinks=False)
                or entry.name.lower().endswith(_partial)
                or entry.name.lower() == "desktop.ini"
                or not xfer.rel_ok(entry.name)
            ):
                continue
            # DirEntry.stat en Windows puede devolver identidad 0; stat real debe
            # coincidir con fstat del descriptor antes de leer contenido.
            info = os.stat(entry.path, follow_symlinks=False)
            if xfer.permitido(entry.path) is None:
                continue
            files.append(
                {
                    "name": entry.name,
                    "size": info.st_size,
                    "modified_ns": info.st_mtime_ns,
                    "token": _token(entry.name, info),
                }
            )
    files.sort(key=lambda entry: entry["modified_ns"], reverse=True)
    return {"folder": str(root), "files": files[:30]}


def read(data):
    root = allowed_folder()
    selection = _unpack(data.get("token"))
    offset = data.get("offset")
    if type(offset) is not int or not 0 <= offset <= selection["fingerprint"][2]:
        raise ValueError("Posición de descarga inválida")
    path = root / selection["name"]
    if xfer.permitido(str(path)) is None:
        raise PermissionError("La descarga está fuera de la carpeta autorizada")
    with path.open("rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or fingerprint(info) != selection["fingerprint"]:
            raise ValueError("La descarga cambió; actualizá la lista")
        file.seek(offset)
        raw = file.read(CHUNK)
        if fingerprint(os.fstat(file.fileno())) != selection["fingerprint"]:
            raise ValueError("La descarga cambió durante la lectura")
    return {"offset": offset, "data": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def dispatch(data):
    try:
        action = data.get("action")
        if action == "downloads-list":
            return 200, recent()
        if action == "downloads-read":
            return 200, read(data)
        if action == "downloads-enable":
            return 200, enable()
        return 400, {"error": "Acción de descargas inválida"}
    except PermissionError as exc:
        return 403, {"error": str(exc), "folder": str(folder()), "needs_permission": True}
    except (OSError, ValueError, KeyError) as exc:
        return 409, {"error": str(exc)}
