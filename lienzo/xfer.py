"""Copiar archivos y carpetas a otra PC emparejada, por el listener de peers (encargo del 2026-10-04:
«un canal performante peer to peer, que aguante microcortes, estilo robocopy /Z /MT»).

Dos mitades en el mismo modulo:

  * **El que manda** (`Trabajo`, lo que arranca `POST /xfer` del tablero): lista el origen, le pide al
    otro lado que tiene, lee y hashea lo propio y manda solo lo distinto. Cada trabajo queda en
    `<LIENZO_HOME>/xfer/trabajos/<id>.json` (parametros y avance) y `<id>.hechos` (los archivos ya
    verificados del otro lado, uno por linea): un reinicio del server retoma desde ahi, a mitad del
    arbol, sin volver a leer lo ya hecho.
  * **El que recibe** (`atender_peer`, lo que llama `PeerHandler` para `/peer/xfer/*`): escribe a
    `<archivo>.parte`, lleva al lado un diario `<archivo>.parte.diario` con los bloques que ya llegaron
    y verifico, y renombra al nombre bueno recien con el archivo entero releido y verificado.

Firma: cada pedido es un pedido de peer comun (HMAC de la clave del par sobre metodo, ruta, cuerpo,
ts y nonce, ventana de +-30 s). El cuerpo grande se parte en bloques de `bs` (8 MiB de partida) y
cada bloque es su propio pedido firmado, asi que el modelo de firma de siempre alcanza: no hace falta
una firma por bloque aparte. Los archivos chicos viajan de a muchos en un `paquete` firmado entero.

Hash: sha256 (con SHA-NI de la CPU hace 1,5 GB/s contra 0,56 de blake2b, medido el 2026-10-04 en la
PC de Ariel). Hash por bloque al llegar, y del archivo entero al cerrar: el que recibe relee el
`.parte` y lo compara bloque a bloque con la lista del que manda. El hash del archivo que se informa
es el sha256 de la lista de hashes de sus bloques.

Rutas: origen y destino tienen que caer en `copy_roots` de la `config.json` de cada PC (vacia o
ausente es ninguna, como `launch_roots`). Las de WSL van como `\\\\wsl.localhost\\<distro>\\...`.

Solo biblioteca estandar.
"""

from __future__ import annotations

import collections
import hashlib
import http.client
import json
import os
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

try:
    from . import federation, state
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import federation
    import state

MIB = 1024 * 1024
BS = 8 * MIB  # tamano de bloque de partida (medido, ver README)
BS_MIN, BS_MAX = 1 * MIB, 32 * MIB
HILOS = 6
HILOS_MAX = 16
CHICO = 1 * MIB  # menos que esto viaja entero dentro de un paquete
PAQUETE_BYTES = 8 * MIB
PAQUETE_ARCHIVOS = 256
GRUPO = 256  # archivos chicos por pedido de estado
MAX_CUERPO = BS_MAX + MIB  # techo del cuerpo de /peer/xfer/*: un bloque grande y su cabecera
RESERVA_GB = 1.5  # la de health.RESERVA_GB: con menos libre, se frena
TIMEOUT_S = 120.0
TIMEOUT_LARGO_S = 1800.0  # estado y cerrar de un archivo grande releen GB del disco
REINTENTO_MAX_S = 30.0
INTENTOS_CAMBIO = 3  # un archivo que cambia en el origen mientras viaja se reintenta hasta aca
PARTE = ".parte"
DIARIO = ".parte.diario"
ACTIVOS = ("listando", "copiando", "esperando")

# el server lo cambia por su log; quien construye la conexion a un peer tambien lo pone el server
log: Callable[[str], None] = lambda msg: state.log(msg)
conn_de: Callable[[str], federation.PeerConn | None] = lambda pc: None


class Pausa(Exception):
    """El trabajo se pauso (DELETE /xfer/<id>) o el server se esta cerrando."""


class Rechazo(Exception):
    """El otro lado contesto que no (4xx que no se arregla reintentando)."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# --- comun ---------------------------------------------------------------------------------


def hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hash_total(hashes: list[str]) -> str:
    """El hash del archivo: sha256 de la lista de hashes de sus bloques, en orden."""
    return hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()


def n_bloques(size: int, bs: int) -> int:
    return (size + bs - 1) // bs


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def roots() -> list[str]:
    """`copy_roots` de config.json, normalizadas. Vacia o ausente: ninguna, no todas."""
    r = state.load_config().get("copy_roots")
    if not isinstance(r, list):
        return []
    return [_norm(x) for x in r if isinstance(x, str) and x.strip()]


def permitido(path: object) -> str | None:
    """La ruta absoluta normalizada si cae dentro de `copy_roots`; None si no. Un `:` despues de la
    unidad (un stream alternativo de NTFS) o un byte de control no pasan."""
    if not isinstance(path, str) or not path.strip() or any(ord(c) < 32 for c in path):
        return None
    if not os.path.isabs(path) or ":" in os.path.splitdrive(path)[1]:
        return None
    norm = _norm(path)
    for root in roots():
        if norm == root or norm.startswith(root.rstrip(os.sep) + os.sep):
            return os.path.normpath(path)
    return None


def rel_ok(rel: object) -> bool:
    """Una ruta relativa con `/`, sin `..`, sin unidad ni `:`, y que no choca con los temporales."""
    if not isinstance(rel, str) or not rel or len(rel) > 1024 or any(ord(c) < 32 for c in rel):
        return False
    partes = rel.split("/")
    return all(p and p not in (".", "..") and ":" not in p and "\\" not in p for p in partes) and not rel.endswith(
        (PARTE, DIARIO)
    )


def unir(raiz: str, rel: str) -> str:
    p = os.path.normpath(os.path.join(raiz, *rel.split("/")))
    if not _norm(p).startswith(_norm(raiz).rstrip(os.sep) + os.sep):
        raise Rechazo(400, "ruta relativa fuera del destino")
    return p


def mem_libre_gb() -> float | None:
    try:
        try:
            from . import health
        except ImportError:
            import health
        return health._memoria()[0]
    except Exception:
        return None


def prioridad_baja() -> None:
    """Hilo en modo segundo plano de Windows: baja la prioridad de CPU y tambien la de disco y
    memoria (THREAD_MODE_BACKGROUND_BEGIN). En otros sistemas, nada."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), 0x00010000)
    except Exception:  # sin prioridad baja se copia igual
        return


# --- cache de WSL ----------------------------------------------------------------------------
#
# Medido el 2026-10-04 copiando 2 GB de WSL a WSL: lo que se lee o escribe por 9p queda en la cache
# de paginas de la VM de WSL, que Windows ve como memoria de vmmemWSL. A mitad de la copia la PC que
# recibia bajo de 2,6 a 0,5 GB libres y la propia copia quedo frenada por la reserva. `dd
# iflag=nocache count=0` le pide al kernel de WSL que suelte las paginas de ESE archivo (2 GB en 2 s,
# y Windows recupera la memoria por page reporting): se hace cada SOLTAR_CADA bytes y al cerrar.

SOLTAR_CADA = 256 * MIB
_WSL_PREFIJOS = ("\\\\wsl.localhost\\", "\\\\wsl$\\")


def ruta_wsl(path: str) -> tuple[str, str] | None:
    """(distro, ruta de Linux) de una ruta `\\\\wsl.localhost\\<distro>\\...`; None si no es de WSL."""
    p = os.path.normpath(path)
    for pref in _WSL_PREFIJOS:
        if p.lower().startswith(pref.lower()):
            distro, _, resto = p[len(pref) :].partition("\\")
            if distro and resto:
                return distro, "/" + resto.replace("\\", "/")
    return None


def soltar_cache(path: str) -> None:
    """Le pide a WSL que suelte la cache de ese archivo, en un hilo aparte (wsl.exe tarda unos
    cientos de ms y no puede frenar un bloque). Fuera de WSL, nada. Un fallo solo se loguea: es un
    alivio de memoria, no parte de la copia."""
    w = ruta_wsl(path)
    if w is None:
        return

    def correr() -> None:
        try:
            try:
                from . import subproc
            except ImportError:
                import subproc
            code, _, err = subproc.correr(
                ["wsl.exe", "-d", w[0], "-e", "dd", f"if={w[1]}", "iflag=nocache", "count=0", "status=none"],
                timeout=60,
            )
            if code != 0:
                log(f"xfer: no pude soltar la cache de WSL de {w[1]} ({code}: {err.strip()[:120]})")
        except Exception as e:
            log(f"xfer: no pude soltar la cache de WSL de {w[1]} ({type(e).__name__}: {e})")

    threading.Thread(target=correr, name="xfer-cache-wsl", daemon=True).start()


class Soltador:
    """Cuenta bytes por archivo y suelta su cache de WSL cada SOLTAR_CADA."""

    def __init__(self):
        self._lock = threading.Lock()
        self._bytes: dict[str, int] = {}

    def sumar(self, path: str, n: int) -> None:
        if ruta_wsl(path) is None:
            return
        with self._lock:
            total = self._bytes.get(path, 0) + n
            soltar = total >= SOLTAR_CADA
            self._bytes[path] = 0 if soltar else total
        if soltar:
            soltar_cache(path)

    def cerrar(self, path: str) -> None:
        with self._lock:
            self._bytes.pop(path, None)
        soltar_cache(path)


SOLTADOR = Soltador()


def _partir(raw: bytes) -> tuple[dict, bytes]:
    """Cuerpo binario de bloque y paquete: una linea de JSON y despues los bytes."""
    i = raw.find(b"\n")
    if i < 0:
        raise Rechazo(400, "cuerpo sin cabecera")
    try:
        cab = json.loads(raw[:i].decode("utf-8"))
    except ValueError:
        raise Rechazo(400, "cabecera invalida") from None
    if not isinstance(cab, dict):
        raise Rechazo(400, "cabecera invalida")
    return cab, raw[i + 1 :]


def _armar(cab: dict, datos: bytes | list[bytes]) -> bytes:
    partes = datos if isinstance(datos, list) else [datos]
    return b"".join([json.dumps(cab, ensure_ascii=False).encode("utf-8"), b"\n", *partes])


# --- el que recibe -------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock_de(path: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(_norm(path), threading.Lock())


class CacheHashes:
    """Hashes por bloque de los archivos ya completos del destino, para no releer GB en cada pasada:
    vale solo si coinciden tamano, mtime_ns y tamano de bloque. En sqlite (WAL) bajo LIENZO_HOME."""

    def __init__(self):
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._ruta = ""

    def _conn(self) -> sqlite3.Connection:
        ruta = os.path.join(state.LIENZO, "xfer", "hashes.db")
        if self._db is None or ruta != self._ruta:
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            self._db = sqlite3.connect(ruta, check_same_thread=False, timeout=30)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS h (ruta TEXT PRIMARY KEY, size INT, mtime INT, bs INT, hashes TEXT)"
            )
            self._ruta = ruta
        return self._db

    def get(self, path: str, st: os.stat_result, bs: int) -> list[str] | None:
        with self._lock:
            fila = self._conn().execute("SELECT size, mtime, bs, hashes FROM h WHERE ruta=?", (_norm(path),)).fetchone()
        if fila and fila[0] == st.st_size and fila[1] == st.st_mtime_ns and fila[2] == bs:
            return json.loads(fila[3])
        return None

    def put(self, path: str, bs: int, hashes: list[str]) -> None:
        try:
            st = os.stat(path)
        except OSError:
            return
        with self._lock:
            db = self._conn()
            db.execute(
                "INSERT OR REPLACE INTO h VALUES (?,?,?,?,?)",
                (_norm(path), st.st_size, st.st_mtime_ns, bs, json.dumps(hashes)),
            )
            db.commit()

    def cerrar(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


CACHE = CacheHashes()


def hashes_de(path: str, bs: int) -> list[str]:
    out = []
    with open(path, "rb") as f:
        while True:
            b = f.read(bs)
            if not b:
                return out
            out.append(hash_bytes(b))


def _hashes_final(path: str, bs: int) -> list[str]:
    st = os.stat(path)
    h = CACHE.get(path, st, bs)
    if h is None:
        h = hashes_de(path, bs)
        CACHE.put(path, bs, h)
    return h


def leer_diario(path: str, bs: int) -> dict[int, str] | None:
    """{bloque: hash} de lo que el `.parte` ya tiene verificado, o None si no hay diario o es de
    otro tamano de bloque (no sirve: se tira y se empieza de nuevo)."""
    try:
        with open(path + DIARIO, encoding="ascii") as f:
            lineas = f.read().splitlines()
    except OSError, UnicodeDecodeError:
        return None
    if not lineas or lineas[0] != f"bs {bs}":
        return None
    out: dict[int, str] = {}
    for ln in lineas[1:]:
        partes = ln.split()
        try:
            if len(partes) == 2 and partes[0] == "x":
                out.pop(int(partes[1]), None)
            elif len(partes) == 2 and len(partes[1]) == 64:
                out[int(partes[0])] = partes[1]
        except ValueError:
            continue  # una linea a medias de un corte de luz: se ignora
    return out


def _anotar(path: str, lineas: list[str]) -> None:
    with open(path + DIARIO, "a", encoding="ascii") as f:
        f.write("".join(ln + "\n" for ln in lineas))
        f.flush()
        os.fsync(f.fileno())


def _tirar_parte(path: str) -> None:
    for ext in (PARTE, DIARIO):
        try:
            os.remove(path + ext)
        except FileNotFoundError:
            pass


def estado_archivo(path: str, bs: int) -> dict:
    """Lo que el destino tiene de un archivo: `{bloques: {i: hash}, parcial, size}`. Un `.parte` con
    diario manda sobre el final (es una copia a medias, mas nueva); uno sin diario no se sabe que
    tiene y se tira."""
    with _lock_de(path):
        if os.path.exists(path + PARTE):
            diario = leer_diario(path, bs)
            if diario is not None:
                return {"bloques": {str(i): h for i, h in diario.items()}, "parcial": True, "size": None}
            _tirar_parte(path)
        if os.path.isfile(path):
            h = _hashes_final(path, bs)
            return {"bloques": {str(i): x for i, x in enumerate(h)}, "parcial": False, "size": os.path.getsize(path)}
    return {"bloques": {}, "parcial": False, "size": None}


def _asegurar_parte(path: str, bs: int) -> None:
    """Crea `<archivo>.parte` y su diario si no estan. Si el destino ya tenia el archivo, el `.parte`
    arranca como copia del final (solo viajan los bloques distintos) y el diario lista sus bloques."""
    if os.path.exists(path + PARTE) and leer_diario(path, bs) is not None:
        return
    _tirar_parte(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lineas = [f"bs {bs}"]
    if os.path.isfile(path):
        h = _hashes_final(path, bs)
        shutil.copyfile(path, path + PARTE)
        lineas += [f"{i} {x}" for i, x in enumerate(h)]
    else:
        open(path + PARTE, "wb").close()
    with open(path + DIARIO, "w", encoding="ascii") as f:
        f.write("".join(ln + "\n" for ln in lineas))
        f.flush()
        os.fsync(f.fileno())


def _raiz(d: dict) -> str:
    raiz = permitido(d.get("destino"))
    if raiz is None:
        raise Rechazo(403, "destino fuera de copy_roots de esta PC")
    os.makedirs(raiz, exist_ok=True)
    return raiz


def _bs(d: dict) -> int:
    bs = d.get("bs")
    if not isinstance(bs, int) or not BS_MIN <= bs <= BS_MAX:
        raise Rechazo(400, "bs invalido")
    return bs


def _memoria_ok() -> None:
    libre = mem_libre_gb()
    if libre is not None and libre < RESERVA_GB:
        raise Rechazo(503, f"memoria baja en esta PC ({libre:.1f} GB libres, reserva {RESERVA_GB} GB)")


def r_estado(d: dict) -> dict:
    raiz, bs = _raiz(d), _bs(d)
    archivos = d.get("archivos")
    if not isinstance(archivos, list) or len(archivos) > 4 * GRUPO:
        raise Rechazo(400, "archivos invalido")
    out = {}
    for rel in archivos:
        if not rel_ok(rel):
            raise Rechazo(400, f"ruta relativa invalida: {rel!r}")
        out[rel] = estado_archivo(unir(raiz, rel), bs)
    return {"archivos": out, "libre": shutil.disk_usage(raiz).free}


def r_bloque(raw: bytes) -> dict:
    cab, datos = _partir(raw)
    raiz, bs = _raiz(cab), _bs(cab)
    rel, i, size, h = cab.get("rel"), cab.get("i"), cab.get("size"), cab.get("hash")
    if not rel_ok(rel) or not isinstance(i, int) or not isinstance(size, int) or i < 0 or size < 0:
        raise Rechazo(400, "cabecera de bloque invalida")
    if i >= n_bloques(size, bs) or len(datos) != min(bs, size - i * bs):
        raise Rechazo(400, "largo de bloque invalido")
    if hash_bytes(datos) != h:
        raise Rechazo(422, f"bloque {i} de {rel}: el hash no coincide")
    _memoria_ok()
    path = unir(raiz, rel)
    prioridad_baja()
    with _lock_de(path):
        _asegurar_parte(path, bs)
    with open(path + PARTE, "r+b") as f:
        f.seek(i * bs)
        f.write(datos)
        f.flush()
        os.fsync(f.fileno())
    with _lock_de(path):
        _anotar(path, [f"{i} {h}"])
    SOLTADOR.sumar(path + PARTE, len(datos))
    return {"ok": True}


def r_cerrar(d: dict) -> tuple[int, dict]:
    """Relee el `.parte` entero, lo compara con la lista del que manda y, si cierra, lo renombra. Si
    faltan o no coinciden bloques: 409 con cuales (y se borran del diario) para que los mande."""
    raiz, bs = _raiz(d), _bs(d)
    rel, size, mtime_ns, hashes = d.get("rel"), d.get("size"), d.get("mtime_ns"), d.get("hashes")
    if not rel_ok(rel) or not isinstance(size, int) or not isinstance(mtime_ns, int) or not isinstance(hashes, list):
        raise Rechazo(400, "cierre invalido")
    if len(hashes) != n_bloques(size, bs):
        raise Rechazo(400, "la lista de hashes no corresponde al tamano")
    path = unir(raiz, rel)
    prioridad_baja()
    with _lock_de(path):
        if not os.path.exists(path + PARTE):
            if os.path.isfile(path) and os.path.getsize(path) == size and _hashes_final(path, bs) == hashes:
                os.utime(path, ns=(mtime_ns, mtime_ns))
                CACHE.put(path, bs, hashes)
                return 200, {"ok": True, "igual": True, "hash": hash_total(hashes)}
            _asegurar_parte(path, bs)
        with open(path + PARTE, "r+b") as f:
            f.truncate(size)
            faltan = []
            for i, h in enumerate(hashes):
                f.seek(i * bs)
                b = f.read(bs)
                if hash_bytes(b) != h:
                    faltan.append(i)
                SOLTADOR.sumar(path + PARTE, len(b))
            f.flush()
            os.fsync(f.fileno())
        if faltan:
            _anotar(path, [f"x {i}" for i in faltan])
            return 409, {"error": f"{len(faltan)} bloques faltan o no coinciden", "faltan": faltan}
        os.replace(path + PARTE, path)
        os.utime(path, ns=(mtime_ns, mtime_ns))
        try:
            os.remove(path + DIARIO)
        except FileNotFoundError:
            pass
        CACHE.put(path, bs, hashes)
    SOLTADOR.cerrar(path)
    return 200, {"ok": True, "hash": hash_total(hashes)}


def r_paquete(raw: bytes) -> dict:
    """Varios archivos chicos enteros: cada uno se verifica, se escribe a `.parte`, se baja a disco
    y recien ahi se renombra. Devuelve `{rel: "ok" | motivo}`."""
    cab, datos = _partir(raw)
    raiz, bs = _raiz(cab), _bs(cab)
    archivos = cab.get("archivos")
    if (
        not isinstance(archivos, list)
        or len(archivos) > PAQUETE_ARCHIVOS
        or not all(isinstance(a, dict) for a in archivos)
    ):
        raise Rechazo(400, "paquete invalido")
    if sum(a.get("size") if isinstance(a.get("size"), int) else 0 for a in archivos) != len(datos):
        raise Rechazo(400, "el largo del paquete no cierra")
    _memoria_ok()
    prioridad_baja()
    out, off = {}, 0
    for a in archivos:
        rel, size, mtime_ns, h = a.get("rel"), a.get("size"), a.get("mtime_ns"), a.get("hash")
        if not rel_ok(rel) or not isinstance(size, int) or size >= bs or not isinstance(mtime_ns, int):
            raise Rechazo(400, "archivo de paquete invalido")
        trozo = datos[off : off + size]
        off += size
        if hash_bytes(trozo) != h:
            out[rel] = "hash"
            continue
        path = unir(raiz, rel)
        with _lock_de(path):
            _tirar_parte(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + PARTE, "wb") as f:
                f.write(trozo)
                f.flush()
                os.fsync(f.fileno())
            os.replace(path + PARTE, path)
            os.utime(path, ns=(mtime_ns, mtime_ns))
            CACHE.put(path, bs, [h] if size else [])
        out[rel] = "ok"
    return {"archivos": out}


def r_sobrantes(d: dict) -> dict:
    """Lo que hay en el destino y no en la lista del origen: lo que borraria el modo espejo."""
    raiz = _raiz(d)
    rels = d.get("rels")
    if not isinstance(rels, list):
        raise Rechazo(400, "rels invalido")
    origen = set(rels)
    sobra = [r for r, _, _ in listar(raiz) if r not in origen]
    return {"sobrantes": sobra[:20000], "total": len(sobra)}


def r_borrar(d: dict) -> dict:
    raiz = _raiz(d)
    rels = d.get("rels")
    if not isinstance(rels, list):
        raise Rechazo(400, "rels invalido")
    n = 0
    for rel in rels:
        if not rel_ok(rel):
            continue
        path = unir(raiz, rel)
        with _lock_de(path):
            try:
                os.remove(path)
                n += 1
            except FileNotFoundError:
                pass
    log(f"xfer espejo: {n} archivos borrados en {raiz}")
    return {"borrados": n}


def atender_peer(rest: list[str], raw: bytes) -> tuple[int, dict]:
    """POST /peer/xfer/<accion>. Todo lo que es del pedido (fuera de copy_roots, hash que no
    coincide, memoria baja) vuelve como codigo y motivo, nunca como 500."""
    try:
        accion = rest[0] if len(rest) == 1 else ""
        if accion == "bloque":
            return 200, r_bloque(raw)
        if accion == "paquete":
            return 200, r_paquete(raw)
        try:
            d = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            raise Rechazo(400, "JSON invalido") from None
        if not isinstance(d, dict):
            raise Rechazo(400, "el cuerpo debe ser un objeto JSON")
        if accion == "estado":
            return 200, r_estado(d)
        if accion == "cerrar":
            return r_cerrar(d)
        if accion == "sobrantes":
            return 200, r_sobrantes(d)
        if accion == "borrar":
            return 200, r_borrar(d)
        return 404, {"error": "ruta desconocida"}
    except Rechazo as e:
        return e.code, {"error": str(e)}
    except OSError as e:
        return 507 if getattr(e, "errno", None) == 28 else 500, {"error": f"{type(e).__name__}: {e}"}


# --- el que manda --------------------------------------------------------------------------


def listar(raiz: str) -> list[tuple[str, int, int]]:
    """(rel con `/`, size, mtime_ns) de cada archivo bajo `raiz`, sin seguir links ni juntions y sin
    los temporales del canal. Con os.scandir: las 57.000 de una carpeta de recortes en segundos."""
    out = []
    pila = [("", raiz)]
    while pila:
        pref, carpeta = pila.pop()
        try:
            entradas = list(os.scandir(carpeta))
        except OSError:
            continue
        for e in sorted(entradas, key=lambda x: x.name):
            rel = f"{pref}{e.name}"
            try:
                if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                    continue
                if e.is_dir(follow_symlinks=False):
                    pila.append((rel + "/", e.path))
                elif e.is_file(follow_symlinks=False) and not e.name.endswith((PARTE, DIARIO)):
                    st = e.stat(follow_symlinks=False)
                    out.append((rel, st.st_size, st.st_mtime_ns))
            except OSError:
                continue
    return out


class Balde:
    """Tope de bytes por segundo (0: sin tope), compartido por los hilos de un trabajo."""

    def __init__(self, mbps: float):
        self.rate = max(0.0, float(mbps or 0)) * 1e6
        self._lock = threading.Lock()
        self._t = time.monotonic()
        self._fichas = self.rate  # un segundo de rafaga

    def tomar(self, n: int) -> None:
        if self.rate <= 0:
            return
        with self._lock:
            ahora = time.monotonic()
            self._fichas = min(self.rate, self._fichas + (ahora - self._t) * self.rate) - n
            self._t = ahora
            espera = -self._fichas / self.rate if self._fichas < 0 else 0.0
        if espera > 0:
            time.sleep(espera)


def _dir_trabajos() -> str:
    d = os.path.join(state.LIENZO, "xfer", "trabajos")
    os.makedirs(d, exist_ok=True)
    return d


class Trabajo:
    PARAMS = ("id", "pc", "origen", "destino", "bs", "hilos", "mbps", "disco_mbps", "espejo", "creado")

    def __init__(self, d: dict):
        for k in self.PARAMS:
            setattr(self, k, d.get(k))
        self.estado: str = d.get("estado") or "listando"
        self.detalle = d.get("detalle") or ""
        self.confirmado = bool(d.get("confirmado"))
        self.borraria: list[str] = d.get("borraria") or []
        self.errores: list[str] = d.get("errores") or []
        self.terminado = d.get("terminado")
        self.bytes_total = self.archivos_total = 0
        self.bytes_hechos = self.archivos_hechos = 0
        self.bytes_enviados = d.get("bytes_enviados") or 0
        self.salteados = 0
        self.ultimos: collections.deque = collections.deque(maxlen=20)
        self._en_curso: dict[str, int] = {}
        self._lock = threading.RLock()
        self._pausa = threading.Event()
        self._hilo: threading.Thread | None = None
        self._local = threading.local()
        self._red = Balde(self.mbps or 0)
        self._disco = Balde(self.disco_mbps or 0)
        self._muestras: collections.deque = collections.deque(maxlen=60)
        self._ultimo_motivo = ""

    # --- persistencia
    def _ruta(self, ext: str) -> str:
        return os.path.join(_dir_trabajos(), f"{self.id}{ext}")

    def guardar(self) -> None:
        d = {k: getattr(self, k) for k in self.PARAMS}
        d.update(
            estado=self.estado,
            detalle=self.detalle,
            confirmado=self.confirmado,
            borraria=self.borraria[:20000],
            errores=self.errores[-30:],
            terminado=self.terminado,
            bytes_enviados=self.bytes_enviados,
        )
        state.atomic_write(self._ruta(".json"), json.dumps(d, ensure_ascii=False))

    def _cargar_hechos(self) -> set[str]:
        try:
            with open(self._ruta(".hechos"), encoding="utf-8") as f:
                return {ln.rstrip("\n") for ln in f if ln.endswith("\n")}
        except OSError:
            return set()

    def _hecho(self, rel: str, size: int, salteado: bool, h: str = "") -> None:
        with self._lock:
            with open(self._ruta(".hechos"), "a", encoding="utf-8") as f:
                f.write(rel + "\n")
            self.archivos_hechos += 1
            self.bytes_hechos += size
            self._en_curso.pop(rel, None)
            if salteado:
                self.salteados += 1
            self.ultimos.append({"rel": rel, "size": size, "hash": h, "salteado": salteado, "ts": time.time()})

    def _error(self, msg: str) -> None:
        with self._lock:
            self.errores.append(f"{time.strftime('%H:%M:%S')} {msg}")
            self.errores = self.errores[-30:]
        log(f"xfer {self.id}: {msg}")

    # --- vista
    def vista(self) -> dict:
        with self._lock:
            ahora = time.time()
            hechos = self.bytes_hechos + sum(self._en_curso.values())
            self._muestras.append((ahora, hechos, self.bytes_enviados))
            viejas = [m for m in self._muestras if ahora - m[0] <= 10] or [self._muestras[-1]]
            t0, h0, e0 = viejas[0]
            dt = max(ahora - t0, 1e-6)
            ritmo = (hechos - h0) / dt if dt > 0.5 else 0.0
            red = (self.bytes_enviados - e0) / dt if dt > 0.5 else 0.0
            falta = max(0, self.bytes_total - hechos)
            return {
                "id": self.id,
                "pc": self.pc,
                "origen": self.origen,
                "destino": self.destino,
                "estado": self.estado,
                "detalle": self.detalle,
                "bytes_total": self.bytes_total,
                "bytes_hechos": hechos,
                "bytes_enviados": self.bytes_enviados,
                "archivos_total": self.archivos_total,
                "archivos_hechos": self.archivos_hechos,
                "salteados": self.salteados,
                "pct": round(100 * hechos / self.bytes_total, 1)
                if self.bytes_total
                else (100.0 if self.estado == "terminado" else 0.0),
                "mbps": round(ritmo / 1e6, 1),
                "red_mbps": round(red / 1e6, 1),
                "eta_s": round(falta / ritmo) if ritmo > 1 and self.estado in ACTIVOS else None,
                "errores": list(self.errores[-10:]),
                "ultimos": list(self.ultimos)[-5:],
                "borraria": self.borraria[:200] if self.espejo else None,
                "borraria_total": len(self.borraria) if self.espejo else None,
                "params": {"bs": self.bs, "hilos": self.hilos, "mbps": self.mbps, "disco_mbps": self.disco_mbps},
                "creado": self.creado,
                "terminado": self.terminado,
            }

    # --- control
    def arrancar(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._pausa.clear()
        self._hilo = threading.Thread(target=self._correr, name=f"xfer-{self.id}", daemon=True)
        self._hilo.start()

    def pausar(self) -> None:
        self._pausa.set()

    def _chequear(self) -> None:
        if self._pausa.is_set():
            raise Pausa()

    def _esperar(self, s: float) -> None:
        if self._pausa.wait(s):
            raise Pausa()

    def _esperar_memoria(self) -> None:
        while True:
            libre = mem_libre_gb()
            if libre is None or libre >= RESERVA_GB:
                if self.detalle.startswith("memoria"):
                    self.detalle = ""
                return
            self.detalle = f"memoria baja aca ({libre:.1f} GB libres): espero"
            self._esperar(5)

    # --- red
    def _conn(self) -> tuple[http.client.HTTPConnection, federation.PeerConn]:
        peer = conn_de(self.pc)
        if peer is None:
            raise ConnectionRefusedError(f"sin conexion con {self.pc}")
        c = getattr(self._local, "c", None)
        if c is None or getattr(self._local, "dest", None) != (peer.host, peer.port):
            if c is not None:
                c.close()
            c = http.client.HTTPConnection(peer.host, peer.port, timeout=TIMEOUT_S)
            self._local.c, self._local.dest = c, (peer.host, peer.port)
        return c, peer

    def _soltar(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
        self._local.c = None

    def pedir(self, accion: str, cuerpo: bytes, timeout: float = TIMEOUT_S) -> tuple[int, dict]:
        """Un pedido firmado a /peer/xfer/<accion>, reintentando lo que es de red o de espera (corte,
        timeout, 503 de memoria, el otro server reiniciandose) hasta que ande o se pause. Un 401 se
        reintenta un rato (reloj corrido un momento, el otro server recien levantado) y despues se
        corta: con la clave distinta no se arregla esperando. Lo demas vuelve con su codigo."""
        path = f"/peer/xfer/{accion}"
        espera, rechazos = 1.0, 0
        while True:
            self._chequear()
            try:
                c, peer = self._conn()
                c.timeout = timeout
                if c.sock is not None:
                    c.sock.settimeout(timeout)
                c.request("POST", path, body=cuerpo, headers=federation.signed_headers(peer, "POST", path, cuerpo))
                r = c.getresponse()
                data = r.read()
                if (r.getheader("Connection") or "").lower() == "close":
                    self._soltar()
                try:
                    res = json.loads(data.decode("utf-8")) if data else {}
                except ValueError:
                    res = {"error": data[:200].decode("utf-8", "replace")}
                if r.status == 401:
                    rechazos += 1
                    if rechazos > 10:
                        raise Rechazo(401, f"la otra PC no acepta la firma: {res.get('error', '')}")
                if r.status in (401, 502, 503, 504):
                    raise ConnectionError(f"{r.status} {res.get('error', '')}")
                if self.detalle.startswith("reintento"):
                    self.detalle = ""
                return r.status, res
            except (OSError, http.client.HTTPException) as e:
                self._soltar()
                motivo = f"{accion}: {type(e).__name__}: {e}"[:200]
                if motivo != self._ultimo_motivo:
                    self._ultimo_motivo = motivo
                    self._error(motivo)
                self.detalle = f"reintento en {espera:.0f} s ({motivo})"
                self._esperar(espera)
                espera = min(espera * 2, REINTENTO_MAX_S)

    def _pedir_json(self, accion: str, d: dict, timeout: float = TIMEOUT_S) -> tuple[int, dict]:
        return self.pedir(accion, json.dumps(d, ensure_ascii=False).encode("utf-8"), timeout)

    def _enviar(self, accion: str, cuerpo: bytes, n: int, timeout: float = TIMEOUT_S) -> tuple[int, dict]:
        self._red.tomar(n)
        code, res = self.pedir(accion, cuerpo, timeout)
        if code == 200:
            with self._lock:
                self.bytes_enviados += n
        return code, res

    def _leer(self, path: str, off: int, n: int) -> bytes:
        self._esperar_memoria()
        self._disco.tomar(n)
        with open(path, "rb") as f:
            f.seek(off)
            return f.read(n)

    # --- el trabajo
    def _correr(self) -> None:
        prioridad_baja()
        try:
            self._fases()
        except Pausa:
            self.estado, self.detalle = "pausado", ""
        except Rechazo as e:
            self.estado = "error"
            self._error(str(e))
        except Exception as e:
            self.estado = "error"
            self._error(f"{type(e).__name__}: {e}")
            log(traceback.format_exc())
        finally:
            for c in (getattr(self._local, "c", None),):
                if c is not None:
                    c.close()
            self.guardar()

    def _fases(self) -> None:
        self.estado, self.detalle = "listando", ""
        self.guardar()
        origen = permitido(self.origen)
        if origen is None:
            raise Rechazo(403, "origen fuera de copy_roots de esta PC")
        if os.path.isfile(origen):
            base = os.path.dirname(origen)
            st = os.stat(origen)
            archivos = [(os.path.basename(origen), st.st_size, st.st_mtime_ns)]
        elif os.path.isdir(origen):
            base = origen
            archivos = listar(origen)
        else:
            raise Rechazo(404, "el origen no existe")
        hechos = self._cargar_hechos()
        self.archivos_total = len(archivos)
        self.bytes_total = sum(a[1] for a in archivos)
        self.archivos_hechos = sum(1 for a in archivos if a[0] in hechos)
        self.bytes_hechos = sum(a[1] for a in archivos if a[0] in hechos)
        pend = [a for a in archivos if a[0] not in hechos]
        if self.espejo and not self.confirmado:
            code, res = self._pedir_json(
                "sobrantes", {"destino": self.destino, "rels": [a[0] for a in archivos]}, TIMEOUT_LARGO_S
            )
            if code != 200:
                raise Rechazo(code, res.get("error") or f"sobrantes: {code}")
            self.borraria = res.get("sobrantes") or []
            self.estado = "confirmar_espejo"
            self.detalle = (
                f"el modo espejo borraria {res.get('total', 0)} archivos del destino: POST /xfer/{self.id}/confirmar"
            )
            return
        self.estado = "copiando"
        self.guardar()
        chicos = [a for a in pend if a[1] < min(CHICO, self.bs)]
        grandes = [a for a in pend if a[1] >= min(CHICO, self.bs)]
        # el espacio del otro lado, antes de mandar nada
        if pend:
            code, res = self._pedir_json("estado", {"destino": self.destino, "bs": self.bs, "archivos": []})
            if code != 200:
                raise Rechazo(code, res.get("error") or f"estado: {code}")
            falta = sum(a[1] for a in pend)
            if isinstance(res.get("libre"), int) and res["libre"] < falta:
                raise Rechazo(
                    507, f"no entra: faltan {falta / 1e9:.1f} GB y el destino tiene {res['libre'] / 1e9:.1f} GB libres"
                )
        grupos = [chicos[i : i + GRUPO] for i in range(0, len(chicos), GRUPO)]
        if grupos:
            with ThreadPoolExecutor(self.hilos, thread_name_prefix=f"xfer-{self.id}") as ex:
                list(ex.map(lambda g: self._grupo(base, g), grupos))
        for a in grandes:
            self._grande(base, a)
        if self.espejo and self.borraria:
            self.detalle = f"espejo: borrando {len(self.borraria)} archivos"
            code, res = self._pedir_json("borrar", {"destino": self.destino, "rels": self.borraria}, TIMEOUT_LARGO_S)
            if code != 200:
                raise Rechazo(code, res.get("error") or f"borrar: {code}")
        faltan = self.archivos_total - self.archivos_hechos
        self.estado = "terminado" if faltan == 0 else "con_errores"
        self.detalle = (
            "" if faltan == 0 else f"{faltan} archivos no se pudieron copiar (ver errores); retomar los reintenta"
        )
        self.terminado = time.time()
        log(
            f"xfer {self.id}: {self.estado}, {self.archivos_hechos} archivos ({self.salteados} ya estaban iguales), "
            f"{self.bytes_enviados / 1e6:.0f} MB por la red"
        )

    def _grupo(self, base: str, grupo: list[tuple[str, int, int]]) -> None:
        prioridad_baja()
        self._chequear()
        code, res = self._pedir_json(
            "estado", {"destino": self.destino, "bs": self.bs, "archivos": [a[0] for a in grupo]}, TIMEOUT_LARGO_S
        )
        if code != 200:
            self._error(f"estado: {code} {res.get('error')}")
            return
        remotos = res.get("archivos") or {}
        paquete: list[dict] = []
        datos: list[bytes] = []

        def mandar() -> None:
            if not paquete:
                return
            cuerpo = _armar({"destino": self.destino, "bs": self.bs, "archivos": paquete}, datos)
            try:
                code, res = self._enviar("paquete", cuerpo, sum(len(x) for x in datos))
                if code != 200:
                    self._error(f"paquete de {len(paquete)} archivos: {code} {res.get('error')}")
                    return
                for a in paquete:
                    r = (res.get("archivos") or {}).get(a["rel"])
                    if r == "ok":
                        self._hecho(a["rel"], a["size"], False, a["hash"])
                    else:
                        self._error(f"{a['rel']}: {r or 'sin respuesta'}; queda para la proxima pasada")
            finally:
                paquete.clear()
                datos.clear()

        for rel, size, mtime_ns in grupo:
            self._chequear()
            path = os.path.join(base, *rel.split("/"))
            try:
                b = self._leer(path, 0, size + 1)
                st = os.stat(path)
            except OSError as e:
                self._error(f"{rel}: no se puede leer ({e})")
                continue
            if len(b) != st.st_size or st.st_size >= min(CHICO, self.bs):
                self._error(f"{rel}: cambio en el origen mientras se leia; queda para la proxima pasada")
                continue
            h = hash_bytes(b)
            r = remotos.get(rel) or {}
            if not r.get("parcial") and r.get("size") == len(b) and (not b or (r.get("bloques") or {}).get("0") == h):
                self._hecho(rel, len(b), True, h)
                continue
            paquete.append({"rel": rel, "size": len(b), "mtime_ns": st.st_mtime_ns, "hash": h})
            datos.append(b)
            if len(paquete) >= PAQUETE_ARCHIVOS or sum(len(x) for x in datos) >= PAQUETE_BYTES:
                mandar()
        mandar()

    def _grande(self, base: str, a: tuple[str, int, int]) -> None:
        rel = a[0]
        path = os.path.join(base, *rel.split("/"))
        for _ in range(INTENTOS_CAMBIO):
            self._chequear()
            try:
                st0 = os.stat(path)
            except OSError as e:
                self._error(f"{rel}: no se puede leer ({e})")
                return
            self.detalle = f"{rel}: comparando con el destino"
            code, res = self._pedir_json(
                "estado", {"destino": self.destino, "bs": self.bs, "archivos": [rel]}, TIMEOUT_LARGO_S
            )
            if code != 200:
                self._error(f"{rel}: estado {code} {res.get('error')}")
                return
            remotos = ((res.get("archivos") or {}).get(rel) or {}).get("bloques") or {}
            size, bs = st0.st_size, self.bs
            n = n_bloques(size, bs)
            hashes = self._pasada(path, rel, size, remotos)
            st1 = os.stat(path)
            if (st1.st_size, st1.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns):
                self._error(f"{rel}: cambio en el origen mientras viajaba; lo vuelvo a pasar (solo lo distinto)")
                self._en_curso.pop(rel, None)
                continue
            self.detalle = f"{rel}: verificando del otro lado"
            for _ in range(3):
                code, res = self._pedir_json(
                    "cerrar",
                    {
                        "destino": self.destino,
                        "bs": bs,
                        "rel": rel,
                        "size": size,
                        "mtime_ns": st0.st_mtime_ns,
                        "hashes": hashes,
                    },
                    TIMEOUT_LARGO_S,
                )
                if code != 409:
                    break
                faltan = [i for i in res.get("faltan") or [] if isinstance(i, int) and 0 <= i < n]
                self._error(f"{rel}: el otro lado pide de nuevo {len(faltan)} bloques")
                for i in faltan:
                    datos = self._leer(path, i * bs, min(bs, size - i * bs))
                    if hash_bytes(datos) != hashes[i]:
                        break  # cambio en el origen: la vuelta de afuera lo repite
                    self._mandar_bloque(rel, size, i, datos, hashes[i])
            if code == 200:
                self._hecho(rel, size, bool(res.get("igual")), res.get("hash", ""))
                self.detalle = ""
                return
            self._error(f"{rel}: cerrar {code} {res.get('error')}")
            self._en_curso.pop(rel, None)
            return
        self._error(f"{rel}: cambio en el origen {INTENTOS_CAMBIO} veces seguidas; queda sin copiar")
        self._en_curso.pop(rel, None)

    def _pasada(self, path: str, rel: str, size: int, remotos: dict) -> list[str]:
        """Lee y hashea cada bloque con `hilos` en paralelo (en orden, para que el destino escriba casi
        secuencial: NTFS rellena con ceros hasta el bloque mas lejano) y manda los que el destino no
        tiene iguales. Devuelve la lista entera de hashes, para el cierre."""
        bs = self.bs
        hashes = [""] * n_bloques(size, bs)
        hecho = [0]
        self._en_curso[rel] = 0
        self.detalle = rel

        def bloque(i: int) -> None:
            self._chequear()
            datos = self._leer(path, i * bs, min(bs, size - i * bs))
            SOLTADOR.sumar(path, len(datos))
            h = hash_bytes(datos)
            hashes[i] = h
            if remotos.get(str(i)) != h:
                self._mandar_bloque(rel, size, i, datos, h)
            with self._lock:
                hecho[0] += len(datos)
                self._en_curso[rel] = hecho[0]

        try:
            with ThreadPoolExecutor(self.hilos, thread_name_prefix=f"xfer-{self.id}") as ex:
                list(ex.map(bloque, range(len(hashes))))
        finally:
            SOLTADOR.cerrar(path)
        return hashes

    def _mandar_bloque(self, rel: str, size: int, i: int, datos: bytes, h: str) -> None:
        cab = {"destino": self.destino, "bs": self.bs, "rel": rel, "size": size, "i": i, "hash": h}
        for _ in range(5):
            code, res = self._enviar("bloque", _armar(cab, datos), len(datos))
            if code == 200:
                return
            if code != 422:  # 422: el bloque llego distinto; se manda de nuevo
                raise Rechazo(code, f"{rel} bloque {i}: {res.get('error')}")
            self._error(f"{rel} bloque {i}: llego corrupto, lo mando de nuevo")
        raise Rechazo(422, f"{rel} bloque {i}: llego corrupto 5 veces seguidas")


# --- registro de trabajos (lo que usa el server) -------------------------------------------

TRABAJOS: dict[str, Trabajo] = {}
_reg_lock = threading.Lock()


def _numero(d: dict, k: str, defecto, lo, hi) -> int | float:
    v = d.get(k, defecto)
    if v is None:
        v = defecto
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise Rechazo(400, f"{k} fuera de rango ({lo} a {hi})")
    return v


def nuevo(d: dict, pc_propio: str) -> tuple[int, dict]:
    """POST /xfer {pc, origen, destino, bs_mib?, hilos?, mbps?, disco_mbps?, espejo?}."""
    try:
        pc = d.get("pc")
        if not isinstance(pc, str) or not pc or pc == pc_propio:
            raise Rechazo(400, "pc tiene que ser otra PC emparejada (el pc_id de GET /peers)")
        if conn_de(pc) is None:
            raise Rechazo(503, f"sin conexion con {pc}")
        if permitido(d.get("origen")) is None:
            raise Rechazo(403, "origen fuera de copy_roots de esta PC")
        if (
            not isinstance(d.get("destino"), str)
            or not os.path.isabs(d["destino"])
            and not d["destino"].startswith("\\\\")
        ):
            raise Rechazo(400, "destino tiene que ser una ruta absoluta de la otra PC")
        t = Trabajo(
            {
                "id": secrets.token_hex(4),
                "pc": pc,
                "origen": os.path.normpath(d["origen"]),
                "destino": d["destino"],
                "bs": int(_numero(d, "bs_mib", BS // MIB, 1, BS_MAX // MIB)) * MIB,
                "hilos": int(_numero(d, "hilos", HILOS, 1, HILOS_MAX)),
                "mbps": _numero(d, "mbps", 0, 0, 10000),
                "disco_mbps": _numero(d, "disco_mbps", 0, 0, 10000),
                "espejo": bool(d.get("espejo")),
                "creado": time.time(),
            }
        )
    except Rechazo as e:
        return e.code, {"error": str(e)}
    with _reg_lock:
        TRABAJOS[t.id] = t
    t.guardar()
    t.arrancar()
    log(f"xfer {t.id}: {t.origen} -> {pc}:{t.destino} (bs {t.bs // MIB} MiB, {t.hilos} hilos)")
    return 202, {"id": t.id}


def ver(tid: str) -> tuple[int, dict]:
    t = TRABAJOS.get(tid)
    return (200, t.vista()) if t else (404, {"error": "no existe ese trabajo"})


def todos() -> list[dict]:
    return [t.vista() for t in sorted(TRABAJOS.values(), key=lambda x: x.creado or 0, reverse=True)]


def pausar(tid: str) -> tuple[int, dict]:
    """Pausa: los hilos cortan al terminar el bloque o el pedido en curso. No se espera mas de unos
    segundos (un cierre que relee GB puede tardar): la vista dice `pausando` hasta que corten."""
    t = TRABAJOS.get(tid)
    if t is None:
        return 404, {"error": "no existe ese trabajo"}
    t.pausar()
    if t._hilo is not None:
        t._hilo.join(timeout=3)
    if t._hilo is not None and t._hilo.is_alive():
        t.detalle = "pausando: termina lo que tiene en vuelo"
    elif t.estado in ACTIVOS or t.estado == "confirmar_espejo":
        t.estado = "pausado"
    t.guardar()
    return 200, t.vista()


def retomar(tid: str, *, confirmar: bool = False) -> tuple[int, dict]:
    t = TRABAJOS.get(tid)
    if t is None:
        return 404, {"error": "no existe ese trabajo"}
    if t._hilo is not None and t._hilo.is_alive():
        if not confirmar:
            return 409, {"error": "ya esta corriendo"}
        t._hilo.join(timeout=5)
    if confirmar:
        if not t.espejo:
            return 400, {"error": "ese trabajo no es espejo"}
        t.confirmado = True
    t.errores = []
    t.arrancar()
    return 202, {"id": t.id}


def resumen() -> dict | None:
    """Para el chip de la PC: cuantos trabajos activos, el avance conjunto y la velocidad."""
    activos = [t.vista() for t in TRABAJOS.values() if t.estado in ACTIVOS]
    if not activos:
        return None
    total = sum(v["bytes_total"] for v in activos)
    hechos = sum(v["bytes_hechos"] for v in activos)
    return {
        "activos": len(activos),
        "pct": round(100 * hechos / total, 1) if total else 0.0,
        "mbps": round(sum(v["mbps"] for v in activos), 1),
    }


def arrancar() -> None:
    """Al arrancar el server: carga los trabajos guardados y retoma los que estaban andando."""
    try:
        nombres = os.listdir(_dir_trabajos())
    except OSError:
        return
    for n in nombres:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir_trabajos(), n), encoding="utf-8") as f:
                t = Trabajo(json.load(f))
        except (OSError, ValueError) as e:
            log(f"xfer: no pude leer {n} ({e})")
            continue
        if not t.id:
            continue
        TRABAJOS[t.id] = t
        if t.estado in ACTIVOS:
            log(f"xfer {t.id}: retomo despues del reinicio")
            t.arrancar()
