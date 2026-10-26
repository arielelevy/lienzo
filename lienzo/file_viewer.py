"""Lectura acotada de archivos para el visor web, sin ejecutar contenido."""

import os
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


def read_file(raw: str, roots: list[str]) -> tuple[int, dict]:
    try:
        path = Path(raw).resolve(strict=True)
        allowed = False
        for root in roots:
            base = Path(root).resolve()
            if path.is_relative_to(base):
                allowed = True
                break
        if not allowed:
            return 403, {"error": "Archivo fuera de las carpetas habilitadas"}
        if not path.is_file():
            return 400, {"error": "La ruta no es un archivo"}
        with path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return 413, {"error": "El archivo supera los 2 MiB del visor"}
        if b"\x00" in data:
            return 415, {"error": "El visor admite archivos de texto"}
        text = data.decode("utf-8-sig")
        return 200, {"path": os.fspath(path), "text": text, "markdown": path.suffix.lower() in (".md", ".markdown")}
    except (OSError, ValueError, UnicodeError):
        return 404, {"error": "No se pudo leer el archivo como texto UTF-8"}
