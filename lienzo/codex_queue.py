"""Enviar a hilos de Codex (CLI o app de escritorio) con `codex queue`, sin teclear.

Medido el 2026-10-17 (codex-cli 0.163.0, informe-A-codex-queue.md):
- `codex queue --thread <id> --message <texto>` entrega a un hilo de TUI vivo y quieto en ~0,5 s, y a uno
  ocupado lo deja en cola y lo entra como turno siguiente al terminar el actual. Multilínea, comillas, `$`, `%`,
  `&|<>^!`, emoji y 22 000 caracteres llegan exactos (argv a un `codex.exe` nativo, sin shell).
- Un id inexistente sale con código 1 y «no rollout found for thread id».
- Con el proceso del hilo CERRADO también «entrega»: el app-server compartido de Codex ejecuta el turno en
  segundo plano, sin terminal ni app visibles. Por eso un hilo de CLI sin proceso vivo, o de la app cerrada,
  se rechaza con motivo en vez de encolar. Una CLI viva también se rechaza: su PID no prueba que
  conserve el hilo después de /new o /clear. Un rollout abierto estable y la fecha de creación tampoco
  prueban el hilo visible: la reproducción real de /new conservó ambos. El sondeo rechaza esa
  identidad incierta; no se habilita queue CLI hasta disponer de una vinculación autoritativa.

Estados de un envío: `rechazado` (con motivo), `encolado` (codex lo aceptó), `entregado` (el texto aparece en el
rollout del hilo como mensaje de usuario) y `sin_confirmacion` (pasó el plazo sin verlo; visible, sin reintento).
El texto nunca va a los logs: sólo su largo y un hash.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import codex_identity
import procinfo
import procs
import state
import subproc
from atomico import atomic_write

QUEUE_TIMEOUT = 20
CONFIRM_WAIT_S = 8  # lo que `enviar` espera ver el mensaje en el rollout antes de devolver «encolado»
CONFIRM_LIMIT_S = 600  # sin verlo en este plazo, el envío queda «sin_confirmacion»
DUPLICATE_S = 60  # el mismo texto al mismo hilo dentro de este plazo no se vuelve a encolar (doble envío)
MAX_MESSAGE = 24000  # la línea de comandos de Windows tiene un techo de 32 767 caracteres
ROLLOUT_TAIL = 4 * 1024 * 1024
APP_CACHE_S = 10
THREAD_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
QUEUED = re.compile(r"Queued message ([0-9a-f-]{36}) for thread ([0-9a-f-]{36})")
_lock = threading.Lock()
_app = {"at": -1e9, "running": False}


def store_path() -> Path:
    return Path(state.LIENZO) / "codex-queue-envios.json"


def codex_exe() -> str | None:
    """`codex.exe` nativo. Un `.cmd`/`.ps1` haría pasar el texto por un shell: no se usa."""
    exe = shutil.which("codex")
    return exe if exe and exe.lower().endswith(".exe") else None


def message_fits(s: dict, message: str) -> bool:
    """CreateProcess cuenta UTF-16 del argv citado, no caracteres Unicode del mensaje."""
    argv = [codex_exe() or "codex.exe", "queue", "--thread", s.get("session_id", ""), "--message", message]
    return len(message) <= MAX_MESSAGE and (
        not subproc.WINDOWS or len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2 < 32767
    )


def _pids() -> list[int]:
    if not procinfo._WIN:
        return []
    arr = (ctypes.c_ulong * 8192)()
    needed = ctypes.c_ulong()
    if not ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    return [arr[i] for i in range(needed.value // ctypes.sizeof(ctypes.c_ulong)) if arr[i]]


def app_running() -> bool:
    """La app de escritorio de Codex (ChatGPT.exe bajo WindowsApps\\OpenAI.Codex_) está abierta."""
    with _lock:
        if time.monotonic() - _app["at"] < APP_CACHE_S:
            return _app["running"]
    running = any(procs.desktop_app(procinfo.image_path(pid)) == "codex-desktop" for pid in _pids())
    with _lock:
        _app.update(at=time.monotonic(), running=running)
    return running


def es_desktop(s: dict) -> bool:
    ext = s.get("external") or {}
    return ext.get("kind") == "codex-desktop" and ext.get("via") == "rollout"


def _no(motivo: str) -> dict:
    return {"puede": False, "motivo": motivo, "transporte": None}


def puede_enviar(s: dict, contexto: dict | None = None) -> dict:
    """`{puede, motivo, transporte}` para mandar por `codex queue` a la tarjeta `s`. No mira las guardias
    comunes de la tarjeta (detenida, permiso pendiente): eso lo hace `sessions.puede_enviar`."""
    if s.get("agent") != "codex":
        return _no("no es una sesión de Codex")
    thread = s.get("session_id") or ""
    if not THREAD_ID.match(thread):
        return _no("la tarjeta no tiene el id de hilo de Codex (todavía no se lo conoce)")
    rollout = s.get("transcript_path")
    if not rollout or not os.path.isfile(rollout):
        return _no("no se encontró el rollout del hilo: no se podría confirmar la entrega")
    if codex_exe() is None:
        return _no("codex.exe no está en el PATH de esta PC")
    if es_desktop(s):
        if not app_running():
            return _no("la app de Codex no está abierta: codex queue ejecutaría el turno en segundo plano, sin la app")
    elif not s.get("pid") or not procinfo.alive(s["pid"]):
        return _no("el proceso del hilo terminó: codex queue ejecutaría el turno en segundo plano, sin terminal")
    else:
        identity = codex_identity.probe(s["pid"])
        if not identity["verified"]:
            return _no(f"identidad de hilo CLI sin verificar: {identity['reason']}")
        if identity["process_start"] != s.get("codex_process_start"):
            return _no(
                "identidad de hilo CLI sin verificar: creación del proceso distinta o no registrada (PID reciclado)"
            )
        if identity["thread"] != thread or os.path.normcase(os.path.realpath(identity["path"])) != os.path.normcase(
            os.path.realpath(rollout)
        ):
            return _no(
                "identidad de hilo CLI sin verificar: el proceso tiene otro rollout activo; esperar reidentificación"
            )
    return {"puede": True, "motivo": None, "transporte": "codex_queue"}


def _digest(thread: str, message: str) -> str:
    return hashlib.sha256(f"{thread}\0{message}".encode()).hexdigest()[:24]


def _load() -> dict:
    try:
        text = store_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict) or any(
        not isinstance(v, dict)
        or v.get("envio_id") != key
        or v.get("estado") not in ("pendiente", "encolado", "sin_confirmacion", "entregado", "rechazado")
        or type(v.get("at")) not in (int, float)
        or not 0 <= v["at"] <= 253_402_300_799  # timestamp UTC hasta 9999-12-31; también rechaza NaN/inf
        or any(not isinstance(v.get(field), str) for field in ("thread", "rollout", "sha256", "desde"))
        for key, v in data.items()
    ):
        raise ValueError("estructura del diario inválida")
    return data


def _diario_fallido(envio_id: str, *, enviado: bool = False) -> dict:
    return {
        "estado": "sin_confirmacion" if enviado else "rechazado",
        "motivo": "No se pudo leer o guardar el diario de envíos; se conserva sin sobrescribir. "
        + ("El envío pudo ejecutarse; no se reintenta." if enviado else "No se envió nada."),
        "envio_id": envio_id,
        "referencia": None,
        "transporte": "codex_queue" if enviado else None,
    }


def _save(data: dict) -> None:
    cutoff = time.time() - 86400
    # Una reserva incierta no vence con el historial: olvidarla permitiría un reenvío ciego.
    data = {
        k: v
        for k, v in data.items()
        if v.get("at", 0) >= cutoff or v.get("estado") in ("pendiente", "encolado", "sin_confirmacion")
    }
    store_path().parent.mkdir(parents=True, exist_ok=True)
    atomic_write(str(store_path()), json.dumps(data, ensure_ascii=False))


def _user_messages_since(rollout: str, since_iso: str) -> list[str]:
    try:
        with open(rollout, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - ROLLOUT_TAIL))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    texts = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        payload = event.get("payload") if isinstance(event, dict) else None
        if (
            isinstance(payload, dict)
            and event.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "user"
            and str(event.get("timestamp") or "") >= since_iso
        ):
            texts.append("".join(c.get("text", "") for c in payload.get("content", []) if isinstance(c, dict)))
    return texts


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r", "").strip().encode()).hexdigest()[:16]


def delivered(rollout: str, sha: str, since_iso: str) -> bool:
    """El mensaje (por su hash) aparece en el rollout como mensaje de usuario desde `since_iso`."""
    return any(_sha(text) == sha for text in _user_messages_since(rollout, since_iso))


def _iso(moment: float) -> str:
    return dt.datetime.fromtimestamp(moment, dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _public(record: dict) -> dict:
    return {k: record.get(k) for k in ("estado", "motivo", "referencia", "envio_id", "transporte", "at")}


def enviar(s: dict, mensaje: str, contexto: dict | None = None, *, esperar: float = CONFIRM_WAIT_S) -> dict:
    """`{estado, motivo, referencia, envio_id, transporte}`. Vuelve a comprobar `puede_enviar`; nunca encola
    dos veces el mismo envío ni reintenta solo."""
    plan = puede_enviar(s, contexto)
    if not plan["puede"]:
        return {
            "estado": "rechazado",
            "motivo": plan["motivo"],
            "referencia": None,
            "envio_id": None,
            "transporte": None,
        }
    message = (mensaje or "").replace("\r", "").strip()
    if not message:
        return {
            "estado": "rechazado",
            "motivo": "texto vacío",
            "referencia": None,
            "envio_id": None,
            "transporte": None,
        }
    if not message_fits(s, message):
        motivo = (
            f"mensaje de {len(message)} caracteres: más que el techo de la línea de comandos; mandarlo como adjunto"
        )
        return {"estado": "rechazado", "motivo": motivo, "referencia": None, "envio_id": None, "transporte": None}
    thread, rollout = s["session_id"], s["transcript_path"]
    envio_id = (contexto or {}).get("envio_id") or _digest(thread, message)
    with _lock:
        try:
            data = _load()
        except OSError, ValueError:
            return _diario_fallido(envio_id)
        previous = data.get(envio_id)
        if previous and (
            previous["estado"] in ("pendiente", "encolado", "sin_confirmacion")
            or (previous["estado"] == "entregado" and time.time() - previous["at"] < DUPLICATE_S)
        ):
            return {
                **_public(previous),
                "motivo": "ese mismo envío sigue reservado o ya se mandó; no se encola de nuevo",
            }
        started = time.time()
        record = {
            "envio_id": envio_id,
            "thread": thread,
            "rollout": rollout,
            "sha256": _sha(message),
            "largo": len(message),
            "at": started,
            "desde": _iso(started - 1),
            "estado": "pendiente",
            "transporte": "codex_queue",
        }
        data[envio_id] = record
        try:
            _save(data)
        except OSError, ValueError:
            return _diario_fallido(envio_id)
    code, out, err = subproc.correr(
        [codex_exe(), "queue", "--thread", thread, "--message", message], timeout=QUEUE_TIMEOUT
    )
    match = QUEUED.search(out or "")
    if code != 0 or not match or match.group(2) != thread:
        detail = (err or out or "").replace(message, "[mensaje]").strip()[-300:]
        # Sin confirmación correlacionada no sabemos si el daemon aceptó antes del error/timeout.
        # NO_ARRANCO sí garantiza que no hubo proceso; el resto conserva la reserva sin reenvío.
        rejected = code == subproc.NO_ARRANCO or (code != 0 and "no rollout found" in detail)
        record.update(
            estado="rechazado" if rejected else "sin_confirmacion",
            motivo=f"codex queue salió con código {code}: {detail}"
            + ("" if rejected else "; resultado incierto, no se reintenta"),
            codigo=code,
        )
    else:
        record.update(estado="encolado", motivo=None, referencia=match.group(1), codigo=0)
        deadline = time.monotonic() + esperar
        while time.monotonic() < deadline:
            if delivered(rollout, record["sha256"], record["desde"]):
                record["estado"] = "entregado"
                break
            time.sleep(0.25)
    with _lock:
        try:
            data = _load()
            data[envio_id] = record
            _save(data)
        except OSError, ValueError:
            return _diario_fallido(envio_id, enviado=True)
    state.log(
        f"codex queue {thread[:8]}: {record['estado']} ({record['largo']} caracteres, sha {record['sha256']})"
        + (f": {record['motivo']}" if record.get("motivo") else "")
    )
    return _public(record)


def confirmar(envio_id: str) -> dict:
    """Revisa un envío encolado: `entregado` si ya está en el rollout; pasado CONFIRM_LIMIT_S, `sin_confirmacion`."""
    with _lock:
        try:
            data = _load()
        except OSError, ValueError:
            return _diario_fallido(envio_id, enviado=True)
        record = data.get(envio_id)
        if record is None:
            return {
                "estado": "desconocido",
                "motivo": "envío no registrado",
                "referencia": None,
                "envio_id": envio_id,
                "transporte": None,
            }
        if record["estado"] in ("pendiente", "encolado", "sin_confirmacion"):
            if delivered(record["rollout"], record["sha256"], record["desde"]):
                record["estado"], record["motivo"] = "entregado", None
            elif time.time() - record["at"] > CONFIRM_LIMIT_S:
                record["estado"] = "sin_confirmacion"
                record["motivo"] = f"no apareció en el rollout del hilo en {CONFIRM_LIMIT_S // 60} min; no se reintenta"
            data[envio_id] = record
            try:
                _save(data)
            except OSError, ValueError:
                return _diario_fallido(envio_id, enviado=True)
        return _public(record)
