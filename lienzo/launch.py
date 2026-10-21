"""Lanzar una sesion nueva en esta PC (plan multi-PC §3.7): escribe un .cmd que hace chcp, pone el
titulo, entra al cwd y llama al ejecutable del agente por ruta absoluta, y lo abre con
explorer.exe, que desacopla el entorno --el mismo truco del skill `lienzo`: un `claude` hijo
lanzado directo desde una sesion de Claude Code hereda CLAUDECODE y compania, se cree anidado y se
apaga solo sin decir nada--. Restringido a `launch_roots` (config.json) y a los cuatro agentes
conocidos; el titulo se sanea antes de escribirlo, nunca se interpreta como comando.

En Mac/Linux/WSL no hay .cmd ni explorer.exe: la sesion se abre adentro de tmux (`tmux new-session
-d`), porque fuera de tmux el lienzo la ve pero no le puede escribir (un PTY es de quien lo creo). El
mismo desacople del entorno lo hace `env -u` con las variables de Claude Code."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import uuid

import agent_improvements
import claude_pipe_runtime
import harness_updates
import state
import tmux
from agentes import AGENTES
from work_titles import project_title

WINDOWS = sys.platform == "win32"

_CLAUDE_PIPE_ERRORS = frozenset(
    {
        "el enlace Claude se está cerrando",
        "límite de enlaces Claude alcanzado; cerrá los enlaces sin uso",
        "no se pudo verificar el proceso de esta sesión Claude",
        "protocolo Claude desconocido o incompatible: se requiere peerProtocol entero 1",
        "versión Claude desconocida o inválida",
        "versión Claude anterior al mínimo Windows 2.1.234",
        "el proceso Claude cambió durante el registro",
        "el proceso de la sesión cambió: cerrá el enlace anterior",
        "bootstrap Claude finalizado sin conexión vigente; cerrá el enlace y registrá de nuevo",
    }
)


def claude_pipe_error(error: Exception) -> str:
    """Sólo motivos públicos controlados; nunca mensajes arbitrarios del SO o transporte."""
    if isinstance(error, ValueError) and str(error) in _CLAUDE_PIPE_ERRORS:
        return str(error)
    return f"no se pudo abrir el enlace local Claude ({type(error).__name__})"


# los ejecutables salen del registro de agentes (agentes.py); el nombre queda porque lo leen otros
AGENT_EXES = {nombre: p.exe for nombre, p in AGENTES.items()}
# las que hacen que un `claude` hijo se crea anidado y se apague solo (ver el docstring)
_CLAUDE_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT")

# en un .cmd, & < > ^ % reinterpretan la linea y " cierra la comilla del titulo.
# El separador | se conserva y _launch_cmd lo escapa como ^|; tmux recibe argumentos literales.
_UNSAFE_TITLE_RE = re.compile(r'[&<>^%"\r\n]')


def _resume_args(agent: str, resume: str | None) -> list[str]:
    """Argumentos para retomar, o [] si no se puede (sin pedido, o un id que no es de verdad para
    un agente que retoma por id). Cada elemento es seguro de escribir tal cual en el .cmd."""
    p = AGENTES.get(agent)
    return p.resume_args(resume) if p else []


# elegir el modelo al lanzar: los que el registro marca con acepta_modelo (coda, claude y codex) lo
# reciben con --model. El id entra en la linea del .cmd, asi que solo pasa [A-Za-z0-9._/:@-] (sin
# espacios ni nada que reinterprete el .cmd)
_MODEL_RE = re.compile(r"[A-Za-z0-9._/:@-]{1,80}")


def _model_args(agent: str, model: str | None) -> list[str]:
    """`--model <id>` si el agente lo soporta y el id es valido; [] si no."""
    p = AGENTES.get(agent)
    if isinstance(model, str) and p is not None and p.acepta_modelo and _MODEL_RE.fullmatch(model):
        return ["--model", model]
    return []


# el nombre corto entra en la linea del .cmd: solo [A-Za-z0-9._-], sin nada que la reinterprete
_NOMBRE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def nombre_corto(title: str) -> str:
    """El nombre para el canal nativo (ListAgents, SendMessage), sacado del titulo de la tarjeta:
    `chesstudia - encargo I - ...` da `chesstudia-I`, `chesstudia - coordinadora - ...` da
    `chesstudia-coordinadora`, y cualquier otro titulo, sus primeras palabras. Sin acentos."""
    import unicodedata

    plano = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    partes = [p.strip() for p in re.split(r"\s+(?:\||-)\s+", plano) if p.strip()]
    if len(partes) >= 2:
        rol = re.sub(r"^encargo\s+", "", partes[1], flags=re.IGNORECASE)
        base = f"{partes[0]}-{rol}"
    else:
        base = partes[0] if partes else ""
    return _NOMBRE_RE.sub("-", base).strip("-.")[:40].strip("-.")


def _nombre_args(agent: str, title: str) -> list[str]:
    """Los argumentos que nombran la sesion al lanzarla (`nombrar` del registro), o [] si el agente
    no se deja nombrar o el titulo no da nombre."""
    p = AGENTES.get(agent)
    nombre = nombre_corto(title)
    if p is None or not p.nombrar or not nombre:
        return []
    return [a.replace("{nombre}", nombre) for a in p.nombrar]


def _sanitize_title(title: str) -> str:
    limpio = _UNSAFE_TITLE_RE.sub(" ", (title or "").strip())
    return state.short(" ".join(limpio.split()), 120) or "lienzo"


def _allowed_roots() -> list[str]:
    """`launch_roots` de config.json, normalizadas para comparar con `cwd`. Vacia o ausente:
    ninguna (§3.7: "vacía = no se lanza nada"), no todas."""
    roots = state.load_config().get("launch_roots")
    if not isinstance(roots, list):
        return []
    return [os.path.normcase(os.path.normpath(r)) for r in roots if isinstance(r, str) and r.strip()]


# aparte para que los tests no tengan que crear cada carpeta que prueban
_existe = os.path.isdir


def _physical_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(path, strict=True))


def _cwd_allowed(cwd: str, roots: list[str]) -> bool:
    # % expande variables adentro del .cmd aunque vaya entre comillas, y " las cierra
    if not cwd or not roots or any(c in cwd for c in '"%\r\n') or not _existe(cwd):
        return False
    norm = os.path.normcase(os.path.normpath(cwd))
    try:
        physical = _physical_path(cwd)
        for root in roots:
            if norm != root and not norm.startswith(root.rstrip(os.sep) + os.sep):
                continue
            physical_root = _physical_path(root)
            if os.path.commonpath((physical, physical_root)) == physical_root:
                return True
    except OSError, ValueError:
        return False
    return False


def _exe_path(exe_name: str) -> str | None:
    """Por ruta absoluta, porque el PATH no se hereda entero por explorer.exe: primero donde lo deja
    el instalador de Claude Code (~/.local/bin), despues el PATH de este server."""
    propio = os.path.join(state.HOME, ".local", "bin", exe_name)
    candidatos: list[str] = []
    if exe_name == "agy.exe":
        local = os.environ.get("LOCALAPPDATA", os.path.join(state.HOME, "AppData", "Local"))
        candidatos.append(os.path.join(local, "agy", "bin", exe_name))
    if exe_name == "codex.exe":
        # El instalador standalone mantiene esta entrada. Una copia vieja en .local/bin
        # no reconoce su instalación y seguiría lanzando una versión sin actualizar.
        local = os.environ.get("LOCALAPPDATA", os.path.join(state.HOME, "AppData", "Local"))
        candidatos.append(os.path.join(local, "Programs", "OpenAI", "Codex", "bin", exe_name))
    if exe_name == "kiro-cli.exe":
        # el instalador lo deja por usuario o, con admin, en Program Files (ar-it33940, 2026-10-09)
        for base in (
            os.environ.get("LOCALAPPDATA", os.path.join(state.HOME, "AppData", "Local")),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
        ):
            candidatos.append(os.path.join(base, "Kiro-Cli", exe_name))
    if exe_name == "pi.exe":
        # el instalador oficial de pi.dev en Windows no trae .exe: la entrada es un .cmd
        candidatos.append(os.path.join(state.HOME, ".pi", "agent", "bin", "pi.cmd"))
    for c in candidatos:
        if os.path.isfile(c):
            return c
    if os.path.isfile(propio):
        return propio
    encontrado = shutil.which(exe_name)
    if encontrado is None and exe_name.endswith(".exe"):
        encontrado = shutil.which(exe_name.removesuffix(".exe") + ".cmd")  # npm deja un .cmd
    return encontrado


def _cuota_coda() -> str | None:
    try:
        import health

        return health.coda_cuota(esperar=True)
    except Exception:  # no poder medir no frena un lanzamiento
        return None


def harness_executable(agent: str) -> str | None:
    name = AGENT_EXES[agent]
    return _exe_path(name if WINDOWS else name.removesuffix(".exe"))


def open_vscode(cwd: str) -> dict:
    """Abre una carpeta permitida sin interpretar su ruta como un comando."""
    if not _cwd_allowed(cwd, _allowed_roots()):
        return {"ok": False, "error": "cwd fuera de launch_roots"}
    candidates = [shutil.which("Code.exe" if WINDOWS else "code")]
    if WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        system = os.environ.get("ProgramFiles")
        if local:
            candidates.append(os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"))
        if system:
            candidates.append(os.path.join(system, "Microsoft VS Code", "Code.exe"))
    executable = next((p for p in candidates if p and os.path.isfile(p)), None)
    if executable is None:
        return {"ok": False, "error": "No encuentro VS Code en esta PC"}
    try:
        subprocess.Popen([executable, "--new-window", cwd])
    except OSError as exc:
        return {"ok": False, "error": f"No se pudo abrir VS Code: {exc}"}
    return {"ok": True}


def launch(
    cwd: str,
    title: str,
    agent: str,
    resume: str | None = None,
    model: str | None = None,
    distro: str | None = None,
    modo: str = "general",
    claude_pipe: bool = False,
    chrome: bool = False,
) -> dict:
    """Escribe el .cmd en `<LIENZO_HOME>/launch/` y lo lanza con explorer.exe. Rechaza (sin tocar
    disco ni proceso) un `cwd` fuera de `launch_roots` y un `agent` desconocido. Devuelve
    `{ok, cmd_path}`; buscar la tarjeta nueva lo hace despues el server (rescan de por medio).
    Con `resume` (el session_id a retomar) agrega el retomar del agente; si el id no es valido para
    un agente que retoma por id (p. ej. `pid-123`) lanza sin retomar y lo dice: `resumed: false`.
    Con `distro` (Windows con WSL) la sesion nace adentro de tmux de esa distro: spawn por
    wsl.exe -d <distro> con el cwd traducido a /mnt/<letra>, y la tarjeta queda direccionada a esa
    distro desde el nacimiento. Con `chrome` (sólo Claude en Windows nativo) la sesión nace con
    `--chrome`: maneja el Chrome real del usuario por la extensión, así que va a pedido, nunca por defecto.
    Sin pedido, el comportamiento de siempre."""
    exe_name = AGENT_EXES.get(agent)
    if exe_name is None:
        return {"ok": False, "error": f"agente desconocido: {agent!r}"}
    if ("win32" if WINDOWS else sys.platform) not in AGENTES[agent].supported_platforms:
        return {"ok": False, "error": f"integracion de {agent} no soportada en esta plataforma"}
    if chrome and (agent != "claude" or distro):
        # la extensión habla con el host nativo de Windows: desde WSL no la alcanza
        return {"ok": False, "error": "chrome requiere una sesión Claude en Windows nativo"}
    if agent == "antigravity" and distro:
        return {"ok": False, "error": "Antigravity está integrado sólo en Windows; WSL todavía no está soportado"}
    if agent == "coda" and _cuota_coda() == "agotada":
        # abriria una terminal que falla en el primer turno (medido el 2026-10-04)
        return {
            "ok": False,
            "code": 409,
            "error": "coda no tiene cuota en esta PC («Quota exceeded»): lanzá en otra PC u otro agente",
        }
    if not _cwd_allowed(cwd, _allowed_roots()):
        return {"ok": False, "error": "cwd fuera de launch_roots"}
    if not WINDOWS or distro:
        exe_name = exe_name.removesuffix(".exe")
    if distro and WINDOWS:
        # adentro de WSL corre el binario de Linux de esa distro, no el .exe de Windows (revision 2026-10-10:
        # se le pasaba la ruta de Windows y la sesion no arrancaba); se busca en el PATH de la distro
        exe_path = exe_name if tmux.en_distro(distro, exe_name) else None
        if exe_path is None:
            return {"ok": False, "error": f"no encuentro {exe_name} en la distro {distro}"}
    else:
        exe_path = _exe_path(exe_name)
    if exe_path is None:
        return {"ok": False, "error": f"no encuentro {exe_name} en esta PC"}
    update_error = harness_updates.before_launch(agent, exe_path, distro)
    # Los instaladores pueden cambiar la ruta; volver a resolver después de actualizar.
    if not (distro and WINDOWS):
        exe_path = _exe_path(exe_name)
        if exe_path is None:
            return {"ok": False, "error": f"no encuentro {exe_name} después de comprobar actualizaciones"}
    resume_args = _resume_args(agent, resume)
    model_args = _model_args(agent, model)
    nombre_args = _nombre_args(agent, title)
    extra = [*AGENTES[agent].iniciar, *resume_args, *model_args, *nombre_args, *(["--chrome"] if chrome else [])]
    improvement_warnings = []
    try:
        instructions, improvement_warnings = agent_improvements.launch_instructions(agent, distro, modo)
        if instructions:
            extra += _improvement_args(agent, instructions, cwd, distro=distro)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        improvement_warnings.append(f"mejoras no aplicadas: {error}")
    if agent == "codex":
        # Solo esta invocación: Lienzo es dueño del título proyecto | tarea.
        # null no es TOML válido para -c; el array vacío se verificó en Codex 0.162.1.
        extra += ["-c", "tui.terminal_title=[]", "-c", "tui.notifications=false"]
    pipe_sid = None
    if claude_pipe:
        if agent != "claude" or not WINDOWS or distro or resume:
            return {"ok": False, "error": "claude_pipe requiere una sesión Claude nueva en Windows nativo"}
        pipe_sid = str(uuid.uuid4())
        try:
            prepared = claude_pipe_runtime.prepare_launch(pipe_sid)
        except (ValueError, OSError, RuntimeError) as error:
            return {"ok": False, "code": 409, "error": claude_pipe_error(error)}
        launch_dir = os.path.join(state.LIENZO, "launch")
        settings = os.path.join(launch_dir, f"{pipe_sid}.claude-settings.json")
        try:
            os.makedirs(launch_dir, exist_ok=True)
            with open(settings, "w", encoding="utf-8") as stream:
                json.dump(prepared["hook_settings"], stream)  # sólo comando público; nunca environment()
        except OSError:
            claude_pipe_runtime.close(pipe_sid)
            raise
        extra += ["--session-id", pipe_sid, "--settings", settings]
    if distro and WINDOWS:
        # WSL: el cwd de Windows no existe adentro de la distro; se traduce a /mnt/<letra> (§WSL)
        cwd_linux = tmux.ruta_wsl(cwd)
        res = _launch_tmux(cwd_linux, title, exe_path, extra, distro=distro)
    else:
        try:
            res = _launch_cmd(cwd, title, exe_path, extra) if WINDOWS else _launch_tmux(cwd, title, exe_path, extra)
        except Exception:
            if pipe_sid:
                claude_pipe_runtime.close(pipe_sid)
            raise
    if pipe_sid:
        if res.get("ok"):
            res["session_id"] = pipe_sid
            res["claude_pipe"] = "esperando adaptador; entrega aún no habilitada"
        else:
            claude_pipe_runtime.close(pipe_sid)
    if distro and res.get("ok"):
        res["distro"] = distro
    if nombre_args and res.get("ok"):
        res["native_name"] = nombre_corto(title)
    if resume is not None:
        res["resumed"] = bool(resume_args)
    if model is not None:
        res["model_applied"] = bool(model_args)
    if agent == "coda" and model_args and res.get("ok"):
        # medido el 2026-10-02: coda escribe el --model en su config.json, asi que las codas que se
        # lancen despues sin modelo corren este (PENDIENTES, «--model en coda»)
        res["aviso"] = "coda guarda --model como modelo por defecto de esta PC: las proximas codas sin modelo usan este"
    if update_error or improvement_warnings:
        res["aviso"] = "; ".join(filter(None, [res.get("aviso"), update_error, *improvement_warnings]))
    return res


def _codex_config_paths(cwd: str, distro: str | None) -> list:
    from pathlib import Path, PurePosixPath

    if distro and WINDOWS:
        env = subprocess.run(
            ["wsl.exe", "-d", distro, "--exec", "sh", "-c", 'printf "%s\\n" "${CODEX_HOME:-$HOME/.codex}"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
        home = env.stdout.strip()
        if env.returncode or not home.startswith("/") or "\n" in home:
            raise ValueError("no se pudo resolver la configuracion Codex de WSL; no se reemplazo")
        unc = Path("//wsl.localhost") / distro
        project = PurePosixPath(tmux.ruta_wsl(cwd))
        global_config = unc / home.lstrip("/") / "config.toml"
        if not (unc / home.lstrip("/")).is_dir():
            raise ValueError("no se puede leer la configuracion Codex de WSL; no se reemplazo")
        projects = [unc / str(p).lstrip("/") / ".codex" / "config.toml" for p in [*reversed(project.parents), project]]
        return [global_config, *projects]
    project = Path(cwd)
    global_config = Path(os.environ.get("CODEX_HOME", str(Path(state.HOME) / ".codex"))) / "config.toml"
    return [global_config, *[p / ".codex" / "config.toml" for p in [*reversed(project.parents), project]]]


def _improvement_args(agent: str, instructions: str, cwd: str, *, distro: str | None = None) -> list[str]:
    if agent == "codex":
        import tomllib

        # No sustituir developer_instructions del usuario/proyecto con las nuestras.
        existing = ""
        for path in _codex_config_paths(cwd, distro):
            if path.is_file():
                config = tomllib.loads(path.read_text(encoding="utf-8"))
                if "developer_instructions" in config:
                    if not isinstance(config["developer_instructions"], str):
                        raise ValueError("developer_instructions no es texto")
                    existing = config["developer_instructions"]
        value = " ".join(filter(None, [existing, instructions]))
        # -c admite texto literal si no es TOML; no reemplaza el prompt base del modelo.
        args = ["-c", "developer_instructions=" + value]
    else:
        args = ["--append-system-prompt", instructions]
    if WINDOWS and not distro:
        for value in args:
            _cmd_arg(value)
        if sum(len(value) for value in args) > 6000:
            raise ValueError("instrucciones demasiado largas para cmd; no se reemplazaron")
    return args


def _cmd_arg(value: str) -> str:
    if any(c in value for c in '&|<>^%!"\r\n'):
        raise ValueError("argumento de lanzamiento inseguro para cmd")
    try:
        value.encode("cp1252")
    except UnicodeError:
        raise ValueError("argumento no representable en la consola cp1252; no se modifico") from None
    return f'"{value}"' if any(c.isspace() for c in value) else value


def _launch_cmd(cwd: str, title: str, exe_path: str, extra: list[str]) -> dict:
    """Windows: un .cmd en `<LIENZO_HOME>/launch/` que explorer.exe abre en una consola nueva."""
    launch_dir = os.path.join(state.LIENZO, "launch")
    os.makedirs(launch_dir, exist_ok=True)
    cmd_path = os.path.join(launch_dir, f"{secrets.token_hex(6)}.cmd")
    title = _sanitize_title(project_title({"repo": state.repo_of(cwd), "title": title})).replace("|", "^|")
    cuerpo = (
        "@echo off\r\n"
        "chcp 1252 >nul\r\n"
        f"title {title}\r\n"
        f'cd /d "{cwd}"\r\n'
        f'"{exe_path}"{"".join(" " + _cmd_arg(a) for a in extra)}\r\n'
    )
    with open(cmd_path, "w", encoding="cp1252", errors="replace", newline="") as f:
        f.write(cuerpo)
    subprocess.Popen(["explorer.exe", cmd_path])
    return {"ok": True, "cmd_path": cmd_path}


def _launch_tmux(
    cwd: str, title: str, exe_path: str, extra: list[str] | None = None, distro: str | None = None
) -> dict:
    """Mac/Linux/WSL: una sesion de tmux nueva y suelta (-d) con el agente adentro, en `cwd`, con el
    titulo como nombre de ventana. Va como lista de argumentos, sin shell: ni el titulo ni el cwd se
    interpretan. El barrido la encuentra despues por el pane, como a cualquier agente en tmux.
    Con `distro` (Windows con WSL) el spawn va por `wsl.exe -d <distro>`: nace en el tmux de esa
    distro, y el barrido la etiqueta con ella (la tarjeta la trae del barrido, no de aca)."""
    nombre = f"lienzo-{secrets.token_hex(3)}"
    unset = [a for v in _CLAUDE_ENV for a in ("-u", v)]
    title = _sanitize_title(project_title({"repo": state.repo_of(cwd), "title": title}))
    argv = ["tmux", "new-session", "-d", "-s", nombre, "-n", title, "-c", cwd]
    argv += ["env", *unset, exe_path, *(extra or [])]
    if distro:
        argv = ["wsl.exe", "-d", distro, *argv]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "error": f"no se pudo abrir tmux: {e}"}
    return {"ok": True, "tmux_session": nombre}
