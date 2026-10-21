"""Regresiones del frente C (2026-10-20), diagnostico en .temp/coordinacion/2026-10-20/C-memoria:
vinculos retirados desde otro proyecto, revision siguiente de un informe capturado con huecos, entrega
y transicion en una sola transaccion, actor `server` enviado por un cliente HTTP, cierre de ronda sin
cierre_seq, sin_entrega -> entregado sin informe y reglas cuestionadas fuera de pendientes."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import conocimiento_api as api
import veredictos as v
from conocimiento import Rechazo

P, Q = "uno", "dos"
C = "coordinadora:c"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    k.registrar_proyecto(P, "Uno")
    k.registrar_proyecto(Q, "Dos")


def _n(pid, tipo, texto, datos=None):
    return k.crear_nodo(pid, tipo, texto, datos or {}, autor="f")["id"]


def _vinculo_de_q():
    h = _n(Q, "hallazgo", "h", {"donde": "a.py:1", "gravedad": "baja"})
    t = _n(Q, "tema", "t")
    k.vincular(Q, h, "sobre", t, autor="f")
    return h, t


def _activo(de, rel, a):
    with k._abrir(Q) as con:
        return con.execute(
            "SELECT activo FROM vinculo WHERE de = ? AND relacion = ? AND a = ?", (de, rel, a)
        ).fetchone()[0]


def test_retirar_vinculo_de_otro_proyecto_es_404_y_no_lo_toca():
    h, t = _vinculo_de_q()
    with pytest.raises(Rechazo) as e:
        k.retirar_vinculo(P, h, "sobre", t, por=C)
    assert e.value.codigo == 404
    assert _activo(h, "sobre", t) == 1
    k.retirar_vinculo(Q, h, "sobre", t, por=C)  # en su proyecto sigue andando
    assert _activo(h, "sobre", t) == 0


def test_veredicto_que_retira_un_vinculo_de_otro_proyecto_no_aplica_nada():
    h, t = _vinculo_de_q()
    hp = _n(P, "hallazgo", "propio", {"donde": "b.py:1", "gravedad": "baja"})
    with pytest.raises(Rechazo) as e:
        v.veredicto(
            P, [{"nodo": hp, "estado": "confirmado"}, {"retirar": {"de": h, "relacion": "sobre", "a": t}}], por=C
        )
    assert e.value.codigo == 404
    assert _activo(h, "sobre", t) == 1
    assert k.nodo(P, hp)["estado"] == "propuesto"  # atomico: el primer item tampoco quedo


def _encargo_enviado(pid=P, sid="s1"):
    r = k.abrir_ronda(pid, "r", autor=C)
    e = k.crear_encargo(pid, r["id"], "A", "x", autor=C)
    k.encargo_enviado(pid, e["id"], {"session_id": sid, "agent": "claude"})
    return r["id"], e["id"]


def test_informe_capturado_usa_la_revision_siguiente_aunque_haya_huecos():
    ronda, e = _encargo_enviado()
    k.cambiar_estado(P, e, "sin_entrega", por=C)
    k.entregar(P, e, "informe r1", revision=1, autor="frente:f")
    k.entregar(P, e, "informe r3", revision=3, autor="frente:f")
    k.cambiar_estado(P, e, "pendiente", por=C)
    k.encargo_enviado(P, e, {"session_id": "s1", "agent": "claude"})
    inf = k.informe_capturado(P, "s1", "informe capturado al cerrar el turno", ronda=ronda, origen={})
    assert inf is not None and inf["creado"] and inf["datos"]["revision"] == 4
    assert k.nodo(P, e)["estado"] == "entregado"


def test_informe_capturado_no_pierde_contra_una_entrega_explicita_concurrente(monkeypatch):
    ronda, e = _encargo_enviado()
    k.cambiar_estado(P, e, "sin_entrega", por=C)
    k.entregar(P, e, "informe r1", revision=1, autor="frente:f")  # el frente no la reabre
    k.cambiar_estado(P, e, "pendiente", por=C)
    k.encargo_enviado(P, e, {"session_id": "s1", "agent": "claude"})
    real = k.entregar

    def con_carrera(*args, **kw):
        # la coordinadora entrega r2 entre que la captura elige el encargo y entrega
        monkeypatch.setattr(k, "entregar", real)
        real(P, e, "informe explicito r2", revision=2, autor=C)
        return real(*args, **kw)

    monkeypatch.setattr(k, "entregar", con_carrera)
    inf = k.informe_capturado(P, "s1", "informe capturado", ronda=ronda, origen={})
    assert inf is not None and inf["creado"] and inf["datos"]["revision"] == 3
    assert k.nodos(P, tipo="informe")["total"] == 3


def test_entrega_y_paso_a_entregado_son_una_sola_transaccion(monkeypatch):
    _, e = _encargo_enviado()
    real = k.cambiar_estado

    def falla(pid, nid, nuevo, **kw):
        if nuevo == "entregado":
            raise k.sqlite3.OperationalError("database is locked")
        return real(pid, nid, nuevo, **kw)

    monkeypatch.setattr(k, "cambiar_estado", falla)
    with pytest.raises(k.sqlite3.OperationalError):
        k.entregar(P, e, "informe r1", revision=1, autor="frente:f")
    assert k.nodos(P, tipo="informe")["total"] == 0  # nada a medias
    assert k.nodo(P, e)["estado"] == "enviado"
    monkeypatch.setattr(k, "cambiar_estado", real)
    n = k.entregar(P, e, "informe r1", revision=1, autor="frente:f")  # el reintento completa
    assert n["creado"] and k.nodo(P, e)["estado"] == "entregado"


def test_reenviar_la_misma_entrega_completa_un_encargo_que_quedo_enviado():
    r = k.abrir_ronda(P, "r", autor=C)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=C)["id"]
    primera = k.entregar(P, e, "informe r1", revision=1, autor="frente:f")  # antes de tomarlo: sigue pendiente
    assert k.nodo(P, e)["estado"] == "pendiente"
    k.encargo_enviado(P, e, {"session_id": "s1", "agent": "claude"})
    again = k.entregar(P, e, "informe r1", revision=1, autor="frente:f")
    assert again["id"] == primera["id"] and not again["creado"]
    assert k.nodo(P, e)["estado"] == "entregado"
    assert k.nodos(P, tipo="informe")["total"] == 1


def test_reenvio_tardio_de_la_coordinadora_completa_un_encargo_sin_entrega():
    # mismo estado que dejaba una entrega tardia cuyo paso a entregado fallo en su propia transaccion:
    # el informe persiste, responde al encargo y el encargo sigue sin_entrega
    _, e = _encargo_enviado()
    k.cambiar_estado(P, e, "sin_entrega", por=C)
    primera = k.entregar(P, e, "informe tardio", revision=1, autor="frente:f")
    k.entregar(P, e, "informe tardio", revision=1, autor="frente:g")  # un frente no la reabre
    assert k.nodo(P, e)["estado"] == "sin_entrega"
    again = k.entregar(P, e, "informe tardio", revision=1, autor=C)
    assert again["id"] == primera["id"] and not again["creado"]
    assert k.nodo(P, e)["estado"] == "entregado"
    assert k.nodos(P, tipo="informe")["total"] == 1


def test_tomar_el_encargo_y_pasarlo_a_enviado_son_una_sola_transaccion(monkeypatch):
    r = k.abrir_ronda(P, "r", autor=C)
    e = k.crear_encargo(P, r["id"], "A", "x", autor=C)["id"]
    real = k.cambiar_estado

    def falla(pid, nid, nuevo, **kw):
        if nuevo == "enviado":
            raise k.sqlite3.OperationalError("database is locked")
        return real(pid, nid, nuevo, **kw)

    monkeypatch.setattr(k, "cambiar_estado", falla)
    with pytest.raises(k.sqlite3.OperationalError):
        k.encargo_enviado(P, e, {"session_id": "s1", "agent": "claude"})
    with k._abrir(P) as con:
        assert (
            con.execute("SELECT COUNT(*) FROM vinculo WHERE de = ? AND relacion = 'ejecutado_por'", (e,)).fetchone()[0]
            == 0
        )
    assert k.nodo(P, e)["estado"] == "pendiente"


@pytest.mark.parametrize("campo,valor", [("por", "server"), ("por", "server:x"), ("por", " Server:x")])
def test_api_rechaza_el_actor_server_enviado_por_un_cliente(campo, valor):
    _, e = _encargo_enviado()
    code, res = api.dispatch("POST", [P, "encargos", e, "estado"], {"estado": "entregado", campo: valor}, {})
    assert code == 403 and "server" in res["error"]
    assert k.nodo(P, e)["estado"] == "enviado"


def test_api_rechaza_server_como_autor_y_deja_a_los_demas():
    h = _n(P, "hallazgo", "h", {"donde": "a.py:1", "gravedad": "baja"})
    t = _n(P, "tema", "t")
    code, _ = api.dispatch("POST", [P, "vinculos"], {"de": h, "relacion": "sobre", "a": t, "autor": "server"}, {})
    assert code == 403
    code, _ = api.dispatch("POST", [P, "vinculos"], {"de": h, "relacion": "sobre", "a": t, "autor": "frente:f"}, {})
    assert code == 200
    code, _ = api.dispatch("POST", [P, "nodos", h, "estado"], {"estado": "confirmado", "por": C}, {})
    assert code == 200
    code, _ = api.dispatch("GET", [P], None, {})  # las lecturas no cambian
    assert code == 200


def test_cerrar_una_ronda_por_la_ruta_de_nodos_guarda_cierre_seq():
    r = k.abrir_ronda(P, "r", autor=C)["id"]
    code, res = api.dispatch("POST", [P, "nodos", r, "estado"], {"estado": "cerrada", "por": C}, {})
    assert code == 200 and res["estado"] == "cerrada"
    assert isinstance(k.nodo(P, r)["datos"].get("cierre_seq"), int)


def test_cerrar_una_ronda_sin_cerrar_ronda_se_rechaza():
    r = k.abrir_ronda(P, "r", autor=C)["id"]
    with pytest.raises(Rechazo) as e:
        k.cambiar_estado(P, r, "cerrada", por=C)
    assert e.value.codigo == 409
    with pytest.raises(Rechazo):
        v.veredicto(P, [{"nodo": r, "estado": "cerrada"}], por=C)
    assert k.nodo(P, r)["estado"] == "abierta"
    assert isinstance(k.cerrar_ronda(P, r, por=C)["datos"]["cierre_seq"], int)


def test_sin_entrega_a_entregado_exige_una_entrega():
    _, e = _encargo_enviado()
    k.cambiar_estado(P, e, "sin_entrega", por=C)
    with pytest.raises(Rechazo) as x:
        k.cambiar_estado(P, e, "entregado", por=C)
    assert x.value.codigo == 409 and k.nodo(P, e)["estado"] == "sin_entrega"
    k.entregar(P, e, "informe tardio", revision=1, autor=C)  # la entrega tardia explicita sigue
    assert k.nodo(P, e)["estado"] == "entregado"


def test_pendientes_muestran_las_reglas_cuestionadas():
    i1 = _n(P, "incidente", "timeout", {"herramienta": "red", "agente": "codex"})
    r = _n(P, "regla", "reintentar", {"ambito": "proyecto"})
    k.vincular(P, r, "derivada_de", i1, autor="f")
    k.cambiar_estado(P, r, "vigente", por=C)
    i2 = _n(P, "incidente", "timeout otra vez", {"herramienta": "red", "agente": "codex"})
    v.veredicto(P, [{"de": i2, "relacion": "repite", "a": i1}], por=C)
    assert k.nodo(P, r)["estado"] == "cuestionada"
    assert r in {n["id"] for n in v.pendientes(P)["pendientes"]}


def test_cerrar_y_revivir_una_sesion_alcanza_a_todos_sus_proyectos_y_el_incidente_va_al_actual():
    # una sesion que trabajo en dos carpetas tiene un nodo sesion en cada proyecto (anexo D de v5)
    tarjeta = {"session_id": "s2p", "agent": "claude"}
    nq = k.registrar_sesion(Q, tarjeta)
    np_ = k.registrar_sesion(P, tarjeta)  # P es el proyecto actual: el ultimo donde se la vio
    k.sesion_cerrada("s2p")
    assert (k.nodo(P, np_["id"])["estado"], k.nodo(Q, nq["id"])["estado"]) == ("cerrada", "cerrada")
    k.sesion_viva("s2p")
    assert (k.nodo(P, np_["id"])["estado"], k.nodo(Q, nq["id"])["estado"]) == ("viva", "viva")
    inc = k.incidente_operativo("s2p", "permiso denegado", herramienta="Bash", clave="incidente:s2p:1")
    assert inc is not None and inc["proyecto"] == P
    assert k.nodos(Q, tipo="incidente")["total"] == 0


def test_cierre_de_sesion_idempotente_y_un_proyecto_que_falla_no_frena_a_los_otros(monkeypatch):
    tarjeta = {"session_id": "s2f", "agent": "codex"}
    nq = k.registrar_sesion(Q, tarjeta)
    np_ = k.registrar_sesion(P, tarjeta)
    k.sesion_cerrada("s2f")
    k.sesion_cerrada("s2f")  # repetido: sin error ni cambio nuevo
    with k._abrir(P) as con:
        cambios = con.execute(
            "SELECT COUNT(*) FROM cambio WHERE nodo_id IN (?, ?) AND accion = 'estado'", (np_["id"], nq["id"])
        ).fetchone()[0]
    assert cambios == 2
    logs = []
    monkeypatch.setattr(k.state, "log", logs.append)
    real = k.cambiar_estado

    def falla_en_q(pid, nid, nuevo, **kw):
        if pid == Q:
            raise k.sqlite3.OperationalError("database is locked")
        return real(pid, nid, nuevo, **kw)

    monkeypatch.setattr(k, "cambiar_estado", falla_en_q)
    k.sesion_viva("s2f")
    assert k.nodo(P, np_["id"])["estado"] == "viva"
    assert k.nodo(Q, nq["id"])["estado"] == "cerrada"
    assert any("s2f" in m and Q in m and "locked" in m for m in logs)


def _regla_derivada(ronda=None):
    i1 = k.crear_nodo(P, "incidente", "timeout", {"herramienta": "red", "agente": "codex"}, autor="f", ronda=ronda)[
        "id"
    ]
    r = k.crear_nodo(P, "regla", "reintentar", {"ambito": "proyecto"}, autor="f", ronda=ronda)["id"]
    k.vincular(P, r, "derivada_de", i1, autor="f")
    k.cambiar_estado(P, r, "vigente", por=C)
    i2 = k.crear_nodo(
        P, "incidente", "timeout otra vez", {"herramienta": "red", "agente": "codex"}, autor="f", ronda=ronda
    )
    return i1, i2["id"], r


def test_si_cuestionar_falla_el_veredicto_que_confirma_el_repite_no_queda_a_medias(monkeypatch):
    import aprendizaje

    i1, i2, r = _regla_derivada()

    def falla(*a, **kw):
        raise k.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(aprendizaje, "_aplicar_cuestionada", falla)
    with pytest.raises(k.sqlite3.OperationalError):
        v.veredicto(P, [{"de": i2, "relacion": "repite", "a": i1}], por=C)
    with k._abrir(P) as con:
        repite = con.execute(
            "SELECT activo FROM vinculo WHERE de = ? AND relacion = 'repite' AND a = ?", (i2, i1)
        ).fetchone()
    assert repite is None  # todo o nada: ni el repite ni la regla cambiaron
    assert k.nodo(P, r)["estado"] == "vigente"


def test_cerrar_ronda_cuestiona_antes_de_cierre_seq_y_la_regla_sale_en_pendientes():
    ronda = k.abrir_ronda(P, "r", autor=C)["id"]
    i1, i2, r = _regla_derivada(ronda)
    res = v.cerrar_ronda(P, ronda, por=C, veredictos=[{"de": i2, "relacion": "repite", "a": i1}], sin_resolver=[])
    assert k.nodo(P, r)["estado"] == "cuestionada"
    assert [x["id"] for x in res["reglas_cuestionadas"]] == [r]
    cierre = k.nodo(P, ronda)["datos"]["cierre_seq"]
    with k._abrir(P) as con:
        seqs = [
            x[0] for x in con.execute("SELECT seq FROM cambio WHERE nodo_id = ? AND accion IN ('estado','datos')", (r,))
        ]
    assert seqs and max(seqs) <= cierre  # el cuestionamiento es parte del cierre, no un cambio posterior
    assert r in {p["id"] for p in res["pendientes"]}


def test_si_cuestionar_falla_el_cierre_de_ronda_se_deshace_entero(monkeypatch):
    import aprendizaje

    ronda = k.abrir_ronda(P, "r", autor=C)["id"]
    i1, i2, r = _regla_derivada(ronda)

    def falla(*a, **kw):
        raise k.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(aprendizaje, "_aplicar_cuestionada", falla)
    with pytest.raises(k.sqlite3.OperationalError):
        v.cerrar_ronda(P, ronda, por=C, veredictos=[{"de": i2, "relacion": "repite", "a": i1}])
    n = k.nodo(P, ronda)
    assert n["estado"] == "abierta" and "cierre_seq" not in n["datos"]
    assert k.nodo(P, r)["estado"] == "vigente"
    with k._abrir(P) as con:
        assert con.execute("SELECT 1 FROM vinculo WHERE de = ? AND relacion = 'repite'", (i2,)).fetchone() is None


class _BaseBloqueada:
    """Simula «database is locked» en las consultas FTS: sqlite3 no deja parchear execute."""

    def __init__(self, conexion):
        self.conexion = conexion

    def __enter__(self):
        self.con = self.conexion.__enter__()
        return self

    def __exit__(self, *exc):
        return self.conexion.__exit__(*exc)

    def execute(self, sql, *args):
        if "MATCH" in sql:
            raise k.sqlite3.OperationalError("database is locked")
        return self.con.execute(sql, *args)


def test_base_bloqueada_no_se_informa_como_consulta_fts_invalida(monkeypatch):
    _n(P, "hallazgo", "alfa", {"donde": "a.py:1", "gravedad": "baja"})
    with pytest.raises(Rechazo) as e:
        k.buscar(P, '"sin cerrar')
    assert e.value.codigo == 400 and "FTS invalida" in str(e.value)  # la sintaxis sigue siendo 400
    real = k._abrir
    monkeypatch.setattr(k, "_abrir", lambda pid: _BaseBloqueada(real(pid)))
    for buscar in (k.buscar, k.buscar_prosa):
        with pytest.raises(Rechazo) as e:
            buscar(P, "alfa")
        assert e.value.codigo == 503 and "FTS invalida" not in str(e.value) and "locked" in str(e.value)


def test_preguntar_usa_hasta_30_semillas_lexicas_por_mejor_puesto_y_avisa_el_corte():
    for i in range(40):
        _n(P, "hallazgo", f"alfa {i}", {"donde": f"a{i}.py:1", "gravedad": "baja"})
        _n(P, "hallazgo", f"beta {i}", {"donde": f"b{i}.py:1", "gravedad": "baja"})
    res = v.preguntar(P, ["alfa", "beta"], saltos=0)
    assert res["total"] == 30
    assert res["semillas_lexicas"] == {"encontradas": 60, "usadas": 30, "maximo": 30}
    puestos = sorted(c["puesto"] for c in res["candidatos"])
    assert puestos == sorted(list(range(1, 16)) * 2)  # 15 de cada lista: mejor puesto, no una sola consulta


def test_el_corte_de_semillas_no_compara_puntajes_de_consultas_distintas(monkeypatch):
    # tres listas: a y b de 20, c de 5. Hasta el puesto 12 entran 29; en el 13 queda un lugar para a13 o b13.
    # b tiene una escala BM25 mucho mejor: si el corte comparara puntajes elegiria b13; por id elige a13
    largos = {"a": (20, -1.0), "b": (20, -1000.0), "c": (5, -5.0)}

    def buscar(pid, q, tipo=None, limite=30):
        n, escala = largos[q]
        return [
            {"id": f"{q}{i + 1:02d}", "tipo": "hallazgo", "texto": q, "datos": {}, "puntaje": escala * (1 - i / 100)}
            for i in range(n)
        ]

    monkeypatch.setattr(k, "buscar", buscar)
    res = v.preguntar(P, ["a", "b", "c"], saltos=0, limite=100)
    ids = {c["id"] for c in res["candidatos"]}
    assert res["semillas_lexicas"] == {"encontradas": 45, "usadas": 30, "maximo": 30}
    assert "a13" in ids and "b13" not in ids
    # el orden final tampoco compara escalas: en el mismo puesto desempata el id, no el puntaje
    assert [c["id"] for c in res["candidatos"][:3]] == ["a01", "b01", "c01"]


# --- lote 8: paginacion con foto fija ---------------------------------------------------------------


def _tema_con(n, texto="tfoto"):
    t = _n(P, "tema", texto)
    ids = []
    for i in range(n):
        h = _n(P, "hallazgo", f"hallazgo {i}", {"donde": f"f{i}.py:1", "gravedad": "baja"})
        k.vincular(P, h, "sobre", t, autor="f")
        ids.append(h)
    return t, ids


def _ids(res):
    return [c["id"] for c in res["candidatos"]]


@pytest.fixture
def fotos_limpias(monkeypatch):
    monkeypatch.setattr(v, "_FOTOS", v._Fotos())
    return v._FOTOS


def _seq():
    with k._abrir(P) as con:
        return con.execute("SELECT COALESCE(MAX(seq), 0) FROM cambio WHERE proyecto = ?", (P,)).fetchone()[0]


def test_foto_fija_la_lista_entre_paginas_aunque_entren_nodos(fotos_limpias):
    t, _ = _tema_con(150)
    p1 = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=100)
    foto = p1["foto"]
    assert foto["token"] and foto["ids"] == 151 and foto["hasta_seq"] == _seq()  # 150 hallazgos y el tema
    nuevos = set(_tema_con(10, "otro")[1])
    for h in nuevos:
        k.vincular(P, h, "sobre", t, autor="f")
    p2 = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=100, offset=100, foto=foto["token"])
    todos = _ids(p1) + _ids(p2)
    assert p2["total"] == 151 and len(todos) == 151 and len(set(todos)) == 151
    assert not nuevos & set(todos)
    assert p2["foto"]["token"] == foto["token"]


def test_detalle_actual_marcado_si_cambio_despues_de_la_foto(fotos_limpias):
    _tema_con(30)
    p1 = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=10)
    tok = p1["foto"]["token"]
    ultimo = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=10, offset=20, foto=tok)["candidatos"][0]["id"]
    k.cambiar_estado(P, ultimo, "confirmado", por=C)
    p3 = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=10, offset=20, foto=tok)
    marca = {c["id"]: (c["estado"], c["cambio_despues_de_la_foto"]) for c in p3["candidatos"]}
    assert marca[ultimo] == ("confirmado", True)
    assert all(not m for i, (_, m) in marca.items() if i != ultimo)


def test_token_de_otra_consulta_es_409_y_vencido_o_desconocido_410(fotos_limpias, monkeypatch):
    _tema_con(5)
    k.registrar_proyecto("tres", "Tres")
    tok = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=2)["foto"]["token"]
    for kw in ({"saltos": 1}, {"tipo": "hallazgo"}, {"consultas": ["x"]}):
        args = {"consultas": [], "temas": ["tfoto"], "saltos": 0, **kw}
        with pytest.raises(Rechazo) as e:
            v.preguntar(P, args.pop("consultas"), offset=2, limite=2, foto=tok, **args)
        assert e.value.codigo == 409
    with pytest.raises(Rechazo) as e:
        v.preguntar("tres", [], temas=["tfoto"], saltos=0, offset=2, limite=2, foto=tok)
    assert e.value.codigo == 409
    with pytest.raises(Rechazo) as e:
        v.preguntar(P, [], temas=["tfoto"], saltos=0, offset=2, limite=2, foto="no-existe")
    assert e.value.codigo == 410
    ahora = v._reloj()
    monkeypatch.setattr(v, "_reloj", lambda: ahora + v.FOTO_TTL_S + 1)
    with pytest.raises(Rechazo) as e:
        v.preguntar(P, [], temas=["tfoto"], saltos=0, offset=2, limite=2, foto=tok)
    assert e.value.codigo == 410 and "repet" in str(e.value)


def test_sin_token_la_pagina_siguiente_recalcula_y_lo_dice(fotos_limpias):
    _tema_con(5)
    res = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=2, offset=2)
    assert res["foto"] is None and "recalcul" in res["foto_motivo"]


def test_calculo_inicial_inconsistente_es_409_sin_foto(fotos_limpias, monkeypatch):
    _tema_con(5)
    real = v._recuperar

    def con_escritura(*a, **kw):
        out = real(*a, **kw)
        _n(P, "hallazgo", "escrito durante el calculo", {"donde": "x.py:1", "gravedad": "baja"})
        return out

    monkeypatch.setattr(v, "_recuperar", con_escritura)
    with pytest.raises(Rechazo) as e:
        v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=2)
    assert e.value.codigo == 409 and len(fotos_limpias) == 0


def test_limites_de_memoria_de_las_fotos(fotos_limpias, monkeypatch):
    _tema_con(20)
    monkeypatch.setattr(v, "FOTOS_MAX", 2)
    toks = [v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=5)["foto"]["token"] for _ in range(3)]
    with pytest.raises(Rechazo) as e:
        v.preguntar(P, [], temas=["tfoto"], saltos=0, offset=5, limite=5, foto=toks[0])
    assert e.value.codigo == 410  # la mas vieja salio primero
    assert v.preguntar(P, [], temas=["tfoto"], saltos=0, offset=5, limite=5, foto=toks[2])["total"] == 21
    monkeypatch.setattr(v, "FOTO_MAX_BYTES", 200)
    grande = v.preguntar(P, [], temas=["tfoto"], saltos=0, limite=5)
    assert grande["foto"] is None and "demasiados" in grande["foto_motivo"]
    assert grande["total"] == 21 and len(grande["candidatos"]) == 5
    assert fotos_limpias.bytes <= v.FOTOS_MAX_BYTES


def test_api_traduce_la_foto_y_sus_errores(fotos_limpias):
    _tema_con(5)
    code, res = api.dispatch("GET", [P, "preguntar"], None, {"temas": ["tfoto"], "saltos": ["0"], "limite": ["2"]})
    assert code == 200
    tok = res["foto"]["token"]
    q = {"temas": ["tfoto"], "saltos": ["0"], "limite": ["2"], "offset": ["2"], "foto": [tok]}
    code, res2 = api.dispatch("GET", [P, "preguntar"], None, q)
    assert code == 200 and res2["foto"]["token"] == tok and res2["offset"] == 2
    code, err = api.dispatch("GET", [P, "preguntar"], None, {**q, "foto": ["vencido"]})
    assert code == 410 and "error" in err
