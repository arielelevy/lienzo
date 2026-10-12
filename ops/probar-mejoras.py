"""Prueba real acotada; no lanza agentes ni modifica sesiones o proyectos."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import agent_improvements
import jev


def check_rtk() -> dict:
    path = agent_improvements.rtk_path()
    if not path:
        raise ValueError("RTK no esta instalado")
    records = []
    # Entrada propia: salida de tests sintética con un diagnóstico que no puede perderse.
    with tempfile.TemporaryDirectory(prefix="lienzo-rtk-") as directory:
        script = Path(directory) / "case.py"
        for exit_code in (0, 7):
            script.write_text("import sys\nprint('20 passed' if sys.argv[1]=='0' else 'FAILED diagnostic-sentinel')\nsys.exit(int(sys.argv[1]))\n")
            argv = [sys.executable, str(script), str(exit_code)]
            raw = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
            compact = subprocess.run([path, "test", "--", *argv], capture_output=True, text=True, timeout=15, check=False)
            original = subprocess.run([path, "proxy", "--", *argv], capture_output=True, text=True, timeout=15, check=False)
            assert raw.returncode == compact.returncode == original.returncode == exit_code
            assert raw.stdout == original.stdout
            if exit_code:
                assert "diagnostic-sentinel" in compact.stdout + compact.stderr
            records.append({"exit": exit_code, "raw": raw.stdout, "compact": compact.stdout,
                            "original": original.stdout, "match": True})
    return {"rtk": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jev", action="store_true", help="una llamada paga, cota estimada USD 0.001")
    parser.add_argument("--rtk", action="store_true")
    args = parser.parse_args()
    data = {}
    if args.rtk:
        data.update(check_rtk())
    if args.jev:
        evidence = {"scope": "prueba sintetica de conectividad, no una sesion real", "counts": {"turns": 0, "tools": 0},
                    "tools": [], "partial": True, "quality": "desconocida"}
        data["jev"] = jev.decide(evidence)
    print(json.dumps(data, ensure_ascii=False))
