"""Identidad de esta PC y de un repo (plan multi-PC §3.1, §3.6): `pc_id()` y `pc_info()` leen o
crean `<LIENZO_HOME>/peer.json`; `repo_key()` normaliza el remote `origin` de un repo sin llamar a
`git` por subprocess, para que el mismo repo clonado en dos PCs (o con dos carpetas locales
distintas) tenga la misma clave y comparta coordinadora."""

from __future__ import annotations

import configparser
import json
import os
import re
import secrets
import socket
import threading
from urllib.parse import urlparse

import state

# paleta fija (plan §3.1: "un hex de una paleta fija elegido por pc_id"); el indice sale del
# propio pc_id asi que dos PCs con el mismo id (imposible en la practica) quedarian con el mismo
# color, y no hace falta guardar un contador aparte
PALETTE = (
    "#4C6EF5",  # azul
    "#12B886",  # verde
    "#F59F00",  # ambar
    "#E64980",  # rosa
    "#7048E8",  # violeta
    "#15AABF",  # cian
    "#FA5252",  # rojo
    "#82C91E",  # lima
)

_PC_ID_RE = re.compile(r"[0-9a-f]{12}")
_lock = threading.RLock()


def _peer_path() -> str:
    return os.path.join(state.LIENZO, "peer.json")


def _color_for(pc_id_: str) -> str:
    return PALETTE[int(pc_id_, 16) % len(PALETTE)]


# pc_id() se pide en cada sesion nueva, link, regla y tick del beacon, y peer.json casi nunca
# cambia: se cachea por ruta, mtime y tamano; una escritura (set_name, _ensure_peer) lo invalida
_peer_cache: tuple[str, tuple[int, int], dict] | None = None


def _apartar_corrupto(path: str, motivo: str) -> None:
    """peer.json ilegible: se renombra a `peer.json.corrupto-<ts>` y se avisa, en vez de pisarlo
    en silencio con una identidad nueva (revision 2026-10-04, B15: perder el pc_id rompe todos los
    emparejamientos y no quedaba ni el archivo para recuperarlo a mano). Mismo criterio que
    federation.apartar_corrupto; no se importa de ahi para no cargar http.client aca."""
    import time

    destino = f"{path}.corrupto-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, destino)
    except OSError as e:
        state.log(f"peer.json corrupto ({motivo}) y no lo pude apartar ({e}): se va a reescribir")
        return
    state.log(f"peer.json corrupto ({motivo}): lo aparte en {destino}; esta PC arranca con un pc_id nuevo")


def _load_peer() -> dict | None:
    """El contenido de peer.json, o None si no existe o estaba corrupto (y ya se aparto). Si
    existe y no se puede leer (antivirus, permisos), NO devuelve None: eso haria crear un pc_id
    nuevo encima de uno bueno. Usa la ultima lectura buena si la hay; si no, el error sube."""
    global _peer_cache
    path = _peer_path()
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as e:
        return _ultima_buena_o_error(path, e)
    firma = (st.st_mtime_ns, st.st_size)
    if _peer_cache is not None and _peer_cache[0] == path and _peer_cache[1] == firma:
        return dict(_peer_cache[2])
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return None
    except OSError as e:
        return _ultima_buena_o_error(path, e)
    except ValueError as e:  # incluye UnicodeDecodeError
        _apartar_corrupto(path, f"JSON invalido: {e}")
        return None
    if not isinstance(d, dict) or not _PC_ID_RE.fullmatch(str(d.get("pc_id") or "")):
        _apartar_corrupto(path, "sin un pc_id valido")
        return None
    _peer_cache = (path, firma, d)
    return dict(d)


def _ultima_buena_o_error(path: str, error: OSError) -> dict:
    """peer.json existe y no se pudo leer: la ultima lectura buena de `path`, o el error sube."""
    if _peer_cache is not None and _peer_cache[0] == path:
        state.log(f"peer.json: no lo pude leer ahora ({error}); sigo con la ultima lectura buena")
        return dict(_peer_cache[2])
    raise error


def _save_peer(d: dict) -> None:
    os.makedirs(state.LIENZO, exist_ok=True)
    global _peer_cache
    path = _peer_path()
    state.atomic_write(path, json.dumps(d, ensure_ascii=False, indent=1))
    # lo recien escrito ya es una «lectura buena»: si el proximo open falla (antivirus), se usa esta
    try:
        st = os.stat(path)
        _peer_cache = (path, (st.st_mtime_ns, st.st_size), dict(d))
    except OSError:
        pass  # sin cache: la proxima lectura lo arma


def _ensure_peer() -> dict:
    """Lee peer.json; si falta, esta corrupto o le faltan campos (nombre/color de un formato
    viejo), lo crea o lo completa. `pc_id` es el unico campo que, una vez creado, no se toca: un
    archivo corrupto se regenera con un id nuevo (perder la identidad vieja es mejor que no
    arrancar)."""
    with _lock:
        d = _load_peer()
        changed = d is None
        if d is None:
            d = {"pc_id": secrets.token_hex(6)}
        if not d.get("name"):
            d["name"] = socket.gethostname().lower()
            changed = True
        if not d.get("color"):
            d["color"] = _color_for(d["pc_id"])
            changed = True
        if changed:
            _save_peer(d)
        return d


def pc_id() -> str:
    return _ensure_peer()["pc_id"]


def pc_info() -> dict:
    d = _ensure_peer()
    return {"pc_id": d["pc_id"], "name": d["name"], "color": d["color"]}


def set_name(name: str) -> dict:
    """Cambia el nombre de esta PC (pantalla de emparejamiento, plan §3.1). El pc_id no se toca."""
    name = (name or "").strip()
    if not name:
        raise ValueError("el nombre no puede quedar vacio")
    with _lock:
        d = _ensure_peer()
        d["name"] = name
        _save_peer(d)
        return {"pc_id": d["pc_id"], "name": d["name"], "color": d["color"]}


# --- identidad de repo (plan §3.6) -------------------------------------------------------------


def _read_commondir(git_admin_dir: str) -> str | None:
    """Un worktree tiene su propio `<gitdir>/commondir` con la ruta (relativa) al `.git`
    compartido, que es donde vive el `config` con los remotes: el `.git` del worktree no tiene
    uno propio."""
    try:
        with open(os.path.join(git_admin_dir, "commondir"), encoding="utf-8") as f:
            rel = f.read().strip()
    except OSError:
        return None
    if not rel:
        return None
    return os.path.normpath(os.path.join(git_admin_dir, rel))


def _resolve_git_dir(entry: str) -> str:
    """De la entrada `.git` (carpeta normal, o archivo `gitdir: <ruta>` de un worktree) a la
    carpeta que realmente tiene `config`."""
    if os.path.isdir(entry):
        return entry
    try:
        with open(entry, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError:
        return entry
    if not line.startswith("gitdir:"):
        return entry
    admin = line.split(":", 1)[1].strip()
    if not os.path.isabs(admin):
        admin = os.path.join(os.path.dirname(entry), admin)
    admin = os.path.normpath(admin)
    return _read_commondir(admin) or admin


def _find_repo_root(cwd: str) -> tuple[str, str] | None:
    """(carpeta raiz del repo, carpeta git real) subiendo desde `cwd`, o `None` si no hay repo."""
    d = os.path.abspath(cwd)
    while True:
        git = os.path.join(d, ".git")
        if os.path.exists(git):
            return d, _resolve_git_dir(git)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# scp-like (`[user@]host:path`, sin "://"); la negativa evita confundir "https://" o una ruta de
# Windows con letra de unidad (que no trae un "/" pegado al ":")
_SCP_RE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?!/)(?P<path>.+)$")


def _normalize_remote(url: str) -> str | None:
    """host en minusculas, sin credenciales, sin `.git` final; `git@host:a/b` y
    `ssh://git@host/a/b` quedan como `host/a/b`, igual que la forma `https://`."""
    url = (url or "").strip()
    if not url:
        return None
    m = None if "://" in url else _SCP_RE.match(url)
    if m:
        host, path = m.group("host"), m.group("path")
    else:
        parsed = urlparse(url)
        host, path = parsed.hostname, parsed.path
        if not host:
            return None
    path = path.strip("/").removesuffix(".git")
    key = f"{host}/{path}".strip("/").lower()
    return key or None


def _origin_url(config_path: str) -> str | None:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        if not cp.read(config_path, encoding="utf-8"):
            return None
    except configparser.Error:
        return None
    for section in cp.sections():
        if re.fullmatch(r'remote\s+"origin"', section.strip()):
            return cp[section].get("url")
    return None


_repo_cache: dict[str, tuple[float | None, str | None]] = {}


def _cached_origin(config_path: str) -> str | None:
    """Cachea por `config_path` y su mtime: releer y reparsear el .git/config en cada llamada
    seria tirar CPU en cada tarjeta de cada barrido."""
    try:
        mtime = os.path.getmtime(config_path)
    except OSError:
        mtime = None
    with _lock:
        hit = _repo_cache.get(config_path)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        url = _origin_url(config_path) if mtime is not None else None
        _repo_cache[config_path] = (mtime, url)
        return url


def origin_url(cwd: str | None) -> str | None:
    """El remote `origin` tal cual del repo que contiene a `cwd`, o None (sin cwd, sin repo o sin
    origin). Lo usa health para probar la credencial de git solo de los repos en uso."""
    found = _find_repo_root(cwd) if cwd else None
    return _cached_origin(os.path.join(found[1], "config")) if found else None


def repo_key(cwd: str | None) -> str:
    """Remote `origin` normalizado del repo que contiene a `cwd`. Sin repo, o sin `cwd`: el nombre
    de la carpeta raiz del repo si lo hay, si no `repo_of(cwd)` (que ya sabe que hacer con
    `None`)."""
    found = _find_repo_root(cwd) if cwd else None
    if found is None:
        return state.repo_of(cwd)
    root, git_dir = found
    origin = _cached_origin(os.path.join(git_dir, "config"))
    key = _normalize_remote(origin) if origin else None
    return key or os.path.basename(root.rstrip("\\/")) or state.repo_of(cwd)
