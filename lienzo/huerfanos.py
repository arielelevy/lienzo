"""Elección pura de continuidad: relaciones explícitas y una coordinadora por repo."""

from __future__ import annotations


def repo(s: dict) -> str | None:
    return s.get("repo_key") or s.get("repo") or None


def viva(s: dict, caidas: set[str]) -> bool:
    return bool(s.get("alive") and s.get("state") != "muerta" and not s.get("stopped_by") and s.get("pc") not in caidas)


def _padres(links: list, reglas: list) -> dict:
    padres = {}
    for r in reglas:
        if r.get("kind") == "on_stop" and r.get("from") and r.get("to"):
            padres.setdefault(r["from"], set()).add(r["to"])
    ultimos = {}
    for ln in sorted(links, key=lambda x: (x.get("ts") or "", x.get("id") or "")):
        if ln.get("kind") == "send" and ln.get("from") and ln.get("to"):
            ultimos[ln["to"]] = {ln["from"]}
    for sid, origen in ultimos.items():
        padres.setdefault(sid, origen)  # una regla de informe tiene prioridad sobre un encargo histórico
    return padres


def _pendientes(s: dict, sesiones: list, reglas: list) -> list:
    anteriores = s.get("orphaned_from", [])
    pendientes = set(s.get("orphaned_pending", []))
    # Un frente restaurado puede traer una regla estacionada que no existía al promover.
    propios = {x["session_id"] for x in sesiones if repo(x) == repo(s)}
    pendientes.update(
        r["to"] for r in reglas if r.get("kind") == "on_stop" and r.get("from") in propios and r.get("to") in anteriores
    )
    return sorted(pendientes)


def _ausentes(s: dict, padres: dict, vivas: dict, coordinadas: set) -> list:
    sid = s["session_id"]
    if (
        not repo(s)
        or repo(s) in coordinadas
        or s.get("coordinator_declined")
        or s.get("external")
        or sid.startswith(("pid-", "tmux-"))
    ):
        return []
    relacionados = padres.get(sid, set()) - {sid}
    return [] if relacionados & vivas.keys() else sorted(relacionados)


def _actividad(vivas: dict, pares) -> dict:
    out = {}
    for coordinadora, frente in pares:
        if coordinadora == frente or coordinadora not in vivas or frente not in vivas:
            continue
        if repo(vivas[coordinadora]) and repo(vivas[coordinadora]) == repo(vivas[frente]):
            out.setdefault(coordinadora, set()).add(frente)
    return out


def _de_hecho(vivas: dict, links: list, reglas: list, coordinadas: set) -> dict:
    informes = _actividad(
        vivas,
        (
            (r.get("to"), r.get("from"))
            for r in reglas
            if r.get("kind") == "on_stop"
            and r.get("enabled")
            and not r.get("parked_since")
            and not r.get("archived_at")
        ),
    )
    encargos = _actividad(vivas, ((ln.get("from"), ln.get("to")) for ln in links if ln.get("kind") == "send"))
    candidatos = {}
    for sid, s in vivas.items():
        identidad = repo(s)
        if (
            not identidad
            or identidad in coordinadas
            or s.get("coordinator_declined")
            or s.get("external")
            or sid.startswith(("pid-", "tmux-"))
        ):
            continue
        n_informes, n_encargos = len(informes.get(sid, ())), len(encargos.get(sid, ()))
        if n_informes >= 2 and n_encargos >= 2:
            candidatos.setdefault(identidad, []).append(
                {
                    "session_id": sid,
                    "repo": identidad,
                    "old": [],
                    "de_hecho": True,
                    "informes": n_informes,
                    "frentes": n_encargos,
                }
            )
    return candidatos


def planes(sesiones: list, links: list, reglas: list, caidas: set[str]) -> list[dict]:
    """Una elección por repo, o propuestas sin promoción cuando hay coordinadoras de hecho ambiguas."""
    vivas = {s["session_id"]: s for s in sesiones if viva(s, caidas)}
    coordinadas = {repo(s) for s in vivas.values() if s.get("coordinator")}
    padres = _padres(links, reglas)
    candidatos = {}
    for sid, s in vivas.items():
        identidad = repo(s)
        if s.get("coordinator"):
            pendientes = _pendientes(s, sesiones, reglas)
            if pendientes or s.get("orphaned_notice_pending"):
                candidatos[identidad] = [{"session_id": sid, "repo": identidad, "old": pendientes}]
            continue
        ausentes = _ausentes(s, padres, vivas, coordinadas)
        if ausentes:
            candidatos.setdefault(identidad, []).append({"session_id": sid, "repo": identidad, "old": ausentes})
    for identidad, grupo in _de_hecho(vivas, links, reglas, coordinadas).items():
        candidatos[identidad] = [dict(p, propuesta=len(grupo) > 1) for p in grupo]
    return [
        p
        for _, grupo in sorted(candidatos.items())
        for p in (
            sorted(grupo, key=lambda p: p["session_id"])
            if grupo[0].get("propuesta")
            else [min(grupo, key=lambda p: p["session_id"])]
        )
    ]


def recablear(reglas: list, sesiones: list, old: str, new: str, identidad: str) -> int:
    """Sólo on_stop de frentes del repo, sin crear una regla que se informe a sí misma."""
    propios = {s["session_id"] for s in sesiones if repo(s) == identidad}
    n = 0
    for r in reglas:
        if r.get("kind") != "on_stop" or r.get("from") not in propios or old not in (r.get("to"), r.get("parked_to")):
            continue
        r["to"] = new
        r.pop("to_pc", None)
        r.pop("parked_to", None)
        if r.get("from") == new:
            r["enabled"] = False
            r["disabled_reason"] = "frente promovido a coordinadora"
            r.pop("parked_was_enabled", None)
        elif not r.get("parked_from"):
            r["enabled"] = r.pop("parked_was_enabled", r.get("enabled", False))
            r.pop("disabled_reason", None)
            r.pop("archived_at", None)
        if not r.get("parked_from"):
            r.pop("parked_since", None)
        n += 1
    return n
