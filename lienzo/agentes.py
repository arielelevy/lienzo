"""Lo que cambia de un agente a otro (claude, codex, pi, coda), en un modulo hoja: no importa sessions
ni nada que lo importe, asi que launch, restore, transcripts y sessions lo pueden leer sin ciclos.

Dos cosas:
- `AGENTES`, el registro con los DATOS de cada agente (`Perfil`): ejecutable, como se retoma, si
  acepta --model y que parser lee su transcripcion. Lo leen launch.py, restore.py y
  transcripts.parse. Las ramas de COMPORTAMIENTO (lo que Pi o CODA hacen distinto en sessions.py,
  cada una con su comentario) no son datos y no viven aca.
- adivinar la transcripcion de un agente que encontro el barrido (las `guess_*`, que antes vivian
  en sessions.py; sessions las reexporta con el mismo nombre)."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass

try:
    import tmux
    from state import HOME, claude_slug, parse_ts
except ImportError:  # importado como lienzo.agentes, sin lienzo/ en sys.path
    from . import tmux
    from .state import HOME, claude_slug, parse_ts

# --- registro de agentes ----------------------------------------------------------------------


@dataclass(frozen=True)
class Perfil:
    """Los datos de un agente. `retomar_por_id` son los argumentos que van ANTES del session_id
    (claude y codex retoman una sesion dada); `retomar_ultima`, los que retoman «la ultima de esta
    carpeta» sin id (pi y coda). `parser` es el NOMBRE de la funcion de transcripts.py, que se busca
    recien al parsear (guardar la funcion al importar dejaria afuera los monkeypatch), y
    `parser_args` dice cuales de max_bytes / leaf_id recibe despues de la ruta, en ese orden."""

    exe: str
    parser: str
    parser_args: tuple[str, ...]
    retomar_por_id: tuple[str, ...] = ()
    retomar_ultima: tuple[str, ...] = ()
    acepta_modelo: bool = False


AGENTES: dict[str, Perfil] = {
    "claude": Perfil(
        exe="claude.exe",
        parser="parse_claude",
        parser_args=("max_bytes",),
        retomar_por_id=("--resume",),
        acepta_modelo=True,
    ),
    "codex": Perfil(
        exe="codex.exe",
        parser="parse_codex",
        parser_args=("max_bytes",),
        retomar_por_id=("resume",),
        acepta_modelo=True,
    ),
    # Pi elige la rama activa con leaf_id; no recibe --model
    "pi": Perfil(exe="pi.exe", parser="parse_pi", parser_args=("max_bytes", "leaf_id"), retomar_ultima=("--resume",)),
    # CODA guarda todas las sesiones en una misma base: leaf_id es la sesion, y se lee por filas, no por bytes
    "coda": Perfil(
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
    """Codex mezcla todos los rollouts en un arbol por fecha, asi que hay que abrirlos: entre los
    de la TUI con el mismo cwd, gana el que arranco mas cerca del nacimiento del proceso. "El mas
    nuevo" se equivoca si despues de abrir la TUI corrio un `codex exec` en el mismo directorio."""
    nacio = t0 + BIRTH_MARGIN_S  # t0 ya viene con el margen restado
    best, best_gap = None, None
    for p in glob.glob(os.path.join(home, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl")):
        mtime = _mtime(p)
        if mtime is None or mtime < t0:
            continue
        try:
            with open(p, "rb") as f:
                first = json.loads(f.readline().decode("utf-8", errors="replace"))
        except OSError, ValueError:
            continue
        pl = first.get("payload") or {}
        if (pl.get("cwd") or "").lower() != cwd.lower():
            continue
        if pl.get("originator") not in (None, "codex-tui", "codex_cli_rs"):
            continue  # Codex Desktop (importados), codex_exec, app-server: no son la TUI
        birth = parse_ts(pl.get("timestamp") or first.get("timestamp"))
        gap = (birth.timestamp() if birth else mtime) - nacio
        if gap < -BIRTH_MARGIN_S:
            continue  # arranco antes que el proceso: no es suyo
        if best_gap is None or abs(gap) < abs(best_gap):
            best, best_gap = (pl.get("id") or pl.get("session_id"), p), gap
    return best or (None, None)


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
    if not cwd:
        return None, None
    born = parse_ts(created)
    if agent == "pi":
        return guess_pi(cwd, born.timestamp()) if born else (None, None)
    if agent == "coda":
        return None, None  # la identidad de CODA viene exacta del log (coda.identity), no se adivina
    t0 = born.timestamp() - BIRTH_MARGIN_S if born else 0
    return guess_claude(cwd, t0, home) if agent == "claude" else guess_codex(cwd, t0, home)
