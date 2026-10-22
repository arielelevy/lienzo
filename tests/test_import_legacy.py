"""Reimportacion de una base vieja por proyecto que siguio creciendo (PENDIENTES: «Resolver la reimportacion
legacy»). Cada fila de nodo y vinculo traida guarda de que base y de que revision viene (`importada_fila`):
una reimportacion actualiza lo que cambio alla si la fila central sigue como se importo (CAS por huella),
una repetida no cambia nada y lo editado aca despues de importar no se pisa, queda un choque a la vista.
Todo sobre bases sinteticas en un LIENZO_HOME temporal (conftest); ninguna base real."""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import replica

V1 = """
CREATE TABLE proyecto (id TEXT PRIMARY KEY, nombre TEXT NOT NULL, creado TEXT NOT NULL);
CREATE TABLE nodo (id TEXT PRIMARY KEY, proyecto TEXT NOT NULL, tipo TEXT NOT NULL, texto TEXT NOT NULL,
  datos TEXT NOT NULL DEFAULT '{}', estado TEXT, estado_fecha TEXT, estado_por TEXT, autor TEXT NOT NULL,
  origen TEXT NOT NULL, ronda TEXT, fecha TEXT NOT NULL, clave_ingesta TEXT UNIQUE);
CREATE TABLE vinculo (de TEXT NOT NULL, relacion TEXT NOT NULL, a TEXT NOT NULL, activo INTEGER NOT NULL DEFAULT 1,
  fecha TEXT NOT NULL, autor TEXT NOT NULL, origen TEXT NOT NULL, motivo TEXT, PRIMARY KEY (de, relacion, a));
CREATE TABLE cambio (seq INTEGER PRIMARY KEY AUTOINCREMENT, proyecto TEXT NOT NULL, nodo_id TEXT, de TEXT,
  relacion TEXT, a TEXT, accion TEXT NOT NULL, anterior TEXT, nuevo TEXT NOT NULL, autor TEXT NOT NULL,
  motivo TEXT NOT NULL, origen TEXT NOT NULL, fecha TEXT NOT NULL);
PRAGMA user_version = 1;
"""
F = "2026-10-08T21:00:00.000Z"
TARDE = "2026-10-09T10:00:00.000Z"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    monkeypatch.setattr(k.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(k, "_revisadas", set())
    # el server viejo tiene la base abierta: no se renombra y la proxima apertura la vuelve a leer
    monkeypatch.setattr(k, "_renombrar", lambda importadas: None)


def _vieja(pid="p") -> str:
    return os.path.join(k.raiz(), pid, "conocimiento.sqlite")


def base_vieja(pid="p"):
    """Una base del esquema 1 con una ronda, un encargo con cuerpo, un tema y un vinculo encargo -> tema."""
    carpeta = os.path.join(k.raiz(), pid)
    os.makedirs(os.path.join(carpeta, "rondas", "r"), exist_ok=True)
    with open(os.path.join(carpeta, "rondas", "r", "encargo-A.md"), "w", encoding="utf-8") as f:
        f.write("# Encargo\nhalving entero")
    con = sqlite3.connect(_vieja(pid))
    con.executescript(V1)
    con.execute("INSERT INTO proyecto VALUES (?,?,?)", (pid, pid, F))
    for nid, tipo, texto, datos, estado in (
        ("r-p", "ronda", "ronda 1", "{}", "abierta"),
        ("e-p", "encargo", "Encargo A", json.dumps({"ruta": "rondas/r/encargo-A.md", "letra": "A"}), "pendiente"),
        ("t-p", "tema", "halving", "{}", None),
    ):
        _nodo_viejo(con, pid, nid, tipo, texto, datos, estado)
    con.execute("INSERT INTO vinculo VALUES ('e-p','sobre','t-p',1,?,'c','{}',NULL)", (F,))
    con.commit()
    con.close()
    idx = k._leer_indice()
    idx["proyectos"][pid] = {"nombre": pid, "remotes": [], "carpetas": [], "creado": F}
    k._guardar_indice(idx)


def _nodo_viejo(con, pid, nid, tipo, texto, datos="{}", estado=None):
    con.execute(
        "INSERT INTO nodo (id, proyecto, tipo, texto, datos, estado, autor, origen, fecha) VALUES (?,?,?,?,?,?,?,?,?)",
        (nid, pid, tipo, texto, datos, estado, "c", "{}", F),
    )
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, accion, nuevo, autor, motivo, origen, fecha) VALUES (?,?,?,?,?,?,?,?)",
        (pid, nid, "nodo", json.dumps({"id": nid, "tipo": tipo, "texto": texto}), "c", "", "{}", F),
    )


def escribir_vieja(sql: str, args=(), motivo="tarde", nodo_id=None, vinculo=(None, None, None)):
    """El server viejo sigue escribiendo: la fila y su cambio en la base vieja (el de un vinculo lleva
    de, relacion y a, como los anota el server)."""
    con = sqlite3.connect(_vieja())
    con.execute(sql, args)
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, de, relacion, a, accion, nuevo, autor, motivo, origen, fecha)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("p", nodo_id, *vinculo, "estado", "{}", "c", motivo, "{}", TARDE),
    )
    con.commit()
    con.close()


def reabrir():
    """El proceso siguiente: vuelve a revisar las bases viejas al abrir la central."""
    k._revisadas.clear()
    return k.resumen("p")


def foto() -> dict:
    with sqlite3.connect(k.db_path()) as con:
        return {
            t: con.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
            for t in ("nodo", "vinculo", "cambio", "prosa_fts", "replica_conflicto", "importada_fila")
        } | {"importada": con.execute("SELECT ruta, proyecto, ultimo_seq FROM importada").fetchall()}


def _central(sql, args=()):
    with sqlite3.connect(k.db_path()) as con:
        return con.execute(sql, args).fetchall()


def test_la_procedencia_dice_de_que_base_y_revision_viene_cada_fila():
    base_vieja()
    reabrir()
    filas = _central("SELECT ruta, tabla, clave, revision FROM importada_fila ORDER BY tabla, clave")
    assert filas == [
        (_vieja(), "nodo", "e-p", 3),
        (_vieja(), "nodo", "r-p", 3),
        (_vieja(), "nodo", "t-p", 3),
        (_vieja(), "vinculo", json.dumps(["e-p", "sobre", "t-p"]), 3),
    ]


def test_una_reimportacion_trae_el_cambio_de_estado_y_el_cambio_entra_una_vez():
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET estado = 'cerrada', estado_fecha = ? WHERE id = 'r-p'", (TARDE,), nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "r-p")["estado"] == "cerrada"
    assert [c["motivo"] for c in k.cambios("p")].count("tarde") == 1
    assert _central("SELECT revision FROM importada_fila WHERE clave = 'r-p'") == [(4,)]
    assert _central("SELECT COUNT(*) FROM replica_conflicto") == [(0,)]


def test_un_vinculo_retirado_alla_queda_retirado_aca():
    base_vieja()
    reabrir()
    escribir_vieja(
        "UPDATE vinculo SET activo = 0, fecha = ? WHERE de = 'e-p'", (TARDE,), vinculo=("e-p", "sobre", "t-p")
    )
    reabrir()
    assert _central("SELECT activo FROM vinculo WHERE de = 'e-p' AND a = 't-p'") == [(0,)]


def test_un_informe_nuevo_de_la_base_vieja_entra_a_la_prosa():
    base_vieja()
    reabrir()
    os.makedirs(os.path.join(k.raiz(), "p", "rondas", "r"), exist_ok=True)
    with open(os.path.join(k.raiz(), "p", "rondas", "r", "informe-A-1.md"), "w", encoding="utf-8") as f:
        f.write("Informe: la cota de Lovasz no alcanza")
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "i-p", "informe", "Informe A", json.dumps({"ruta": "rondas/r/informe-A-1.md"}), "recibido")
    con.commit()
    con.close()
    reabrir()
    assert k.nodo("p", "i-p")["tipo"] == "informe"
    assert [x["nodo"] for x in k.buscar_prosa("p", "Lovasz")] == ["i-p"]
    assert _central("SELECT COUNT(*) FROM prosa_fts WHERE nodo = 'e-p'") == [(1,)]  # el viejo no se reindexa


def test_lo_editado_aca_y_alla_no_se_pisa_y_queda_un_choque_visible():
    base_vieja()
    reabrir()
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    escribir_vieja("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'", nodo_id="t-p")
    reabrir()
    n = k.nodo("p", "t-p")
    assert n["texto"] == "halving" and n["datos"] == {"nota": "aca"}
    choques = replica.estado("p")["conflictos"]
    assert len(choques) == 1 and choques[0]["nodo"] == "t-p" and "base vieja" in choques[0]["motivo"]
    assert _central("SELECT revision FROM importada_fila WHERE clave = 't-p'") == [(3,)]  # no avanza
    antes = foto()
    reabrir()
    assert foto() == antes  # el mismo choque no se registra dos veces


def test_lo_editado_aca_sin_cambio_alla_se_conserva_sin_choque():
    base_vieja()
    reabrir()
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "t-p")["datos"] == {"nota": "aca"}
    assert k.nodo("p", "r-p")["estado"] == "cerrada"
    assert replica.estado("p")["conflictos"] == []


def test_reimportar_sin_novedades_no_cambia_nada():
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    antes = foto()
    reabrir()
    reabrir()
    assert foto() == antes


def test_una_importacion_sin_procedencia_no_pisa_lo_que_cambio_alla():
    """Lo traido por el importador anterior no tiene procedencia: si cambio alla y aca esta distinto, no se
    sabe cual vale, asi que no se pisa; queda un choque. Lo que alla no cambio ni se mira."""
    base_vieja()
    reabrir()
    with sqlite3.connect(k.db_path()) as con:
        con.execute("DELETE FROM importada_fila")
    escribir_vieja("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'", nodo_id="t-p")
    reabrir()
    assert k.nodo("p", "t-p")["texto"] == "halving"
    assert [c["nodo"] for c in replica.estado("p")["conflictos"]] == ["t-p"]
    assert _central("SELECT COUNT(*) FROM importada_fila") == [(0,)]


def test_lo_editado_aca_sin_procedencia_no_es_choque_si_alla_cambio_otra_cosa():
    base_vieja()
    reabrir()
    with sqlite3.connect(k.db_path()) as con:
        con.execute("DELETE FROM importada_fila")
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "t-p")["datos"] == {"nota": "aca"}
    # r-p cambio alla y sin procedencia no se sabe si cambio aca: choque conservador. t-p, que alla no cambio, no
    assert [c["nodo"] for c in replica.estado("p")["conflictos"]] == ["r-p"]


def test_solo_se_miran_las_filas_que_nombra_el_historial_nuevo(monkeypatch):
    base_vieja()
    reabrir()
    vistas = []
    original = k._reimportar_fila

    def espia(con, pid, ruta, tabla, fila, revision):
        vistas.append((tabla, k._clave_fila(tabla, fila)))
        return original(con, pid, ruta, tabla, fila, revision)

    monkeypatch.setattr(k, "_reimportar_fila", espia)
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert vistas == [("nodo", "r-p")]


def _con_capturas():
    """La base vieja del esquema 3 tambien guarda capturas."""
    con = sqlite3.connect(_vieja())
    con.execute(
        "CREATE TABLE captura (id TEXT PRIMARY KEY, proyecto TEXT NOT NULL, clase TEXT NOT NULL, estado TEXT NOT NULL,"
        " session_id TEXT NOT NULL, sesion TEXT, agente TEXT, modelo TEXT, pc TEXT, origen TEXT NOT NULL,"
        " texto TEXT NOT NULL, bytes INTEGER NOT NULL, hash TEXT NOT NULL, recortado INTEGER NOT NULL,"
        " redactado INTEGER NOT NULL, fecha TEXT NOT NULL, clave_ingesta TEXT UNIQUE)"
    )
    con.commit()
    con.close()


def _captura_vieja(cid):
    """El server viejo captura sin escribir historial."""
    con = sqlite3.connect(_vieja())
    con.execute(
        "INSERT INTO captura VALUES (?,'p','pedido','observado','s1',NULL,NULL,NULL,NULL,'{}','hola',4,'h',0,0,?,NULL)",
        (cid, TARDE),
    )
    con.commit()
    con.close()


def test_una_captura_nueva_alla_entra_aunque_no_tenga_cambio():
    base_vieja()
    _con_capturas()
    reabrir()
    _captura_vieja("c1")
    reabrir()
    assert _central("SELECT id FROM captura") == [("c1",)]


def test_sin_tabla_de_historial_alla_una_fila_nueva_entra_igual():
    base_vieja()
    con = sqlite3.connect(_vieja())
    con.execute("DROP TABLE cambio")
    con.commit()
    con.close()
    reabrir()
    con = sqlite3.connect(_vieja())
    con.execute(
        "INSERT INTO nodo (id, proyecto, tipo, texto, autor, origen, fecha) VALUES ('n-p','p','tema','nuevo','c','{}',?)",
        (TARDE,),
    )
    con.commit()
    con.close()
    reabrir()
    assert k.nodo("p", "n-p")["texto"] == "nuevo"


def test_el_historial_de_un_choque_no_se_publica_como_propio():
    base_vieja()
    reabrir()
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    escribir_vieja("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'", motivo="choca", nodo_id="t-p")
    reabrir()
    assert [c["motivo"] for c in k.cambios("p")].count("choca") == 1  # queda en el historial
    propios = replica._cambios_propios("p", 0, 500)["cambios"]
    assert "choca" not in [c["motivo"] for c in propios]  # pero no viaja a los pares como de esta PC


def test_un_vinculo_de_otro_proyecto_no_se_pisa():
    central_antes(("t-p", "q", "tema de q", None), ("e-p", "q", "encargo de q", None))
    with sqlite3.connect(k.db_path()) as con:
        con.execute("INSERT INTO vinculo VALUES ('e-p','sobre','t-p',1,?,'c','{}',NULL)", (F,))
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE vinculo SET activo = 0 WHERE de = 'e-p'", vinculo=("e-p", "sobre", "t-p"))
    reabrir()
    assert _central("SELECT activo FROM vinculo WHERE de = 'e-p'") == [(1,)]
    assert any("proyecto q" in c["motivo"] for c in replica.estado("p")["conflictos"])


def test_una_diferencia_de_la_primera_importacion_no_se_describe_como_doble_edicion():
    central_antes(("t-p", "p", "halving de aca", None))
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'", nodo_id="t-p")
    reabrir()
    choques = replica.estado("p")["conflictos"]
    assert len(choques) == 1 and "cambiaron el mismo" not in choques[0]["motivo"]


def test_un_fallo_a_mitad_de_la_reimportacion_no_deja_nada_a_medias(monkeypatch):
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "i-p", "informe", "Informe A", json.dumps({"ruta": "rondas/r/informe.md"}), "recibido")
    con.commit()
    con.close()
    antes = foto()
    original = k._rellenar_prosa

    def falla(*a, **kw):
        raise OSError("disco")

    monkeypatch.setattr(k, "_rellenar_prosa", falla)
    reabrir()
    assert foto() == antes  # ni el estado, ni el nodo, ni el historial, ni el cursor
    monkeypatch.setattr(k, "_rellenar_prosa", original)
    reabrir()
    assert k.nodo("p", "r-p")["estado"] == "cerrada" and k.nodo("p", "i-p")["tipo"] == "informe"
    assert _central("SELECT ultimo_seq FROM importada") == [(5,)]


def test_un_nodo_nuevo_alla_con_la_clave_de_uno_de_aca_no_rompe_la_reimportacion():
    base_vieja()
    reabrir()
    aca = k.crear_nodo("p", "tema", "x", autor="c", clave_ingesta="tema:x")
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "x-p", "tema", "x alla")
    con.execute("UPDATE nodo SET clave_ingesta = 'tema:x' WHERE id = 'x-p'")
    con.commit()
    con.close()
    reabrir()
    assert k.nodo("p", "x-p")["texto"] == "x alla" and k.nodo("p", aca["id"])["texto"] == "x"
    assert [(d["nodo_local"], d["nodo_remoto"]) for d in replica.estado("p")["duplicados"]] == [(aca["id"], "x-p")]


# --- code review de la reimportacion (encargo B2, 2026-10-21) ---


def central_antes(*nodos):
    """La central ya existe (sin base vieja todavia) con estos nodos `(id, proyecto, texto, clave_ingesta)`:
    la primera importacion los encuentra."""
    for pid in {n[1] for n in nodos} | {"p"}:
        k.registrar_proyecto(pid)
    with sqlite3.connect(k.db_path()) as con:
        for nid, pid, texto, clave in nodos:
            con.execute(
                "INSERT INTO nodo (id, proyecto, tipo, texto, autor, origen, fecha, clave_ingesta)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (nid, pid, "tema", texto, "c", "{}", F, clave),
            )


def test_una_fila_nueva_que_viola_un_check_se_omite_sin_frenar_la_reimportacion():
    base_vieja()
    reabrir()
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "malo-p", "tipo-que-no-existe", "malo")  # el esquema 1 no tenia el CHECK de tipo
    con.commit()
    con.close()
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "r-p")["estado"] == "cerrada"  # lo demas entro
    assert _central("SELECT COUNT(*) FROM nodo WHERE id = 'malo-p'") == [(0,)]
    assert _central("SELECT ultimo_seq FROM importada") == [(5,)]  # el cursor avanzo


def test_una_actualizacion_que_viola_un_check_se_omite_sin_frenar_la_reimportacion():
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET datos = 'no es json' WHERE id = 't-p'", nodo_id="t-p")
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "r-p")["estado"] == "cerrada"
    assert k.nodo("p", "t-p")["datos"] == {}
    assert _central("SELECT ultimo_seq FROM importada") == [(5,)]


def test_una_clave_repetida_da_lo_mismo_en_la_primera_importacion_que_en_las_siguientes():
    central_antes(("aca-x", "p", "x", "tema:x"))
    base_vieja()
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "x-p", "tema", "x alla")
    con.execute("UPDATE nodo SET clave_ingesta = 'tema:x' WHERE id = 'x-p'")
    con.commit()
    con.close()
    reabrir()  # primera importacion
    assert k.nodo("p", "x-p")["texto"] == "x alla"
    assert [(d["nodo_local"], d["nodo_remoto"]) for d in replica.estado("p")["duplicados"]] == [("aca-x", "x-p")]
    antes = foto()
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()  # reimportacion: la clave repetida no cambia nada
    despues = foto()
    assert despues["replica_conflicto"] == antes["replica_conflicto"] == []
    assert _central("SELECT COUNT(*) FROM replica_duplicado") == [(1,)]
    assert [n for n in despues["nodo"] if n[0] == "x-p"] == [n for n in antes["nodo"] if n[0] == "x-p"]


def test_lo_que_ya_diferia_en_la_primera_importacion_no_es_un_choque_nuevo_al_reimportar():
    central_antes(("t-p", "p", "halving de aca", None))
    base_vieja()
    reabrir()  # primera: t-p ya estaba distinto y no se piso
    escribir_vieja("UPDATE nodo SET estado = 'cerrada' WHERE id = 'r-p'", nodo_id="r-p")
    reabrir()
    assert k.nodo("p", "t-p")["texto"] == "halving de aca"
    assert replica.estado("p")["conflictos"] == []


def test_si_la_base_vieja_no_tiene_cambios_nuevos_no_se_recorre_fila_por_fila(monkeypatch):
    base_vieja()
    reabrir()

    def no(*a, **kw):
        raise AssertionError("recorrio las filas sin cambios nuevos alla")

    monkeypatch.setattr(k, "_reimportar_fila", no)
    antes = foto()
    reabrir()
    assert foto() == antes


def test_un_id_que_es_de_otro_proyecto_queda_con_un_motivo_propio():
    central_antes(("t-p", "q", "tema de q", None))
    base_vieja()
    reabrir()
    escribir_vieja("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'", nodo_id="t-p")
    reabrir()
    assert _central("SELECT proyecto, texto FROM nodo WHERE id = 't-p'") == [("q", "tema de q")]
    choques = replica.estado("p")["conflictos"]
    assert len(choques) == 1 and "proyecto q" in choques[0]["motivo"]
    assert "cambiaron el mismo" not in choques[0]["motivo"] and "sin procedencia" not in choques[0]["motivo"]


def test_la_clave_repetida_se_resuelve_con_la_misma_funcion_que_la_replica(monkeypatch):
    llamadas = []
    original = k.clave_libre

    def espia(con, pid, nid, clave):
        llamadas.append(nid)
        return original(con, pid, nid, clave)

    monkeypatch.setattr(k, "clave_libre", espia)
    central_antes(("aca-x", "p", "x", "tema:x"))
    base_vieja()
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "x-p", "tema", "x alla")
    con.execute("UPDATE nodo SET clave_ingesta = 'tema:x' WHERE id = 'x-p'")
    con.commit()
    con.close()
    reabrir()
    assert "x-p" in llamadas
    with sqlite3.connect(k.db_path()) as c:
        c.row_factory = sqlite3.Row
        n = {"id": "y-r", "tipo": "tema", "texto": "y", "datos": {}, "autor": "c", "origen": {}, "fecha": F}
        replica._aplicar_nodo(c, "p", {"pc": "pcB", "seq_origen": 1}, {**n, "clave_ingesta": "tema:x"})
    assert "y-r" in llamadas


def test_con_indice_de_prosa_alla_se_copia_solo_la_de_lo_que_entra_sin_indice():
    base_vieja()
    con = sqlite3.connect(_vieja())
    con.execute("CREATE VIRTUAL TABLE prosa_fts USING fts5(nodo UNINDEXED, texto)")
    con.execute("INSERT INTO prosa_fts VALUES ('e-p', 'halving entero')")
    con.commit()
    con.close()
    reabrir()
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "i-p", "informe", "Informe A", json.dumps({"ruta": "rondas/r/informe.md"}), "recibido")
    con.execute("INSERT INTO prosa_fts VALUES ('i-p', 'la cota de Lovasz no alcanza')")
    con.commit()
    con.close()
    reabrir()
    assert [x["nodo"] for x in k.buscar_prosa("p", "Lovasz")] == ["i-p"]
    assert _central("SELECT nodo, COUNT(*) FROM prosa_fts GROUP BY nodo ORDER BY nodo") == [("e-p", 1), ("i-p", 1)]


def test_el_log_cuenta_las_nuevas(monkeypatch):
    base_vieja()
    reabrir()
    con = sqlite3.connect(_vieja())
    _nodo_viejo(con, "p", "n-p", "tema", "nuevo alla")
    con.commit()
    con.close()
    log = []
    monkeypatch.setattr(k.state, "log", log.append)
    reabrir()
    assert any("1 nuevas" in m for m in log), log


# --- segunda pasada del code review (encargo B2) ---


def test_el_historial_de_otra_pc_sobre_una_fila_no_aplicada_no_queda_como_ya_recibido():
    base_vieja()
    reabrir()
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    con = sqlite3.connect(_vieja())  # el server viejo recibio una edicion de pcB por la replica
    con.execute("ALTER TABLE cambio ADD COLUMN pc TEXT")
    con.execute("ALTER TABLE cambio ADD COLUMN seq_origen INTEGER")
    con.execute("UPDATE nodo SET texto = 'halving de B' WHERE id = 't-p'")
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, accion, nuevo, autor, motivo, origen, fecha, pc, seq_origen)"
        " VALUES ('p','t-p','texto','{}','c','de B','{}',?, 'pcB', 17)",
        (TARDE,),
    )
    con.commit()
    con.close()
    reabrir()
    assert k.nodo("p", "t-p")["texto"] == "halving"  # choque: no se aplico
    # cuando (pcB, 17) llegue por la replica no tiene que parecer ya aplicado
    assert _central("SELECT COUNT(*) FROM cambio WHERE pc = 'pcB' AND seq_origen = 17") == [(0,)]


def test_en_la_primera_importacion_un_id_de_otro_proyecto_no_se_publica_como_propio():
    central_antes(("t-p", "q", "halving", None))  # mismo contenido que alla, pero de q
    base_vieja()
    reabrir()
    propios = replica._cambios_propios("p", 0, 500)["cambios"]
    assert "t-p" not in [c["nodo_id"] for c in propios]


def test_un_informe_actualizado_alla_reindexa_su_prosa():
    base_vieja()
    reabrir()
    with open(os.path.join(k.raiz(), "p", "rondas", "r", "encargo-B.md"), "w", encoding="utf-8") as f:
        f.write("# Encargo\ncota de Lovasz")
    datos = json.dumps({"ruta": "rondas/r/encargo-B.md", "letra": "A"})
    escribir_vieja("UPDATE nodo SET datos = ? WHERE id = 'e-p'", (datos,), nodo_id="e-p")
    reabrir()
    assert [x["nodo"] for x in k.buscar_prosa("p", "Lovasz")] == ["e-p"]
    assert k.buscar_prosa("p", "halving entero") == []
    assert _central("SELECT COUNT(*) FROM prosa_fts WHERE nodo = 'e-p'") == [(1,)]


def test_sin_historial_alla_un_choque_ya_registrado_no_vuelve_a_escribir(monkeypatch):
    base_vieja()
    con = sqlite3.connect(_vieja())
    con.execute("DROP TABLE cambio")
    con.commit()
    con.close()
    reabrir()
    k.actualizar_datos("p", "t-p", {"nota": "aca"}, por="coordinadora:c")
    con = sqlite3.connect(_vieja())
    con.execute("UPDATE nodo SET texto = 'halving alla' WHERE id = 't-p'")
    con.commit()
    con.close()
    reabrir()
    assert len(replica.estado("p")["conflictos"]) == 1
    fecha = _central("SELECT fecha FROM importada")
    log = []
    monkeypatch.setattr(k.state, "log", log.append)
    reabrir()
    assert log == [] and _central("SELECT fecha FROM importada") == fecha


def test_una_captura_nueva_no_relee_la_prosa(monkeypatch):
    base_vieja()
    _con_capturas()
    reabrir()
    _captura_vieja("c1")

    def no(*a, **kw):
        raise AssertionError("releyo la prosa por una captura")

    monkeypatch.setattr(k, "_rellenar_prosa", no)
    reabrir()
    assert _central("SELECT id FROM captura") == [("c1",)]
