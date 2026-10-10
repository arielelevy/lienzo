"""Aprendizaje operativo del conocimiento por proyecto (v5 §6, etapa 4): incidentes parecidos y
grupos de recurrencia (§6.1), reglas cuestionadas por una recurrencia posterior a su vigencia (§6.2),
apoyos rechazados y dependencias de un nodo (§6.3), y las lecciones de un agente en todos los
proyectos (§6.3, ultimo parrafo).

Todo es de solo lectura salvo `cuestionar` y `cuestionar_regla`, que aplican la unica transicion que
la tabla de v5 §3.4 le da al server (regla: vigente -> cuestionada). Los `repite` los confirma la
coordinadora con un veredicto; aca solo se proponen (`parecidos`) y se recorren.

Usa las consultas de `conocimiento` y sus internals de auditoria en una transaccion unica para
cuestionar reglas; no toca el esquema. Las fechas son las ISO UTC de `conocimiento.ahora()`: se comparan como texto, igual que en
las consultas de v5 §8.5.
"""

from __future__ import annotations

import re
from collections import deque

import conocimiento as k
from conocimiento import Rechazo

LIMITE_PARECIDOS = 10
MAX_TERMINOS = 24  # palabras del sintoma que entran a la consulta FTS
_PALABRA = re.compile(r"\w+")
# (tipo, estado) de un respaldo caido (v5 §6.3)
RESPALDOS_CAIDOS = {("hallazgo", "rechazado"), ("medicion", "rechazada"), ("decision", "revertida")}
# relaciones por las que un nodo depende de otro (quien cita a quien), para `dependencias`
RELACIONES_DEPENDENCIA = ("motivada_por", "apoya", "derivada_de", "contesta")
ESTADOS_LECCION = ("vigente", "cuestionada")
LIMITE_INCIDENTES_AGENTE = 50  # por proyecto, los mas nuevos

_SQL_GRUPO = """
WITH RECURSIVE grupo(id) AS (
  SELECT :i
  UNION
  SELECT v.a FROM grupo g JOIN vinculo v ON v.de = g.id AND v.relacion = 'repite' AND v.activo = 1
  UNION
  SELECT v.de FROM grupo g JOIN vinculo v ON v.a = g.id AND v.relacion = 'repite' AND v.activo = 1
)
SELECT n.* FROM grupo g JOIN nodo n ON n.id = g.id
WHERE n.proyecto = :p AND n.tipo = 'incidente'
ORDER BY n.fecha, n.id
"""


# --- utilidades -----------------------------------------------------------------------------


def _incidente(con, pid: str, nid: str) -> dict:
    n = k._nodo(con, pid, nid)
    if n["tipo"] != "incidente":
        raise Rechazo(f"no es un incidente: {nid}")
    return n


def _regla(con, pid: str, nid: str) -> dict:
    n = k._nodo(con, pid, nid)
    if n["tipo"] != "regla":
        raise Rechazo(f"no es una regla: {nid}")
    return n


def _grupo(con, pid: str, nid: str) -> list[dict]:
    """El grupo de recurrencia de un incidente: el y todos los unidos por `repite` activo, directa o
    transitivamente y en las dos direcciones. `UNION` cuenta cada episodio una vez aunque haya varias
    rutas (v5 §6.1). Ordenado por fecha."""
    return [k._fila(r) for r in con.execute(_SQL_GRUPO, {"i": nid, "p": pid}).fetchall()]


def _episodio(n: dict) -> dict:
    d = n.get("datos") or {}
    return {
        "id": n["id"],
        "texto": n["texto"],
        "fecha": n["fecha"],
        "estado": n.get("estado"),
        "herramienta": d.get("herramienta"),
        "agente": d.get("agente"),
        "modelo": d.get("modelo"),
    }


def _paso(n: dict, relacion: str) -> dict:
    return {"id": n["id"], "tipo": n["tipo"], "texto": n["texto"], "estado": n.get("estado"), "relacion": relacion}


def consulta_fts(texto: str) -> str:
    """La consulta FTS5 a partir del sintoma: cada palabra entre comillas (asi `and`, `or`, `not` o
    un guion no se leen como sintaxis) unidas por OR; BM25 ordena por cuantas comparte. Vacia si el
    texto no tiene palabras."""
    vistas: list[str] = []
    for p in _PALABRA.findall((texto or "").lower()):
        if len(p) < 2 or p in vistas:
            continue
        vistas.append(p)
        if len(vistas) >= MAX_TERMINOS:
            break
    return " OR ".join(f'"{p}"' for p in vistas)


# --- 6.1 recurrencia --------------------------------------------------------------------------


def parecidos(pid: str, incidente: str, *, limite: int = LIMITE_PARECIDOS) -> list[dict]:
    """Candidatos a recurrencia de un incidente: los incidentes del proyecto que BM25 encuentra con las
    palabras de su sintoma (v5 §8.5, consulta 3), con los de la misma herramienta y el mismo agente
    primero y, dentro de cada grupo, por puntaje. Excluye el incidente y todo su grupo de recurrencia
    (lo ya vinculado por `repite` en cualquier direccion, directa o transitiva). No vincula: `repite`
    lo confirma la coordinadora. Una semejanza textual no prueba la misma causa."""
    limite = max(1, min(int(limite), k.LIMITE_PAGINA))
    with k._abrir(pid) as con:
        n = _incidente(con, pid, incidente)
        grupo = {g["id"] for g in _grupo(con, pid, incidente)}
        consulta = consulta_fts(n["texto"])
        if not consulta:
            return []
        # Sin LIMIT previo: un candidato con mejor herramienta/agente puede quedar
        # arbitrariamente lejos en el ranking lexical. El corte se hace al final.
        candidatos = [
            k._fila(r)
            for r in con.execute(
                "SELECT n.*, bm25(nodo_fts, 3.0, 1.0) AS puntaje FROM nodo_fts"
                " JOIN nodo n ON n.rowid = nodo_fts.rowid WHERE nodo_fts MATCH ?"
                " AND n.proyecto = ? AND n.tipo = 'incidente'",
                (consulta, pid),
            )
        ]
    herramienta, agente = n["datos"].get("herramienta"), n["datos"].get("agente")
    out = []
    for c in candidatos:
        if c["id"] in grupo:
            continue
        d = c["datos"]
        out.append(
            {
                **_episodio(c),
                "puntaje": c["puntaje"],
                "misma_herramienta": bool(herramienta) and d.get("herramienta") == herramienta,
                "mismo_agente": bool(agente) and d.get("agente") == agente,
            }
        )
    out.sort(key=lambda x: (not x["misma_herramienta"], not x["mismo_agente"], x["puntaje"], x["id"]))
    return out[:limite]


def recurrencia(pid: str, incidente: str) -> dict:
    """Los episodios de la cadena `repite` de un incidente (directa o transitiva, en las dos
    direcciones), cada uno una vez aunque haya varias rutas, con la cantidad y el primero y el ultimo
    por fecha. Un incidente sin `repite` es un grupo de uno (`recurrente: False`)."""
    with k._abrir(pid) as con:
        _incidente(con, pid, incidente)
        episodios = [_episodio(g) for g in _grupo(con, pid, incidente)]
    return {
        "incidente": incidente,
        "cantidad": len(episodios),
        "recurrente": len(episodios) > 1,
        "primero": episodios[0],
        "ultimo": episodios[-1],
        "episodios": episodios,
    }


def recurrencias(pid: str) -> list[dict]:
    """Grupos confirmados de dos o mas incidentes, una vez por componente.

    Solo repite activos; sin duplicar episodios por rutas redundantes. La ficha
    usa como incidente representativo el primero por fecha e ID. Solo lectura.
    """
    with k._abrir(pid) as con:
        con.execute("BEGIN")
        nodos = {
            r["id"]: k._fila(r)
            for r in con.execute("SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'incidente'", (pid,))
        }
        vecinos: dict[str, set[str]] = {}
        for r in con.execute(
            "SELECT v.de, v.a FROM vinculo v JOIN nodo x ON x.id = v.de AND x.proyecto = ?"
            " WHERE v.relacion = 'repite' AND v.activo = 1",
            (pid,),
        ):
            if r["de"] in nodos and r["a"] in nodos:
                vecinos.setdefault(r["de"], set()).add(r["a"])
                vecinos.setdefault(r["a"], set()).add(r["de"])
    vistos = set()
    grupos = []
    for nid in sorted(vecinos):
        if nid in vistos:
            continue
        vistos.add(nid)
        pendientes = [nid]
        miembros = []
        while pendientes:
            actual = pendientes.pop()
            miembros.append(nodos[actual])
            for vecino in vecinos[actual]:
                if vecino not in vistos:
                    vistos.add(vecino)
                    pendientes.append(vecino)
        if len(miembros) < 2:
            continue
        miembros.sort(key=lambda n: (n["fecha"], n["id"]))
        episodios = [_episodio(n) for n in miembros]
        grupos.append(
            {
                "incidente": episodios[0]["id"],
                "cantidad": len(episodios),
                "recurrente": True,
                "primero": episodios[0],
                "ultimo": episodios[-1],
                "episodios": episodios,
            }
        )
    return sorted(grupos, key=lambda g: (g["primero"]["fecha"], g["incidente"]))


# --- 6.2 reglas cuestionadas ------------------------------------------------------------------


def _incidentes_origen(con, pid: str, regla: str) -> list[str]:
    """Los incidentes de los que la regla esta `derivada_de` (activos). Una decision no cuenta."""
    return [
        r["a"]
        for r in con.execute(
            "SELECT v.a FROM vinculo v JOIN nodo i ON i.id = v.a WHERE v.de = ? AND v.relacion = 'derivada_de'"
            " AND v.activo = 1 AND i.tipo = 'incidente' AND i.proyecto = ? ORDER BY v.fecha, v.a",
            (regla, pid),
        )
    ]


def _episodios_posteriores(con, pid: str, regla: dict, origen: list[str]) -> list[dict] | None:
    """Los episodios del grupo de recurrencia de los incidentes de origen con `fecha` posterior a
    `datos.vigente_desde`, sin los de origen. None si la regla no tiene contador: sin incidente de
    origen (derivada solo de una decision) o sin `vigente_desde` (v5 §6.2)."""
    desde = regla["datos"].get("vigente_desde")
    if not origen or not isinstance(desde, str) or not desde.strip():
        return None
    vistos: dict[str, dict] = {}
    for i in origen:
        for g in _grupo(con, pid, i):
            if g["id"] not in origen and g["fecha"] > desde:
                vistos[g["id"]] = g
    return sorted((_episodio(g) for g in vistos.values()), key=lambda e: (e["fecha"], e["id"]))


def _ficha(regla: dict, episodios: list[dict] | None, *, recien: bool = False) -> dict:
    d = regla["datos"]
    eps = episodios or []
    return {
        "id": regla["id"],
        "texto": regla["texto"],
        "estado": regla.get("estado"),
        "ambito": d.get("ambito"),
        "agente": d.get("agente"),
        "modelo": d.get("modelo"),
        "vigente_desde": d.get("vigente_desde"),
        "episodios_posteriores": d.get("episodios_posteriores") or [],
        "episodios": eps,
        "recurrencias": len(eps),
        "recien": recien,
    }


def _aplicar_cuestionada(con, pid: str, regla: dict, episodios: list[dict]) -> dict:
    """Estado, datos y ambos registros de auditoria en la transaccion del llamador.

    El llamador toma BEGIN IMMEDIATE antes de leer para evitar candidatos obsoletos.
    Solo aplica la transicion del server declarada en TRANSICIONES.
    """
    permitidos = k.TRANSICIONES.get(regla["tipo"], {}).get((regla.get("estado"), "cuestionada"))
    if not permitidos:
        raise Rechazo("transicion no permitida a cuestionada", 409)
    if k.rol_de("server") not in permitidos:
        raise Rechazo("server no puede cuestionar esta regla", 403)
    ids = [e["id"] for e in episodios]
    motivo = f"recurrencia confirmada posterior a vigente_desde: {len(ids)} episodio(s)"
    nid = regla["id"]
    con.execute(
        "UPDATE nodo SET estado = ?, estado_fecha = ?, estado_por = ? WHERE id = ? AND proyecto = ?",
        ("cuestionada", k.ahora(), "server", nid, pid),
    )
    estado = k._nodo(con, pid, nid)
    k._cambio(con, pid, "estado", "server", motivo, {}, estado, anterior=regla, nodo_id=nid)
    datos = {**estado["datos"], "episodios_posteriores": ids}
    con.execute("UPDATE nodo SET datos = ? WHERE id = ? AND proyecto = ?", (k._json(datos), nid, pid))
    actualizado = k._nodo(con, pid, nid)
    k._cambio(con, pid, "datos", "server", motivo, {}, actualizado, anterior=estado, nodo_id=nid)
    return actualizado


def reglas_cuestionadas(pid: str) -> list[dict]:
    """Las reglas `cuestionada` con sus episodios posteriores contados hoy desde el grafo (v5 §8.5,
    consulta 4): si la coordinadora retiro un `repite`, el contador baja (hasta cero) pero la regla
    sigue cuestionada hasta su veredicto. `episodios_posteriores` es lo guardado al cuestionarla."""
    with k._abrir(pid) as con:
        filas = con.execute(
            "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'regla' AND estado = 'cuestionada' ORDER BY fecha, id",
            (pid,),
        ).fetchall()
        out = []
        for r in filas:
            regla = k._fila(r)
            out.append(
                _ficha(regla, _episodios_posteriores(con, pid, regla, _incidentes_origen(con, pid, regla["id"])))
            )
    return out


def por_cuestionar(pid: str) -> list[tuple[dict, list[dict]]]:
    """Solo lectura: las reglas `vigente` que `cuestionar` pasaria a cuestionada, cada una con sus
    episodios posteriores. Una sola conexion para todas."""
    with k._abrir(pid) as con:
        filas = con.execute(
            "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'regla' AND estado = 'vigente' ORDER BY fecha, id", (pid,)
        ).fetchall()
        out = []
        for r in filas:
            regla = k._fila(r)
            eps = _episodios_posteriores(con, pid, regla, _incidentes_origen(con, pid, regla["id"]))
            if eps:
                out.append((regla, eps))
    return out


def cuestionar(pid: str) -> list[dict]:
    """Pasa a `cuestionada` cada regla `vigente` derivada de un incidente cuyo grupo de recurrencia
    tiene un episodio posterior a `datos.vigente_desde`, con `por="server"` y los ids en
    `datos.episodios_posteriores` (v5 §6.2). Idempotente: una regla ya cuestionada no se toca; una sin
    `vigente_desde` o derivada solo de una decision no se cuestiona. Devuelve todas las reglas
    cuestionadas del proyecto, con `recien` en las de esta pasada."""
    nuevas = set()
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        filas = con.execute(
            "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'regla' AND estado = 'vigente' ORDER BY fecha, id",
            (pid,),
        ).fetchall()
        for fila in filas:
            regla = k._fila(fila)
            eps = _episodios_posteriores(con, pid, regla, _incidentes_origen(con, pid, regla["id"]))
            if eps:
                _aplicar_cuestionada(con, pid, regla, eps)
                nuevas.add(regla["id"])
    return [{**f, "recien": f["id"] in nuevas} for f in reglas_cuestionadas(pid)]


def cuestionar_regla(pid: str, regla: str) -> dict:
    """`cuestionar` para una sola regla. Devuelve su ficha con `cuestionada` (si esta pasada la cambio)
    y `motivo` cuando no: ya cuestionada, no vigente, sin vigente_desde, derivada solo de una decision
    o sin episodios posteriores."""
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        r = _regla(con, pid, regla)
        origen = _incidentes_origen(con, pid, r["id"])
        eps = _episodios_posteriores(con, pid, r, origen)
        ficha = _ficha(r, eps)
        if r.get("estado") == "cuestionada":
            return {**ficha, "cuestionada": False, "motivo": "ya estaba cuestionada"}
        if r.get("estado") != "vigente":
            return {**ficha, "cuestionada": False, "motivo": f"la regla esta {r.get('estado')}, no vigente"}
        if eps is None:
            motivo = (
                "sin incidente de origen (derivada solo de una decision)" if not origen else "sin datos.vigente_desde"
            )
            return {**ficha, "cuestionada": False, "motivo": motivo}
        if not eps:
            return {**ficha, "cuestionada": False, "motivo": "sin episodios posteriores a vigente_desde"}
        r2 = _aplicar_cuestionada(con, pid, r, eps)
        return {**_ficha(r2, eps, recien=True), "cuestionada": True, "motivo": "recurrencia posterior a vigente_desde"}


# --- 6.3 apoyos rechazados y dependencias -----------------------------------------------------


class _Respaldos:
    """El subgrafo de respaldos de un proyecto (decisiones, hallazgos, mediciones, incidentes,
    preguntas e informes con sus `motivada_por` y `contesta` activos), cargado una vez, y las cadenas
    desde cada nodo hasta sus respaldos caidos. Solo lectura."""

    def __init__(self, con, pid: str):
        self.nodos: dict[str, dict] = {
            r["id"]: k._fila(r)
            for r in con.execute(
                "SELECT id, tipo, texto, estado FROM nodo WHERE proyecto = ? AND tipo IN"
                " ('decision','hallazgo','medicion','incidente','pregunta','informe')",
                (pid,),
            )
        }
        self.motiva: dict[str, list[str]] = {}  # decision -> sus respaldos (motivada_por)
        self.contesta: dict[str, list[str]] = {}  # pregunta -> nodos que la contestan
        for r in con.execute(
            "SELECT v.de, v.relacion, v.a FROM vinculo v JOIN nodo x ON x.id = v.de AND x.proyecto = ?"
            " WHERE v.activo = 1 AND v.relacion IN ('motivada_por','contesta')",
            (pid,),
        ):
            de, rel, a = r["de"], r["relacion"], r["a"]
            if de not in self.nodos or a not in self.nodos:
                continue
            if rel == "motivada_por":
                self.motiva.setdefault(de, []).append(a)
            else:
                self.contesta.setdefault(a, []).append(de)

    def caido(self, nid: str) -> bool:
        n = self.nodos[nid]
        return (n["tipo"], n.get("estado")) in RESPALDOS_CAIDOS

    def cadenas_decision(self, nid: str) -> list[list[dict]]:
        """Una cadena minima por respaldo caido, con BFS iterativo y visita unica.

        No enumera todos los caminos del grafo: rutas redundantes y ciclos no
        multiplican el trabajo. Empates deterministas por ID, sin limite de pila.
        """
        padres: dict[str, str | None] = {nid: None}
        pendientes = deque([nid])
        out: list[list[dict]] = []
        while pendientes:
            actual = pendientes.popleft()
            for a in sorted(self.motiva.get(actual, [])):
                if a in padres:
                    continue
                padres[a] = actual
                if self.caido(a):
                    cadena = []
                    paso = a
                    while paso != nid:
                        cadena.append(_paso(self.nodos[paso], "motivada_por"))
                        paso = padres[paso]
                    out.append(list(reversed(cadena)))
                elif self.nodos[a]["tipo"] == "decision":
                    pendientes.append(a)
        return out

    def cadenas_pregunta(self, nid: str) -> list[list[dict]]:
        """Para una pregunta contestada: la respuesta caida, o la respuesta (decision) con un respaldo
        caido (v5 §6.3: «si cae un respaldo de una pregunta contestada, se pide revisar su respuesta»)."""
        if self.nodos[nid].get("estado") != "contestada":
            return []
        out: list[list[dict]] = []
        for x in sorted(self.contesta.get(nid, [])):
            n = self.nodos[x]
            paso = _paso(n, "contesta")
            if self.caido(x):
                out.append([paso])
            elif n["tipo"] == "decision":
                out += [[paso, *c] for c in self.cadenas_decision(x)]
        return out

    def cadenas(self, nid: str) -> list[list[dict]]:
        tipo = self.nodos[nid]["tipo"]
        if tipo == "decision":
            return self.cadenas_decision(nid)
        if tipo == "pregunta":
            return self.cadenas_pregunta(nid)
        return []

    def aviso(self, nid: str) -> dict:
        n = self.nodos[nid]
        cadenas = self.cadenas(nid)
        return {
            "id": nid,
            "tipo": n["tipo"],
            "texto": n["texto"],
            "estado": n.get("estado"),
            "cadenas": cadenas,
            "respaldos_caidos": sorted({c[-1]["id"] for c in cadenas}),
        }


def apoyos_rechazados(pid: str) -> list[dict]:
    """Aviso «apoyo rechazado» (v5 §6.3), calculado desde el grafo sin cambiar nada: cada decision
    (vigente o no) que, directa o transitivamente por `motivada_por`, se apoya en un hallazgo
    rechazado, una medicion rechazada o una decision revertida; y cada pregunta contestada cuya
    respuesta cayo o se apoya en algo caido. Por nodo, las cadenas hasta cada respaldo caido."""
    with k._abrir(pid) as con:
        g = _Respaldos(con, pid)
    out = []
    for nid, n in sorted(g.nodos.items(), key=lambda kv: (kv[1]["tipo"], kv[0])):
        if n["tipo"] in ("decision", "pregunta"):
            a = g.aviso(nid)
            if a["cadenas"]:
                out.append(a)
    return out


def aviso(pid: str, nodo: str) -> dict:
    """El aviso de un solo nodo: sus cadenas hasta respaldos caidos (vacias si no tiene o si el tipo
    no se apoya en nada)."""
    with k._abrir(pid) as con:
        n = k._nodo(con, pid, nodo)
        g = _Respaldos(con, pid)
    if n["id"] not in g.nodos:
        return {
            "id": n["id"],
            "tipo": n["tipo"],
            "texto": n["texto"],
            "estado": n.get("estado"),
            "cadenas": [],
            "respaldos_caidos": [],
        }
    return g.aviso(n["id"])


def dependencias(pid: str, nodo: str) -> dict:
    """Lo que depende de un nodo: quien lo cita por motivada_por, apoya, derivada_de o contesta,
    transitivo (una decision motivada por una decision motivada por el hallazgo). Para ver que
    arrastra un rechazo antes de emitirlo. Cada dependiente una vez, con el salto, la relacion y el
    nodo por el que llego; un ciclo no se repite."""
    with k._abrir(pid) as con:
        n = k._nodo(con, pid, nodo)
        q = ",".join("?" * len(RELACIONES_DEPENDENCIA))
        citan: dict[str, list[tuple[str, str]]] = {}  # nodo -> [(quien depende de el, relacion)]
        for r in con.execute(
            f"SELECT v.de, v.relacion, v.a FROM vinculo v JOIN nodo x ON x.id = v.de"
            f" WHERE v.activo = 1 AND v.relacion IN ({q}) AND x.proyecto = ?",
            [*RELACIONES_DEPENDENCIA, pid],
        ):
            # en motivada_por, apoya y derivada_de depende el origen (`de`) del destino; en contesta
            # el vinculo va de la respuesta a la pregunta, y la que depende es la pregunta (`a`)
            if r["relacion"] == "contesta":
                citan.setdefault(r["de"], []).append((r["a"], "contesta"))
            else:
                citan.setdefault(r["a"], []).append((r["de"], r["relacion"]))
        vistos = {nodo}
        frontera = [nodo]
        salto = 0
        hallados: list[dict] = []
        while frontera:
            salto += 1
            siguiente = []
            for via in frontera:
                for de, rel in sorted(citan.get(via, [])):
                    if de in vistos:
                        continue
                    vistos.add(de)
                    siguiente.append(de)
                    hallados.append({"id": de, "relacion": rel, "via": via, "salto": salto})
            frontera = siguiente
        for h in hallados:
            d = k._nodo(con, pid, h["id"])
            h.update({"tipo": d["tipo"], "texto": d["texto"], "estado": d.get("estado")})
    return {
        "nodo": {"id": n["id"], "tipo": n["tipo"], "texto": n["texto"], "estado": n.get("estado")},
        "total": len(hallados),
        "dependientes": hallados,
    }


# --- 6.3 lecciones de un agente entre proyectos -----------------------------------------------


def lecciones(agente: str, *, modelo: str | None = None, proyectos: list[str] | None = None) -> dict:
    """Las reglas `vigente` o `cuestionada` con `ambito == "agente"` para ese agente en todos los
    proyectos registrados (o en `proyectos`), de solo lectura y con el proyecto de origen en cada
    una. Con `modelo`, las de ese modelo y las que no fijan modelo. No copia nada: la coordinadora
    decide si aplican al proyecto actual (v5 §6.3). Un proyecto que no se pudo abrir se informa en
    `no_disponibles`, no como vacio (v5 §4)."""
    agente = k._texto(agente, "agente", 100).lower()
    modelo = modelo.strip().lower() if isinstance(modelo, str) and modelo.strip() else None
    registrados = {p["id"]: p for p in k.proyectos()}
    pedidos = (
        [p.strip().lower() for p in proyectos if isinstance(p, str) and p.strip()] if proyectos else list(registrados)
    )
    reglas, incidentes, no_disponibles, consultados = [], [], [], []
    for pid in pedidos:
        if pid not in registrados:
            no_disponibles.append({"proyecto": pid, "error": "proyecto desconocido"})
            continue
        try:
            with k._abrir(pid) as con:
                filas = con.execute(
                    "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'regla' AND estado IN ('vigente','cuestionada')"
                    " AND json_extract(datos, '$.ambito') = 'agente' ORDER BY fecha, id",
                    (pid,),
                ).fetchall()
                inc = con.execute(
                    "SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'incidente'"
                    " AND lower(json_extract(datos, '$.agente')) = ? ORDER BY fecha DESC, id LIMIT ?",
                    (pid, agente, LIMITE_INCIDENTES_AGENTE),
                ).fetchall()
        except Exception as e:
            no_disponibles.append({"proyecto": pid, "error": str(e)})
            continue
        consultados.append(pid)
        for r in inc:
            i = k._fila(r)
            if modelo and i["datos"].get("modelo") and str(i["datos"]["modelo"]).lower() != modelo:
                continue
            incidentes.append({**_episodio(i), "proyecto": pid})
        for r in filas:
            regla = k._fila(r)
            d = regla["datos"]
            if str(d.get("agente") or "").lower() != agente:
                continue
            if modelo and d.get("modelo") and str(d["modelo"]).lower() != modelo:
                continue
            reglas.append({**regla, "proyecto": pid, "proyecto_nombre": registrados[pid].get("nombre")})
    return {
        "agente": agente,
        "modelo": modelo,
        "proyectos": consultados,
        "reglas": reglas,
        "incidentes": incidentes,  # v5 §4: como se comporta el agente; episodios, no lecciones
        "no_disponibles": no_disponibles,
    }
