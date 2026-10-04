"""Estado compartido del lienzo-server y utilidades sin logica de negocio: rutas, constantes, el
lock, el registro de sesiones en memoria, los pendientes, los clientes SSE, las listas persistidas
(links y reglas) y ~/.lienzo/config.json. Lo importan sessions.py, rules.py y server.py; no importa
a ninguno de ellos."""

from __future__ import annotations

import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
# LIENZO_HOME (plan multi-PC §F0): dos instancias en la misma PC, con puertos y carpeta de estado
# distintos, simulan dos PCs. Sin la variable, la carpeta de siempre.
LIENZO = os.environ.get("LIENZO_HOME") or os.path.join(HOME, ".lienzo")
EVENTS = os.path.join(LIENZO, "events")
PENDING = os.path.join(LIENZO, "pending")
ANSWERS = os.path.join(LIENZO, "answers")
ADJUNTOS = os.path.join(LIENZO, "adjuntos")
SESSIONS = os.path.join(LIENZO, "sessions")
LOG = os.path.join(LIENZO, "lienzo.log")
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "web", "dist")  # salida de `npm run build` (Vite + React)
# los documentos que muestra /docs, por nombre: solo estos, leidos del repo en cada pedido para
# que la referencia nunca quede atras del archivo. Sus imagenes viven en docs/img
DOCS = {n: os.path.join(ROOT, n) for n in ("README.md", "DISENO.es.md")}
DOCS_IMG = os.path.join(ROOT, "docs", "img")
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".map": "application/json",
}
PYTHON = sys.executable

NEEDS_NOTIFICATIONS = {
    "permission_prompt",
    "idle_prompt",
    "agent_needs_input",
    "elicitation_dialog",
    "elicitation_url_dialog",
}
DEAD_GRACE_S = 60
STALE_SESSION_H = 24  # al arrancar: tarjetas sin proceso y sin eventos hace mas de esto se purgan
ATTACH_MAX_DAYS = 30
LONG_TEXT = 500
STATES = ("corriendo", "te_necesita", "termino", "muerta")

LINKS_FILE = os.path.join(LIENZO, "links.json")
RULES_FILE = os.path.join(LIENZO, "rules.json")
CONFIG_FILE = os.path.join(LIENZO, "config.json")
UI_CONFIG_KEYS = ("auto_continue", "auto_retry", "auto_aprobar")  # lo unico que la UI puede leer y escribir por /config

# Regla del lock (RLock, reentrante). Toda escritura sobre `sessions`, sobre `pending` o sobre el
# dict de una tarjeta va con el lock tomado. Lo lento queda AFUERA y se aplica despues: el subproceso
# de la pantalla (medido: 183 ms por sesion), el de send.py (hasta 60 s) y el parseo de la
# transcripcion (22 ms de mediana, 48 ms el peor caso sobre 2 MB de cola). Al volver a tomarlo hay
# que revalidar que la tarjeta siga siendo la misma (`sessions.get(sid) is s`): entre medio pudo
# borrarse, y un touch() sobre una tarjeta ya borrada le rehacia el archivo en disco.
lock = threading.RLock()
sessions: dict[str, dict] = {}
pending: dict[str, dict] = {}
clients: list[queue.Queue] = []
transcript_stat: dict[str, tuple] = {}


# --- utilidades ----------------------------------------------------------------


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


# --- log --------------------------------------------------------------------------------
# Una linea por hecho: `HH:MM:SS  etiqueta  mensaje`. La etiqueta sale del propio mensaje (no hay
# que pasarla en cada llamada), los ids de sesion se muestran como `repo/1a2b3c4d`, y un traceback
# va entero al archivo pero en consola queda en una linea con la excepcion. El archivo lleva la
# fecha completa para poder grep-ear por dia; la consola solo la hora, con una linea separadora
# cuando cambia el dia. Colores solo si stdout es una terminal.
_TAGS = (
    ("Traceback", "error"),
    ("lienzo-server", "server"),
    ("send ", "envio"),
    ("regla", "regla"),
    ("tunel", "tunel"),
    ("cloudflared", "tunel"),
    ("permiso", "permiso"),
    ("pending", "permiso"),
    ("evento", "evento"),
    ("barrido", "barrido"),
    ("purgad", "limpieza"),
    ("tarjeta", "sesion"),
    ("titulo", "sesion"),
    ("config", "config"),
    ("login", "acceso"),
    ("bloqueado", "acceso"),
)
_COLORS = {
    "error": "\x1b[31m",
    "envio": "\x1b[36m",
    "regla": "\x1b[35m",
    "server": "\x1b[32m",
    "sesion": "\x1b[34m",
    "permiso": "\x1b[33m",
    "tunel": "\x1b[32m",
}
_SID_RE = re.compile(r"(?<![0-9a-f/])([0-9a-f]{8})(?![0-9a-f])")
_last_day = [""]
_tty = [None]


def _tag(msg: str) -> str:
    if _SID_RE.match(msg) and msg[8:9] == ":":
        return "sesion"
    low = msg.lower()
    for needle, tag in _TAGS:
        if needle.lower() in low:
            return tag
    return "info"


def _with_names(msg: str) -> str:
    """`5c8f1c91` -> `lienzo/5c8f1c91` cuando ese prefijo es una sesion conocida."""

    def sub(m: re.Match) -> str:
        sid = m.group(1)
        for full, s in list(sessions.items()):
            if full.startswith(sid):
                return f"{s.get('repo') or '?'}/{sid}"
        return sid

    return _SID_RE.sub(sub, msg)


def log(msg: str) -> None:
    t = dt.datetime.now().astimezone()
    msg = _with_names(str(msg).rstrip())
    tag = _tag(msg)
    is_tb = msg.lstrip().startswith("Traceback") or "\nTraceback" in msg
    # archivo: fecha completa, mensaje entero (con el traceback si lo hay)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{t.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}  {tag:<8} {msg}\n")
    except OSError:
        pass
    # consola: hora corta, separador de dia, traceback resumido a su ultima linea
    if _tty[0] is None:
        _tty[0] = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if is_tb:
        lines = [l for l in msg.splitlines() if l.strip()]
        head = next((l for l in lines if not l.startswith("Traceback") and not l.startswith(" ")), "")
        msg = (
            f"{lines[-1].strip()}"
            + (f"  ({head.strip()})" if head and head.strip() != lines[-1].strip() else "")
            + "  · detalle en lienzo.log"
        )
    day = t.strftime("%Y-%m-%d")
    if day != _last_day[0]:
        _last_day[0] = day
        print(f"── {day} ──", flush=True)
    if _tty[0]:
        c = _COLORS.get(tag, "\x1b[90m")
        print(f"\x1b[90m{t.strftime('%H:%M:%S')}\x1b[0m  {c}{tag:<8}\x1b[0m {msg}", flush=True)
    else:
        print(f"{t.strftime('%H:%M:%S')}  {tag:<8} {msg}", flush=True)


_avisos: dict[str, str] = {}
_avisos_lock = threading.Lock()


def avisar_si_cambia(clave: str, msg: str | None) -> None:
    """Loguea `msg` solo si es distinto del ultimo aviso de `clave`; `None` dice que se arreglo (y lo
    loguea una vez, si habia algo). Para los bucles de fondo que fallan igual en cada vuelta (cada
    0,5 s el de pendientes, cada 2 s la liveness): antes o se tragaban el error o inundaban el log.
    Es la idea de FuenteTemperatura._avisar de health.py, para cualquier clave. Lock propio y no
    `lock`: se llama desde adentro y desde afuera del lock de las tarjetas."""
    with _avisos_lock:
        prev = _avisos.get(clave)
        if msg == prev:
            return
        if msg is None:
            _avisos.pop(clave, None)
        else:
            _avisos[clave] = msg
    log(msg if msg is not None else f"{clave}: se normalizo")


def is_disconnect(e: BaseException) -> bool:
    """El navegador cerro la conexion (cambio de pestaña, recarga, SSE que se corta): no es un
    error nuestro y no merece traceback. WinError 10053/10054 son las variantes de Windows."""
    if isinstance(e, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
        return True
    return isinstance(e, OSError) and getattr(e, "winerror", None) in (10053, 10054)


def atomic_write(path: str, text: str) -> None:
    """Escritura atomica. El .tmp lleva el id del hilo: dos hilos que guardan la misma tarjeta a la
    vez (consume_events bajo lock, liveness/screen_loop sin lock) chocaban en el mismo .tmp y
    os.replace fallaba con WinError 32 (medido 2026-09-05 16:30). Y si Windows todavia tiene el
    destino abierto por otro lector (antivirus, el otro hilo), se reintenta un poco."""
    tmp = f"{path}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for i in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 4:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (i + 1))


def short(s, n=300) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def broadcast(ev: dict) -> None:
    data = json.dumps(ev, ensure_ascii=False)
    with lock:
        dead = []
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            clients.remove(q)


def claude_slug(cwd: str) -> str:
    return cwd.replace(":", "-").replace("\\", "-").replace("/", "-")


def repo_of(cwd: str | None) -> str:
    return os.path.basename((cwd or "").rstrip("\\/")) or "?"


def parse_ts(raw) -> dt.datetime | None:
    """ISO a datetime con zona: los hooks mandan hora local con offset, la transcripcion UTC con Z;
    lo que venga sin zona se asume UTC (la transcripcion). None si no parsea."""
    if not raw:
        return None
    try:
        d = dt.datetime.fromisoformat(str(raw))  # fromisoformat ya entiende la Z final
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


# --- JSON en disco ------------------------------------------------------------------------


def apartar_corrupto(path: str, motivo) -> None:
    """Renombra un JSON que no se pudo parsear a `<archivo>.corrupto-<ts>` y lo dice en el log.
    Antes se tomaba como vacio en silencio y el primer guardado lo pisaba: se perdian las reglas
    o la config sin rastro (plan de refactor 0.8, E3). Apartado, el contenido sigue en disco para
    rescatarlo a mano, y el que lo usa arranca vacio."""
    nombre = os.path.basename(path)
    dest = f"{path}.corrupto-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, dest)
    except FileNotFoundError:
        return  # otro hilo ya lo aparto
    except OSError as e:
        log(f"{nombre} corrupto ({motivo}) y no se pudo apartar: {e}")
        return
    log(f"{nombre} corrupto ({motivo}): apartado como {os.path.basename(dest)}; se arranca vacio")


def leer_json(path: str) -> tuple[object, str | None]:
    """(dato, error). Si no existe: (None, None), vacio y sin log. Si no parsea: lo aparta
    (apartar_corrupto) y devuelve (None, "corrupto"). Si existe y no se pudo abrir (bloqueado, sin
    permiso): (None, "ilegible"), sin log (lo loguea quien llama, que sabe cada cuanto lee): quien
    lo use no debe escribir encima."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, None
    except ValueError as e:  # JSONDecodeError y UnicodeDecodeError
        apartar_corrupto(path, e)
        return None, "corrupto"
    except OSError:
        return None, "ilegible"


# --- listas persistidas: vinculos y reglas -----------------------------------------------


class JsonList:
    """Lista persistida en un JSON y publicada por SSE: vinculos (reenvios hechos) y reglas
    (conexiones pendientes). Todo pasa por aca: agregar, filtrar, guardar, avisar."""

    def __init__(self, path: str, event: str):
        self.path = path
        self.event = event
        self.items: list[dict] = []
        # el archivo existe pero no se pudo leer (bloqueado, sin permiso): guardar la lista vacia
        # que quedo en memoria lo pisaria. Mientras siga asi, save() no escribe
        self.no_pisar = False

    def load(self, keep) -> None:
        datos, err = leer_json(self.path)
        if err is None and datos is not None and not isinstance(datos, list):
            apartar_corrupto(self.path, "no es una lista")
        self.no_pisar = err == "ilegible"
        if self.no_pisar:
            log(f"{os.path.basename(self.path)} existe y no se pudo leer: se arranca vacio y no se guarda encima")
        self.items = [x for x in datos if keep(x)] if isinstance(datos, list) else []

    def save(self) -> None:
        if self.no_pisar:
            avisar_si_cambia(
                f"guardar {self.path}",
                f"no se guarda {os.path.basename(self.path)}: no se pudo leer al arrancar y se pisaria con lo que hay en memoria",
            )
            return
        try:
            atomic_write(self.path, json.dumps(self.items, ensure_ascii=False, indent=1))
        except OSError as e:
            # antes se tragaba: si rules.json o links.json no se podian escribir (disco lleno, archivo
            # bloqueado), las reglas seguian en memoria y se perdian en el proximo arranque sin aviso
            log(f"no se pudo guardar {os.path.basename(self.path)}: {e}")

    def snapshot(self) -> list[dict]:
        with lock:
            return list(self.items)

    def publish(self) -> None:
        broadcast({"type": self.event, self.event: self.snapshot()})

    def add(self, item: dict, cap: int = 200) -> None:
        with lock:
            self.items.append(item)
            del self.items[:-cap]
            self.save()
        self.publish()

    def remove(self, pred) -> None:
        with lock:
            n = len(self.items)
            self.items[:] = [x for x in self.items if not pred(x)]
            changed = n != len(self.items)
            if changed:
                self.save()
        if changed:
            self.publish()


links = JsonList(LINKS_FILE, "links")  # {id, from, to, ts, text, kind}
rules = JsonList(RULES_FILE, "rules")  # {id, kind: on_stop|at, from, to, text, at, repeat, max_fires, fired, enabled}


# --- config.json ---------------------------------------------------------------------------


def _leer_config() -> tuple[dict, str | None]:
    """(config, error): error None si se leyo (o no existe: vacia), "corrupto" si no era un objeto
    JSON (ya quedo apartado), "ilegible" si existe y no se pudo abrir."""
    d, err = leer_json(CONFIG_FILE)
    if err is None and d is not None and not isinstance(d, dict):
        apartar_corrupto(CONFIG_FILE, "no es un objeto")
        err = "corrupto"
    # se lee cada 2 s (auto-aprobar): el «no se pudo abrir» se loguea cuando cambia, no en cada vuelta
    avisar_si_cambia("config.json", "config.json no se pudo abrir: se toma vacia" if err == "ilegible" else None)
    return (d if err is None and isinstance(d, dict) else {}), err


def load_config() -> dict:
    """~/.lienzo/config.json (lo comparte con hook.py): ejemplos, wait, auto_continue, auto_retry.
    Si no existe, vacia. Si esta corrupta, se aparta como config.json.corrupto-<ts> (con log) y se
    toma vacia (plan de refactor 0.8, E3)."""
    return _leer_config()[0]


def public_config() -> dict:
    cfg = load_config()
    return {k: bool(cfg.get(k)) for k in UI_CONFIG_KEYS}


def set_config_key(key: str, value: bool) -> bool:
    """Escribe una sola clave y deja el resto del archivo como estaba (hook.py lee ejemplos y wait).
    Si la lectura fallo (corrupta o ilegible) NO escribe: un archivo nuevo con una sola clave
    tiraba el resto (ejemplos, wait, launch_roots) sin aviso. Devuelve si escribio; la corrupta ya
    quedo apartada, asi que el proximo intento arranca un archivo nuevo."""
    with lock:
        cfg, err = _leer_config()
        if err is not None:
            log(f"config: no se escribe {key}={value}: config.json {err} al leerla")
            return False
        cfg[key] = value
        atomic_write(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=1))
        return True
