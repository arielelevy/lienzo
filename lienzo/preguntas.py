"""Consultas de trabajo dirigidas a la coordinadora del repositorio."""

import json
import re
import traceback
from copy import deepcopy
from threading import Event
from time import monotonic, sleep, time

import sessions as ses
import state
from tarjeta_texto import questions_of, strip_control

enviar = None  # El servidor instala su enrutador; no se importa un segundo server como módulo.
_ocupadas = {}
_liberadas = {}
_lecturas = {}
_CAMPOS = (
    "consulta_coordinadora",
    "respuesta_coordinadora",
    "consulta_intentada",
    "consulta_reintentar_en",
    "consulta_fallos",
    "consulta_destino",
    "pregunta_respondida",
    "respuestas_hook",
)


def _fuente(s):
    return json.dumps(
        [
            s.get("state"),
            s.get("state_since"),
            s.get("prompt_id"),
            s.get("needs"),
            s.get("dialog"),
            s.get("pending_id"),
        ],
        sort_keys=True,
    )


def _operar(s, fn, *args, esperar=0):
    limite = monotonic() + esperar
    while True:
        with state.lock:
            ocupado = _liberadas.get(s["session_id"])
            if ocupado is None:
                sid = s["session_id"]
                registrada = ses.sessions.get(sid)
                if registrada is not None and registrada is not s:
                    return 409, {"error": "la tarjeta cambió"}
                # El historial y las capturas no participan de la operación.
                foto = dict(s)
                for k in (*_CAMPOS, "needs", "dialog"):
                    if k in foto:
                        foto[k] = deepcopy(foto[k])
                fuente = _fuente(s)
                foto["_foto_origen"] = fuente
                _liberadas[s["session_id"]] = Event()
                _ocupadas[s["session_id"]] = s
                break
        restante = limite - monotonic()
        if restante <= 0 or not ocupado.wait(restante):
            return 409, {"error": "la consulta está ocupada; reintentá la respuesta"}
    try:
        return fn(foto, *args)
    finally:
        with state.lock:
            _ocupadas.pop(sid, None)
            _liberadas.pop(sid).set()
            vigente = ses.sessions.get(sid) is s if registrada is s else registrada is None
            cambios = {k: foto[k] for k in _CAMPOS if k in foto} != {k: s[k] for k in _CAMPOS if k in s}
            if vigente and _fuente(s) == fuente and cambios:
                for k in _CAMPOS:
                    if k in foto:
                        s[k] = deepcopy(foto[k])
                    else:
                        s.pop(k, None)
                ses.touch(s)


def _reservar_envio(foto):
    with state.lock:
        actual = ses.sessions.get(foto["session_id"])
        if actual is None or actual is not _ocupadas.get(foto["session_id"]):
            return False
        if _fuente(actual) != foto["_foto_origen"]:
            return False
        actual["consulta_intentada"] = deepcopy(foto["consulta_intentada"])
        ses.touch(actual)
        return True


def dialogo_coda(lineas):
    """El panel lateral de CODA no pertenece a la pregunta ni a sus opciones."""
    lineas = [l.split("│", 1)[0].rstrip(" █").strip() for l in lineas]
    pie = next(
        (i for i in range(len(lineas) - 1, -1, -1) if "select" in lineas[i] and "Enter confirm" in lineas[i]), None
    )
    if pie is None:
        return None
    opciones, inicio, marcada = [], None, []
    for i, linea in enumerate(lineas[:pie]):
        m = re.fullmatch(r"([>❯]?)\s*(\d+)\.\s+(.+)", linea)
        if not m:
            if opciones and linea and not linea.startswith("›"):
                opciones[-1]["text"] += " " + linea
            continue
        n = int(m[2])
        if n == 1:
            opciones, inicio, marcada = [], i, []
        if n != len(opciones) + 1:
            continue
        opciones.append({"n": n, "text": m[3]})
        if m[1]:
            marcada.append(n)
    if inicio is None or len(opciones) < 2 or len(marcada) != 1:
        return None
    cuerpo = []
    for linea in reversed(lineas[:inicio]):
        limpia = linea.lstrip("┃ ")
        if not limpia and cuerpo:
            break
        if limpia:
            cuerpo.append(limpia)
    pregunta = " ".join(reversed(cuerpo))
    d = {
        "question": pregunta,
        "options": opciones,
        "selected": marcada[0],
        "teclas": "flechas",
        "lector": "pregunta_coda",
    }
    entrada = next((l[1:].strip() for l in lineas[inicio:pie] if l.startswith("›")), None)
    if entrada is not None:
        d["input_text"] = entrada
    return d


def validar(d):
    autor = d.get("from")
    if autor is not None and (
        not isinstance(autor, str) or not autor or len(autor) > 200 or strip_control(autor) != autor
    ):
        return 400, {"error": "from debe ser el id de quien responde"}
    opcion, texto = d.get("opcion"), d.get("texto")
    if (opcion is None) == (texto is None):
        return 400, {"error": "indicá opcion o texto"}
    if opcion is not None and (type(opcion) is not int or opcion < 1):
        return 400, {"error": "opcion debe ser un entero positivo"}
    if texto is not None and (
        not isinstance(texto, str) or not texto.strip() or len(texto) > 2000 or strip_control(texto) != texto
    ):
        return 400, {"error": "texto debe tener entre 1 y 2000 caracteres sin controles"}
    return None


def obtener(s, *, explicito=False):
    with state.lock:
        s = dict(s)
        for k in ("needs", "dialog", "respuestas_hook"):
            if k in s:
                s[k] = deepcopy(s[k])
        p = deepcopy(ses.pending.get(s.get("pending_id")))
    n = s.get("needs") or {}
    if s.get("state") != "te_necesita":
        return None
    # un permiso sin pedido vivo (el hook vencio: PermissionTimeout) con un dialogo con opciones en pantalla es
    # una pregunta que solo se contesta por la terminal (openSeec 0.21-B, 2026-10-31: responder daba 409)
    vencido = (
        explicito
        and n.get("kind") == "permission"
        and not s.get("pending_id")
        and (s.get("dialog") or {}).get("options")
    )
    if (
        n.get("kind") != "question"
        and not vencido
        and not (n.get("kind") == "dialog" and (explicito or s.get("auto_aprobar_omitido")))
    ):
        return None
    if s.get("pending_id") and p is None:
        return None
    qs = questions_of(p) if p else []
    if qs:
        parcial = s.get("respuestas_hook") or {}
        answers = parcial.get("answers", {}) if parcial.get("request_id") == p["request_id"] else {}
        q = next((q for q in qs if q["question"] not in answers), qs[-1])
        d = {
            "question": q["question"],
            "options": [{"n": i, "text": o["label"]} for i, o in enumerate(q.get("options", []), 1)],
            "pending_id": p["request_id"],
            "questions": qs,
            "answers": answers,
        }
        return d if explicito or es_trabajo(s, d) else None
    d = s.get("dialog") if s.get("agent") != "coda" or n.get("kind") == "dialog" else None
    if not d and n.get("options"):
        d = {"question": n.get("question") or n.get("detail"), "options": n["options"]}
        if s.get("agent") == "coda":
            d.update(lector="pregunta_coda", teclas="flechas")
    if not d:
        r = ses.read_screen(s)
        lector = dialogo_coda if s.get("agent") == "coda" else ses.screen.dialog
        d = lector(r.get("lines") or []) if r.get("ok") else None
    return d if explicito or es_trabajo(s, d) else None


def es_trabajo(s, d):
    if not d:
        return False
    q = " ".join(str(d.get("question", "")).lower().split())
    reservado = r"trust|confianza|accessing workspace|switch model|select model|cambiar modelo|requires approval|requiere permiso|approvals? pending"
    if re.search(reservado, q):
        return False
    if ses.autoaprobar_opcion(d, s.get("agent")) is not None:
        return False
    if (s.get("needs") or {}).get("kind") == "question":
        return True
    # Una omisión no prueba que sea trabajo. Sólo consultas inequívocas; lo ambiguo queda humano.
    return bool(re.match(r"[¿]?(cómo seguimos|qué hacemos|cuál opción|how should we|which option|what should we)", q))


def clave(s, d):
    n = s.get("needs") or {}
    return [
        s["session_id"],
        n.get("coda_at") or n.get("since") or s.get("dialog_at"),
        " ".join(str(d.get("question", "")).split()),
        [{"n": o.get("n"), "text": " ".join(str(o.get("text", "")).split())} for o in d.get("options", [])],
    ]


def limpiar(s):
    with state.lock:
        for k in _CAMPOS:
            s.pop(k, None)
        _lecturas.pop(s["session_id"], None)


def actualizar_pregunta(s, d):
    anterior = s.get("consulta_intentada") or (s.get("consulta_coordinadora") or {}).get("clave")
    if anterior and anterior != clave(s, d):
        limpiar(s)


def consultar(s):
    with state.lock:
        if s["session_id"] in _ocupadas:
            return 409, {"error": "la consulta está ocupada"}
        if _lectura_vigente(s):
            return
    return _operar(s, _consultar)


def _coordinadora(s):
    with state.lock:
        locales = [dict(x) for x in ses.sessions.values() if x.get("coordinator")]
    candidatas = [
        x
        for x in [*locales, *ses._mirror_sessions()]
        if x.get("alive") and not x.get("stopped_by") and x["session_id"] != s["session_id"]
    ]
    sucesora = next(
        (
            x
            for x in candidatas
            if x["session_id"] == s.get("consulta_destino")
            and x.get("coordinator")
            and x.get("repo_key") == s.get("repo_key")
        ),
        None,
    )
    return sucesora if sucesora is not None else ses.repo_coordinator(s.get("repo_key"), candidatas, [])


def _lectura_vigente(s):
    """El camino frecuente no copia la tarjeta ni busca coordinadoras."""
    sid = s["session_id"]
    with state.lock:
        origen = _ocupadas.get(sid, s)
        lectura = _lecturas.get(sid, {})
        hasta = max(lectura.get("hasta", 0), s.get("consulta_reintentar_en") or 0)
        return lectura.get("origen") is origen and lectura.get("fuente") == _fuente(s) and time() < hasta


def _para_envio(s):
    if _lectura_vigente(s):
        return
    with state.lock:
        sid = s["session_id"]
        _lecturas[sid] = {"fuente": _fuente(s), "hasta": time() + 5, "origen": _ocupadas.get(sid, s)}
    d = obtener(s)
    if not d:
        _limpiar_vista(s)
        return
    actualizar_pregunta(s, d)
    identidad = clave(s, d)
    if s.get("consulta_intentada") == identidad:
        reintentar = s.get("consulta_reintentar_en")
        if reintentar is None or time() < reintentar:
            return
    return d


def _consultar(s):
    d = _para_envio(s)
    if d is None:
        return
    coord = _coordinadora(s)
    if coord is not None:
        _enviar_consulta(s, coord, d)


def _enviar_consulta(s, coord, d):
    opciones = "\n".join(f"{o['n']}. {o['text']}" for o in d.get("options", []))
    texto = (
        f"Consulta de «{s.get('title') or s['session_id']}»:\n{d['question']}\n{opciones}\n"
        f"Contestá con c.responder({s['session_id']!r}, opcion=n) o texto='...'; "
        f"POST /sessions/{s['session_id']}/responder {{opcion: n}} o {{texto: '...'}}."
    )
    if enviar is None:
        raise RuntimeError("el enrutador de consultas no está instalado")
    s.pop("consulta_reintentar_en", None)
    s["consulta_intentada"] = clave(s, d)
    if not _reservar_envio(s):
        return
    try:
        code, out = enviar(coord["session_id"], {"text": texto, "from": s["session_id"], "sin_aviso": True})
    except Exception:
        state.log(f"envío de consulta {s['session_id']}:\n{traceback.format_exc()}")
        code, out = 503, {"error": "falló el transporte de la consulta"}
    state.log(f"consulta {s['session_id']} -> {coord['session_id']}: {code} {out}")
    _resultado_envio(s, coord, d, code, out)


def _resultado_envio(s, coord, d, code, out):
    if code == 200:
        s.pop("consulta_reintentar_en", None)
        s.pop("consulta_fallos", None)  # la racha de fallos es de esta pregunta: no pasa a la siguiente
        s["consulta_coordinadora"] = {
            "clave": clave(s, d),
            "dialog": d,
            "a": coord["session_id"],
            "titulo": coord.get("title"),
        }
    else:
        fallos = s.get("consulta_fallos", 0) + 1
        s["consulta_fallos"] = fallos
        if code == 404 and isinstance(out.get("sucesora"), str):
            s["consulta_destino"] = out["sucesora"]
        if fallos < 4:
            s["consulta_reintentar_en"] = time() + 15 * 2 ** (fallos - 1)
        else:
            state.log(f"consulta {s['session_id']}: agotados 4 intentos; queda para la persona")


def responder(s, cuerpo):
    return _operar(s, _responder, cuerpo, esperar=3)


def _responder(s, cuerpo):
    if rechazo := validar(cuerpo):
        return rechazo
    if bloqueo := ses.external_blocked(s):
        return bloqueo
    if s.get("stopped_by"):
        return 409, {"error": "la sesión está detenida"}
    d = obtener(s, explicito=True)
    if not d:
        if s.get("state") != "te_necesita":
            limpiar(s)
        else:
            _limpiar_vista(s)
        return 409, {"error": "la pregunta ya no está abierta"}
    actualizar_pregunta(s, d)
    if s.get("pregunta_respondida") == clave(s, d):
        return 409, {"error": "la pregunta ya fue contestada"}
    opcion, texto = cuerpo.get("opcion"), cuerpo.get("texto")
    elegida = next((o["text"] for o in d.get("options", []) if o["n"] == opcion), None)
    if opcion is not None and elegida is None:
        return 409, {"error": "esa opción no está abierta"}
    if d.get("pending_id"):
        code, out = _hook(s, d, texto or elegida)
    else:
        code, out = _terminal(s, d, opcion, texto)
    if code == 200:
        s["pregunta_respondida"] = clave(s, d)
        s["respuesta_coordinadora"] = {
            "por": _autor(cuerpo.get("from")),
            "de": cuerpo.get("from"),
            "texto": texto or elegida,
            "at": ses.now(),
        }
        state.log(f"respuesta {s['session_id']}: {s['respuesta_coordinadora']}")
    return code, out


def _autor(sid):
    if sid is None:
        return "tablero"
    with state.lock:
        tarjeta = ses.find_session(sid)
        titulo = tarjeta.get("title") if tarjeta else None
    if titulo:
        return titulo
    return sid[:8]


def _limpiar_vista(s):
    s.pop("consulta_coordinadora", None)
    s.pop("respuesta_coordinadora", None)


def _hook(s, d, texto):
    answers = {**d["answers"], d["question"]: texto}
    if len(answers) < len(d["questions"]):
        s["respuestas_hook"] = {"request_id": d["pending_id"], "answers": answers}
        s.pop("consulta_intentada", None)
        s.pop("consulta_coordinadora", None)
        return 200, {"ok": True, "restantes": len(d["questions"]) - len(answers)}
    code, out = ses.answer_pending(d["pending_id"], "allow", answers=answers)
    return (409, out) if code == 410 else (code, out)


def _terminal(s, d, opcion, texto):
    if bloqueo := ses.send_blocked(s):
        return bloqueo
    actual, motivo = ses._dialogo_en_pantalla(s, d)
    if not actual:
        return 409, {"error": motivo}
    if " ".join((actual.get("question") or "").split()) != " ".join((d.get("question") or "").split()):
        return 409, {"error": "la pregunta cambió"}
    if texto is not None:
        return _texto_coda(s, d, texto)
    elegida = next(o["text"] for o in d["options"] if o["n"] == opcion)
    if elegida.startswith("Type something"):
        return 409, {"error": "para Type something indicá texto"}
    if (s.get("needs") or {}).get("kind") == "dialog" and d.get("teclas") != "flechas":
        return ses.run_send(s, str(opcion), enter=False)
    return ses._elegir_con_flechas(s, d, opcion)


def _texto_coda(s, d, texto):
    libre = next((o["n"] for o in d["options"] if o["text"].startswith("Type something")), None)
    if s.get("agent") != "coda" or libre is None:
        return 409, {"error": "el diálogo no ofrece Type something de CODA"}
    actual, motivo = ses._dialogo_en_pantalla(s, d)
    if not actual:
        return 409, {"error": motivo}
    if "input_text" not in actual:
        code, out = ses._elegir_con_flechas(s, d, libre)
        if code != 200:
            return code, out
        for _ in range(10):
            actual, motivo = ses._dialogo_en_pantalla(s, d)
            if not actual:
                return 409, {"error": motivo}
            if "input_text" in actual:
                break
            sleep(0.1)
    if actual.get("selected") != libre or actual.get("input_text") != "":
        return 409, {"error": "el editor de Type something no está abierto y vacío"}
    return ses.run_send(s, texto, enter=True)


def barrer():
    with state.lock:
        tarjetas = list(ses.sessions.values())
        for sid in list(_lecturas):
            if ses.sessions.get(sid) is not _lecturas[sid]["origen"]:
                _lecturas.pop(sid)
    for s in tarjetas:
        try:
            with state.lock:
                if ses.sessions.get(s["session_id"]) is not s:
                    continue
                n = s.get("needs") or {}
                if s.get("state") != "te_necesita" or n.get("kind") not in ("question", "dialog"):
                    _lecturas.pop(s["session_id"], None)
                    if any(k in s for k in _CAMPOS):
                        limpiar(s)
                        ses.touch(s)
                elegible = n.get("kind") == "question" or s.get("auto_aprobar_omitido")
            if elegible:
                consultar(s)
        except Exception:
            state.log(f"consulta {s['session_id']}:\n{traceback.format_exc()}")


def bucle(stop=None):
    """Un trabajador propio; nunca ocupa el hilo de permisos ni duerme con el lock."""
    stop = stop if stop is not None else Event()
    while not stop.is_set():
        try:
            barrer()
        except Exception:
            state.log(f"barrido de consultas:\n{traceback.format_exc()}")
        stop.wait(0.5)
