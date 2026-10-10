"""Conocimiento por proyecto, etapa 3 (docs/propuesta-memoria-2026-10-08/v5.md §5.3, §7 y §8.5):
veredictos de la coordinadora en una sola transaccion, pendientes de veredicto, duplicados sugeridos,
cierre de ronda con veredictos y «sin resolver» explicito, temas canonicos con aliases, briefing para
abrir una ronda, la cadena joins -> BM25 -> expansion (`preguntar`) y la vista en Markdown de un tema.

Usa `conocimiento` sin modificarlo. El cierre comparte una conexion con sus funciones publicas;
los veredictos registran tambien el inicio de vigencia de reglas. Los avisos de reglas cuestionadas
y apoyos rechazados requieren `aprendizaje` (frente D); los errores se propagan al llamador.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

import conocimiento as k
from conocimiento import Rechazo

ROLES_VEREDICTO = {k.C, k.P}
ESTADOS_PENDIENTES = ("propuesto", "propuesta", "observado", "abierta", "recibido")
TIPOS_PENDIENTES = ("informe", "hallazgo", "decision", "incidente", "regla", "medicion", "pregunta")
# (tipo, estado) -> seccion del briefing (v5 §4 y §7.2); lo que no esta aca va a `otros`
VIGENTE = {("decision", "vigente"), ("regla", "vigente"), ("medicion", "valida"), ("hallazgo", "confirmado")}
ABIERTO = {
    ("pregunta", "abierta"),
    ("hallazgo", "propuesto"),
    ("incidente", "observado"),
    ("incidente", "diagnosticado"),
    ("decision", "propuesta"),
    ("regla", "propuesta"),
    ("regla", "cuestionada"),
    ("medicion", "propuesta"),
    ("informe", "recibido"),
}
# en la vista, lo que espera veredicto se separa de lo abierto (preguntas, incidentes, cuestionadas)
ESPERA_VEREDICTO = {
    ("hallazgo", "propuesto"),
    ("decision", "propuesta"),
    ("regla", "propuesta"),
    ("medicion", "propuesta"),
}
RELACION_DUPLICADO = {
    "hallazgo": "mismo_que",
    "incidente": "repite",
    "decision": "reemplaza",
    "regla": "reemplaza",
    "medicion": "reemplaza",
}
UMBRAL_DUPLICADO = 0.5  # fraccion de palabras en comun (Jaccard) para proponer un par por BM25
PALABRA_MIN = 4
PALABRAS_MAX = 12
LIMITE_CAMBIOS = 500
BRIEFING_SIN_FILTRO = 100  # nodos vigentes o abiertos que trae un briefing sin archivos, temas ni consultas
LOCALIZADOR = re.compile(r"(::.*|:\d+(:\d+)?)$")  # tests/x.py::caso, codigo/a.py:88, a.py:88:4
NO_PALABRA = re.compile(r"[^a-z0-9]+")


# --- utilidades -----------------------------------------------------------------------------------


def normalizar(texto: str) -> str:
    """Minusculas, sin tildes, con una sola palabra entre espacios: lo que se compara en temas y duplicados."""
    s = unicodedata.normalize("NFKD", texto or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(NO_PALABRA.sub(" ", s).split())


def _palabras(texto: str) -> set[str]:
    return {w for w in normalizar(texto).split() if len(w) >= PALABRA_MIN}


def norm_ruta(ruta: str) -> str:
    """Una ruta como se compara (v5 §7.1): barras de /, minusculas, sin el localizador de linea o de caso."""
    r = (ruta or "").strip().replace("\\", "/")
    return LOCALIZADOR.sub("", r).strip("/").lower()


def ruta_bajo(ruta: str, archivo: str) -> bool:
    """`ruta` es `archivo` o esta debajo de el. Un prefijo de directorio exige el separador: `codigo/a/`
    no incluye `codigo/ab/` (v5 §7.1)."""
    r, a = norm_ruta(ruta), norm_ruta(archivo)
    return bool(a) and (r == a or r.startswith(a + "/"))


def _lista_textos(x, nombre: str, maximo: int = 50) -> list[str]:
    if x is None:
        return []
    if isinstance(x, str):
        x = [x]
    if not isinstance(x, list):
        raise Rechazo(f"{nombre} debe ser una lista")
    return [s.strip() for s in x if isinstance(s, str) and s.strip()][:maximo]


def _vinculos_de(con: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """Los vinculos activos que tocan cada id, en una consulta (json_each evita el tope de parametros)."""
    if not ids:
        return {}
    j = k._json(ids)
    out: dict[str, list[dict]] = {i: [] for i in ids}
    for r in con.execute(
        "SELECT * FROM vinculo WHERE activo = 1 AND (de IN (SELECT value FROM json_each(?))"
        " OR a IN (SELECT value FROM json_each(?)))",
        (j, j),
    ):
        v = k._fila(r)
        for lado in (v["de"], v["a"]):
            if lado in out:
                out[lado].append(v)
    return out


def _tema_por_texto(con: sqlite3.Connection, pid: str, ref: str) -> dict | None:
    """Un tema por id, por texto o por alias (sin tildes ni mayusculas)."""
    r = con.execute("SELECT * FROM nodo WHERE id = ? AND proyecto = ? AND tipo = 'tema'", (ref, pid)).fetchone()
    if r is not None:
        return k._fila(r)
    n = normalizar(ref)
    if not n:
        return None
    for r in con.execute("SELECT * FROM nodo WHERE proyecto = ? AND tipo = 'tema' ORDER BY fecha, id", (pid,)):
        t = k._fila(r)
        aliases = t["datos"].get("aliases") if isinstance(t["datos"], dict) else None
        if normalizar(t["texto"]) == n or any(normalizar(a) == n for a in (aliases or []) if isinstance(a, str)):
            return t
    return None


# --- veredictos (v5 §5.3) --------------------------------------------------------------------------


def _estado_en(con, pid, nid, nuevo, *, por, motivo, origen) -> dict:
    """`conocimiento.cambiar_estado` sobre la conexion del veredicto (misma tabla, mismos codigos, el
    mismo `vigente_desde` para reglas). El respaldo de §3.4 se difiere: `_respaldos` lo mira al final."""
    return k.cambiar_estado(pid, nid, nuevo, por=por, motivo=motivo, origen=origen, con=con, diferir_respaldo=True)


def _respaldos(con, pid, aplicados: list[dict], origen: dict) -> None:
    """Al final del veredicto: cada nodo que quedo en un estado «con respaldo» (corregido, resuelto,
    contestada, reemplazada, superada) lo tiene. Si no, 409 y la transaccion entera se revierte."""
    for a in aplicados:
        if a["accion"] != "estado" or not a.get("cambio"):
            continue  # un estado que ya estaba no se vuelve a juzgar
        n = k._nodo(con, pid, a["nodo"]["id"])
        if (falta := k.falta_respaldo(con, n["id"], n["tipo"], n["estado"], origen)) is not None:
            raise Rechazo(f"item {a['item']}: {falta}", 409)


def _cuestionar_si_repite(pid: str, aplicados: list[dict]) -> list[dict]:
    """Un `repite` confirmado puede dejar una regla con recurrencia posterior a su vigencia: se aplica
    la transicion del server en el acto (v5 §6.2), no cuando alguien se acuerde de pedirla."""
    if not any(a["accion"] == "vinculo" and a["vinculo"]["relacion"] == "repite" for a in aplicados):
        return []
    import aprendizaje

    return [r for r in aprendizaje.cuestionar(pid) if r.get("recien")]


def _retirar_en(con, pid, de, relacion, a, *, por, motivo, origen) -> dict:
    """`conocimiento.retirar_vinculo` sobre la conexion del veredicto."""
    r = con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
    if r is None:
        raise Rechazo("vinculo desconocido", 404)
    if not r["activo"]:
        return k._fila(r)
    con.execute("UPDATE vinculo SET activo = 0 WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a))
    v = k._fila(
        con.execute("SELECT * FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, relacion, a)).fetchone()
    )
    k._cambio(con, pid, "vinculo_retirado", por, motivo, origen, v, anterior=k._fila(r), de=de, relacion=relacion, a=a)
    return v


def _origen_veredicto(con, pid, revision, evidencia) -> dict:
    origen: dict = {"veredicto": True}
    if revision is not None:
        inf = k._nodo(con, pid, k._texto(revision, "revision", 64))
        if inf["tipo"] != "informe":
            raise Rechazo("revision debe ser el id de un informe")
        origen["revision"] = inf["id"]
    ev = _lista_textos(evidencia, "evidencia")
    for e in ev:
        if k._nodo(con, pid, e)["tipo"] != "evidencia":
            raise Rechazo(f"{e} no es una evidencia")
    if ev:
        origen["evidencia"] = ev
    return origen


def _item_en(con, pid, i, it, *, por, motivo, origen) -> dict:
    if not isinstance(it, dict):
        raise Rechazo(f"item {i}: debe ser un objeto")
    try:
        if "nodo" in it:
            nid = k._texto(it.get("nodo"), "nodo", 64)
            antes = k._nodo(con, pid, nid).get("estado")
            n = _estado_en(
                con, pid, nid, k._texto(it.get("estado"), "estado", 40), por=por, motivo=motivo, origen=origen
            )
            return {"item": i, "accion": "estado", "nodo": n, "cambio": antes != n.get("estado")}
        if "retirar" in it:
            r = k._objeto(it.get("retirar"), "retirar")
            v = _retirar_en(
                con,
                pid,
                k._texto(r.get("de"), "de", 64),
                k._texto(r.get("relacion"), "relacion", 40),
                k._texto(r.get("a"), "a", 64),
                por=por,
                motivo=it.get("motivo") or motivo,
                origen=origen,
            )
            return {"item": i, "accion": "vinculo_retirado", "vinculo": v}
        if "relacion" in it:
            v = k.vincular(
                pid,
                k._texto(it.get("de"), "de", 64),
                k._texto(it.get("relacion"), "relacion", 40),
                k._texto(it.get("a"), "a", 64),
                autor=por,
                origen=origen,
                motivo=it.get("motivo"),
                con=con,
            )
            return {"item": i, "accion": "vinculo", "vinculo": v}
    except Rechazo as e:
        raise Rechazo(f"item {i}: {e}", e.codigo) from e
    raise Rechazo(f"item {i}: debe traer nodo+estado, de+relacion+a o retirar")


def veredicto(pid: str, items: list, *, por: str, revision=None, evidencia=None, motivo: str = "") -> dict:
    """Aplica de una vez (una transaccion) una lista de items: `{"nodo", "estado"}`, `{"de", "relacion",
    "a", "motivo"?}` o `{"retirar": {"de", "relacion", "a"}}`. Respeta TRANSICIONES (409/403 como
    cambiar_estado); si un item falla no se aplica ninguno y el error dice la posicion. Cada cambio lleva
    en `origen` la `revision` (informe juzgado) y la `evidencia` (ids de nodos evidencia) si vienen.
    Solo `coordinadora:` o `persona:` emiten veredictos."""
    por = k._texto(por, "por", 200)
    if k.rol_de(por) not in ROLES_VEREDICTO:
        raise Rechazo(f"{k.rol_de(por) or '?'} no emite veredictos", 403)
    if not isinstance(items, list) or not items:
        raise Rechazo("items debe ser una lista no vacia")
    motivo = motivo or "veredicto"
    with k._abrir(pid) as con:
        origen = _origen_veredicto(con, pid, revision, evidencia)
        aplicados = [_item_en(con, pid, i, it, por=por, motivo=motivo, origen=origen) for i, it in enumerate(items)]
        _respaldos(con, pid, aplicados, origen)
    res = {"por": por, "origen": origen, "aplicados": aplicados, "n": len(aplicados)}
    if cuestionadas := _cuestionar_si_repite(pid, aplicados):
        res["reglas_cuestionadas"] = cuestionadas
    return res


# --- pendientes y duplicados ------------------------------------------------------------------------


def pendientes(pid: str, ronda: str | None = None) -> dict:
    """Lo que espera veredicto: informes `recibido` y nodos en el estado inicial de su tipo, por ronda y
    fecha, cada uno con sus vinculos activos. Con `ronda`, solo esa ronda (las entregas tardias conservan
    la ronda de origen, asi que entran, marcadas `tardia`)."""
    tipos = ",".join(f"'{t}'" for t in TIPOS_PENDIENTES)
    estados = ",".join(f"'{e}'" for e in ESTADOS_PENDIENTES)
    cond, args = [f"n.proyecto = ? AND n.tipo IN ({tipos}) AND n.estado IN ({estados})"], [pid]
    with k._abrir(pid) as con:
        cierre = None
        if ronda:
            rn = k._nodo(con, pid, ronda)
            if rn["tipo"] != "ronda":
                raise Rechazo("ronda no es una ronda")
            cond.append("n.ronda = ?")
            args.append(ronda)
            cierre = rn["estado_fecha"] if rn["estado"] == "cerrada" else None
        filas = con.execute(
            f"SELECT n.*, r.fecha AS ronda_fecha, r.estado_fecha AS ronda_cierre, r.estado AS ronda_estado FROM nodo n"
            f" LEFT JOIN nodo r ON r.id = n.ronda WHERE {' AND '.join(cond)}"
            " ORDER BY (n.ronda IS NULL), r.fecha, r.rowid, n.fecha, n.rowid",
            args,
        ).fetchall()
        out = [k._fila(r) for r in filas]
        vinculos = _vinculos_de(con, [n["id"] for n in out])
    for n in out:
        c = cierre if ronda else (n["ronda_cierre"] if n["ronda_estado"] == "cerrada" else None)
        n["tardia"] = bool(c and n["fecha"] > c)
        n["vinculos"] = vinculos.get(n["id"], [])
        for kk in ("ronda_fecha", "ronda_cierre", "ronda_estado"):
            n.pop(kk, None)
    with k._abrir(pid) as con:
        cond_e = ["proyecto = ? AND tipo = 'encargo' AND estado IN ('pendiente','enviado','sin_entrega')"]
        args_e = [pid]
        if ronda:
            cond_e.append("ronda = ?")
            args_e.append(ronda)
        encargos = [
            k._fila(r)
            for r in con.execute(f"SELECT * FROM nodo WHERE {' AND '.join(cond_e)} ORDER BY fecha, rowid", args_e)
        ]
    # v5 §4 «¿Que quedo abierto?»: tambien los encargos pendientes, enviados o sin entrega
    return {"ronda": ronda, "total": len(out), "pendientes": out, "encargos_abiertos": encargos}


def _informe_de(con: sqlite3.Connection, nid: str) -> str | None:
    r = con.execute(
        "SELECT a FROM vinculo WHERE de = ? AND relacion = 'declarado_en' AND activo = 1 ORDER BY fecha LIMIT 1", (nid,)
    ).fetchone()
    return r["a"] if r else None


def duplicados(pid: str, ronda: str | None = None) -> list[dict]:
    """Pares de nodos del mismo tipo con texto igual (normalizado) o parecido por BM25, declarados en
    informes distintos (revisiones del mismo encargo o rondas distintas): candidatos a `mismo_que`
    (hallazgo), `repite` (incidente) o `reemplaza` (decision, regla, medicion). No vincula nada: la
    coordinadora decide con un veredicto `{"de": b, "relacion": ..., "a": a}` (b es el posterior).
    Con `ronda`, al menos uno de los dos es de esa ronda."""
    tipos = ",".join(f"'{t}'" for t in RELACION_DUPLICADO)
    out, vistos = [], set()
    with k._abrir(pid) as con:
        nodos = [
            k._fila(r)
            for r in con.execute(
                f"SELECT * FROM nodo WHERE proyecto = ? AND tipo IN ({tipos}) ORDER BY fecha, id", (pid,)
            )
        ]
        if not nodos:
            return []
        informe = {n["id"]: _informe_de(con, n["id"]) for n in nodos}
        por_id = {n["id"]: n for n in nodos}
        ya = {
            (r["de"], r["a"])
            for r in con.execute(
                "SELECT de, a FROM vinculo WHERE activo = 1 AND relacion IN ('mismo_que','repite','reemplaza')"
            )
        }
        for n in nodos:
            palabras = _palabras(n["texto"])
            candidatos: dict[str, float] = {}
            if palabras:
                consulta = " OR ".join(f'"{w}"' for w in sorted(palabras)[:PALABRAS_MAX])
                for r in con.execute(
                    "SELECT n.id, bm25(nodo_fts, 3.0, 1.0) AS puntaje FROM nodo_fts JOIN nodo n ON n.rowid = nodo_fts.rowid"
                    " WHERE nodo_fts MATCH ? AND n.proyecto = ? AND n.tipo = ? AND n.id <> ? ORDER BY puntaje, n.id LIMIT 10",
                    (consulta, pid, n["tipo"], n["id"]),
                ):
                    candidatos[r["id"]] = r["puntaje"]
            # texto igual aunque BM25 no lo traiga (palabras cortas)
            mio = normalizar(n["texto"])
            for o in nodos:
                if o["id"] != n["id"] and o["tipo"] == n["tipo"] and normalizar(o["texto"]) == mio:
                    candidatos.setdefault(o["id"], 0.0)
            for oid, bm in candidatos.items():
                o = por_id[oid]
                par = tuple(sorted((n["id"], oid)))
                if par in vistos:
                    continue
                if ronda and ronda not in (n["ronda"], o["ronda"]):
                    continue
                if informe[n["id"]] and informe[n["id"]] == informe[oid]:
                    continue  # dos cosas parecidas en el mismo informe las quiso asi el frente
                if par in ya or (par[1], par[0]) in ya:
                    continue
                otras = _palabras(o["texto"])
                if mio == normalizar(o["texto"]):
                    puntaje, motivo = 1.0, "texto igual"
                else:
                    comunes = palabras & otras
                    puntaje = len(comunes) / len(palabras | otras) if palabras | otras else 0.0
                    if puntaje < UMBRAL_DUPLICADO:
                        continue
                    motivo = f"bm25 {bm:.1f}, {len(comunes)} palabras en comun: {', '.join(sorted(comunes)[:6])}"
                vistos.add(par)
                a, b = (o, n) if (o["fecha"], o["id"]) < (n["fecha"], n["id"]) else (n, o)
                out.append(
                    {
                        "a": a["id"],
                        "b": b["id"],
                        "tipo": n["tipo"],
                        "relacion": RELACION_DUPLICADO[n["tipo"]],
                        "texto_a": a["texto"],
                        "texto_b": b["texto"],
                        "ronda_a": a["ronda"],
                        "ronda_b": b["ronda"],
                        "motivo": motivo,
                        "puntaje": round(puntaje, 3),
                    }
                )
    out.sort(key=lambda d: (-d["puntaje"], d["tipo"], d["a"], d["b"]))
    return out


# --- cierre con veredictos --------------------------------------------------------------------------


def cerrar_ronda(pid: str, ronda: str, *, por: str, veredictos=None, sin_resolver=None, motivo: str = "") -> dict:
    """Aplica los veredictos (cada uno `{items, revision?, evidencia?, motivo?}`, o items sueltos que
    forman un solo veredicto), anota en `datos.sin_resolver` de la ronda lo que se deja explicitamente sin
    resolver (`[{nodo, motivo}]`) y recien entonces cierra (conocimiento.cerrar_ronda escribe cierre_seq y
    rechaza cerrar dos veces). Toda la escritura comparte BEGIN IMMEDIATE y una conexion.
    Lo que sigue pendiente sin motivo vuelve en `pendientes`; no bloquea."""
    por = k._texto(por, "por", 200)
    if veredictos is not None and not isinstance(veredictos, list):
        raise Rechazo("veredictos debe ser una lista")
    lista = veredictos or []
    for i, item in enumerate(lista):
        if not isinstance(item, dict):
            raise Rechazo(f"veredictos[{i}]: debe ser un objeto")
    sueltos = [item for item in lista if "items" not in item]
    grupos = [item for item in lista if "items" in item]
    if sueltos:
        grupos.append({"items": sueltos})
    aplicados = []
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        rn = k._nodo(con, pid, ronda)
        if rn["tipo"] != "ronda":
            raise Rechazo("ronda no es una ronda")
        if rn["estado"] == "cerrada":
            raise Rechazo("la ronda ya esta cerrada", 409)
        permitidos = k.TRANSICIONES.get("ronda", {}).get((rn["estado"], "cerrada"), set())
        if k.rol_de(por) not in permitidos:
            raise Rechazo("el actor no puede cerrar la ronda", 403)
        if sin_resolver is not None and not isinstance(sin_resolver, list):
            raise Rechazo("sin_resolver debe ser una lista")
        sr = []
        for i, x in enumerate(sin_resolver or []):
            if not isinstance(x, dict):
                raise Rechazo(f"sin_resolver[{i}]: debe ser un objeto")
            nid = k._texto(x.get("nodo"), f"sin_resolver[{i}].nodo", 64)
            k._nodo(con, pid, nid)
            sr.append({"nodo": nid, "motivo": k._texto(x.get("motivo"), f"sin_resolver[{i}].motivo", 1000)})
        for g in grupos:
            items = g.get("items")
            if not isinstance(items, list) or not items:
                raise Rechazo("items debe ser una lista no vacia")
            origen = _origen_veredicto(con, pid, g.get("revision"), g.get("evidencia"))
            resultados = [
                _item_en(con, pid, i, it, por=por, motivo=g.get("motivo") or motivo or "cierre de ronda", origen=origen)
                for i, it in enumerate(items)
            ]
            _respaldos(con, pid, resultados, origen)
            aplicados.append({"por": por, "origen": origen, "aplicados": resultados, "n": len(resultados)})
        if sr:
            fecha = k.ahora()
            k.actualizar_datos(
                pid,
                ronda,
                {"sin_resolver": [{**x, "por": por, "fecha": fecha} for x in sr]},
                por=por,
                motivo="sin resolver al cerrar",
                con=con,
            )
        cerrada = k.cerrar_ronda(pid, ronda, por=por, motivo=motivo, con=con)
    dejados = {x["nodo"] for x in sr}
    quedan = [p for p in pendientes(pid, ronda)["pendientes"] if p["id"] not in dejados]
    res = {"ronda": cerrada, "veredictos": aplicados, "sin_resolver": sr, "pendientes": quedan}
    if cuestionadas := _cuestionar_si_repite(pid, [a for g in aplicados for a in g["aplicados"]]):
        res["reglas_cuestionadas"] = cuestionadas
    return res


# --- temas canonicos --------------------------------------------------------------------------------


def tema(pid: str, texto: str, *, por: str, aliases=None) -> dict:
    """El tema canonico de `texto`: lo busca por texto o alias (sin tildes ni mayusculas); si existe, le
    suma los aliases nuevos (y el texto pedido si difiere del canonico); si no, lo crea."""
    texto = k._texto(texto, "texto", 200)
    por = k._texto(por, "por", 200)
    nuevos = _lista_textos(aliases, "aliases")
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        t = _tema_por_texto(con, pid, texto)
        if t is None:
            n = k.crear_nodo(pid, "tema", texto, {"aliases": nuevos}, autor=por, motivo="tema canonico", con=con)
            return {**n, "creado": True}
        actuales = [a for a in (t["datos"].get("aliases") or []) if isinstance(a, str)]
        conocidos = {normalizar(t["texto"])} | {normalizar(a) for a in actuales}
        agregar = []
        for a in [texto, *nuevos]:
            if normalizar(a) not in conocidos:
                agregar.append(a)
                conocidos.add(normalizar(a))
        if agregar:
            t = k.actualizar_datos(pid, t["id"], {"aliases": actuales + agregar}, por=por, motivo="aliases", con=con)
        return {**t, "creado": False, "aliases_nuevos": agregar}


def temas(pid: str) -> list[dict]:
    """Los temas con cuantos nodos distintos los citan (`sobre` o `aplica_a`), los mas citados primero."""
    with k._abrir(pid) as con:
        filas = con.execute(
            "SELECT t.id, t.texto, t.datos, t.fecha, COUNT(DISTINCT v.de) AS nodos FROM nodo t LEFT JOIN vinculo v"
            " ON v.a = t.id AND v.activo = 1 AND v.relacion IN ('sobre','aplica_a') WHERE t.proyecto = ? AND t.tipo = 'tema'"
            " GROUP BY t.id ORDER BY nodos DESC, t.texto, t.id",
            (pid,),
        ).fetchall()
    out = []
    for r in filas:
        f = k._fila(r)
        out.append(
            {"id": f["id"], "texto": f["texto"], "aliases": f["datos"].get("aliases") or [], "nodos": f["nodos"]}
        )
    return out


# --- recuperacion: joins -> BM25 -> expansion (v5 §7.1) ----------------------------------------------


class _Candidatos:
    """Un nodo entra una vez con todas sus procedencias; se conserva el mejor puntaje y el menor salto."""

    def __init__(self):
        self.nodos: dict[str, dict] = {}
        self.orden: list[str] = []

    def sumar(self, n: dict, procedencia: str, *, puntaje=None, salto=None, puesto=None) -> None:
        c = self.nodos.get(n["id"])
        if c is None:
            c = {
                kk: n.get(kk)
                for kk in (
                    "id",
                    "tipo",
                    "texto",
                    "estado",
                    "estado_fecha",
                    "estado_por",
                    "datos",
                    "ronda",
                    "fecha",
                    "autor",
                )
            }
            c["procedencia"] = []
            c["puntaje"] = None
            c["puesto"] = None
            c["salto"] = None
            self.nodos[n["id"]] = c
            self.orden.append(n["id"])
        if procedencia not in c["procedencia"]:
            c["procedencia"].append(procedencia)
        if puntaje is not None and (c["puntaje"] is None or puntaje < c["puntaje"]):
            c["puntaje"] = puntaje
        if salto is not None and (c["salto"] is None or salto < c["salto"]):
            c["salto"] = salto
        if puesto is not None and (c["puesto"] is None or puesto < c["puesto"]):
            c["puesto"] = puesto

    def lista(self) -> list[dict]:
        return [self.nodos[i] for i in self.orden]


def _joins(con, pid, cand: _Candidatos, archivos: list[str], temas_ref: list[str]) -> list[str]:
    """Capa 1 (v5 §7.1): nodos `sobre`/`aplica_a` los temas, y hallazgos, evidencias e incidentes cuyo
    `donde`/`referencia`/`archivo` cae bajo alguno de los archivos. Devuelve los temas no resueltos."""
    sin_tema = []
    for ref in temas_ref:
        t = _tema_por_texto(con, pid, ref)
        if t is None:
            sin_tema.append(ref)
            continue
        cand.sumar(t, "tema", salto=0)
        for r in con.execute(
            "SELECT n.* FROM vinculo v JOIN nodo n ON n.id = v.de WHERE v.a = ? AND v.activo = 1"
            " AND v.relacion IN ('sobre','aplica_a') AND n.proyecto = ? ORDER BY n.fecha, n.id",
            (t["id"], pid),
        ):
            cand.sumar(k._fila(r), "tema", salto=0)
    if archivos:
        for r in con.execute(
            "SELECT * FROM nodo WHERE proyecto = ? AND tipo IN ('hallazgo','evidencia','incidente')"
            " AND (json_extract(datos, '$.donde') IS NOT NULL OR json_extract(datos, '$.referencia') IS NOT NULL"
            " OR json_extract(datos, '$.archivo') IS NOT NULL) ORDER BY fecha, id",
            (pid,),
        ):
            n = k._fila(r)
            rutas = [n["datos"].get(c) for c in ("donde", "referencia", "archivo")]
            if any(isinstance(ru, str) and ruta_bajo(ru, a) for ru in rutas for a in archivos):
                cand.sumar(n, "archivo", salto=0)
    return sin_tema


def _bm25(pid, cand: _Candidatos, consultas: list[str], tipo: str | None) -> None:
    """Capa 2: cada consulta FTS por separado. Los puntajes de consultas distintas no se comparan entre
    si: un nodo conserva su mejor puesto en cualquiera de las listas (v5 §7.1, «combinando por mejor
    puesto de cada lista») y, aparte, su mejor puntaje."""
    for q in consultas:
        for i, h in enumerate(k.buscar(pid, q, tipo=tipo, limite=k.LIMITE_BUSQUEDA)):
            cand.sumar(h, f"bm25:{q}", puntaje=h["puntaje"], salto=0, puesto=i + 1)


def _expansion(pid, cand: _Candidatos, saltos: int) -> None:
    """Capa 3: vecinos a `saltos` de todas las semillas (joins y BM25), de a 30 porque `expandir` corta ahi."""
    if saltos <= 0:
        return
    semillas = list(cand.orden)
    for i in range(0, len(semillas), k.LIMITE_BUSQUEDA):
        for n in k.expandir(pid, semillas[i : i + k.LIMITE_BUSQUEDA], saltos=saltos):
            if n["salto"] > 0:
                cand.sumar(n, "expansion", salto=n["salto"])


def _recuperar(pid, *, archivos, temas_ref, consultas, tipo, saltos) -> tuple[_Candidatos, list[str]]:
    cand = _Candidatos()
    with k._abrir(pid) as con:
        sin_tema = _joins(con, pid, cand, archivos, temas_ref)
    _bm25(pid, cand, consultas, tipo)
    _expansion(pid, cand, saltos)
    return cand, sin_tema


def _apoyos_caidos(pid: str) -> dict[str, list[str]]:
    """id -> respaldos caidos, para marcar candidatos (decisiones y preguntas con apoyo rechazado)."""
    import aprendizaje

    return {a["id"]: a["respaldos_caidos"] for a in aprendizaje.apoyos_rechazados(pid)}


def _avisos(pid: str) -> dict:
    """Contrato: apoyos rechazados, reglas cuestionadas y grupos de recurrencias.
    Aprendizaje es obligatorio. Sus fallos se propagan, sin respuestas parciales."""
    import aprendizaje

    return {
        "disponible": True,
        "apoyos_rechazados": aprendizaje.apoyos_rechazados(pid),
        "reglas_cuestionadas": aprendizaje.reglas_cuestionadas(pid),
        "recurrencias": aprendizaje.recurrencias(pid),
    }


def _cambios_desde_cierre(pid: str) -> dict:
    """Los cambios posteriores al cierre de la ultima ronda cerrada (v5 §4), compactados: sin el nodo
    entero antes y despues, con tipo, texto y estado del resultado. La ultima es la de cierre mas nuevo
    por fecha, y el punto de corte es el seq LOCAL del cambio que anoto `cierre_seq`: si la ronda la
    cerro otra PC, su `cierre_seq` es del espacio de seq de alla y no se compara con el de aca
    (code review 2026-10-09)."""
    with k._abrir(pid) as con:
        r = con.execute(
            "SELECT id, json_extract(datos, '$.cierre_seq') AS seq FROM nodo WHERE proyecto = ? AND tipo = 'ronda'"
            " AND estado = 'cerrada' AND json_extract(datos, '$.cierre_seq') IS NOT NULL"
            " ORDER BY estado_fecha DESC, id LIMIT 1",
            (pid,),
        ).fetchone()
        ancla = None
        if r is not None:
            ancla = con.execute(
                "SELECT seq FROM cambio WHERE nodo_id = ? AND accion = 'datos' AND motivo = 'cierre_seq'"
                " ORDER BY seq DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
    # el ancla es el cambio que guardo cierre_seq: la lista empieza en el (como siempre: en la PC que
    # cerro, cierre_seq es justo el seq anterior al del ancla)
    desde = int(ancla["seq"]) - 1 if ancla else (int(r["seq"]) if r else 0)
    out = []
    for c in k.cambios(pid, desde=desde, limite=LIMITE_CAMBIOS):
        nuevo = c.get("nuevo") if isinstance(c.get("nuevo"), dict) else {}
        out.append(
            {
                "seq": c["seq"],
                "accion": c["accion"],
                "nodo": c.get("nodo_id") or nuevo.get("de"),
                "de": c.get("de"),
                "relacion": c.get("relacion"),
                "a": c.get("a"),
                "tipo": nuevo.get("tipo"),
                "texto": nuevo.get("texto"),
                "estado": nuevo.get("estado"),
                "autor": c["autor"],
                "motivo": c["motivo"],
                "fecha": c["fecha"],
            }
        )
    return {
        "ronda_cerrada": r["id"] if r else None,
        "desde_seq": desde,
        "cambios": out,
        "truncado": len(out) >= LIMITE_CAMBIOS,
    }


def briefing(pid: str, *, archivos=None, temas=None, consultas=None, desde_cierre: bool = True, encargos=None) -> dict:
    """Para abrir una ronda (v5 §7.2): joins por temas y archivos, BM25 por cada consulta y un salto de
    expansion; devuelve `vigente`, `abierto` y `otros` (sin repetir: un nodo con todas sus procedencias),
    `cambios` desde el cierre anterior y los `avisos` del modulo obligatorio aprendizaje. `encargos`
    (ids) suma los archivos que cada encargo declaro (v5 §7.2: «parte de archivos/temas» del encargo)."""
    archivos = _lista_textos(archivos, "archivos")
    for eid in _lista_textos(encargos, "encargos"):
        with k._abrir(pid) as con:
            e = k._nodo(con, pid, eid)
        if e["tipo"] != "encargo":
            raise Rechazo(f"{eid} no es un encargo")
        archivos += [a for a in e["datos"].get("archivos") or [] if isinstance(a, str) and a not in archivos]
    temas_ref = _lista_textos(temas, "temas")
    consultas = _lista_textos(consultas, "consultas", 10)
    if archivos or temas_ref or consultas:
        cand, sin_tema = _recuperar(
            pid, archivos=archivos, temas_ref=temas_ref, consultas=consultas, tipo=None, saltos=1
        )
    else:
        # sin de donde partir, el estado del proyecto: lo vigente y lo abierto mas reciente (antes devolvia
        # todo vacio y el briefing de una sesion que recien llega no decia nada)
        cand, sin_tema = _Candidatos(), []
        estados = sorted(VIGENTE | ABIERTO)
        cond = " OR ".join("(tipo = ? AND estado = ?)" for _ in estados)
        with k._abrir(pid) as con:
            for r in con.execute(
                f"SELECT * FROM nodo WHERE proyecto = ? AND ({cond}) ORDER BY fecha DESC, id LIMIT ?",
                [pid, *[x for par in estados for x in par], BRIEFING_SIN_FILTRO],
            ):
                cand.sumar(k._fila(r), "estado", salto=0)
    vigente, abierto, otros = [], [], []
    for n in cand.lista():
        clave = (n["tipo"], n["estado"])
        (vigente if clave in VIGENTE else abierto if clave in ABIERTO else otros).append(n)
    return {
        "proyecto": pid,
        "archivos": archivos,
        "temas": temas_ref,
        "temas_sin_resolver": sin_tema,
        "consultas": consultas,
        "vigente": vigente,
        "abierto": abierto,
        "otros": otros,
        "cambios": _cambios_desde_cierre(pid) if desde_cierre else None,
        "avisos": _avisos(pid),
    }


def preguntar(
    pid: str,
    consultas,
    *,
    archivos=None,
    temas=None,
    tipo=None,
    saltos: int = 1,
    offset: int = 0,
    limite: int = 100,
    prosa: bool = False,
) -> dict:
    """La cadena joins -> BM25 -> expansion (v5 §7.1) sin leer cuerpos: candidatos con procedencia,
    puntaje, salto y sus vinculos activos; los informes y encargos traen `ruta` para `leer_cuerpo`.
    `tipo` filtra las semillas BM25 (la expansion trae lo que las rodea). Pagina despues de
    recuperar todo: total sin recorte, siguientes como offset o None; limite entre 1 y 500.
    Con `prosa` (opt-in) suma `prosa`: BM25 de cada consulta sobre los cuerpos de encargos e informes y
    las capturas, marcado «prosa, no declarado» y sin mezclarse con los candidatos ni con su paginacion.
    Sin `prosa` la respuesta no cambia."""
    if type(offset) is not int or offset < 0:
        raise Rechazo("offset debe ser un entero no negativo")
    if type(limite) is not int or not 1 <= limite <= 500:
        raise Rechazo("limite debe ser un entero entre 1 y 500")
    consultas = _lista_textos(consultas, "consultas", 10)
    archivos = _lista_textos(archivos, "archivos")
    temas_ref = _lista_textos(temas, "temas")
    if not consultas and not archivos and not temas_ref:
        raise Rechazo("hace falta al menos una consulta, un archivo o un tema")
    saltos = max(0, min(int(saltos), k.SALTOS_MAX))
    cand, sin_tema = _recuperar(
        pid, archivos=archivos, temas_ref=temas_ref, consultas=consultas, tipo=tipo, saltos=saltos
    )
    out = cand.lista()
    with k._abrir(pid) as con:
        vinculos = _vinculos_de(con, [n["id"] for n in out])
    for n in out:
        n["vinculos"] = vinculos.get(n["id"], [])
        if n["tipo"] in ("informe", "encargo"):
            n["ruta"] = n["datos"].get("ruta")
    caidos = _apoyos_caidos(pid)
    for n in out:
        if n["id"] in caidos:
            n["apoyo_rechazado"] = caidos[n["id"]]  # v5 §6.3: el aviso acompana al candidato
    out.sort(
        key=lambda n: (
            n["salto"] if n["salto"] is not None else 9,
            # sin puesto (llego por tema o archivo) va despues de los de BM25, como antes del puesto
            n["puesto"] if n["puesto"] is not None else float("inf"),
            n["puntaje"] if n["puntaje"] is not None else 0,
            n["id"],
        )
    )
    res = {
        "proyecto": pid,
        "consultas": consultas,
        "temas_sin_resolver": sin_tema,
        "total": len(out),
        "offset": offset,
        "limite": limite,
        "siguientes": offset + limite if offset + limite < len(out) else None,
        "candidatos": out[offset : offset + limite],
    }
    if prosa:
        vistos, prosa_out = set(), []
        for q in consultas:
            for p in k.buscar_prosa(pid, q):
                clave = p.get("nodo") or p.get("captura")
                if clave not in vistos:
                    vistos.add(clave)
                    prosa_out.append({**p, "consulta": q})
        res["prosa"] = prosa_out
    return res


# --- vista en Markdown (v5 §7.2) ---------------------------------------------------------------------


def _linea(n: dict) -> str:
    extra = ""
    d = n.get("datos") or {}
    if n["tipo"] == "decision" and d.get("motivo"):
        extra = f" — motivo: {d['motivo']}"
    elif n["tipo"] == "hallazgo" and d.get("donde"):
        extra = f" — en {d['donde']}"
    elif n["tipo"] == "medicion" and "valor" in d:
        extra = f" — {d.get('metrica', '')} {d['valor']} {d.get('unidad', '')} ({d.get('condicion', '')})".rstrip()
    elif n["tipo"] == "regla" and d.get("vigente_desde"):
        extra = f" — vigente desde {d['vigente_desde']}"
    elif n["tipo"] == "pregunta" and d.get("para_quien"):
        extra = f" — para {d['para_quien']}"
    estado = f", {n['estado']}" if n.get("estado") else ""
    return f"- [{n['tipo']}{estado}] {n['texto']}{extra} (nodo:{n['id']})"


def briefing_markdown(b: dict) -> str:
    """El briefing como texto para pegar en un encargo (v5 §9, etapa 5: «texto generado para los
    encargos»): vigente, abierto, avisos y lo cambiado, cada linea con `nodo:<id>` para citar."""
    lineas = ["## Memoria del proyecto"]
    if b.get("archivos") or b.get("temas"):
        lineas.append(f"Partiendo de: {', '.join([*b.get('archivos', []), *b.get('temas', [])])}.")
    for titulo, items, vacio in (
        ("Vigente", b["vigente"], "nada vigente"),
        ("Abierto o esperando veredicto", b["abierto"], "nada abierto"),
    ):
        lineas.append(f"\n### {titulo}")
        if items:
            lineas.extend(_linea(n) for n in items)
        else:
            lineas.append(f"_{vacio}_")
    av = b.get("avisos") or {}
    avisos = [f"- apoyo rechazado: {x['texto']} (nodo:{x['id']})" for x in av.get("apoyos_rechazados", [])]
    avisos += [f"- regla cuestionada: {x['texto']} (nodo:{x['id']})" for x in av.get("reglas_cuestionadas", [])]
    lineas.append("\n### Avisos")
    lineas.extend(avisos or ["_sin avisos_"])
    cambios = (b.get("cambios") or {}).get("cambios") or []
    if cambios:
        lineas.append(f"\n### Cambios desde el ultimo cierre ({len(cambios)}, los ultimos 15)")
        for c in cambios[-15:]:
            que = c.get("texto") or c.get("relacion") or ""
            lineas.append(f"- {c['accion']} {c.get('tipo') or ''}: {que}".rstrip())
    lineas.append("\nCita estos ids en tu bloque de conocimiento como `nodo:<id>`.")
    return "\n".join(lineas)


_SQL_DESCARTE = """
WITH RECURSIVE cadena(id) AS (
  SELECT v.de FROM vinculo v JOIN nodo d ON d.id = v.de
  WHERE v.a = :alt AND v.relacion = 'descarta' AND v.activo = 1 AND d.proyecto = :p
  UNION
  SELECT v.a FROM cadena c JOIN vinculo v ON v.de = c.id AND v.activo = 1
  JOIN nodo n ON n.id = v.a AND n.proyecto = :p
  WHERE v.relacion IN ('motivada_por','apoya','confirmado_por')
)
SELECT n.*, (SELECT motivo FROM vinculo WHERE de = n.id AND relacion = 'descarta' AND a = :alt AND activo = 1)
  AS motivo_descarte
FROM cadena c JOIN nodo n ON n.id = c.id ORDER BY n.tipo, n.id
"""


def por_que_descartada(pid: str, alternativa: str) -> dict:
    """v5 §4 y §8.5 consulta 1: las decisiones que descartan la alternativa (con su motivo) y los
    fundamentos alcanzables por motivada_por, apoya y confirmado_por, incluidos estados no vigentes.
    `UNION` tolera ciclos. Tambien las decisiones que la eligen: la alternativa no tiene estado
    absoluto (§3.1). Cada nodo con un apoyo caido trae el aviso."""
    with k._abrir(pid) as con:
        a = k._nodo(con, pid, alternativa)
        if a["tipo"] != "alternativa":
            raise Rechazo(f"{alternativa} no es una alternativa")
        out = [k._fila(r) for r in con.execute(_SQL_DESCARTE, {"alt": alternativa, "p": pid}).fetchall()]
        elegida = [
            k._fila(r)
            for r in con.execute(
                "SELECT d.*, v.motivo AS motivo_eleccion FROM vinculo v JOIN nodo d ON d.id = v.de"
                " WHERE v.a = ? AND v.relacion = 'elige' AND v.activo = 1 ORDER BY d.fecha, d.id",
                (alternativa,),
            )
        ]
    caidos = _apoyos_caidos(pid)
    for n in out:
        if n["id"] in caidos:
            n["apoyo_rechazado"] = caidos[n["id"]]
    return {
        "alternativa": {"id": a["id"], "texto": a["texto"]},
        "descartada_por": [n for n in out if n.get("motivo_descarte")],
        "fundamentos": [n for n in out if not n.get("motivo_descarte")],
        "elegida_por": elegida,
    }


def vista(pid: str, tema_ref: str) -> dict:
    """Texto en Markdown para pegar en un encargo: lo vigente del tema, lo abierto, los avisos y lo que
    espera veredicto, cada linea con `nodo:<id>` para que el frente lo cite en su bloque."""
    with k._abrir(pid) as con:
        t = _tema_por_texto(con, pid, k._texto(tema_ref, "tema", 200))
    if t is None:
        raise Rechazo(f"tema desconocido: {tema_ref}", 404)
    b = briefing(pid, temas=[t["id"]], desde_cierre=False)
    aliases = [a for a in (t["datos"].get("aliases") or []) if isinstance(a, str)]
    lineas = [f"## Conocimiento del proyecto sobre «{t['texto']}» (nodo:{t['id']})"]
    if aliases:
        lineas.append(f"Tambien llamado: {', '.join(aliases)}.")
    directos = {n["id"] for n in b["vigente"] + b["abierto"] + b["otros"] if "tema" in n["procedencia"]}
    vigente = [n for n in b["vigente"] if n["id"] in directos]
    espera = [n for n in b["abierto"] if n["id"] in directos and (n["tipo"], n["estado"]) in ESPERA_VEREDICTO]
    abierto = [n for n in b["abierto"] if n["id"] in directos and (n["tipo"], n["estado"]) not in ESPERA_VEREDICTO]
    cerca = [n for n in b["vigente"] + b["abierto"] + b["otros"] if n["id"] not in directos]

    def seccion(titulo, items, vacio):
        lineas.append(f"\n### {titulo}")
        if items:
            lineas.extend(_linea(n) for n in items)
        else:
            lineas.append(f"_{vacio}_")

    seccion("Vigente", vigente, "nada vigente sobre este tema")
    seccion("Abierto", abierto, "sin preguntas ni incidentes abiertos")
    lineas.append("\n### Avisos")
    av = b["avisos"]
    hubo = False
    for nombre in ("apoyos_rechazados", "reglas_cuestionadas"):
        for x in av[nombre]:
            if isinstance(x, dict):
                hubo = True
                nid = x.get("id") or x.get("nodo")
                lineas.append(
                    f"- {nombre.replace('_', ' ')}: {x.get('texto') or x}" + (f" (nodo:{nid})" if nid else "")
                )
    if not hubo:
        lineas.append("_sin avisos_")
    seccion("Pendientes de veredicto", espera, "nada espera veredicto")
    if cerca:
        seccion("Relacionado (a un salto)", cerca, "")
    lineas.append(
        f"\nCita estos ids en tu bloque de conocimiento como `nodo:<id>`; el tema canonico es nodo:{t['id']}."
    )
    return {"tema": t["id"], "texto": t["texto"], "markdown": "\n".join(lineas)}
