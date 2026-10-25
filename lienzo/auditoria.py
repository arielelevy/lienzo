"""Ronda de auditoría de sesiones (pedido de Ariel, 2026-10-25): cada 5 min, barata y determinista.

No despierta modelos ni lee transcripts: mira lo que el tablero ya sabe (`GET /sessions` y `GET /links`)
y clasifica cada sesión viva. Lo que encuentra va en un solo aviso por coordinadora, sin repetir lo ya
avisado: la clave de un hallazgo lleva su evidencia (desde cuándo está así, o el id del envío), y además
hay un enfriamiento por sesión y tipo.

Tipos de hallazgo:

- `idle_evitable`: frente quieto hace >= `idle_min` sin bloqueo declarado, esperando que lo asignen.
- `entrega_sin_leer`: el frente entregó (regla hacia la coordinadora) y la coordinadora no le mandó nada
  después, y está quieta. Es el caso «4 CLIs quietos 14 min» de OpenSyync.
- `envio_no_tomado`: se le mandó algo y la sesión no cambió de estado en `envio_min`: puede haber quedado
  en el editor o un diálogo tiene el teclado (caso a480da47, 2026-10-25).
- `bloqueado_humano`: espera un permiso o una respuesta (`te_necesita`) hace >= `bloqueo_min`. Es espera
  necesaria: se avisa para que alguien conteste, no se resuelve sola.
- `sin_coordinadora`: frentes vivos de un repo sin coordinadora viva.

Espera legítima, que no avisa: `corriendo`, cuota agotada (`limit_until` futuro) y un frente quieto que
cerró con `ESTADO: bloqueado` (`bloqueado_dependencia` queda en el informe pero no en el aviso).

    py -m lienzo.auditoria            una ronda: imprime el informe y no manda nada
    py -m lienzo.auditoria --enviar   además manda el aviso agrupado a cada coordinadora
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

CFG = {"idle_min": 10, "envio_min": 2, "bloqueo_min": 5, "enfriamiento_min": 30, "olvido_h": 24}
AVISAN = ("idle_evitable", "entrega_sin_leer", "envio_no_tomado", "bloqueado_humano", "sin_coordinadora")
_BLOQUEADO = re.compile(r"ESTADO:\s*bloquead", re.IGNORECASE)


def _t(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def _min(a: dt.datetime, b: dt.datetime | None) -> float:
    return (a - b).total_seconds() / 60 if b else 0.0


def clasificar(sesiones: list, links: list, ahora: dt.datetime, cfg: dict = CFG) -> list:
    """Un hallazgo por sesión que no está trabajando ni en espera legítima. Sin efectos."""
    vivas = [s for s in sesiones if s.get("alive") and s.get("state") != "muerta" and not s.get("stopped_by")]
    coord = {s.get("repo_key"): s for s in vivas if s.get("coordinator")}
    con_regla = {}  # frente -> última entrega (link `rule`) hacia una coordinadora
    ultimo_a = {}  # sesión -> último envío o regla que recibió
    for ln in sorted(links, key=lambda x: x.get("ts") or ""):
        if ln.get("kind") in ("send", "rule") and ln.get("to"):
            ultimo_a[ln["to"]] = ln
        if ln.get("kind") == "rule" and ln.get("from"):
            con_regla.setdefault(ln["from"], {})[ln.get("to")] = ln
    out = []
    for s in vivas:
        sid, estado = s["session_id"], s.get("state")
        desde = _t(s.get("state_since"))
        quieta = _min(ahora, desde)
        base = {
            "session_id": sid,
            "title": s.get("title"),
            "pc": s.get("pc"),
            "repo": s.get("repo_key"),
            "desde": s.get("state_since"),
            "minutos": round(quieta, 1),
        }
        if estado == "corriendo":
            continue
        if _t(s.get("limit_until")) and _t(s.get("limit_until")) > ahora:
            continue  # espera de cuota: legítima
        if estado == "te_necesita" and (s.get("needs") or {}).get("kind") == "sin_enviar":
            # el server ya vio que el envío no se confirmó en 25 s (hooks_eventos.envio_sin_confirmar)
            # pero sólo lo dejaba en la tarjeta y en el log: acá le llega a la coordinadora
            out.append(
                {
                    **base,
                    "tipo": "envio_no_tomado",
                    "evidencia": (s.get("needs") or {}).get("since") or s.get("state_since"),
                    "sugerencia": "mirar su pantalla: texto sin Enter o un diálogo con el teclado (Esc en la tarjeta)",
                }
            )
            continue
        if estado == "te_necesita":
            if quieta >= cfg["bloqueo_min"]:
                out.append(
                    {
                        **base,
                        "tipo": "bloqueado_humano",
                        "evidencia": s.get("state_since"),
                        "sugerencia": "contestar el permiso o la pregunta en su tarjeta",
                    }
                )
            continue
        recibido = ultimo_a.get(sid)
        t_rec = _t(recibido.get("ts")) if recibido else None
        if recibido and t_rec and (desde is None or desde <= t_rec) and _min(ahora, t_rec) >= cfg["envio_min"]:
            out.append(
                {
                    **base,
                    "tipo": "envio_no_tomado",
                    "evidencia": recibido.get("id"),
                    "minutos": round(_min(ahora, t_rec), 1),
                    "sugerencia": "mirar su pantalla: puede tener el texto sin Enter o un diálogo abierto",
                }
            )
            continue
        if s.get("coordinator") or quieta < cfg["idle_min"]:
            continue
        if _BLOQUEADO.search((s.get("last_reply") or "")[-400:]):
            out.append(
                {
                    **base,
                    "tipo": "bloqueado_dependencia",
                    "evidencia": s.get("state_since"),
                    "sugerencia": "espera declarada por el frente; ver su último informe",
                }
            )
            continue
        c = coord.get(s.get("repo_key"))
        if c is None:
            out.append(
                {
                    **base,
                    "tipo": "sin_coordinadora",
                    "evidencia": s.get("state_since"),
                    "sugerencia": "marcar una coordinadora para el repo o asignar el frente",
                }
            )
            continue
        entrega = con_regla.get(sid, {}).get(c["session_id"])
        t_ent = _t(entrega.get("ts")) if entrega else None
        respondio = (
            t_rec is not None and t_ent is not None and t_rec > t_ent and recibido.get("from") == c["session_id"]
        )
        if t_ent and not respondio and c.get("state") != "corriendo":
            out.append(
                {
                    **base,
                    "tipo": "entrega_sin_leer",
                    "evidencia": entrega.get("id"),
                    "coordinadora": c["session_id"],
                    "sugerencia": "leer su informe y darle la tarea siguiente ya autorizada, o cerrarlo",
                }
            )
        else:
            out.append(
                {
                    **base,
                    "tipo": "idle_evitable",
                    "evidencia": s.get("state_since"),
                    "coordinadora": c["session_id"],
                    "sugerencia": "asignar la tarea siguiente ya autorizada, o /exit si no hay",
                }
            )
    return out


def filtrar(hallazgos: list, previo: dict, ahora: dt.datetime, cfg: dict = CFG) -> tuple[list, dict]:
    """Deja sólo lo que hay que avisar: no repite una clave ya avisada (misma evidencia) y respeta el
    enfriamiento por (tipo, sesión). Devuelve (a_avisar, estado_nuevo)."""
    emitidos = dict(previo.get("emitidos") or {})
    ultimo = dict(previo.get("ultimo") or {})
    corte = ahora - dt.timedelta(hours=cfg["olvido_h"])
    emitidos = {k: v for k, v in emitidos.items() if (_t(v) or ahora) >= corte}
    avisar = []
    for h in hallazgos:
        if h["tipo"] not in AVISAN:
            continue
        clave = f"{h['tipo']}|{h['session_id']}|{h.get('evidencia')}"
        par = f"{h['tipo']}|{h['session_id']}"
        if clave in emitidos:
            continue
        if _t(ultimo.get(par)) and _min(ahora, _t(ultimo[par])) < cfg["enfriamiento_min"]:
            continue
        avisar.append(h)
        emitidos[clave] = ultimo[par] = ahora.isoformat(timespec="seconds")
    return avisar, {"emitidos": emitidos, "ultimo": ultimo, "ronda": ahora.isoformat(timespec="seconds")}


def agrupar(avisos: list, sesiones: list) -> dict:
    """Un texto por coordinadora (o `None` si el repo no tiene). Una sola línea por hallazgo."""
    coord = {s.get("repo_key"): s["session_id"] for s in sesiones if s.get("coordinator") and s.get("alive")}
    por = {}
    for h in avisos:
        destino = h.get("coordinadora") or coord.get(h.get("repo"))
        por.setdefault(destino, []).append(
            f"- {h['tipo']}: «{h.get('title') or h['session_id'][:8]}» hace {h['minutos']:.0f} min. {h['sugerencia']}."
        )
    return {
        d: "[auditoría del lienzo] " + str(len(ls)) + " sesiones para mirar:\n" + "\n".join(ls) for d, ls in por.items()
    }


def ronda(sesiones: list, links: list, previo: dict, ahora: dt.datetime | None = None, cfg: dict = CFG) -> dict:
    ahora = ahora or dt.datetime.now().astimezone()
    t0 = time.perf_counter()
    hallazgos = clasificar(sesiones, links, ahora, cfg)
    avisar, estado = filtrar(hallazgos, previo, ahora, cfg)
    return {
        "ahora": ahora.isoformat(timespec="seconds"),
        "sesiones": len(sesiones),
        "hallazgos": hallazgos,
        "avisar": avisar,
        "textos": agrupar(avisar, sesiones),
        "estado": estado,
        "costo_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


# ---------- línea de comandos: lee la API del server local ----------
def _get(base: str, ruta: str):
    with urllib.request.urlopen(base + ruta, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base: str, ruta: str, cuerpo: dict):
    req = urllib.request.Request(
        base + ruta,
        data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
        headers={"X-Lienzo": "1", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def main(argv: list | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ronda de auditoría de sesiones del lienzo")
    ap.add_argument("--base", default="http://127.0.0.1:7321")
    ap.add_argument("--estado", default=os.path.join(os.path.expanduser("~"), ".lienzo", "auditoria.json"))
    ap.add_argument("--enviar", action="store_true", help="manda el aviso agrupado a cada coordinadora")
    a = ap.parse_args(argv)
    try:
        with open(a.estado, encoding="utf-8") as f:
            previo = json.load(f)
    except OSError, ValueError:
        previo = {}
    r = ronda(_get(a.base, "/sessions"), _get(a.base, "/links"), previo)
    for destino, texto in r["textos"].items():
        print(f"== para {destino or 'nadie (repo sin coordinadora)'}\n{texto}")
        if a.enviar and destino:
            # sin_aviso: el turno que dispara este aviso no vuelve como aviso (evita bucles)
            _post(a.base, f"/sessions/{destino}/send", {"text": texto, "sin_aviso": True})
    print(
        json.dumps(
            {k: r[k] for k in ("ahora", "sesiones", "costo_ms")}
            | {
                "hallazgos": [(h["tipo"], (h.get("title") or "")[:50], h["minutos"]) for h in r["hallazgos"]],
                "avisados": len(r["avisar"]),
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    if a.enviar:
        with open(a.estado, "w", encoding="utf-8") as f:
            json.dump(r["estado"], f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
