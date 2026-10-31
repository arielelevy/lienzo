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
- `bloqueo_olvidado`: un frente cerró con `ESTADO: bloqueado` y sigue así pasado el vencimiento de su
  categoría (permiso 30 min, dependencia 60 min, pausa 4 h).
- `turno_cortado`: el frente quedó en `termino` con el turno cortado por un error (`last_error`), sin informe.
- `informe_no_entregado`: un frente cerró un turno con `ESTADO:` y su regla `on_stop` hacia la
  coordinadora está apagada (un borrado rechazado o un tope), así que el informe no le llegó. Caso de
  opensyync del 2026-10-25: la regla L→K quedó apagada 75 min y el informe final de L se perdió.

Espera legítima, que no avisa: `corriendo`, cuota agotada (`limit_until` futuro) y un bloqueo declarado
dentro de su vencimiento (`bloqueado_permiso`, `bloqueado_dependencia`, `bloqueado_pausa`: quedan en el
informe pero no en el aviso). También `espera_turno`: el frente está en la cola de un turno (`GET /turnos`)
y le llega un mensaje cuando le toca (openSeec, 2026-10-30: salía como `idle_evitable`).

Cuándo se avisa un frente quieto: a partir de `idle_min` (8 min). Con una ronda cada 5 min, el primer aviso
llega entre los 8 y los 13 min de quietud; el caso de los 4 CLIs quietos 14 min queda siempre cubierto.

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

if __package__:
    from . import huerfanos
else:
    import huerfanos

CFG = {
    "idle_min": 8,
    "envio_min": 2,
    "bloqueo_min": 5,
    "enfriamiento_min": 30,
    "olvido_h": 24,
    "vence_min": {"permiso": 30, "dependencia": 60, "pausa": 240},
}
AVISAN = (
    "idle_evitable",
    "entrega_sin_leer",
    "envio_no_tomado",
    "bloqueado_humano",
    "sin_coordinadora",
    "bloqueo_olvidado",
    "informe_no_entregado",
    "turno_cortado",
)
_BLOQUEADO = re.compile(r"ESTADO:\s*bloquead[oa]?(.*)", re.IGNORECASE | re.DOTALL)
_CATEGORIA = (
    ("permiso", re.compile(r"permis|aprobaci|autoriz|aprob[aá]", re.IGNORECASE)),
    ("pausa", re.compile(r"pausa|en espera de ariel|hasta (ma[nñ]ana|el lunes)|vuelvo", re.IGNORECASE)),
)


def categoria_bloqueo(texto: str) -> str:
    """De qué es el bloqueo que declaró el frente, por lo que dice después de `ESTADO: bloqueado`."""
    for nombre, patron in _CATEGORIA:
        if patron.search(texto):
            return nombre
    return "dependencia"


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


def validar_espera(d: dict) -> tuple[int, dict] | None:
    if not isinstance(d.get("from"), str) or not d["from"].strip():
        return 400, {"error": "falta from: coordinadora del repo"}
    if d.get("motivo") is None:
        return None  # cancelar
    motivo, hasta = d["motivo"], d.get("hasta")
    if not isinstance(motivo, str) or not motivo.strip() or len(motivo) > 500:
        return 400, {"error": "motivo debe tener entre 1 y 500 caracteres"}
    try:
        fecha = dt.datetime.fromisoformat(hasta) if isinstance(hasta, str) else None
    except ValueError:
        fecha = None
    if fecha is None or fecha.tzinfo is None or fecha <= dt.datetime.now(dt.UTC):
        return 400, {"error": "hasta debe ser una fecha ISO futura con zona horaria"}
    return None


def declarar_espera(s: dict, d: dict, todas: list) -> tuple[int, dict]:
    """Con el lock de sesiones tomado por el llamador; sólo la ★ viva del mismo repo."""
    if rechazo := validar_espera(d):
        return rechazo
    coordinadora = next((x for x in todas if x.get("session_id") == d["from"]), None)
    if not (
        coordinadora
        and coordinadora.get("coordinator")
        and coordinadora.get("alive")
        and coordinadora.get("state") != "muerta"
        and not coordinadora.get("stopped_by")
        and s.get("repo_key")
        and coordinadora.get("repo_key") == s["repo_key"]
    ):
        return 403, {"error": "sólo la coordinadora viva del mismo repo puede declarar la espera"}
    if d.get("motivo") is None:
        s.pop("espera_declarada", None)
    else:
        s["espera_declarada"] = {
            "por": d["from"],
            "motivo": d["motivo"].strip(),
            "hasta": d["hasta"],
            "prompt_id": s.get("prompt_id"),
            "last_prompt": s.get("last_prompt"),
            "state_since": s.get("state_since"),
        }
    return 200, {"ok": True, "espera_declarada": s.get("espera_declarada")}


def _espera_vigente(s: dict, coordinadora: dict | None) -> dict | None:
    espera = s.get("espera_declarada")
    if not isinstance(espera, dict) or not coordinadora or espera.get("por") != coordinadora["session_id"]:
        return None
    if any(espera.get(k) != s.get(k) for k in ("prompt_id", "last_prompt", "state_since")):
        return None
    return espera if _t(espera.get("hasta")) else None


def _regla_apagada(reglas: list, frente: str, coordinadora: str) -> dict | None:
    """La regla `on_stop` repetida de `frente` que está apagada y debería llevarle los informes a la
    coordinadora, si no hay otra viva hacia ella. Cuenta también la que quedó apuntando a una
    coordinadora anterior (cambió la ★ y la regla no la siguió); no las archivadas, ni las estacionadas
    que esperan a la sucesora de esta misma coordinadora."""
    del_frente = [r for r in reglas if r.get("kind") == "on_stop" and r.get("from") == frente]
    if any(r.get("enabled") and r.get("to") == coordinadora for r in del_frente):
        return None
    return next(
        (
            r
            for r in del_frente
            if r.get("repeat")
            and not r.get("enabled")
            and not r.get("archived_at")
            and not (r.get("parked_since") and r.get("to") == coordinadora)
        ),
        None,
    )


def _acusado(reglas: list, frente: str, coord: str, desde: dt.datetime | None) -> bool:
    """La coordinadora acusó recibo (o integró) un informe de la regla frente -> coordinadora después de
    la entrega `desde`: lo leyó aunque no le haya mandado nada (el informe le llega como adjunto)."""
    if desde is None:
        return False
    for r in reglas:
        if r.get("from") != frente or r.get("to") != coord:
            continue
        for i in r.get("informes") or ():
            marcas = [_t(i.get(k)) for k in ("recibido_at", "integrado_at")]
            if any(m is not None and m >= desde for m in marcas):
                return True
    return False


def clasificar(
    sesiones: list,
    links: list,
    ahora: dt.datetime,
    cfg: dict = CFG,
    reglas: list | None = None,
    turnos: dict | None = None,
) -> list:
    """Un hallazgo por sesión que no está trabajando ni en espera legítima. Sin efectos."""
    vivas = [s for s in sesiones if s.get("alive") and s.get("state") != "muerta" and not s.get("stopped_by")]
    coord = {s.get("repo_key"): s for s in vivas if s.get("coordinator")}
    reglas = reglas or []
    en_cola = {}  # sesión -> recurso cuyo turno espera
    for recurso, t in (turnos or {}).items():
        for x in (t or {}).get("cola") or []:
            if isinstance(x, dict) and x.get("session_id"):
                en_cola.setdefault(x["session_id"], recurso)
    con_regla = {}  # frente -> última entrega (link `rule`) hacia una coordinadora
    ultimo_a = {}  # sesión -> último envío o regla que recibió
    respuesta_a = {}  # sesión -> último envío, regla o mensaje nativo que recibió
    for ln in sorted(links, key=lambda x: x.get("ts") or ""):
        if ln.get("kind") in ("send", "rule") and ln.get("to"):
            ultimo_a[ln["to"]] = ln
        # un SendMessage de la coordinadora (`native`) también es responderle (openSeec, 2026-10-30)
        if ln.get("kind") in ("send", "rule", "native") and ln.get("to"):
            respuesta_a[ln["to"]] = ln
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
        c = coord.get(s.get("repo_key"))
        apagada = _regla_apagada(reglas, sid, c["session_id"]) if c and not s.get("coordinator") else None
        cola = (s.get("last_reply") or "")[-400:]
        # el informe llegó si hubo una entrega (link `rule`) de este frente después de su último turno:
        # cubre la regla que entregó y recién después se apagó (un borrado, el tope total)
        entregas = [_t(ln.get("ts")) for ln in con_regla.get(sid, {}).values()]
        entregado = any(t and desde and t >= desde for t in entregas)
        if (
            apagada
            and not entregado
            and (apagada.get("solo_si") or "ESTADO:") in cola
            and not _BLOQUEADO.search(cola)  # un bloqueo declarado sigue su camino (bloqueado_*, bloqueo_olvidado)
        ):
            # no espera a idle_min: cada minuto que pasa es un informe que la coordinadora no ve
            out.append(
                {
                    **base,
                    "tipo": "informe_no_entregado",
                    "evidencia": f"{apagada['id']}|{s.get('state_since')}",
                    "coordinadora": c["session_id"],
                    "sugerencia": f"su regla {apagada['id']} está apagada ({apagada.get('disabled_reason') or 'sin motivo'}): "
                    "leer su último informe en la tarjeta y reactivar o recablear la regla",
                }
            )
            continue
        if s.get("coordinator") or quieta < cfg["idle_min"]:
            continue
        if s.get("last_error") and estado == "termino":
            # el turno terminó por un error (del modelo o del servicio), no con su informe: no es un frente
            # ocioso sino caído (openSeec P, 2026-10-31: un grep sin `pattern` cortó la coda sin ESTADO:)
            out.append(
                {
                    **base,
                    "tipo": "turno_cortado",
                    "evidencia": s.get("state_since"),
                    "error": str(s["last_error"])[:200],
                    "coordinadora": c["session_id"] if c else None,
                    "sugerencia": "el turno se cortó con error: mandarle «Continuar» (o Reintentar en la tarjeta)",
                }
            )
            continue
        if espera := _espera_vigente(s, c):
            vencida = _t(espera["hasta"]) <= ahora
            out.append(
                {
                    **base,
                    "tipo": "bloqueo_olvidado" if vencida else "espera_declarada",
                    "coordinadora": c["session_id"],
                    "motivo": espera["motivo"],
                    "hasta": espera["hasta"],
                    "evidencia": f"{espera['por']}|{espera['hasta']}|{espera['motivo']}",
                    "sugerencia": "revisar la espera declarada por la coordinadora" if vencida else espera["motivo"],
                }
            )
            continue
        if m := _BLOQUEADO.search((s.get("last_reply") or "")[-400:]):
            cat = categoria_bloqueo(m.group(1))
            vencido = quieta >= cfg["vence_min"][cat]
            out.append(
                {
                    **base,
                    "tipo": "bloqueo_olvidado" if vencido else f"bloqueado_{cat}",
                    "categoria": cat,
                    "evidencia": s.get("state_since"),
                    "sugerencia": f"bloqueo de {cat} declarado hace {quieta:.0f} min: destrabarlo o reasignar"
                    if vencido
                    else "espera declarada por el frente; ver su último informe",
                }
            )
            continue
        if sid in en_cola:
            out.append(
                {
                    **base,
                    "tipo": "espera_turno",
                    "recurso": en_cola[sid],
                    "evidencia": s.get("state_since"),
                    "sugerencia": f"espera el turno de «{en_cola[sid]}»: le llega un mensaje cuando le toca",
                }
            )
            continue
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
        respuesta = respuesta_a.get(sid) or {}
        t_resp = _t(respuesta.get("ts"))
        respondio = (
            t_resp is not None and t_ent is not None and t_resp > t_ent and respuesta.get("from") == c["session_id"]
        ) or _acusado(reglas, sid, c["session_id"], t_ent)
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


def _coordinadoras(sesiones: list) -> dict:
    return {s.get("repo_key"): s["session_id"] for s in sesiones if s.get("coordinator") and s.get("alive")}


def _destino(h: dict, coord: dict) -> str | None:
    return h.get("coordinadora") or coord.get(h.get("repo"))


def agrupar(avisos: list, sesiones: list) -> dict:
    """Un texto por coordinadora (o `None` si el repo no tiene). Una sola línea por hallazgo."""
    coord = _coordinadoras(sesiones)
    por = {}
    for h in avisos:
        por.setdefault(_destino(h, coord), []).append(
            f"- {h['tipo']}: «{h.get('title') or h['session_id'][:8]}» hace {h['minutos']:.0f} min. {h['sugerencia']}."
        )
    return {
        d: "[auditoría del lienzo] " + str(len(ls)) + " sesiones para mirar:\n" + "\n".join(ls) for d, ls in por.items()
    }


def ronda(
    sesiones: list,
    links: list,
    previo: dict,
    ahora: dt.datetime | None = None,
    cfg: dict = CFG,
    reglas: list | None = None,
    turnos: dict | None = None,
) -> dict:
    ahora = ahora or dt.datetime.now().astimezone()
    t0 = time.perf_counter()
    hallazgos = clasificar(sesiones, links, ahora, cfg, reglas, turnos)
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


def _leer_estado(ruta: str) -> dict:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except OSError, ValueError:
        return {}


def ronda_local(base: str, ruta_estado: str, enviar: bool) -> dict:
    """Una ronda contra el server: audita sólo las sesiones de esta PC (cada PC audita lo suyo, así dos
    servers no avisan dos veces lo mismo) y, con `enviar`, manda un aviso por coordinadora. No le manda
    a una coordinadora que tiene ella misma un envío sin tomar: más texto no la destraba."""
    sesiones = _get(base, "/sessions")
    pares = _get(base, "/peers") or []
    pc = next((p.get("pc_id") for p in pares if p.get("local")), None)
    if enviar and recuperar_huerfanos(base, sesiones, pares, pc):
        sesiones = _get(base, "/sessions")
    caidas = {p["pc_id"] for p in pares if p.get("alive") is False}
    sesiones = [{**s, "alive": False} if s.get("pc") in caidas else s for s in sesiones]
    locales = {s["session_id"] for s in sesiones if not s.get("pc") or s.get("pc") == pc}
    ahora = dt.datetime.now().astimezone()
    t0 = time.perf_counter()
    try:
        reglas = _get(base, "/rules")
    except Exception as e:  # sin reglas se pierde sólo informe_no_entregado, no la ronda entera
        print(f"auditoria: no se pudieron leer las reglas ({type(e).__name__}: {e})", flush=True)
        reglas = []
    try:
        turnos = (_get(base, "/turnos") or {}).get("turnos") or {}
    except Exception as e:  # sin turnos, quien espera en una cola puede salir como idle_evitable
        print(f"auditoria: no se pudieron leer los turnos ({type(e).__name__}: {e})", flush=True)
        turnos = {}
    hallazgos = [
        h
        for h in clasificar(sesiones, _get(base, "/links"), ahora, reglas=reglas, turnos=turnos)
        if h["session_id"] in locales
    ]
    previo = _leer_estado(ruta_estado)
    avisar, estado = filtrar(hallazgos, previo, ahora)
    r = {
        "ahora": ahora.isoformat(timespec="seconds"),
        "sesiones": len(sesiones),
        "hallazgos": hallazgos,
        "avisar": avisar,
        "textos": agrupar(avisar, sesiones),
        "estado": estado,
        "costo_ms": round((time.perf_counter() - t0) * 1000, 2),
        "enviados": [],
        "fallidos": {},
    }
    trabadas = {h["session_id"] for h in hallazgos if h["tipo"] == "envio_no_tomado"}
    if not enviar:
        return r
    for destino, texto in r["textos"].items():
        if not destino or destino in trabadas:
            continue
        try:
            # sin `sin_aviso`: el server lo acepta sólo con un `from` de sesión y la auditoría no es una
            # sesión (2026-10-25: con `sin_aviso: true` solo, cada envío daba 400 y ningún aviso salía)
            _post(base, f"/sessions/{destino}/send", {"text": texto})
            r["enviados"].append(destino)
        except Exception as e:
            r["fallidos"][destino] = f"{type(e).__name__}: {e}"
    # lo que no se entregó no cuenta como avisado: vuelve a intentarse en la ronda siguiente
    coord = _coordinadoras(sesiones)
    for h in avisar:
        if _destino(h, coord) not in r["enviados"]:
            par = f"{h['tipo']}|{h['session_id']}"
            estado["emitidos"].pop(f"{par}|{h.get('evidencia')}", None)
            if (anterior := (previo.get("ultimo") or {}).get(par)) is not None:
                estado["ultimo"][par] = anterior
            else:
                estado["ultimo"].pop(par, None)
    with open(ruta_estado, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    return r


def recuperar_huerfanos(base: str, sesiones: list, pares: list, pc: str | None) -> bool:
    """La elección es global; sólo la PC de la elegida pide el traspaso al servidor."""
    caidas = {p["pc_id"] for p in pares if p.get("alive") is False}
    planes = huerfanos.planes(sesiones, _get(base, "/links"), _get(base, "/rules"), caidas)
    elegidas = {p["session_id"] for p in planes}
    planes.extend(
        {"session_id": s["session_id"]}
        for s in sesiones
        if (s.get("coordinator_proposal") or {}).get("kind") == "role" and s["session_id"] not in elegidas
    )
    locales = {s["session_id"] for s in sesiones if s.get("pc") == pc}
    cambios = False
    for plan in planes:
        if plan["session_id"] in locales:
            try:
                _post(base, f"/sessions/{plan['session_id']}/orphan", {})
                cambios = True
            except OSError as e:
                print(f"auditoria: no se pudo recuperar {plan['session_id']}: {type(e).__name__}: {e}", flush=True)
    return cambios


def bucle(base: str, cada_min: float, log, ruta_estado: str | None = None) -> None:
    """Hilo del server: una ronda cada `cada_min` (config `auditoria_min`, 5 por defecto; 0 la apaga).
    Sólo HTTP contra el propio server: no toca el registro de sesiones ni el lock."""
    ruta_estado = ruta_estado or os.path.join(os.path.expanduser("~"), ".lienzo", "auditoria.json")
    time.sleep(60)  # que el barrido inicial y el espejo lleguen antes de la primera ronda
    while True:
        try:
            r = ronda_local(base, ruta_estado, enviar=True)
            if r["avisar"]:
                log(
                    f"auditoria: {len(r['hallazgos'])} hallazgos, {len(r['avisar'])} avisados a "
                    f"{len(r['enviados'])} coordinadoras ({r['costo_ms']} ms)"
                )
            for destino, error in r["fallidos"].items():
                log(f"auditoria: no se pudo avisar a {destino[:8]} ({error}); se reintenta en la ronda siguiente")
        except Exception as e:
            log(f"auditoria: ronda fallida ({type(e).__name__}: {e})")
        time.sleep(cada_min * 60)


def main(argv: list | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ronda de auditoría de sesiones del lienzo")
    ap.add_argument("--base", default="http://127.0.0.1:7321")
    ap.add_argument("--estado", default=os.path.join(os.path.expanduser("~"), ".lienzo", "auditoria.json"))
    ap.add_argument("--enviar", action="store_true", help="manda el aviso agrupado a cada coordinadora")
    a = ap.parse_args(argv)
    r = ronda_local(a.base, a.estado, a.enviar)
    for destino, texto in r["textos"].items():
        print(f"== para {destino or 'nadie (repo sin coordinadora)'}\n{texto}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
