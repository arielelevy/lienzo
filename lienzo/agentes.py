"""Proveedores de CLI: contrato comun de identidad, transcripcion, modelo, dialogo y reanudacion.

No importa sessions. Los lectores de procesos y parsers se reciben al llamar para evitar ciclos
y conservar los formatos propios. agent-capabilities.json tambien lo consume el frontend.
Las guess_* siguen siendo publicas para los consumidores y sus pruebas.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

try:
    import tmux
    from state import HOME, claude_slug, parse_ts
except ImportError:  # importado como lienzo.agentes, sin lienzo/ en sys.path
    from . import tmux
    from .state import HOME, claude_slug, parse_ts

# --- registro de agentes ----------------------------------------------------------------------
CAPACIDADES = json.loads(Path(__file__).with_name("agent-capabilities.json").read_text(encoding="utf-8"))
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


@dataclass(frozen=True)
class Perfil:
    """Los datos de un agente. `retomar_por_id` son los argumentos que van ANTES del session_id
    (claude y codex retoman una sesion dada); `retomar_ultima`, los que retoman «la ultima de esta
    carpeta» sin id (pi y coda). `parser` es el NOMBRE de la funcion de transcripts.py, que se busca
    recien al parsear (guardar la funcion al importar dejaria afuera los monkeypatch), y
    `parser_args` dice cuales de max_bytes / leaf_id recibe despues de la ruta, en ese orden.
    `nombrar` son los argumentos que van ANTES del nombre corto de la sesion al lanzarla (ver
    launch._nombre_args); vacio si el agente no se deja nombrar."""

    exe: str
    parser: str
    parser_args: tuple[str, ...]
    retomar_por_id: tuple[str, ...] = ()
    retomar_ultima: tuple[str, ...] = ()
    acepta_modelo: bool = False
    nombrar: tuple[str, ...] = ()
    iniciar: tuple[str, ...] = ()

    identity_key: ClassVar[str | None] = None
    persist_unhooked: ClassVar[bool] = False
    after_dialog: ClassVar[str] = "termino"
    live_dialog_with_hooks: ClassVar[bool] = False
    supported_platforms: ClassVar[tuple[str, ...]] = ("win32", "linux", "darwin")

    @property
    def capabilities(self) -> dict:
        return CAPACIDADES[self.parser.removeprefix("parse_")]

    def valid_id(self, sid, *, strict: bool = True) -> bool:
        if not isinstance(sid, str) or not sid:
            return False
        pattern = UUID_PATTERN if strict else r"[0-9a-fA-F-]{8,40}"
        return not self.retomar_por_id or bool(re.fullmatch(pattern, sid))

    def resume_args(self, sid) -> list[str]:
        if not sid:
            return []
        if self.retomar_ultima:
            return list(self.retomar_ultima)
        return [*self.retomar_por_id, sid] if self.valid_id(sid, strict=False) else []

    def identity(self, process: dict, readers: dict):
        return None

    def guess(self, cwd: str, born, home: str):
        return guess_claude(cwd, born.timestamp() - BIRTH_MARGIN_S if born else 0, home)

    def parse(self, path: str, parsers: dict, **args) -> dict:
        return parsers[self.parser](path, *(args[a] for a in self.parser_args))

    def model(self, path: str, transcripts) -> str | None:
        if not path:
            return None
        try:
            lines, _ = transcripts.tail_lines(path)
        except OSError:
            return None
        model = None
        for row in transcripts.iter_json(lines):
            model = self.row_model(row) or model
        return model

    def row_model(self, row: dict) -> str | None:
        msg = row.get("message")
        return msg.get("model") if isinstance(msg, dict) and msg.get("role") == "assistant" else None

    def waiting_text(self, turn: dict) -> str | None:
        return None

    def stop_is_final(self, reason: str | None) -> bool:
        return True

    def decorate_dialog(self, dialog: dict, transcript: dict) -> None:
        pass

    def same_dialog(self, current: dict, previous: dict, read_transcript) -> bool:
        return True

    # Con que arranca la pregunta de un permiso dibujado como dialogo en ESTA TUI (el auto-aprobar
    # lo contesta; una pregunta de verdad, «Switch model?» o la confianza en una carpeta no empiezan
    # asi). La base es la de Claude Code, igual que `guess`. Sin comodin «do you want to»: no todo lo
    # que empieza asi es un permiso («Do you want to use this API key?»)
    preguntas_de_permiso: ClassVar[tuple[str, ...]] = (
        "do you want to proceed",
        "do you want to make",
        "do you want to create",
        "do you want to run",
        "do you want to read",
        "do you want to write",
        "do you want to edit",
        "do you want to fetch",
        "do you want to allow",
        "would you like to proceed",  # salir del plan (ExitPlanMode): «Yes» / «No, keep planning»
    )

    def permission_option(self, dialog: dict | None) -> int | None:
        """La opcion que permite, si `dialog` (de screen.dialog) es un permiso de esta TUI, o None.
        Es un permiso si la pregunta arranca como una de `preguntas_de_permiso` o alguna opcion
        ofrece «don't ask again» (eso solo lo tiene un permiso, y sirve cuando la pregunta se leyo
        mal: un comando largo la deja lejos de las opciones, medido el 2026-10-08). Permite la
        primera «Yes» que no sea «don't ask again» (eso ademas lo recordaria)."""
        q, ops = _dialogo_plano(dialog)
        if not ops:
            return None
        if not q.startswith(self.preguntas_de_permiso) and not any("ask again" in t for _, t in ops):
            return None
        return next((n for n, t in ops if t.startswith("yes") and "ask again" not in t), None)

    def permission_reason(self, dialog: dict | None) -> str:
        """Por que el auto-aprobar NO contesta este dialogo (para la tarjeta). Por como arranca la
        pregunta, no por una palabra suelta («Which model should the pipeline use?» no es el
        cambio de modelo)."""
        q, _ops = _dialogo_plano(dialog)
        if q.startswith("do you trust") or "accessing workspace" in q:
            return "la confianza en una carpeta la decide el humano"
        if q.startswith(("switch model", "select model")):
            return "el cambio de modelo lo decide el humano"
        return "no es un permiso: es una pregunta con opciones"


def _dialogo_plano(dialog: dict | None) -> tuple[str, list[tuple[int | None, str]]]:
    """(pregunta, [(n, texto)]) en minusculas y sin bordes, para comparar."""
    if not dialog:
        return "", []
    q = (dialog.get("question") or "").strip().lower()
    ops = [(o.get("n"), (o.get("text") or "").strip().lower()) for o in dialog.get("options") or []]
    return q, ops


class Codex(Perfil):
    identity_key = "codex_session"
    after_dialog = "corriendo"
    live_dialog_with_hooks = True
    # «Would you like to run the following command?» con «Yes, proceed (y)» / «Yes, and don't ask
    # again for commands that start with ...» (medido el 2026-10-08 en Teorema y A); el parche de
    # archivos pregunta «Would you like to make/apply the following edits?» sin «don't ask again»
    preguntas_de_permiso = (
        "would you like to run",
        "would you like to proceed",
        "would you like to make",
        "would you like to apply",
        "would you like to edit",
    )

    def guess(self, cwd: str, born, home: str):
        return None, None  # cwd y fecha no vinculan un rollout al proceso

    def identity(self, process: dict, readers: dict):
        try:
            import codex_identity
        except ImportError:
            from . import codex_identity
        proof = codex_identity.transcript_identity(process["pid"])
        return (proof["thread"], proof["path"]) if proof["verified"] or proof.get("observed") else None

    def row_model(self, row: dict) -> str | None:
        payload = row.get("payload")
        return payload.get("model") if row.get("type") == "turn_context" and isinstance(payload, dict) else None


class Pi(Perfil):
    identity_key = "pi_session"
    preguntas_de_permiso = ()  # Pi pide por la extension (pi_dialog), no con un dialogo numerado

    def permission_option(self, dialog: dict | None) -> int | None:
        return None

    def guess(self, cwd: str, born, home: str):
        return guess_pi(cwd, born.timestamp()) if born else (None, None)

    def identity(self, process: dict, readers: dict):
        return readers["pi"](process["pid"], process.get("children") or [])


class Coda(Perfil):
    identity_key = "coda_session"
    preguntas_de_permiso = ()  # coda tiene su cartel «Approval Required» (autoaprobar.DialogoDeCoda)

    def permission_option(self, dialog: dict | None) -> int | None:
        return None

    def guess(self, cwd: str, born, home: str):
        return None, None

    def identity(self, process: dict, readers: dict):
        return readers["coda"](process["pid"])

    def model(self, path: str, transcripts) -> str | None:
        return None

    def stop_is_final(self, reason: str | None) -> bool:
        # hooks.md de CODA solo documenta turn_complete. No inventar otros finales.
        return reason in (None, "", "turn_complete")


class Kiro(Perfil):
    identity_key = "kiro_session"
    persist_unhooked = True
    after_dialog = "corriendo"
    live_dialog_with_hooks = True
    supported_platforms = ("win32",)  # identidad verificada con el motor de V3 en Windows
    preguntas_de_permiso = ()

    def permission_option(self, dialog: dict | None) -> int | None:
        """Kiro V3 pide «requires approval» con Allow / Always allow / Deny / Always deny (sin
        numeros, se elige con flechas): permite «Allow», nunca «Always allow»."""
        q, ops = _dialogo_plano(dialog)
        allow_deny = any(t.startswith("allow") for _, t in ops) and any(t.startswith("deny") for _, t in ops)
        if not ("requires approval" in q or "requiere permiso" in q or allow_deny):
            return None
        return next((n for n, t in ops if t == "allow"), None)

    def permission_reason(self, dialog: dict | None) -> str:
        q, ops = _dialogo_plano(dialog)
        if "requires approval" in q or "requiere permiso" in q or any(t.startswith("allow") for _, t in ops):
            return "es un permiso de Kiro pero no se leyo la opcion «Allow»: contestalo en la terminal"
        return super().permission_reason(dialog)

    def guess(self, cwd: str, born, home: str):
        return None, None

    def identity(self, process: dict, readers: dict):
        return readers["kiro"](process["pid"])

    def valid_id(self, sid, *, strict: bool = True) -> bool:
        return isinstance(sid, str) and bool(re.fullmatch("sess_" + UUID_PATTERN, sid))

    def model(self, path: str, transcripts) -> str | None:
        try:
            from . import kiro
        except ImportError:
            import kiro
        return kiro.read_metadata(path).get("modelId") if path else None

    def waiting_text(self, turn: dict) -> str | None:
        return "Pensando…" if not turn.get("ended") else None

    def decorate_dialog(self, dialog: dict, transcript: dict) -> None:
        turns = transcript.get("turns") or []
        if turns:
            dialog["kiro_tool_call_id"] = (turns[-1].get("kiro_pending") or {}).get("toolCallId")

    def same_dialog(self, current: dict, previous: dict, read_transcript) -> bool:
        if (current.get("question"), current.get("detail")) != (previous.get("question"), previous.get("detail")):
            return False
        if previous.get("kiro_tool_call_id"):
            turns = (read_transcript() or {}).get("turns") or []
            pending = (turns[-1].get("kiro_pending") or {}) if turns else {}
            return pending.get("toolCallId") == previous["kiro_tool_call_id"]
        return True


AGENTES: dict[str, Perfil] = {
    "kiro": Kiro(
        exe="kiro-cli.exe",
        parser="parse_kiro",
        parser_args=("max_bytes",),
        retomar_por_id=("--resume-id",),
        iniciar=("--v3",),
    ),
    "claude": Perfil(
        exe="claude.exe",
        parser="parse_claude",
        parser_args=("max_bytes",),
        retomar_por_id=("--resume",),
        acepta_modelo=True,
        # -n le da el nombre con que la ven ListAgents y SendMessage (si no, sale «chess-f6»), y
        # --remote-control la publica en la cuenta: sin eso el canal nativo no cruza PCs
        nombrar=("-n", "{nombre}", "--remote-control", "{nombre}"),
    ),
    "codex": Codex(
        exe="codex.exe",
        parser="parse_codex",
        parser_args=("max_bytes",),
        retomar_por_id=("resume",),
        acepta_modelo=True,
    ),
    # Pi elige la rama activa con leaf_id; no recibe --model
    "pi": Pi(exe="pi.exe", parser="parse_pi", parser_args=("max_bytes", "leaf_id"), retomar_ultima=("--resume",)),
    # CODA guarda todas las sesiones en una misma base: leaf_id es la sesion, y se lee por filas, no por bytes
    "coda": Coda(
        exe="coda.exe",
        parser="parse_coda",
        parser_args=("leaf_id",),
        retomar_ultima=("--lastsession",),
        acepta_modelo=True,
    ),
}


class AgenteDesconocido(ValueError):
    """Un agente que no esta en AGENTES. Antes transcripts.parse lo leia como Claude sin avisar."""


def perfil(agent: str) -> Perfil:
    """El perfil de `agent`, o AgenteDesconocido con el nombre."""
    p = AGENTES.get(agent) if isinstance(agent, str) else None
    if p is None:
        raise AgenteDesconocido(f"agente desconocido: {agent!r} (conocidos: {', '.join(AGENTES)})")
    return p


# --- adivinar la transcripcion de un agente del barrido ---------------------------------------

BIRTH_MARGIN_S = 120  # margen a los dos lados del nacimiento del proceso, que el barrido fecha grueso


def transcript_home(d: dict) -> str:
    """La base donde viven las transcripciones de este agente. Los de WSL vistos desde Windows estan
    en la home de WSL, que se lee por UNC (\\wsl.localhost\\...); el resto, en la home local."""
    if d.get("backend") == "tmux" and tmux._VIA_WSL:
        return tmux.wsl_unc_home() or HOME
    return HOME


def guess_claude(cwd: str, t0: float, home: str = HOME) -> tuple[str | None, str | None]:
    """Claude guarda una transcripcion por sesion en un directorio por cwd, y el nombre del archivo
    ES el session_id: alcanza con la mas nueva que siga viva despues de `t0`."""
    d = os.path.join(home, ".claude", "projects", claude_slug(cwd))
    cands = [(m, p) for p in glob.glob(os.path.join(d, "*.jsonl")) if (m := _mtime(p)) is not None and m >= t0]
    if not cands:
        return None, None
    p = max(cands, key=lambda c: c[0])[1]
    return os.path.splitext(os.path.basename(p))[0], p


def _mtime(path: str) -> float | None:
    """getmtime que no levanta: entre el glob y el stat una transcripcion puede borrarse (un /clear,
    una limpieza), y el OSError cortaba el barrido entero (plan de refactor 1.5)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def guess_codex(cwd: str, t0: float, home: str = HOME) -> tuple[str | None, str | None]:
    """Sin PID no hay identidad comprobable: no adjudicar por fecha ni cwd.

    Conserva el contrato público. El descubrimiento usa Codex.identity con
    evidencia actual vinculada al proceso, incluso si el rollout es anterior.
    """
    return None, None


# Registro de sesiones vivas de Claude Code (medido 2026-10-17): `<config>/sessions/<pid>.json`, uno por
# proceso, para la CLI y para el motor de Claude Desktop. De ahi solo salen estos campos: el `.key` de
# al lado y `messagingSocketPath` (el pipe del canal) no se leen ni se exponen.
CLAUDE_REGISTRO_CAMPOS = ("sessionId", "entrypoint", "name", "kind", "status", "version", "peerProtocol")


def claude_registro(pid: int, proc_start: int | None) -> dict | None:
    """Lo que Claude Code anota de la sesion del proceso `pid`, o None. Exige `proc_start` (la creacion
    del proceso como FILETIME) igual al `procStart` anotado: el archivo de un proceso muerto puede quedar
    y su pid reciclarse. Respeta CLAUDE_CONFIG_DIR, como Claude Code."""
    if not pid or proc_start is None:
        return None
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
    try:
        with open(os.path.join(base, "sessions", f"{int(pid)}.json"), encoding="utf-8") as f:
            reg = json.load(f)
    except OSError, ValueError:
        return None
    if not isinstance(reg, dict) or reg.get("pid") != int(pid) or str(reg.get("procStart")) != str(proc_start):
        return None
    return {k: reg[k] for k in CLAUDE_REGISTRO_CAMPOS if k in reg}


# Hilos de la app de escritorio de Codex (medido 2026-10-17 sobre ~/.codex/sessions): la app no tiene
# un proceso por hilo (su codex.exe es un app-server compartido), asi que el hilo se ve por su rollout.
# Los reales dicen `codex_work_desktop`; los `Codex Desktop` de esta PC son todos transcripciones de
# Claude importadas (external_agent_session_imports.json), que no son trabajo en curso.
DESKTOP_ORIGINATORS = ("codex_work_desktop", "Codex Desktop")
_cabeceras: dict[str, dict | None] = {}  # rollout -> cabecera del hilo de la app, o None si no es de la app
_importados: tuple[float, frozenset[str]] = (-1.0, frozenset())


def _cabecera_desktop(path: str) -> dict | None:
    """La cabecera del rollout si es un hilo de la app, o None. Se lee una vez por archivo: la
    cabecera no cambia aunque el rollout crezca."""
    if path in _cabeceras:
        return _cabeceras[path]
    try:
        with open(path, "rb") as f:
            pl = json.loads(f.readline().decode("utf-8", errors="replace")).get("payload") or {}
    except OSError, ValueError, AttributeError:
        return None  # a medio escribir: se reintenta en la proxima vuelta
    cab = None
    if pl.get("originator") in DESKTOP_ORIGINATORS and (pl.get("id") or pl.get("session_id")):
        cab = {
            "id": pl.get("id") or pl.get("session_id"),
            "cwd": pl.get("cwd"),
            "originator": pl["originator"],
            "started": pl.get("timestamp"),
        }
    _cabeceras[path] = cab
    return cab


def _ids_importados(codex_home: str) -> frozenset[str]:
    """Hilos que Codex armo importando transcripciones de otro agente: no son trabajo de la app."""
    global _importados
    path = os.path.join(codex_home, "external_agent_session_imports.json")
    mtime = _mtime(path)
    if mtime is None:
        return frozenset()
    if mtime != _importados[0]:
        try:
            with open(path, encoding="utf-8") as f:
                records = json.load(f).get("records") or []
            ids = frozenset(
                r["imported_thread_id"] for r in records if isinstance(r, dict) and r.get("imported_thread_id")
            )
        except OSError, ValueError, AttributeError, TypeError:
            ids = _importados[1]  # ilegible ahora: el ultimo conjunto bueno
        _importados = (mtime, ids)
    return _importados[1]


def codex_desktop_threads(since: float, codex_home: str | None = None) -> list[dict]:
    """Hilos de la app de Codex con actividad desde `since` (epoch): `{id, path, cwd, originator,
    started, mtime}`. Solo stat de cada rollout; abre la cabecera de los nuevos, una vez. Respeta
    CODEX_HOME, como Codex (y las pruebas, que lo apuntan a una carpeta temporal)."""
    codex_home = codex_home or os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    importados = _ids_importados(codex_home)
    hilos = []
    for p in glob.glob(os.path.join(codex_home, "sessions", "*", "*", "*", "rollout-*.jsonl")):
        mtime = _mtime(p)
        if mtime is None or mtime < since:
            continue
        cab = _cabecera_desktop(p)
        if cab and cab["id"] not in importados:
            hilos.append({**cab, "path": p, "mtime": mtime})
    return hilos


def guess_pi(cwd: str, born: float) -> tuple[str | None, str | None]:
    """Respaldo para una unica Pi en el proyecto, sin extension ni shell hijo observable.

    Pi puede reanudar un archivo anterior al proceso: importa su actividad, no el nombre
    ni la fecha de creacion. Verificar cwd e id de la cabecera, y actividad posterior al
    nacimiento. El llamador excluye proyectos compartidos por varias TUIs de Pi.
    """
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent")
    slug = "--" + re.sub(r"[\\/:]", "-", re.sub(r"^[\\/]", "", cwd)) + "--"
    folder = os.environ.get("PI_CODING_AGENT_SESSION_DIR") or os.path.join(agent_dir, "sessions", slug)
    candidates = []
    for path in glob.glob(os.path.join(folder, "*.jsonl")):
        try:
            modified = os.path.getmtime(path)
            if modified < born:
                continue
            with open(path, encoding="utf-8") as f:
                header = json.loads(f.readline(65536))
            if not isinstance(header, dict) or header.get("type") != "session":
                continue
            if not isinstance(header.get("id"), str) or not header["id"]:
                continue
            if not isinstance(header.get("cwd"), str) or os.path.normcase(header["cwd"]) != os.path.normcase(cwd):
                continue
            candidates.append((modified, header["id"], path))
        except OSError, ValueError:
            continue
    candidates.sort(reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
        return None, None
    return candidates[0][1], candidates[0][2]


def guess_transcript(
    agent: str, cwd: str | None, created: str | None, home: str = HOME
) -> tuple[str | None, str | None]:
    """(session_id, transcript_path) mas probable para un agente encontrado por barrido: el barrido
    solo sabe pid y cwd, y de ahi hay que deducir de que sesion se trata. `created` es el
    nacimiento del proceso, con BIRTH_MARGIN_S de margen porque las dos fechas no son la misma
    (el rollout se crea un rato despues de abrir la TUI). `home` es la base de las transcripciones
    (la home de WSL por UNC para los agentes de WSL)."""
    provider = perfil(agent)
    if not cwd:
        return None, None
    born = parse_ts(created)
    return provider.guess(cwd, born, home)
