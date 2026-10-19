"""Descargas aisladas: no lee ni modifica carpetas reales del usuario."""

import base64
import hashlib
import json
import time

import download_source as source
import downloads
import pytest
import state


@pytest.fixture
def folder(tmp_path, monkeypatch):
    root = tmp_path / "Downloads"
    root.mkdir()
    monkeypatch.setattr(source, "folder", lambda: root)
    monkeypatch.setattr(downloads, "_plans", {})
    monkeypatch.setattr(downloads, "_jobs", {})
    monkeypatch.setattr(downloads.identity, "pc_id", lambda: "local")
    source.enable()
    return root


def finished(jid):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = downloads.status(jid)[1]
        if result["state"] in ("received", "error"):
            return result
        time.sleep(0.01)
    pytest.fail("la descarga no terminó")


def remote(monkeypatch, files, hook=None):
    def call(pc, action, **data):
        if action == "list":
            return {
                "folder": "REMOTE/Downloads",
                "files": [
                    {"name": name, "size": len(raw), "token": name, "modified_ns": 1} for name, raw in files.items()
                ],
            }
        if action == "read":
            if hook:
                hook()
            raw = files[data["token"]][data["offset"] : data["offset"] + source.CHUNK]
            return {
                "offset": data["offset"],
                "data": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        raise AssertionError(action)

    monkeypatch.setattr(downloads, "_call", call)


def test_lista_recientes_no_incluye_incompletos_y_rechaza_token_alterado(folder):
    (folder / "nota.pdf").write_bytes(b"gemini")
    (folder / "en-curso.crdownload").write_bytes(b"partial")
    (folder / "temporal.part").write_bytes(b"partial")
    files = source.recent()["files"]
    assert [file["name"] for file in files] == ["nota.pdf"]
    code, data = source.dispatch({"action": "downloads-read", "token": files[0]["token"], "offset": 0})
    assert code == 200 and base64.b64decode(data["data"]) == b"gemini"
    assert source.dispatch({"action": "downloads-read", "token": "x" + files[0]["token"][1:], "offset": 0})[0] == 409


def test_source_cambiado_no_se_lee_con_token_viejo(folder):
    path = folder / "nota.txt"
    path.write_bytes(b"before")
    token = source.recent()["files"][0]["token"]
    path.write_bytes(b"after-changed")
    assert source.dispatch({"action": "downloads-read", "token": token, "offset": 0})[0] == 409


def test_habilitar_solo_downloads_preserva_configuracion_y_rechaza_config_rota(folder):
    cfg = {"copy_roots": [], "launch_roots": ["D:/Apps"], "other": 42}
    from pathlib import Path

    path = Path(state.CONFIG_FILE)
    path.write_text(json.dumps(cfg))
    source.enable()
    saved = json.loads(path.read_text())
    assert saved == {**cfg, "copy_roots": [str(folder)]}
    path.write_text("[broken")
    with pytest.raises(ValueError):
        source.enable()
    assert path.read_text() == "[broken"


def test_traer_nuevo_fragmentado_y_vacio_sin_pisar(folder, monkeypatch):
    remote(monkeypatch, {"nota.pdf": b"a" * (source.CHUNK + 17), "vacio.txt": b""})
    code, preview = downloads.preview("remote")
    assert code == 200 and not any(file["exists"] for file in preview["files"])
    code, job = downloads.start({"plan": preview["plan"], "files": [file["id"] for file in preview["files"]]})
    assert code == 202
    assert finished(job["id"])["state"] == "received"
    assert (folder / "nota.pdf").read_bytes() == b"a" * (source.CHUNK + 17)
    assert (folder / "vacio.txt").read_bytes() == b""
    assert not list(folder.glob("*.part"))
    assert downloads.start({"plan": preview["plan"], "files": [preview["files"][0]["id"]]})[0] == 400


def test_existente_requiere_confirmacion_explicita(folder, monkeypatch):
    path = folder / "nota.pdf"
    path.write_bytes(b"local")
    remote(monkeypatch, {"nota.pdf": b"remote"})
    _, preview = downloads.preview("remote")
    file = preview["files"][0]
    assert file["exists"]
    data = {"plan": preview["plan"], "files": [file["id"]]}
    assert downloads.start(data)[0] == 409
    assert path.read_bytes() == b"local"
    code, job = downloads.start({**data, "replace": [file["id"]]})
    assert code == 202 and finished(job["id"])["state"] == "received"
    assert path.read_bytes() == b"remote"


def test_cambio_local_durante_copia_se_preserva(folder, monkeypatch):
    path = folder / "nota.pdf"
    path.write_bytes(b"local")
    remote(monkeypatch, {"nota.pdf": b"remote"}, hook=lambda: path.write_bytes(b"edicion-nueva"))
    _, preview = downloads.preview("remote")
    file = preview["files"][0]
    code, job = downloads.start({"plan": preview["plan"], "files": [file["id"]], "replace": [file["id"]]})
    assert code == 202 and finished(job["id"])["state"] == "error"
    assert path.read_bytes() == b"edicion-nueva"


def test_nombre_fuera_de_descargas_y_destino_aparecido_tarde_se_rechazan(folder, monkeypatch):
    remote(monkeypatch, {"../afuera.txt": b"bad"})
    assert downloads.preview("remote")[0] == 409
    remote(monkeypatch, {"nota.pdf": b"remote"})
    _, preview = downloads.preview("remote")
    (folder / "nota.pdf").write_bytes(b"archivo nuevo local")
    assert downloads.start({"plan": preview["plan"], "files": [preview["files"][0]["id"]]})[0] == 409
    assert (folder / "nota.pdf").read_bytes() == b"archivo nuevo local"
