import os

import launch
from lienzo import server


def test_vscode_rejects_unallowed_directory(monkeypatch):
    monkeypatch.setattr(launch, "_allowed_roots", lambda: [])
    assert launch.open_vscode("D:/outside")["ok"] is False


def test_vscode_literal_path_and_missing_install(tmp_path, monkeypatch):
    project = tmp_path / "project & space"
    project.mkdir()
    exe = tmp_path / "Code.exe"
    exe.write_text("")
    monkeypatch.setattr(launch, "_allowed_roots", lambda: [os.path.normcase(str(tmp_path))])
    monkeypatch.setattr(launch.shutil, "which", lambda _: str(exe))
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv: calls.append(argv))
    assert launch.open_vscode(str(project)) == {"ok": True}
    assert calls == [[str(exe), "--new-window", str(project)]]
    exe.unlink()
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert launch.open_vscode(str(project))["error"] == "No encuentro VS Code en esta PC"


def test_vscode_api_local_and_remote(monkeypatch):
    monkeypatch.setattr(server.identity, "pc_id", lambda: "local")
    monkeypatch.setattr(launch, "open_vscode", lambda cwd: {"ok": True, "cwd": cwd})
    body = {"cwd": "D:/project", "agent": "vscode"}
    assert server.accion_launch(body, desde_tablero=True) == (200, {"ok": True, "cwd": "D:/project"})
    assert server.accion_launch({**body, "distro": "Ubuntu"}, desde_tablero=True)[0] == 400
    calls = []
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *args: calls.append(args) or (200, {"ok": True}))
    assert server.accion_launch({**body, "pc": "remote"}, desde_tablero=True)[0] == 200
    assert calls == [("remote", "POST", "/launch", {**body, "title": ""})]
