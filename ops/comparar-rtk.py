"""OFF/ON de contratos locales: no lanza coding agents ni llama a servicios pagos."""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lienzo"))
import agent_improvements
import optimization_activity
import optimization_cost
import subproc

FILES = ["tests/test_optimization_activity.py", "tests/test_optimization_memory.py"]


def manifest():
    relevant = [*FILES, "tests/conftest.py", *[p.relative_to(ROOT).as_posix() for p in (ROOT / "lienzo").glob("*.py")]]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in relevant}


def signals():
    measured = optimization_activity.snapshot(0)
    # Este proceso no comparte state.sessions con el servidor; consultar su fuente real.
    sessions = {}
    pending = []
    for route in ("sessions", "pending"):
        with urllib.request.urlopen("http://127.0.0.1:7321/" + route, timeout=3) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("estado real demasiado grande; no ejecutar")
        data = json.loads(raw)
        if route == "pending":
            pending = data
        else:
            sessions = {s["session_id"]: s for s in data}
            measured["agents_busy"] = any(s.get("alive") is not False and s.get("state") not in ("termino", "muerta") for s in data)
    measured["pending"] = optimization_activity.pending_active(pending, sessions)
    return measured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="solo si hay inactividad/recursos; una comparación local")
    args = parser.parse_args()
    path = agent_improvements.rtk_path()
    evidence = {"kind": "local-contract-comparison", "agent": None, "os": sys.platform, "rtk": bool(path),
                "max_service_cost_usd": optimization_cost.maximum("local-rtk-contract"),
                "agent_tokens": None, "agent_cost": None, "agent_quality": "no evaluada",
                "brief": "no evaluado", "manifest": manifest(), "profiles": [], "scope": "pytest directo/RTK, no agentes"}
    if not args.run:
        evidence["state"] = "plan, no ejecutado"
    elif path is None:
        evidence["state"] = "bloqueado: RTK ausente"
    else:
        # Dos muestras de recursos antes de iniciar. La actividad se revisa entre perfiles.
        signals()  # calentar el delta de CPU; no confundir primera muestra desconocida con quietud
        time.sleep(1)
        first = signals()
        time.sleep(1)
        second = signals()
        reason = optimization_activity.block_reason(first) or optimization_activity.block_reason(second)
        if reason:
            evidence["state"] = "bloqueado: " + reason
        else:
            evidence["state"] = "ejecutando contrato local"
            for profile in ("OFF", "ON"):
                if manifest() != evidence["manifest"]:
                    evidence["state"] = "invalidado: fuentes cambiaron"
                    break
                reason = optimization_activity.block_reason(signals())
                if reason:
                    evidence["state"] = "suspendido entre perfiles: " + reason
                    break
                argv = [sys.executable, "-m", "pytest", *FILES, "-q", "-p", "no:cacheprovider"]
                start = time.monotonic()
                code, stdout, stderr = subproc.correr(argv, cwd=str(ROOT), timeout=10, max_output=200_000)
                if profile == "ON":
                    filter_code, filtered, filter_error = subproc.correr(
                        [path, "pipe", "--filter", "pytest"], entrada=stdout, timeout=5, max_output=200_000,
                    )
                    if filter_code == 0:
                        stdout = filtered
                    code = code or filter_code
                    if filter_error:
                        stderr += "\nRTK: " + filter_error
                evidence["profiles"].append({"profile": profile, "code": code,
                    "seconds": time.monotonic() - start, "stdout": stdout, "stderr": stderr,
                    "output_chars": len(stdout) + len(stderr), "oracle": "contratos reales: assertions de bloqueo y memoria"})
                if code:
                    evidence["state"] = "revisar: oráculo falló; sin reintento"
                    break
            if len(evidence["profiles"]) == 2 and all(p["code"] == 0 for p in evidence["profiles"]):
                evidence["state"] = "comparación local observada; sin veredicto sobre agentes"
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
