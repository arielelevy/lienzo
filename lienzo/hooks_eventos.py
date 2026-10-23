"""Eventos de hooks de los agentes: aplicar cada evento a su tarjeta (claim de pid, prompt, stop,
notificaciones, compactacion, actividad de coda) y consumir la carpeta de eventos.

Salio de sessions.py sin cambiar el codigo (particion del frente F, 2026-10-21). El registro de
sesiones y todo lo demas que vive en sessions se lee como `ses.X` en tiempo de llamada, asi un
parche de prueba sobre `ses.X` le sigue llegando.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import time
import traceback

import coda
import sessions as ses
import titulo_lanzado
from state import EVENTS, NEEDS_NOTIFICATIONS


def heredar_de_provisoria(prov: dict, s: dict) -> None:
    """La tarjeta real hereda de la provisoria (`pid-N` del barrido) lo que se le puso a mano antes de
    que llegara el primer hook: el titulo del usuario y la marca de coordinadora. Medido el
    2026-10-04: lanzar_y_titular titulaba la provisoria y, al pasar al id real, el titulo se perdia y
    salia del primer mensaje («Bien el diagnostico. Reintenta…» en vez de «encargo F»)."""
    if prov.get("title_source") == "user" and s.get("title_source") != "user":
        s["title"], s["title_source"] = prov.get("title"), "user"
    for k in ("coordinator", "copycat_of"):
        if prov.get(k) and not s.get(k):
            s[k] = prov[k]


def claim_pid(s: dict, ev: dict) -> None:
    """El evento trae un pid vivo: la tarjeta se lo queda, salvo que ya sea de otra. Otra tarjeta con
    el mismo pid: si es un placeholder del barrido (source sweep o id "pid-N") es la misma sesion y
    se reemplaza; si es una sesion con hooks que termino (SessionEnd por /clear o resume) o dejo de
    emitir y esta trae su propia transcripcion, el proceso siguio con otro session_id y esta la
    continua (hereda pid, reglas y links); si es una sesion real que sigue viva, el pid ya tiene
    duena y este evento no se lo lleva (una prueba manual del hook con otro session_id no debe
    borrar la sesion real ni sus reglas). Se llama con el lock tomado."""
    pid, sid = ev["pid"], s["session_id"]
    if s.get("pid") and s["pid"] != pid and not s.get("external") and ses.backend.agent_alive(s):
        ext = ses.backend.external_origin(ev)
        if ext and ext.get("desktop"):
            # Claude Desktop comparte ~/.claude/projects y muestra las sesiones de la CLI: si un motor
            # suyo emite con el mismo session_id mientras la CLI vive, la tarjeta sigue siendo la de
            # la CLI (no cambia de origen por haberse visto en la app)
            ses.state.log(
                f"{sid[:8]}: evento de Claude Desktop (pid {pid}) con la CLI viva (pid {s['pid']}): sigue la CLI"
            )
            return
    owner = None
    if s.get("pid") != pid:
        for other_sid, other in list(ses.sessions.items()):
            if other_sid != sid and ses.backend.proc_key(other) == ses.backend.proc_key(ev):
                if other.get("source") == "sweep" or other_sid.startswith("pid-"):
                    # el placeholder del barrido es la misma sesion: lo que lo nombraba (una regla de
                    # cableado hecha al lanzarla, un link) pasa al sid real antes de darlo de baja
                    try:
                        n_rules, n_links = ses.repoint_refs(other_sid, sid)
                    except OSError as e:
                        owner = other_sid
                        ses.state.log(
                            f"pid {pid}: no reemplazo {other_sid[:8]} por {sid[:8]}: no se guardaron reglas/enlaces: {e}"
                        )
                    else:
                        if n_rules:
                            ses.rules.publish()
                        if n_links:
                            ses.links.publish()
                        heredar_de_provisoria(other, s)
                        ses.drop_session(other_sid, "duplicada por barrido")
                elif ses.continues_session(other, ev):
                    if not ses.continue_session(other, s):
                        owner = other_sid
                else:
                    owner = other_sid
        if owner:
            ses.state.log(
                f"pid {pid} ya pertenece a {owner[:8]}; evento {ev.get('hook_event_name') or '?'} de {sid[:8]} no lo toma"
            )
    if not owner:
        proceso_nuevo = s.get("pid") != pid
        s["pid"] = pid
        s["agent_exe"] = ev.get("agent_exe")
        # el panel de Claude Code de VS Code y las apps de escritorio disparan hooks pero no
        # tienen consola: se ven y se leen, no se les escribe
        ext = ses.backend.external_origin(s)
        # un proceso nuevo decide de cero (retomar en una terminal propia una sesion que corrio en un
        # orquestador la vuelve personal); el mismo proceso conserva la marca que puso un plugin
        if ext or proceso_nuevo:
            s["external"] = ext
        s["no_console"] = bool(s.get("external")) or not ses.backend.is_tui(s)
        if proceso_nuevo:
            titulo_lanzado.aplicar(s)  # el titulo pedido en /sessions/launch, si nacio de uno


ENVIO_SIN_CONFIRMAR_S = 25  # con el agente libre, lo que tarda en llegar el UserPromptSubmit de un envio
AVISO_SIN_ENVIAR_S = 180


def confirmar_codex_desde_turno(s: dict, turn: dict) -> bool:
    """Codex incorpora mensajes al turno activo: prompt_ts, no ts_start, fecha su recepción.

    Un pedido posterior prueba consumo según el contrato Z2, aunque el parser haya unido
    varios mensajes. No confirma ejecución terminada ni reenvía el texto.
    """
    receipt = s.get("envio_codex") or {}
    if (
        s.get("agent") != "codex"
        or receipt.get("transporte") != "tecleo"
        or receipt.get("estado") not in ("pendiente", "encolado", "sin_confirmacion")
        or not receipt.get("envio_id")
        or type(receipt.get("at")) not in (int, float)
        or not math.isfinite(receipt["at"])
    ):
        return False
    prompt = ses.turn_prompt(turn)
    entered = ses.parse_ts(turn.get("prompt_ts") if "prompt_ts" in turn else turn.get("ts_start"))
    if not prompt or ses.transcripts.is_system_prompt(prompt) or entered is None:
        return False
    if not entered.timestamp() >= receipt["at"]:
        return False
    receipt.update(estado="entregado", motivo=None, confirmacion_final=True)
    s["sent_mark"] = s["envio_pendiente"] = None
    return True


def stale_send_notice(s: dict, turn: dict | None = None) -> bool:
    """Un pedido humano posterior o una entrega exacta posterior dejan viejo el aviso.

    El acuse conserva su correlación/hash original. No prueba fin de turno: el estado
    se reconstruye con la transcripción, sin inventarlo a partir de last_reply.
    Con el lock del registro tomado, igual que envio_sin_confirmar.
    """
    notice = s.get("needs") or {}
    receipt = s.get("envio_codex") or {}
    if (
        s.get("agent") != "codex"
        or not s.get("alive")
        or s.get("state") == "muerta"
        or notice.get("kind") != "sin_enviar"
        or s.get("pending_id")
    ):
        return False
    since = ses.parse_ts(notice.get("since"))
    if since is None:
        return False
    if time.time() - since.timestamp() >= AVISO_SIN_ENVIAR_S:
        return True  # el estado lo reconstruye el caller con la transcripción, no el reloj
    if turn is not None:
        prompt = ses.turn_prompt(turn)
        entered = ses.parse_ts(turn.get("prompt_ts") if "prompt_ts" in turn else turn.get("ts_start"))
        if prompt and not ses.transcripts.is_system_prompt(prompt) and entered and entered > since:
            return True  # Retirar el aviso no confirma el recibo del envío.
        ended_at = ses.parse_ts(turn.get("ts_end"))
        if turn.get("ended") and ended_at and ended_at > since:
            return True
        if (
            receipt.get("confirmacion_final") is True
            and entered
            and type(receipt.get("at")) in (int, float)
            and entered.timestamp() >= receipt["at"]
        ):
            return True
    if (
        receipt.get("estado") != "entregado"
        or receipt.get("confirmacion_final") is not True
        or not receipt.get("envio_id")
    ):
        return False
    sent_at = receipt.get("at")
    if type(sent_at) not in (int, float):
        return False
    try:
        sent = dt.datetime.fromtimestamp(sent_at, dt.UTC)
    except OSError, OverflowError, ValueError:
        return False
    return sent > since  # sin orden causal probado, conservar el aviso más nuevo


def clear_stale_send_notice(s: dict, turn: dict | None = None) -> bool:
    """Con transcripción disponible, retira el aviso sin modificar el acuse ni reenviar."""
    if not stale_send_notice(s, turn):
        return False
    s["needs"] = None
    return True


def envio_sin_confirmar(s: dict, ahora: float) -> bool:
    """Un envio del lienzo que el agente no confirmo con su UserPromptSubmit: pasa a "te necesita"
    con un aviso, en vez de figurar corriendo con el texto en el editor. Mientras el agente trabaja
    el mensaje queda en cola (Claude lo toma al cerrar el turno): se cuenta desde que quedo libre.
    Con el lock. Devuelve si marco."""
    p = s.get("envio_pendiente")
    if not p:
        return False
    if s.get("sent_mark") is None or not s.get("alive"):
        s["envio_pendiente"] = None  # confirmado por otro camino, o el proceso murio
        receipt = s.get("envio_codex") or {}
        if (
            not s.get("alive")
            and receipt.get("transporte") == "tecleo"
            and receipt.get("estado") in ("pendiente", "encolado")
        ):
            receipt.update(estado="sin_confirmacion", motivo="el proceso Codex terminó sin confirmar; no se reintenta")
        return False
    if (
        s.get("state") == "corriendo"
        or s.get("pending_id")
        or (s.get("needs") or {}).get("kind") in ("permission", "question", "denied")
    ):
        return False
    desde = max(p["at"], (ses.parse_ts(s.get("state_since")) or dt.datetime.min.replace(tzinfo=dt.UTC)).timestamp())
    if ahora - desde < ENVIO_SIN_CONFIRMAR_S:
        return False
    entered = ses.parse_ts(s.get("prompt_ts"))
    if s.get("agent") == "codex" and entered and entered.timestamp() >= p["at"]:
        receipt = s.get("envio_codex") or {}
        if (
            receipt.get("transporte") == "tecleo"
            and receipt.get("estado") in ("pendiente", "encolado", "sin_confirmacion")
            and receipt.get("envio_id")
            and type(receipt.get("at")) in (int, float)
            and math.isfinite(receipt["at"])
            and entered.timestamp() >= receipt["at"]
        ):
            receipt.update(estado="entregado", motivo=None, confirmacion_final=True)
            s["sent_mark"] = None
        s["envio_pendiente"] = None
        return True
    s["envio_pendiente"] = None
    receipt = s.get("envio_codex") or {}
    if receipt.get("transporte") == "tecleo" and receipt.get("estado") in ("pendiente", "encolado"):
        receipt.update(estado="sin_confirmacion", motivo="Codex no confirmó el mensaje; no se reintenta")
    detalle = ses.short(s.get("last_prompt") or "", 200)
    ses.set_needs(s, {"kind": "sin_enviar", "detail": detalle, "where": "terminal"})
    ses.state.log(
        f"send {s['session_id'][:8]}: el agente no confirmo el encargo en {ENVIO_SIN_CONFIRMAR_S} s"
        + (" (la consola no consumio el texto)" if p.get("sin_consumo") else "")
        + ": puede haber quedado en el editor sin Enter"
    )
    return True


def hook_prompt_submit(s: dict, ev: dict) -> None:
    s["envio_pendiente"] = None  # el agente tomo un pedido: el envio quedo confirmado
    ses.set_state(s, "corriendo")
    s["stopped_by"] = None  # volvio a trabajar: la marca de detenida ya no cuenta
    raw = ev.get("prompt", "")
    sistema = ses.transcripts.is_system_prompt(raw)
    via = None if sistema else ses.prompt_origin(s, raw)
    receipt = s.get("envio_codex") or {}
    if (
        via == "lienzo"
        and receipt.get("transporte") == "tecleo"
        and hashlib.sha256(raw.encode()).hexdigest() == receipt.get("prompt_sha256")
    ):
        receipt.update(estado="entregado", motivo=None, confirmacion_final=True)
    # el pedido que es el propio mensaje de autorizacion (lo tecleo el lienzo con `autorizando`) no
    # olvida lo autorizado: si no, la relectura del turno volvia a mostrar la misma denegacion
    autorizacion = via == "lienzo" and s.get("autorizando")
    s["autorizando"] = False
    s["last_denied"] = None  # pedido nuevo: lo denegado antes ya se resolvio o se descarto
    if not autorizacion:
        s["denied_ok"] = None  # y lo autorizado tambien: una denegacion en el turno nuevo es nueva
    # pedido en curso: con esto se reconoce un Stop tardio del pedido anterior (stale_stop)
    s["prompt_id"] = ev.get("prompt_id")
    s["prompt_ts"] = s["last_event_ts"]
    if not sistema:
        ses.set_last_prompt(s, raw, via)
        ses.title_from_prompt(s)
        ses.captura.pedido(s, raw, via, turno=ev.get("prompt_id"))  # la memoria del proyecto (anexo A de v5)
    s["pending_id"] = None
    s["typing"] = False  # lo que habia en la caja ya se mando; screen_loop lo confirma en 5 s
    if s["agent"] == "coda":
        # turno nuevo: sin esto quedan los contadores del anterior (ver apply_turn)
        s.update({"tool_count": 0, "last_files": [], "last_cmd": None, "tool_errors": 0})


COMPACTING_MAX_S = 600  # si PostCompact no llega (coda se cae), la marca vence sola
COMPACTING_CARRERA_S = 10  # PreCompact y el UserPromptSubmit del mismo /compact llegan en cualquier orden


def compacting(s: dict) -> bool:
    """La sesion esta compactando contexto (PreCompact sin PostCompact todavia)."""
    t = s.get("compacting")
    return bool(t) and time.time() - t < COMPACTING_MAX_S


def hook_stop(s: dict, ev: dict) -> None:
    reason = ev.get("stop_reason")
    s["stop_reason"] = reason
    if ses.stale_stop(s, ev):
        ses.state.log(
            f"Stop tardio de {s['session_id'][:8]} (pedido {str(ev.get('prompt_id'))[:8]}, ya corre "
            f"{str(s.get('prompt_id'))[:8]}): la tarjeta sigue corriendo"
        )
    elif compacting(s):
        ses.state.log(f"Stop de {s['session_id'][:8]} durante una compactacion: la tarjeta sigue corriendo")
    elif not ses.perfil(s["agent"]).stop_is_final(reason):
        ses.state.log(f"Stop de {s['session_id'][:8]} con motivo {reason!r}: se espera el final de la transcripcion")
    else:
        ses.set_state(s, "termino")
        if ev.get("last_assistant_message"):
            # entero, igual que turn_say: el recorte se lo hace la tarjeta por CSS
            texto = (ev["last_assistant_message"] or "").strip()
            s["last_reply"] = ses.transcripts.reparar_mojibake(texto) if s["agent"] == "coda" else texto
    s["pending_id"] = None


def hook_notification(s: dict, ev: dict) -> None:
    nt = ev.get("notification_type") or ""
    if nt == "idle_prompt" and s.get("last_prompt") and not (s.get("last_reply") or "").rstrip().endswith("?"):
        # termino con un informe que no pregunta nada: no "te necesita", solo termino. La
        # tarjeta libre (sin pedido) si pasa a te_necesita/idle, para ofrecer "Darle trabajo"
        ses.state.log(f"{s['session_id'][:8]}: idle_prompt sin pregunta al final; la tarjeta queda en {s['state']}")
        return
    if nt not in NEEDS_NOTIFICATIONS:
        return
    ses.set_needs(
        s,
        {
            "kind": "idle" if nt == "idle_prompt" else "permission" if nt == "permission_prompt" else nt,
            "detail": ses.short(ev.get("message", ""), 300),
            "where": "terminal",
        },
    )


# lo que CODA corre en el turno abierto, por sesion: su base guarda el turno recien al cerrarlo, y sin
# esto el panel mostraba el pedido solo, sin nada en vivo (2026-10-09). En memoria y fuera de la
# tarjeta, que viaja entera por el SSE; GET .../digest lo suma al turno abierto (coda_vivo_en_turno)
CODA_VIVO: dict[str, list[dict]] = {}
CODA_VIVO_MAX = 300


def _coda_vivo_anotar(sid: str, tool: str, name: str, inp: dict, sub: bool, ts: str) -> None:
    paso: dict = {"tool": tool, "ts": ts, "sub": sub}
    if name in ses.CMD_TOOLS:
        paso["cmd"] = ses.short(str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " "), 300)
    if name in ses.FILE_TOOLS:
        paso["files"] = ses.tool_paths(inp)
    if name in CODA_ASK_TOOLS:
        paso["pregunta"] = ses.short(str(inp.get("question") or inp.get("prompt") or inp.get("message") or ""), 300)
    lista = CODA_VIVO.setdefault(sid, [])
    lista.append(paso)
    del lista[:-CODA_VIVO_MAX]


def coda_vivo_en_turno(sid: str, turno: dict) -> dict:
    """El turno abierto de CODA (tal como lo da transcripts.digest: el pedido solo) con las
    herramientas que el hook vio desde que empezo. Un turno cerrado vuelve igual: ahi manda la base."""
    if turno.get("ended"):
        return turno
    desde = ses.parse_ts(turno.get("ts_start"))
    pasos = [p for p in CODA_VIVO.get(sid) or [] if not desde or (ses.parse_ts(p["ts"]) or desde) >= desde]
    if not pasos:
        return turno
    archivos = list(dict.fromkeys(f for p in pasos for f in p.get("files") or []))
    return {
        **turno,
        "tools": max(turno.get("tools") or 0, len(pasos)),
        "commands": [p["cmd"] for p in pasos if p.get("cmd")][-50:],
        "files": archivos[-50:],
        "questions": [p["pregunta"] for p in pasos if p.get("pregunta")],
        "subagents": max(turno.get("subagents") or 0, int(any(p["sub"] for p in pasos))),
        "says": [*(turno.get("says") or []), f"en vivo: {len(pasos)} herramientas, la última {pasos[-1]['tool']}"],
    }


def coda_tool(s: dict, ev: dict, sub: bool = False) -> None:
    """PreToolUse de CODA: la herramienta que va a correr, a la tarjeta. Es la unica señal de
    avance durante el turno, porque CODA escribe el turno en su base recien al cerrarlo; al
    cerrarse, la transcripcion rehace estos contadores con el turno entero (turn_activity)."""
    tool = str(ev.get("tool_name") or "?")
    name = tool.lower()
    inp = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    _coda_vivo_anotar(s["session_id"], tool, name, inp, sub, ev.get("host_ts") or ses.now())
    if ev.get("auto_aprobado"):
        cmd = inp.get("command") or inp.get("cmd") or inp.get("file_path") or ""
        ses.state.log(f"AUTO-APROBADO (hook coda) {s['session_id'][:8]}: {tool} {ses.short(str(cmd), 160)}")
    s["tool_count"] = (s.get("tool_count") or 0) + 1
    if (s.get("needs") or {}).get("via") in ("tool", "screen"):
        # la herramienta que habia abierto el dialogo ya se contesto: corre otra
        ses.set_state(s, "corriendo")
    if name in ses.CMD_TOOLS:
        raw = str(inp.get("command") or inp.get("cmd") or "").strip().replace("\n", " ")
        raw = ses.CD_PREFIX_RE.sub("", raw).strip()
        if raw:
            s["last_cmd"] = ses.short(raw, 120)
    if name in ses.FILE_TOOLS:
        for ruta in ses.tool_paths(inp):
            base = os.path.basename(ruta.replace("\\", "/").rstrip("/"))
            if base:
                s["last_files"] = [base, *[f for f in s.get("last_files") or [] if f != base]][:3]
    at, since = ses.parse_ts(ev.get("host_ts")), ses.parse_ts(s.get("state_since"))
    if s["state"] == "termino" and at and since and at > since:
        # una herramienta despues del cierre es un turno en curso: pasa cuando el UserPromptSubmit
        # no llego, y la base no lo corrige porque CODA no la toca hasta cerrar el turno. La
        # comparacion deja afuera un PreToolUse del turno anterior que llega despues del Stop
        ses.set_state(s, "corriendo")
    if s["state"] == "corriendo":
        s["last_reply"] = f"usando {tool}" + (" (subagente)" if sub else "")
    if name in CODA_ASK_TOOLS and not sub:
        # ask_user es una PREGUNTA, no un permiso: con auto-aprobar prendido el hook la deja pasar
        # (la herramienta tiene que correr para preguntar) y nadie marcaba la tarjeta; CODA la
        # preguntaba en su terminal y el tablero seguia en corriendo (medido el 2026-10-09 en
        # ar-it33940: dos ask_user AUTO-APROBADOS sin «te necesita»)
        pregunta = inp.get("question") or inp.get("prompt") or inp.get("message") or ""
        detalle = (
            ses.short(str(pregunta).strip(), 300)
            if pregunta
            else ses.short(json.dumps(inp, ensure_ascii=False), 300)
            if inp
            else ""
        )
        ses.set_needs(s, {"kind": "question", "tool": tool, "detail": detalle, "where": "terminal", "via": "tool"})
        s["needs"]["coda_at"] = f"tool:{ev.get('host_ts') or ses.now()}"
    if name in CODA_DIALOG_TOOLS and not sub:
        # estas herramientas abren SIEMPRE un dialogo «Approval Required» y no dejan un `ask` en el
        # log de coda: sin esto la tarjeta seguia en corriendo y nadie veia el pedido (medido el
        # 2026-10-04: propose_policy de una regla permanente para git reset --hard)
        detalle = ses.short(json.dumps(inp, ensure_ascii=False), 300) if inp else ""
        ses.set_needs(
            s,
            {
                "kind": "permission",
                "tool": tool,
                "detail": f"{CODA_DIALOG_TOOLS[name]} {detalle}".strip(),
                "where": "terminal",
                "via": "tool",
            },
        )
        s["needs"]["coda_at"] = f"tool:{ev.get('host_ts') or ses.now()}"


# herramientas de coda que siempre piden aprobacion en su terminal, con lo que piden
CODA_DIALOG_TOOLS = {"propose_policy": "propone una regla de permisos permanente:"}
# herramientas de coda que le preguntan algo al usuario en su terminal (no un permiso)
CODA_ASK_TOOLS = frozenset({"ask_user", "askuser", "ask_user_question"})

CODA_SENT_RETRY_S = (
    20  # tras contestar, si el permiso sigue abierto pasado este tiempo, la tarjeta vuelve a mostrar los botones
)
CODA_ASK_CAUSES = {
    "command-policy": "comando que pide confirmación",
    "unresolved-command": "comando que no pudo verificar",
}


def _pedido_de_fondo(act: dict) -> bool:
    """¿El log de coda muestra un permiso abierto de un subagente aunque el turno principal ya cerro?
    Pasa con un workflow o un agente de fondo (medido el 2026-10-10: el workflow sdd-olas de una coda
    quedo una hora esperando la aprobacion de un `py -c` de solo lectura con la tarjeta en termino)."""
    return not act["running"] and bool((act.get("asking") or {}).get("sub"))


def coda_log_activity(s: dict) -> bool:
    """Lo que dice el log de CODA (coda.activity), con el lock tomado; devuelve si cambio algo.

    Para toda tarjeta de CODA viva: el pedido de permiso abierto la pone en te_necesita, y al
    contestarse la devuelve a corriendo. Sin hooks, ademas, cuantas herramientas lleva el turno y
    cual corre (el comando y los archivos los da coda_tool, con hooks)."""
    act = coda.activity(s["pid"])
    if not act:
        return False
    before = (s["state"], s.get("needs"), s.get("tool_count"), s.get("last_reply"))
    if act["running"] and s["state"] == "termino":
        # el log muestra herramientas del turno abierto despues del cierre: se perdio el
        # UserPromptSubmit y la sesion quedo esperando (un permiso, por ejemplo) sin otro evento
        last, since = ses.parse_ts(act.get("last_at")), ses.parse_ts(s.get("state_since"))
        if last and since and last > since:
            ses.set_state(s, "corriendo")
    if act.get("error") and s.get("last_error") != act["error"]:
        s["last_error"] = act["error"]  # «coda sin cuota»: la tarjeta lo dice en rojo en vez de «termino»
    elif not act.get("error") and (s.get("last_error") or "").startswith("coda sin cuota"):
        # el log ya no dice que falte cuota (un turno nuevo, o siguio trabajando): antes el aviso
        # quedaba para siempre aunque coda trabajara (medido el 2026-10-09 en ar-it33940)
        s["last_error"] = None
    den = act.get("denied")
    pedido, cuando = ses.parse_ts(s.get("prompt_ts")), ses.parse_ts((den or {}).get("at"))
    if den and pedido and cuando and cuando < pedido:
        # del turno anterior: el log todavia no tiene el «prompt started» del pedido nuevo, que ya
        # borro la marca. Sin esto volvia enseguida y el boton «Autorizar» no se iba (2026-10-04)
        den = None
    if den:
        # la misma denegacion (mismo `at`) conserva el comando que se denego: last_cmd avanza con
        # cada comando que coda si aprueba, y con el detalle nuevo set_denied la volvia a anunciar
        # como DENEGADO en todos los comandos que seguian en el turno (2026-10-09, sesion a1209581
        # de ar-it33940)
        prev = s.get("last_denied") or {}
        detalle = prev.get("detalle") if prev.get("fuente") == "coda" and prev.get("at") == den.get("at") else None
        ses.set_denied(
            s,
            {
                "tool": den["tool"],
                "motivo": CODA_ASK_CAUSES.get(den.get("cause") or "", den.get("cause") or ""),
                "detalle": detalle if detalle is not None else s.get("last_cmd") or "",
                "at": den.get("at"),
                "fuente": "coda",
                "sub": den.get("sub"),
            },
        )
    ask = act.get("asking") if act["running"] or _pedido_de_fondo(act) else None
    if ask and ask.get("at") == s.get("coda_fondo_hecho"):
        ask = None  # el permiso de fondo que la pantalla ya mostro contestado (coda_fondo_en_pantalla)
    needs = s.get("needs") or {}
    if (
        act["running"]
        and not ask
        and not needs
        and s["state"] == "corriendo"
        and s.get("last_event") == "PreToolUse"
        and (s.get("last_reply") or "") in {f"usando {t}" for t in CODA_ASK_TOOLS}
    ):
        # la pregunta quedo abierta sin que coda_tool la marcara: llego antes de que el server la
        # conociera (un reinicio con el codigo nuevo, medido el 2026-10-09 en ar-it33940) o se perdio
        # su PreToolUse. Ninguna herramienta corrio despues: coda esta esperando la respuesta
        ses.set_needs(
            s,
            {
                "kind": "question",
                "tool": s["last_reply"][len("usando ") :],
                "detail": "",
                "where": "terminal",
                "via": "tool",
            },
        )
        s["needs"]["coda_at"] = f"tool:{s.get('last_event_ts') or ses.now()}"
        needs = s["needs"]
    if ask and (s["state"] in ("corriendo", "te_necesita") or (s["state"] == "termino" and _pedido_de_fondo(act))):
        detail = CODA_ASK_CAUSES.get(ask["cause"] or "", ask["cause"] or "")
        detail = " · ".join(x for x in (detail, "de un subagente" if ask["sub"] else "") if x)
        if needs.get("kind") != "permission" or needs.get("coda_at") != ask["at"]:
            previa = needs if needs.get("kind") == "question" else None
            de_fondo = s["state"] == "termino" or bool(needs.get("de_fondo"))
            ses.set_needs(s, {"kind": "permission", "tool": ask["tool"], "detail": detail, "where": "terminal"})
            s["needs"]["coda_at"] = ask["at"]
            if de_fondo:
                # pedido con el turno principal cerrado: al contestarse vuelve a termino sin disparar on_stop
                s["needs"]["de_fondo"] = True
            if previa is not None and str(ask.get("tool") or "").lower() in CODA_ASK_TOOLS:
                # sin auto-aprobar, ask_user pide permiso antes de preguntar: se guarda la pregunta
                # para volver a ella cuando el permiso se conteste (ver el elif de abajo)
                s["needs"]["pregunta"] = previa
        elif needs.get("where") == "enviado" and time.time() - (needs.get("sent_ts") or 0) > CODA_SENT_RETRY_S:
            # el Enter/Esc no resolvio el permiso (sigue abierto en el log): se devuelven los botones
            s["needs"] = {**needs, "where": "terminal"}
    elif s["state"] == "te_necesita" and isinstance(needs.get("pregunta"), dict) and act["running"]:
        # el permiso de ask_user se contesto: ahora CODA muestra la pregunta en su terminal
        ses.set_needs(s, needs["pregunta"])
    elif s["state"] == "te_necesita" and needs.get("coda_at") and needs.get("via") not in ("tool", "screen"):
        # (el dialogo de una herramienta como propose_policy no figura en el log: lo cierra el
        # proximo PreToolUse o el fin del turno, no la ausencia de un `ask`)
        if needs.get("de_fondo") and not act["running"]:
            # el permiso de un subagente de fondo se contesto: la tarjeta vuelve a como estaba, sin que
            # cuente como fin de un trabajo (set_state dispararia on_stop con cada permiso)
            s["state"], s["state_since"], s["needs"] = "termino", ses.now(), None
        else:
            ses.set_state(s, "corriendo" if act["running"] else "termino")
    if not s.get("hooked") and act["running"] and act["last_tool"]:
        s["tool_count"] = act["tools"]
        if s["state"] == "corriendo":
            s["last_reply"] = f"usando {act['last_tool']}" + (" (subagente)" if act["sub"] else "")
    return before != (s["state"], s.get("needs"), s.get("tool_count"), s.get("last_reply")) or bool(
        act.get("denied")
        and (s.get("last_denied") or {}).get("at") == act["denied"].get("at")
        and (s.get("last_denied") or {}).get("visto", "") >= (s.get("state_since") or "")
    )


def apply_hook(s: dict, ev: dict, name: str, created: bool) -> None:
    """Lo propio de cada evento de hook sobre una tarjeta que apply_event ya puso al dia (pid, cwd,
    transcripcion, ultimo evento). Se llama con el lock tomado."""
    if name == "SessionStart":
        if s["agent"] == "pi":
            ses.set_state(s, "termino" if ev.get("pi_idle", True) else "corriendo")
        elif created or s.get("state") == "muerta":
            ses.set_state(s, "termino")
    elif name == "PiBusy" and s["agent"] == "pi":
        ses.set_state(s, "corriendo")
    elif name == "PiPromptStart" and s["agent"] == "pi":
        ses.set_needs(s, {"kind": "pi_dialog", "detail": ses.short(ev.get("message", ""), 300), "where": "terminal"})
    elif name == "PiPromptEnd" and s["agent"] == "pi":
        # Closing an idle dialog is not completion of a job: do not fire on_stop.
        if (s.get("needs") or {}).get("kind") == "pi_dialog":
            s["state"], s["state_since"], s["needs"] = (
                ("termino" if ev.get("pi_idle") else "corriendo"),
                ses.now(),
                None,
            )
    elif name == "UserPromptSubmit":
        # un pedido nuevo es un turno nuevo: la compactacion anterior termino aunque PostCompact no
        # haya llegado (coda la aborta sin mandarlo, ver coda_compactacion_abortada). Una marca reciente
        # es la del propio /compact: los dos hooks son procesos aparte y llegan en cualquier orden
        if s.get("compacting") and time.time() - s["compacting"] > COMPACTING_CARRERA_S:
            s["compacting"] = None
        hook_prompt_submit(s, ev)
    elif name == "Stop":
        hook_stop(s, ev)
    elif name == "Notification":
        hook_notification(s, ev)
    elif name == "PermissionRequest":
        pregunta = ses.is_question(ev)
        ses.set_needs(
            s,
            {
                # una pregunta con opciones no es un permiso: la tarjeta la muestra distinto
                "kind": "question" if pregunta else "permission",
                "tool": ev.get("tool_name"),
                "detail": ses.first_question(ev) if pregunta else ses.tool_detail(ev.get("tool_input")),
                "tool_use_id": ev.get("tool_use_id"),
                "where": "lienzo",
            },
        )
    elif name == "PermissionDecision":
        s["pending_id"] = None
        ses.set_state(s, "corriendo")  # set_state ya limpia `needs` al salir de te_necesita
    elif name == "PermissionTimeout":
        if s["state"] == "te_necesita" and s.get("needs"):
            s["needs"]["where"] = "terminal"
        s["pending_id"] = None
    elif name == "PostToolUse":
        # con el id en null no hay con que emparejar y cualquier PostToolUse limpiaria el aviso:
        # AskUserQuestion pide permiso con tool_use_id null (medido el 2026-09-08), y su cierre lo
        # trae igual el PermissionDecision / PermissionTimeout
        tuid = (s.get("needs") or {}).get("tool_use_id")
        if s["state"] == "te_necesita" and tuid and tuid == ev.get("tool_use_id"):
            ses.set_state(s, "corriendo")
    elif name == "PreToolUse" and s["agent"] == "coda":
        coda_tool(s, ev)
    elif name in ("PreCompact", "PostCompact") and s["agent"] == "coda":
        s["compacting"] = time.time() if name == "PreCompact" else None
    elif name == "Interrupt":
        ses.set_state(s, "termino")
    elif name == "SessionEnd":
        ses.marcar_muerta(s, avisar=False)  # /exit, logout o /clear: a proposito, no se avisa


def apply_event(ev: dict) -> None:
    name = ev.get("hook_event_name") or "?"
    sid = ev.get("session_id")
    if not sid or ev.get("agent_id"):
        return  # sin sesion, o subagente
    if ev.get("agent") == "coda" and coda.is_root(sid, ev.get("transcript_path") or None) is False:
        # subagente de CODA: corre en el mismo proceso con sesion propia en la base. No es una
        # tarjeta, pero lo que hace es trabajo de la madre y se ve en la de ella
        madre = coda.parent_of(sid, ev.get("transcript_path") or None)
        if name == "PreToolUse" and madre:
            with ses.lock:
                s = ses.sessions.get(madre)
                if s is not None and s["state"] != "muerta":
                    coda_tool(s, ev, sub=True)
                    ses.touch(s)
        return
    with ses.lock:
        s = ses.sessions.get(sid)
        created = s is None
        if created:
            s = ses.new_session(sid, ev.get("agent") or "claude", "hook")
            ses.sessions[sid] = s
        s["hooked"] = True
        s["source"] = "hook"
        if s.get("state") not in ses.STATES:
            s["state"], s["state_since"] = "termino", ses.now()
        # el evento trae el pid de un proceso que ya termino: quedo en la cola mientras el server
        # estaba apagado, o el agente lo escribio justo antes de cerrarse. Prueba que la sesion
        # existio, no que siga viva: sin esto la tarjeta nacia viva y sin pid, y refresh_alive no
        # toca las tarjetas sin pid, asi que no se moria nunca
        ev_pid_dead = bool(ev.get("pid")) and not ses.backend.agent_alive(ev)
        if ev.get("pid") and not ev_pid_dead:
            claim_pid(s, ev)
        if ses.backend.is_tmux(s) and isinstance(ev.get("tmux_pane"), str) and ses.TMUX_PANE.fullmatch(ev["tmux_pane"]):
            s["target"] = ev["tmux_pane"]
        if ev.get("cwd") and (not s.get("cwd") or name == "SessionStart"):
            # el cwd de los hooks sigue al shell del agente (cambia con un cd de una tool);
            # el repo de la tarjeta se fija al arrancar y no baila
            s["cwd"] = ev["cwd"]
            ses.apply_repo(s, ev["cwd"])
        if ev.get("transcript_path") or (s["agent"] == "pi" and "transcript_path" in ev):
            s["transcript_path"] = ev["transcript_path"]
        if s["agent"] == "pi":
            if "pi_leaf_id" in ev:
                s["pi_leaf_id"] = ev["pi_leaf_id"]
            if "pi_title" in ev and s.get("title_source") != "user":
                ses.choose_title(s, ev["pi_title"])
        s["last_event"] = name
        s["last_event_ts"] = ev.get("host_ts") or ses.now()
        if name == "SessionEnd":
            s["end_reason"] = ev.get("reason") if isinstance(ev.get("reason"), str) else None
        elif name == "SessionStart":
            s["end_reason"] = None
        if not s["alive"] and not created and not ev_pid_dead:
            # dada por muerta y volvio (claude --resume conserva el session_id): el conocimiento por
            # proyecto vuelve su nodo sesion a viva. Con el pid del evento muerto no: marcar_muerta viene
            # unas lineas abajo y los dos hilos correrian a ver quien escribe ultimo
            ses.en_hilo(ses.conocimiento.sesion_viva, s["session_id"])
        s["alive"] = True
        s["dead_since"] = None
        apply_hook(s, ev, name, created)
        if created or name == "SessionStart":
            ses.en_hilo(ses.adopt_dead_target, dict(s))
        if ev_pid_dead and not (s.get("pid") and ses.backend.agent_alive(s)):
            ses.marcar_muerta(s, avisar=False)  # un evento viejo no dice que muriera trabajando ahora
        if created or name in ("SessionStart", "PiTree", "PiMetadata") or (s["agent"] == "pi" and name == "Stop"):
            r = ses.read_transcript(s)
            if r is not None:
                ses.apply_transcript(s, r)
            if s["agent"] == "pi" and name in ("SessionStart", "PiTree"):
                ts = r["turns"] if r else []
                s["last_prompt"] = (ses.turn_prompt(ts[-1]) or "") if ts else ""
                s["last_reply"] = (ts[-1].get("final") or "") if ts else ""
                ses.state.broadcast({"type": "transcript", "session_id": sid, "size": 0})
        ses.touch(s)


# Eventos ya aplicados cuyo archivo Windows no dejo borrar (antivirus, indexador con el archivo
# abierto): sin esto la vuelta siguiente lo releia y lo volvia a aplicar cada 0,25 s (plan de
# refactor 1.6, E8). Se reintenta el borrado en cada vuelta y al lograrlo el nombre sale del set.
# Acotado: los nombres llevan la hora, y uno que lleva tanto sin poder borrarse es basura igual.
_aplicados: dict[str, None] = {}
APLICADOS_MAX = 1000


def _borrar_evento(n: str, p: str) -> None:
    try:
        os.remove(p)
    except FileNotFoundError:
        _aplicados.pop(n, None)
    except OSError as e:
        if n not in _aplicados:
            ses.state.log(f"evento {n}: aplicado pero no se pudo borrar ({e}); no se vuelve a aplicar")
            _aplicados[n] = None
            while len(_aplicados) > APLICADOS_MAX:
                _aplicados.pop(next(iter(_aplicados)))
    else:
        _aplicados.pop(n, None)


# T7 (revisión total, 2026-10-22): un evento que falla al aplicarse (disco lleno, bloqueo al guardar) se
# borraba y se perdía. Va a events/cuarentena para recuperarlo a mano; no se reintenta solo, porque pudo
# haber aplicado una parte y reaplicarlo la duplicaría. Si ni la cuarentena se puede escribir, el archivo
# queda donde está y sólo se reintenta moverlo, nunca aplicarlo de nuevo.
_sin_cuarentena: dict[str, None] = {}


def _a_cuarentena(n: str, p: str) -> None:
    try:
        destino = os.path.join(EVENTS, "cuarentena")
        os.makedirs(destino, exist_ok=True)
        os.replace(p, os.path.join(destino, n))
    except FileNotFoundError:
        _sin_cuarentena.pop(n, None)
    except OSError as e:
        if n not in _sin_cuarentena:
            ses.state.log(f"evento {n}: falló y tampoco se pudo mover a cuarentena ({e}); queda y no se reaplica")
            _sin_cuarentena[n] = None
            while len(_sin_cuarentena) > APLICADOS_MAX:
                _sin_cuarentena.pop(next(iter(_sin_cuarentena)))
    else:
        if _sin_cuarentena.pop(n, None) is None:
            ses.state.log(f"evento {n}: falló al aplicarse; quedó en {EVENTS}/cuarentena para recuperarlo")


def consume_events() -> None:
    while True:
        consume_once()
        time.sleep(0.25)


def consume_once() -> None:
    """Una vuelta sobre ~/.lienzo/events: aplica cada evento y borra su archivo."""
    try:
        names = sorted(os.listdir(EVENTS))
        ses.state.avisar_si_cambia("events", None)
    except OSError as e:
        # sin carpeta de eventos no llega ningun hook: antes no se decia (plan de refactor 1.15)
        ses.state.avisar_si_cambia("events", f"no se puede leer {EVENTS}: {e}; no llegan eventos de los hooks")
        names = []
    for n in names:
        p = os.path.join(EVENTS, n)
        if n.endswith(".tmp"):
            continue
        if n in _aplicados:
            _borrar_evento(n, p)  # ya aplicado: solo falta que Windows lo suelte
            continue
        if n in _sin_cuarentena:
            _a_cuarentena(n, p)  # ya falló una vez: sólo falta moverlo
            continue
        if not n.endswith(".json"):
            try:
                # bad-*.txt: lo que un hook no pudo parsear. El getmtime iba fuera del try y un
                # archivo que desaparecia entre el listdir y esta linea mataba el hilo entero
                if n.startswith("bad-") and time.time() - os.path.getmtime(p) > 3600:
                    os.remove(p)
            except OSError:
                pass
            continue
        try:
            with open(p, encoding="utf-8") as f:
                ev = json.load(f)
        except OSError, ValueError:
            ses.state.log(f"evento {n} ilegible:\n{traceback.format_exc()}")
            _borrar_evento(n, p)  # inválido para siempre: reintentar no lo arregla
            continue
        try:
            apply_event(ev)
        except Exception:
            ses.state.log(f"evento {n} fallo:\n{traceback.format_exc()}")
            _a_cuarentena(n, p)
            continue
        _borrar_evento(n, p)
