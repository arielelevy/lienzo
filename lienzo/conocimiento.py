"""Conocimiento por proyecto (docs/propuesta-memoria-2026-10-08/v5.md), etapa 1: identidad de
proyecto, esquema SQLite con FTS5 y CTE recursivo, nodos con estado y transiciones, vinculos
tipados, historial de cambios, rondas, encargos, entrega explicita de informes y los adaptadores de
lo que el server ya observa (sesiones que cierran, permisos denegados, errores de API, muerte con
un encargo a medias).

Vive en `<LIENZO_HOME>/proyectos/<proyecto>/`: `conocimiento.sqlite`, `rondas/<ronda>/` con los
cuerpos de encargos e informes, y `evidencia/`. `indice.json` al lado de las carpetas dice que
proyecto corresponde a cada remote y a cada carpeta por PC: `repo_key` cambia si una PC tiene remote
y la otra no (MEJORAS.md, 2026-10-04), asi que el proyecto tiene identidad propia.

Funciones puras respecto de HTTP: devuelven dicts y levantan `Rechazo` (con codigo) ante lo
invalido; `conocimiento_api.py` traduce a (codigo, cuerpo). Solo biblioteca estandar (sqlite3 trae
FTS5 y JSON1 en el Python de esta PC: 3.50.4, medido el 2026-10-08).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import uuid

import identity
import state
from atomico import atomic_write

VERSION_ESQUEMA = 1
LIMITE_BUSQUEDA = 30
LIMITE_PAGINA = 100
SALTOS_MAX = 2

TIPOS = (
    "ronda",
    "encargo",
    "sesion",
    "informe",
    "hallazgo",
    "decision",
    "alternativa",
    "incidente",
    "regla",
    "medicion",
    "pregunta",
    "tema",
    "evidencia",
)
# estado con el que nace cada tipo (v5 §3.4); None = sin estado (SQL NULL)
ESTADO_INICIAL = {
    "ronda": "abierta",
    "encargo": "pendiente",
    "sesion": "viva",
    "informe": "recibido",
    "hallazgo": "propuesto",
    "decision": "propuesta",
    "alternativa": None,
    "incidente": "observado",
    "regla": "propuesta",
    "medicion": "propuesta",
    "pregunta": "abierta",
    "tema": None,
    "evidencia": None,
}
# (de, a) -> quienes pueden disparar la transicion (v5 §3.4). `por` se escribe como
# 'server' | 'coordinadora:<sid>' | 'frente:<sid>' | 'persona:<nombre>'; se mira el rol antes del ':'
S, C, F, P = "server", "coordinadora", "frente", "persona"
TRANSICIONES: dict[str, dict[tuple[str, str], set[str]]] = {
    "ronda": {
        ("abierta", "suspendida"): {C, P},
        ("suspendida", "abierta"): {C, P},
        ("abierta", "cerrada"): {C, P},
        ("suspendida", "cerrada"): {C, P},
    },
    "encargo": {
        ("pendiente", "enviado"): {S},
        ("enviado", "entregado"): {S},
        ("pendiente", "sin_entrega"): {C, P},
        ("enviado", "sin_entrega"): {C, P},
        ("sin_entrega", "pendiente"): {C, P},
        ("sin_entrega", "entregado"): {C, P},
    },
    "sesion": {("viva", "cerrada"): {S}, ("cerrada", "viva"): {S}},
    "informe": {("recibido", "revisado"): {C, P}},
    "hallazgo": {
        ("propuesto", "confirmado"): {C, P},
        ("propuesto", "rechazado"): {C, P},
        ("confirmado", "corregido"): {C, P},
        ("confirmado", "rechazado"): {C, P},
        ("corregido", "rechazado"): {C, P},
        ("rechazado", "propuesto"): {C, P},
        ("corregido", "confirmado"): {C, P},
    },
    "decision": {
        ("propuesta", "vigente"): {C, P},
        ("propuesta", "revertida"): {C, P},
        ("vigente", "reemplazada"): {C, P},
        ("vigente", "revertida"): {C, P},
    },
    "incidente": {
        ("observado", "diagnosticado"): {C, P},
        ("observado", "resuelto"): {C, P},
        ("diagnosticado", "resuelto"): {C, P},
        ("diagnosticado", "observado"): {C, P},
    },
    "regla": {
        ("propuesta", "vigente"): {C, P},
        ("propuesta", "retirada"): {C, P},
        ("vigente", "retirada"): {C, P},
        ("vigente", "cuestionada"): {S},
        ("cuestionada", "vigente"): {C, P},
        ("cuestionada", "retirada"): {C, P},
    },
    "medicion": {
        ("propuesta", "valida"): {C, P},
        ("propuesta", "rechazada"): {C, P},
        ("valida", "superada"): {C, P},
        ("valida", "rechazada"): {C, P},
    },
    "pregunta": {("abierta", "contestada"): {C, P}, ("contestada", "abierta"): {C, P}},
}
# relacion -> (tipos de origen, tipos de destino) (v5 §3.2)
RELACIONES: dict[str, tuple[set[str], set[str]]] = {
    "ejecutado_por": ({"encargo"}, {"sesion"}),
    "responde_a": ({"informe"}, {"encargo"}),
    "declarado_en": (set(TIPOS[4:]), {"informe"}),
    "motivada_por": ({"decision"}, {"hallazgo", "medicion", "incidente", "decision"}),
    "elige": ({"decision"}, {"alternativa"}),
    "descarta": ({"decision"}, {"alternativa"}),
    "reemplaza": ({"decision", "regla", "medicion"}, {"decision", "regla", "medicion"}),
    "encontrado_por": ({"hallazgo"}, {"sesion"}),
    "confirmado_por": ({"hallazgo"}, {"sesion", "evidencia"}),
    "mismo_que": ({"hallazgo"}, {"hallazgo"}),
    "corregido_en": ({"hallazgo", "incidente"}, {"evidencia"}),
    "repite": ({"incidente"}, {"incidente"}),
    "derivada_de": ({"regla"}, {"incidente", "decision"}),
    "aplica_a": ({"regla"}, {"tema"}),
    "contesta": ({"hallazgo", "decision", "medicion", "informe"}, {"pregunta"}),
    "sobre": (set(TIPOS), {"tema"}),
    "apoya": (set(TIPOS), {"evidencia"}),
}
CON_MOTIVO = {"elige", "descarta"}  # el motivo es obligatorio
# el bloque `conocimiento` del informe (v5 §5.2): lo que un frente puede declarar
DECLARABLES = set(TIPOS[4:])  # de hallazgo a evidencia; ronda, encargo, sesion e informe los crea el server
RELACIONES_DEL_FRENTE = {"motivada_por", "elige", "descarta", "derivada_de", "aplica_a", "sobre", "apoya"}
GRAVEDADES = ("baja", "media", "alta", "critica")
AMBITOS = ("proyecto", "agente")
BLOQUE = re.compile(r"```conocimiento[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)
ID_LOCAL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
SIN_CICLOS = {"mismo_que", "repite", "reemplaza"}
MISMO_TIPO_EN_REEMPLAZA = True

ID_PROYECTO = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
LETRA = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS proyecto (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodo (
  id TEXT PRIMARY KEY,
  proyecto TEXT NOT NULL REFERENCES proyecto(id),
  tipo TEXT NOT NULL CHECK (tipo IN (
    'ronda','encargo','sesion','informe','hallazgo','decision','alternativa',
    'incidente','regla','medicion','pregunta','tema','evidencia')),
  texto TEXT NOT NULL,
  datos TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(datos)),
  estado TEXT,
  estado_fecha TEXT,
  estado_por TEXT,
  autor TEXT NOT NULL,
  origen TEXT NOT NULL CHECK (json_valid(origen)),
  ronda TEXT REFERENCES nodo(id),
  fecha TEXT NOT NULL,
  clave_ingesta TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS nodo_tipo ON nodo(proyecto, tipo, estado);
CREATE TABLE IF NOT EXISTS vinculo (
  de TEXT NOT NULL REFERENCES nodo(id),
  relacion TEXT NOT NULL,
  a TEXT NOT NULL REFERENCES nodo(id),
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
  fecha TEXT NOT NULL,
  autor TEXT NOT NULL,
  origen TEXT NOT NULL CHECK (json_valid(origen)),
  motivo TEXT,
  PRIMARY KEY (de, relacion, a)
);
CREATE INDEX IF NOT EXISTS vinculo_inverso ON vinculo(a, relacion, activo);
CREATE TABLE IF NOT EXISTS cambio (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  proyecto TEXT NOT NULL REFERENCES proyecto(id),
  nodo_id TEXT REFERENCES nodo(id),
  de TEXT REFERENCES nodo(id),
  relacion TEXT,
  a TEXT REFERENCES nodo(id),
  accion TEXT NOT NULL,
  anterior TEXT CHECK (anterior IS NULL OR json_valid(anterior)),
  nuevo TEXT NOT NULL CHECK (json_valid(nuevo)),
  autor TEXT NOT NULL,
  motivo TEXT NOT NULL,
  origen TEXT NOT NULL CHECK (json_valid(origen)),
  fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cambio_proyecto ON cambio(proyecto, seq);
CREATE VIRTUAL TABLE IF NOT EXISTS nodo_fts USING fts5(
  texto, datos, content='nodo', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS nodo_ai AFTER INSERT ON nodo BEGIN
  INSERT INTO nodo_fts(rowid, texto, datos) VALUES (new.rowid, new.texto, new.datos);
END;
CREATE TRIGGER IF NOT EXISTS nodo_ad AFTER DELETE ON nodo BEGIN
  INSERT INTO nodo_fts(nodo_fts, rowid, texto, datos) VALUES ('delete', old.rowid, old.texto, old.datos);
END;
CREATE TRIGGER IF NOT EXISTS nodo_au AFTER UPDATE ON nodo BEGIN
  INSERT INTO nodo_fts(nodo_fts, rowid, texto, datos) VALUES ('delete', old.rowid, old.texto, old.datos);
  INSERT INTO nodo_fts(rowid, texto, datos) VALUES (new.rowid, new.texto, new.datos);
END;
"""

_lock = threading.RLock()  # el indice y las carpetas; la base tiene sus propias transacciones
_sesion_proyecto: dict[str, str] = {}  # session_id -> proyecto, para los adaptadores (bajo _lock)
_sesion_sin_proyecto: set[str] = set()  # sesiones que ya se buscaron en todas las bases y no estan (bajo _lock)


class Rechazo(ValueError):
    """Un pedido invalido: `codigo` HTTP y mensaje para el cliente."""

    def __init__(self, msg: str, codigo: int = 400):
        super().__init__(msg)
        self.codigo = codigo


# --- utilidades ---------------------------------------------------------------------------


def ahora() -> str:
    """Fechas en UTC con milisegundos: lo que se compara entre PCs y en las consultas (v5 §8.5)."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def nuevo_id() -> str:
    return uuid.uuid4().hex


def raiz() -> str:
    """`<LIENZO_HOME>/proyectos`, leido en cada llamada: las pruebas apuntan LIENZO_HOME a una carpeta
    temporal despues de importar state."""
    return os.path.join(os.environ.get("LIENZO_HOME") or state.LIENZO, "proyectos")


norm_cwd = identity.norm_cwd


def _json(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def _objeto(x, nombre: str) -> dict:
    if x is None:
        return {}
    if not isinstance(x, dict):
        raise Rechazo(f"{nombre} debe ser un objeto JSON")
    return x


def _texto(x, nombre: str, maximo: int = 4000) -> str:
    if not isinstance(x, str) or not x.strip():
        raise Rechazo(f"{nombre} debe ser un texto no vacio")
    return x.strip()[:maximo]


def rol_de(por: str) -> str:
    return (por or "").split(":", 1)[0]


# --- indice de proyectos --------------------------------------------------------------------


def _indice_path() -> str:
    return os.path.join(raiz(), "indice.json")


def _leer_indice() -> dict:
    d, err = state.leer_json(_indice_path())
    if err is not None or not isinstance(d, dict):
        return {"proyectos": {}}
    d.setdefault("proyectos", {})
    return d


def _guardar_indice(d: dict) -> None:
    os.makedirs(raiz(), exist_ok=True)
    atomic_write(_indice_path(), json.dumps(d, ensure_ascii=False, indent=1))


def proyectos() -> list[dict]:
    with _lock:
        d = _leer_indice()
    return [{"id": k, **v} for k, v in sorted(d["proyectos"].items())]


def proyecto(pid: str) -> dict:
    with _lock:
        p = _leer_indice()["proyectos"].get(pid)
    if not p:
        raise Rechazo(f"proyecto desconocido: {pid}", 404)
    return {"id": pid, **p}


def _carpeta(pid: str) -> str:
    return os.path.join(raiz(), pid)


def _db_path(pid: str) -> str:
    return os.path.join(_carpeta(pid), "conocimiento.sqlite")


def registrar_proyecto(
    pid: str, nombre: str | None = None, remotes: list[str] | None = None, carpetas: list[dict] | None = None
) -> dict:
    """Crea el proyecto (carpeta, base con esquema y fila) o le suma aliases en el indice si ya existe.
    `remotes` son claves normalizadas (`identity.repo_key` de un repo con origin: host/a/b);
    `carpetas` son {pc, cwd}. Nada se fusiona por nombre: un alias que ya es de otro proyecto es 409."""
    if not isinstance(pid, str) or not ID_PROYECTO.fullmatch(pid):
        raise Rechazo("id de proyecto invalido: minusculas, digitos, punto, guion o guion bajo, hasta 64")
    remotes = [r.strip().lower() for r in (remotes or []) if isinstance(r, str) and r.strip()]
    carpetas = [
        {"pc": str(c.get("pc") or ""), "cwd": norm_cwd(c.get("cwd"))}
        for c in (carpetas or [])
        if isinstance(c, dict) and c.get("cwd")
    ]
    with _lock:
        idx = _leer_indice()
        for otro, v in idx["proyectos"].items():
            if otro == pid:
                continue
            if set(remotes) & set(v.get("remotes") or []):
                raise Rechazo(f"un remote ya pertenece al proyecto {otro}", 409)
            if any(c in (v.get("carpetas") or []) for c in carpetas):
                raise Rechazo(f"una carpeta ya pertenece al proyecto {otro}", 409)
        p = idx["proyectos"].get(pid)
        nuevo = p is None
        if nuevo:
            p = {"nombre": _texto(nombre or pid, "nombre", 200), "remotes": [], "carpetas": [], "creado": ahora()}
            idx["proyectos"][pid] = p
        for r in remotes:
            if r not in p["remotes"]:
                p["remotes"].append(r)
        for c in carpetas:
            if c not in p["carpetas"]:
                p["carpetas"].append(c)
        os.makedirs(os.path.join(_carpeta(pid), "rondas"), exist_ok=True)
        os.makedirs(os.path.join(_carpeta(pid), "evidencia"), exist_ok=True)
        with _abrir(pid) as con:
            # remotes y carpetas viven solo en indice.json: una copia en la base seria una segunda
            # fuente de verdad que nadie lee (code review 2026-10-08)
            con.execute(
                "INSERT OR IGNORE INTO proyecto (id, nombre, creado) VALUES (?, ?, ?)", (pid, p["nombre"], p["creado"])
            )
        _guardar_indice(idx)
        if nuevo:
            state.log(f"conocimiento: proyecto {pid} registrado")
    return {"id": pid, **p}


def resolver_proyecto(repo_key: str | None = None, cwd: str | None = None, pc: str | None = None) -> str | None:
    """El proyecto de una tarjeta, por remote (repo_key normalizado) o por carpeta en esa PC. None si
    no esta asignado: las coincidencias por nombre solo sugieren (v5 §8.1), no asignan."""
    rk = (repo_key or "").strip().lower()
    c = norm_cwd(cwd)
    with _lock:
        idx = _leer_indice()
    for pid, v in idx["proyectos"].items():
        if rk and rk in (v.get("remotes") or []):
            return pid
        if c and any(x.get("cwd") == c and (not pc or x.get("pc") in ("", pc)) for x in (v.get("carpetas") or [])):
            return pid
    return None


# --- base por proyecto ----------------------------------------------------------------------


class _Conexion:
    """Una conexion por operacion, con transaccion: `with _abrir(pid) as con:` confirma al salir sin
    excepcion y revierte si la hubo. Sin conexiones compartidas entre hilos."""

    def __init__(self, path: str):
        self.path = path

    def __enter__(self) -> sqlite3.Connection:
        self.con = sqlite3.connect(self.path, timeout=10, isolation_level="DEFERRED")
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        # el esquema se decide por user_version, no por si el archivo existia: connect lo crea antes
        # de que corra el esquema, y un fallo a mitad dejaria una base vacia que nadie repararia
        if self.con.execute("PRAGMA user_version").fetchone()[0] < VERSION_ESQUEMA:
            self.con.execute("PRAGMA journal_mode = WAL")
            self.con.executescript(ESQUEMA)
            self.con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
            self.con.commit()
        return self.con

    def __exit__(self, et, ev, tb):
        if et is None:
            self.con.commit()
        else:
            self.con.rollback()
        self.con.close()
        return False


def _abrir(pid: str) -> _Conexion:
    if not os.path.isdir(_carpeta(pid)):
        raise Rechazo(f"proyecto desconocido: {pid}", 404)
    return _Conexion(_db_path(pid))


def _fila(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("datos", "origen", "anterior", "nuevo"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def _nodo(con: sqlite3.Connection, pid: str, nid: str) -> dict:
    r = con.execute("SELECT * FROM nodo WHERE id = ? AND proyecto = ?", (nid, pid)).fetchone()
    if r is None:
        raise Rechazo(f"nodo desconocido: {nid}", 404)
    return _fila(r)


def _cambio(
    con, pid, accion, autor, motivo, origen, nuevo, anterior=None, nodo_id=None, de=None, relacion=None, a=None
):
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, de, relacion, a, accion, anterior, nuevo, autor, motivo, origen, fecha)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            pid,
            nodo_id,
            de,
            relacion,
            a,
            accion,
            _json(anterior) if anterior is not None else None,
            _json(nuevo),
            autor,
            motivo or "",
            _json(origen or {}),
            ahora(),
        ),
    )


def declarar_nodo(pid: str, tipo, texto, datos, *, autor: str, origen=None, ronda=None, motivo: str = "") -> dict:
    """Un nodo declarado a mano (POST /nodos): solo tipos de conocimiento (de hallazgo a evidencia) y
    con los mismos campos obligatorios que exige el bloque del informe. Ronda, encargo, sesion e
    informe los crea el server por sus propias operaciones."""
    if not isinstance(tipo, str) or tipo not in DECLARABLES:
        raise Rechazo(f"tipo no declarable: {tipo}")
    faltan = _faltan_datos(tipo, _objeto(datos, "datos"))
    if faltan:
        raise Rechazo("; ".join(faltan))
    return crear_nodo(pid, tipo, texto, datos, autor=autor, origen=origen, ronda=ronda, motivo=motivo)


def crear_nodo(
    pid: str,
    tipo: str,
    texto: str,
    datos: dict | None = None,
    *,
    autor: str,
    origen: dict | None = None,
    ronda: str | None = None,
    clave_ingesta: str | None = None,
    motivo: str = "",
    con: sqlite3.Connection | None = None,
) -> dict:
    """Un nodo nuevo con el estado inicial de su tipo. Con `clave_ingesta` es idempotente: si ya
    existe, devuelve el existente (`creado: False`)."""
    if not isinstance(tipo, str) or tipo not in TIPOS:
        raise Rechazo(f"tipo desconocido: {tipo}")
    texto = _texto(texto, "texto")
    datos = _objeto(datos, "datos")
    origen = _objeto(origen, "origen")
    autor = _texto(autor, "autor", 200)
    if con is None:
        with _abrir(pid) as c2:
            return crear_nodo(
                pid,
                tipo,
                texto,
                datos,
                autor=autor,
                origen=origen,
                ronda=ronda,
                clave_ingesta=clave_ingesta,
                motivo=motivo,
                con=c2,
            )
    if clave_ingesta:
        r = con.execute("SELECT * FROM nodo WHERE clave_ingesta = ?", (clave_ingesta,)).fetchone()
        if r is not None:
            return {**_fila(r), "creado": False}
    if ronda:
        rn = _nodo(con, pid, ronda)
        if rn["tipo"] != "ronda":
            raise Rechazo("ronda no es una ronda")
    estado = ESTADO_INICIAL[tipo]
    fecha = ahora()
    nid = nuevo_id()
    con.execute(
        "INSERT INTO nodo (id, proyecto, tipo, texto, datos, estado, estado_fecha, estado_por, autor, origen, ronda,"
        " fecha, clave_ingesta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            nid,
            pid,
            tipo,
            texto,
            _json(datos),
            estado,
            fecha if estado else None,
            autor if estado else None,
            autor,
            _json(origen),
            ronda,
            fecha,
            clave_ingesta,
        ),
    )
    n = _nodo(con, pid, nid)
    _cambio(con, pid, "nodo", autor, motivo, origen, n, nodo_id=nid)
    return {**n, "creado": True}


def cambiar_estado(
    pid: str,
    nid: str,
    nuevo: str,
    *,
    por: str,
    motivo: str = "",
    origen: dict | None = None,
    con: sqlite3.Connection | None = None,
) -> dict:
    """Aplica una transicion de v5 §3.4 o la rechaza (409). Idempotente si ya esta en `nuevo`."""
    por = _texto(por, "por", 200)
    origen = _objeto(origen, "origen")
    if con is None:
        with _abrir(pid) as c2:
            return cambiar_estado(pid, nid, nuevo, por=por, motivo=motivo, origen=origen, con=c2)
    n = _nodo(con, pid, nid)
    actual = n.get("estado")
    if actual == nuevo:
        return n
    permitidos = TRANSICIONES.get(n["tipo"], {}).get((actual, nuevo))
    if not permitidos:
        raise Rechazo(f"transicion no permitida para {n['tipo']}: {actual} -> {nuevo}", 409)
    if rol_de(por) not in permitidos:
        raise Rechazo(f"{rol_de(por) or '?'} no puede pasar {n['tipo']} de {actual} a {nuevo}", 403)
    fecha = ahora()
    con.execute("UPDATE nodo SET estado = ?, estado_fecha = ?, estado_por = ? WHERE id = ?", (nuevo, fecha, por, nid))
    n2 = _nodo(con, pid, nid)
    _cambio(con, pid, "estado", por, motivo, origen, n2, anterior=n, nodo_id=nid)
    return n2


def actualizar_datos(
    pid: str,
    nid: str,
    datos: dict,
    *,
    por: str,
    motivo: str = "",
    origen: dict | None = None,
    con: sqlite3.Connection | None = None,
) -> dict:
    """Mezcla claves en `datos` (lo que el server completa: hash, revision, cierre_seq). No cambia
    texto ni estado."""
    datos = _objeto(datos, "datos")
    if con is None:
        with _abrir(pid) as c2:
            return actualizar_datos(pid, nid, datos, por=por, motivo=motivo, origen=origen, con=c2)
    n = _nodo(con, pid, nid)
    nuevos = {**n["datos"], **datos}
    con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json(nuevos), nid))
    n2 = _nodo(con, pid, nid)
    _cambio(con, pid, "datos", por, motivo, origen or {}, n2, anterior=n, nodo_id=nid)
    return n2


def _hay_camino(con: sqlite3.Connection, relacion: str, desde: str, hasta: str) -> bool:
    """Para prohibir ciclos en mismo_que, repite y reemplaza: ¿se llega de `desde` a `hasta`?"""
    r = con.execute(
        "WITH RECURSIVE c(id) AS (SELECT ? UNION SELECT v.a FROM vinculo v JOIN c ON v.de = c.id"
        " WHERE v.relacion = ? AND v.activo = 1) SELECT 1 FROM c WHERE id = ? LIMIT 1",
        (desde, relacion, hasta),
    ).fetchone()
    return r is not None


def vincular(
    pid: str,
    de: str,
    relacion: str,
    a: str,
    *,
    autor: str,
    origen: dict | None = None,
    motivo: str | None = None,
    con: sqlite3.Connection | None = None,
) -> dict:
    """Un vinculo tipado entre dos nodos del mismo proyecto (v5 §3.2). Idempotente: el mismo vinculo
    activo se devuelve tal cual (`creado: False`)."""
    if relacion not in RELACIONES:
        raise Rechazo(f"relacion desconocida: {relacion}")
    autor = _texto(autor, "autor", 200)
    origen = _objeto(origen, "origen")
    if relacion in CON_MOTIVO and not (isinstance(motivo, str) and motivo.strip()):
        raise Rechazo(f"{relacion} exige motivo")
    if con is None:
        with _abrir(pid) as c2:
            return vincular(pid, de, relacion, a, autor=autor, origen=origen, motivo=motivo, con=c2)
    nd, na = _nodo(con, pid, de), _nodo(con, pid, a)
    tde, ta = RELACIONES[relacion]
    if nd["tipo"] not in tde or na["tipo"] not in ta:
        raise Rechazo(f"{relacion} no admite {nd['tipo']} -> {na['tipo']}")
    if de == a:
        raise Rechazo("un nodo no se vincula consigo mismo")
    if relacion == "reemplaza" and nd["tipo"] != na["tipo"]:
        raise Rechazo("reemplaza exige dos nodos del mismo tipo")
    if relacion in SIN_CICLOS and _hay_camino(con, relacion, a, de):
        raise Rechazo(f"{relacion} formaria un ciclo", 409)
    r = con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
    fecha = ahora()
    if r is not None and r["activo"]:
        return {**_fila(r), "creado": False}
    if r is not None:
        con.execute(
            "UPDATE vinculo SET activo = 1, fecha = ?, autor = ?, origen = ?, motivo = ? WHERE de = ? AND relacion = ?"
            " AND a = ?",
            (fecha, autor, _json(origen), motivo, de, relacion, a),
        )
    else:
        con.execute(
            "INSERT INTO vinculo (de, relacion, a, activo, fecha, autor, origen, motivo) VALUES (?,?,?,1,?,?,?,?)",
            (de, relacion, a, fecha, autor, _json(origen), motivo),
        )
    v = _fila(
        con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
    )
    _cambio(con, pid, "vinculo", autor, motivo or "", origen, v, de=de, relacion=relacion, a=a)
    return {**v, "creado": True}


def retirar_vinculo(pid: str, de: str, relacion: str, a: str, *, por: str, motivo: str = "") -> dict:
    with _abrir(pid) as con:
        r = con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
        if r is None:
            raise Rechazo("vinculo desconocido", 404)
        if not r["activo"]:
            return _fila(r)
        con.execute("UPDATE vinculo SET activo = 0 WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a))
        v = _fila(
            con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
        )
        _cambio(con, pid, "vinculo_retirado", por, motivo, {}, v, anterior=_fila(r), de=de, relacion=relacion, a=a)
        return v


# --- rondas, encargos, entregas -------------------------------------------------------------


def abrir_ronda(
    pid: str, objetivo: str, *, autor: str, coordinadora: str | None = None, origen: dict | None = None
) -> dict:
    datos = {"objetivo": objetivo, "coordinadora": coordinadora}
    n = crear_nodo(pid, "ronda", objetivo, datos, autor=autor, origen=origen, motivo="abrir ronda")
    os.makedirs(os.path.join(_carpeta(pid), "rondas", n["id"]), exist_ok=True)
    return n


def cerrar_ronda(pid: str, ronda: str, *, por: str, motivo: str = "", con: sqlite3.Connection | None = None) -> dict:
    """Cierre explicito (v5 §5.3, la parte de etapa 1): estado cerrada y `cierre_seq` con la ultima
    secuencia de cambios, para que «que cambio desde el cierre anterior» tenga de donde partir."""
    if con is None:
        with _abrir(pid) as c2:
            c2.execute("BEGIN IMMEDIATE")
            return cerrar_ronda(pid, ronda, por=por, motivo=motivo, con=c2)
    if _nodo(con, pid, ronda).get("estado") == "cerrada":
        raise Rechazo("la ronda ya esta cerrada", 409)
    n = cambiar_estado(pid, ronda, "cerrada", por=por, motivo=motivo or "cerrar ronda", con=con)
    seq = con.execute("SELECT COALESCE(MAX(seq), 0) FROM cambio WHERE proyecto = ?", (pid,)).fetchone()[0]
    return actualizar_datos(pid, n["id"], {"cierre_seq": seq}, por=por, motivo="cierre_seq", con=con)


def crear_encargo(
    pid: str,
    ronda: str,
    letra: str,
    texto: str,
    *,
    autor: str,
    archivos: list[str] | None = None,
    origen: dict | None = None,
) -> dict:
    """El pedido a un frente, con su cuerpo guardado en rondas/<ronda>/encargo-<letra>.md. La letra
    identifica el encargo dentro de la ronda (A, B, C...): dos encargos con la misma letra en la misma
    ronda son 409."""
    if not isinstance(letra, str) or not LETRA.fullmatch(letra):
        raise Rechazo("letra invalida")
    letra = letra.upper()  # encargo-A.md y encargo-a.md son el mismo archivo en Windows
    texto = _texto(texto, "texto", 200_000)
    archivos = [str(x) for x in (archivos or []) if isinstance(x, str)]
    with _abrir(pid) as con:
        rn = _nodo(con, pid, ronda)
        if rn["tipo"] != "ronda":
            raise Rechazo("ronda no es una ronda")
        if rn["estado"] == "cerrada":
            raise Rechazo("la ronda esta cerrada", 409)
        ruta = f"rondas/{ronda}/encargo-{letra}.md"  # siempre con /: la base viaja entre PCs (v5 §8.2)
        n = crear_nodo(
            pid,
            "encargo",
            (texto.splitlines()[0].lstrip("# ").strip() or letra)[:200],
            {"letra": letra, "archivos": archivos, "ruta": ruta},
            autor=autor,
            origen=origen,
            ronda=ronda,
            clave_ingesta=f"encargo:{ronda}:{letra}",
            motivo="crear encargo",
            con=con,
        )
        if not n["creado"]:
            raise Rechazo(f"ya hay un encargo {letra} en esta ronda", 409)
        _escribir_cuerpo(pid, ruta, texto)  # antes del commit: si el disco falla, el nodo no queda
    return n


def _escribir_cuerpo(pid: str, ruta: str, cuerpo: str) -> None:
    full = os.path.join(_carpeta(pid), *ruta.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    atomic_write(full, cuerpo)


def _sesion(con, pid, sid, *, agente=None, modelo=None, pc=None, cwd=None, autor="server") -> dict:
    datos = {"session_id": sid, "agente": agente, "modelo": modelo, "pc": pc, "cwd": cwd}
    datos = {k: v for k, v in datos.items() if v is not None}
    n = crear_nodo(
        pid,
        "sesion",
        f"{agente or '?'} {sid[:8]}",
        datos,
        autor=autor,
        origen={"session_id": sid},
        clave_ingesta=f"sesion:{sid}",
        motivo="sesion observada",
        con=con,
    )
    if not n["creado"] and any(v is not None and n["datos"].get(k) != v for k, v in datos.items()):
        con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json({**n["datos"], **datos}), n["id"]))
        n = _nodo(con, pid, n["id"])
    return n


def encargo_enviado(pid: str, encargo: str, sesion: dict, *, autor: str = "server") -> dict:
    """La tarjeta `sesion` tomo el encargo: pendiente -> enviado, nodo de sesion y vinculo
    ejecutado_por. `sesion` es la tarjeta real (conocimiento_api la busca en esta PC o en el espejo y
    rechaza un id que el lienzo no conoce) o, en las pruebas, un dict con session_id y, si se conocen,
    agent, model, pc, cwd."""
    sid = _texto(sesion.get("session_id"), "session_id", 100)
    with _abrir(pid) as con:
        e = _nodo(con, pid, encargo)
        if e["tipo"] != "encargo":
            raise Rechazo("no es un encargo")
        s = _sesion(
            con,
            pid,
            sid,
            agente=sesion.get("agent"),
            modelo=sesion.get("model"),
            pc=sesion.get("pc"),
            cwd=sesion.get("cwd"),
            autor=autor,
        )
        vincular(pid, encargo, "ejecutado_por", s["id"], autor=autor, origen={"session_id": sid}, con=con)
    with _lock:
        _sesion_proyecto[sid] = pid
        _sesion_sin_proyecto.discard(sid)
    if e["estado"] == "pendiente":
        return cambiar_estado(pid, encargo, "enviado", por="server", motivo="la tarjeta tomo el encargo")
    return e


def entregar(
    pid: str,
    encargo: str,
    cuerpo: str,
    *,
    revision: int,
    autor: str,
    origen: dict | None = None,
) -> dict:
    """La entrega explicita (v5 §5.1): el informe integro con su hash, en rondas/<ronda>/informe-<letra>-r<N>.md,
    un nodo informe `recibido`, responde_a el encargo, y el encargo pasa a entregado. Idempotente por
    (encargo, revision, hash). La misma revision con otro contenido es 409. Si el informe termina con
    un bloque ```conocimiento``` (v5 §5.2), se incorpora entero o queda pendiente con sus errores en
    datos.conocimiento; reenviar el mismo informe devuelve los ids ya creados."""
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise Rechazo("revision debe ser un entero >= 1")
    if not isinstance(cuerpo, str) or not cuerpo.strip():
        raise Rechazo("cuerpo vacio")
    sha = hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()
    origen = _objeto(origen, "origen")
    with _abrir(pid) as con:
        e = _nodo(con, pid, encargo)
        if e["tipo"] != "encargo":
            raise Rechazo("no es un encargo")
        letra = e["datos"].get("letra", "x")
        ruta = f"rondas/{e['ronda']}/informe-{letra}-r{revision}.md"
        otra = con.execute(
            "SELECT id, datos FROM nodo WHERE proyecto = ? AND tipo = 'informe' AND json_extract(datos, '$.revision') = ?"
            " AND EXISTS (SELECT 1 FROM vinculo v WHERE v.de = nodo.id AND v.relacion = 'responde_a' AND v.a = ?)",
            (pid, revision, encargo),
        ).fetchone()
        if otra is not None and json.loads(otra["datos"]).get("hash") != sha:
            raise Rechazo(f"la revision {revision} ya existe con otro contenido", 409)
        n = crear_nodo(
            pid,
            "informe",
            f"informe {letra} r{revision}",
            {"ruta": ruta, "hash": sha, "revision": revision, "bytes": len(cuerpo.encode("utf-8"))},
            autor=autor,
            origen=origen,
            ronda=e["ronda"],
            clave_ingesta=f"informe:{encargo}:{revision}:{sha}",
            motivo="entrega",
            con=con,
        )
        if n["creado"]:
            vincular(pid, n["id"], "responde_a", encargo, autor=autor, origen=origen, con=con)
            bloque = extraer_bloque(cuerpo)
            if bloque is not None:
                # v5 §5.2: todo o nada, en la misma transaccion que el informe. Con errores el informe
                # queda igual y el bloque «pendiente de vincular», con los errores por posicion
                res = _incorporar_bloque(con, pid, n["id"], e, bloque, autor=autor, origen=origen)
                datos = {**n["datos"], "conocimiento": res}
                con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json(datos), n["id"]))
                n2 = _nodo(con, pid, n["id"])
                _cambio(con, pid, "conocimiento", autor, res["estado"], origen, n2, anterior=n, nodo_id=n["id"])
                n = {**n2, "creado": True}
            _escribir_cuerpo(pid, ruta, cuerpo)  # antes del commit, como en crear_encargo
    if n["creado"] and e["estado"] == "enviado":
        cambiar_estado(pid, encargo, "entregado", por="server", motivo=f"informe r{revision}")
    return n


# --- el bloque `conocimiento` del informe (v5 §5.2, etapa 2) -------------------------------------


def extraer_bloque(cuerpo: str) -> str | None:
    """El texto del ultimo bloque ```conocimiento ... ``` del informe, o None si no hay (un informe sin
    bloque es valido)."""
    m = BLOQUE.findall(cuerpo or "")
    return m[-1] if m else None


def _campo(d: dict, k: str) -> bool:
    v = d.get(k)
    return isinstance(v, str) and bool(v.strip())


def _faltan_datos(tipo: str, d: dict) -> list[str]:
    """Los campos obligatorios de `datos` por tipo (tabla de v5 §5.2). Devuelve los errores."""
    err = []
    if tipo == "hallazgo":
        if not _campo(d, "donde"):
            err.append("falta datos.donde")
        if d.get("gravedad") not in GRAVEDADES:
            err.append(f"datos.gravedad debe ser una de {', '.join(GRAVEDADES)}")
    elif tipo == "decision":
        if not _campo(d, "motivo"):
            err.append("falta datos.motivo")
    elif tipo == "incidente":
        for k in ("herramienta", "agente"):
            if not _campo(d, k):
                err.append(f"falta datos.{k}")
    elif tipo == "regla":
        if d.get("ambito") not in AMBITOS:
            err.append(f"datos.ambito debe ser uno de {', '.join(AMBITOS)}")
        elif d.get("ambito") == "agente" and not _campo(d, "agente"):
            err.append("ambito=agente exige datos.agente")
    elif tipo == "medicion":
        for k in ("metrica", "unidad", "condicion"):
            if not _campo(d, k):
                err.append(f"falta datos.{k}")
        v = d.get("valor")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            err.append("datos.valor debe ser un numero finito")
    elif tipo == "pregunta":
        if not _campo(d, "para_quien"):
            err.append("falta datos.para_quien")
    elif tipo == "evidencia":
        for k in ("clase", "referencia"):
            if not _campo(d, k):
                err.append(f"falta datos.{k}")
    return err


def validar_bloque(con: sqlite3.Connection, pid: str, texto: str) -> tuple[dict | None, list[dict]]:
    """Parsea y valida el bloque entero: ids locales unicos, tipos declarables, campos obligatorios,
    vinculos del frente con extremos resolubles (id local o `nodo:<id>` del proyecto) y tipos
    compatibles, motivo en elige/descarta, decision con elige o descarta, regla con derivada_de.
    Devuelve (bloque, errores); con errores no se incorpora nada. Cada error dice donde."""
    try:
        b = json.loads(texto)
    except ValueError as e:
        return None, [{"donde": "bloque", "error": f"JSON invalido: {e}"}]
    if not isinstance(b, dict):
        return None, [{"donde": "bloque", "error": "el bloque debe ser un objeto JSON"}]
    err: list[dict] = []
    if b.get("version") != 1:
        err.append({"donde": "version", "error": "version debe ser 1"})
    nodos = b.get("nodos")
    if not isinstance(nodos, list):
        err.append({"donde": "nodos", "error": "nodos debe ser una lista"})
        nodos = []
    vinculos = b.get("vinculos", [])
    if not isinstance(vinculos, list):
        err.append({"donde": "vinculos", "error": "vinculos debe ser una lista"})
        vinculos = []
    tipos: dict[str, str] = {}  # id local -> tipo
    for i, nd in enumerate(nodos):
        donde = f"nodos[{i}]"
        if not isinstance(nd, dict):
            err.append({"donde": donde, "error": "cada nodo es un objeto"})
            continue
        lid = nd.get("id")
        if not isinstance(lid, str) or not ID_LOCAL.fullmatch(lid):
            err.append({"donde": donde, "error": "id local invalido"})
        elif lid in tipos:
            err.append({"donde": f"nodo {lid}", "error": "id local repetido"})
        else:
            donde = f"nodo {lid}"
        tipo = nd.get("tipo")
        if not isinstance(tipo, str) or tipo not in DECLARABLES:
            err.append({"donde": donde, "error": f"tipo no declarable: {tipo}"})
            tipo = None
        if not isinstance(nd.get("texto"), str) or not nd["texto"].strip():
            err.append({"donde": donde, "error": "texto vacio"})
        datos = nd.get("datos")
        if not isinstance(datos, dict):
            err.append({"donde": donde, "error": "datos debe ser un objeto"})
            datos = {}
        if tipo:
            err += [{"donde": donde, "error": x} for x in _faltan_datos(tipo, datos)]
            if isinstance(lid, str) and lid not in tipos:
                tipos[lid] = tipo

    def resolver(ref, donde):
        """(id persistente o None, tipo) de un extremo; registra el error si no se resuelve."""
        if not isinstance(ref, str) or not ref.strip():
            err.append({"donde": donde, "error": "extremo vacio"})
            return None, None
        if ref.startswith("nodo:"):
            r = con.execute("SELECT id, tipo FROM nodo WHERE id = ? AND proyecto = ?", (ref[5:], pid)).fetchone()
            if r is None:
                err.append({"donde": donde, "error": f"{ref} no existe en el proyecto"})
                return None, None
            return r["id"], r["tipo"]
        if ref not in tipos:
            err.append({"donde": donde, "error": f"id local desconocido: {ref}"})
            return None, None
        return ref, tipos[ref]

    con_salida: dict[str, set[str]] = {}  # id local -> relaciones que salen de el
    for i, v in enumerate(vinculos):
        donde = f"vinculos[{i}]"
        if not isinstance(v, dict):
            err.append({"donde": donde, "error": "cada vinculo es un objeto"})
            continue
        rel = v.get("relacion")
        if not isinstance(rel, str) or rel not in RELACIONES_DEL_FRENTE:
            err.append({"donde": donde, "error": f"relacion no declarable por un frente: {rel}"})
            continue
        de, tde = resolver(v.get("de"), donde)
        a, ta = resolver(v.get("a"), donde)
        if de is None or a is None:
            continue
        if de == a:
            err.append({"donde": donde, "error": "un nodo no se vincula consigo mismo"})
        tipos_de, tipos_a = RELACIONES[rel]
        if tde not in tipos_de or ta not in tipos_a:
            err.append({"donde": donde, "error": f"{rel} no admite {tde} -> {ta}"})
        if rel in CON_MOTIVO and not _campo(v, "motivo"):
            err.append({"donde": donde, "error": f"{rel} exige motivo"})
        if isinstance(v.get("de"), str) and not v["de"].startswith("nodo:"):
            con_salida.setdefault(v["de"], set()).add(rel)
    for lid, tipo in tipos.items():
        if tipo == "decision" and not con_salida.get(lid, set()) & {"elige", "descarta"}:
            err.append({"donde": f"nodo {lid}", "error": "una decision exige al menos un vinculo elige o descarta"})
        if tipo == "regla" and "derivada_de" not in con_salida.get(lid, set()):
            err.append({"donde": f"nodo {lid}", "error": "una regla exige derivada_de"})
    return (b if not err else None), err


def _sesion_del_encargo(con: sqlite3.Connection, encargo: str) -> str | None:
    r = con.execute(
        "SELECT a FROM vinculo WHERE de = ? AND relacion = 'ejecutado_por' AND activo = 1 ORDER BY fecha DESC LIMIT 1",
        (encargo,),
    ).fetchone()
    return r["a"] if r else None


def _incorporar_bloque(
    con: sqlite3.Connection, pid: str, informe: str, encargo: dict, texto: str, *, autor: str, origen: dict
) -> dict:
    """Valida el bloque y, si esta entero, crea sus nodos (estado inicial de su tipo, ronda del
    encargo, `declarado_en` el informe, hallazgos `encontrado_por` la sesion del encargo) y sus
    vinculos. Devuelve lo que se guarda en datos.conocimiento del informe: el mapa de ids locales a
    persistentes, o los errores. Idempotente por informe (clave declarado:<informe>:<id local>)."""
    bloque, errores = validar_bloque(con, pid, texto)
    if bloque is None:
        return {"estado": "pendiente_de_vincular", "errores": errores}
    sesion = _sesion_del_encargo(con, encargo["id"])
    ids: dict[str, str] = {}
    for nd in bloque["nodos"]:
        n = crear_nodo(
            pid,
            nd["tipo"],
            nd["texto"],
            nd["datos"],
            autor=autor,
            origen={**origen, "informe": informe, "local": nd["id"]},
            ronda=encargo["ronda"],
            clave_ingesta=f"declarado:{informe}:{nd['id']}",
            motivo="declarado en el informe",
            con=con,
        )
        ids[nd["id"]] = n["id"]
        vincular(pid, n["id"], "declarado_en", informe, autor=autor, origen=origen, con=con)
        if nd["tipo"] == "hallazgo" and sesion:
            vincular(pid, n["id"], "encontrado_por", sesion, autor=autor, origen=origen, con=con)

    def pers(ref: str) -> str:
        return ref[5:] if ref.startswith("nodo:") else ids[ref]

    hechos = 0
    for v in bloque.get("vinculos", []):
        vincular(
            pid, pers(v["de"]), v["relacion"], pers(v["a"]), autor=autor, origen=origen, motivo=v.get("motivo"), con=con
        )
        hechos += 1
    return {"estado": "incorporado", "ids": ids, "nodos": len(ids), "vinculos": hechos}


# --- adaptadores de lo que el server ya ve (mejor esfuerzo, nunca rompen al llamador) --------


def _proyecto_de_sesion(sid: str) -> str | None:
    """El proyecto de una sesion que trabajo un encargo, o None. Las que no estan en ninguna base se
    recuerdan (cache negativa): cada muerte o permiso denegado de una tarjeta comun abria todas las
    bases (code review 2026-10-08). encargo_enviado saca la sesion de esa cache al vincularla."""
    with _lock:
        pid = _sesion_proyecto.get(sid)
        if pid:
            return pid
        if sid in _sesion_sin_proyecto:
            return None
    for p in proyectos():
        try:
            with _abrir(p["id"]) as con:
                r = con.execute("SELECT 1 FROM nodo WHERE clave_ingesta = ?", (f"sesion:{sid}",)).fetchone()
        except Rechazo:
            continue
        if r is not None:
            with _lock:
                _sesion_proyecto[sid] = p["id"]
            return p["id"]
    with _lock:
        _sesion_sin_proyecto.add(sid)
    return None


def _ronda_de_sesion(con, pid, sid) -> str | None:
    r = con.execute(
        "SELECT e.ronda FROM nodo s JOIN vinculo v ON v.a = s.id AND v.relacion = 'ejecutado_por' AND v.activo = 1"
        " JOIN nodo e ON e.id = v.de WHERE s.clave_ingesta = ? ORDER BY e.fecha DESC LIMIT 1",
        (f"sesion:{sid}",),
    ).fetchone()
    return r[0] if r else None


def sesion_cerrada(sid: str) -> None:
    """La tarjeta murio o se cerro: el nodo sesion pasa a cerrada, si la sesion trabajo un encargo."""
    _estado_sesion(sid, "cerrada", "la sesion termino")


def sesion_viva(sid: str) -> None:
    """La tarjeta dada por muerta volvio (claude --resume conserva el session_id, o el barrido la
    encontro viva): el nodo sesion vuelve a viva (code review 2026-10-08)."""
    _estado_sesion(sid, "viva", "la sesion volvio")


def _estado_sesion(sid: str, estado: str, motivo: str) -> None:
    try:
        pid = _proyecto_de_sesion(sid)
        if not pid:
            return
        with _abrir(pid) as con:
            r = con.execute("SELECT id FROM nodo WHERE clave_ingesta = ?", (f"sesion:{sid}",)).fetchone()
        if r is not None:
            cambiar_estado(pid, r["id"], estado, por="server", motivo=motivo)
    except Exception as e:
        state.log(f"conocimiento: sesion {estado} {sid[:8]}: {e}")


_incidentes_vistos: set[str] = set()  # claves ya escritas (o sin proyecto) en este proceso (bajo _lock)


def visto(clave: str) -> bool:
    """Si un incidente con esa clave ya se trato en este proceso: el llamador se ahorra el hilo."""
    with _lock:
        return clave in _incidentes_vistos


def clave_permiso(sid: str, tool, motivo, detalle) -> str:
    """La misma denegacion llega dos veces (log de coda con `at`, transcripcion con `turno`): la clave
    sale de lo que no cambia entre las dos."""
    firma = hashlib.sha1(f"{tool}|{motivo}|{detalle or ''}".encode()).hexdigest()[:16]
    return f"incidente:permiso:{sid}:{firma}"


def incidente_operativo(
    sid: str, texto: str, *, herramienta: str, datos: dict | None = None, clave: str | None = None
) -> dict | None:
    """Un incidente que el server observo en una sesion que trabaja un encargo: permiso denegado,
    error de API, muerte con el encargo a medias (v5 §5.1). Queda `observado`, en la ronda del encargo,
    con la sesion como origen. Nada si la sesion no esta en ningun proyecto. Con `clave` es
    idempotente (clave_ingesta) y ademas no vuelve a abrir las bases por una clave ya tratada: el
    refresco de una tarjeta con un error de API repite el mismo turno cada vez. La clave se da por
    vista recien cuando el incidente quedo escrito (o la sesion no es de ningun proyecto): un fallo
    pasajero (base bloqueada) no lo pierde para siempre (code review 2026-10-08)."""
    try:
        if clave and visto(clave):
            return None
        pid = _proyecto_de_sesion(sid)
        if not pid:
            if clave:
                with _lock:
                    _incidentes_vistos.add(clave)
            return None
        with _abrir(pid) as con:
            ronda = _ronda_de_sesion(con, pid, sid)
            s = con.execute("SELECT datos FROM nodo WHERE clave_ingesta = ?", (f"sesion:{sid}",)).fetchone()
            sd = json.loads(s["datos"]) if s else {}
            d = {"herramienta": herramienta, "agente": sd.get("agente"), "modelo": sd.get("modelo"), **(datos or {})}
            d = {k: v for k, v in d.items() if v is not None}
            n = crear_nodo(
                pid,
                "incidente",
                texto,
                d,
                autor="server",
                origen={"session_id": sid},
                ronda=ronda,
                clave_ingesta=clave,
                motivo="incidente observado por el server",
                con=con,
            )
        if clave:
            with _lock:
                _incidentes_vistos.add(clave)
        return n
    except Exception as e:
        state.log(f"conocimiento: incidente de {sid[:8]}: {e}")
        return None


# --- consultas ------------------------------------------------------------------------------


def resumen(pid: str) -> dict:
    p = proyecto(pid)
    with _abrir(pid) as con:
        por_tipo = {}
        for r in con.execute(
            "SELECT tipo, estado, COUNT(*) AS n FROM nodo WHERE proyecto = ? GROUP BY tipo, estado", (pid,)
        ):
            por_tipo.setdefault(r["tipo"], {})[r["estado"] or "sin_estado"] = r["n"]
        rondas = [
            _fila(r)
            for r in con.execute("SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'ronda' ORDER BY fecha", (pid,))
        ]
        seq = con.execute("SELECT COALESCE(MAX(seq), 0) FROM cambio WHERE proyecto = ?", (pid,)).fetchone()[0]
    return {"proyecto": p, "nodos": por_tipo, "rondas": rondas, "ultimo_cambio": seq}


def nodos(
    pid: str,
    *,
    tipo: str | None = None,
    estado: str | None = None,
    ronda: str | None = None,
    limite: int = LIMITE_PAGINA,
    desde: int = 0,
) -> dict:
    cond, args = ["proyecto = ?"], [pid]
    if tipo:
        cond.append("tipo = ?")
        args.append(tipo)
    if estado:
        cond.append("estado = ?")
        args.append(estado)
    if ronda:
        cond.append("(ronda = ? OR id = ?)")
        args += [ronda, ronda]
    limite = max(1, min(int(limite), LIMITE_PAGINA))
    with _abrir(pid) as con:
        total = con.execute(f"SELECT COUNT(*) FROM nodo WHERE {' AND '.join(cond)}", args).fetchone()[0]
        filas = con.execute(
            f"SELECT * FROM nodo WHERE {' AND '.join(cond)} ORDER BY fecha, id LIMIT ? OFFSET ?",
            [*args, limite, max(0, int(desde))],
        ).fetchall()
    return {"total": total, "desde": desde, "nodos": [_fila(r) for r in filas]}


def nodo(pid: str, nid: str) -> dict:
    with _abrir(pid) as con:
        n = _nodo(con, pid, nid)
        salen = [_fila(r) for r in con.execute("SELECT * FROM vinculo WHERE de = ? AND activo = 1", (nid,))]
        entran = [_fila(r) for r in con.execute("SELECT * FROM vinculo WHERE a = ? AND activo = 1", (nid,))]
        cambios = [
            _fila(r)
            for r in con.execute(
                "SELECT * FROM cambio WHERE nodo_id = ? OR de = ? OR a = ? ORDER BY seq", (nid, nid, nid)
            )
        ]
    return {**n, "vinculos": {"salen": salen, "entran": entran}, "cambios": cambios}


def buscar(pid: str, consulta: str, *, tipo: str | None = None, limite: int = LIMITE_BUSQUEDA) -> list[dict]:
    """BM25 de FTS5 (v5 §7.1): `texto` pesa 3 y `datos` 1; menor puntaje primero. La consulta llega como
    parametro y una sintaxis invalida de FTS es un 400, no un 500."""
    consulta = _texto(consulta, "consulta", 500)
    limite = max(1, min(int(limite), LIMITE_PAGINA))
    cond, args = ["n.proyecto = ?"], [pid]
    if tipo:
        cond.append("n.tipo = ?")
        args.append(tipo)
    with _abrir(pid) as con:
        try:
            filas = con.execute(
                "SELECT n.*, bm25(nodo_fts, 3.0, 1.0) AS puntaje FROM nodo_fts JOIN nodo n ON n.rowid = nodo_fts.rowid"
                f" WHERE nodo_fts MATCH ? AND {' AND '.join(cond)} ORDER BY puntaje, n.id LIMIT ?",
                [consulta, *args, limite],
            ).fetchall()
        except sqlite3.OperationalError as e:
            raise Rechazo(f"consulta FTS invalida: {e}") from e
    return [_fila(r) for r in filas]


_RELACIONES_EXPANSION = (
    "motivada_por",
    "elige",
    "descarta",
    "reemplaza",
    "confirmado_por",
    "mismo_que",
    "corregido_en",
    "repite",
    "derivada_de",
    "aplica_a",
    "sobre",
    "apoya",
    "contesta",
    "declarado_en",
    "encontrado_por",
)
_NO_PUENTE = ("tema", "informe", "sesion")  # contexto: se devuelven, no expanden su vecindario


def expandir(pid: str, semillas: list[str], *, saltos: int = SALTOS_MAX) -> list[dict]:
    """Los vecinos a `saltos` pasos de las semillas, en las dos direcciones (v5 §8.5, consulta 5).
    Cada nodo trae `salto` (0 las semillas) y los vinculos activos que lo conectan."""
    semillas = [s for s in semillas if isinstance(s, str)][:LIMITE_BUSQUEDA]
    saltos = max(0, min(int(saltos), SALTOS_MAX))
    if not semillas:
        return []
    # las dos listas son constantes del modulo (nombres sin comillas), no entrada del cliente
    relaciones = ",".join(f"'{r}'" for r in _RELACIONES_EXPANSION)
    no_puente = ",".join(f"'{t}'" for t in _NO_PUENTE)
    sql = f"""
WITH RECURSIVE
aristas(de, a) AS (
  SELECT v.de, v.a FROM vinculo v JOIN nodo x ON x.id = v.de JOIN nodo y ON y.id = v.a
  WHERE v.activo = 1 AND x.proyecto = :p AND y.proyecto = :p AND v.relacion IN ({relaciones})
),
adyacentes(de, a) AS (SELECT de, a FROM aristas UNION SELECT a, de FROM aristas),
recorrido(id, salto) AS (
  SELECT n.id, 0 FROM json_each(:semillas) j JOIN nodo n ON n.id = j.value WHERE n.proyecto = :p
  UNION
  SELECT ad.a, r.salto + 1 FROM recorrido r JOIN nodo n ON n.id = r.id JOIN adyacentes ad ON ad.de = r.id
  WHERE r.salto < :saltos AND n.tipo NOT IN ({no_puente})
)
SELECT n.*, MIN(r.salto) AS salto FROM recorrido r JOIN nodo n ON n.id = r.id GROUP BY n.id ORDER BY salto, n.id
"""
    with _abrir(pid) as con:
        filas = con.execute(sql, {"p": pid, "semillas": json.dumps(semillas), "saltos": saltos}).fetchall()
        ids = [r["id"] for r in filas]
        vinculos = []
        if ids:
            q = ",".join("?" * len(ids))
            vinculos = [
                _fila(r)
                for r in con.execute(
                    f"SELECT * FROM vinculo WHERE activo = 1 AND de IN ({q}) AND a IN ({q})", [*ids, *ids]
                )
            ]
    out = [_fila(r) for r in filas]
    for n in out:
        n["vinculos"] = [v for v in vinculos if n["id"] in (v["de"], v["a"])]
    return out


def cambios(pid: str, *, desde: int = 0, limite: int = LIMITE_PAGINA) -> list[dict]:
    limite = max(1, min(int(limite), 500))
    with _abrir(pid) as con:
        return [
            _fila(r)
            for r in con.execute(
                "SELECT * FROM cambio WHERE proyecto = ? AND seq > ? ORDER BY seq LIMIT ?", (pid, int(desde), limite)
            )
        ]


def leer_cuerpo(pid: str, ruta: str) -> str:
    """Un encargo o informe guardado, por su ruta relativa (`datos.ruta`). Solo dentro de la carpeta
    del proyecto."""
    base = os.path.realpath(_carpeta(pid))
    full = os.path.realpath(os.path.join(base, ruta))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        raise Rechazo("cuerpo desconocido", 404)
    with open(full, encoding="utf-8") as f:
        return f.read()
