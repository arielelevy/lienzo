from types import SimpleNamespace

from lienzo import startup_update as updater


def run_results(monkeypatch, results):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(returncode=result[0], stdout=result[1], stderr="")

    monkeypatch.setattr(updater.subprocess, "run", run)
    return calls


def test_current_checkout_does_not_build(monkeypatch):
    calls = run_results(monkeypatch, [(0, "old"), (0, ""), (0, "")])
    assert updater.update() == 0
    assert calls[1][0] == ["git", "pull", "--ff-only"]
    assert len(calls) == 3


def test_failed_pull_keeps_local_version_and_reports(monkeypatch, capsys):
    calls = run_results(monkeypatch, [(0, "old"), (1, "")])
    assert updater.update() == 0
    assert len(calls) == 2
    assert "git pull falló (código 1)" in capsys.readouterr().out


def test_updated_web_builds_and_propagates_failure(tmp_path, monkeypatch, capsys):
    (tmp_path / "web").mkdir()
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    calls = run_results(monkeypatch, [(0, "old"), (0, ""), (0, "web/src/App.tsx"), (7, "")])
    assert updater.update() == 7
    assert calls[-1][1]["cwd"] == updater.ROOT / "web"
    assert "no arranco" in capsys.readouterr().out
    assert (tmp_path / "web" / ".startup-build-pending").exists()
    run_results(monkeypatch, [(0, "new"), (0, ""), (0, ""), (0, "")])
    assert updater.update() == 0
    assert not (tmp_path / "web" / ".startup-build-pending").exists()


def test_missing_git_stops_with_visible_error(monkeypatch, capsys):
    run_results(monkeypatch, [FileNotFoundError("git")])
    assert updater.update() == 1
    assert "no se pudo actualizar" in capsys.readouterr().out


def test_real_git_pull_updates_checkout(tmp_path, monkeypatch):
    import subprocess

    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    checkout = tmp_path / "checkout"

    def git(*args, cwd=tmp_path):
        return subprocess.run(
            ["git", *map(str, args)], cwd=cwd, check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True
        )

    git("init", "--bare", remote)
    git("clone", remote, source)
    git("config", "user.email", "test@example.invalid", cwd=source)
    git("config", "user.name", "Startup test", cwd=source)
    (source / "version.txt").write_text("old")
    git("add", "version.txt", cwd=source)
    git("commit", "-m", "initial", cwd=source)
    git("push", "origin", "HEAD", cwd=source)
    git("clone", remote, checkout)
    (source / "version.txt").write_text("new")
    git("commit", "-am", "update", cwd=source)
    git("push", "origin", "HEAD", cwd=source)
    monkeypatch.setattr(updater, "ROOT", checkout)
    assert updater.update() == 0
    assert (checkout / "version.txt").read_text() == "new"
