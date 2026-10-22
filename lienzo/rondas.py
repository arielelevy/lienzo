"""Primitivas de rondas largas (pedido de Ariel, 2026-10-16, aprendido en OpenSyync, olas 21-22):

- **Aviso coordinado** (`POST /avisos`): el mismo texto a N frentes con una lista de confirmaciones.
  Cada frente confirma cerrando su respuesta con `ACK <id>` (o `POST /avisos/<id>/ack`), y quien lo
  mando recibe UN solo aviso cuando confirmaron todos, o cuando vence con quienes faltan. Antes cada
  ida y vuelta de un cambio de contrato pasaba por la coordinadora, varios minutos por salto.
- **Turno de un recurso pesado** (`POST/DELETE /turnos/<recurso>`): navegador, suite, motores, pago.
  Un dueño con vencimiento, una cola visible y una guardia de memoria; se libera solo cuando vence o
  cuando la sesion dueña ya no esta. La coordinadora solo define la politica (`PUT .../politica`).
- **Presion de memoria** (`GET /memoria`): con la memoria libre bajo el umbral, que sesion quieta
  conviene cerrar; y el tope de sesiones vivas por repo que mira el lanzamiento.

Todo vive en `~/.lienzo/rondas.json` y se publica por SSE (`{"type": "rondas"}`). `revisar()` corre en
el bucle de las reglas (cada 5 s): confirma por respuesta, vence avisos y turnos, y pasa el turno."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets

import health
import identity
import sessions as ses
import state
from state import lock, now, short

RECURSO = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
TEXTO_MAX = 8000
NOTA_MAX = 300
AVISO_MAX_DESTINOS = 12
AVISO_VENCE_MIN, AVISO_VENCE_MAX_MIN = 60, 24 * 60
AVISOS_GUARDADOS = 50  # los cerrados mas viejos se van
TURNO_TTL_MIN, TURNO_TTL_MAX_MIN = 30, 240
MEM_AVISO_GB = 1.5  # config.json: mem_aviso_gb
MAX_SESIONES_POR_REPO = 0  # config.json: max_sesiones_por_repo; 0 = sin tope (decision de Ariel, 2026-10-16)

_datos: dict = {"avisos": {}, "turnos": {}, "politicas": {}}


def _path() -> str:
    return os.path.join(state.LIENZO, "rondas.json")


def cargar() -> None:
    d, err = state.leer_json(_path())
    if err is None and isinstance(d, dict):
        with lock:
            for k in _datos:
                if isinstance(d.get(k), dict):
                    _datos[k] = d[k]


def _guardar() -> None:
    """Con el lock tomado. Poda los avisos cerrados viejos. Nunca levanta."""
    avisos = _datos["avisos"]
    cerrados = sorted((a.get("creado") or "", k) for k, a in avisos.items() if a.get("estado") != "abierto")
    for _, k in cerrados[: max(0, len(avisos) - AVISOS_GUARDADOS)]:
        avisos.pop(k, None)
    try:
        state.atomic_write(_path(), json.dumps(_datos, ensure_ascii=False, indent=1))
    except OSError as e:
        state.log(f"no se pudo guardar rondas.json: {e}")


def vista() -> dict:
    with lock:
        avisos = sorted(_datos["avisos"].values(), key=lambda a: a.get("creado") or "", reverse=True)
        return json.loads(json.dumps({"avisos": avisos, "turnos": _datos["turnos"], "politicas": _datos["politicas"]}))


def _publicar() -> None:
    state.broadcast({"type": "rondas", **vista()})


def _ahora() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _iso(d: dt.datetime) -> str:
    return d.isoformat(timespec="seconds")


def _vencio(valor) -> bool:
    try:
        return dt.datetime.fromisoformat(str(valor)) <= _ahora()
    except TypeError, ValueError:
        return True


def _sesion(sid: str) -> tuple[str, dict | None]:
    """(id vigente, tarjeta): si `sid` quedo viejo, la sucesora (ses.sucesora_de)."""
    s = ses.find_session(sid)
    if s is None and (nueva := ses.sucesora_de(sid)):
        return nueva, ses.find_session(nueva)
    return sid, s


def _nombre(sid: str) -> str:
    s = ses.find_session(sid)
    return short((s or {}).get("title") or (s or {}).get("repo") or sid[:8], 60)


def _mandar(sid: str | None, texto: str) -> tuple[int, dict]:
    if not sid:
        return 404, {"error": "sin destino"}
    sid, s = _sesion(sid)
    if s is None:
        state.log(f"rondas: no se pudo avisar a {sid[:8]}: la sesion no se ve")
        return 404, {"error": "sesion desconocida"}
    return ses.send_to_session(s, texto, [])


def _avisar(sid: str | None, texto: str) -> None:
    """_mandar en un hilo: cada envio puede tardar hasta 60 s, y esto corre en el bucle de reglas o en
    un pedido HTTP (un ack, soltar un turno) que no puede quedar esperando la consola de otro."""
    if sid:
        ses.en_hilo(_mandar, sid, texto)


def _vigente(sid: str) -> str:
    """El id de hoy de `sid`: el mismo, o su sucesora si se restauro con otro."""
    return _sesion(sid)[0]


# --- avisos coordinados ------------------------------------------------------------------------


def marca_ack(aid: str) -> str:
    return f"ACK {aid}"


def _texto_aviso(a: dict) -> str:
    n = len(a["destinos"])
    return (
        f"[aviso coordinado {a['id']}: lo reciben {n} frentes a la vez]\n{a['texto']}\n\n"
        f"Cuando lo hayas aplicado, cerrá tu respuesta con una línea «{marca_ack(a['id'])}» y, si hace falta, "
        "una nota corta en la misma línea. No les escribas a los otros frentes: el lienzo junta las "
        "confirmaciones y avisa una sola vez."
    )


def crear_aviso(d: dict) -> tuple[int, dict]:
    """POST /avisos {texto, a: [session_id...], de?, vence_min?}. 200 con el aviso; los envios salen
    en hilos (cada uno puede tardar hasta 60 s) y su resultado queda en `destinos`."""
    texto, destinos, de = d.get("texto"), d.get("a"), d.get("de") or None
    if not isinstance(texto, str) or not texto.strip() or len(texto) > TEXTO_MAX:
        return 400, {"error": f"texto debe ser un texto de 1 a {TEXTO_MAX} caracteres"}
    if not isinstance(destinos, list) or not 1 <= len(destinos) <= AVISO_MAX_DESTINOS:
        return 400, {"error": f"a debe ser una lista de 1 a {AVISO_MAX_DESTINOS} session_id"}
    if not all(isinstance(x, str) and x for x in destinos) or len(set(destinos)) != len(destinos):
        return 400, {"error": "a: session_id repetidos o vacios"}
    if de is not None and not isinstance(de, str):
        return 400, {"error": "de debe ser un session_id"}
    vence = d.get("vence_min", AVISO_VENCE_MIN)
    if isinstance(vence, bool) or not isinstance(vence, int) or not 1 <= vence <= AVISO_VENCE_MAX_MIN:
        return 400, {"error": f"vence_min debe ser un entero entre 1 y {AVISO_VENCE_MAX_MIN}"}
    vigentes = [_sesion(x) for x in destinos]
    faltan = [x for x, (_, s) in zip(destinos, vigentes, strict=True) if s is None]
    if faltan:
        return 404, {"error": "sesiones desconocidas", "faltan": faltan}
    if len({sid for sid, _ in vigentes}) != len(vigentes):
        # un id viejo y su sucesora son la misma sesion: recibiria el aviso dos veces
        return 400, {"error": "a: dos ids son la misma sesion (una es la sucesora de la otra)"}
    if de is not None and _vigente(de) in {sid for sid, _ in vigentes}:
        return 400, {"error": "quien manda el aviso no puede ser destino"}
    aid = "av-" + secrets.token_hex(4)
    aviso = {
        "id": aid,
        "texto": texto,
        "de": de,
        "creado": now(),
        "vence": _iso(_ahora() + dt.timedelta(minutes=vence)),
        "estado": "abierto",
        "destinos": {sid: {"estado": "enviando", "ts": now(), "nota": None} for sid, _ in vigentes},
    }
    with lock:
        _datos["avisos"][aid] = aviso
        _guardar()
    state.log(f"aviso {aid} a {len(vigentes)} frentes: {short(texto, 60)!r}")
    _publicar()
    for sid, _ in vigentes:
        ses.en_hilo(_entregar, aid, sid)
    return 200, vista_aviso(aid)


def vista_aviso(aid: str) -> dict | None:
    with lock:
        a = _datos["avisos"].get(aid)
        return json.loads(json.dumps(a)) if a else None


def _entregar(aid: str, sid: str) -> None:
    with lock:
        a = _datos["avisos"].get(aid)
        texto = _texto_aviso(a) if a else None
    if texto is None:
        return
    code, res = _mandar(sid, texto)
    with lock:
        dest = (_datos["avisos"].get(aid) or {}).get("destinos", {}).get(sid)
        if dest is not None and dest["estado"] == "enviando":
            dest["estado"] = "enviado" if code == 200 else "fallo"
            dest["ts"] = now()
            if code != 200:
                dest["nota"] = short(str(res.get("error") if isinstance(res, dict) else res), NOTA_MAX)
        de = (_datos["avisos"].get(aid) or {}).get("de")
        _guardar()
    if code == 200 and de:
        ses.add_link(de, sid, texto, kind="send")
    state.log(f"aviso {aid} -> {sid[:8]}: {'ok' if code == 200 else res}")
    _publicar()


def ack(aid: str, sid: str, nota: str | None = None, por: str = "api") -> tuple[int, dict]:
    """POST /avisos/<id>/ack {session_id, nota?}. Una sesion restaurada confirma por la vieja."""
    if not isinstance(sid, str) or not sid:
        return 400, {"error": "falta session_id"}
    if nota is not None and not isinstance(nota, str):
        return 400, {"error": "nota debe ser un texto"}
    with lock:
        a = _datos["avisos"].get(aid)
        if a is None:
            return 404, {"error": "aviso desconocido"}
        clave = sid if sid in a["destinos"] else next((k for k in a["destinos"] if ses.sucesora_de(k) == sid), None)
        if clave is None:
            return 404, {"error": "esa sesion no recibio el aviso"}
        if a["estado"] != "abierto":
            return 409, {"error": f"el aviso ya esta {a['estado']}", "estado": a["estado"]}
        a["destinos"][clave].update(
            estado="confirmado", ts=now(), nota=short(nota, NOTA_MAX) if nota else None, por=por
        )
        _guardar()
    state.log(f"aviso {aid}: confirmo {sid[:8]} ({por})")
    _cerrar_si_completo(aid)
    _publicar()
    return 200, vista_aviso(aid)


def _cerrar_si_completo(aid: str) -> None:
    with lock:
        a = _datos["avisos"].get(aid)
        if not a or a["estado"] != "abierto" or any(x["estado"] != "confirmado" for x in a["destinos"].values()):
            return
        a["estado"], a["cerrado"] = "completo", now()
        _guardar()
        resumen = dict(a)
    lineas = [
        f"- {_nombre(sid)}" + (f": {x['nota']}" if x.get("nota") else "") for sid, x in resumen["destinos"].items()
    ]
    texto = f"[lienzo] aviso {aid} confirmado por los {len(lineas)} frentes:\n" + "\n".join(lineas)
    state.log(f"aviso {aid} completo")
    _avisar(resumen.get("de"), texto)


def _ack_en_respuesta(aid: str, s: dict) -> str | None:
    """La linea con `ACK <id>` de la ultima respuesta cerrada de la tarjeta (sin el marcador), o None."""
    if s.get("state") == "corriendo":
        return None
    marca = marca_ack(aid)
    for linea in reversed((s.get("last_reply") or "").splitlines()):
        if marca in linea:
            return linea.split(marca, 1)[1].strip(" :-—·`*") or ""
    return None


def _revisar_avisos() -> None:
    with lock:
        abiertos = [(a["id"], dict(a["destinos"])) for a in _datos["avisos"].values() if a["estado"] == "abierto"]
    for aid, destinos in abiertos:
        for sid, x in destinos.items():
            if x["estado"] != "enviado":
                continue
            _, s = _sesion(sid)
            nota = _ack_en_respuesta(aid, s) if s else None
            if nota is not None:
                ack(aid, sid, nota or None, por="respuesta")
        with lock:
            a = _datos["avisos"].get(aid)
            if not a or a["estado"] != "abierto" or not _vencio(a["vence"]):
                continue
            a["estado"], a["cerrado"] = "vencido", now()
            _guardar()
            faltan = [sid for sid, x in a["destinos"].items() if x["estado"] != "confirmado"]
            de = a.get("de")
        state.log(f"aviso {aid} vencido: faltan {len(faltan)}")
        if de:
            nombres = "\n".join(f"- {_nombre(sid)} ({destinos[sid]['estado']})" for sid in faltan)
            _avisar(de, f"[lienzo] aviso {aid} vencido sin todas las confirmaciones. Faltan:\n{nombres}")
        _publicar()


# --- turnos de recursos pesados ----------------------------------------------------------------


def politica(recurso: str) -> dict:
    with lock:
        p = dict(_datos["politicas"].get(recurso) or {})
    return {"ttl_max_min": TURNO_TTL_MAX_MIN, "mem_min_gb": 0.0, **p}


def fijar_politica(recurso: str, d: dict) -> tuple[int, dict]:
    """PUT /turnos/<recurso>/politica {ttl_max_min?, mem_min_gb?}: lo decide la coordinadora."""
    if not RECURSO.fullmatch(recurso or ""):
        return 400, {"error": "recurso: minusculas, numeros, - y _, hasta 32"}
    p = politica(recurso)
    ttl = d.get("ttl_max_min", p["ttl_max_min"])
    mem = d.get("mem_min_gb", p["mem_min_gb"])
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 24 * 60:
        return 400, {"error": "ttl_max_min debe ser un entero entre 1 y 1440"}
    if isinstance(mem, bool) or not isinstance(mem, (int, float)) or not 0 <= mem <= 256:
        return 400, {"error": "mem_min_gb debe ser un numero entre 0 y 256"}
    with lock:
        _datos["politicas"][recurso] = {"ttl_max_min": ttl, "mem_min_gb": float(mem), "por": d.get("por"), "ts": now()}
        _guardar()
    _publicar()
    return 200, politica(recurso)


def _memoria_libre() -> float | None:
    try:
        return health._memoria()[0]
    except OSError:
        return None


def _memoria_ok(recurso: str) -> tuple[bool, str]:
    minimo = politica(recurso)["mem_min_gb"]
    if not minimo:
        return True, ""
    libre = _memoria_libre()
    if libre is None or libre >= minimo:  # sin dato no se frena a ciegas (como restaurar)
        return True, ""
    return False, f"memoria libre {libre:.1f} GB, la politica pide {minimo:g} GB"


def _turno(recurso: str) -> dict:
    return _datos["turnos"].setdefault(recurso, {"dueno": None, "cola": []})


def pedir_turno(recurso: str, d: dict) -> tuple[int, dict]:
    """POST /turnos/<recurso> {session_id, ttl_min?, motivo?}: 200 `otorgado` (o renovado si ya era
    suyo), 202 en cola con su posicion. Quien espera recibe un mensaje cuando le toca."""
    if not RECURSO.fullmatch(recurso or ""):
        return 400, {"error": "recurso: minusculas, numeros, - y _, hasta 32"}
    sid, motivo = d.get("session_id"), d.get("motivo")
    if not isinstance(sid, str) or not sid:
        return 400, {"error": "falta session_id"}
    if motivo is not None and not isinstance(motivo, str):
        return 400, {"error": "motivo debe ser un texto"}
    sid, s = _sesion(sid)
    if s is None:
        return 404, {"error": "sesion desconocida"}
    tope = politica(recurso)["ttl_max_min"]
    ttl = d.get("ttl_min", min(TURNO_TTL_MIN, tope))
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= tope:
        return 400, {"error": f"ttl_min debe ser un entero entre 1 y {tope}"}
    pedido = {"session_id": sid, "ttl_min": ttl, "motivo": short(motivo, 200) if motivo else None, "pedido": now()}
    with lock:
        t = _turno(recurso)
        dueno = t["dueno"]
        if dueno and _vigente(dueno["session_id"]) == sid:
            dueno["vence"] = _iso(_ahora() + dt.timedelta(minutes=ttl))
            _guardar()
            out = (200, {"otorgado": True, "renovado": True, "recurso": recurso, **dueno})
        elif any(_vigente(x["session_id"]) == sid for x in t["cola"]):
            pos = 1 + next(i for i, x in enumerate(t["cola"]) if _vigente(x["session_id"]) == sid)
            out = (202, {"otorgado": False, "recurso": recurso, "posicion": pos, "dueno": dueno})
        else:
            ok, porque = _memoria_ok(recurso)
            if dueno is None and not t["cola"] and ok:
                t["dueno"] = _otorgar(pedido)
                _guardar()
                out = (200, {"otorgado": True, "recurso": recurso, **t["dueno"]})
            else:
                t["cola"].append(pedido)
                _guardar()
                espera = porque if dueno is None and not ok else "ocupado"
                out = (
                    202,
                    {
                        "otorgado": False,
                        "recurso": recurso,
                        "posicion": len(t["cola"]),
                        "dueno": dueno,
                        "espera": espera,
                    },
                )
    state.log(f"turno {recurso}: {sid[:8]} {'lo tiene' if out[0] == 200 else 'en cola'}")
    _publicar()
    return out


def _otorgar(pedido: dict) -> dict:
    ahora = _ahora()
    return {
        "session_id": pedido["session_id"],
        "motivo": pedido.get("motivo"),
        "desde": _iso(ahora),
        "vence": _iso(ahora + dt.timedelta(minutes=pedido["ttl_min"])),
    }


def liberar_turno(recurso: str, sid: str, por: str = "api") -> tuple[int, dict]:
    """DELETE /turnos/<recurso> {session_id}: suelta el turno (o sale de la cola) y pasa al siguiente."""
    if not isinstance(sid, str) or not sid:
        return 400, {"error": "falta session_id"}
    sid = _vigente(sid)
    with lock:
        t = _datos["turnos"].get(recurso)
        if t and t["dueno"] and _vigente(t["dueno"]["session_id"]) == sid:
            t["dueno"] = None
        elif t and any(_vigente(x["session_id"]) == sid for x in t["cola"]):
            t["cola"] = [x for x in t["cola"] if _vigente(x["session_id"]) != sid]
        else:
            return 404, {"error": "esa sesion no tiene ni espera ese turno"}
        _guardar()
    state.log(f"turno {recurso}: {sid[:8]} lo suelta ({por})")
    _pasar_turno(recurso)
    _publicar()
    return 200, {"recurso": recurso, **(_datos["turnos"].get(recurso) or {})}


def _pasar_turno(recurso: str) -> None:
    with lock:
        t = _datos["turnos"].get(recurso)
        if not t or t["dueno"] or not t["cola"] or not _memoria_ok(recurso)[0]:
            return
        t["dueno"] = _otorgar(t["cola"].pop(0))
        _guardar()
        dueno = dict(t["dueno"])
    hora = dt.datetime.fromisoformat(dueno["vence"]).strftime("%H:%M")
    state.log(f"turno {recurso}: pasa a {dueno['session_id'][:8]}")
    _avisar(
        dueno["session_id"],
        f"[lienzo] te toca el turno de «{recurso}» (vence a las {hora}). Al terminar, soltalo: "
        f"DELETE /turnos/{recurso} o coordinar.liberar_turno('{recurso}', <tu session_id>).",
    )


def _viva(sid: str) -> bool:
    _, s = _sesion(sid)
    return bool(s) and s.get("alive") is not False and s.get("state") != "muerta"


def _revisar_turnos() -> None:
    with lock:
        recursos = list(_datos["turnos"])
    for recurso in recursos:
        avisar = None
        with lock:
            t = _datos["turnos"][recurso]
            cola = [x for x in t["cola"] if _viva(x["session_id"])]
            cambio = len(cola) != len(t["cola"])
            t["cola"] = cola
            for x in [*cola, *([t["dueno"]] if t["dueno"] else [])]:
                # una sesion restaurada con otro id sigue siendo la misma en el turno y en la cola
                if (nuevo := _vigente(x["session_id"])) != x["session_id"]:
                    x["session_id"], cambio = nuevo, True
            d = t["dueno"]
            if d and (not _viva(d["session_id"]) or _vencio(d["vence"])):
                motivo = "vencio" if _viva(d["session_id"]) else "la sesion duena ya no esta"
                t["dueno"], cambio = None, True
                state.log(f"turno {recurso}: liberado ({motivo}, {d['session_id'][:8]})")
                if motivo == "vencio":
                    avisar = d["session_id"]
            if cambio:
                _guardar()
        if avisar:
            _avisar(avisar, f"[lienzo] tu turno de «{recurso}» vencio y paso al siguiente; si seguis, pedilo de nuevo.")
        if cambio:
            _pasar_turno(recurso)
            _publicar()
        elif t["cola"] and not t["dueno"]:
            _pasar_turno(recurso)  # esperaba memoria: puede que ya alcance


# --- presion de memoria ------------------------------------------------------------------------


def _config_num(clave: str, defecto: float) -> float:
    v = state.load_config().get(clave, defecto)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else defecto


def presion() -> dict:
    """GET /memoria: memoria libre de esta PC, si esta bajo el umbral (`mem_aviso_gb`) y las sesiones
    quietas que conviene cerrar primero: vivas, terminadas, sin ser coordinadora, sin turno ni aviso
    pendiente, la que lleva mas tiempo quieta primero. Sugerencia: no cierra nada."""
    libre = _memoria_libre()
    umbral = _config_num("mem_aviso_gb", MEM_AVISO_GB)
    with lock:
        pendientes = {
            sid
            for a in _datos["avisos"].values()
            if a["estado"] == "abierto"
            for sid, x in a["destinos"].items()
            if x["estado"] != "confirmado"
        }
        duenos = {(t.get("dueno") or {}).get("session_id") for t in _datos["turnos"].values()}
        quietas = [
            {
                "session_id": s["session_id"],
                "title": s.get("title"),
                "repo": s.get("repo"),
                "agent": s.get("agent"),
                "quieta_desde": s.get("state_since"),
            }
            for s in state.sessions.values()
            if s.get("alive")
            and s.get("state") == "termino"
            and not s.get("coordinator")
            and s["session_id"] not in pendientes | duenos
        ]
    quietas.sort(key=lambda x: x.get("quieta_desde") or "")
    return {
        "mem_free_gb": round(libre, 2) if libre is not None else None,
        "umbral_gb": umbral,
        "bajo": libre is not None and libre < umbral,
        "cerrar": quietas[:3],
        "max_sesiones_por_repo": int(_config_num("max_sesiones_por_repo", MAX_SESIONES_POR_REPO)),
    }


def tope_repo(cwd: str, todas: list[dict]) -> dict | None:
    """Si lanzar otra sesion en `cwd` pasa el tope de sesiones vivas por repo (todas las PCs), el
    rechazo para el 409; None si entra. `todas` son las tarjetas de GET /sessions."""
    tope = int(_config_num("max_sesiones_por_repo", MAX_SESIONES_POR_REPO))
    if not tope:
        return None
    # por repo_key, y por carpeta: lanzando en otra PC, la ruta puede no existir aca y la clave local
    # cae al nombre de la carpeta, que no coincide con el remote de las tarjetas de alla
    clave, carpeta = identity.repo_key(cwd), identity.norm_cwd(cwd)
    vivas = [
        s
        for s in todas
        if s.get("alive")
        and s.get("state") != "muerta"
        and ((clave and s.get("repo_key") == clave) or (carpeta and identity.norm_cwd(s.get("cwd")) == carpeta))
    ]
    if len(vivas) < tope:
        return None
    return {
        "error": f"ya hay {len(vivas)} sesiones vivas en este repo (tope {tope}, max_sesiones_por_repo): "
        "cerrá una quieta o mandá forzar: true",
        "code": "tope_repo",
        "vivas": [{"session_id": s["session_id"], "title": s.get("title"), "state": s.get("state")} for s in vivas],
    }


def revisar() -> None:
    """Del bucle de reglas, cada 5 s. Cada parte por separado: una que levanta no frena a la otra."""
    for paso in (_revisar_avisos, _revisar_turnos):
        try:
            paso()
        except Exception:
            import traceback

            state.log(f"rondas, {paso.__name__}:\n{traceback.format_exc()}")
