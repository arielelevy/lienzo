"""Consulta entre investigadores (docs/specs/consulta-investigadores): dos o tres agentes piensan un
problema dificil por vueltas y un revisor sintetiza. El lienzo media cada vuelta por el envio de siempre
(se teclea, deja flecha `kind: "consulta"`), lleva la cuenta y pone el tope: ninguna tarjeta le escribe
a otra, asi que no hay bucle A<->B posible.

El avance lo dispara el cierre de turno (rules.fire_on_stop -> turno_cerrado) y, para lo que ese gancho
no ve (una tarjeta de otra PC, una respuesta llegada con el server caido), vigilar() cada 30 s. Las dos
vias pasan por _tomar, que es idempotente.

Estado en memoria (CONSULTAS, con state.lock) y en disco en ~/.lienzo/consultas/<id>/: consulta.json,
un .md por respuesta y sintesis.md.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import threading
import time

import state
from state import LIENZO, lock, now, parse_ts, short

DIR = os.path.join(LIENZO, "consultas")
VUELTAS_DEFECTO, VUELTAS_MAX = 2, 3
ESPERA_DEFECTO_MIN = 30
SIN_CAMBIOS = "SIN CAMBIOS"
REPRESENTA = "REPRESENTA BIEN"
VIGILAR_CADA_S = 30.0
ABIERTAS = ("abierta", "sintetizando", "revisando", "corrigiendo")
TEXTO_MAX = 200_000  # una respuesta entera de una vuelta (rules.full_reply recorta a 6000 por defecto)

CONSULTAS: dict[str, dict] = {}
# los cablea server.py al arrancar: enviar(sid, texto, de, cid) -> (code, out) por el envio del tablero
# (local o reenviado a la PC duena, con la flecha de la consulta); y la tarjeta (local o espejada)
enviar = None
tarjeta = None
_ultima_vigilancia = 0.0


# --- guardar y leer ------------------------------------------------------------------------------


def _carpeta(cid: str) -> str:
    return os.path.join(DIR, os.path.basename(cid))


def _guardar(c: dict) -> None:
    """A disco y al tablero (SSE `consulta`). Con el lock tomado: es un RLock y broadcast lo vuelve a tomar."""
    os.makedirs(_carpeta(c["id"]), exist_ok=True)
    state.atomic_write(os.path.join(_carpeta(c["id"]), "consulta.json"), json.dumps(c, ensure_ascii=False, indent=1))
    state.broadcast({"type": "consulta", "consulta": resumen(c)})


def _guardar_md(cid: str, nombre: str, texto: str) -> None:
    os.makedirs(_carpeta(cid), exist_ok=True)
    state.atomic_write(os.path.join(_carpeta(cid), nombre), texto)


def cargar() -> None:
    """Al arrancar: las consultas de disco, para seguir las abiertas desde la vuelta en que estaban."""
    if not os.path.isdir(DIR):
        return
    for nombre in os.listdir(DIR):
        ruta = os.path.join(DIR, nombre, "consulta.json")
        if not os.path.isfile(ruta):
            continue
        c, err = state.leer_json(ruta)
        if err or not isinstance(c, dict) or "id" not in c:
            state.apartar_corrupto(ruta, err or "sin id")
            continue
        with lock:
            CONSULTAS[c["id"]] = c


# --- vistas --------------------------------------------------------------------------------------


def resumen(c: dict) -> dict:
    """Lo que necesita el tablero para pintar roles y estado, sin las respuestas enteras."""
    faltan = sorted(c["pendientes"])
    return {
        "id": c["id"],
        "pregunta": short(c["pregunta"], 200),
        "estado": c["estado"],
        "vuelta": c["vuelta"],
        "vueltas": c["vueltas"],
        "investigadores": c["investigadores"],
        "revisor": c["revisor"],
        "coordinador": c["coordinador"],
        "nombres": c["nombres"],
        "esperando": [c["nombres"].get(s, s[:8]) for s in faltan],
        "pendientes": faltan,
        "fuera": c["fuera"],
        "motivo": c["motivo"],
        "creada": c["creada"],
        "cerrada": c["cerrada"],
    }


def listar(limite: int = 20) -> list[dict]:
    with lock:
        todas = sorted(CONSULTAS.values(), key=lambda c: c["creada"], reverse=True)[:limite]
        return [resumen(c) for c in todas]


def ver(cid: str) -> dict | None:
    with lock:
        c = CONSULTAS.get(cid)
        return json.loads(json.dumps(c)) if c else None


def espera(sid: str) -> bool:
    """¿Alguna consulta abierta espera una respuesta de `sid`? Barato: rules lo mira en cada cierre de turno."""
    with lock:
        return any(c["estado"] in ABIERTAS and sid in c["pendientes"] for c in CONSULTAS.values())


def de_tarjeta(sid: str) -> dict | None:
    with lock:
        c = next((c for c in CONSULTAS.values() if c["estado"] in ABIERTAS and sid in _participantes(c)), None)
        return resumen(c) if c else None


def _participantes(c: dict) -> list[str]:
    return [*c["investigadores"], *([c["revisor"]] if c["revisor"] else [])]


# --- abrir ---------------------------------------------------------------------------------------


def _nombre(s: dict) -> str:
    agente = {"claude": "Claude", "codex": "Codex", "coda": "coda", "pi": "Pi", "kiro": "Kiro"}.get(s.get("agent"), "?")
    modelo = (s.get("model") or "").split("/")[-1]
    return f"{agente} ({modelo})" if modelo else agente


def _rechazo(msg: str, code: int = 400) -> tuple[int, dict]:
    return code, {"ok": False, "error": msg}


def abrir(d: dict) -> tuple[int, dict]:
    """POST /consultas. Valida todo antes de mandar nada (1.2, 1.3) y manda la vuelta 1 a la vez."""
    pregunta = d.get("pregunta")
    inv = d.get("investigadores")
    revisor = d.get("revisor")
    coordinador = d.get("coordinador")
    if not isinstance(pregunta, str) or not pregunta.strip():
        return _rechazo("falta la pregunta")
    if not isinstance(inv, list) or not all(isinstance(x, str) for x in inv) or not 2 <= len(inv) <= 3:
        return _rechazo("hacen falta 2 o 3 investigadores")
    if len(set(inv)) != len(inv) or (revisor and revisor in inv):
        return _rechazo("un investigador repetido (o el revisor es también investigador)")
    vueltas = d.get("vueltas", VUELTAS_DEFECTO)
    if not isinstance(vueltas, int) or isinstance(vueltas, bool) or not 1 <= vueltas <= VUELTAS_MAX:
        return _rechazo(f"vueltas va de 1 a {VUELTAS_MAX}")
    espera = d.get("espera_min", ESPERA_DEFECTO_MIN)
    if not isinstance(espera, int) or isinstance(espera, bool) or espera < 1:
        return _rechazo("espera_min tiene que ser un entero positivo")
    enfoques = d.get("enfoques") or {}
    if not isinstance(enfoques, dict):
        return _rechazo("enfoques es {sid: texto}")
    # una vuelta 1 ya hecha a mano (por el envio de siempre): se guarda y la consulta sigue desde la 2
    previa = d.get("vuelta1") or {}
    if (
        not isinstance(previa, dict)
        or (previa and set(previa) != set(inv))
        or not all(isinstance(v, str) and v.strip() for v in previa.values())
    ):
        return _rechazo("vuelta1 es {sid: respuesta} con una respuesta por investigador")
    todos = [*inv, *([revisor] if revisor else [])]
    tarjetas = {}
    for sid in todos:
        s = tarjeta(sid) if tarjeta else None
        if not s or not s.get("alive", True) or s.get("state") == "muerta":
            return _rechazo(f"no hay una tarjeta viva con id {sid[:8]}")
        if s.get("stopped_by"):
            return _rechazo(f"{sid[:8]} está detenida")
        tarjetas[sid] = s
    with lock:
        ocupadas = {p for c in CONSULTAS.values() if c["estado"] in ABIERTAS for p in _participantes(c)}
    if ocupadas & set(todos):
        return _rechazo(f"{min(ocupadas & set(todos))[:8]} ya está en otra consulta abierta")
    # solo los investigadores: el revisor recibe su pedido recien en la sintesis, y muchas veces es la
    # misma sesion que abre la consulta, que al abrirla figura corriendo (prueba de Teorema, 2026-10-10)
    corriendo = [sid for sid in inv if tarjetas[sid].get("state") == "corriendo"]
    if corriendo:
        return _rechazo(f"{corriendo[0][:8]} está trabajando: la consulta arranca con todos quietos", 409)

    nombres = {sid: _nombre(tarjetas[sid]) for sid in todos}
    for nombre in set(nombres.values()):  # dos «Claude (opus)»: se les suma la letra
        repetidos = [sid for sid in inv if nombres[sid] == nombre]
        if len(repetidos) > 1:
            for i, sid in enumerate(repetidos):
                nombres[sid] = f"{nombre} {'ABC'[i]}"
    if revisor:
        # el revisor aparte se nombra como tal: si no, «Claude (opus)» se confunde con un investigador
        nombres[revisor] = f"revisor · {nombres[revisor]}"
    cid = f"c-{dt.datetime.now():%Y%m%d}-{secrets.token_hex(3)}"
    c = {
        "id": cid,
        "pregunta": pregunta.strip(),
        "investigadores": inv,
        "revisor": revisor or inv[0],
        "coordinador": coordinador if isinstance(coordinador, str) and coordinador else None,
        "nombres": nombres,
        "vueltas": vueltas,
        "espera_min": espera,
        "enfoques": {k: v for k, v in enfoques.items() if k in inv and isinstance(v, str)},
        "revisar_sintesis": d.get("revisar_sintesis") is not False,
        "estado": "abierta",
        "vuelta": 1,
        "pendientes": {},
        "respuestas": {},
        "replicas": [],
        "sintesis": None,
        "objeciones": {},
        "fuera": {},
        "motivo": None,
        "creada": now(),
        "cerrada": None,
    }
    # el revisor que no es investigador se marca aparte; si no hay revisor, sintetiza el primero
    c["revisor_aparte"] = bool(revisor)
    with lock:
        CONSULTAS[cid] = c
        _guardar(c)
    if previa:
        with lock:
            c["respuestas"]["1"] = {
                sid: {
                    "texto": t.strip(),
                    "ts": now(),
                    "agente": tarjetas[sid].get("agent"),
                    "modelo": tarjetas[sid].get("model"),
                    "previa": True,
                }
                for sid, t in previa.items()
            }
            _guardar(c)
        for sid, t in previa.items():
            _guardar_md(cid, f"v1-{sid[:8]}.md", f"# {nombres[sid]}\n\n{t.strip()}\n")
        _avanzar(cid)
    else:
        _mandar_vuelta(cid, {sid: _pedido_vuelta1(c, sid) for sid in inv}, de=c["coordinador"])
    tope = len(inv) * vueltas + 1 + (len(inv) if c["revisar_sintesis"] else 0)
    state.log(f"consulta {cid}: abierta con {', '.join(nombres[s] for s in inv)}; revisor {nombres[c['revisor']]}")
    return 200, {"ok": True, "id": cid, "tope_turnos": tope}


# --- los pedidos ---------------------------------------------------------------------------------


REGLAS = (
    "Podés leer el repositorio y buscar en la web. NO edites ni crees archivos ni hagas commits: es una "
    "consulta para pensar. Distinguí lo probado de lo conjeturado. Cerrá con una línea «Confianza: alta|media|baja»."
)


def _marca(cid: str, etapa: str) -> str:
    return f"[consulta {cid} · {etapa}]"


def _pedido_vuelta1(c: dict, sid: str) -> str:
    otros = len(c["investigadores"]) - 1
    enfoque = c["enfoques"].get(sid)
    return "\n\n".join(
        x
        for x in (
            _marca(c["id"], "vuelta 1"),
            (
                f"Sos uno de {otros + 1} investigadores de una consulta del lienzo. Los otros reciben la misma "
                "pregunta a la vez; en la vuelta siguiente vas a ver sus respuestas y ellos la tuya."
            ),
            f"Pregunta:\n{c['pregunta']}",
            f"Tu enfoque: {enfoque}" if enfoque else "",
            REGLAS,
        )
        if x
    )


def _pedido_revision(c: dict, sid: str, n: int) -> str:
    otras = [
        f"### {c['nombres'][o]}\n\n{c['respuestas'][str(n)][o]['texto']}"
        for o in c["investigadores"]
        if o != sid and o in c["respuestas"].get(str(n), {})
    ]
    return "\n\n".join(
        (
            _marca(c["id"], f"vuelta {n + 1}"),
            f"Vuelta {n + 1} de {c['vueltas']}. Estas son las respuestas de los otros investigadores a la vuelta {n}:",
            *otras,
            (
                "Revisá la tuya con tres secciones: «Acepto» (qué y por qué), «Sostengo» (qué y por qué) y «Refuto» "
                "(con evidencia: código, una fuente o un contraejemplo). No cambies de posición sin una razón nueva. "
                f"Después tu respuesta corregida. Si la mantenés entera, escribí «{SIN_CAMBIOS}» en la primera línea."
            ),
            REGLAS,
        )
    )


def _todas_las_respuestas(c: dict) -> str:
    partes = []
    for n in sorted(c["respuestas"], key=int):
        for sid, r in c["respuestas"][n].items():
            partes.append(f"### Vuelta {n} · {c['nombres'][sid]}\n\n{r['texto']}")
    return "\n\n".join(partes)


def _pedido_sintesis(c: dict) -> str:
    return "\n\n".join(
        (
            _marca(c["id"], "síntesis"),
            "Sos el revisor de una consulta entre investigadores. Pregunta:",
            c["pregunta"],
            "Respuestas de todas las vueltas:",
            _todas_las_respuestas(c),
            (
                "Escribí la síntesis: «Acuerdos», «Desacuerdos» (quién sostiene qué, sin resolverlos a tu favor si "
                "participaste) y «Conclusión recomendada», con lo que falta para cerrarla. No edites archivos."
            ),
        )
    )


def _pedido_revisar_sintesis(c: dict) -> str:
    return "\n\n".join(
        (
            _marca(c["id"], "revisión"),
            f"Esta es la síntesis que escribió {c['nombres'][c['revisor']]} de la consulta en la que participaste:",
            c["sintesis"] or "",
            f"Contestá en una línea: «{REPRESENTA}», o la corrección de cómo quedó representada tu posición.",
        )
    )


# --- enviar --------------------------------------------------------------------------------------


def _enviar_uno(cid: str, sid: str, texto: str, de: str | None) -> tuple[int, dict]:
    """El envio de una sola tarjeta, con try/except: sin anotar pendiente ni sacar a nadie (eso lo
    deciden quienes lo llaman — `_mandar_vuelta` anota y saca, `replica` no toca nada)."""
    try:
        return enviar(sid, texto, de, cid) if enviar else (503, {"error": "sin envío cableado"})
    except Exception as e:
        return 500, {"error": f"{type(e).__name__}: {e}"}


def _mandar_vuelta(cid: str, pedidos: dict[str, str], de: str | None) -> None:
    """Manda los pedidos (uno por tarjeta) en paralelo y anota los pendientes con su marca. `de` es el
    origen de la flecha: el coordinador, o el investigador cuya respuesta se pasa (si es uno solo)."""
    with lock:
        c = CONSULTAS[cid]
        for sid, texto in pedidos.items():
            c["pendientes"][sid] = {"marca": texto.split("\n", 1)[0], "enviado": now()}
        _guardar(c)
    resultados: dict[str, tuple[int, dict]] = {}

    def uno(sid: str, texto: str) -> None:
        resultados[sid] = _enviar_uno(cid, sid, texto, de)  # un envio roto no corta a los demas

    hilos = [threading.Thread(target=uno, args=(sid, t), daemon=True) for sid, t in pedidos.items()]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(90)
    for sid in pedidos:
        code, out = resultados.get(sid, (504, {"error": "el envío no volvió"}))
        if code != 200:
            _sacar(cid, sid, f"el envío falló ({code}: {short(str(out.get('error') or out), 120)})")


def _avisar_coordinador(c: dict, texto: str) -> None:
    if c["coordinador"] and enviar:
        try:
            enviar(c["coordinador"], texto, None, c["id"])
        except Exception as e:
            state.log(f"consulta {c['id']}: no se pudo avisar al coordinador: {e}")


# --- respuestas y avance -------------------------------------------------------------------------


_ADJUNTO = re.compile(r"Adjunto:\s*(\S+\.md)")


def _es_respuesta(s: dict, marca: str) -> bool:
    """El ultimo pedido de la tarjeta es el de la consulta: la marca al principio de `last_prompt`, o el
    `mensaje.md` del adjunto (un mensaje largo se teclea como «Leé el archivo adjunto…») que empieza con ella."""
    p = (s.get("last_prompt") or "").lstrip()
    if p.startswith(marca):
        return True
    m = _ADJUNTO.search(p)
    if m and os.path.isfile(m.group(1)):
        try:
            with open(m.group(1), encoding="utf-8") as f:
                return f.read(len(marca) + 8).lstrip().startswith(marca)
        except OSError:
            return False
    return False


def _cerro_despues(s: dict, enviado: str) -> bool:
    cuando, desde = parse_ts(s.get("state_since")), parse_ts(enviado)
    return bool(cuando and desde and cuando >= desde)


def turno_cerrado(s: dict, texto: str) -> None:
    """Gancho de rules.fire_on_stop: la tarjeta `s` cerro turno con `texto` (la respuesta entera)."""
    sid = s.get("session_id")
    with lock:
        cid = next((c["id"] for c in CONSULTAS.values() if c["estado"] in ABIERTAS and sid in c["pendientes"]), None)
    if cid:
        _tomar(cid, sid, s, texto)


def _tomar(cid: str, sid: str, s: dict, texto: str) -> bool:
    """Guarda la respuesta de `sid` si es la que la consulta espera (idempotente) y avanza."""
    with lock:
        c = CONSULTAS.get(cid)
        p = (c or {}).get("pendientes", {}).get(sid)
        if not c or not p or c["estado"] not in ABIERTAS:
            return False
        if not _es_respuesta(s, p["marca"]) or not _cerro_despues(s, p["enviado"]):
            return False
        del c["pendientes"][sid]
        etapa = c["estado"]
        if etapa == "abierta":
            n = str(c["vuelta"])
            c["respuestas"].setdefault(n, {})[sid] = {
                "texto": texto,
                "ts": now(),
                "agente": s.get("agent"),
                "modelo": s.get("model"),
            }
            nombre_md = f"v{n}-{sid[:8]}.md"
        elif etapa == "sintetizando":
            c["sintesis"] = texto
            nombre_md = "sintesis-borrador.md"
        elif etapa == "corrigiendo":
            c["sintesis_previa"], c["sintesis"] = c["sintesis"], texto
            nombre_md = "sintesis-corregida.md"
        else:
            c["objeciones"][sid] = texto.strip()
            nombre_md = f"revision-{sid[:8]}.md"
        _guardar(c)
    _guardar_md(cid, nombre_md, f"# {c['nombres'].get(sid, sid)}\n\n{texto}\n")
    state.log(f"consulta {cid}: respondió {c['nombres'].get(sid, sid[:8])} ({etapa}, vuelta {c['vuelta']})")
    _avanzar(cid)
    return True


def _avanzar(cid: str) -> None:
    """Con todos los pendientes contestados: la vuelta siguiente, la sintesis, la revision o el cierre."""
    with lock:
        c = CONSULTAS.get(cid)
        if not c or c["pendientes"] or c["estado"] not in ABIERTAS:
            return
        estado, n = c["estado"], c["vuelta"]
        activos = [i for i in c["investigadores"] if i not in c["fuera"]]
    if estado == "abierta":
        resp = c["respuestas"].get(str(n), {})
        convergio = n > 1 and all((resp[i]["texto"].lstrip().upper().startswith(SIN_CAMBIOS)) for i in resp)
        if n < c["vueltas"] and not convergio and len(activos) >= 2:
            with lock:
                c["vuelta"] = n + 1
            pedidos = {sid: _pedido_revision(c, sid, n) for sid in activos}
            # la flecha sale de quien se lee: con dos investigadores, el otro
            for sid, texto in pedidos.items():
                otros = [o for o in activos if o != sid]
                _mandar_vuelta(cid, {sid: texto}, de=otros[0] if len(otros) == 1 else c["coordinador"])
            return
        with lock:
            c["estado"] = "sintetizando"
            if c["revisor"] in c["fuera"] or c["revisor"] not in _participantes(c):
                c["revisor"] = activos[0]
        # la flecha de la sintesis sale de cada investigador: son sus respuestas las que llegan al revisor
        _mandar_vuelta(
            cid, {c["revisor"]: _pedido_sintesis(c)}, de=[i for i in activos if i != c["revisor"]] or c["coordinador"]
        )
        return
    if estado == "sintetizando":
        revisan = [i for i in activos if i != c["revisor"]] if c["revisar_sintesis"] else []
        if revisan:
            with lock:
                c["estado"] = "revisando"
            _mandar_vuelta(cid, {sid: _pedido_revisar_sintesis(c) for sid in revisan}, de=c["revisor"])
            return
    if estado == "revisando" and _objeciones(c) and c["revisor"] not in c["fuera"]:
        # una vuelta corta: el revisor integra las objeciones antes de cerrar (pedido de la prueba de Teorema)
        with lock:
            c["estado"] = "corrigiendo"
        _mandar_vuelta(cid, {c["revisor"]: _pedido_corregir(c)}, de=list(_objeciones(c)))
        return
    _cerrar(cid)


PRECISION_MIN = 40  # una aprobacion con mas texto que esto despues de REPRESENTA BIEN trae una precision


def _objeciones(c: dict) -> dict[str, str]:
    """Lo que el revisor tiene que integrar: las revisiones que no dicen REPRESENTA BIEN y las que lo dicen
    pero agregan una precision (prueba de Teorema, c-20261010-a22b28: «REPRESENTA BIEN, con esta precision…»
    se trataba como aprobacion pura y la precision no llegaba a la correccion ni al cierre)."""
    out = {}
    for k, v in c["objeciones"].items():
        t = v.strip().lstrip("«*").strip()
        if not t.upper().startswith(REPRESENTA) or len(t[len(REPRESENTA) :].strip(" .,:;»*")) > PRECISION_MIN:
            out[k] = v.strip()
    return out


def _pedido_corregir(c: dict) -> str:
    obj = "\n\n".join(f"### {c['nombres'][k]}\n\n{v}" for k, v in _objeciones(c).items())
    return "\n\n".join(
        (
            _marca(c["id"], "corrección"),
            "Estas son las objeciones y precisiones de los investigadores a tu síntesis:",
            obj,
            (
                "Integralas: corregí la síntesis donde tengan razón y, donde no, decí por qué en una línea. "
                "Devolvé la síntesis final completa, con las mismas secciones. No edites archivos."
            ),
        )
    )


def _cerrar(cid: str) -> None:
    with lock:
        c = CONSULTAS[cid]
        c["estado"], c["cerrada"] = "cerrada", now()
        objeciones = _objeciones(c)
        aceptaron = [c["nombres"][k] for k in c["objeciones"] if k not in objeciones]
        corregida = "sintesis_previa" in c
        _guardar(c)
    texto = f"# Consulta {cid}\n\n**Pregunta:** {c['pregunta']}\n\n{c['sintesis'] or ''}\n"
    if aceptaron:
        texto += f"\n**Representa bien, según:** {', '.join(aceptaron)}.\n"
    if objeciones:
        titulo = "Objeciones (ya integradas por el revisor)" if corregida else "Objeciones"
        texto += f"\n## {titulo}\n\n" + "\n".join(f"- **{c['nombres'][k]}:** {v}" for k, v in objeciones.items())
    _guardar_md(cid, "sintesis.md", texto)
    if not c["coordinador"]:
        # con coordinador, la sintesis entra a la memoria al enviarsela (el envio se captura solo); sin el,
        # se captura aca como envio. `consulta` no es una clase de captura: se descartaba (2026-10-10)
        try:
            import captura

            rev = tarjeta(c["revisor"]) if tarjeta else None
            if rev:
                captura.envio(rev, texto, de=None, consulta=cid)
        except Exception as e:
            state.log(f"consulta {cid}: la síntesis no quedó en la memoria: {e}")
    state.log(f"consulta {cid}: cerrada ({len(objeciones)} objeciones)")
    _avisar_coordinador(c, f"[consulta {cid} · cerrada]\n\n{texto}")


def _sacar(cid: str, sid: str, motivo: str) -> None:
    """Un participante sale (murio, detenido, vencido, envio fallido): se sigue con al menos dos
    investigadores, o se cancela. Si era el revisor, sintetiza el primero que quede."""
    with lock:
        c = CONSULTAS.get(cid)
        if not c or c["estado"] not in ABIERTAS:
            return
        c["pendientes"].pop(sid, None)
        c["fuera"][sid] = motivo
        activos = [i for i in c["investigadores"] if i not in c["fuera"]]
        cancelar_ = len(activos) < 2 and c["estado"] == "abierta"
        if cancelar_:
            c["estado"], c["motivo"], c["cerrada"] = "cancelada", f"quedan menos de dos: {motivo}", now()
        elif sid == c["revisor"] and activos:
            c["revisor"] = activos[0]
            if c["estado"] == "sintetizando":
                c["pendientes"] = {}
        _guardar(c)
        nombre = c["nombres"].get(sid, sid[:8])
    state.log(f"consulta {cid}: sale {nombre} ({motivo})")
    if cancelar_:
        _avisar_coordinador(c, f"[consulta {cid} · cancelada] {c['motivo']}")
        return
    if sid == c["revisor"] or c["estado"] == "sintetizando" and not c["pendientes"]:
        with lock:
            c["estado"] = "abierta"  # vuelve a pedir la sintesis al revisor nuevo
            c["vuelta"] = c["vueltas"]
    _avanzar(cid)


def replica(cid: str, d: dict) -> tuple[int, dict]:
    """POST /consultas/<id>/replica. d = {"para": sid, "de": sid, "vuelta": n}. Le reenvía a `para` la
    respuesta de `de` en esa vuelta, por el envío de siempre: sin tocar pendientes ni avance, y si el
    envío falla no saca a nadie — devuelve el error como respuesta."""
    with lock:
        c = CONSULTAS.get(cid)
        if not c:
            return 404, {"ok": False, "error": "no hay una consulta con ese id"}
        if c["estado"] not in ABIERTAS:
            return 409, {"ok": False, "error": f"la consulta ya está {c['estado']}"}
        para, de, vuelta = d.get("para"), d.get("de"), d.get("vuelta")
        if not isinstance(para, str) or not isinstance(de, str):
            return _rechazo("para y de son ids de tarjeta")
        if not isinstance(vuelta, int) or isinstance(vuelta, bool) or vuelta < 1:
            return _rechazo("vuelta tiene que ser un entero positivo")
        if para not in _participantes(c):
            return _rechazo(f"{para[:8]} no participa de la consulta")
        r = c["respuestas"].get(str(vuelta), {}).get(de)
        if not r:
            return _rechazo(f"no hay respuesta de {de[:8]} en la vuelta {vuelta}")
        if para in c["pendientes"]:
            # mientras contesta una vuelta, la replica pisaria su ultimo pedido y su respuesta ya no se
            # reconoceria como de la vuelta (_es_respuesta mira la marca del ultimo pedido)
            return _rechazo(f"{para[:8]} está contestando: mandá la réplica cuando termine", 409)
        pedido = "\n\n".join(
            (
                _marca(cid, "réplica"),
                (
                    f"Te reenvía el coordinador una respuesta puntual de {c['nombres'].get(de, de[:8])} "
                    f"de la vuelta {vuelta}, por si no te llegó:"
                ),
                r["texto"],
                REGLAS,
            )
        )
    code, out = _enviar_uno(cid, para, pedido, de)
    if code != 200:
        return 502, {"ok": False, "error": f"el envío falló ({code}: {short(str(out.get('error') or out), 120)})"}
    with lock:
        c = CONSULTAS.get(cid)
        if not c:
            return 404, {"ok": False, "error": "no hay una consulta con ese id"}
        anotacion = {"para": para, "de": de, "vuelta": vuelta, "ts": now()}
        c.setdefault("replicas", []).append(anotacion)
        _guardar(c)
    state.log(
        f"consulta {cid}: réplica de {c['nombres'].get(de, de[:8])} a {c['nombres'].get(para, para[:8])} (vuelta {vuelta})"
    )
    return 200, {"ok": True, "replica": anotacion}


def cancelar(cid: str) -> tuple[int, dict]:
    with lock:
        c = CONSULTAS.get(cid)
        if not c:
            return 404, {"ok": False, "error": "no hay una consulta con ese id"}
        if c["estado"] not in ABIERTAS:
            return 409, {"ok": False, "error": f"la consulta ya está {c['estado']}"}
        c["estado"], c["motivo"], c["cerrada"] = "cancelada", "cancelada a pedido", now()
        c["pendientes"] = {}
        _guardar(c)
    state.log(f"consulta {cid}: cancelada a pedido")
    return 200, {"ok": True}


# --- vigilancia ----------------------------------------------------------------------------------


def vigilar(ahora: float | None = None, leer_respuesta=None) -> None:
    """Cada VIGILAR_CADA_S: respuestas que el gancho no vio (otra PC, server caido) y participantes que
    murieron, se detuvieron o vencieron la espera. `leer_respuesta(s)` da el texto entero de una tarjeta."""
    global _ultima_vigilancia
    ahora = time.time() if ahora is None else ahora
    if ahora - _ultima_vigilancia < VIGILAR_CADA_S:
        return
    _ultima_vigilancia = ahora
    with lock:
        trabajo = [
            (c["id"], sid, dict(p), c["espera_min"])
            for c in CONSULTAS.values()
            if c["estado"] in ABIERTAS
            for sid, p in c["pendientes"].items()
        ]
    for cid, sid, p, espera in trabajo:
        s = tarjeta(sid) if tarjeta else None
        if not s or s.get("state") == "muerta" or s.get("alive") is False:
            _sacar(cid, sid, "la tarjeta murió")
            continue
        if s.get("stopped_by"):
            _sacar(cid, sid, "la tarjeta se detuvo")
            continue
        if s.get("state") == "termino" and _es_respuesta(s, p["marca"]) and _cerro_despues(s, p["enviado"]):
            _tomar(cid, sid, s, leer_respuesta(s) if leer_respuesta else s.get("last_reply") or "")
            continue
        desde = parse_ts(p["enviado"])
        if desde and (dt.datetime.now().astimezone() - desde).total_seconds() > espera * 60:
            _sacar(cid, sid, f"no contestó en {espera} min")
