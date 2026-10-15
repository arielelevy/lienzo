import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "preparar_mejoras", Path(__file__).parents[1] / "ops" / "preparar-mejoras.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_hash_mismatch_does_not_install():
    with pytest.raises(ValueError, match="hash"):
        installer.binary_from_archive(b"untrusted")


def test_reads_only_expected_binary_without_extracting_paths(monkeypatch):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("rtk.exe", b"test-binary")
        archive.writestr("../escape", b"ignore")
    raw = output.getvalue()
    monkeypatch.setattr(installer, "SHA256", installer.hashlib.sha256(raw).hexdigest())
    assert installer.binary_from_archive(raw) == b"test-binary"
