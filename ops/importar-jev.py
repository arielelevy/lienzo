"""Importación local explícita; la clave nunca se imprime ni se pasa en argv."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import jev_credentials

READ_KEY = (
    "import pathlib,shlex,sys; "
    "rows=pathlib.Path('/etc/chesstudia/nube.env').read_text().splitlines(); "
    "values=[shlex.split(line.split('=',1)[1],comments=True) for line in rows "
    "if line.strip().removeprefix('export ').startswith('CHESSTUDIA_OPENROUTER_API_KEY=')]; "
    "assert len(values)==1 and len(values[0])==1, 'credencial ausente o ambigua'; "
    "sys.stdout.write(values[0][0])"
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--distro", required=True)
    args = parser.parse_args()
    result = subprocess.run(["wsl.exe", "-d", args.distro, "--", "python3", "-c", READ_KEY],
                            capture_output=True, timeout=15, check=False)
    if result.returncode:
        sys.exit("No se pudo leer la credencial de Chesstudia; no se guardo nada")
    jev_credentials.store(result.stdout.decode("utf-8").strip())
    print(json.dumps({"ok": True, "credential": "protegida para el usuario de Lienzo"}))
