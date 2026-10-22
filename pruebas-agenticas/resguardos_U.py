"""Lanza focales aislados de U, con stdin cerrado y código de salida real."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

base = Path(tempfile.mkdtemp(prefix="lienzo-U-18848-")) / "pytest"
command = [
    sys.executable,
    "-B",
    "-m",
    "pytest",
    "tests/test_encargo_u.py",
    "tests/test_registro_retencion.py",
    "tests/test_emergencia.py",
    "tests/test_mirror.py",
    "tests/test_tarjetas_ajenas.py",
    "tests/test_ejecuciones_externas.py",
    "-q",
    "-p",
    "no:cacheprovider",
    "--basetemp",
    str(base),
]
result = subprocess.run(command, stdin=subprocess.DEVNULL, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
raise SystemExit(result.returncode)
