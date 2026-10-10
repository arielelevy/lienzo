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
import transcripts
from atomico import atomic_write

VERSION_ESQUEMA = 3  # 2: captura e indice de prosa; 3: origen de cada cambio y tablas de replica (anexo C)
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
  fecha TEXT NOT NULL,
  pc TEXT,
  seq_origen INTEGER
);
-- version 3 (anexo C): pc es la PC donde se origino el cambio y seq_origen su seq alla; el par
-- identifica el cambio en todas las PCs. Sin comentarios dentro del CREATE TABLE: rompen ALTER TABLE
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
-- version 2: lo que pasa por el lienzo queda sin registrarlo a mano (anexo A de v5). Un registro
-- inmutable aparte de los nodos: no entra al BM25 de nodos ni a los cambios del briefing
CREATE TABLE IF NOT EXISTS captura (
  id TEXT PRIMARY KEY,
  proyecto TEXT NOT NULL REFERENCES proyecto(id),
  clase TEXT NOT NULL CHECK (clase IN ('pedido','respuesta','envio','regla')),
  estado TEXT NOT NULL DEFAULT 'observado' CHECK (estado = 'observado'),
  session_id TEXT NOT NULL,
  sesion TEXT REFERENCES nodo(id),
  agente TEXT,
  modelo TEXT,
  pc TEXT,
  origen TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(origen)),
  texto TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  hash TEXT NOT NULL,
  recortado INTEGER NOT NULL DEFAULT 0,
  redactado INTEGER NOT NULL DEFAULT 0,
  fecha TEXT NOT NULL,
  clave_ingesta TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS captura_sesion ON captura(session_id, fecha);
CREATE INDEX IF NOT EXISTS captura_fecha ON captura(proyecto, fecha);
CREATE VIRTUAL TABLE IF NOT EXISTS captura_fts USING fts5(
  texto, content='captura', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS captura_ai AFTER INSERT ON captura BEGIN
  INSERT INTO captura_fts(rowid, texto) VALUES (new.rowid, new.texto);
END;
CREATE TRIGGER IF NOT EXISTS captura_ad AFTER DELETE ON captura BEGIN
  INSERT INTO captura_fts(captura_fts, rowid, texto) VALUES ('delete', old.rowid, old.texto);
END;
CREATE TRIGGER IF NOT EXISTS captura_inmutable BEFORE UPDATE ON captura BEGIN
  SELECT RAISE(ABORT, 'una captura no se modifica');
END;
-- la prosa de encargos e informes, aparte del BM25 de nodos (lo que se escribio, no lo declarado)
CREATE VIRTUAL TABLE IF NOT EXISTS prosa_fts USING fts5(
  nodo UNINDEXED, texto, tokenize='unicode61 remove_diacritics 2'
);
-- version 3: replica entre PCs (anexo C de v5). Cursores por par, choques y duplicados para la
-- coordinadora, y cambios que esperan a otro (un vinculo cuyo nodo todavia no llego)
CREATE TABLE IF NOT EXISTS replica_cursor (
  peer TEXT NOT NULL,
  proyecto_remoto TEXT NOT NULL,
  clase TEXT NOT NULL CHECK (clase IN ('cambio','captura')),
  ultimo INTEGER NOT NULL DEFAULT 0,
  fecha TEXT NOT NULL,
  PRIMARY KEY (peer, proyecto_remoto, clase)
);
CREATE TABLE IF NOT EXISTS replica_conflicto (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nodo TEXT NOT NULL,
  pc TEXT NOT NULL,
  seq_origen INTEGER NOT NULL,
  motivo TEXT NOT NULL,
  fecha TEXT NOT NULL,
  UNIQUE (pc, seq_origen)
);
CREATE TABLE IF NOT EXISTS replica_duplicado (
  nodo_local TEXT NOT NULL,
  nodo_remoto TEXT NOT NULL,
  clave TEXT NOT NULL,
  fecha TEXT NOT NULL,
  PRIMARY KEY (nodo_local, nodo_remoto)
);
CREATE TABLE IF NOT EXISTS replica_pendiente (
  pc TEXT NOT NULL,
  seq_origen INTEGER NOT NULL,
  cambio TEXT NOT NULL CHECK (json_valid(cambio)),
  error TEXT NOT NULL,
  fecha TEXT NOT NULL,
  PRIMARY KEY (pc, seq_origen)
);
"""
# despues de que exista la columna (en una base vieja, despues del ALTER)
ESQUEMA_3 = """
CREATE UNIQUE INDEX IF NOT EXISTS cambio_origen ON cambio(pc, seq_origen);
CREATE INDEX IF NOT EXISTS cambio_nodo ON cambio(nodo_id, fecha);
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


# --- texto roto (U+FFFD y mojibake) ----------------------------------------------------------------

_ROTO = re.compile("�|" + transcripts._MOJIBAKE_RE.pattern + "+")
ROTO_MAX = 5  # marcas que se informan por texto; las demas se cuentan


def texto_roto(texto) -> list[dict]:
    """Las marcas de texto roto de `texto`: `reemplazo` (U+FFFD: el caracter original se perdio al
    decodificar, no se puede recuperar) o `mojibake` (UTF-8 leido como Windows-1252: «ó» quedo «Ã³»;
    `transcripts.reparar_mojibake` lo recupera). Cada una con posicion, linea y columna (desde 1).
    Vacio si el texto esta sano o no es texto."""
    if not isinstance(texto, str):
        return []
    out = []
    for m in _ROTO.finditer(texto):
        antes = texto[: m.start()]
        linea = antes.count("\n") + 1
        columna = m.start() - (antes.rfind("\n") + 1) + 1
        if m.group() == "�":
            out.append({"clase": "reemplazo", "pos": m.start(), "linea": linea, "columna": columna})
        else:
            reparado = transcripts.reparar_mojibake(m.group())
            out.append(
                {
                    "clase": "mojibake",
                    "pos": m.start(),
                    "linea": linea,
                    "columna": columna,
                    "muestra": m.group(),
                    "reparado": reparado if reparado != m.group() else None,
                }
            )
    return out


def describir_roto(marcas: list[dict]) -> str:
    """Las marcas en una frase para el error: sin repetir el caracter de reemplazo, que se volveria a
    copiar donde se lea el error."""
    partes = []
    for x in marcas[:ROTO_MAX]:
        donde = f"linea {x['linea']}, columna {x['columna']}"
        if x["clase"] == "reemplazo":
            partes.append(f"U+FFFD (caracter perdido al decodificar) en {donde}")
        else:
            quiso = f" (quiso decir «{x['reparado']}»)" if x.get("reparado") else ""
            partes.append(f"mojibake de UTF-8 leido como Windows-1252 «{x['muestra']}»{quiso} en {donde}")
    if len(marcas) > ROTO_MAX:
        partes.append(f"y {len(marcas) - ROTO_MAX} marca(s) mas")
    return "texto roto: " + "; ".join(partes) + ". Mandalo en UTF-8 sin decodificar de nuevo"


_MOJIBAKE_RACHA = re.compile(transcripts._MOJIBAKE_RE.pattern + "+")


def reparar_segmentos(texto: str) -> str:
    """Repara cada racha de mojibake por separado (`transcripts.reparar_mojibake` es todo o nada sobre
    el texto entero y no repara uno que ademas tenga, por ejemplo, una flecha). Una racha que no vuelve
    a ser UTF-8 valido queda como estaba."""
    if not isinstance(texto, str):
        return texto
    return _MOJIBAKE_RACHA.sub(lambda m: transcripts.reparar_mojibake(m.group()), texto)


def _reparar_en(x):
    if isinstance(x, str):
        return reparar_segmentos(x)
    if isinstance(x, dict):
        return {kk: _reparar_en(v) for kk, v in x.items()}
    if isinstance(x, list):
        return [_reparar_en(v) for v in x]
    return x


def _textos_de(x, camino: str):
    """(camino, texto) de cada cadena dentro de `x` (dicts y listas anidados)."""
    if isinstance(x, str):
        yield camino, x
    elif isinstance(x, dict):
        for kk, v in x.items():
            yield from _textos_de(v, f"{camino}.{kk}" if camino else str(kk))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _textos_de(v, f"{camino}[{i}]")


def roto_en(campos: dict) -> list[str]:
    """Los errores de texto roto de varios campos (`{"texto": ..., "datos": {...}}`), uno por campo."""
    err = []
    for camino, s in _textos_de(campos, ""):
        marcas = texto_roto(s)
        if marcas:
            err.append(f"{camino}: {describir_roto(marcas)}")
    return err


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
    """El proyecto de una tarjeta, por carpeta en esa PC (el cwd o la raiz del repo que lo contiene:
    anexo A de v5, proyecto = carpeta) o, si ninguna carpeta coincide, por remote (repo_key
    normalizado). None si no esta asignado: las coincidencias por nombre solo sugieren (v5 §8.1)."""
    rk = (repo_key or "").strip().lower()
    candidatas = {x for x in (norm_cwd(cwd), norm_cwd(carpeta_de(cwd))) if x}
    with _lock:
        idx = _leer_indice()
    for pid, v in idx["proyectos"].items():
        if any(x.get("cwd") in candidatas and (not pc or x.get("pc") in ("", pc)) for x in (v.get("carpetas") or [])):
            return pid
    for pid, v in idx["proyectos"].items():
        if rk and rk in (v.get("remotes") or []):
            return pid
    return None


def carpeta_de(cwd: str | None) -> str | None:
    """La carpeta que identifica al proyecto de un cwd (anexo A de v5: proyecto = carpeta): la raiz
    del repo Git que lo contiene, y para un worktree la del repo principal (el que tiene el `.git`
    comun, porque un worktree es el mismo proyecto en paralelo). Sin repo, el cwd. None sin cwd."""
    if not cwd or not str(cwd).strip():
        return None
    try:
        found = identity._find_repo_root(cwd)
    except OSError:
        found = None
    if found is None:
        return os.path.abspath(cwd)
    root, git_dir = found
    if os.path.basename(os.path.normpath(git_dir)).lower() == ".git":
        return os.path.dirname(os.path.normpath(git_dir))
    return root


def _slug(nombre: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (nombre or "").lower()).strip("-._")
    return s[:56] or "carpeta"


def proyecto_de_carpeta(cwd: str | None, pc: str, remote: str | None = None) -> str | None:
    """El proyecto de una carpeta en la PC `pc`, creandolo si nadie lo tiene (anexo A de v5: lo que pasa
    por el lienzo se registra solo). Orden: (1) la carpeta ya es de un proyecto en esta PC; (2) el
    `remote` es de un proyecto que todavia no tiene carpeta en esta PC: es la misma carpeta en otra PC
    y se le suma como alias; (3) proyecto nuevo con el nombre de la carpeta (`-2`, `-3` si ya existe),
    con el remote como alias si nadie lo tiene. Dos carpetas de la misma PC nunca se juntan por el
    remote. None sin cwd."""
    carpeta = carpeta_de(cwd)
    if carpeta is None:
        return None
    c = norm_cwd(carpeta)
    rk = (remote or "").strip().lower() or None
    with _lock:
        idx = _leer_indice()["proyectos"]
        for pid, v in idx.items():
            if any(x.get("cwd") == c and x.get("pc") in ("", pc) for x in (v.get("carpetas") or [])):
                return pid
        if rk:
            for pid, v in idx.items():
                if rk in (v.get("remotes") or []) and not any(
                    x.get("pc") in ("", pc) for x in (v.get("carpetas") or [])
                ):
                    registrar_proyecto(pid, carpetas=[{"pc": pc, "cwd": c}])
                    return pid
        base = _slug(os.path.basename(carpeta.rstrip("\\/")))
        pid, i = base, 2
        while pid in idx or os.path.exists(_carpeta(pid)):
            pid, i = f"{base}-{i}", i + 1
        libre = rk and not any(rk in (v.get("remotes") or []) for v in idx.values())
        registrar_proyecto(
            pid, os.path.basename(carpeta.rstrip("\\/")) or pid, [rk] if libre else [], [{"pc": pc, "cwd": c}]
        )
        state.log(f"conocimiento: proyecto {pid} creado solo para la carpeta {c} (pc {pc})")
        return pid


# --- base por proyecto ----------------------------------------------------------------------


class _Conexion:
    """Una conexion por operacion, con transaccion: `with _abrir(pid) as con:` confirma al salir sin
    excepcion y revierte si la hubo. Sin conexiones compartidas entre hilos."""

    def __init__(self, path: str):
        self.path = path

    def __enter__(self) -> sqlite3.Connection:
        # el esquema se decide por user_version, no por si el archivo existia: connect lo crea antes
        # de que corra el esquema, y un fallo a mitad dejaria una base vacia que nadie repararia
        _migrar(self.path)
        self.con = sqlite3.connect(self.path, timeout=10, isolation_level="DEFERRED")
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        return self.con

    def __exit__(self, et, ev, tb):
        if et is None:
            self.con.commit()
        else:
            self.con.rollback()
        self.con.close()
        return False


_lock_migracion = threading.Lock()


def _sentencias(script: str):
    """Las sentencias de un script, una por una: un trigger lleva `;` adentro de BEGIN ... END y
    `sqlite3.complete_statement` sabe cuando termina."""
    buf = ""
    for linea in script.splitlines(keepends=True):
        if not buf and (not linea.strip() or linea.lstrip().startswith("--")):
            continue
        buf += linea
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""


def _migrar(path: str) -> None:
    """Lleva la base a VERSION_ESQUEMA de una sola vez, o no la toca. `executescript` hacia COMMIT
    entre sentencias y dos aperturas a la vez (el hilo de captura, el barrido y el panel al arrancar)
    duplicaban la prosa o chocaban con «duplicate column» (code review 2026-10-09). Ahora: un lock por
    proceso, BEGIN IMMEDIATE entre procesos, user_version releido adentro, cada sentencia con execute
    y el numero de version en la misma transaccion."""
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        al_dia = con.execute("PRAGMA user_version").fetchone()[0] >= VERSION_ESQUEMA  # lectura, sin lock
    finally:
        con.close()
    if al_dia:
        return
    with _lock_migracion:
        con = sqlite3.connect(path, timeout=30, isolation_level=None)
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("BEGIN IMMEDIATE")
            try:
                version = con.execute("PRAGMA user_version").fetchone()[0]
                if version < VERSION_ESQUEMA:
                    for sentencia in _sentencias(ESQUEMA):
                        con.execute(sentencia)
                    if 1 <= version < 3:
                        # de 2 a 3: cada cambio viejo es de esta PC, con su seq como seq de origen
                        columnas = {r[1] for r in con.execute("PRAGMA table_info(cambio)")}
                        for col, tipo in (("pc", "TEXT"), ("seq_origen", "INTEGER")):
                            if col not in columnas:
                                con.execute(f"ALTER TABLE cambio ADD COLUMN {col} {tipo}")
                        con.execute("UPDATE cambio SET pc = ?, seq_origen = seq WHERE pc IS NULL", (identity.pc_id(),))
                    if version == 1:
                        # de 1 a 2: los cuerpos ya guardados entran al indice de prosa
                        _rellenar_prosa(con, os.path.dirname(path))
                    for sentencia in _sentencias(ESQUEMA_3):
                        con.execute(sentencia)
                    con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()


def _leer_archivo(full: str) -> str | None:
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _rellenar_prosa(con: sqlite3.Connection, carpeta: str) -> int:
    """Indexa los cuerpos de encargos e informes que ya estaban guardados (migracion 1 -> 2). Un
    cuerpo que falta en disco no frena la migracion: queda fuera del indice."""
    n = 0
    for r in con.execute("SELECT id, datos FROM nodo WHERE tipo IN ('encargo','informe')").fetchall():
        ruta = json.loads(r[1]).get("ruta")
        if not isinstance(ruta, str):
            continue
        texto = _leer_archivo(os.path.join(carpeta, *ruta.split("/")))
        if texto:
            con.execute("INSERT INTO prosa_fts (nodo, texto) VALUES (?, ?)", (r[0], texto))
            n += 1
    return n


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


def _despues_de(fecha: str) -> str:
    """`fecha` mas un milisegundo, en el mismo formato de `ahora()`."""
    d = dt.datetime.fromisoformat(fecha) + dt.timedelta(milliseconds=1)
    return d.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fecha_causal(con, nodo_id, de, relacion, a) -> str:
    """La fecha de un cambio local: la hora de ahora, pero nunca antes que el ultimo cambio que esta PC
    ya conoce de ese nodo o vinculo (un reloj hibrido). La replica decide el ultimo que escribe por
    fecha: con el reloj de otra PC adelantado, una edicion hecha despues de ver la de alla perdia y las
    dos PCs quedaban distintas para siempre (encargo B, code review 2026-10-09)."""
    fecha = ahora()
    if nodo_id:
        r = con.execute("SELECT MAX(fecha) FROM cambio WHERE nodo_id = ?", (nodo_id,)).fetchone()
    elif de and a:
        r = con.execute(
            "SELECT MAX(fecha) FROM cambio WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)
        ).fetchone()
    else:
        r = None
    if r and r[0] and r[0] >= fecha:
        fecha = _despues_de(r[0])
    return fecha


def _cambio(
    con, pid, accion, autor, motivo, origen, nuevo, anterior=None, nodo_id=None, de=None, relacion=None, a=None
):
    cur = con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, de, relacion, a, accion, anterior, nuevo, autor, motivo, origen, fecha, pc)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            _fecha_causal(con, nodo_id, de, relacion, a),
            identity.pc_id(),
        ),
    )
    # un cambio de esta PC: su seq de origen es su seq (la replica lo trae a las demas por ese par)
    con.execute("UPDATE cambio SET seq_origen = seq WHERE seq = ?", (cur.lastrowid,))


def id_de_sesion(sid: str) -> str:
    """El id del nodo `sesion` sale del session_id, igual en todas las PCs: si la PC del coordinador y la
    de la sesion la registran las dos, la replica las junta en un nodo (anexo C) en vez de duplicarla."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"lienzo:sesion:{sid}").hex


def declarar_nodo(pid: str, tipo, texto, datos, *, autor: str, origen=None, ronda=None, motivo: str = "") -> dict:
    """Un nodo declarado a mano (POST /nodos): solo tipos de conocimiento (de hallazgo a evidencia) y
    con los mismos campos obligatorios que exige el bloque del informe. Ronda, encargo, sesion e
    informe los crea el server por sus propias operaciones."""
    if not isinstance(tipo, str) or tipo not in DECLARABLES:
        raise Rechazo(f"tipo no declarable: {tipo}")
    faltan = _faltan_datos(tipo, _objeto(datos, "datos")) + roto_en({"texto": texto, "datos": datos})
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
    nid: str | None = None,
) -> dict:
    """Un nodo nuevo con el estado inicial de su tipo. Con `clave_ingesta` es idempotente: si ya
    existe, devuelve el existente (`creado: False`). `nid` fija el id (sesiones: `id_de_sesion`)."""
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
                nid=nid,
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
    nid = nid or nuevo_id()
    # ON CONFLICT: dos escritores con la misma clave a la vez (la captura y encargo_enviado crean la
    # misma sesion) pasaban los dos el SELECT de arriba y el segundo moria en UNIQUE (code review)
    cur = con.execute(
        "INSERT INTO nodo (id, proyecto, tipo, texto, datos, estado, estado_fecha, estado_por, autor, origen, ronda,"
        " fecha, clave_ingesta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (clave_ingesta) DO NOTHING",
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
    if cur.rowcount == 0:
        r = con.execute("SELECT * FROM nodo WHERE clave_ingesta = ?", (clave_ingesta,)).fetchone()
        return {**_fila(r), "creado": False}
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
    diferir_respaldo: bool = False,
) -> dict:
    """Aplica una transicion de v5 §3.4 o la rechaza (409). Idempotente si ya esta en `nuevo`. Una
    regla que pasa a vigente recibe `datos.vigente_desde` (abre un periodo nuevo, §6.2), venga del
    veredicto o de esta ruta. Las transiciones «con respaldo» (RESPALDO) exigen el suyo; un veredicto
    las difiere (`diferir_respaldo`) y las mira al final, para que el vinculo pueda venir en otro item."""
    por = _texto(por, "por", 200)
    origen = _objeto(origen, "origen")
    if con is None:
        with _abrir(pid) as c2:
            return cambiar_estado(
                pid, nid, nuevo, por=por, motivo=motivo, origen=origen, con=c2, diferir_respaldo=diferir_respaldo
            )
    n = _nodo(con, pid, nid)
    actual = n.get("estado")
    if actual == nuevo:
        return n
    permitidos = TRANSICIONES.get(n["tipo"], {}).get((actual, nuevo))
    if not permitidos:
        raise Rechazo(f"transicion no permitida para {n['tipo']}: {actual} -> {nuevo}", 409)
    if rol_de(por) not in permitidos:
        raise Rechazo(f"{rol_de(por) or '?'} no puede pasar {n['tipo']} de {actual} a {nuevo}", 403)
    if not diferir_respaldo and (falta := falta_respaldo(con, nid, n["tipo"], nuevo, origen)):
        raise Rechazo(falta, 409)
    fecha = ahora()
    con.execute("UPDATE nodo SET estado = ?, estado_fecha = ?, estado_por = ? WHERE id = ?", (nuevo, fecha, por, nid))
    if n["tipo"] == "regla" and nuevo == "vigente":
        con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json({**n["datos"], "vigente_desde": fecha}), nid))
    n2 = _nodo(con, pid, nid)
    _cambio(con, pid, "estado", por, motivo, origen, n2, anterior=n, nodo_id=nid)
    return n2


# (tipo, estado nuevo) -> el respaldo que exige (v5 §3.4): corregir o resolver con una correccion
# respaldada (vinculo corregido_en, o evidencia citada en el veredicto), contestar con `contesta`,
# reemplazar o superar con la sucesora (`reemplaza` que llega)
RESPALDO = {
    ("hallazgo", "corregido"): "corregido_en",
    ("incidente", "resuelto"): "corregido_en",
    ("pregunta", "contestada"): "contesta",
    ("decision", "reemplazada"): "reemplaza",
    ("medicion", "superada"): "reemplaza",
}


def falta_respaldo(con: sqlite3.Connection, nid: str, tipo: str, nuevo: str, origen: dict | None) -> str | None:
    """El error si la transicion a `nuevo` exige un respaldo que no esta, o None."""
    rel = RESPALDO.get((tipo, nuevo))
    if rel is None:
        return None
    if rel == "corregido_en":
        if (origen or {}).get("evidencia"):
            return None
        q, que = (
            "SELECT 1 FROM vinculo WHERE de = ? AND relacion = 'corregido_en' AND activo = 1",
            "corregido_en a una evidencia, o evidencia en el veredicto",
        )
    elif rel == "contesta":
        q, que = (
            "SELECT 1 FROM vinculo WHERE a = ? AND relacion = 'contesta' AND activo = 1",
            "un vinculo contesta que llegue",
        )
    else:
        q, que = (
            "SELECT 1 FROM vinculo WHERE a = ? AND relacion = 'reemplaza' AND activo = 1",
            "la sucesora (reemplaza que llegue)",
        )
    if con.execute(q, (nid,)).fetchone() is None:
        return f"{tipo} {nuevo} exige {que} (v5 §3.4)"
    return None


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
        _escribir_cuerpo(
            pid, ruta, texto, con=con, nodo=n["id"]
        )  # antes del commit: si el disco falla, el nodo no queda
    return n


def escribir_exacto(full: str, datos: bytes) -> None:
    """Escribe `datos` en un .tmp y lo cambia por `full` de un saque, sin traducir fines de linea."""
    tmp = f"{full}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(datos)
        os.replace(tmp, full)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _escribir_cuerpo(pid: str, ruta: str, cuerpo: str, *, con: sqlite3.Connection, nodo: str) -> None:
    """El cuerpo tal cual, byte por byte: el hash del nodo es el de estos bytes. `atomic_write` abre
    en modo texto y en Windows cada \\n quedaba \\r\\n, asi que ningun informe guardado hasta el
    2026-10-09 verificaba su hash contra el archivo (medido: 5 de 5). Tambien entra al indice de prosa,
    en la transaccion del nodo."""
    full = os.path.join(_carpeta(pid), *ruta.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    escribir_exacto(full, cuerpo.encode("utf-8"))
    con.execute("INSERT INTO prosa_fts (nodo, texto) VALUES (?, ?)", (nodo, cuerpo))


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
        nid=id_de_sesion(sid),
    )
    if not n["creado"] and any(v is not None and n["datos"].get(k) != v for k, v in datos.items()):
        # cada mutacion deja su cambio (v5 §8.4): el modelo o el cwd de la sesion cambiaron
        anterior = n
        con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json({**n["datos"], **datos}), n["id"]))
        n = _nodo(con, pid, n["id"])
        _cambio(
            con, pid, "datos", autor, "sesion observada", {"session_id": sid}, n, anterior=anterior, nodo_id=n["id"]
        )
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
    if marcas := texto_roto(cuerpo):
        raise Rechazo(f"cuerpo: {describir_roto(marcas)}")
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
        if (ya := _informe_por_hash(con, pid, sha, encargo)) is not None:
            # el mismo contenido ya entro: como otra revision de este encargo (idempotente por
            # contenido), o capturado solo al cerrar el turno del frente sin encargo (se adopta)
            n = _adoptar(con, pid, ya, e, revision, autor=autor, origen=origen)
        else:
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
            n = _con_bloque(con, pid, n, cuerpo, ronda=e["ronda"], encargo=e["id"], autor=autor, origen=origen)
            _escribir_cuerpo(pid, ruta, cuerpo, con=con, nodo=n["id"])  # antes del commit, como en crear_encargo
    if (n["creado"] or n.get("adoptado")) and e["estado"] == "enviado":
        cambiar_estado(pid, encargo, "entregado", por="server", motivo=f"informe r{revision}")
    elif (n["creado"] or n.get("adoptado")) and e["estado"] == "sin_entrega" and rol_de(autor) in (C, P):
        # entrega tardia explicita (v5 §3.4): sin_entrega -> entregado, por quien entrega
        cambiar_estado(pid, encargo, "entregado", por=autor, motivo=f"entrega tardia r{revision}")
    return n


def _informe_por_hash(con: sqlite3.Connection, pid: str, sha: str, encargo: str) -> dict | None:
    """Un informe con ese contenido que ya responde a `encargo`, o uno capturado que no responde a
    ninguno. None si no hay."""
    for r in con.execute(
        "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'informe' AND json_extract(datos, '$.hash') = ?"
        " ORDER BY fecha, id",
        (pid, sha),
    ).fetchall():
        destinos = {
            x[0]
            for x in con.execute(
                "SELECT a FROM vinculo WHERE de = ? AND relacion = 'responde_a' AND activo = 1", (r["id"],)
            )
        }
        if encargo in destinos or not destinos:
            return _fila(r)
    return None


def _adoptar(con, pid: str, informe: dict, encargo: dict, revision: int, *, autor: str, origen: dict) -> dict:
    """Un informe capturado (sin encargo) pasa a responder a `encargo`: vinculo, revision y ronda. Su
    bloque ya se incorporo al capturarlo y no se repite. Si ya respondia a este encargo, se devuelve."""
    ya = con.execute(
        "SELECT 1 FROM vinculo WHERE de = ? AND relacion = 'responde_a' AND a = ? AND activo = 1",
        (informe["id"], encargo["id"]),
    ).fetchone()
    if ya is not None:
        return {**informe, "creado": False}
    vincular(pid, informe["id"], "responde_a", encargo["id"], autor=autor, origen=origen, con=con)
    datos = {**informe["datos"], "revision": revision, "capturado": True}
    con.execute(
        "UPDATE nodo SET datos = ?, ronda = COALESCE(ronda, ?) WHERE id = ?",
        (_json(datos), encargo["ronda"], informe["id"]),
    )
    n2 = _nodo(con, pid, informe["id"])
    _cambio(
        con,
        pid,
        "adopcion",
        autor,
        f"responde al encargo {encargo['id']}",
        origen,
        n2,
        anterior=informe,
        nodo_id=n2["id"],
    )
    return {**n2, "creado": False, "adoptado": True}


def _con_bloque(con, pid: str, n: dict, cuerpo: str, *, ronda, encargo, autor: str, origen: dict) -> dict:
    """Incorpora el bloque ```conocimiento``` del cuerpo al informe recien creado `n`, si lo trae."""
    bloque = extraer_bloque(cuerpo)
    if bloque is None:
        return n
    # v5 §5.2: todo o nada, en la misma transaccion que el informe. Con errores el informe
    # queda igual y el bloque «pendiente de vincular», con los errores por posicion
    sesion = _sesion_del_encargo(con, encargo) if encargo else origen.get("sesion_nodo")
    res = _incorporar_bloque(con, pid, n["id"], ronda, sesion, bloque, autor=autor, origen=origen)
    datos = {**n["datos"], "conocimiento": res}
    con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json(datos), n["id"]))
    n2 = _nodo(con, pid, n["id"])
    _cambio(con, pid, "conocimiento", autor, res["estado"], origen, n2, anterior=n, nodo_id=n["id"])
    return {**n2, "creado": True}


def informe_capturado(pid: str, sid: str, cuerpo: str, *, ronda: str | None, origen: dict) -> dict | None:
    """La respuesta final de una sesion trae un bloque ```conocimiento```: es un informe aunque nadie
    lo entregue (anexo A de v5). Queda `recibido` en capturas/, con su bloque incorporado igual que en
    una entrega (o pendiente con sus errores). Si la sesion trabaja un unico encargo `enviado`, se
    entrega a ese encargo como su revision siguiente; si no, queda sin encargo hasta que una entrega
    explicita con el mismo contenido lo adopte. Idempotente por (sesion, hash). None si el cuerpo
    tiene texto roto: no se guarda un informe que la entrega explicita rechazaria."""
    if texto_roto(cuerpo):
        return None
    sha = hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()
    with _abrir(pid) as con:
        # la coordinadora pudo entregarlo a mano antes de que la cola de captura llegara: es el mismo
        # informe, no otro con su bloque repetido (code review 2026-10-09)
        ya = con.execute(
            "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'informe' AND json_extract(datos, '$.hash') = ?"
            " ORDER BY fecha, id LIMIT 1",
            (pid, sha),
        ).fetchone()
        if ya is not None:
            return {**_fila(ya), "creado": False}
        s = con.execute("SELECT id FROM nodo WHERE clave_ingesta = ?", (f"sesion:{sid}",)).fetchone()
        encargos = [
            _fila(r)
            for r in con.execute(
                "SELECT e.* FROM nodo e JOIN vinculo v ON v.de = e.id AND v.relacion = 'ejecutado_por' AND v.activo = 1"
                " JOIN nodo x ON x.id = v.a WHERE x.clave_ingesta = ? AND e.tipo = 'encargo' AND e.estado = 'enviado'",
                (f"sesion:{sid}",),
            )
        ]
    if len(encargos) == 1:
        e = encargos[0]
        with _abrir(pid) as con:
            hechas = con.execute(
                "SELECT COUNT(*) FROM vinculo WHERE a = ? AND relacion = 'responde_a' AND activo = 1", (e["id"],)
            ).fetchone()[0]
        return entregar(pid, e["id"], cuerpo, revision=hechas + 1, autor="server", origen=origen)
    origen = {**origen, "session_id": sid, "sesion_nodo": s["id"] if s else None}
    ruta = f"capturas/informe-{sha[:16]}.md"
    with _abrir(pid) as con:
        n = crear_nodo(
            pid,
            "informe",
            f"informe capturado {sid[:8]}",
            {"ruta": ruta, "hash": sha, "bytes": len(cuerpo.encode("utf-8")), "capturado": True},
            autor="server",
            origen=origen,
            ronda=ronda,
            clave_ingesta=f"informe:captura:{sid}:{sha}",
            motivo="respuesta final con bloque de conocimiento",
            con=con,
        )
        if n["creado"]:
            n = _con_bloque(con, pid, n, cuerpo, ronda=ronda, encargo=None, autor="server", origen=origen)
            _escribir_cuerpo(pid, ruta, cuerpo, con=con, nodo=n["id"])
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
        err += [{"donde": donde, "error": x} for x in roto_en({"texto": nd.get("texto"), "datos": datos})]
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
        err += [{"donde": donde, "error": x} for x in roto_en({"motivo": v.get("motivo")})]
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
    con: sqlite3.Connection,
    pid: str,
    informe: str,
    ronda: str | None,
    sesion: str | None,
    texto: str,
    *,
    autor: str,
    origen: dict,
) -> dict:
    """Valida el bloque y, si esta entero, crea sus nodos (estado inicial de su tipo, `ronda`,
    `declarado_en` el informe, hallazgos `encontrado_por` el nodo `sesion`) y sus vinculos. Devuelve
    lo que se guarda en datos.conocimiento del informe: el mapa de ids locales a persistentes, o los
    errores. Idempotente por informe (clave declarado:<informe>:<id local>)."""
    bloque, errores = validar_bloque(con, pid, texto)
    if bloque is None:
        return {"estado": "pendiente_de_vincular", "errores": errores}
    ids: dict[str, str] = {}
    for nd in bloque["nodos"]:
        n = crear_nodo(
            pid,
            nd["tipo"],
            nd["texto"],
            nd["datos"],
            autor=autor,
            origen={**origen, "informe": informe, "local": nd["id"]},
            ronda=ronda,
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


# --- bloque pendiente, evidencia recibida y respaldo (v5 §5.2, §8.2, §8.3) -----------------------


def reincorporar(pid: str, informe: str, *, por: str) -> dict:
    """Vuelve a validar el bloque de un informe que quedo `pendiente_de_vincular` (v5 §5.2: «el cuerpo
    guardado permite recuperar un bloque pendiente»): si lo que faltaba ya existe (un `nodo:<id>` que
    se creo despues, un tema), se incorpora con las mismas claves que la primera vez. Con errores,
    devuelve los de ahora y no toca nada."""
    por = _texto(por, "por", 200)
    if rol_de(por) not in (C, P):
        raise Rechazo(f"{rol_de(por) or '?'} no reincorpora bloques", 403)
    with _abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        n = _nodo(con, pid, informe)
        if n["tipo"] != "informe":
            raise Rechazo("no es un informe")
        estado = (n["datos"].get("conocimiento") or {}).get("estado")
        if estado != "pendiente_de_vincular":
            raise Rechazo(f"el bloque del informe no esta pendiente ({estado or 'sin bloque'})", 409)
        cuerpo = _leer_archivo(os.path.join(_carpeta(pid), *n["datos"]["ruta"].split("/")))
        bloque = extraer_bloque(cuerpo or "")
        if bloque is None:
            raise Rechazo("el cuerpo guardado no tiene bloque", 409)
        r = con.execute(
            "SELECT a FROM vinculo WHERE de = ? AND relacion = 'responde_a' AND activo = 1 LIMIT 1", (informe,)
        ).fetchone()
        sesion = _sesion_del_encargo(con, r["a"]) if r else (n["origen"] or {}).get("sesion_nodo")
        res = _incorporar_bloque(
            con, pid, informe, n["ronda"], sesion, bloque, autor=por, origen={"reincorporado": True}
        )
        if res["estado"] != "incorporado":
            return {"informe": informe, "conocimiento": res}
        con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (_json({**n["datos"], "conocimiento": res}), informe))
        n2 = _nodo(con, pid, informe)
        _cambio(con, pid, "conocimiento", por, "bloque reincorporado", {}, n2, anterior=n, nodo_id=informe)
    return {"informe": informe, "conocimiento": res}


EVIDENCIA_MAX_BYTES = 10_000_000
NOMBRE_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def recibir_evidencia(
    pid: str, nombre: str, contenido: bytes, *, clase: str, texto: str | None = None, autor: str, origen=None
) -> dict:
    """Un artefacto entregado al lienzo (v5 §8.2): se guarda en evidencia/<hash>-<nombre> y queda un nodo
    `evidencia` con clase, referencia (la ruta en la carpeta del proyecto), hash y bytes. El mismo
    contenido devuelve la misma evidencia. Un hash identifica el contenido, no demuestra nada (§3.1)."""
    if not isinstance(contenido, bytes) or not contenido:
        raise Rechazo("contenido vacio")
    if len(contenido) > EVIDENCIA_MAX_BYTES:
        raise Rechazo(f"la evidencia pasa de {EVIDENCIA_MAX_BYTES} bytes", 413)
    nombre = NOMBRE_SEGURO.sub("-", _texto(nombre, "nombre", 120)).strip("-.") or "evidencia"
    clase = _texto(clase, "clase", 40)
    sha = hashlib.sha256(contenido).hexdigest()
    ruta = f"evidencia/{sha[:16]}-{nombre}"
    with _abrir(pid) as con:
        n = crear_nodo(
            pid,
            "evidencia",
            texto or nombre,
            {"clase": clase, "referencia": ruta, "hash": sha, "bytes": len(contenido), "recibida": True},
            autor=autor,
            origen=origen,
            clave_ingesta=f"evidencia:{sha}",
            motivo="evidencia recibida",
            con=con,
        )
        if n["creado"]:
            full = os.path.join(_carpeta(pid), *ruta.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            escribir_exacto(full, contenido)
    return n


def respaldar(pid: str, destino: str | None = None) -> dict:
    """Respaldo de la instancia del proyecto (v5 §8.3): la base con la API de backup de SQLite (no una
    copia del archivo abierto) y los artefactos asociados (rondas/, capturas/, evidencia/), mas su
    entrada del indice. En `destino` o en <LIENZO_HOME>/respaldos/<proyecto>/<fecha>/."""
    p = proyecto(pid)
    fecha = ahora().replace(":", "").replace("-", "").replace(".", "")
    destino = destino or os.path.join(os.path.dirname(raiz()), "respaldos", pid, fecha)
    os.makedirs(destino, exist_ok=True)
    origen = sqlite3.connect(_db_path(pid), timeout=10)
    copia = sqlite3.connect(os.path.join(destino, "conocimiento.sqlite"))
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    archivos = 0
    import shutil

    for sub in ("rondas", "capturas", "evidencia"):
        src = os.path.join(_carpeta(pid), sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(destino, sub), dirs_exist_ok=True)
            archivos += sum(len(f) for _, _, f in os.walk(src))
    atomic_write(os.path.join(destino, "proyecto.json"), json.dumps(p, ensure_ascii=False, indent=1))
    return {"proyecto": pid, "destino": destino, "archivos": archivos}


# --- texto roto ya guardado: medir y reparar por auditoria ----------------------------------------


def texto_roto_proyecto(pid: str) -> dict:
    """Mide el texto roto del proyecto sin tocar nada: nodos (texto y datos), cuerpos de encargos e
    informes en disco, cambios y capturas. Cada nodo dice si es reparable (solo mojibake) o no (tiene
    U+FFFD: el original se perdio)."""
    carpeta = _carpeta(pid)
    nodos_rotos, cuerpos = [], []
    with _abrir(pid) as con:
        filas = [_fila(r) for r in con.execute("SELECT * FROM nodo WHERE proyecto = ? ORDER BY fecha, id", (pid,))]
        cambios_rotos = sum(
            1 for (n,) in con.execute("SELECT nuevo FROM cambio WHERE proyecto = ?", (pid,)) if texto_roto(n)
        )
        capturas_rotas = sum(
            1 for (t,) in con.execute("SELECT texto FROM captura WHERE proyecto = ?", (pid,)) if texto_roto(t)
        )
    for n in filas:
        marcas = [m for _, s in _textos_de({"texto": n["texto"], "datos": n["datos"]}, "") for m in texto_roto(s)]
        if marcas:
            reemplazos = sum(1 for m in marcas if m["clase"] == "reemplazo")
            nodos_rotos.append(
                {
                    "id": n["id"],
                    "tipo": n["tipo"],
                    "texto": n["texto"],
                    "reemplazo": reemplazos,
                    "mojibake": len(marcas) - reemplazos,
                    "reparable": reemplazos == 0,
                }
            )
        ruta = n["datos"].get("ruta") if n["tipo"] in ("encargo", "informe") else None
        if isinstance(ruta, str):
            texto = _leer_archivo(os.path.join(carpeta, *ruta.split("/")))
            marcas = texto_roto(texto or "")
            if marcas:
                reemplazos = sum(1 for m in marcas if m["clase"] == "reemplazo")
                cuerpos.append(
                    {"nodo": n["id"], "ruta": ruta, "reemplazo": reemplazos, "mojibake": len(marcas) - reemplazos}
                )
    return {
        "proyecto": pid,
        "nodos": len(filas),
        "nodos_rotos": nodos_rotos,
        "cuerpos_rotos": cuerpos,
        "cambios_rotos": cambios_rotos,
        "capturas_rotas": capturas_rotas,
    }


def reparar_texto(pid: str, *, por: str, aplicar: bool = False) -> dict:
    """Repara el mojibake de los nodos por la via de auditoria: cada nodo reparado cambia su texto y sus
    datos en una transaccion con un `cambio` (accion `texto`, anterior y nuevo), sin UPDATE a mano.
    Un nodo con U+FFFD no se toca: se lista en `irrecuperables` (no se inventa el texto perdido). Sin
    `aplicar`, solo dice que haria. Los cuerpos en disco no se reescriben: su hash es el de lo
    entregado."""
    por = _texto(por, "por", 200)
    if rol_de(por) not in (C, P):
        raise Rechazo(f"{rol_de(por) or '?'} no repara texto", 403)
    reparados, irrecuperables, sin_cambio = [], [], []
    with _abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        for r in con.execute("SELECT * FROM nodo WHERE proyecto = ? ORDER BY fecha, id", (pid,)).fetchall():
            n = _fila(r)
            marcas = [m for _, s in _textos_de({"texto": n["texto"], "datos": n["datos"]}, "") for m in texto_roto(s)]
            if not marcas:
                continue
            if any(m["clase"] == "reemplazo" for m in marcas):
                irrecuperables.append({"id": n["id"], "tipo": n["tipo"], "texto": n["texto"]})
                continue
            texto, datos = reparar_segmentos(n["texto"]), _reparar_en(n["datos"])
            if (texto, datos) == (n["texto"], n["datos"]):
                sin_cambio.append({"id": n["id"], "tipo": n["tipo"], "texto": n["texto"]})
                continue
            reparados.append({"id": n["id"], "tipo": n["tipo"], "antes": n["texto"], "despues": texto})
            if aplicar:
                con.execute("UPDATE nodo SET texto = ?, datos = ? WHERE id = ?", (texto, _json(datos), n["id"]))
                n2 = _nodo(con, pid, n["id"])
                _cambio(
                    con,
                    pid,
                    "texto",
                    por,
                    "reparar mojibake (UTF-8 leido como Windows-1252)",
                    {},
                    n2,
                    anterior=n,
                    nodo_id=n["id"],
                )
    return {
        "aplicado": bool(aplicar),
        "reparados": reparados,
        "irrecuperables": irrecuperables,
        "sin_cambio": sin_cambio,
    }


# --- captura automatica (anexo A de v5): lo que pasa por el lienzo, sin registrarlo a mano -----

CLASES_CAPTURA = ("pedido", "respuesta", "envio", "regla")
CAPTURA_MAX_BYTES = 64_000  # texto guardado por captura; el hash y los bytes son los del original


def _recordar_sesion(sid: str, pid: str) -> None:
    with _lock:
        _sesion_proyecto[sid] = pid
        _sesion_sin_proyecto.discard(sid)


def registrar_sesion(pid: str, tarjeta: dict) -> dict:
    """El nodo `sesion` de una tarjeta vista en la carpeta del proyecto (viva), con agente, modelo, pc
    y cwd; idempotente por session_id. Desde aca los adaptadores (cierre, vuelta, permisos, errores)
    la encuentran aunque no trabaje un encargo."""
    sid = _texto(tarjeta.get("session_id"), "session_id", 100)
    with _abrir(pid) as con:
        n = _sesion(
            con,
            pid,
            sid,
            agente=tarjeta.get("agent"),
            modelo=tarjeta.get("model"),
            pc=tarjeta.get("pc"),
            cwd=tarjeta.get("cwd"),
        )
    _recordar_sesion(sid, pid)
    return n


def _recortar(texto: str) -> tuple[str, bool]:
    b = texto.encode("utf-8")
    if len(b) <= CAPTURA_MAX_BYTES:
        return texto, False
    return b[:CAPTURA_MAX_BYTES].decode("utf-8", errors="ignore") + "\n[... recortado por el lienzo]", True


def capturar(
    pid: str,
    clase: str,
    texto: str,
    tarjeta: dict,
    *,
    origen: dict | None = None,
    clave: str | None = None,
    redactado: bool = False,
) -> dict | None:
    """Una captura `observado` en el proyecto: un pedido, una respuesta final, un envio entre sesiones
    o el disparo de una regla, con sesion, agente, modelo, pc y hora. El texto ya viene sin secretos
    (captura.py los tapa antes de encolar: el original nunca llega aca); se guarda hasta
    CAPTURA_MAX_BYTES, con el hash y los bytes del texto entero antes de recortarlo.
    Idempotente por `clave` (devuelve None si ya estaba). Nunca crea nodos de conocimiento ni cambios
    de estado: el veredicto de v5 §3.4 no cambia."""
    if clase not in CLASES_CAPTURA:
        raise Rechazo(f"clase de captura desconocida: {clase}")
    if not isinstance(texto, str) or not texto.strip():
        return None
    sid = _texto(tarjeta.get("session_id"), "session_id", 100)
    original = texto.strip()
    guardado, recortado = _recortar(original)
    b = original.encode("utf-8")
    with _abrir(pid) as con:
        if clave and con.execute("SELECT 1 FROM captura WHERE clave_ingesta = ?", (clave,)).fetchone():
            return None
        s = _sesion(
            con,
            pid,
            sid,
            agente=tarjeta.get("agent"),
            modelo=tarjeta.get("model"),
            pc=tarjeta.get("pc"),
            cwd=tarjeta.get("cwd"),
        )
        fila = {
            "id": nuevo_id(),
            "proyecto": pid,
            "clase": clase,
            "session_id": sid,
            "sesion": s["id"],
            "agente": tarjeta.get("agent"),
            "modelo": tarjeta.get("model"),
            "pc": tarjeta.get("pc"),
            "origen": _json(_objeto(origen, "origen")),
            "texto": guardado,
            "bytes": len(b),
            "hash": hashlib.sha256(b).hexdigest(),
            "recortado": int(recortado),
            "redactado": int(bool(redactado)),
            "fecha": ahora(),
            "clave_ingesta": clave,
        }
        con.execute(
            f"INSERT INTO captura ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})", list(fila.values())
        )
    _recordar_sesion(sid, pid)
    return {**fila, "origen": json.loads(fila["origen"])}


def capturas(
    pid: str, *, session_id: str | None = None, clase: str | None = None, desde: str | None = None, limite: int = 100
) -> dict:
    """Las capturas del proyecto, de la mas nueva a la mas vieja, con filtros por sesion, clase y fecha
    minima (ISO UTC)."""
    cond, args = ["proyecto = ?"], [pid]
    for col, v in (("session_id", session_id), ("clase", clase)):
        if v:
            cond.append(f"{col} = ?")
            args.append(v)
    if desde:
        cond.append("fecha >= ?")
        args.append(desde)
    limite = max(1, min(int(limite), 500))
    with _abrir(pid) as con:
        total = con.execute(f"SELECT COUNT(*) FROM captura WHERE {' AND '.join(cond)}", args).fetchone()[0]
        filas = con.execute(
            f"SELECT * FROM captura WHERE {' AND '.join(cond)} ORDER BY fecha DESC, rowid DESC LIMIT ?", [*args, limite]
        ).fetchall()
    return {"total": total, "capturas": [_fila(r) for r in filas]}


def buscar_prosa(pid: str, consulta: str, *, limite: int = LIMITE_BUSQUEDA) -> list[dict]:
    """BM25 sobre la prosa: los cuerpos de encargos e informes y las capturas. Fuente aparte de los
    nodos: cada resultado viene marcado `prosa, no declarado`, con un fragmento y, si es un cuerpo, el
    nodo al que pertenece. La consulta es FTS5 como en `buscar`; una sintaxis invalida es 400."""
    consulta = _texto(consulta, "consulta", 500)
    limite = max(1, min(int(limite), LIMITE_PAGINA))
    out = []
    with _abrir(pid) as con:
        try:
            for r in con.execute(
                "SELECT p.nodo, n.tipo, n.texto AS titulo, n.datos, bm25(prosa_fts) AS puntaje,"
                " snippet(prosa_fts, 1, '[', ']', ' … ', 24) AS fragmento FROM prosa_fts p"
                " JOIN nodo n ON n.id = p.nodo AND n.proyecto = ? WHERE prosa_fts MATCH ? ORDER BY puntaje LIMIT ?",
                (pid, consulta, limite),
            ):
                out.append(
                    {
                        "fuente": r["tipo"],
                        "marca": "prosa, no declarado",
                        "nodo": r["nodo"],
                        "titulo": r["titulo"],
                        "ruta": json.loads(r["datos"]).get("ruta"),
                        "puntaje": r["puntaje"],
                        "fragmento": r["fragmento"],
                    }
                )
            for r in con.execute(
                "SELECT c.id, c.clase, c.session_id, c.agente, c.fecha, bm25(captura_fts) AS puntaje,"
                " snippet(captura_fts, 0, '[', ']', ' … ', 24) AS fragmento FROM captura_fts"
                " JOIN captura c ON c.rowid = captura_fts.rowid WHERE captura_fts MATCH ? AND c.proyecto = ?"
                " ORDER BY puntaje LIMIT ?",
                (consulta, pid, limite),
            ):
                out.append(
                    {
                        "fuente": f"captura:{r['clase']}",
                        "marca": "prosa, no declarado",
                        "captura": r["id"],
                        "session_id": r["session_id"],
                        "agente": r["agente"],
                        "fecha": r["fecha"],
                        "puntaje": r["puntaje"],
                        "fragmento": r["fragmento"],
                    }
                )
        except sqlite3.OperationalError as e:
            raise Rechazo(f"consulta FTS invalida: {e}") from e
    out.sort(key=lambda x: (x["puntaje"], x.get("nodo") or x.get("captura")))
    return out[:limite]


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
