"""Replica de la memoria por proyecto entre las PCs emparejadas (anexo C de
docs/propuesta-memoria-2026-10-08/v5.md), sobre el canal firmado que ya existe: `POST /peer/conocimiento`
con `{op, ...}` en el cuerpo (un POST para que la firma cubra los parametros).

- Cada PC escribe solo en su base. Cada `cambio` lleva la PC donde se origino y su seq alla
  (`pc`, `seq_origen`): una PC le pide a cada par los cambios que nacieron en el, desde su cursor, y
  los aplica en una transaccion junto con el cursor nuevo. Un corte a mitad no aplica nada ni mueve el
  cursor: la vuelta siguiente repite el lote, y (pc, seq_origen) unico lo vuelve idempotente.
- Un nodo se crea con su id (UUID, igual en todas las PCs; las sesiones con `id_de_sesion`). Si otro
  nodo local ya tiene su `clave_ingesta`, el remoto entra igual sin la clave y queda un duplicado
  sugerido, sin fusionar. Un cambio de estado o de datos gana si es el mas nuevo por (fecha, pc); si el
  nodo local ya no estaba como el remoto lo vio (`anterior`), queda un choque para la coordinadora. Los
  dos cambios quedan en el historial: ninguna revision se pierde.
- Un vinculo o un cambio cuyo nodo todavia no llego (lo creo una tercera PC) espera en
  `replica_pendiente` y se reintenta en cada vuelta.
- Las capturas (inmutables) se copian por id desde el rowid de origen. Los cuerpos de encargos e
  informes y los artefactos de evidencia se piden aparte y se verifican por hash cuando lo hay.
- Los proyectos se unen por remote (anexo A: el remote une la misma carpeta en dos PCs). Uno sin
  remote no se replica: no hay como saber que es el mismo. Uno que solo existe en el par se crea aca
  con su id (o `-2`) y sus remotes, sin carpeta en esta PC.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import traceback

import conocimiento as k
import identity
import state
from conocimiento import Rechazo

LOTE = 500  # cambios o capturas por pedido
CICLO_S = 120  # cada cuanto el server sincroniza con los pares vivos
_lock = threading.Lock()  # una sincronizacion a la vez por proceso
_sin_soporte: dict[str, float] = {}  # par viejo sin la ruta -> cuando se vio; se reintenta pasado SIN_SOPORTE_S
SIN_SOPORTE_S = 900  # la otra PC se actualiza con un pull: no se la saltea hasta el reinicio
_cuerpos_fallidos: dict[tuple[str, str, str], float] = {}  # (par, proyecto, ruta) -> cuando fallo
REINTENTO_CUERPO_S = 1800
SUBCARPETAS = ("rondas", "capturas", "evidencia")  # lo unico que un par puede pedir o traer

ACCIONES_DE_NODO = ("nodo", "estado", "datos", "texto", "conocimiento", "adopcion")
CAMPOS_NODO = ("tipo", "texto", "datos", "estado", "estado_fecha", "estado_por", "autor", "origen", "ronda", "fecha")


# --- lado que atiende: POST /peer/conocimiento ----------------------------------------------------


def atender(d: dict) -> tuple[int, dict]:
    """Lo que un par le pide a esta PC. Solo lectura: nunca escribe en la base de aca."""
    try:
        op = d.get("op")
        if op == "proyectos":
            return 200, {"pc": identity.pc_id(), "esquema": k.VERSION_ESQUEMA, "proyectos": _proyectos_replicables()}
        pid = k._texto(d.get("proyecto"), "proyecto", 64)
        k.proyecto(pid)
        if op == "cambios":
            return 200, _cambios_propios(pid, _entero(d.get("desde")), _entero(d.get("limite"), LOTE))
        if op == "capturas":
            return 200, _capturas_propias(pid, _entero(d.get("desde")), _entero(d.get("limite"), LOTE))
        if op == "cuerpo":
            return 200, _cuerpo(pid, k._texto(d.get("ruta"), "ruta", 300))
        return 400, {"error": f"op desconocida: {op}"}
    except Rechazo as e:
        return e.codigo, {"error": str(e)}


def _entero(v, defecto: int = 0) -> int:
    try:
        return max(0, int(v))
    except TypeError, ValueError:
        return defecto


def _proyectos_replicables() -> list[dict]:
    return [{"id": p["id"], "nombre": p.get("nombre"), "remotes": p.get("remotes") or []} for p in k.proyectos()]


def _cambios_propios(pid: str, desde: int, limite: int) -> dict:
    """Los cambios que nacieron en esta PC con seq de origen mayor que `desde`, en orden."""
    limite = max(1, min(limite, LOTE))
    yo = identity.pc_id()
    with k._abrir(pid) as con:
        filas = con.execute(
            "SELECT * FROM cambio WHERE proyecto = ? AND pc = ? AND seq_origen > ? ORDER BY seq_origen LIMIT ?",
            (pid, yo, desde, limite + 1),
        ).fetchall()
    out = [k._fila(r) for r in filas[:limite]]
    return {"pc": yo, "cambios": out, "hay_mas": len(filas) > limite}


def _capturas_propias(pid: str, desde: int, limite: int) -> dict:
    """Las capturas tomadas en esta PC (pc de la tarjeta = esta) con rowid mayor que `desde`."""
    limite = max(1, min(limite, LOTE))
    yo = identity.pc_id()
    with k._abrir(pid) as con:
        filas = con.execute(
            "SELECT rowid AS _rowid, * FROM captura WHERE proyecto = ? AND pc = ? AND rowid > ? ORDER BY rowid LIMIT ?",
            (pid, yo, desde, limite + 1),
        ).fetchall()
    out = [k._fila(r) for r in filas[:limite]]
    return {"pc": yo, "capturas": out, "hay_mas": len(filas) > limite}


def ruta_segura(pid: str, ruta) -> str | None:
    """La ruta absoluta de `ruta` si cae dentro de rondas/, capturas/ o evidencia/ del proyecto; si no,
    None. La usan los dos lados: el que atiende no entrega la base ni nada de afuera, y el que recibe no
    escribe donde diga un nodo de otra PC (`../..`)."""
    if not isinstance(ruta, str) or not ruta.strip():
        return None
    base = os.path.realpath(k._carpeta(pid))
    full = os.path.realpath(os.path.join(base, *ruta.replace("\\", "/").split("/")))
    if not any(full.startswith(os.path.join(base, sub) + os.sep) for sub in SUBCARPETAS):
        return None
    return full


def _cuerpo(pid: str, ruta: str) -> dict:
    full = ruta_segura(pid, ruta)
    if full is None or not os.path.isfile(full):
        raise Rechazo("cuerpo desconocido", 404)
    with open(full, "rb") as f:
        datos = f.read()
    return {"ruta": ruta, "base64": base64.b64encode(datos).decode("ascii")}


# --- lado que pide: sincronizar con un par --------------------------------------------------------


def _pedir(forward, pc: str, cuerpo: dict) -> dict:
    code, res = forward(pc, "POST", "/conocimiento", cuerpo)
    if code == 404 and "desconocida" in str((res or {}).get("error", "")):
        raise SinSoporte(pc)
    if code != 200:
        raise OSError(f"{pc}: {code} {(res or {}).get('error')}")
    return res


class SinSoporte(RuntimeError):
    """El par tiene un lienzo sin replica (no conoce la ruta)."""


def _proyecto_local(remoto: dict) -> str | None:
    """El proyecto de aca que comparte un remote con el del par, o uno nuevo (su id, o `-2`). None si el
    del par no tiene remote: no se puede saber que es el mismo."""
    remotes = [r for r in remoto.get("remotes") or [] if isinstance(r, str)]
    if not remotes:
        return None
    for p in k.proyectos():
        if set(remotes) & set(p.get("remotes") or []):
            libres = [r for r in remotes if r not in (p.get("remotes") or [])]
            otros = {r for q in k.proyectos() if q["id"] != p["id"] for r in q.get("remotes") or []}
            if libres and not set(libres) & otros:
                k.registrar_proyecto(p["id"], remotes=libres)
            return p["id"]
    base, i = remoto["id"][:56], 2  # el sufijo -N no puede pasar el largo de un id (64)
    pid = base
    while any(p["id"] == pid for p in k.proyectos()) or os.path.exists(k._carpeta(pid)):
        pid, i = f"{base}-{i}", i + 1
    k.registrar_proyecto(pid, remoto.get("nombre") or pid, remotes=remotes)
    state.log(f"replica: proyecto {pid} creado como copia del de otra PC ({', '.join(remotes)})")
    return pid


def sincronizar(pc: str, forward) -> dict:
    """Trae de `pc` lo que nacio alla, proyecto por proyecto. `forward(pc, metodo, ruta, cuerpo)` es
    mirror.MIRROR.forward (o el de las pruebas). Devuelve, por proyecto, cuanto se aplico."""
    with _lock:
        res = {"pc": pc, "proyectos": [], "sin_remote": []}
        lista = _pedir(forward, pc, {"op": "proyectos"})
        if lista.get("pc") == identity.pc_id():
            raise OSError("el par respondio con el pc_id de esta PC")
        if lista.get("esquema") != k.VERSION_ESQUEMA:
            # (pc, seq_origen) identifica un cambio en toda la base desde el esquema 4: con otro esquema los
            # numeros no se comparan. Se espera a que la otra PC se actualice (code review 2026-10-10)
            raise SinSoporte(pc)
        for remoto in lista.get("proyectos") or []:
            pid = None
            try:
                pid = _proyecto_local(remoto)
                if pid is None:
                    res["sin_remote"].append(remoto.get("id"))
                    continue
                res["proyectos"].append(_sincronizar_proyecto(pc, forward, remoto["id"], pid))
            except SinSoporte:
                raise
            except Exception as e:  # un proyecto roto no frena a los demas; queda dicho y en el log
                state.log(f"replica: {remoto.get('id')} de {pc}:\n{traceback.format_exc()}")
                res["proyectos"].append(
                    {"proyecto": pid, "remoto": remoto.get("id"), "error": f"{type(e).__name__}: {e}"}
                )
        return res


def _cursor(con, pc: str, remoto: str, clase: str) -> int:
    """El ultimo seq de origen (o rowid de captura) traido de `pc` para su proyecto `remoto`."""
    r = con.execute(
        "SELECT ultimo FROM replica_cursor WHERE peer = ? AND proyecto_remoto = ? AND clase = ?", (pc, remoto, clase)
    ).fetchone()
    return r[0] if r else 0


def _mover_cursor(con, pid: str, pc: str, remoto: str, clase: str, ultimo: int) -> None:
    con.execute(
        "INSERT INTO replica_cursor (peer, proyecto_remoto, clase, proyecto, ultimo, fecha) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT (peer, proyecto_remoto, clase) DO UPDATE SET ultimo = excluded.ultimo, fecha = excluded.fecha,"
        " proyecto = excluded.proyecto",
        (pc, remoto, clase, pid, ultimo, k.ahora()),
    )


def _sincronizar_proyecto(pc: str, forward, remoto: str, pid: str) -> dict:
    out = {"proyecto": pid, "remoto": remoto, "cambios": 0, "capturas": 0, "cuerpos": 0, "pendientes": 0}
    while True:
        with k._abrir(pid) as con:
            desde = _cursor(con, pc, remoto, "cambio")
        lote = _pedir(forward, pc, {"op": "cambios", "proyecto": remoto, "desde": desde, "limite": LOTE})
        cambios = lote.get("cambios") or []
        if cambios:
            with k._abrir(pid) as con:
                con.execute("BEGIN IMMEDIATE")
                for c in cambios:
                    if aplicar(con, pid, c):
                        out["cambios"] += 1
                _mover_cursor(con, pid, pc, remoto, "cambio", max(int(c["seq_origen"]) for c in cambios))
        if not lote.get("hay_mas"):
            break
    out["pendientes"] = _reintentar_pendientes(pid)
    while True:
        with k._abrir(pid) as con:
            desde = _cursor(con, pc, remoto, "captura")
        lote = _pedir(forward, pc, {"op": "capturas", "proyecto": remoto, "desde": desde, "limite": LOTE})
        caps = lote.get("capturas") or []
        if caps:
            with k._abrir(pid) as con:
                con.execute("BEGIN IMMEDIATE")
                for c in caps:
                    out["capturas"] += _aplicar_captura(con, pid, c)
                _mover_cursor(con, pid, pc, remoto, "captura", max(int(c["_rowid"]) for c in caps))
        if not lote.get("hay_mas"):
            break
    out["cuerpos"] = _traer_cuerpos(pc, forward, remoto, pid)
    with k._abrir(pid) as con:
        # la vuelta termino bien: el cursor queda aunque no haya llegado nada (asi se sabe que esta PC
        # replica con `pc` en este proyecto, y que los encargos a sus tarjetas se pueden vincular de aca)
        for clase in ("cambio", "captura"):
            _mover_cursor(con, pid, pc, remoto, clase, _cursor(con, pc, remoto, clase))
    return out


# --- aplicar ---------------------------------------------------------------------------------------


def aplicar(con: sqlite3.Connection, pid: str, c: dict) -> bool:
    """Aplica un cambio de otra PC en la transaccion del llamador. True si era nuevo. Uno que no se
    puede aplicar todavia (falta un nodo) queda en replica_pendiente; nunca levanta por eso."""
    if not c.get("pc") or c.get("seq_origen") is None:
        return False
    ya = con.execute("SELECT 1 FROM cambio WHERE pc = ? AND seq_origen = ?", (c["pc"], c["seq_origen"])).fetchone()
    if ya is not None:
        return False
    con.execute("SAVEPOINT replica")
    try:
        _aplicar(con, pid, c)
        con.execute("RELEASE replica")
        con.execute("DELETE FROM replica_pendiente WHERE pc = ? AND seq_origen = ?", (c["pc"], c["seq_origen"]))
        return True
    except sqlite3.IntegrityError as e:
        con.execute("ROLLBACK TO replica")
        con.execute("RELEASE replica")
        con.execute(
            "INSERT OR REPLACE INTO replica_pendiente (proyecto, pc, seq_origen, cambio, error, fecha)"
            " VALUES (?,?,?,?,?,?)",
            (pid, c["pc"], c["seq_origen"], k._json(c), str(e), k.ahora()),
        )
        return False


def _js(x):
    return x if isinstance(x, str) else k._json(x if x is not None else {})


def _aplicar(con, pid: str, c: dict) -> None:
    nuevo = c.get("nuevo") if isinstance(c.get("nuevo"), dict) else {}
    if c.get("accion") in ACCIONES_DE_NODO and nuevo.get("tipo") in k.TIPOS:
        _aplicar_nodo(con, pid, c, nuevo)
    elif c.get("accion") in ("vinculo", "vinculo_retirado") and nuevo.get("de") and nuevo.get("a"):
        _aplicar_vinculo(con, c, nuevo)
    # cualquier otra accion queda solo en el historial
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, de, relacion, a, accion, anterior, nuevo, autor, motivo, origen, fecha,"
        " pc, seq_origen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            pid,
            c.get("nodo_id"),
            c.get("de"),
            c.get("relacion"),
            c.get("a"),
            c["accion"],
            _js(c["anterior"]) if c.get("anterior") is not None else None,
            _js(nuevo),
            c.get("autor") or "?",
            c.get("motivo") or "",
            _js(c.get("origen")),
            c.get("fecha") or k.ahora(),
            c["pc"],
            c["seq_origen"],
        ),
    )


def _ultimo_cambio(con, nid: str) -> tuple[str, str] | None:
    r = con.execute(
        "SELECT fecha, pc FROM cambio WHERE nodo_id = ? ORDER BY fecha DESC, pc DESC LIMIT 1", (nid,)
    ).fetchone()
    return (r[0], r[1] or "") if r else None


def _aplicar_nodo(con, pid: str, c: dict, n: dict) -> None:
    nid = n["id"]
    actual = con.execute("SELECT * FROM nodo WHERE id = ?", (nid,)).fetchone()
    if actual is not None and actual["proyecto"] != pid:
        # el id existe en otro proyecto de esta base: no se pisa; espera con el error a la vista
        raise sqlite3.IntegrityError(f"el nodo {nid} ya es del proyecto {actual['proyecto']}")
    valores = {campo: n.get(campo) for campo in CAMPOS_NODO}
    valores["datos"] = _js(valores["datos"])
    valores["origen"] = _js(valores["origen"])
    if actual is None:
        clave = n.get("clave_ingesta")
        if clave:
            otro = con.execute("SELECT id FROM nodo WHERE proyecto = ? AND clave_ingesta = ?", (pid, clave)).fetchone()
            if otro is not None:
                # lo mismo registrado en las dos PCs con ids distintos: se sugiere, no se fusiona
                con.execute(
                    "INSERT OR IGNORE INTO replica_duplicado (proyecto, nodo_local, nodo_remoto, clave, fecha)"
                    " VALUES (?,?,?,?,?)",
                    (pid, otro[0], nid, clave, k.ahora()),
                )
                clave = None
        con.execute(
            "INSERT INTO nodo (id, proyecto, tipo, texto, datos, estado, estado_fecha, estado_por, autor, origen, ronda,"
            " fecha, clave_ingesta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, pid, *[valores[x] for x in CAMPOS_NODO], clave),
        )
        return
    ultimo = _ultimo_cambio(con, nid)
    remoto = (c.get("fecha") or "", c.get("pc") or "")
    anterior = c.get("anterior") if isinstance(c.get("anterior"), dict) else None
    loc = k._fila(actual)
    diverge = anterior is not None and any(loc.get(x) != anterior.get(x) for x in ("estado", "texto", "datos"))
    # choque solo si lo que se pisa nacio en esta PC: con tres PCs, C puede recibir la edicion de B
    # antes que la de A que B ya habia visto, y eso no es un choque (encargo B, code review 2026-10-09).
    # Un choque entre A y B lo registran A y B, que son quienes editaron
    if diverge and ultimo is not None and ultimo[1] == identity.pc_id():
        con.execute(
            "INSERT OR IGNORE INTO replica_conflicto (proyecto, nodo, pc, seq_origen, motivo, fecha) VALUES (?,?,?,?,?,?)",
            (
                pid,
                nid,
                c["pc"],
                c["seq_origen"],
                f"el nodo cambio aca y en {c['pc']} a la vez ({c['accion']}); gana el mas nuevo, los dos quedan en el historial",
                k.ahora(),
            ),
        )
    if ultimo is None or remoto >= ultimo:
        con.execute(
            "UPDATE nodo SET texto = ?, datos = ?, estado = ?, estado_fecha = ?, estado_por = ?, ronda = ? WHERE id = ?",
            (
                valores["texto"],
                valores["datos"],
                valores["estado"],
                valores["estado_fecha"],
                valores["estado_por"],
                valores["ronda"],
                nid,
            ),
        )


def _aplicar_vinculo(con, c: dict, v: dict) -> None:
    activo = 0 if c["accion"] == "vinculo_retirado" else int(v.get("activo", 1))
    actual = con.execute(
        "SELECT fecha FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (v["de"], v["relacion"], v["a"])
    ).fetchone()
    fecha = c.get("fecha") or v.get("fecha") or k.ahora()
    if actual is None:
        con.execute(
            "INSERT INTO vinculo (de, relacion, a, activo, fecha, autor, origen, motivo) VALUES (?,?,?,?,?,?,?,?)",
            (
                v["de"],
                v["relacion"],
                v["a"],
                activo,
                fecha,
                v.get("autor") or "?",
                _js(v.get("origen")),
                v.get("motivo"),
            ),
        )
    elif fecha >= actual[0]:
        con.execute(
            "UPDATE vinculo SET activo = ?, fecha = ?, autor = ?, origen = ?, motivo = ? WHERE de = ? AND relacion = ?"
            " AND a = ?",
            (
                activo,
                fecha,
                v.get("autor") or "?",
                _js(v.get("origen")),
                v.get("motivo"),
                v["de"],
                v["relacion"],
                v["a"],
            ),
        )


def _reintentar_pendientes(pid: str) -> int:
    """Los cambios que esperaban un nodo de otra PC: se reintentan en orden. Devuelve los que siguen."""
    with k._abrir(pid) as con:
        con.execute("BEGIN IMMEDIATE")
        for (cambio,) in con.execute(
            "SELECT cambio FROM replica_pendiente WHERE proyecto = ? ORDER BY fecha, pc, seq_origen", (pid,)
        ).fetchall():
            aplicar(con, pid, json.loads(cambio))
        return con.execute("SELECT COUNT(*) FROM replica_pendiente WHERE proyecto = ?", (pid,)).fetchone()[0]


def _aplicar_captura(con, pid: str, c: dict) -> int:
    """Una captura de otra PC, por id. Una que ya esta se saltea; una mal formada levanta (NOT NULL o
    CHECK): el lote no se aplica, el cursor no avanza y el error queda a la vista, en vez de que un
    INSERT OR IGNORE la descarte en silencio (code review 2026-10-09)."""
    if con.execute("SELECT 1 FROM captura WHERE id = ?", (c.get("id"),)).fetchone() is not None:
        return 0
    sesion = c.get("sesion")
    if sesion and con.execute("SELECT 1 FROM nodo WHERE id = ?", (sesion,)).fetchone() is None:
        sesion = None
    cur = con.execute(
        "INSERT INTO captura (id, proyecto, clase, estado, session_id, sesion, agente, modelo, pc, origen,"
        " texto, bytes, hash, recortado, redactado, fecha, clave_ingesta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            c["id"],
            pid,
            c["clase"],
            "observado",
            c["session_id"],
            sesion,
            c.get("agente"),
            c.get("modelo"),
            c.get("pc"),
            _js(c.get("origen")),
            c["texto"],
            c["bytes"],
            c["hash"],
            c.get("recortado") or 0,
            c.get("redactado") or 0,
            c["fecha"],
            None if not c.get("clave_ingesta") else c["clave_ingesta"],
        ),
    )
    return cur.rowcount


def _traer_cuerpos(pc: str, forward, remoto: str, pid: str) -> int:
    """Los cuerpos y artefactos que los nodos citan y no estan en disco: se piden al par, se verifican
    por hash si el nodo lo trae, y entran al indice de prosa."""
    with k._abrir(pid) as con:
        faltan = []
        for r in con.execute(
            "SELECT id, tipo, datos FROM nodo WHERE proyecto = ? AND tipo IN ('encargo','informe','evidencia')", (pid,)
        ):
            d = json.loads(r["datos"])
            ruta = d.get("ruta") if r["tipo"] != "evidencia" else (d.get("referencia") if d.get("recibida") else None)
            full = ruta_segura(pid, ruta)
            if ruta is not None and full is None:
                state.log(f"replica: {r['id']} cita una ruta fuera del proyecto ({ruta!r}): no se trae")
                continue
            if full is not None and not os.path.isfile(full):
                faltan.append((r["id"], r["tipo"], ruta, full, d.get("hash")))
    hechos = 0
    ahora = time.monotonic()
    for nid, tipo, ruta, full, sha in faltan:
        clave = (pc, remoto, ruta)
        if ahora - _cuerpos_fallidos.get(clave, -REINTENTO_CUERPO_S) < REINTENTO_CUERPO_S:
            continue  # ese par no lo tenia hace poco (un nodo de una tercera PC): no se pide cada vuelta
        try:
            res = _pedir(forward, pc, {"op": "cuerpo", "proyecto": remoto, "ruta": ruta})
            datos = base64.b64decode(res["base64"])
        except (OSError, KeyError, ValueError) as e:
            _cuerpos_fallidos[clave] = ahora
            state.log(f"replica: cuerpo {ruta} de {pc}: {e}")
            continue
        if (
            sha
            and hashlib.sha256(datos).hexdigest() != sha
            and hashlib.sha256(datos.replace(b"\r\n", b"\n")).hexdigest() != sha
        ):
            state.log(f"replica: cuerpo {ruta} de {pc} no coincide con su hash: no se guarda")
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        k.escribir_exacto(full, datos)
        _cuerpos_fallidos.pop(clave, None)
        if tipo in ("encargo", "informe"):
            with k._abrir(pid) as con:
                con.execute(
                    "INSERT INTO prosa_fts (nodo, texto) VALUES (?, ?)", (nid, datos.decode("utf-8", "replace"))
                )
        hechos += 1
    return hechos


# --- estado y bucle --------------------------------------------------------------------------------


def estado(pid: str) -> dict:
    """Cursores por par, choques y duplicados para la coordinadora, y cambios que esperan."""
    with k._abrir(pid) as con:
        return {
            "proyecto": pid,
            "cursores": [
                dict(r)
                for r in con.execute("SELECT * FROM replica_cursor WHERE proyecto = ? ORDER BY peer, clase", (pid,))
            ],
            "conflictos": [
                dict(r) for r in con.execute("SELECT * FROM replica_conflicto WHERE proyecto = ? ORDER BY id", (pid,))
            ],
            "duplicados": [
                dict(r)
                for r in con.execute("SELECT * FROM replica_duplicado WHERE proyecto = ? ORDER BY fecha", (pid,))
            ],
            "pendientes": [
                {kk: r[kk] for kk in ("pc", "seq_origen", "error", "fecha")}
                for r in con.execute("SELECT * FROM replica_pendiente WHERE proyecto = ? ORDER BY fecha", (pid,))
            ],
        }


def sincronizar_todos(mirror) -> list[dict]:
    """Una vuelta con cada par vivo. Un par viejo (sin la ruta) se avisa una vez y se saltea."""
    out = []
    ahora = time.monotonic()
    for p in mirror.peers_status():
        pc = p.get("pc_id")
        if not pc or not p.get("alive") or ahora - _sin_soporte.get(pc, -SIN_SOPORTE_S) < SIN_SOPORTE_S:
            continue
        try:
            out.append(sincronizar(pc, mirror.forward))
            _sin_soporte.pop(pc, None)
        except SinSoporte:
            if pc not in _sin_soporte:
                state.log(
                    f"replica: {p.get('name') or pc} tiene un lienzo sin replica de la memoria; se reintenta en 15 min"
                )
            _sin_soporte[pc] = ahora
        except Exception as e:  # un par roto no frena a los demas
            state.log(f"replica: con {pc}:\n{traceback.format_exc()}")
            out.append({"pc": pc, "error": f"{type(e).__name__}: {e}"})
    return out


def bucle(mirror, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    while not stop.wait(CICLO_S):
        try:
            for r in sincronizar_todos(mirror):
                n = sum(p.get("cambios", 0) + p.get("capturas", 0) for p in r.get("proyectos", []))
                if n or r.get("error"):
                    state.log(
                        f"replica con {r['pc']}: {n} aplicados" + (f", error {r['error']}" if r.get("error") else "")
                    )
        except Exception:
            state.log(f"replica:\n{traceback.format_exc()}")
