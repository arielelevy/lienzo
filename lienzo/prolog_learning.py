"""Consulta acotada al motor separado; snapshot consistente, sin escribir conocimiento."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

import aprendizaje
import conocimiento as k
import creencias

ENGINE = (
    Path(os.environ["LIENZO_PROLOG_ENGINE"]).expanduser().resolve()
    if "LIENZO_PROLOG_ENGINE" in os.environ
    else (Path(__file__).resolve().parents[2] / "motor-logico/main.pl")
)
STATES = set(creencias.MOTIVOS)
_busy = threading.BoundedSemaphore(1)


class MotorError(Exception):
    pass


def _epoch(value):
    try:
        date = dt.datetime.fromisoformat(value)
        return date.timestamp() if date.tzinfo else None
    except TypeError, ValueError, OverflowError:
        return None


def snapshot(pid, context):
    context = creencias._contexto(context)
    now = dt.datetime.now(dt.UTC)
    with k._abrir(pid) as con:
        con.execute("BEGIN")
        rows = con.execute("SELECT * FROM nodo WHERE proyecto=? ORDER BY id LIMIT 1001", (pid,)).fetchall()
        edges = con.execute(
            "SELECT v.de,v.a,v.relacion FROM vinculo v JOIN nodo n ON n.id=v.de "
            "WHERE n.proyecto=? AND v.activo=1 AND v.relacion IN ('motivada_por','apoya') "
            "ORDER BY v.de,v.a LIMIT 2001",
            (pid,),
        ).fetchall()
        if len(rows) > 1000 or len(edges) > 2000:
            raise k.Rechazo("El snapshot excede 1000 nodos o 2000 vínculos; no se razona con datos truncados", 413)
        nodes = [k._fila(row) for row in rows]
        beliefs = [n for n in nodes if n["tipo"] == "decision" and n["datos"].get("clase") == "creencia_operativa"]
        graph = aprendizaje._Respaldos(con, pid)
        evidence = {n["id"] for n in nodes if n["tipo"] == "evidencia"}
        supports = {(e["de"], e["a"]) for e in edges if e["relacion"] == "apoya" and e["a"] in evidence}
        python = {}
        for belief in beliefs:
            state, _ = creencias._evaluar(belief, context, supports, graph.cadenas, ahora=now)
            python[belief["id"]] = state
    payload = {
        "contract": 1,
        "domain": "learning",
        "now": now.timestamp(),
        "context": context,
        "nodes": [{"id": n["id"], "kind": n["tipo"], "state": n["estado"]} for n in nodes],
        "edges": [{"from": e["de"], "to": e["a"], "relation": e["relacion"]} for e in edges],
        "beliefs": [
            {
                "id": b["id"],
                "state": b["estado"],
                "verdict": b["datos"].get("resultado"),
                "approved_by": b["datos"].get("veredicto_por"),
                "evidence": b["datos"].get("evidencia_veredicto"),
                "until": _epoch(b["datos"].get("vigente_hasta")),
                "required": b["datos"].get("contexto"),
            }
            for b in beliefs
        ],
    }
    return payload, python


def command():
    if os.name == "nt":
        # Ruta absoluta montada por WSL; no shell, interpolación ni reinstalación.
        drive = ENGINE.drive.rstrip(":").lower()
        path = "/mnt/" + drive + ENGINE.as_posix()[len(ENGINE.drive) :]
        return [
            "wsl.exe",
            "-d",
            "Ubuntu",
            "--",
            "swipl",
            "-q",
            "-f",
            "none",
            "--stack-limit=128m",
            "-s",
            path,
            "-g",
            "main",
            "-t",
            "halt",
        ]
    return ["swipl", "-q", "-f", "none", "--stack-limit=128m", "-s", str(ENGINE), "-g", "main", "-t", "halt"]


def run(payload):
    text = json.dumps(payload, ensure_ascii=True, allow_nan=False)
    if len(text.encode()) > 1024 * 1024:
        raise k.Rechazo("El snapshot supera 1 MiB", 413)
    if not ENGINE.is_file():
        raise MotorError("Motor lógico no encontrado: cloná motor-logico junto a Lienzo o fijá LIENZO_PROLOG_ENGINE")
    if not _busy.acquire(blocking=False):
        raise k.Rechazo("El motor Prolog está ocupado; volvé a consultar", 409)
    try:
        result = subprocess.run(
            command(),
            input=text + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            raise MotorError("Prolog no pudo resolver la consulta; revisá SWI-Prolog en Ubuntu WSL")
        if len(result.stdout.encode("utf-8")) > 2 * 1024 * 1024:
            raise MotorError("La respuesta Prolog excede 2 MiB")
        output = json.loads(result.stdout)
        validate(output, payload)
        return output
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise MotorError(f"Motor Prolog no disponible o respuesta inválida ({type(exc).__name__})") from None
    finally:
        _busy.release()


def validate(output, payload):
    if (
        not isinstance(output, dict)
        or type(output.get("contract")) is not int  # True == 1 en Python: un bool no es versión
        or output["contract"] != 1
        or output.get("domain") != "learning"
        or type(output.get("rules")) is not int
        or output["rules"] != 1
        or output.get("authority") != "observation_only"
    ):
        raise ValueError("contrato inválido")
    items = output.get("conclusions")
    ids = {b["id"] for b in payload["beliefs"]}
    nodes = {n["id"] for n in payload["nodes"]}
    if not isinstance(items, list) or len(items) != len(ids):
        raise ValueError("respuesta incompleta")
    found = []
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in STATES or item.get("rule") != item.get("status"):
            raise ValueError("conclusión inválida")
        found.append(item["id"])
        if not isinstance(item.get("chains"), list) or any(
            not isinstance(path, list) or not path or path[0] != item["id"] or any(node not in nodes for node in path)
            for path in item["chains"]
        ):
            raise ValueError("justificación inválida")
    if set(found) != ids or len(set(found)) != len(found):
        raise ValueError("IDs inválidos")


def inferir(pid, context):
    payload, python = snapshot(pid, context)
    try:
        output = run(payload)
    except MotorError as exc:
        return 503, {"error": str(exc), "code": "prolog_unavailable"}
    differences = [
        {"id": c["id"], "python": python[c["id"]], "prolog": c["status"]}
        for c in output["conclusions"]
        if c["status"] != python[c["id"]]
    ]
    return 200, {
        "motor": "SWI-Prolog · WSL" if os.name == "nt" else "SWI-Prolog",
        "autoridad": "observación; no modifica creencias",
        "contexto": payload["context"],
        "snapshot": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "reglas": output["rules"],
        "conclusiones": output["conclusions"],
        "diferencias": differences,
    }
