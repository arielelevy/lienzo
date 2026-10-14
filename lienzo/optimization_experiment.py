"""Dos perfiles locales de contrato, USD0 de servicios; ningún coding agent."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import optimization_cost
import state
import subproc
from atomico import atomic_write
from tools import rtk

FILES = ("tests/test_optimization_activity.py", "tests/test_optimization_memory.py")


def manifest():
    root = Path(state.ROOT)
    files = [
        *(root / "lienzo").glob("*.py"),
        *(root / "lienzo/tools").glob("*.py"),
        root / "tests/conftest.py",
        *[root / f for f in FILES],
    ]
    return hashlib.sha256(
        json.dumps(
            [(p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]
        ).encode()
    ).hexdigest()


def step(job):
    if optimization_cost.maximum("local-rtk-contract") != "0":
        raise ValueError("contrato local sin costo cero verificado")
    if manifest() != job["source_version"]:
        raise ValueError("fuentes cambiaron; ensayo requiere nueva revisión")
    path = rtk.ruta()
    if not path:
        raise ValueError("RTK ausente en esta PC")
    profile = ("OFF", "ON")[job["cursor"]]
    argv = [sys.executable, "-m", "pytest", *FILES, "-q", "-p", "no:cacheprovider"]
    import time

    started = time.monotonic()
    code, stdout, stderr = subproc.correr(argv, timeout=10, cwd=state.ROOT, max_output=200_000)
    raw_stdout = stdout
    filter_code = 0
    if profile == "ON":
        filter_code, filtered, filter_error = subproc.correr(
            [path, "pipe", "--filter", "pytest"],
            entrada=stdout,
            timeout=5,
            max_output=200_000,
        )
        if filter_code == 0:
            stdout = filtered
        if filter_error:
            stderr += "\nRTK: " + filter_error
    if manifest() != job["source_version"]:
        raise ValueError("fuentes cambiaron durante ensayo; no validar resultado")
    return {
        "profile": profile,
        "code": code or filter_code,
        "command_code": code,
        "filter_code": filter_code,
        "raw_stdout": raw_stdout,
        "seconds": time.monotonic() - started,
        "stdout": stdout,
        "stderr": stderr,
        "output_chars": len(stdout) + len(stderr),
        "agent_tokens": None,
        "agent_quality": "no evaluada",
        "service_cost_usd": 0,
    }


def save(job):
    root = Path(state.LIENZO) / "improvements"
    root.mkdir(parents=True, exist_ok=True)
    name = "off-on-" + hashlib.sha256(job["id"].encode()).hexdigest() + ".json"
    target = root / name
    atomic_write(
        str(target),
        json.dumps(
            {
                "scope": "contratos locales, no agentes",
                "project": job["project"],
                "source_version": job["source_version"],
                "profiles": job["profiles"],
                "agent_quality": "no evaluada",
                "service_cost_usd": 0,
                "requires_verdict": True,
            },
            ensure_ascii=False,
        ),
    )
    return "improvements/" + name
