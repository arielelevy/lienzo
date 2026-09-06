"""Estado compartido del lienzo-server y utilidades sin logica de negocio: rutas, constantes, el
lock, el registro de sesiones en memoria, los pendientes, los clientes SSE, las listas persistidas
(links y reglas) y ~/.lienzo/config.json. Lo importan sessions.py, rules.py y server.py; no importa
a ninguno de ellos."""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LIENZO = os.path.join(HOME, ".lienzo")
EVENTS = os.path.join(LIENZO, "events")
PENDING = os.path.join(LIENZO, "pending")
ANSWERS = os.path.join(LIENZO, "answers")
ADJUNTOS = os.path.join(LIENZO, "adjuntos")
SESSIONS = os.path.join(LIENZO, "sessions")
LOG = os.path.join(LIENZO, "lienzo.log")
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "web", "dist")                 # salida de `npm run build` (Vite + React)
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
        ".woff2": "font/woff2", ".map": "application/json"}
PYTHON = sys.executable

NEEDS_NOTIFICATIONS = {"permission_prompt", "idle_prompt", "agent_needs_input",
                       "elicitation_dialog", "elicitation_url_dialog"}
DEAD_GRACE_S = 60
STALE_SESSION_H = 24          # al arrancar: tarjetas sin proceso y sin eventos hace mas de esto se purgan
ATTACH_MAX_DAYS = 30
LONG_TEXT = 500
STATES = ("corriendo", "te_necesita", "termino", "muerta")

LINKS_FILE = os.path.join(LIENZO, "links.json")
RULES_FILE = os.path.join(LIENZO, "rules.json")
CONFIG_FILE = os.path.join(LIENZO, "config.json")
UI_CONFIG_KEYS = ("auto_continue",)      # lo unico que la UI puede leer y escribir por /config

lock = threading.RLock()
sessions: dict[str, dict] = {}
pending: dict[str, dict] = {}
clients: list[queue.Queue] = []
transcript_stat: dict[str, tuple] = {}


# --- utilidades ----------------------------------------------------------------

def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


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
        d = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


# --- listas persistidas: vinculos y reglas -----------------------------------------------

class JsonList:
    """Lista persistida en un JSON y publicada por SSE: vinculos (reenvios hechos) y reglas
    (conexiones pendientes). Todo pasa por aca: agregar, filtrar, guardar, avisar."""

    def __init__(self, path: str, event: str):
        self.path = path
        self.event = event
        self.items: list[dict] = []

    def load(self, keep) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.items = [x for x in json.load(f) if keep(x)]
        except (OSError, ValueError):
            self.items = []

    def save(self) -> None:
        try:
            atomic_write(self.path, json.dumps(self.items, ensure_ascii=False, indent=1))
        except OSError:
            pass

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


links = JsonList(LINKS_FILE, "links")   # {id, from, to, ts, text, kind}
rules = JsonList(RULES_FILE, "rules")   # {id, kind: on_stop|at, from, to, text, at, repeat, max_fires, fired, enabled}


# --- config.json ---------------------------------------------------------------------------

def load_config() -> dict:
    """~/.lienzo/config.json (lo comparte con hook.py): ejemplos, wait, auto_continue."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def public_config() -> dict:
    cfg = load_config()
    return {k: bool(cfg.get(k)) for k in UI_CONFIG_KEYS}


def set_config_key(key: str, value: bool) -> None:
    """Escribe una sola clave y deja el resto del archivo como estaba (hook.py lee ejemplos y wait)."""
    with lock:
        cfg = load_config()
        cfg[key] = value
        atomic_write(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=1))
