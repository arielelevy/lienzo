"""Exercise the documented launcher without the import paths supplied by pytest."""

import os
import subprocess
import sys
from pathlib import Path


def test_direct_server_help_from_unrelated_directory(tmp_path):
    script = Path(__file__).resolve().parents[1] / "lienzo" / "server.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: lienzo-server" in result.stdout
