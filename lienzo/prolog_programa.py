"""Cláusulas de creencias como datos: no se ejecuta Prolog recibido (AA, lote 1)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from atomico import atomic_write

VERSION = 1
TEXTO, NUMERO = "texto", "numero"
VOCABULARIO = {
    **{
        p: (TEXTO,)
        for p in (
            "chrome_en_uso",
            "pruebas",
            "arbol_compartido",
            "por_commitear",
            "salida_redirigida",
            "artefactos_exclusivos",
            "evidencia_fallo_completa",
            "pc_bloqueada",
            "presion_ram",
            "cache_wsl_alta",
            "frentes_concurrentes",
            "espera_coordinadora",
            "pendientes_humanos",
            "necesita_veredicto",
            "reinicio_propuesto",
            "restauracion",
            "sucesora_verificada",
            "interactiva",
        )
    },
    **{
        p: (TEXTO, TEXTO)
        for p in (
            "proyecto",
            "tecnologia",
            "tipo_archivo",
            "ruta",
            "area",
            "fase",
            "tipo_trabajo",
            "agente",
            "modelo",
            "entorno",
            "shell",
            "fallo",
            "send_error",
            "modo",
            "entrega",
            "por_lanzar",
            "turno_exclusivo",
            "vigente",
            "omitida_en",
        )
    },
    **{
        p: (TEXTO, NUMERO)
        for p in (
            "memoria_libre_gb",
            "frentes_activos",
            "recurso_necesita_gb",
            "wsl_arranque_gb",
            "codigo_pruebas",
            "version_chrome",
        )
    },
    "cuota_semanal_disponible_pct": (TEXTO, TEXTO, NUMERO),
    "cuota_mensual_disponible": (TEXTO, TEXTO, NUMERO),
    "escenario_ram": (TEXTO, TEXTO, NUMERO, NUMERO),
    "recomendar": (TEXTO, TEXTO, TEXTO),
    "impedir": (TEXTO, TEXTO, TEXTO),
}
CONCLUSIONES = {"recomendar", "impedir"}
TOKEN = re.compile(
    r"""\s*(?:(:-|=<|<=|>=|!=|<|>|=|[(),.])|([A-Z][A-Za-z0-9_]*|[a-z][a-z0-9_]*)|(-?\d+(?:\.\d+)?)|('[^'\\\r\n]*'|"(?:[^"\\\r\n]|\\.)*"))"""
)
_lock = threading.RLock()
_pendientes = {}
_errores = {}
_cola_lock = threading.Lock()
_worker = None


def canonico(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _tokens(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 4000:
        raise ValueError("cláusula vacía o demasiado larga")
    out, pos = [], 0
    while pos < len(text.rstrip()):
        found = TOKEN.match(text, pos)
        if not found:
            raise ValueError(f"símbolo no permitido en posición {pos}")
        out.append(next(x for x in found.groups() if x is not None))
        pos = found.end()
    return out


class _Parser:
    def __init__(self, text):
        self.tokens = _tokens(text)
        self.pos = 0

    def pop(self):
        if self.pos >= len(self.tokens):
            raise ValueError("cláusula incompleta")
        value = self.tokens[self.pos]
        self.pos += 1
        return value

    def expect(self, value):
        if self.pop() != value:
            raise ValueError(f"se esperaba {value}")

    def term(self):
        text = self.pop()
        if text.startswith(("'", '"')):
            value = text[1:-1] if text.startswith("'") else json.loads(text)
            if value.startswith("?"):
                raise ValueError("las constantes no pueden usar el prefijo de variables")
            return value
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", text):
            return "?" + text
        if re.fullmatch(r"[a-z][a-z0-9_]*", text):
            return text
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            value = float(text) if "." in text else int(text)
            if not math.isfinite(value):
                raise ValueError("número no finito")
            return value
        raise ValueError("término inválido")

    def literal(self):
        pred = self.pop()
        if pred not in VOCABULARIO:
            raise ValueError(f"predicado fuera del vocabulario: {pred}")
        self.expect("(")
        args = [self.term()]
        while self.tokens[self.pos : self.pos + 1] == [","]:
            self.pop()
            args.append(self.term())
        self.expect(")")
        if len(args) != len(VOCABULARIO[pred]):
            raise ValueError(f"aridad inválida en {pred}")
        return {"pred": pred, "args": args}


def _variable(x):
    return isinstance(x, str) and x.startswith("?")


def _tipos(lit, tipos):
    for value, kind in zip(lit["args"], VOCABULARIO[lit["pred"]], strict=True):
        if _variable(value):
            if tipos.setdefault(value, kind) != kind:
                raise ValueError("variable usada con tipos incompatibles")
        elif kind == NUMERO:
            if type(value) not in (int, float) or value < 0:
                raise ValueError("se esperaba número no negativo")
        elif not isinstance(value, str):
            raise ValueError("se esperaba texto")


def validar(value):
    if not isinstance(value, dict) or set(value) != {"version", "vocabulario", "clausula"}:
        raise ValueError("regla_logica requiere version, vocabulario y clausula")
    if any(type(value[k]) is not int or value[k] != VERSION for k in ("version", "vocabulario")):
        raise ValueError("versión de regla o vocabulario desconocida")
    parser = _Parser(value["clausula"])
    head = parser.literal()
    parser.expect(":-")
    body, bound, tipos = [], set(), {}
    while True:
        if parser.tokens[parser.pos : parser.pos + 1] and parser.tokens[parser.pos] in VOCABULARIO:
            item = parser.literal()
            if item["pred"] == head["pred"]:
                raise ValueError("no se admite recursión directa en cláusulas de creencias")
            _tipos(item, tipos)
            bound.update(x for x in item["args"] if _variable(x))
        else:
            a, op, b = parser.term(), parser.pop(), parser.term()
            if op not in ("<", "<=", "=<", ">", ">=", "=", "!="):
                raise ValueError("comparación no permitida")
            if any(_variable(x) and x not in bound for x in (a, b)):
                raise ValueError("comparación con variable libre")
            if op not in ("=", "!=") and any(
                (tipos.get(x) != NUMERO if _variable(x) else type(x) not in (int, float)) for x in (a, b)
            ):
                raise ValueError("comparación de orden requiere números")
            item = {"cmp": "<=" if op == "=<" else op, "args": [a, b]}
        body.append(item)
        sep = parser.pop()
        if sep == ".":
            break
        if sep != "," or len(body) >= 32:
            raise ValueError("cuerpo inválido o demasiado largo")
    if parser.pos != len(parser.tokens):
        raise ValueError("texto después de la cláusula")
    if any(_variable(x) and x not in bound for x in head["args"]):
        raise ValueError("cabeza con variable libre")
    _tipos(head, tipos)
    return {"head": head, "body": body}


def identidad(ast):
    names = {}

    def normalize(x):
        if isinstance(x, dict):
            return {k: normalize(v) for k, v in x.items()}
        if isinstance(x, list):
            return [normalize(v) for v in x]
        if _variable(x):
            return names.setdefault(x, "?V" + str(len(names)))
        return x

    return hashlib.sha256(canonico(normalize(ast)).encode()).hexdigest()


def desde_ast(ast):
    """Cláusula visible de una deducción; la misma validación que recibe el proponente."""

    def term(value):
        if _variable(value):
            return value[1:]
        return json.dumps(value, ensure_ascii=True, allow_nan=False)

    def literal(item):
        return item["pred"] + "(" + ", ".join(term(x) for x in item["args"]) + ")"

    body = []
    for item in ast["body"]:
        if "cmp" in item:
            body.append(f"{term(item['args'][0])} {item['cmp']} {term(item['args'][1])}")
        else:
            body.append(literal(item))
    result = {"version": 1, "vocabulario": 1, "clausula": literal(ast["head"]) + " :- " + ", ".join(body) + "."}
    validar(result)
    return result


def revision(node):
    data = node["datos"]
    meaning = {
        key: data.get(key)
        for key in (
            "regla_logica",
            "accion",
            "contexto",
            "alcance",
            "dimension",
            "principio",
        )
    }
    meaning["texto"] = node["texto"]
    meaning["metadatos"] = {key: val for key, val in data.get("metadatos", {}).items() if key != "fuentes"}
    return hashlib.sha256(canonico(meaning).encode()).hexdigest()


def veredicto_actual(node):
    approved = node["datos"].get("revision_veredicto")
    if approved is None:
        return not node["datos"].get("regla_logica") and not node["datos"].get("principio")
    return approved == revision(node)


def equivalente(con, pid, payload):
    """Idempotencia semántica al proponer; la fusión de dos nodos existentes sigue siendo de AB."""
    import conocimiento as k

    signature = payload.get("regla_logica")
    if signature is None:
        return None  # texto legacy: la equivalencia debe revisarse con el helper de fusión de AB
    logical = identidad(validar(signature))
    for row in con.execute(
        "SELECT * FROM nodo WHERE proyecto=? AND tipo='decision' AND estado IN ('propuesta','vigente') "
        "AND json_extract(datos,'$.clase')='creencia_operativa' ORDER BY estado DESC,fecha,id",
        (pid,),
    ):
        node = k._fila(row)
        data = node["datos"]
        if not data.get("regla_logica"):
            continue
        if identidad(validar(data["regla_logica"])) != logical:
            continue
        if all(
            data.get(key, default) == payload.get(key, default)
            for key, default in (
                ("contexto", {}),
                ("dimension", ""),
                ("alcance", "proyecto"),
                ("excepciones", ""),
                ("accion", ""),
            )
        ):
            return {**node, "creado": False}
    return None


def _term(value):
    # Strings JSON se aceptan como strings Prolog; el motor sólo lee términos ground, nunca goals.
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def renderizar(pid, nodes):
    lines = ["% Proyección regenerable de SQLite. Reglas representadas como datos.", f"proyecto({_term(pid)})."]
    for node in sorted(nodes, key=lambda n: n["id"]):
        if node["proyecto"] != pid:
            raise ValueError("nodo de otro proyecto")
        bid, data = node["id"], node["datos"]
        rev = revision(node)
        lines.append(f"creencia({_term(bid)}, {_term(rev)}, {_term(node['estado'])}).")
        if data.get("regla_logica") is None:
            lines.append(f"sin_formalizar({_term(bid)}).")
        else:
            ast = validar(data["regla_logica"])
            visible = data["regla_logica"]["clausula"].replace("\r", " ").replace("\n", " ")
            lines.append(f"% Regla {_term(bid)}: {visible}")
            lines.append(f"regla_logica({_term(bid)}, {_term(canonico(ast))}).")
        projected = {k: v for k, v in data.items() if k != "regla_logica"}
        lines.append(f"datos_creencia({_term(bid)}, {_term(canonico(projected))}).")
    return "\n".join(lines) + "\n"


def exportar(pid, nodes, *, secuencia, raiz):
    if not isinstance(pid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}", pid):
        raise ValueError("id de proyecto inseguro")
    if type(secuencia) is not int or secuencia < 0:
        raise ValueError("secuencia inválida")
    own = [n for n in nodes if n["datos"].get("alcance") != "proceso_lienzo"]
    process = [n for n in nodes if n["datos"].get("alcance") == "proceso_lienzo"]
    if process and pid != "lienzo":
        raise ValueError("proceso_lienzo sólo puede pertenecer a lienzo")
    # Validar todo antes de publicar cualquier archivo. Manifest al final acredita generación completa.
    outputs = {f"proyectos/{pid}.pl": renderizar(pid, own)}
    if pid == "lienzo":
        outputs["proceso_lienzo.pl"] = renderizar(pid, process)
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in outputs.items()}
    root = Path(raiz)
    with _lock:
        manifest_path = root / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"proyectos": {}}
        )
        for name, content in outputs.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(str(path), content)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["proyectos"][pid] = {"secuencia": secuencia, "archivos": hashes, "vocabulario": VERSION}
        atomic_write(str(manifest_path), canonico(manifest))
    return {"hash": hashes[f"proyectos/{pid}.pl"], "secuencia": secuencia, "archivos": hashes}


def sincronizar(pid, *, base=None, raiz=None):
    import conocimiento as k

    base = base or k.db_path()
    root = Path(raiz) if raiz else Path(base).parent / "prolog"
    with sqlite3.connect(Path(base).resolve().as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        nodes = [
            k._fila(r)
            for r in con.execute(
                "SELECT * FROM nodo WHERE proyecto=? AND tipo='decision' "
                "AND json_extract(datos,'$.clase')='creencia_operativa' ORDER BY id",
                (pid,),
            )
        ]
        seq = con.execute("SELECT coalesce(max(seq),0) FROM cambio WHERE proyecto=?", (pid,)).fetchone()[0]
    with _lock:
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"proyectos": {}}
        old = manifest["proyectos"].get(pid)
        if old and old["secuencia"] > seq:
            return old  # otro hilo ya publicó una foto más nueva
        if (
            old
            and old["secuencia"] == seq
            and all(
                (root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == sig
                for name, sig in old["archivos"].items()
            )
        ):
            return old
        result = exportar(pid, nodes, secuencia=seq, raiz=root)
        if pid == "lienzo":
            import prolog_ciclo

            prolog_ciclo.graduar(archivo=root.parent / "reglas-proceso.md")
        return result


def notificar(proyectos, *, base):
    """Hook corto: la generación corre fuera de la escritura y usa rutas capturadas."""
    global _worker
    resolved = str(Path(base).resolve())
    import conocimiento as k
    import state

    log_path = state.LOG if resolved == str(Path(k.db_path()).resolve()) else str(Path(base).parent / "lienzo.log")
    with _cola_lock:
        for pid in proyectos:
            _pendientes[(resolved, pid)] = log_path
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_procesar, name="prolog-proyecciones", daemon=True)
            _worker.start()


def _procesar():
    global _worker
    # Un pequeño lote reduce las regeneraciones al importar una tanda de evidencias.
    time.sleep(0.03)
    while True:
        with _cola_lock:
            if not _pendientes:
                _worker = None
                return
            (base, pid), log_path = _pendientes.popitem()
        try:
            sincronizar(pid, base=base)
            _errores.pop((base, pid), None)
        except Exception as exc:
            _errores[(base, pid)] = str(exc)
            # Capturar la ruta evita que un worker de prueba escriba en el LIENZO_HOME real al terminar.
            log = Path(log_path)
            try:
                with log.open("a", encoding="utf-8") as stream:
                    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    stream.write(f"{stamp}  error    Prolog {pid}: {type(exc).__name__}: {exc}\n")
            except OSError:
                # stderr también queda en el log del servicio si el disco no admite el diagnóstico.
                import sys

                print(f"Prolog {pid}: {exc}", file=sys.stderr)


def archivos(pid):
    """Foto vigente del proyecto y de proceso para el consumidor; verifica hashes antes de cargar."""
    import conocimiento as k
    import prolog_learning

    root = Path(k.db_path()).parent / "prolog"
    owners = [pid] if pid == "lienzo" else [pid, "lienzo"]
    out = []
    for owner in owners:
        if not os.path.isdir(k._carpeta(owner)):
            continue
        entry = sincronizar(owner)
        for name, sig in entry["archivos"].items():
            if owner != pid and name != "proceso_lienzo.pl":
                continue
            path = root / name
            text = path.as_posix()
            if prolog_learning.WSL:
                text = "/mnt/" + path.drive[0].lower() + text[len(path.drive) :]
            out.append({"path": text, "hash": sig})
    return out
