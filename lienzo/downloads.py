"""Traer descargas con selección explícita y protección de archivos existentes."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
from pathlib import Path

import browser_api
import download_source as source
import identity
import xfer

_plans = {}
_jobs = {}
_lock = threading.RLock()
_receiving = threading.Lock()


def _call(pc, action, **data):
    code, result = browser_api.dispatch({"pc": pc, "action": "downloads-" + action, **data})
    if code != 200:
        raise DownloadError(code, result)
    return result


class DownloadError(Exception):
    def __init__(self, code, data):
        super().__init__(data.get("error", "No se pudo transferir la descarga"))
        self.code, self.data = code, data


def _local_info(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if path.is_symlink() or not path.is_file():
        # en el destino hay una carpeta (u otra cosa) con ese nombre: no es un archivo que se
        # pueda traer encima, pero no tiene que tirar abajo el preview de las demás descargas
        return None
    if xfer.permitido(str(path)) is None:
        raise ValueError(f"El destino no es un archivo permitido: {path.name}")
    return source.fingerprint(info)


def preview(pc):
    if not isinstance(pc, str) or not pc or pc == identity.pc_id():
        return 400, {"error": "Elegí otra PC para traer sus descargas"}
    try:
        remote = _call(pc, "list")
        root = source.allowed_folder()
        rows = []
        for file in remote["files"]:
            name = file["name"]
            if not xfer.rel_ok(name) or "/" in name or type(file["size"]) is not int or file["size"] < 0:
                raise ValueError("La otra PC devolvió un archivo inválido")
            local = _local_info(root / name)
            rows.append({**file, "id": secrets.token_hex(8), "local": local, "exists": local is not None})
        pid = secrets.token_hex(16)
        with _lock:
            now = time.monotonic()
            for old in list(_plans):
                if now - _plans[old]["created"] > 900:
                    del _plans[old]
            if len(_plans) >= 100:
                raise ValueError("Hay demasiadas listas abiertas; cerrá alguna y volvé a intentar")
            _plans[pid] = {"pc": pc, "root": str(root), "rows": rows, "created": now}
        return 200, {
            "plan": pid,
            "source": remote["folder"],
            "destination": str(root),
            "files": [{k: v for k, v in row.items() if k not in ("token", "local")} for row in rows],
        }
    except DownloadError as exc:
        return exc.code, exc.data
    except PermissionError as exc:
        return 403, {"error": str(exc), "needs_local_permission": True}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return 409, {"error": str(exc)}


def enable(pc):
    if not isinstance(pc, str) or not pc or pc == identity.pc_id():
        return 400, {"error": "Elegí otra PC para habilitar sus descargas"}
    try:
        result = _call(pc, "enable")
        source.enable()
        return 200, result
    except DownloadError as exc:
        return exc.code, exc.data
    except (OSError, ValueError) as exc:
        return 409, {"error": str(exc)}


def start(data):
    try:
        with _lock:
            plan = _plans.get(data.get("plan"))
            if plan is None or time.monotonic() - plan["created"] > 900:
                raise ValueError("La lista venció; actualizá las descargas")
            ids, replace = data.get("files"), data.get("replace", [])
            if (
                not isinstance(ids, list)
                or not ids
                or len(ids) > 30
                or not all(isinstance(i, str) for i in ids)
                or not isinstance(replace, list)
                or not all(isinstance(i, str) for i in replace)
            ):
                raise ValueError("Elegí los archivos que querés traer")
            selected = [row for row in plan["rows"] if row["id"] in ids]
            if len(selected) != len(set(ids)) or set(replace) - set(ids):
                raise ValueError("La selección no corresponde a esta lista")
            for row in selected:
                current = _local_info(Path(plan["root"]) / row["name"])
                if current != row["local"] or current is not None and row["id"] not in replace:
                    return 409, {
                        "error": f"Confirmá antes de sobrescribir {row['name']}; si cambió, actualizá la lista",
                        "conflict": True,
                    }
            jid = secrets.token_hex(12)
            if len(_jobs) >= 100:
                for old in list(_jobs):
                    if _jobs[old]["state"] in ("received", "error"):
                        del _jobs[old]
                        break
                else:
                    return 429, {"error": "Hay demasiadas transferencias en curso"}
            _jobs[jid] = {
                "id": jid,
                "state": "waiting",
                "bytes": 0,
                "total": sum(row["size"] for row in selected),
                "files": [{"name": row["name"], "state": "pending"} for row in selected],
                "error": None,
            }
            del _plans[data["plan"]]  # una selección no se ejecuta dos veces por doble click
        threading.Thread(target=_receive, args=(jid, plan, selected, set(replace)), daemon=True).start()
        return 202, {"id": jid}
    except (OSError, ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}


def _receive(jid, plan, rows, replace):
    with _receiving:
        with _lock:
            job = _jobs[jid]
            job["state"] = "copying"
        for index, row in enumerate(rows):
            path = Path(plan["root"]) / row["name"]
            temporary = path.parent / (".lienzo-download-" + secrets.token_hex(12) + ".part")
            try:
                if xfer.permitido(str(path)) is None:
                    raise PermissionError("Se revocó el permiso del destino")
                offset = 0
                with temporary.open("xb") as file:
                    while offset < row["size"] or row["size"] == 0 and offset == 0:
                        result = _call(plan["pc"], "read", token=row["token"], offset=offset)
                        if not isinstance(result.get("data"), str) or len(result["data"]) > 4 * (source.CHUNK // 3 + 1):
                            raise ValueError("El bloque recibido supera el límite de descarga")
                        raw = base64.b64decode(result["data"], validate=True)
                        if (
                            result["offset"] != offset
                            or hashlib.sha256(raw).hexdigest() != result["sha256"]
                            or len(raw) > source.CHUNK
                            or offset + len(raw) > row["size"]
                            or not raw
                            and offset < row["size"]
                        ):
                            raise ValueError("No se pudo verificar el contenido de la descarga")
                        file.write(raw)
                        offset += len(raw)
                        with _lock:
                            job["bytes"] += len(raw)
                        if row["size"] == 0:
                            break
                    file.flush()
                    os.fsync(file.fileno())
                if _local_info(path) != row["local"]:
                    raise ValueError("El archivo local cambió; no se sobrescribió. Actualizá la lista")
                if row["local"] is not None and row["id"] in replace:
                    os.replace(temporary, path)
                else:
                    os.link(temporary, path)  # creación exclusiva: nunca pisa un destino aparecido tarde
                with _lock:
                    job["files"][index]["state"] = "received"
            except (DownloadError, OSError, ValueError, KeyError, TypeError) as exc:
                with _lock:
                    job["files"][index].update({"state": "error", "error": str(exc)})
                    job["error"] = str(exc)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    with _lock:
                        job["error"] = f"No se pudo limpiar el temporal {temporary.name}: {exc}"
        with _lock:
            job["state"] = "error" if job["error"] else "received"


def status(jid):
    with _lock:
        job = _jobs.get(jid)
        return (
            (200, {**job, "files": [dict(file) for file in job["files"]]})
            if job
            else (404, {"error": "No existe esa transferencia"})
        )
