"""Git real en repositorios temporales: nunca actualiza ni reinicia el Lienzo del usuario."""

import json
import subprocess

import pytest

from lienzo.updates import UpdateError, Updater


@pytest.fixture
def repo(tmp_path):
    def git(cwd, *args):
        return subprocess.run(
            ["git", *map(str, args)], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()

    origin, source, checkout = (tmp_path / name for name in ("origin.git", "source", "checkout"))
    git(tmp_path, "init", "--bare", "--initial-branch=main", origin)
    git(tmp_path, "clone", origin, source)
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.invalid")
    (source / "web").mkdir()
    (source / "web/package.json").write_text('{"version":"0.4.0"}')
    (source / "pyproject.toml").write_text('[project]\ndependencies=[]\nrequires-python=">=3.14"\n')
    (source / ".gitignore").write_text(".temp/\nweb/dist/\n")
    (source / "version.txt").write_text("old")
    git(source, "add", ".")
    git(source, "commit", "-m", "initial")
    git(source, "push", "origin", "main")
    git(tmp_path, "clone", origin, checkout)
    (source / "version.txt").write_text("new")
    git(source, "commit", "-am", "new version")
    git(source, "push", "origin", "main")
    restarts = []
    updater = Updater(checkout, tmp_path / "update.json", lambda: restarts.append(True) or (202, {}), True)
    return updater, git, source, restarts


def prepare(folder):
    dist = folder / "web/dist"
    dist.mkdir()
    (dist / "index.html").write_text("new page")
    (dist / "new.js").write_text("new asset")


def test_real_update_prepares_before_fast_forward_and_restores_status(repo, monkeypatch):
    updater, git, source, restarts = repo
    info = updater.inspect()
    assert info["behind"] == 1 and info["available"] and not info["blocked"]
    assert "new version" in info["changes"][0]
    old = updater.running
    monkeypatch.setattr(updater, "prepare", prepare)
    updater.apply(info)
    assert (updater.root / "version.txt").read_text() == "new"
    assert (updater.root / "web/dist/index.html").read_text() == "new page"
    assert updater.running == old and restarts == [True]
    assert len(git(updater.root, "worktree", "list").splitlines()) == 1
    restored = Updater(updater.root, updater.journal, lambda: None, True).snapshot()
    assert restored["phase"] == "applied" and not restored["available"]
    assert restored["running"] == info["target"]


def test_dirty_working_tree_is_visible_and_never_applied(repo):
    updater, _, _, restarts = repo
    (updater.root / "version.txt").write_text("user edit")
    info = updater.inspect()
    updater.set(**info)
    assert info["available"] and "cambios locales" in info["blocked"]
    assert updater.submit("apply", info["target"])[0] == 409
    assert (updater.root / "version.txt").read_text() == "user edit" and not restarts


def test_build_failure_does_not_advance_checkout_or_restart(repo, monkeypatch):
    updater, git, _, restarts = repo
    info = updater.inspect()

    def fail(folder):
        raise UpdateError("Falló compilación")

    monkeypatch.setattr(updater, "prepare", fail)
    updater.worker("apply", info["target"])
    assert updater.snapshot()["phase"] == "error"
    assert git(updater.root, "rev-parse", "HEAD") == info["head"]
    assert (updater.root / "version.txt").read_text() == "old" and not restarts
    assert len(git(updater.root, "worktree", "list").splitlines()) == 1


def test_real_npm_build_and_git_activation_in_disposable_checkout(repo):
    updater, git, source, restarts = repo
    package = {
        "name": "update-fixture",
        "version": "0.4.1",
        "scripts": {
            "build": "node -e \"require('fs').mkdirSync('dist',{recursive:true});require('fs').writeFileSync('dist/index.html','built fixture')\""
        },
    }
    (source / "web/package.json").write_text(json.dumps(package))
    (source / "web/package-lock.json").write_text(
        json.dumps(
            {
                "name": "update-fixture",
                "version": "0.4.1",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": "update-fixture", "version": "0.4.1"}},
            }
        )
    )
    git(source, "add", ".")
    git(source, "commit", "-m", "buildable release")
    git(source, "push", "origin", "main")
    updater.worker("apply", updater.inspect()["target"])
    assert updater.snapshot()["phase"] == "restarting", updater.snapshot()
    assert (updater.root / "web/dist/index.html").read_text() == "built fixture"
    assert restarts == [True]


def test_edit_during_build_is_preserved(repo, monkeypatch):
    updater, git, _, restarts = repo
    info = updater.inspect()

    def edit(folder):
        prepare(folder)
        (updater.root / "version.txt").write_text("new user edit")

    monkeypatch.setattr(updater, "prepare", edit)
    updater.worker("apply", info["target"])
    assert "checkout cambió" in updater.snapshot()["error"]
    assert git(updater.root, "rev-parse", "HEAD") == info["head"]
    assert (updater.root / "version.txt").read_text() == "new user edit" and not restarts


def test_stale_target_and_concurrent_request_are_rejected(repo):
    updater, _, _, _ = repo
    updater.set(**updater.inspect())
    assert updater.submit("apply", "wrong")[0] == 409
    updater.busy = True
    assert updater.submit("check")[0] == 409


def test_journal_failure_does_not_leave_operation_locked(repo, monkeypatch):
    updater, _, _, _ = repo

    def fail(**data):
        raise OSError("disk full")

    monkeypatch.setattr(updater, "set", fail)
    assert updater.submit("check")[0] == 503
    assert not updater.busy and updater.snapshot()["phase"] == "error"


def test_diverged_branch_cannot_apply(repo):
    updater, git, _, _ = repo
    git(updater.root, "config", "user.name", "Test")
    git(updater.root, "config", "user.email", "test@example.invalid")
    (updater.root / "local.txt").write_text("local")
    git(updater.root, "add", ".")
    git(updater.root, "commit", "-m", "local change")
    info = updater.inspect()
    assert info["ahead"] == 1 and info["behind"] == 1 and "commits propios" in info["blocked"]


def test_checkout_already_pulled_still_offers_activation(repo):
    updater, git, _, _ = repo
    git(updater.root, "pull", "--ff-only")
    info = updater.inspect()
    assert info["behind"] == 0 and info["available"] and info["head"] != updater.running
    assert "new version" in info["changes"][0]


def test_unsupervised_and_interrupted_job_are_explicit(repo):
    updater, _, _, _ = repo
    updater.supervised = False
    assert updater.submit("apply", "anything")[0] == 409
    updater.journal.write_text(json.dumps({"phase": "building"}))
    recovered = Updater(updater.root, updater.journal, lambda: None, True)
    assert "interrumpió" in recovered.snapshot()["error"]


def test_process_error_never_exposes_remote_credentials(repo):
    updater, _, _, _ = repo
    with pytest.raises(UpdateError) as error:
        updater.run(["git", "show", "not-a-ref"])
    assert str(error.value) == "Falló git (código 128)"


def test_update_route_blocks_tunnel_and_forwards_only_selected_pc(monkeypatch):
    from lienzo import server

    handler = object.__new__(server.Handler)
    handler._json = lambda code, data: (code, data)
    handler._is_local = lambda: False
    assert handler._updates("POST", "apply", data={"target": "abc"})[0] == 403
    handler._is_local = lambda: True
    monkeypatch.setattr(server.identity, "pc_id", lambda: "local")
    calls = []
    monkeypatch.setattr(server.mirror.MIRROR, "forward", lambda *args: calls.append(args) or (202, {"ok": True}))
    assert handler._updates("POST", "apply", "remote", {"target": "abc", "pc": "remote"})[0] == 202
    assert calls == [("remote", "POST", "/updates/apply", {"target": "abc"})]


def test_dispatch_does_not_accept_arbitrary_actions(monkeypatch, repo):
    from lienzo import updates

    monkeypatch.setattr(updates, "SERVICE", repo[0])
    assert updates.dispatch("GET", "")[0] == 200
    assert updates.dispatch("POST", "shell", {"command": "whoami"})[0] == 404
