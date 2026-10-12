"""Instala RTK fijo en LIENZO_HOME/bin y habilita las preferencias autorizadas."""

import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import agent_improvements
import state

VERSION = "0.51.0"
SHA256 = "1623e9b45d28b15122d69e7314776e1123a804224885ce07e7182fb40080f05c"
URL = f"https://github.com/rtk-ai/rtk/releases/download/v{VERSION}/rtk-x86_64-pc-windows-msvc.zip"


def binary_from_archive(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("el hash de RTK no coincide con la publicacion oficial")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [name for name in archive.namelist() if name.rsplit("/", 1)[-1] == "rtk.exe"]
        if len(members) != 1 or archive.getinfo(members[0]).file_size > 60_000_000:
            raise ValueError("archivo RTK inesperado")
        # Leer solo el ejecutable; nunca extractall con rutas del ZIP.
        return archive.read(members[0])


def install() -> dict:
    if os.name != "nt":
        raise ValueError("este instalador es Windows x64; WSL requiere su propio RTK")
    with urllib.request.urlopen(URL, timeout=60) as response:
        raw = response.read(30_000_001)
    if len(raw) > 30_000_000:
        raise ValueError("descarga de RTK demasiado grande")
    data = binary_from_archive(raw)
    root = Path(state.LIENZO) / "bin"
    root.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, root / "rtk.exe")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    status = agent_improvements.configure({"brief": True, "rtk": True})
    return {"ok": True, "rtk_version": VERSION, "status": status}


if __name__ == "__main__":
    print(json.dumps(install(), ensure_ascii=False))
