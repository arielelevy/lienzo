"""Aprendizaje operativo (v5 §6, etapa 4): parecidos y recurrencia, reglas cuestionadas, apoyos
rechazados, dependencias y lecciones por agente entre proyectos. Sobre un LIENZO_HOME temporal
(conftest); los `repite` y los estados se ponen a mano como lo haria un veredicto de la coordinadora.

Revision de continuidad, 2026-10-08, Codex /root, modo secuencial:
Explorer: inspeccion estatica de aprendizaje.py, aprendizaje_api.py y conocimiento.py;
sin navegador ni server real (el encargo exige bases temporales).
Analyser: contraste con encargo-D y v5 secciones 6 y 8.5; umbrales 100/200 ms.
Designer: reutilizacion de casos existentes; correccion de tautologia, precedencia
del assert de API y xfail que ocultaba el umbral; medicion independiente del orden.
Executor: py -m pytest tests/test_aprendizaje.py tests/test_conocimiento.py -q
-p no:cacheprovider -s; salida 1, 38 passed y 1 failed en 9.22 s.
Detective: 40 episodios unicos, recurrencia 7.3 ms, evaluacion 26.2 ms,
cuestionar 489.6 ms, parecidos 10.5 ms; incumplimiento del umbral de escritura.
Code review focalizado: direcciones contesta/motivada_por, ciclos, idempotencia,
SQL parametrizado, errores y oraculos. Pendientes: dos transacciones por regla
(estado/datos no atomicos), corte BM25 a 100 antes del orden por herramienta,
y recursion de respaldos sin limite en grafos profundos.
Limitaciones: runner/compuerta y artefactos formales de los roles corresponden
a la coordinadora; no se aceptaron casos, mutaciones ni baseline. Registro aqui
porque el encargo permite escribir solamente estos tres archivos. No constituye
PASS de pruebas agenticas ni revision integral de dependencias.
"""

import os
import sys
import time
from itertools import pairwise

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import aprendizaje as ap
import aprendizaje_api as api
import conocimiento as k
from conocimiento import Rechazo

P = "teorema"
COORD = "coordinadora:test"
ANTES = "2020-01-01T00:00:00.000Z"  # vigente_desde anterior a todo lo que se crea en la prueba
DESPUES = "2999-01-01T00:00:00.000Z"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)


@pytest.fixture
def proy():
    return k.registrar_proyecto(P, "Teorema")


def _inc(texto, herramienta="permiso", agente="codex", fecha=None, pid=P, con=None):
    n = k.crear_nodo(pid, "incidente", texto, {"herramienta": herramienta, "agente": agente}, autor="f", con=con)
    if fecha:
        _fechar(n["id"], fecha, pid)
    return n["id"]


def _fechar(nid, fecha, pid=P):
    """Los incidentes nacen con ahora(); para ordenar y comparar con vigente_desde se les pone una fecha."""
    with k._abrir(pid) as con:
        con.execute("UPDATE nodo SET fecha = ? WHERE id = ?", (fecha, nid))


def _repite(nuevo, viejo, pid=P):
    k.vincular(pid, nuevo, "repite", viejo, autor=COORD)


def _regla(texto, origen, vigente_desde=ANTES, ambito="proyecto", agente=None, modelo=None, pid=P):
    datos = {"ambito": ambito}
    if agente:
        datos["agente"] = agente
    if modelo:
        datos["modelo"] = modelo
    r = k.crear_nodo(pid, "regla", texto, datos, autor="f")
    k.vincular(pid, r["id"], "derivada_de", origen, autor="f")
    k.cambiar_estado(pid, r["id"], "vigente", por=COORD, motivo="veredicto")  # ya pone vigente_desde
    if vigente_desde:
        k.actualizar_datos(pid, r["id"], {"vigente_desde": vigente_desde}, por=COORD, motivo="vigente_desde")
    else:
        # una regla vigente de antes del 2026-10-09, cuando esta ruta no ponia vigente_desde
        with k._abrir(pid) as con:
            d = k._nodo(con, pid, r["id"])["datos"]
            d.pop("vigente_desde", None)
            con.execute("UPDATE nodo SET datos = ? WHERE id = ?", (k._json(d), r["id"]))
    return r["id"]


def _dec(texto, pid=P):
    return k.crear_nodo(pid, "decision", texto, {"motivo": "m"}, autor="f")["id"]


# --- 6.1 parecidos y recurrencia ---------------------------------------------------------------


def test_parecidos_ordena_por_herramienta_y_agente_y_excluye_el_grupo_repite(proy):
    """La consulta 3 de v5 §8.5: candidatos lexicales, no recurrencias confirmadas."""
    yo = _inc("permiso denegado: Bash rm -rf en tests", "permiso", "codex")
    igual = _inc("permiso denegado: Bash rm en docs", "permiso", "codex")
    otra_h = _inc("error de API: Bash rm denegado", "api", "codex")
    otro_a = _inc("permiso denegado: Bash rm en src", "permiso", "claude")
    ninguno = _inc("permiso denegado al borrar con rm", "api", "claude")
    _inc("timeout de red al clonar", "red", "codex")  # ninguna palabra en comun
    viejo = _inc("permiso denegado: Bash rm -rf en tests (ayer)", "permiso", "codex")
    mas_viejo = _inc("permiso denegado: Bash rm -rf en tests (antes)", "permiso", "codex")
    _repite(yo, viejo)
    _repite(viejo, mas_viejo)  # transitivo: tampoco se propone
    res = ap.parecidos(P, yo)
    ids = [x["id"] for x in res]
    assert yo not in ids and viejo not in ids and mas_viejo not in ids
    assert ids[:2] == [igual, otro_a]  # misma herramienta primero; despues, mismo agente
    assert ids[0] == igual and set(ids[1:3]) == {otra_h, otro_a} and ids[3] == ninguno
    assert res[0]["misma_herramienta"] and res[0]["mismo_agente"] and res[0]["puntaje"] < 0
    assert set(res[0]) == {
        "id",
        "texto",
        "puntaje",
        "herramienta",
        "agente",
        "modelo",
        "fecha",
        "estado",
        "misma_herramienta",
        "mismo_agente",
    }
    assert [x["id"] for x in ap.parecidos(P, yo, limite=1)] == [igual]
    # nada escribio: el grupo de `yo` sigue siendo el de los repite confirmados
    assert ap.recurrencia(P, yo)["cantidad"] == 3


def test_parecidos_sin_palabras_o_sobre_algo_que_no_es_incidente(proy):
    vacio = _inc("?? !!")
    assert ap.parecidos(P, vacio) == []
    d = _dec("x")
    with pytest.raises(Rechazo):
        ap.parecidos(P, d)
    with pytest.raises(Rechazo) as e:
        ap.parecidos(P, "no-existe")
    assert e.value.codigo == 404
    # las palabras reservadas de FTS y los guiones van entre comillas, no rompen la consulta
    raro = _inc("and or not near rm-rf (x)")
    assert ap.consulta_fts("and or not near rm-rf (x)") == '"and" OR "or" OR "not" OR "near" OR "rm" OR "rf"'
    assert isinstance(ap.parecidos(P, raro), list)


def test_recurrencia_cuenta_cada_episodio_una_vez_en_las_dos_direcciones(proy):
    a = _inc("e1", fecha="2026-10-01T00:00:00.000Z")
    b = _inc("e2", fecha="2026-10-02T00:00:00.000Z")
    c = _inc("e3", fecha="2026-10-03T00:00:00.000Z")
    d = _inc("e4", fecha="2026-10-04T00:00:00.000Z")
    suelto = _inc("otro")
    _repite(b, a)
    _repite(c, b)
    _repite(c, a)  # ruta redundante hacia a
    _repite(d, b)  # d y c son hermanos: solo se alcanzan por b
    for x in (a, b, c, d):
        r = ap.recurrencia(P, x)
        assert r["cantidad"] == 4 and r["recurrente"]
        assert [e["id"] for e in r["episodios"]] == [a, b, c, d]
        assert r["primero"]["id"] == a and r["ultimo"]["id"] == d
    s = ap.recurrencia(P, suelto)
    assert s["cantidad"] == 1 and not s["recurrente"] and s["primero"]["id"] == suelto
    k.retirar_vinculo(P, d, "repite", b, por=COORD, motivo="no era lo mismo")
    assert ap.recurrencia(P, a)["cantidad"] == 3 and ap.recurrencia(P, d)["cantidad"] == 1


# --- 6.2 reglas cuestionadas -------------------------------------------------------------------


def test_cuestionar_pasa_a_cuestionada_solo_con_episodio_posterior_y_es_idempotente(proy):
    origen = _inc("permiso denegado: rm", fecha="2026-09-01T00:00:00.000Z")
    r_si = _regla("no usar rm -rf", origen, vigente_desde="2026-09-02T00:00:00.000Z")
    r_futura = _regla("regla recien puesta", origen, vigente_desde=DESPUES)  # el episodio es anterior
    r_sin_fecha = _regla("sin vigente_desde", origen, vigente_desde=None)
    d = _dec("decision")
    r_decision = _regla("derivada de una decision", d)
    tarde = _inc("permiso denegado: rm otra vez", fecha="2026-10-01T00:00:00.000Z")
    _repite(tarde, origen)
    res = ap.cuestionar(P)
    assert [x["id"] for x in res] == [r_si]
    f = res[0]
    assert f["recien"] and f["estado"] == "cuestionada" and f["episodios_posteriores"] == [tarde]
    assert f["recurrencias"] == 1 and f["episodios"][0]["id"] == tarde
    n = k.nodo(P, r_si)
    assert n["estado"] == "cuestionada" and n["estado_por"] == "server" and n["datos"]["vigente_desde"]
    assert n["datos"]["episodios_posteriores"] == [tarde]
    assert any(c["accion"] == "estado" and "recurrencia" in c["motivo"] for c in n["cambios"])
    for r in (r_futura, r_sin_fecha, r_decision):
        assert k.nodo(P, r)["estado"] == "vigente"
    # idempotente: la segunda pasada no toca nada y la regla sigue cuestionada, sin `recien`
    antes = len(k.cambios(P))
    res2 = ap.cuestionar(P)
    assert [x["id"] for x in res2] == [r_si] and not res2[0]["recien"]
    assert len(k.cambios(P)) == antes
    assert ap.cuestionar_regla(P, r_si)["motivo"] == "ya estaba cuestionada"


def test_cuestionar_regla_una_sola_y_sus_motivos(proy):
    origen = _inc("timeout", fecha="2026-09-01T00:00:00.000Z")
    r = _regla("reintentar con backoff", origen)
    assert ap.cuestionar_regla(P, r)["motivo"] == "sin episodios posteriores a vigente_desde"
    tarde = _inc("timeout de nuevo", fecha="2026-10-01T00:00:00.000Z")
    _repite(tarde, origen)
    f = ap.cuestionar_regla(P, r)
    assert f["cuestionada"] and f["episodios_posteriores"] == [tarde] and f["estado"] == "cuestionada"
    sin = _regla("sin fecha", origen, vigente_desde=None)
    assert ap.cuestionar_regla(P, sin)["motivo"] == "sin datos.vigente_desde"
    dec = _regla("de decision", _dec("d"))
    assert "decision" in ap.cuestionar_regla(P, dec)["motivo"]
    prop = k.crear_nodo(P, "regla", "propuesta", {"ambito": "proyecto"}, autor="f")["id"]
    assert ap.cuestionar_regla(P, prop)["motivo"] == "la regla esta propuesta, no vigente"
    with pytest.raises(Rechazo):
        ap.cuestionar_regla(P, origen)  # no es una regla


def test_cuestionar_recorre_el_grupo_transitivo_y_retirar_un_repite_no_devuelve_la_vigencia(proy):
    """La consulta 4 de v5 §8.5: episodios posteriores sin duplicar por caminos multiples; una regla
    con contador cero sigue cuestionada hasta el veredicto."""
    i1 = _inc("e1", fecha="2026-09-01T00:00:00.000Z")
    i2 = _inc("e2", fecha="2026-09-05T00:00:00.000Z")
    r = _regla("leccion", i2, vigente_desde="2026-09-06T00:00:00.000Z")  # derivada del segundo episodio
    _repite(i2, i1)
    i3 = _inc("e3", fecha="2026-10-01T00:00:00.000Z")
    i4 = _inc("e4", fecha="2026-10-02T00:00:00.000Z")
    _repite(i3, i1)  # la coordinadora lo colgo del canonico, no de i2: igual es el mismo grupo
    _repite(i4, i3)
    _repite(i4, i1)  # ruta redundante
    res = ap.cuestionar(P)
    assert res[0]["id"] == r and res[0]["episodios_posteriores"] == [i3, i4]  # i1 e i2 son anteriores
    k.retirar_vinculo(P, i3, "repite", i1, por=COORD, motivo="no era lo mismo")
    k.retirar_vinculo(P, i4, "repite", i1, por=COORD, motivo="no era lo mismo")
    q = ap.reglas_cuestionadas(P)
    assert q[0]["id"] == r and q[0]["recurrencias"] == 0 and q[0]["estado"] == "cuestionada"
    assert q[0]["episodios_posteriores"] == [i3, i4]  # lo que se vio al cuestionarla queda
    assert ap.cuestionar(P)[0]["recurrencias"] == 0
    # la coordinadora revalida: vuelve a vigente con un nuevo periodo
    k.cambiar_estado(P, r, "vigente", por=COORD, motivo="revalidada")
    k.actualizar_datos(P, r, {"vigente_desde": "2026-10-03T00:00:00.000Z"}, por=COORD)
    assert ap.cuestionar(P) == [] and ap.reglas_cuestionadas(P) == []


# --- 6.3 apoyos rechazados y dependencias -----------------------------------------------------


def _grafo_respaldos():
    """D1 -> H (rechazado); D2 -> D1 (transitivo); D3 -> M (medicion rechazada); D4 -> D5 (revertida);
    D6 -> H2 (confirmado): sin aviso. P1 contestada por H; P2 contestada por D2; P3 contestada por D6."""
    h = k.crear_nodo(P, "hallazgo", "pierde el invariante", {"gravedad": "alta"}, autor="f")["id"]
    h2 = k.crear_nodo(P, "hallazgo", "firme", {"gravedad": "baja"}, autor="f")["id"]
    m = k.crear_nodo(P, "medicion", "1e-9", {"metrica": "e", "valor": 1, "unidad": "1"}, autor="f")["id"]
    d1, d2, d3, d4, d5, d6 = (_dec(f"d{i}") for i in range(1, 7))
    k.vincular(P, d1, "motivada_por", h, autor="f")
    k.vincular(P, d2, "motivada_por", d1, autor="f")
    k.vincular(P, d3, "motivada_por", m, autor="f")
    k.vincular(P, d4, "motivada_por", d5, autor="f")
    k.vincular(P, d6, "motivada_por", h2, autor="f")
    k.vincular(P, d1, "motivada_por", d2, autor="f")  # ciclo d1 <-> d2: se tolera
    p1, p2, p3 = (k.crear_nodo(P, "pregunta", f"p{i}", {"para_quien": "ariel"}, autor="f")["id"] for i in range(1, 4))
    for fuente, preg in ((h, p1), (d2, p2), (d6, p3)):
        k.vincular(P, fuente, "contesta", preg, autor=COORD)
        k.cambiar_estado(P, preg, "contestada", por=COORD)
    k.cambiar_estado(P, h, "rechazado", por=COORD, motivo="refutado")
    k.cambiar_estado(P, h2, "confirmado", por=COORD)
    k.cambiar_estado(P, m, "rechazada", por=COORD, motivo="instrumento")
    k.cambiar_estado(P, d5, "vigente", por=COORD)
    k.cambiar_estado(P, d5, "revertida", por=COORD)
    k.cambiar_estado(P, d1, "vigente", por=COORD)  # vigente: igual lleva el aviso
    return {"h": h, "h2": h2, "m": m, "d": [d1, d2, d3, d4, d5, d6], "p": [p1, p2, p3]}


def test_apoyos_rechazados_directos_transitivos_y_de_preguntas_sin_cambiar_estados(proy):
    g = _grafo_respaldos()
    d1, d2, d3, d4, d5, d6 = g["d"]
    p1, p2, p3 = g["p"]
    antes = len(k.cambios(P))
    av = {a["id"]: a for a in ap.apoyos_rechazados(P)}
    assert set(av) == {d1, d2, d3, d4, p1, p2}
    assert av[d1]["estado"] == "vigente" and av[d1]["respaldos_caidos"] == [g["h"]]
    assert [[p["id"] for p in c] for c in av[d1]["cadenas"]] == [[g["h"]]]
    assert [[p["id"] for p in c] for c in av[d2]["cadenas"]] == [[d1, g["h"]]]
    assert av[d2]["cadenas"][0][-1]["estado"] == "rechazado" and av[d2]["cadenas"][0][0]["relacion"] == "motivada_por"
    assert av[d3]["respaldos_caidos"] == [g["m"]]
    assert av[d4]["respaldos_caidos"] == [d5] and av[d4]["cadenas"][0][0]["estado"] == "revertida"
    assert [[p["id"] for p in c] for c in av[p1]["cadenas"]] == [[g["h"]]]
    assert av[p1]["cadenas"][0][0]["relacion"] == "contesta"
    assert [[p["id"] for p in c] for c in av[p2]["cadenas"]] == [[d2, d1, g["h"]]]
    assert len(k.cambios(P)) == antes  # un aviso calculado: nada cambio
    assert ap.aviso(P, d6)["cadenas"] == [] and ap.aviso(P, p3)["cadenas"] == []
    assert ap.aviso(P, d2)["respaldos_caidos"] == [g["h"]]
    assert ap.aviso(P, g["h"])["cadenas"] == []  # un hallazgo no se apoya en nada
    t = k.crear_nodo(P, "tema", "t", autor="f")["id"]
    assert ap.aviso(P, t) == {
        "id": t,
        "tipo": "tema",
        "texto": "t",
        "estado": None,
        "cadenas": [],
        "respaldos_caidos": [],
    }
    # la pregunta vuelve a abierta: ya no pide revisar su respuesta
    k.cambiar_estado(P, p1, "abierta", por=COORD)
    assert p1 not in {a["id"] for a in ap.apoyos_rechazados(P)}


def test_dependencias_inversas_transitivas_con_ciclo(proy):
    g = _grafo_respaldos()
    d1, d2, d3, d4, d5, d6 = g["d"]
    p1, p2, p3 = g["p"]
    r = k.crear_nodo(P, "regla", "regla", {"ambito": "proyecto"}, autor="f")["id"]
    k.vincular(P, r, "derivada_de", d2, autor="f")
    ev = k.crear_nodo(P, "evidencia", "ev", {"clase": "prueba", "referencia": "x"}, autor="f")["id"]
    k.vincular(P, d1, "apoya", ev, autor="f")
    dep = ap.dependencias(P, g["h"])
    por_id = {x["id"]: x for x in dep["dependientes"]}
    assert dep["nodo"]["id"] == g["h"] and dep["total"] == 5
    assert set(por_id) == {d1, d2, p1, p2, r}
    assert por_id[d1] == {
        "id": d1,
        "relacion": "motivada_por",
        "via": g["h"],
        "salto": 1,
        "tipo": "decision",
        "texto": "d1",
        "estado": "vigente",
    }
    assert por_id[p1]["salto"] == 1 and por_id[p1]["relacion"] == "contesta"
    assert por_id[d2]["salto"] == 2 and por_id[d2]["via"] == d1
    assert por_id[p2]["salto"] == 3 and por_id[r]["salto"] == 3 and por_id[r]["relacion"] == "derivada_de"
    assert [x["salto"] for x in dep["dependientes"]] == sorted(x["salto"] for x in dep["dependientes"])
    assert {x["id"] for x in ap.dependencias(P, ev)["dependientes"]} == {d1, d2, p2, r}  # apoya, al reves
    assert ap.dependencias(P, d6)["dependientes"] == [
        {
            "id": p3,
            "relacion": "contesta",
            "via": d6,
            "salto": 1,
            "tipo": "pregunta",
            "texto": "p3",
            "estado": "contestada",
        }
    ]
    with pytest.raises(Rechazo) as e:
        ap.dependencias(P, "nadie")
    assert e.value.codigo == 404


def test_vigente_sobre_un_tema(proy):
    """La consulta 2 de v5 §8.5, tal cual: decisiones y reglas vigentes por sobre/aplica_a."""
    t = k.crear_nodo(P, "tema", "sustituciones", autor="f")["id"]
    d = _dec("racional")
    k.vincular(P, d, "sobre", t, autor="f")
    k.cambiar_estado(P, d, "vigente", por=COORD)
    r = _regla("no halving entero", _inc("x"))
    k.vincular(P, r, "aplica_a", t, autor="f")
    prop = _dec("propuesta")  # no vigente
    k.vincular(P, prop, "sobre", t, autor="f")
    h = k.crear_nodo(P, "hallazgo", "h", {"gravedad": "baja"}, autor="f")["id"]  # otro tipo
    k.vincular(P, h, "sobre", t, autor="f")
    with k._abrir(P) as con:
        filas = con.execute(
            """SELECT n.id, n.tipo FROM nodo n
               WHERE n.proyecto = :proyecto AND n.tipo IN ('decision','regla') AND n.estado = 'vigente'
                 AND EXISTS (SELECT 1 FROM vinculo v WHERE v.de = n.id AND v.a = :tema AND v.activo = 1
                             AND v.relacion IN ('sobre','aplica_a'))
               ORDER BY n.tipo, n.id""",
            {"proyecto": P, "tema": t},
        ).fetchall()
    assert [(f["id"], f["tipo"]) for f in filas] == [(d, "decision"), (r, "regla")]


# --- 6.3 lecciones por agente entre proyectos ---------------------------------------------------


def test_lecciones_cruza_proyectos_de_solo_lectura_y_dice_que_no_pudo_abrir(proy):
    k.registrar_proyecto("lienzo", "Lienzo")
    i_t = _inc("a")
    i_l = _inc("b", pid="lienzo")
    r1 = _regla("codex: no rm -rf", i_t, ambito="agente", agente="codex")
    r2 = _regla("codex gpt-5: pedir permiso antes", i_l, ambito="agente", agente="Codex", modelo="gpt-5", pid="lienzo")
    r3 = _regla("claude: x", i_l, ambito="agente", agente="claude", pid="lienzo")
    _regla("de proyecto", i_t)  # ambito proyecto: no es una leccion del agente
    retirada = _regla("retirada", i_t, ambito="agente", agente="codex")
    k.cambiar_estado(P, retirada, "retirada", por=COORD)
    # una cuestionada tambien cuenta, con su estado visible
    tarde = _inc("a de nuevo", fecha=DESPUES.replace("2999", "2027"))
    _repite(tarde, i_t)
    ap.cuestionar_regla(P, r1)
    with k._abrir(P) as con:
        cambios_antes = con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0]
    res = ap.lecciones("codex")
    assert res["proyectos"] == ["lienzo", P] and res["no_disponibles"] == []
    assert [(r["id"], r["proyecto"], r["estado"]) for r in res["reglas"]] == [
        (r2, "lienzo", "vigente"),
        (r1, P, "cuestionada"),
    ]
    assert res["reglas"][0]["proyecto_nombre"] == "Lienzo"
    assert [r["id"] for r in ap.lecciones("codex", modelo="gpt-5")["reglas"]] == [r2, r1]  # r1 no fija modelo
    assert [r["id"] for r in ap.lecciones("codex", modelo="o3")["reglas"]] == [r1]
    assert [r["id"] for r in ap.lecciones("claude")["reglas"]] == [r3]
    assert [r["id"] for r in ap.lecciones("codex", proyectos=["teorema"])["reglas"]] == [r1]
    assert ap.lecciones("codex", proyectos=["nadie"]) == {
        "agente": "codex",
        "modelo": None,
        "proyectos": [],
        "reglas": [],
        "incidentes": [],
        "no_disponibles": [{"proyecto": "nadie", "error": "proyecto desconocido"}],
    }
    with pytest.raises(Rechazo):
        ap.lecciones("")
    # un proyecto que no se puede abrir se informa, no se devuelve vacio (la base es una sola: falta la
    # carpeta del proyecto, que es lo que _abrir exige)
    os.rename(k._carpeta("lienzo"), k._carpeta("lienzo") + ".fuera")
    res = ap.lecciones("codex")
    assert res["proyectos"] == [P] and res["no_disponibles"][0]["proyecto"] == "lienzo"
    assert [r["id"] for r in res["reglas"]] == [r1]
    with k._abrir(P) as con:
        assert con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0] == cambios_antes


# --- API -----------------------------------------------------------------------------------------


def test_api_rutas_y_errores(proy):
    i1 = _inc("permiso denegado rm", fecha="2026-09-01T00:00:00.000Z")
    i2 = _inc("permiso denegado rm de nuevo", fecha="2026-10-01T00:00:00.000Z")
    i3 = _inc("permiso denegado rm tercera", fecha="2026-10-02T00:00:00.000Z")
    r = _regla("no rm", i1, ambito="agente", agente="codex")
    code, res = api.dispatch("GET", [P, "incidentes", i1, "parecidos"], None, {"limite": ["1"]})
    assert code == 200 and len(res) == 1 and res[0]["id"] in {i2, i3}
    assert api.dispatch("GET", [P, "incidentes", i1, "parecidos"], None, {"limite": ["x"]})[0] == 400
    assert api.dispatch("GET", [P, "incidentes", "nadie", "parecidos"], None, {})[0] == 404
    assert api.dispatch("GET", [P, "incidentes", r, "parecidos"], None, {})[0] == 400
    _repite(i2, i1)
    code, rec = api.dispatch("GET", [P, "incidentes", i1, "recurrencia"], None, {})
    assert code == 200 and rec["cantidad"] == 2
    code, q = api.dispatch("POST", [P, "reglas", "cuestionar"], {}, {})
    assert code == 200 and [x["id"] for x in q] == [r] and q[0]["recien"]
    code, q1 = api.dispatch("POST", [P, "reglas", r, "cuestionar"], {}, {})
    assert code == 200 and q1["motivo"] == "ya estaba cuestionada"
    assert api.dispatch("POST", [P, "reglas", i1, "cuestionar"], {}, {})[0] == 400
    code, qs = api.dispatch("GET", [P, "reglas", "cuestionadas"], None, {})
    assert code == 200 and [x["id"] for x in qs] == [r]
    d = _dec("d")
    h = k.crear_nodo(P, "hallazgo", "h", {"gravedad": "baja"}, autor="f")["id"]
    k.vincular(P, d, "motivada_por", h, autor="f")
    k.cambiar_estado(P, h, "rechazado", por=COORD)
    assert [x["id"] for x in api.dispatch("GET", [P, "avisos"], None, {})[1]] == [d]
    assert api.dispatch("GET", [P, "nodos", d, "aviso"], None, {})[1]["respaldos_caidos"] == [h]
    assert api.dispatch("GET", [P, "nodos", h, "dependencias"], None, {})[1]["total"] == 1
    assert api.dispatch("GET", [P, "nodos", "nadie", "dependencias"], None, {})[0] == 404
    code, lec = api.dispatch("GET", ["lecciones"], None, {"agente": ["codex"], "proyectos": [f"{P},otro"]})
    assert code == 200 and [x["id"] for x in lec["reglas"]] == [r] and lec["no_disponibles"][0]["proyecto"] == "otro"
    assert api.dispatch("GET", ["lecciones"], None, {})[0] == 400  # sin agente
    assert api.dispatch("POST", ["lecciones"], {}, {})[0] == 404
    assert api.dispatch("GET", ["nadie", "avisos"], None, {})[0] == 404
    assert api.dispatch("GET", [P, "otra"], None, {})[0] == 404
    assert api.dispatch("GET", [P, "reglas", "cuestionar"], None, {})[0] == 404  # GET no cuestiona
    assert api.dispatch("GET", [], None, {})[0] == 404


# --- medicion (encargo D) -------------------------------------------------------------------------


def test_parecidos_prioriza_todos_los_candidatos_antes_del_limite(proy):
    yo = _inc("permiso denegado bloqueo")
    with k._abrir(P) as con:
        for _ in range(120):
            _inc("permiso denegado bloqueo", herramienta="red", agente="claude", con=con)
        preferido = _inc("permiso " + "contexto " * 80, con=con)
    ranking = k.buscar(P, ap.consulta_fts("permiso denegado bloqueo"), tipo="incidente", limite=100)
    assert preferido not in {n["id"] for n in ranking}
    assert ap.parecidos(P, yo, limite=1)[0]["id"] == preferido


def test_respaldos_cadena_profunda_ciclo_y_rutas_redundantes(proy):
    h = k.crear_nodo(P, "hallazgo", "respaldo caido", {"gravedad": "alta"}, autor="f")["id"]
    k.cambiar_estado(P, h, "rechazado", por=COORD)
    with k._abrir(P) as con:
        ids = [k.crear_nodo(P, "decision", f"paso {i}", {"motivo": "m"}, autor="f", con=con)["id"] for i in range(1100)]
        for de, a in pairwise(ids):
            k.vincular(P, de, "motivada_por", a, autor="f", con=con)
        k.vincular(P, ids[-1], "motivada_por", ids[0], autor="f", con=con)
        k.vincular(P, ids[-1], "motivada_por", h, autor="f", con=con)
    aviso = ap.aviso(P, ids[0])
    assert aviso["respaldos_caidos"] == [h]
    assert [[n["id"] for n in c] for c in aviso["cadenas"]] == [[*ids[1:], h]]
    # Muchos caminos exponenciales en un DAG de dos nodos por nivel: un respaldo,
    # una cadena minima. Mismo grafo real, sin bajar el limite de recursion.
    with k._abrir(P) as con:
        niveles = [
            [k.crear_nodo(P, "decision", f"nivel {i}-{j}", {"motivo": "m"}, autor="f", con=con)["id"] for j in range(2)]
            for i in range(30)
        ]
        for anterior, siguiente in pairwise(niveles):
            for de in anterior:
                for a in siguiente:
                    k.vincular(P, de, "motivada_por", a, autor="f", con=con)
        for de in niveles[-1]:
            k.vincular(P, de, "motivada_por", h, autor="f", con=con)
    aviso = ap.aviso(P, niveles[0][0])
    assert len(aviso["cadenas"]) == 1 and len(aviso["cadenas"][0]) == 30
    assert aviso["respaldos_caidos"] == [h]


def test_recurrencias_grupos_unicos_lectura_sola_y_retiro(proy):
    assert ap.recurrencias(P) == []
    ids = [_inc(f"episodio {i}", fecha=f"2026-10-{i + 1:02d}T00:00:00.000Z") for i in range(6)]
    for de, a in ((ids[1], ids[0]), (ids[2], ids[1]), (ids[2], ids[0]), (ids[4], ids[3])):
        _repite(de, a)
    with k._abrir(P) as con:
        antes = con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0]
    grupos = ap.recurrencias(P)
    assert [g["cantidad"] for g in grupos] == [3, 2]
    assert [[e["id"] for e in g["episodios"]] for g in grupos] == [ids[:3], ids[3:5]]
    assert [g["incidente"] for g in grupos] == [ids[0], ids[3]]
    assert [g["ultimo"]["id"] for g in grupos] == [ids[2], ids[4]]
    assert api.dispatch("GET", [P, "incidentes", "recurrencias"], None, {}) == (200, grupos)
    with k._abrir(P) as con:
        assert con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0] == antes
    k.retirar_vinculo(P, ids[4], "repite", ids[3], por=COORD, motivo="no recurrente")
    assert len(ap.recurrencias(P)) == 1
    with pytest.raises(Rechazo):
        ap.recurrencias("desconocido")


@pytest.mark.parametrize("una_sola", [False, True])
def test_cuestionar_revierte_estado_datos_y_auditoria_si_falla(proy, monkeypatch, una_sola):
    origen = _inc("fallo", fecha="2026-09-01T00:00:00.000Z")
    reglas = [_regla(f"regla {i}", origen) for i in range(2)]
    posterior = _inc("fallo repetido", fecha="2026-10-01T00:00:00.000Z")
    _repite(posterior, origen)
    antes = [k.nodo(P, r) for r in reglas]
    with k._abrir(P) as con:
        cambios = con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0]
    original = k._cambio
    escritos = []

    def fallar(con, pid, accion, *args, **kwargs):
        original(con, pid, accion, *args, **kwargs)
        if accion == "datos":
            escritos.append(kwargs["nodo_id"])
            if una_sola or len(escritos) == 2:
                raise RuntimeError("fallo inyectado despues de auditar datos")

    monkeypatch.setattr(k, "_cambio", fallar)
    with pytest.raises(RuntimeError, match="fallo inyectado"):
        if una_sola:
            ap.cuestionar_regla(P, reglas[0])
        else:
            ap.cuestionar(P)
    assert [k.nodo(P, r) for r in reglas] == antes
    with k._abrir(P) as con:
        assert con.execute("SELECT COUNT(*) FROM cambio").fetchone()[0] == cambios


def test_cuestionar_respeta_permisos_de_transicion_y_conserva_datos(proy, monkeypatch):
    origen = _inc("fallo", fecha="2026-09-01T00:00:00.000Z")
    regla = _regla("regla", origen)
    posterior = _inc("repite", fecha="2026-10-01T00:00:00.000Z")
    _repite(posterior, origen)
    datos = k.nodo(P, regla)["datos"]
    transiciones = {**k.TRANSICIONES, "regla": {("vigente", "cuestionada"): {"coordinadora"}}}
    with monkeypatch.context() as m:
        m.setattr(k, "TRANSICIONES", transiciones)
        with pytest.raises(Rechazo) as error:
            ap.cuestionar(P)
        assert error.value.codigo == 403
    assert k.nodo(P, regla)["estado"] == "vigente"
    ap.cuestionar_regla(P, regla)
    resultado = k.nodo(P, regla)
    assert resultado["datos"] == {**datos, "episodios_posteriores": [posterior]}
    assert [c["accion"] for c in resultado["cambios"]][-2:] == ["estado", "datos"]


def test_medicion_300_incidentes_cadena_de_40_y_20_reglas(proy):
    """300 incidentes (50 por cada par herramienta/agente, textos variados), una cadena `repite` de 40
    episodios con rutas redundantes, 20 reglas vigentes derivadas de incidentes de la cadena.
    `recurrencia` cuenta exactamente 40 en menos de 100 ms; `cuestionar` las 20 en menos de 200 ms."""
    herramientas, agentes = ("permiso", "api", "red"), ("codex", "claude")
    palabras = ("rm", "git push", "fetch", "timeout", "token", "lock", "socket", "pytest", "ruff", "node")
    ids = []
    with k._abrir(P) as con:
        n = 0
        for h in herramientas:
            for a in agentes:
                for j in range(50):
                    texto = (
                        f"{h} fallo {palabras[j % len(palabras)]} en {palabras[(j * 3) % len(palabras)]} intento {j}"
                    )
                    ids.append(_inc(texto, h, a, con=con))
                    n += 1
        assert n == 300
    cadena = ids[:40]
    with k._abrir(P) as con:
        for i, nid in enumerate(cadena):
            con.execute(
                "UPDATE nodo SET fecha = ? WHERE id = ?",
                (f"2026-09-{1 + i // 2:02d}T{12 * (i % 2):02d}:00:00.000Z", nid),
            )
    with k._abrir(P) as con:
        for i in range(1, 40):
            k.vincular(P, cadena[i], "repite", cadena[i - 1], autor=COORD, con=con)
            if i >= 2:
                k.vincular(P, cadena[i], "repite", cadena[i - 2], autor=COORD, con=con)  # ruta redundante
    reglas = [_regla(f"regla {i}", cadena[i], vigente_desde="2026-09-10T00:00:00.000Z") for i in range(20)]

    t0 = time.perf_counter()
    r = ap.recurrencia(P, cadena[0])
    t_rec = (time.perf_counter() - t0) * 1000
    assert r["cantidad"] == 40 and len({e["id"] for e in r["episodios"]}) == 40
    assert r["primero"]["id"] == cadena[0] and r["ultimo"]["id"] == cadena[39]
    assert ap.recurrencia(P, cadena[39])["cantidad"] == 40

    t0 = time.perf_counter()
    cand = ap.por_cuestionar(P)
    t_eval = (time.perf_counter() - t0) * 1000
    assert {r["id"] for r, _ in cand} == set(reglas)
    t0 = time.perf_counter()
    q = ap.cuestionar(P)
    t_cue = (time.perf_counter() - t0) * 1000
    assert {x["id"] for x in q} == set(reglas) and all(x["recien"] for x in q)
    # posteriores al 10 de septiembre a las 00:00: los indices 19..39 son 21 episodios, 20 si el de origen es uno de ellos
    assert all(x["recurrencias"] in (20, 21) for x in q)
    assert all(k.nodo(P, r)["estado"] == "cuestionada" for r in reglas)

    t0 = time.perf_counter()
    p = ap.parecidos(P, ids[100])
    t_par = (time.perf_counter() - t0) * 1000
    assert p and p[0]["misma_herramienta"] and p[0]["mismo_agente"]
    print(
        f"\nmedicion: recurrencia={t_rec:.1f}ms por_cuestionar(20)={t_eval:.1f}ms cuestionar(20)={t_cue:.1f}ms parecidos={t_par:.1f}ms"
    )
    assert t_rec < 100, t_rec
    assert t_eval < 200, t_eval
    assert t_cue < 200, t_cue
