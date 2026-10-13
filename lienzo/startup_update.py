"""Actualizar el checkout antes de arrancar el servidor."""

from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def update() -> int:
    try:
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        result = subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT, timeout=60)
        if result.returncode:
            print(f"Lienzo: git pull falló (código {result.returncode}); arranco con la versión local.", flush=True)
            return 0
        changes = subprocess.run(
            ["git", "diff", "--name-only", before, "HEAD", "--", "web/"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        pending = ROOT / "web" / ".startup-build-pending"
        if changes:
            pending.touch()
        if pending.exists():
            command = ["npm", "run", "build"]
            if os.name == "nt":
                command = [os.environ["COMSPEC"], "/d", "/c", "npm.cmd run build"]
            result = subprocess.run(command, cwd=ROOT / "web")
            if result.returncode:
                print("Lienzo: falló la compilación de la interfaz; no arranco.", flush=True)
            else:
                pending.unlink()
            return result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Lienzo: no se pudo actualizar: {exc}; no arranco.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(update())
