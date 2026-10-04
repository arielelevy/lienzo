"""El texto de una tarjeta, sin estado: titulos (de la transcripcion, del pedido o del adjunto),
adjuntos, preguntas de AskUserQuestion y lo que la sesion viene haciendo en el turno. Funciones puras
sobre la tarjeta (un dict) y el turno parseado: no tocan el registro de sesiones, el lock ni ningun
proceso; las que escriben, escriben solo en la tarjeta que reciben.

Antes vivian en sessions.py, que las reexporta con el mismo nombre (lo usan server.py, rules.py y
las pruebas como ses.<nombre>). Este modulo no importa sessions."""

from __future__ import annotations

import json
import os
import re

try:
    import transcripts
    from state import short
except ImportError:  # importado como lienzo.tarjeta_texto, sin lienzo/ en sys.path
    from . import transcripts
    from .state import short


ATTACH_WRAPPER = "Leé el archivo adjunto y respondé:"
# la herramienta `read` de coda se traba (medido el 2026-10-02: 4 sesiones, Qwen y GLM, mas de una hora
# en «usando read»), y su shell anda: a coda se le pide leer el adjunto con el shell. Empieza igual que
# ATTACH_WRAPPER, asi que lo que detecta el mensaje envuelto (prefijo) lo sigue reconociendo. Ademas
# se le pide ejecutar: coda resumia el encargo largo y quedaba esperando un segundo «arranca» (medido
# el 2026-10-03 con las sesiones 3 y 4 del curso).
ATTACH_WRAPPER_SHELL = (
    ATTACH_WRAPPER
    + " (NO uses la herramienta read: leelo con el shell, con type). Despues EJECUTA lo que pide, sin resumirmelo"
    " ni pedir confirmacion: solo paras si algo te frena o la decision es del humano."
)


def attachment_path(prompt: str) -> str | None:
    """Ruta del .md que viaja en 'Leé el archivo adjunto y respondé: Adjunto: <ruta>', si existe."""
    p = (prompt or "").strip()
    if not p.startswith(ATTACH_WRAPPER):
        return None
    for part in p.split("Adjunto: ")[1:]:
        path = part.strip()
        if path.lower().endswith(".md") and os.path.isfile(path):
            return path
    return None


def unwrap_attachment(prompt: str) -> str:
    """Un texto largo viaja como 'Leé el archivo adjunto y respondé: Adjunto: <ruta>'. En la
    tarjeta se muestra el contenido del adjunto, no el envoltorio."""
    path = attachment_path(prompt)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read(600)
        except OSError:
            pass
    return prompt


HEADING_RE = re.compile(r"^#{1,6}\s*(.*?)\s*#*\s*$")


def attachment_title(s: dict) -> str | None:
    """Pedido que llego como adjunto: el titulo es el primer encabezado markdown del .md (sin los
    '#'), o su primera linea no vacia. Le gana al ai-title, que para estos pedidos no sirve
    ('Mensaje 20260906'). La ruta queda en last_attachment (o en el envoltorio de una tarjeta
    vieja que todavia lo tenga en last_prompt)."""
    path = s.get("last_attachment") or attachment_path(s.get("last_prompt") or "")
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read(4000).splitlines()]
    except OSError:
        return None
    heading = next((m.group(1) for l in lines if (m := HEADING_RE.match(l)) and m.group(1)), None)
    if heading:
        return short(heading, 60)
    first = next((l for l in lines if l), "")
    # la cabecera de un informe recibido ("Mensaje de X (claude) sobre '…':") no es titulo: si el
    # adjunto empieza asi, no hay titulo que sacar de el
    return None if not first or bad_title(first) else short(first, 60)


def set_last_prompt(s: dict, raw: str, via: str | None = None) -> None:
    """Guarda el ultimo pedido tal como se muestra y, si llego como adjunto, la ruta del .md.
    `via` es de donde vino (prompt_via); solo el hook lo sabe. Sin `via`, un pedido que no cambio
    conserva el origen que ya tenia --la transcripcion repite el mismo pedido-- y uno nuevo queda
    sin origen, que es como se comportaba todo antes de que existiera la marca."""
    nuevo = short(clean_prompt(raw), 500)
    if via is not None:
        s["prompt_via"] = via
    elif nuevo != s.get("last_prompt"):
        s["prompt_via"] = None
    s["last_prompt"] = nuevo
    s["last_attachment"] = attachment_path(raw)


def prompt_mark(text: str) -> str:
    """Huella de un pedido, para reconocerlo cuando vuelve por el hook: espacios colapsados y los
    primeros 120 caracteres."""
    return " ".join((text or "").split())[:120]


USELESS_TITLE_WORDS = ("adjunto", "archivo")
# "Mensaje de lienzo (claude) sobre '…':" es la cabecera de un informe que otra sesion le mando a esta:
# tampoco sirve de titulo (la coordinadora se llamaria como el ultimo informe recibido)
USELESS_TITLE_RE = re.compile(r"^(mensaje(\s+\d+|\s+del\b.*|\s+de\s+.*\bsobre\b.*)?|encargo)$")


def bad_title(title) -> bool:
    """Titulos que no dicen nada: vacio, el XML de un mensaje entre sesiones, o el ai-title que
    Claude arma cuando el pedido llego como adjunto ('Leer archivo adjunto', 'Archivo adjunto
    análisis', 'Mensaje', 'Mensaje 20260906', 'Mensaje del 20260905', 'Encargo')."""
    t = " ".join((title or "").strip().lower().split())
    return not t or t.startswith("<") or any(w in t for w in USELESS_TITLE_WORDS) or bool(USELESS_TITLE_RE.match(t))


def clean_prompt(prompt: str) -> str:
    """Pedido tal como se muestra: mensaje entre sesiones sin el XML ('de lienzo-b7: ...'),
    adjunto desenvuelto (contenido del .md en vez de 'Leé el archivo adjunto...')."""
    pm = transcripts.peer_message(prompt or "")
    if pm:
        return f"de {pm[0]}: {pm[1]}"
    return unwrap_attachment(prompt)


def prompt_title(s: dict) -> str | None:
    """Primera linea del ultimo pedido, si sirve de titulo (no el envoltorio del adjunto ni XML)."""
    at = attachment_title(s)
    if at:
        return at
    p = (s.get("last_prompt") or "").strip()
    if not p or p.startswith((ATTACH_WRAPPER, "<")):
        return None
    first = next((l.strip() for l in p.splitlines() if l.strip()), "")
    m = HEADING_RE.match(first)
    if m and m.group(1):
        first = m.group(1)  # tarjeta vieja: el contenido del .md ya esta en last_prompt
    return short(first, 60) if first else None


def typed_here(s: dict) -> bool:
    """El ultimo pedido lo tipeo el usuario en su terminal y la tarjeta ya tiene un nombre que
    sirve: no se la renombra. El nombre de la tarjeta lo pone el encargo --el que manda la
    coordinadora, o el que se escribe desde el tablero--, no cada cosa que se tipea mientras se
    trabaja. Si todavia no tiene nombre, lo tipeado sirve igual: poner uno no es cambiarlo."""
    return s.get("prompt_via") == "terminal" and not bad_title(s.get("title"))


def choose_title(s: dict, transcript_title: str | None) -> None:
    """Regla unica del titulo automatico. El puesto a mano (title_source 'user') no se toca.
    Gana el ai-title / thread_name de la transcripcion, salvo que sea inutil (bad_title) y haya
    un pedido del que sacar la primera linea: el caso de los pedidos que llegan como adjunto."""
    if s.get("title_source") == "user":
        return
    lp = s.get("last_prompt") or ""
    if lp.startswith(ATTACH_WRAPPER) or "<cross-session-message" in lp:
        set_last_prompt(s, lp)  # tarjetas viejas: limpiar con el parser actual
    at = attachment_title(s)
    if at:
        s["title"], s["title_source"] = at, "prompt"  # el pedido llego como adjunto: su encabezado manda
        return
    pt = None if typed_here(s) else prompt_title(s)
    cur, src = s.get("title"), s.get("title_source")
    if transcript_title is None and src == "transcript" and not bad_title(cur):
        return  # el ai-title quedo fuera de la cola leida: se conserva el que ya teniamos
    if transcript_title and (not bad_title(transcript_title) or not pt):
        s["title"], s["title_source"] = transcript_title, "transcript"
    elif pt:
        s["title"], s["title_source"] = pt, "prompt"
    elif bad_title(cur):
        s["title"], s["title_source"] = None, None


def is_question(d: dict) -> bool:
    """El pendiente no es un permiso sino una pregunta con opciones. AskUserQuestion viene por
    PermissionRequest igual que todo lo demas, pero Permitir/Denegar no le sirve a nadie: permitir
    devuelve la pregunta al selector de la terminal y denegar la cancela."""
    return d.get("tool_name") == "AskUserQuestion" and isinstance(d.get("tool_input"), dict)


def questions_of(d: dict) -> list[dict]:
    """Las preguntas de un AskUserQuestion, cada una con su texto y sus opciones."""
    if not is_question(d):
        return []
    return [q for q in (d["tool_input"].get("questions") or []) if isinstance(q, dict) and q.get("question")]


def first_question(d: dict) -> str:
    """La primera pregunta, para la linea de la tarjeta. Con mas de una se avisa cuantas faltan."""
    qs = questions_of(d)
    if not qs:
        return ""
    resto = f" (+{len(qs) - 1})" if len(qs) > 1 else ""
    return short(str(qs[0]["question"]), 300) + resto


def tool_detail(tool_input) -> str:
    """Una linea que describa lo que la herramienta va a hacer, para el pedido de permiso."""
    if not isinstance(tool_input, dict):
        return short(str(tool_input or ""), 200)
    for k in ("command", "cmd", "file_path", "notebook_path", "url", "pattern", "description"):
        if tool_input.get(k):
            return short(str(tool_input[k]), 300)
    return short(json.dumps(tool_input, ensure_ascii=False), 300)


# nombres en minuscula de los dos agentes: Claude escribe con Edit/Write/Read/NotebookEdit y corre
# con Bash/PowerShell; Codex escribe con apply_patch, mira imagenes con view_image y corre con shell
FILE_TOOLS = ("edit", "write", "read", "notebookedit", "multiedit", "apply_patch", "update_file", "view_image")


CD_PREFIX_RE = re.compile(r'^\s*cd\s+(?:"[^"]*"|\S+)\s*(?:&&|;)\s*')
CMD_TOOLS = ("bash", "powershell", "shell", "run_terminal_cmd", "exec")


def tool_paths(inp: dict) -> list[str]:
    """Las rutas que toca una herramienta, en las formas que usan los dos agentes: `file_path` /
    `notebook_path` / `path` traen una sola (Claude, y view_image de Codex), y `paths` trae varias
    como [{path, type}] (apply_patch de Codex, que puede tocar varios archivos en un mismo bloque:
    medido, 53 bloques en ~/.codex, y por esta forma la tarjeta de Codex no mostraba ningun archivo)."""
    una = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if una:
        return [str(una)]
    return [str(p.get("path") or "" if isinstance(p, dict) else p) for p in (inp.get("paths") or [])]


def turn_activity(t: dict) -> dict:
    """Lo que la sesion viene haciendo en el turno, para la tarjeta: cuantas herramientas lleva, los
    ultimos archivos distintos que toco (del mas nuevo al mas viejo), el ultimo comando que corrio y
    cuantas herramientas volvieron con error. Sale de los bloques que ya tiene la transcripcion, en
    una sola pasada de atras para adelante; las claves son las de la tarjeta."""
    n = errors = 0
    files: list[str] = []
    cmd: str | None = None
    for b in reversed(t.get("blocks", [])):
        if b.get("kind") != "tool":
            continue
        n += 1
        errors += bool((b.get("result") or {}).get("is_error"))
        name = (b.get("name") or "").lower()
        inp = b.get("input") or {}
        if cmd is None and name in CMD_TOOLS:
            raw = str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " ")
            # el "cd <ruta larga> &&" del principio no dice nada y se come la linea entera
            raw = CD_PREFIX_RE.sub("", raw).strip()
            if raw:
                cmd = short(raw, 120)
        if name in FILE_TOOLS:
            for ruta in tool_paths(inp):
                if len(files) >= 3:
                    break
                base = os.path.basename(ruta.replace("\\", "/").rstrip("/"))
                if base and base not in files:
                    files.append(base)
    return {"tool_count": n, "last_files": files, "last_cmd": cmd, "tool_errors": errors}


def using_tool(t: dict) -> str | None:
    """ "usando Bash": la herramienta mas reciente del turno, para la tarjeta mientras corre."""
    b = next((b for b in reversed(t.get("blocks", [])) if b.get("kind") == "tool"), None)
    return f"usando {b['name']}" if b else None


def turn_prompt(t: dict) -> str | None:
    """Pedido del turno, o None si quedo fuera de la cola leida ("(turno anterior...")."""
    p = t.get("prompt")
    return p if p and not p.startswith("(turno anterior") else None


def turn_say(t: dict) -> str | None:
    """Lo que la sesion viene diciendo, para la tarjeta: el ultimo texto que escribio el agente en el
    turno. Mientras corre es el comentario entre dos herramientas ("Ahora parto refresh en dos:");
    cuando el turno cierra es la respuesta final. Si todavia no escribio nada, el nombre de la
    herramienta que esta usando. `transcripts` ya mantiene `final` = ultimo bloque de texto no vacio,
    y el pensamiento (kind "thinking") nunca pasa por ahi: a la tarjeta no va (el toggle
    "Pensamiento" del menu es para la conversacion). Lo de "que herramienta" es turn_activity.

    Va entero. Estaba recortado a 600 caracteres y la tarjeta no lo notaba --el CSS la corta en 6
    lineas de todos modos-- pero si lo notaban el boton de copiar de la tarjeta (copiaba media
    respuesta), la caja de reenviar y el freno del on_stop, que mira si la respuesta termina en
    pregunta: con el recorte terminaba en "…" y nunca frenaba. Medido el 2026-09-07 sobre 124
    turnos: 86 finales pasan de 600 caracteres (mediana 1125, maximo 7863) y el snapshot de
    /sessions pasa de 7,3 a 11,3 KB con cuatro sesiones abiertas."""
    return (t.get("final") or "").strip() or using_tool(t)


def title_from_prompt(s: dict) -> None:
    """Sin ai-title todavia (o con uno inutil): la tarjeta se titula con la primera linea del
    pedido. Un ai-title que sirva lo pisa despues (refresh_from_transcript), salvo que el pedido
    haya llegado como adjunto: ahi manda su encabezado."""
    if s.get("title_source") == "user" or typed_here(s):
        return
    if not (s.get("last_attachment") or bad_title(s.get("title")) or s.get("title_source") == "prompt"):
        return
    if first := prompt_title(s):
        s["title"], s["title_source"] = first, "prompt"


ANSWER_MAX = 2000  # techo de cada respuesta; una opcion es corta y el texto libre no es un ensayo


def question_answers(d: dict, answers: object) -> dict:
    """Lo que se le puede contestar a un AskUserQuestion: solo las preguntas que el pedido trae y
    solo texto. Lo que no coincide se descarta sin romper (el hook igual revalida antes de armar
    el updatedInput). El valor puede ser una opcion, varias separadas por coma (multiSelect) o
    texto libre, que es el "Other" del selector de la terminal."""
    if not isinstance(answers, dict):
        return {}
    preguntas = {q["question"] for q in questions_of(d)}
    return {
        k: strip_control(str(v))[:ANSWER_MAX]
        for k, v in answers.items()
        if k in preguntas and isinstance(v, str) and v.strip()
    }


_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))


def strip_control(s: str) -> str:
    """Saca los caracteres de control y los overrides de direccion Unicode (hallazgo A4 del
    pentest): en la consola destino no llegan como caracteres, se teclean como teclas reales
    (ESC, Tab, Backspace, Ctrl-C) o alteran el orden visible del texto. El texto normal no los
    tiene, y lo largo o multilinea viaja como adjunto .md, no por aca."""
    return "".join(ch for ch in s if ord(ch) >= 0x20 and ord(ch) != 0x7F and ord(ch) not in _BIDI)
