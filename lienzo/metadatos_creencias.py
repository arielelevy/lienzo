"""Metadatos por evidencia, compartidos por proponentes y revisión delegada (AB.6)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

CAMPOS = ("tecnologia", "area", "fase", "tipo_trabajo", "agente", "modelo")
_RUTA = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[a-zA-Z0-9]+")


def relacionadas(con, pid, fuentes):
    """Sigue evidencia → informe → encargo → tarjeta productora, con límite de lectura."""
    import conocimiento as k

    nodes = {n["id"]: n for n in fuentes}
    frontier = list(nodes)
    for _ in range(3):
        following = []
        for nid in frontier:
            rows = con.execute(
                "SELECT n.* FROM vinculo v JOIN nodo n ON n.id=v.a WHERE v.de=? AND v.activo=1 "
                "AND v.relacion IN ('declarado_en','responde_a','ejecutado_por','motivada_por','apoya') "
                "AND n.proyecto=? ORDER BY n.fecha,n.id LIMIT 30",
                (nid, pid),
            ).fetchall()
            for row in rows:
                node = k._fila(row)
                if node["id"] not in nodes and len(nodes) < 60:
                    nodes[node["id"]] = node
                    following.append(node["id"])
        frontier = following
    return list(nodes.values())


def completar(pid, contexto, fuentes, *, extra=None):
    """No pide datos a la persona ni inventa hechos: lo ausente queda explícito y con procedencia."""
    out = {"proyecto": pid, "rutas": [], "tipo_archivo": [], "fuentes": {"proyecto": [{"origen": pid}]}}
    for key in CAMPOS:
        out[key] = []
        out["fuentes"][key] = []
    for node in fuentes:
        data = node.get("datos", {})
        ctx = {**data}
        if isinstance(data.get("agent"), str):
            ctx["agente"] = data["agent"]
        if isinstance(data.get("model"), str):
            ctx["modelo"] = data["model"]
        for field in ("contexto_desarrollo", "contexto"):
            if isinstance(data.get(field), dict):
                ctx.update(data[field])
        for key in CAMPOS:
            value = ctx.get(key)
            if isinstance(value, str) and value.strip():
                out[key].append(value.strip()[:100])
                out["fuentes"][key].append(
                    {"nodo": node["id"], "fecha": node.get("fecha"), "valor": value.strip()[:100]}
                )
        paths = data.get("archivos", [])
        if isinstance(paths, list):
            out["rutas"].extend(p.replace("\\", "/")[:300] for p in paths if isinstance(p, str))
        out["rutas"].extend(_RUTA.findall(node.get("texto", "")))
    for source, values in (("contexto de la propuesta", contexto), ("revisión IA desde evidencia", extra or {})):
        for key in CAMPOS:
            value = values.get(key)
            values_list = [value] if isinstance(value, str) else value
            if isinstance(values_list, list):
                for val in values_list:
                    if isinstance(val, str) and val.strip() and val != "no consta en evidencia":
                        out[key].append(val.strip()[:100])
                        out["fuentes"][key].append({"origen": source, "valor": val.strip()[:100]})
    out["rutas"] = sorted(set(out["rutas"]))[:30]
    out["tipo_archivo"] = sorted({PurePosixPath(p).suffix for p in out["rutas"] if PurePosixPath(p).suffix})
    if not out["tecnologia"]:
        extensions = {".py": "python", ".tsx": "react", ".ts": "typescript", ".js": "javascript"}
        tech = sorted({extensions[e] for e in out["tipo_archivo"] if e in extensions})
        if tech:
            out["tecnologia"] = tech
            out["fuentes"]["tecnologia"] = [{"origen": "extensiones de archivos de la evidencia"}]
    for key in CAMPOS:
        out[key] = sorted(set(out[key]))
    out["fuentes"]["rutas"] = [n["id"] for n in fuentes]
    out["fuentes"]["tipo_archivo"] = "extensiones de rutas"
    return out
