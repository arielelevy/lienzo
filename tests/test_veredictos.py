"""Etapa 3 del conocimiento por proyecto (v5 §5.3, §7, §8.5): veredictos en una transaccion, pendientes,
duplicados sugeridos, cierre con veredictos, temas canonicos, briefing, preguntar (las cinco consultas de
§8.5), vista en Markdown, la API y la medicion con 200 nodos y 400 vinculos. Sobre un LIENZO_HOME
temporal (conftest), nunca contra el server real."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event, Lock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import veredictos as v
import veredictos_api as api
from conocimiento import Rechazo

P = "teorema"
COORD = "coordinadora:c1"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)


@pytest.fixture
def proy():
    return k.registrar_proyecto(P, "Teorema", ["github.com/arielelevy/teorema"])


def _bloque(obj):
    return "## Resultado\n\nlisto\n\n```conocimiento\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


def _entrega(bloque, letra="A", sid="sid-f", ronda=None, revision=1, encargo=None):
    """Ronda + encargo enviado + informe con bloque. Devuelve (ronda, encargo, informe, ids locales)."""
    if ronda is None:
        ronda = k.abrir_ronda(P, f"ronda {letra}", autor=COORD)
    if encargo is None:
        encargo = k.crear_encargo(P, ronda["id"], letra, f"# Encargo {letra}\n\nhacer", autor=COORD)
        k.encargo_enviado(P, encargo["id"], {"session_id": sid, "agent": "codex"})
    inf = k.entregar(P, encargo["id"], _bloque(bloque), revision=revision, autor=f"frente:{sid}")
    assert inf["datos"]["conocimiento"]["estado"] == "incorporado", inf["datos"]["conocimiento"]
    return ronda, encargo, inf, inf["datos"]["conocimiento"]["ids"]


BLOQUE_HALVING = {
    "version": 1,
    "nodos": [
        {
            "id": "h1",
            "tipo": "hallazgo",
            "texto": "el halving entero pierde el invariante con k impar",
            "datos": {"donde": "codigo/sustituciones.py:88", "gravedad": "alta"},
        },
        {"id": "a1", "tipo": "alternativa", "texto": "halving entero en sustituciones", "datos": {}},
        {"id": "a2", "tipo": "alternativa", "texto": "halving racional con denominador comun", "datos": {}},
        {
            "id": "d1",
            "tipo": "decision",
            "texto": "sustituciones con halving racional",
            "datos": {"motivo": "conserva el invariante"},
        },
        {"id": "p1", "tipo": "pregunta", "texto": "¿vale el 2x para n grande?", "datos": {"para_quien": "ariel"}},
        {
            "id": "m1",
            "tipo": "medicion",
            "texto": "error relativo del halving racional",
            "datos": {"metrica": "err", "valor": 1e-9, "unidad": "1", "condicion": "commit 7c2e"},
        },
        {
            "id": "e1",
            "tipo": "evidencia",
            "texto": "la prueba del caso impar",
            "datos": {"clase": "prueba", "referencia": "tests/test_sustituciones.py::test_k_impar"},
        },
        {"id": "t1", "tipo": "tema", "texto": "sustituciones", "datos": {}},
    ],
    "vinculos": [
        {"de": "d1", "relacion": "descarta", "a": "a1", "motivo": "pierde el invariante"},
        {"de": "d1", "relacion": "elige", "a": "a2", "motivo": "exacto"},
        {"de": "d1", "relacion": "motivada_por", "a": "h1"},
        {"de": "h1", "relacion": "apoya", "a": "e1"},
        {"de": "d1", "relacion": "sobre", "a": "t1"},
        {"de": "h1", "relacion": "sobre", "a": "t1"},
        {"de": "p1", "relacion": "sobre", "a": "t1"},
        {"de": "m1", "relacion": "sobre", "a": "t1"},
    ],
}


# --- 1. veredictos ---------------------------------------------------------------------------------------


def test_veredicto_aplica_todo_en_una_transaccion_o_nada_y_dice_la_posicion(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    ev = k.crear_nodo(P, "evidencia", "la correccion", {"clase": "prueba", "referencia": "tests/x.py"}, autor="c")["id"]
    items = [
        {"nodo": ids["h1"], "estado": "confirmado"},
        {"nodo": ids["d1"], "estado": "vigente"},
        {"nodo": ids["h1"], "estado": "corregido"},  # confirmado -> corregido: vale porque el item 0 ya paso
        # (y porque el veredicto cita evidencia: §3.4 pide la correccion respaldada)
        {"nodo": ids["m1"], "estado": "rechazada"},
        {"nodo": ids["p1"], "estado": "contestada"},
        {"de": ids["d1"], "relacion": "contesta", "a": ids["p1"]},
        {"retirar": {"de": ids["m1"], "relacion": "sobre", "a": ids["t1"]}, "motivo": "no era del tema"},
        {"nodo": ids["d1"], "estado": "revertida"},  # vigente -> revertida: ok
        {"nodo": ids["m1"], "estado": "valida"},  # rechazada -> valida no existe: todo se revierte
    ]
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, items, por=COORD)
    assert x.value.codigo == 409 and str(x.value).startswith("item 8:")
    h = k.nodo(P, ids["h1"])
    assert h["estado"] == "propuesto" and k.nodo(P, ids["d1"])["estado"] == "propuesta"
    assert k.nodo(P, ids["m1"])["vinculos"]["salen"]  # el retiro del item 6 tampoco quedo
    assert not any(c["origen"].get("veredicto") for c in k.cambios(P))  # los estados que hay son del server (encargo)
    sin_respaldo = [x for x in items[:-1] if x.get("relacion") != "contesta"]
    with pytest.raises(Rechazo, match="exige un vinculo contesta"):
        v.veredicto(P, sin_respaldo, por=COORD, evidencia=[ev], motivo="sin contesta")
    with pytest.raises(Rechazo, match="corregido exige"):
        v.veredicto(P, items[:-1], por=COORD, motivo="sin evidencia")
    res = v.veredicto(P, items[:-1], por=COORD, revision=inf["id"], evidencia=[ev], motivo="revisado el informe A r1")
    assert res["n"] == 8 and [a["accion"] for a in res["aplicados"][5:7]] == ["vinculo", "vinculo_retirado"]
    assert k.nodo(P, ids["h1"])["estado"] == "corregido" and k.nodo(P, ids["d1"])["estado"] == "revertida"
    assert k.nodo(P, ids["p1"])["estado"] == "contestada"
    assert not any(x["relacion"] == "sobre" for x in k.nodo(P, ids["m1"])["vinculos"]["salen"])
    cambios = [c for c in k.cambios(P) if c["origen"].get("veredicto")]
    assert len(cambios) == 8  # 6 estados + 1 vinculo + 1 retiro
    assert all(c["origen"]["revision"] == inf["id"] for c in cambios)
    assert all(c["motivo"] == "revisado el informe A r1" for c in cambios if c["accion"] == "estado")
    assert next(c for c in cambios if c["accion"] == "vinculo_retirado")["motivo"] == "no era del tema"
    # idempotente por item: lo que ya esta en ese estado o ya vinculado no crea cambios nuevos
    antes = len(k.cambios(P))
    v.veredicto(P, [items[2], items[4], items[5]], por=COORD)
    assert len(k.cambios(P)) == antes


def test_regla_vigente_escribe_vigente_desde_y_el_origen_lleva_la_evidencia(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    inc = k.incidente_operativo("sid-f", "permiso denegado: Bash rm", herramienta="permiso")
    regla = k.declarar_nodo(P, "regla", "no borrar con rm -rf", {"ambito": "proyecto"}, autor="frente:sid-f")
    k.vincular(P, regla["id"], "derivada_de", inc["id"], autor="frente:sid-f")
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"nodo": regla["id"], "estado": "vigente"}], por=COORD, evidencia=[ids["h1"]])
    assert "no es una evidencia" in str(x.value)
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"nodo": regla["id"], "estado": "vigente"}], por=COORD, revision=ids["h1"])
    assert "informe" in str(x.value)
    res = v.veredicto(
        P, [{"nodo": regla["id"], "estado": "vigente"}], por=COORD, revision=inf["id"], evidencia=[ids["e1"]]
    )
    n = res["aplicados"][0]["nodo"]
    assert n["estado"] == "vigente" and n["datos"]["vigente_desde"] == n["estado_fecha"]
    assert res["origen"] == {"veredicto": True, "revision": inf["id"], "evidencia": [ids["e1"]]}
    c = k.cambios(P)[-1]
    assert c["accion"] == "estado" and c["origen"]["evidencia"] == [ids["e1"]] and c["nuevo"]["datos"]["vigente_desde"]
    # revalidar (cuestionada -> vigente) abre otro periodo
    k.cambiar_estado(P, regla["id"], "cuestionada", por="server")
    time.sleep(0.002)
    n2 = v.veredicto(P, [{"nodo": regla["id"], "estado": "vigente"}], por="persona:ariel")["aplicados"][0]["nodo"]
    assert n2["datos"]["vigente_desde"] > n["datos"]["vigente_desde"]


def test_solo_coordinadora_o_persona_emiten_veredictos_y_los_items_se_validan(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    for por in ("frente:sid-f", "server", "nadie"):
        with pytest.raises(Rechazo) as x:
            v.veredicto(P, [{"nodo": ids["h1"], "estado": "confirmado"}], por=por)
        assert x.value.codigo == 403
    with pytest.raises(Rechazo):
        v.veredicto(P, [], por=COORD)
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"nodo": ids["h1"], "estado": "confirmado"}, "texto"], por=COORD)
    assert "item 1" in str(x.value)
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"cosa": 1}], por=COORD)
    assert "item 0" in str(x.value)
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"de": ids["d1"], "relacion": "descarta", "a": ids["a2"]}], por=COORD)  # sin motivo
    assert "item 0" in str(x.value) and "motivo" in str(x.value)
    with pytest.raises(Rechazo) as x:
        v.veredicto(P, [{"nodo": "no-existe", "estado": "confirmado"}], por=COORD)
    assert x.value.codigo == 404
    assert k.nodo(P, ids["h1"])["estado"] == "propuesto"


# --- 2 y 3. pendientes y duplicados -----------------------------------------------------------------------


def test_pendientes_por_ronda_con_vinculos_y_entrega_tardia(proy):
    r1, e1, inf1, ids1 = _entrega(BLOQUE_HALVING, letra="A")
    r2, e2, inf2, ids2 = _entrega(
        {
            "version": 1,
            "nodos": [
                {
                    "id": "i1",
                    "tipo": "incidente",
                    "texto": "se colgo el build",
                    "datos": {"herramienta": "npm", "agente": "codex"},
                }
            ],
        },
        letra="B",
        sid="sid-g",
    )
    todo = v.pendientes(P)
    tipos = [(p["tipo"], p["estado"]) for p in todo["pendientes"]]
    assert tipos[0] == ("informe", "recibido") and todo["total"] == 7  # A: informe, h1, d1, p1, m1; B: informe, i1
    assert ("alternativa", None) not in tipos and ("tema", None) not in tipos
    assert [p["ronda"] for p in todo["pendientes"]] == [r1["id"]] * 5 + [r2["id"]] * 2
    h1 = next(p for p in todo["pendientes"] if p["id"] == ids1["h1"])
    assert {x["relacion"] for x in h1["vinculos"]} == {
        "declarado_en",
        "encontrado_por",
        "apoya",
        "sobre",
        "motivada_por",
    }
    assert not any(p["tardia"] for p in todo["pendientes"])
    # un veredicto saca cosas de la lista; una entrega tardia a la ronda cerrada entra marcada
    v.veredicto(
        P, [{"nodo": ids1["h1"], "estado": "confirmado"}, {"nodo": inf1["id"], "estado": "revisado"}], por=COORD
    )
    k.cerrar_ronda(P, r1["id"], por=COORD)
    time.sleep(0.002)
    r1b, e1b, inf_tarde, ids_tarde = _entrega(
        {
            "version": 1,
            "nodos": [{"id": "h9", "tipo": "hallazgo", "texto": "tarde", "datos": {"donde": "x", "gravedad": "baja"}}],
        },
        ronda=r1,
        encargo=e1,
        revision=2,
    )
    solo_r1 = v.pendientes(P, r1["id"])
    ids = {p["id"]: p for p in solo_r1["pendientes"]}
    assert ids1["h1"] not in ids and inf1["id"] not in ids and ids2["i1"] not in ids
    assert ids[inf_tarde["id"]]["tardia"] and ids[ids_tarde["h9"]]["tardia"] and not ids[ids1["d1"]]["tardia"]
    with pytest.raises(Rechazo):
        v.pendientes(P, ids1["h1"])  # no es una ronda


def test_duplicados_sugiere_pares_entre_informes_sin_vincular(proy):
    r1, e1, inf1, ids1 = _entrega(BLOQUE_HALVING, letra="A")
    r2, e2, inf2, ids2 = _entrega(
        {
            "version": 1,
            "nodos": [
                {
                    "id": "h1",
                    "tipo": "hallazgo",
                    "texto": "El halving ENTERO pierde el invariante con k impar.",
                    "datos": {"donde": "codigo/sustituciones.py", "gravedad": "alta"},
                },
                {
                    "id": "h2",
                    "tipo": "hallazgo",
                    "texto": "con k impar el halving entero pierde el invariante y la cota",
                    "datos": {"donde": "x", "gravedad": "media"},
                },
                {
                    "id": "h3",
                    "tipo": "hallazgo",
                    "texto": "la cota del LP no acota nada",
                    "datos": {"donde": "y", "gravedad": "baja"},
                },
                {
                    "id": "h4",
                    "tipo": "hallazgo",
                    "texto": "la cota del LP no acota nada",
                    "datos": {"donde": "y", "gravedad": "baja"},
                },
                {
                    "id": "d1",
                    "tipo": "decision",
                    "texto": "sustituciones con halving racional",
                    "datos": {"motivo": "otra vez"},
                },
                {"id": "a1", "tipo": "alternativa", "texto": "x", "datos": {}},
            ],
            "vinculos": [{"de": "d1", "relacion": "elige", "a": "a1", "motivo": "m"}],
        },
        letra="B",
        sid="sid-g",
    )
    dup = v.duplicados(P)
    pares = {(d["a"], d["b"]): d for d in dup}
    igual = pares[(ids1["h1"], ids2["h1"])]
    assert igual["puntaje"] == 1.0 and igual["motivo"] == "texto igual" and igual["relacion"] == "mismo_que"
    parecido = pares[(ids1["h1"], ids2["h2"])]
    assert 0.5 <= parecido["puntaje"] < 1.0 and parecido["motivo"].startswith("bm25")
    assert pares[(ids1["d1"], ids2["d1"])]["relacion"] == "reemplaza"
    assert (ids2["h3"], ids2["h4"]) not in pares  # mismo informe: lo quiso asi el frente
    assert all(d["tipo"] != "alternativa" for d in dup)
    assert k.nodo(P, ids2["h1"])["vinculos"]["salen"] == k.nodo(P, ids2["h1"])["vinculos"]["salen"]  # nada vinculado
    assert not any(x["relacion"] == "mismo_que" for x in k.nodo(P, ids2["h1"])["vinculos"]["salen"])
    # con ronda: solo pares que tocan esa ronda; y un par ya vinculado deja de sugerirse
    assert {(d["a"], d["b"]) for d in v.duplicados(P, r2["id"])} == set(pares)
    v.veredicto(P, [{"de": ids2["h1"], "relacion": "mismo_que", "a": ids1["h1"]}], por=COORD)
    assert (ids1["h1"], ids2["h1"]) not in {(d["a"], d["b"]) for d in v.duplicados(P)}
    assert v.duplicados(P, r1["id"]) == [d for d in v.duplicados(P) if r1["id"] in (d["ronda_a"], d["ronda_b"])]


# --- 4. cierre con veredictos ------------------------------------------------------------------------------


def test_cerrar_ronda_aplica_veredictos_anota_sin_resolver_y_devuelve_lo_que_queda(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    with pytest.raises(Rechazo) as x:
        v.cerrar_ronda(P, r["id"], por=COORD, sin_resolver=[{"nodo": ids["p1"]}])
    assert "motivo" in str(x.value) and k.nodo(P, r["id"])["estado"] == "abierta"
    res = v.cerrar_ronda(
        P,
        r["id"],
        por=COORD,
        veredictos=[
            {
                "items": [{"nodo": ids["h1"], "estado": "confirmado"}, {"nodo": ids["d1"], "estado": "vigente"}],
                "revision": inf["id"],
            },
            {"nodo": inf["id"], "estado": "revisado"},  # item suelto: forma su propio veredicto
        ],
        sin_resolver=[{"nodo": ids["p1"], "motivo": "la contesta Ariel"}],
        motivo="fin de la ronda 1",
    )
    assert res["ronda"]["estado"] == "cerrada" and res["ronda"]["datos"]["cierre_seq"] > 0
    assert (
        res["ronda"]["datos"]["sin_resolver"][0]["nodo"] == ids["p1"]
        and res["ronda"]["datos"]["sin_resolver"][0]["por"] == COORD
    )
    assert len(res["veredictos"]) == 2 and res["veredictos"][0]["origen"]["revision"] == inf["id"]
    assert [p["id"] for p in res["pendientes"]] == [ids["m1"]]  # sin veredicto ni motivo: se devuelve, no bloquea
    assert k.nodo(P, ids["d1"])["estado"] == "vigente"
    with pytest.raises(Rechazo) as x:
        v.cerrar_ronda(P, r["id"], por=COORD)
    assert x.value.codigo == 409


def test_cerrar_ronda_con_un_veredicto_malo_no_cierra_ni_aplica(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    with pytest.raises(Rechazo) as x:
        v.cerrar_ronda(
            P,
            r["id"],
            por=COORD,
            veredictos=[{"nodo": ids["h1"], "estado": "confirmado"}, {"nodo": ids["h1"], "estado": "vigente"}],
        )
    assert "item 1" in str(x.value)
    assert k.nodo(P, r["id"])["estado"] == "abierta" and k.nodo(P, ids["h1"])["estado"] == "propuesto"


# --- 5. temas canonicos ------------------------------------------------------------------------------------


def test_cierre_fallido_revierte_veredictos_sin_resolver_y_cierre_seq(proy, monkeypatch):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    antes = k.cambios(P)
    ronda_antes = k.nodo(P, r["id"])
    cerrar_real = k.cerrar_ronda

    def falla_despues_del_cierre(pid, ronda, *, por, motivo="", con=None):
        assert con is not None and con.in_transaction
        assert k._nodo(con, pid, ids["h1"])["estado"] == "confirmado"
        assert k._nodo(con, pid, ronda)["datos"]["sin_resolver"]
        cerrar_real(pid, ronda, por=por, motivo=motivo, con=con)
        assert k._nodo(con, pid, ronda)["datos"]["cierre_seq"] > 0
        raise RuntimeError("fallo despues de escribir el cierre")

    monkeypatch.setattr(k, "cerrar_ronda", falla_despues_del_cierre)
    with pytest.raises(RuntimeError, match="fallo despues"):
        v.cerrar_ronda(
            P,
            r["id"],
            por=COORD,
            veredictos=[{"nodo": ids["h1"], "estado": "confirmado"}],
            sin_resolver=[{"nodo": ids["p1"], "motivo": "pendiente"}],
        )
    assert k.cambios(P) == antes
    assert k.nodo(P, r["id"]) == ronda_antes
    assert k.nodo(P, ids["h1"])["estado"] == "propuesto"


def test_cierres_concurrentes_uno_confirma_y_otro_es_409_sin_escrituras(proy, monkeypatch):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    otro = k.declarar_nodo(P, "hallazgo", "otro hallazgo", {"donde": "test", "gravedad": "baja"}, autor=COORD)
    abrir_real, cerrar_real = k._abrir, k.cerrar_ronda
    barrera, segundo_intento, lock = Barrier(2), Event(), Lock()
    comienzos = []

    def traza(sql):
        if sql == "BEGIN IMMEDIATE":
            with lock:
                comienzos.append(sql)
                if len(comienzos) == 2:
                    segundo_intento.set()

    @contextmanager
    def abrir_trazado(pid):
        with abrir_real(pid) as con:
            con.set_trace_callback(traza)
            yield con

    def cerrar_con_barrera(pid, ronda, *, por, motivo="", con=None):
        # El ganador conserva el bloqueo hasta que el competidor intente BEGIN.
        assert segundo_intento.wait(5), "el segundo cierre no intento la transaccion"
        return cerrar_real(pid, ronda, por=por, motivo=motivo, con=con)

    def intento(nid):
        barrera.wait(timeout=5)
        try:
            resultado = v.cerrar_ronda(P, r["id"], por=COORD, veredictos=[{"nodo": nid, "estado": "confirmado"}])
            return nid, 200, resultado["ronda"]["datos"]["cierre_seq"]
        except Rechazo as error:
            return nid, error.codigo, None

    monkeypatch.setattr(k, "_abrir", abrir_trazado)
    monkeypatch.setattr(k, "cerrar_ronda", cerrar_con_barrera)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(intento, nid) for nid in (ids["h1"], otro["id"])]
        resultados = [f.result(timeout=15) for f in futuros]
    assert sorted(codigo for _, codigo, _ in resultados) == [200, 409]
    assert len(comienzos) == 2
    ganador = next(nid for nid, codigo, _ in resultados if codigo == 200)
    perdedor = next(nid for nid, codigo, _ in resultados if codigo == 409)
    assert k.nodo(P, ganador)["estado"] == "confirmado"
    assert k.nodo(P, perdedor)["estado"] == "propuesto"
    cierre = k.nodo(P, r["id"])
    assert cierre["estado"] == "cerrada"
    assert cierre["datos"]["cierre_seq"] == next(seq for _, codigo, seq in resultados if codigo == 200)
    estados = [c for c in k.cambios(P) if c["accion"] == "estado" and c["nodo_id"] == r["id"]]
    assert len(estados) == 1


def test_tema_canonico_por_texto_o_alias_suma_aliases_y_cuenta_nodos(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    t = v.tema(P, "Sustituciónes", por=COORD, aliases=["sustitución", "subst"])
    # «Sustituciónes» normaliza al texto canonico: no es alias nuevo
    assert not t["creado"] and t["id"] == ids["t1"] and t["aliases_nuevos"] == ["sustitución", "subst"]
    assert v.tema(P, "SUBST", por=COORD)["id"] == ids["t1"]
    assert v.tema(P, "subst", por=COORD, aliases=["Sustitucion"])["aliases_nuevos"] == []  # ya estaba, sin tilde
    nuevo = v.tema(P, "halving", por=COORD, aliases=["mitad"])
    assert nuevo["creado"] and nuevo["datos"]["aliases"] == ["mitad"] and nuevo["estado"] is None
    assert v.tema(P, "mitad", por=COORD)["id"] == nuevo["id"]
    lista = v.temas(P)
    assert [(t["texto"], t["nodos"]) for t in lista] == [("sustituciones", 4), ("halving", 0)]
    assert "subst" in lista[0]["aliases"]
    assert k.buscar(P, "subst", tipo="tema")[0]["id"] == ids["t1"]  # los aliases entran al FTS por datos


# --- 6 y 7. briefing y preguntar, con las cinco consultas de v5 §8.5 ------------------------------------------


def test_briefing_separa_vigente_abierto_y_cambios_con_una_procedencia_por_via(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    v.cerrar_ronda(
        P,
        r["id"],
        por=COORD,
        veredictos=[{"nodo": ids["d1"], "estado": "vigente"}, {"nodo": ids["m1"], "estado": "valida"}],
    )
    seq = k.nodo(P, r["id"])["datos"]["cierre_seq"]
    v.veredicto(P, [{"nodo": ids["h1"], "estado": "confirmado"}], por=COORD)  # despues del cierre
    b = v.briefing(P, archivos=["codigo/"], temas=["Sustitucionés"], consultas=["invariante", "halving"])
    todos = b["vigente"] + b["abierto"] + b["otros"]
    assert len({n["id"] for n in todos}) == len(todos)  # sin repetir
    por_id = {n["id"]: n for n in todos}
    assert [n["id"] for n in b["vigente"]] == [ids["d1"], ids["h1"], ids["m1"]] or {n["id"] for n in b["vigente"]} == {
        ids["d1"],
        ids["h1"],
        ids["m1"],
    }
    assert [n["id"] for n in b["abierto"]] == [ids["p1"], inf["id"]]  # el informe recibido llega a un salto de h1
    assert set(por_id[ids["h1"]]["procedencia"]) == {"tema", "archivo", "bm25:invariante", "bm25:halving"}
    assert por_id[ids["d1"]]["procedencia"] == ["tema", "bm25:invariante", "bm25:halving"]
    assert (
        por_id[ids["e1"]]["procedencia"] == ["expansion"] and por_id[ids["e1"]] in b["otros"]
    )  # evidencia: a un salto de h1
    # Ya es semilla lexical: expandir conserva su distancia minima cero (v5 §8.5.5).
    assert por_id[ids["a1"]]["procedencia"] == ["bm25:halving"]
    assert por_id[ids["t1"]]["procedencia"] == ["tema"]
    assert b["temas_sin_resolver"] == []
    c = b["cambios"]
    assert c["ronda_cerrada"] == r["id"] and c["desde_seq"] == seq and not c["truncado"]
    # conocimiento.cerrar_ronda guarda cierre_seq antes de registrar su propio cambio de datos.
    assert [(x["accion"], x["nodo"], x["estado"]) for x in c["cambios"]] == [
        ("datos", r["id"], "cerrada"),
        ("estado", ids["h1"], "confirmado"),
    ]
    assert c["cambios"][0]["motivo"] == "cierre_seq"
    assert "nuevo" not in c["cambios"][1] and c["cambios"][1]["texto"].startswith("el halving")
    assert b["avisos"]["disponible"] in (True, False)
    b2 = v.briefing(P, temas=["no existe"], desde_cierre=False)
    assert b2["temas_sin_resolver"] == ["no existe"] and b2["cambios"] is None and b2["vigente"] == []
    with pytest.raises(Rechazo):
        v.briefing(P, consultas=["invariante AND ("])


def test_consulta_1_por_que_se_descarto_una_alternativa(proy):
    """v5 §8.5.1: desde la alternativa, la decision que la descarta (con su motivo), lo que la motiva y su evidencia."""
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    res = v.preguntar(P, ["halving entero"], tipo="alternativa", saltos=2)
    por_id = {n["id"]: n for n in res["candidatos"]}
    assert res["candidatos"][0]["id"] == ids["a1"] and por_id[ids["a1"]]["procedencia"] == ["bm25:halving entero"]
    d = por_id[ids["d1"]]
    assert d["salto"] == 1 and d["procedencia"] == ["expansion"] and d["datos"]["motivo"] == "conserva el invariante"
    descarta = next(x for x in d["vinculos"] if x["relacion"] == "descarta" and x["a"] == ids["a1"])
    assert descarta["motivo"] == "pierde el invariante"
    assert por_id[ids["h1"]]["salto"] == 2 and por_id[ids["a2"]]["salto"] == 2  # la elegida esta del otro lado de d1
    assert ids["e1"] not in por_id  # a tres saltos: otro pedido desde h1
    sig = v.preguntar(P, [], temas=[], archivos=["tests/test_sustituciones.py"], saltos=0)
    assert [n["id"] for n in sig["candidatos"]] == [ids["e1"]] and sig["candidatos"][0]["procedencia"] == ["archivo"]
    with pytest.raises(Rechazo):
        v.preguntar(P, [])


def test_consulta_2_que_esta_vigente_sobre_un_tema(proy):
    """v5 §8.5.2: decisiones y reglas vigentes por sobre/aplica_a; los hallazgos abiertos aparte."""
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    inc = k.incidente_operativo("sid-f", "permiso denegado: rm", herramienta="permiso")
    regla = k.declarar_nodo(P, "regla", "no borrar con rm", {"ambito": "proyecto"}, autor="frente:sid-f")
    k.vincular(P, regla["id"], "derivada_de", inc["id"], autor="frente:sid-f")
    k.vincular(P, regla["id"], "aplica_a", ids["t1"], autor="frente:sid-f")
    vieja = k.declarar_nodo(P, "decision", "vieja", {"motivo": "m"}, autor=COORD)
    k.vincular(P, vieja["id"], "sobre", ids["t1"], autor=COORD)
    sucesora = k.crear_nodo(P, "decision", "sucesora (sin tema)", {"motivo": "m"}, autor=COORD)
    v.veredicto(
        P,
        [
            {"nodo": ids["d1"], "estado": "vigente"},
            {"nodo": regla["id"], "estado": "vigente"},
            {"nodo": vieja["id"], "estado": "vigente"},
            {"de": sucesora["id"], "relacion": "reemplaza", "a": vieja["id"]},
            {"nodo": vieja["id"], "estado": "reemplazada"},
        ],
        por=COORD,
    )
    b = v.briefing(P, temas=["sustituciones"], desde_cierre=False)
    assert {(n["tipo"], n["id"]) for n in b["vigente"]} == {("decision", ids["d1"]), ("regla", regla["id"])}
    assert all("tema" in n["procedencia"] for n in b["vigente"])
    # propuestos y abiertos, aparte; el incidente observado y el informe recibido llegan a un salto
    # la sucesora propuesta llega a un salto de la vieja por reemplaza
    esperados = {ids["h1"], ids["p1"], ids["m1"], inc["id"], inf["id"], sucesora["id"]}
    assert {n["id"] for n in b["abierto"]} == esperados
    assert vieja["id"] in {n["id"] for n in b["otros"]}  # reemplazada: ni vigente ni abierta


def test_consulta_3_si_un_incidente_ya_paso(proy):
    """v5 §8.5.3: candidatos lexicales entre incidentes, no recurrencias confirmadas."""
    r = k.abrir_ronda(P, "r", autor=COORD)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=COORD)
    k.encargo_enviado(P, e["id"], {"session_id": "sid-f", "agent": "codex"})
    viejo = k.incidente_operativo("sid-f", "permiso denegado: Bash rm -rf build", herramienta="permiso", clave="k1")
    otro = k.incidente_operativo("sid-f", "error de API: la respuesta dejo de llegar", herramienta="api", clave="k2")
    nuevo = k.incidente_operativo("sid-f", "permiso denegado: Bash rm -rf dist", herramienta="permiso", clave="k3")
    res = v.preguntar(P, ['"permiso denegado"', "rm"], tipo="incidente", saltos=0)
    ids = [n["id"] for n in res["candidatos"]]
    assert set(ids) == {viejo["id"], nuevo["id"]} and otro["id"] not in ids
    assert all(
        n["puntaje"] < 0 and n["procedencia"] == ['bm25:"permiso denegado"', "bm25:rm"] for n in res["candidatos"]
    )
    assert v.preguntar(P, ["dejo de llegar"], tipo="incidente", saltos=0)["candidatos"][0]["id"] == otro["id"]
    # duplicados tambien los propone, como candidatos a repite, sin vincular
    d = [x for x in v.duplicados(P) if x["tipo"] == "incidente"]
    assert len(d) == 1 and (d[0]["a"], d[0]["b"], d[0]["relacion"]) == (viejo["id"], nuevo["id"], "repite")


def test_consulta_4_reglas_cuestionadas_salen_en_abierto_con_su_vigente_desde(proy):
    """v5 §8.5.4: la regla que el server cuestiono (frente D) se ve abierta con el periodo que abrio el veredicto."""
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    inc = k.incidente_operativo("sid-f", "permiso denegado: rm", herramienta="permiso")
    regla = k.declarar_nodo(P, "regla", "no borrar con rm", {"ambito": "proyecto"}, autor="frente:sid-f")
    k.vincular(P, regla["id"], "derivada_de", inc["id"], autor="frente:sid-f")
    k.vincular(P, regla["id"], "aplica_a", ids["t1"], autor="frente:sid-f")
    desde = v.veredicto(P, [{"nodo": regla["id"], "estado": "vigente"}], por=COORD)["aplicados"][0]["nodo"]["datos"][
        "vigente_desde"
    ]
    k.cambiar_estado(P, regla["id"], "cuestionada", por="server", motivo="recurrencia")
    b = v.briefing(P, temas=["sustituciones"], desde_cierre=False)
    cuestionada = next(n for n in b["abierto"] if n["id"] == regla["id"])
    assert cuestionada["estado"] == "cuestionada" and cuestionada["datos"]["vigente_desde"] == desde
    assert regla["id"] not in {n["id"] for n in b["vigente"]}
    p = v.preguntar(P, ["borrar"], tipo="regla", saltos=1)
    assert p["candidatos"][0]["id"] == regla["id"] and inc["id"] in {n["id"] for n in p["candidatos"]}


def test_consulta_5_expandir_candidatos_sin_puentes_por_tema_ni_informe(proy):
    """v5 §8.5.5: dos saltos desde las semillas BM25; tema e informe se devuelven pero no expanden su vecindario."""
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    res = v.preguntar(P, ["invariante"], saltos=2)
    por_id = {n["id"]: n for n in res["candidatos"]}
    assert {i for i, n in por_id.items() if n["salto"] == 0} == {ids["d1"], ids["h1"]}
    assert por_id[ids["a1"]]["salto"] == 1 and por_id[ids["e1"]]["salto"] == 1 and por_id[ids["t1"]]["salto"] == 1
    assert por_id[inf["id"]]["salto"] == 1 and por_id[inf["id"]]["ruta"].endswith("informe-A-r1.md")
    assert ids["p1"] not in por_id and ids["m1"] not in por_id  # solo llegan por el tema, que no es puente
    assert k.leer_cuerpo(P, por_id[inf["id"]]["ruta"]).startswith("## Resultado")
    assert [n["salto"] for n in res["candidatos"]] == sorted(n["salto"] for n in res["candidatos"])
    assert v.preguntar(P, ["invariante"], saltos=0)["total"] == 2


# --- 8. vista ------------------------------------------------------------------------------------------------


def test_vista_markdown_con_ids_citables_y_gancho_de_aprendizaje(proy, monkeypatch):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    v.veredicto(P, [{"nodo": ids["d1"], "estado": "vigente"}], por=COORD)
    md = v.vista(P, "SUSTITUCIONÉS")["markdown"]  # por texto, sin tildes ni mayusculas
    assert md.startswith(f"## Conocimiento del proyecto sobre «sustituciones» (nodo:{ids['t1']})")
    vig = md.split("### Vigente")[1].split("### Abierto")[0]
    assert (
        f"- [decision, vigente] sustituciones con halving racional — motivo: conserva el invariante (nodo:{ids['d1']})"
        in vig
    )
    ab = md.split("### Abierto")[1].split("### Avisos")[0]
    assert f"(nodo:{ids['p1']})" in ab and "para ariel" in ab and ids["h1"] not in ab
    pend = md.split("### Pendientes de veredicto")[1]
    assert f"(nodo:{ids['h1']})" in pend and f"(nodo:{ids['m1']})" in pend and "1e-09 1 (commit 7c2e)" in pend
    assert f"(nodo:{ids['e1']})" in md.split("### Relacionado")[1]  # a un salto, no del tema
    assert md.rstrip().endswith(f"el tema canonico es nodo:{ids['t1']}.")
    with pytest.raises(Rechazo) as x:
        v.vista(P, "no existe")
    assert x.value.codigo == 404
    # Aprendizaje obligatorio: importacion y errores se propagan.
    monkeypatch.setitem(sys.modules, "aprendizaje", None)
    with pytest.raises(ModuleNotFoundError):
        v.vista(P, ids["t1"])
    import types

    falso = types.ModuleType("aprendizaje")
    falso.apoyos_rechazados = lambda pid: [{"id": ids["d1"], "texto": "depende del hallazgo rechazado h1"}]
    falso.reglas_cuestionadas = lambda pid: []
    falso.recurrencias = lambda pid: []
    monkeypatch.setitem(sys.modules, "aprendizaje", falso)
    av = v.vista(P, ids["t1"])["markdown"].split("### Avisos")[1].split("###")[0]
    assert f"- apoyos rechazados: depende del hallazgo rechazado h1 (nodo:{ids['d1']})" in av
    falso.reglas_cuestionadas = lambda pid: (_ for _ in ()).throw(RuntimeError("rota"))
    with pytest.raises(RuntimeError, match="rota"):
        v.briefing(P, temas=[ids["t1"]], desde_cierre=False)
    with pytest.raises(RuntimeError, match="rota"):
        v.vista(P, ids["t1"])


# --- 9. API ---------------------------------------------------------------------------------------------------


def test_api_rutas_y_errores(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    assert api.dispatch("POST", ["nadie", "veredictos"], {}, {})[0] == 404
    assert api.dispatch("GET", [], None, {})[0] == 404
    assert api.dispatch("GET", [P, "otra"], None, {})[0] == 404
    assert api.dispatch("POST", [P, "veredictos"], ["invalido"], {})[0] == 400
    assert (
        api.es_mia(["veredictos"])
        and api.es_mia(["rondas", "x", "cerrar"])
        and not api.es_mia(["rondas", "x", "estado"])
        and not api.es_mia([])
    )
    code, res = api.dispatch(
        "POST", [P, "veredictos"], {"items": [{"nodo": ids["h1"], "estado": "confirmado"}], "por": "frente:f"}, {}
    )
    assert code == 403
    code, res = api.dispatch(
        "POST",
        [P, "veredictos"],
        {"items": [{"nodo": ids["h1"], "estado": "confirmado"}], "por": COORD, "revision": inf["id"]},
        {},
    )
    assert code == 200 and res["aplicados"][0]["nodo"]["estado"] == "confirmado"
    assert (
        api.dispatch("POST", [P, "veredictos"], {"items": [{"nodo": ids["h1"], "estado": "nada"}], "por": COORD}, {})[0]
        == 409
    )
    assert (
        api.dispatch("POST", [P, "veredictos"], {"items": [{"nodo": ids["h1"], "estado": "nada"}]}, {})[0] == 400
    )  # sin por
    code, res = api.dispatch("GET", [P, "pendientes"], None, {"ronda": [r["id"]]})
    assert code == 200 and ids["h1"] not in {p["id"] for p in res["pendientes"]}
    assert api.dispatch("GET", [P, "pendientes"], None, {"ronda": ["x"]})[0] == 404
    code, res = api.dispatch("GET", [P, "duplicados"], None, {})
    assert code == 200 and res == {"duplicados": []}
    code, t = api.dispatch("POST", [P, "temas"], {"texto": "halving", "aliases": ["mitad"], "por": COORD}, {})
    assert code == 200 and t["creado"]
    assert api.dispatch("POST", [P, "temas"], {"texto": "", "por": COORD}, {})[0] == 400
    code, res = api.dispatch("GET", [P, "temas"], None, {})
    assert code == 200 and [x["texto"] for x in res["temas"]] == ["sustituciones", "halving"]
    code, b = api.dispatch(
        "GET",
        [P, "briefing"],
        None,
        {
            "temas": ["sustituciones,mitad"],
            "q": ["invariante", "halving"],
            "archivos": ["codigo/"],
            "desde_cierre": ["0"],
        },
    )
    assert (
        code == 200
        and b["temas"] == ["sustituciones", "mitad"]
        and b["consultas"] == ["invariante", "halving"]
        and b["cambios"] is None
    )
    assert ids["h1"] in {n["id"] for n in b["vigente"]}
    assert api.dispatch("GET", [P, "briefing"], None, {"q": ["("]})[0] == 400
    code, p = api.dispatch(
        "GET", [P, "preguntar"], None, {"q": ["halving entero"], "tipo": ["alternativa"], "saltos": ["2"]}
    )
    assert code == 200 and p["candidatos"][0]["id"] == ids["a1"] and ids["d1"] in {n["id"] for n in p["candidatos"]}
    assert api.dispatch("GET", [P, "preguntar"], None, {"q": ["x"], "saltos": ["dos"]})[0] == 400
    assert api.dispatch("GET", [P, "preguntar"], None, {})[0] == 400
    code, vs = api.dispatch("GET", [P, "vista"], None, {"tema": ["sustituciones"]})
    assert code == 200 and vs["tema"] == ids["t1"] and "### Vigente" in vs["markdown"]
    assert api.dispatch("GET", [P, "vista"], None, {})[0] == 400
    code, c = api.dispatch(
        "POST",
        [P, "rondas", r["id"], "cerrar"],
        {
            "por": COORD,
            "veredictos": [{"nodo": ids["d1"], "estado": "vigente"}],
            "sin_resolver": [{"nodo": ids["p1"], "motivo": "Ariel"}],
            "motivo": "fin",
        },
        {},
    )
    assert (
        code == 200
        and c["ronda"]["estado"] == "cerrada"
        and {p["id"] for p in c["pendientes"]} == {inf["id"], ids["m1"]}
    )
    assert api.dispatch("POST", [P, "rondas", r["id"], "cerrar"], {"por": COORD}, {})[0] == 409
    assert api.dispatch("POST", [P, "rondas", ids["h1"], "cerrar"], {"por": COORD}, {})[0] == 400


# --- rutas y medicion -----------------------------------------------------------------------------------------


def test_cierre_rechaza_actor_y_items_invalidos_sin_escrituras(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    antes = k.cambios(P)
    for opciones, codigo in [
        ({"por": "frente:f", "sin_resolver": [{"nodo": ids["h1"], "motivo": "m"}]}, 403),
        ({"por": COORD, "veredictos": [None]}, 400),
        ({"por": COORD, "sin_resolver": {}}, 400),
        (
            {
                "por": COORD,
                "veredictos": [
                    {"items": [{"nodo": ids["h1"], "estado": "confirmado"}]},
                    {"items": [{"nodo": ids["m1"], "estado": "invalido"}]},
                ],
            },
            409,
        ),
    ]:
        with pytest.raises(Rechazo) as error:
            v.cerrar_ronda(P, r["id"], **opciones)
        assert error.value.codigo == codigo
        assert k.cambios(P) == antes
        assert k.nodo(P, r["id"])["estado"] == "abierta"


def test_preguntar_pagina_sin_perder_candidatos_y_valida_limites(proy):
    r, e, inf, ids = _entrega(BLOQUE_HALVING)
    completo = v.preguntar(P, ["invariante"], saltos=2, limite=500)
    paginas, offset = [], 0
    while True:
        codigo, pagina = api.dispatch(
            "GET",
            [P, "preguntar"],
            None,
            {"q": ["invariante"], "saltos": ["2"], "offset": [str(offset)], "limite": ["2"]},
        )
        assert codigo == 200 and pagina["total"] == completo["total"]
        assert pagina["offset"] == offset and pagina["limite"] == 2
        paginas.extend(pagina["candidatos"])
        if pagina["siguientes"] is None:
            break
        assert pagina["siguientes"] == offset + 2
        offset = pagina["siguientes"]
    assert paginas == completo["candidatos"]
    vacia = v.preguntar(P, ["invariante"], saltos=2, offset=completo["total"])
    assert vacia["candidatos"] == [] and vacia["siguientes"] is None
    assert vacia["total"] == completo["total"]
    for opciones in (
        {"offset": -1},
        {"offset": True},
        {"offset": "0"},
        {"limite": 0},
        {"limite": 501},
        {"limite": 1.5},
    ):
        with pytest.raises(Rechazo):
            v.preguntar(P, ["invariante"], **opciones)
    for campo, valor in (("offset", "-1"), ("offset", "abc"), ("limite", "0"), ("limite", "501")):
        assert api.dispatch("GET", [P, "preguntar"], None, {"q": ["invariante"], campo: [valor]})[0] == 400


def test_norm_ruta_separa_localizador_y_el_prefijo_exige_separador():
    assert v.norm_ruta("codigo\\Sustituciones.py:88") == "codigo/sustituciones.py"
    assert v.norm_ruta("tests/x.py::test_k_impar") == "tests/x.py"
    assert v.norm_ruta("a.py:12:4") == "a.py"
    assert v.ruta_bajo("codigo/a/x.py:3", "codigo/a/") and v.ruta_bajo("codigo/a/x.py", "codigo/a")
    assert not v.ruta_bajo("codigo/ab/x.py", "codigo/a/") and not v.ruta_bajo("codigo/a/x.py", "")
    assert v.ruta_bajo("Codigo/A/X.PY", "codigo/a/x.py")
    assert v.normalizar("  Sustitución, ¡Halving!  ") == "sustitucion halving"


def _proyecto_grande():
    """200 nodos y 400 vinculos validos segun RELACIONES, sobre una sola conexion."""
    with k._abrir(P) as con:

        def n(tipo, texto, datos=None):
            return k.crear_nodo(P, tipo, texto, datos or {}, autor="f", con=con)["id"]

        def vinc(de, rel, a, motivo=None):
            k.vincular(P, de, rel, a, autor="f", motivo=motivo, con=con)

        temas = [n("tema", f"tema {i} modulo{i}") for i in range(20)]
        hall = [
            n(
                "hallazgo",
                f"hallazgo {i}: el modulo{i % 20} pierde el invariante caso{i}",
                {"donde": f"codigo/mod{i % 20}/a{i}.py:{i}", "gravedad": "media"},
            )
            for i in range(60)
        ]
        alts = [n("alternativa", f"alternativa {i} camino{i}") for i in range(30)]
        decs = [
            n("decision", f"decision {i}: usar camino{i % 30} en modulo{i % 20}", {"motivo": f"motivo {i}"})
            for i in range(40)
        ]
        incs = [
            n(
                "incidente",
                f"incidente {i}: fallo herramienta{i % 5} en modulo{i % 20}",
                {"herramienta": f"h{i % 5}", "agente": "codex"},
            )
            for i in range(20)
        ]
        regs = [n("regla", f"regla {i} para modulo{i}", {"ambito": "proyecto"}) for i in range(15)]
        meds = [
            n(
                "medicion",
                f"medicion {i} del modulo{i}",
                {"metrica": "ms", "valor": i, "unidad": "ms", "condicion": "pc"},
            )
            for i in range(15)
        ]
        assert len(temas + hall + alts + decs + incs + regs + meds) == 200
        total = 0
        for i, h in enumerate(hall):
            vinc(h, "sobre", temas[i % 20])
            vinc(h, "sobre", temas[(i + 1) % 20])
            total += 2
        for i, d in enumerate(decs):
            vinc(d, "motivada_por", hall[i])
            vinc(d, "descarta", alts[i % 30], "no")
            vinc(d, "elige", alts[(i + 1) % 30], "si")
            vinc(d, "sobre", temas[i % 20])
            total += 4
        for i, d in enumerate(decs[:21]):
            vinc(d, "sobre", temas[(i + 7) % 20])
            total += 1
        for i, d in enumerate(decs[:15]):
            vinc(d, "motivada_por", meds[i])
            total += 1
        for i, x in enumerate(incs):
            vinc(x, "sobre", temas[i % 20])
            total += 1
            if i:
                vinc(x, "repite", incs[i - 1])
                total += 1
        for i, rg in enumerate(regs):
            vinc(rg, "derivada_de", incs[i])
            vinc(rg, "aplica_a", temas[i])
            total += 2
        for i, m in enumerate(meds):
            vinc(m, "sobre", temas[i])
            total += 1
        assert total == 400
        return temas, hall, alts, decs


def test_rendimiento_briefing_y_preguntar_con_200_nodos_y_400_vinculos(proy, capsys):
    temas, hall, alts, decs = _proyecto_grande()
    with k._abrir(P) as con:
        assert con.execute("SELECT COUNT(*) FROM nodo").fetchone()[0] == 200
        assert con.execute("SELECT COUNT(*) FROM vinculo WHERE activo = 1").fetchone()[0] == 400
    consultas = ["invariante", "camino3 OR camino4", "modulo7"]
    v.briefing(P, temas=[temas[0], "tema 1 modulo1"], consultas=consultas)  # calienta (primera conexion, FTS)
    t0 = time.perf_counter()
    b = v.briefing(P, temas=[temas[0], "tema 1 modulo1"], consultas=consultas)
    t_b = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    p = v.preguntar(P, consultas, temas=[temas[0], "tema 1 modulo1"], saltos=1)
    t_p = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    d = v.duplicados(P)
    t_d = (time.perf_counter() - t0) * 1000
    total = len(b["vigente"]) + len(b["abierto"]) + len(b["otros"])
    print(
        f"\nMEDICION briefing={t_b:.1f}ms ({total} nodos) preguntar={t_p:.1f}ms ({p['total']} candidatos) duplicados={t_d:.1f}ms ({len(d)} pares)"
    )
    assert total > 30 and p["total"] > 30
    assert len({n["id"] for n in p["candidatos"]}) == min(p["total"], p["limite"])
    assert t_b < 200 and t_p < 200  # Umbral del encargo, sin relajar el oraculo.
