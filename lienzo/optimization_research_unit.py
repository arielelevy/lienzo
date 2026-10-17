"""Caso del investigador sobre una unidad de trabajo completa: una ronda, ola o feature coordinada por Lienzo.

Pedido de Ariel (2026-10-17): «se hizo una ola o un feature, ¿se pudo hacer mejor? ¿se pudo organizar mejor?
Lienzo es un coordinador». Los casos sueltos (un hallazgo, un incidente) no muestran el proceso.

Fuentes, todas ya registradas y sin transcripciones crudas:
- carpetas de coordinación del proyecto (`.temp/coordinacion/<día>`, `.coda/coord-<día>`): encargos por frente
  (`A.md`, `A-tema.md`), informes (`informe-A*.md`, su línea ESTADO, sus rondas extra), planes, comunes y traspasos;
- capturas de la ventana de la unidad: métricas de coordinación de `optimizacion_trabajo.medir` (esperas,
  acuses, avisos repetidos o intermedios, difusiones, pico) y sesiones con agente, modelo y PC;
- nivel 2 («cómo se hizo») de las sesiones con más eventos, el mismo de los casos sueltos.

Límite declarado: las fechas de archivo son la última modificación, no la primera entrega.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import conocimiento
import optimizacion_trabajo as trabajo
import optimization_memory as memory

ENCARGO = re.compile(r"^([A-Z])(?:-([\w-]+))?\.md$")
INFORME = re.compile(r"^informe-([A-Z])(?:-([\w-]+))?\.md$")
PLAN = re.compile(r"^plan-([A-Z])(?:-([\w-]+))?\.md$")
COMUN = re.compile(r"^comun.*\.md$", re.IGNORECASE)
TRASPASO = re.compile(r"traspaso.*\.md$", re.IGNORECASE)
RONDA_EXTRA = re.compile(r"^#{2,3} +Ronda +\d+", re.IGNORECASE | re.MULTILINE)
CONTROLES = {
    "pruebas": re.compile(r"pytest|\bpassed\b|ejecutar\.mjs", re.IGNORECASE),
    "mutacion": re.compile(r"mutaci|mutante", re.IGNORECASE),
    "compuerta": re.compile(r"compuerta|baseline", re.IGNORECASE),
    "review": re.compile(r"code.?review|auditor|code-audit", re.IGNORECASE),
}
QUIET_HOURS = 2  # una carpeta sin cambios en este lapso, con informes, es candidata automática
MARGIN = dt.timedelta(minutes=30)
MAX_FILES = 60
SESSIONS = 12
FOLDER_GLOBS = (".temp/coordinacion/*", ".coda/coord-*")


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _mtime(path: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)


def project_roots(project: str) -> list[Path]:
    """Carpetas del proyecto que existen en esta PC (un proyecto puede tener varias o ninguna)."""
    roots = []
    for folder in conocimiento.proyecto(project).get("carpetas", []):
        cwd = folder.get("cwd") if isinstance(folder, dict) else None
        if isinstance(cwd, str) and Path(cwd).is_dir():
            roots.append(Path(cwd).resolve())
    return list(dict.fromkeys(roots))


def resolve_folders(project: str, folders: list[str]) -> tuple[Path, list[Path]]:
    """Carpetas de coordinación pedidas, relativas a una carpeta del proyecto. Rechaza todo lo demás."""
    if not isinstance(folders, list) or not 1 <= len(folders) <= 4 or not all(isinstance(f, str) for f in folders):
        raise ValueError("entre 1 y 4 carpetas de coordinación")
    for root in project_roots(project):
        allowed = {p.resolve() for pattern in FOLDER_GLOBS for p in root.glob(pattern) if p.is_dir()}
        resolved = [(root / f).resolve() for f in folders]
        if all(p in allowed for p in resolved):
            return root, resolved
    raise ValueError("carpetas fuera de .temp/coordinacion o .coda/coord-* del proyecto")


def candidate_folders(project: str, now: dt.datetime | None = None) -> list[tuple[Path, Path]]:
    """(raíz, carpeta) con al menos un informe y sin cambios en QUIET_HOURS: una ola cerrada o quieta."""
    now = now or dt.datetime.now(dt.UTC)
    found = []
    for root in project_roots(project):
        for pattern in FOLDER_GLOBS:
            for folder in sorted(root.glob(pattern)):
                files = [f for f in folder.iterdir() if f.is_file()] if folder.is_dir() else []
                if not any(INFORME.match(f.name) for f in files):
                    continue
                if now - max(_mtime(f) for f in files) >= dt.timedelta(hours=QUIET_HOURS):
                    found.append((root, folder))
    return found


def case(project: str, root: Path, folders: list[Path]) -> dict:
    rel = sorted(f.relative_to(root).as_posix() for f in folders)
    files = [f for folder in folders for f in folder.iterdir() if f.is_file()]
    end = max((_mtime(f) for f in files), default=dt.datetime.now(dt.UTC))
    key = hashlib.sha256(json.dumps(["unidad-v1", project, rel], ensure_ascii=True).encode()).hexdigest()[:32]
    return {
        "case_key": key,
        "project": project,
        "area": "reparto",
        "origin": "unidad",
        "kind": "unit",
        "priority": 2.5,
        "folders": rel,
        "source_ids": [],
        "date": _iso(end),
        "selected_by": "unidad de trabajo con informes",
    }


def _controls(text: str) -> dict:
    return {name: len(pattern.findall(text)) for name, pattern in CONTROLES.items()}


def _estado(text: str) -> str | None:
    for line in text.splitlines():
        if "ESTADO" in line:
            return line.strip()[:240]
    return None


def summarize_folders(root: Path, folders: list[Path], redact) -> dict:
    """Frentes con sus encargos, planes e informes, más comunes, traspasos y otros artefactos."""
    fronts, common, others = {}, [], []
    files = sorted((f for folder in folders for f in folder.iterdir() if f.is_file()), key=_mtime)[:MAX_FILES]
    for f in files:
        rel = f.relative_to(root).as_posix()
        when, size = _iso(_mtime(f)), f.stat().st_size
        for kind, pattern in (("encargos", ENCARGO), ("informes", INFORME), ("planes", PLAN)):
            match = pattern.match(f.name)
            if match:
                front = fronts.setdefault(match.group(1), {"encargos": [], "informes": [], "planes": []})
                entry = {"archivo": rel, "tema": match.group(2), "modificado": when, "bytes": size}
                if kind != "planes":
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if kind == "encargos":
                        entry["inicio"] = redact(" ".join(text[:400].split()))
                    else:
                        entry.update(
                            estado=redact(_estado(text) or "") or None,
                            rondas_extra=len(RONDA_EXTRA.findall(text)),
                            controles_declarados=_controls(text),
                            secciones=[redact(h.strip()[:120]) for h in re.findall(r"^#{1,3} .+$", text, re.MULTILINE)][
                                :20
                            ],
                        )
                front[kind].append(entry)
                break
        else:
            target = common if COMUN.match(f.name) or TRASPASO.match(f.name) else others
            target.append({"archivo": rel, "modificado": when, "bytes": size})
    for front in fronts.values():
        for report in front["informes"]:
            tema = report["tema"]
            order = [e for e in front["encargos"] if e["tema"] == tema]
            if order:
                delta = dt.datetime.fromisoformat(report["modificado"]) - dt.datetime.fromisoformat(
                    order[0]["modificado"]
                )
                report["horas_desde_encargo"] = round(delta.total_seconds() / 3600, 2)
        front["encargos_sin_informe"] = [
            e["archivo"] for e in front["encargos"] if not any(r["tema"] == e["tema"] for r in front["informes"])
        ]
    return {
        "frentes": fronts,
        "comunes_y_traspasos": common,
        "otros_artefactos": len(others),
        "archivos_omitidos": max(0, sum(1 for folder in folders for f in folder.iterdir() if f.is_file()) - MAX_FILES),
    }


def window(root: Path, folders: list[Path]) -> tuple[dt.datetime, dt.datetime]:
    times = [_mtime(f) for folder in folders for f in folder.iterdir() if f.is_file()]
    return min(times) - MARGIN, max(times) + MARGIN


def sessions_in_window(con, project: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    rows = con.execute(
        "SELECT session_id, max(agente) AS agente, max(modelo) AS modelo, max(pc) AS pc, count(*) AS eventos, "
        "sum(clase='pedido') AS pedidos, sum(clase='respuesta') AS respuestas, sum(clase='envio') AS envios, "
        "sum(clase='regla') AS reglas, min(fecha) AS desde, max(fecha) AS hasta "
        "FROM captura WHERE proyecto=? AND fecha BETWEEN ? AND ? GROUP BY session_id ORDER BY eventos DESC LIMIT ?",
        (project, _iso(start), _iso(end), SESSIONS),
    ).fetchall()
    return [dict(r) for r in rows]


def coordination_metrics(project: str, start: dt.datetime, end: dt.datetime) -> dict:
    hours = (end - start).total_seconds() / 3600
    caps = [c for c in trabajo.capturas(project, hours, end) if c["fecha"] >= start]
    metrics = trabajo.medir(caps)
    return {"capturas": len(caps), "metricas": metrics or {"nota": "sin coordinadora identificable en la ventana"}}


def packet(case: dict, *, redact, how, counts_holder: dict) -> dict:
    """Paquete del caso de unidad: qué se pidió y entregó (archivos), cómo se coordinó (capturas) y nivel 2."""
    root, folders = resolve_folders(case["project"], case["folders"])
    start, end = window(root, folders)
    summary = summarize_folders(root, folders, lambda text: redact(text, counts_holder))
    con = memory._connect()
    try:
        sessions = sessions_in_window(con, case["project"], start, end)
        top = [s["session_id"] for s in sessions[:4]]
        detail = how(con, case["project"], top, counts_holder)
    finally:
        con.close()
    return {
        "unidad": {
            "carpetas": case["folders"],
            "ventana": {
                "desde": _iso(start),
                "hasta": _iso(end),
                "horas": round((end - start).total_seconds() / 3600, 1),
            },
            **summary,
        },
        "coordinacion": coordination_metrics(case["project"], start, end),
        "sesiones": sessions,
        "how_it_happened": detail,
        "trace_refs": ["sesion:" + s["session_id"] for s in sessions],
        "unit_limits": (
            "fechas de archivo = última modificación, no primera entrega; capturas sin llamadas a herramientas; "
            "las sesiones de la ventana pueden incluir trabajo ajeno a la unidad"
        ),
    }
