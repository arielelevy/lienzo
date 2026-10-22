"""Regresiones aisladas B05/B07: sin lanzar agentes ni acceder a red."""

import os
import subprocess
from types import SimpleNamespace

import pytest

from lienzo import launch, startup_update


@pytest.mark.parametrize("build_code", [0, 7])
def test_offline_pull_respects_pending_build(tmp_path, monkeypatch, build_code):
    web = tmp_path / "web"
    web.mkdir()
    pending = web / ".startup-build-pending"
    pending.touch()
    monkeypatch.setattr(startup_update, "ROOT", tmp_path)
    codes = iter([0, 1, build_code])
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=next(codes), stdout="old", stderr="")

    monkeypatch.setattr(startup_update.subprocess, "run", run)
    assert startup_update.update() == build_code
    assert len(calls) == 3
    assert calls[-1][1]["cwd"] == web
    assert "build" in " ".join(calls[-1][0])
    assert pending.exists() == bool(build_code)


def test_offline_ready_checkout_does_not_build(tmp_path, monkeypatch):
    monkeypatch.setattr(startup_update, "ROOT", tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout="old", stderr="")

    monkeypatch.setattr(startup_update.subprocess, "run", run)
    assert startup_update.update() == 0
    assert len(calls) == 2


def test_launch_rejects_physical_escape_even_with_logical_prefix(tmp_path, monkeypatch):
    root = tmp_path / "permitted"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = root / "redirected"
    redirected.mkdir()
    resolve = launch._physical_path

    def redirected_realpath(path):
        if os.fspath(path) == str(redirected):
            return os.path.normcase(str(outside))
        return resolve(path)

    monkeypatch.setattr(launch, "_physical_path", redirected_realpath)
    assert not launch._cwd_allowed(str(redirected), [os.path.normcase(str(root))])


def test_launch_physical_roots_preserve_exact_child_and_prefix_boundary(tmp_path):
    root = tmp_path / "allowed"
    child = root / "child"
    child.mkdir(parents=True)
    sibling = tmp_path / "allowed-other"
    sibling.mkdir()
    roots = [os.path.normcase(str(root))]
    assert launch._cwd_allowed(str(root), roots)
    assert launch._cwd_allowed(str(child), roots)
    assert not launch._cwd_allowed(str(sibling), roots)


def test_launch_accepts_descendant_of_volume_root(tmp_path):
    volume = os.path.splitdrive(str(tmp_path))[0] + os.sep
    assert launch._cwd_allowed(str(tmp_path), [os.path.normcase(volume)])


def test_launch_rejects_real_directory_symlink_escape(tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    redirected = root / "redirected"
    try:
        redirected.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"No se puede crear symlink sin cambiar permisos: {exc}")
    assert not launch._cwd_allowed(str(redirected), [os.path.normcase(str(root))])


@pytest.mark.skipif(os.name != "nt", reason="Junction de Windows")
def test_launch_rejects_real_windows_junction_escape(tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    redirected = root / "junction"
    subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(redirected), str(outside)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    try:
        assert redirected.is_junction()
        assert not launch._cwd_allowed(str(redirected), [os.path.normcase(str(root))])
    finally:
        os.rmdir(redirected)  # Solo el enlace dentro de tmp_path; no es una eliminación recursiva.
    assert outside.is_dir()


def test_launch_rejects_unresolvable_physical_directory(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("physical path unavailable")

    monkeypatch.setattr(launch, "_physical_path", denied)
    assert not launch._cwd_allowed(str(tmp_path), [os.path.normcase(str(tmp_path))])
