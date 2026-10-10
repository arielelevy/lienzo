"""Memoria automatica por carpeta (anexo A de v5, pedido de Ariel del 2026-10-09), texto roto al
entrar y su reparacion auditada, busqueda opt-in en la prosa, migracion del esquema y cuerpos byte por
byte. Todo sobre un LIENZO_HOME temporal (conftest)."""

import hashlib
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import captura
import conocimiento as k
import conocimiento_api as api
import veredictos
from conocimiento import Rechazo

BLOQUE = """Listo.

```conocimiento
{"version": 1, "nodos": [
  {"id": "h1", "tipo": "hallazgo", "texto": "la cola de captura no bloquea el lock", "datos": {"donde": "lienzo/captura.py:1", "gravedad": "media"}},
  {"id": "t1", "tipo": "tema", "texto": "captura", "datos": {}}
], "vinculos": [{"de": "h1", "relacion": "sobre", "a": "t1"}]}
```
"""


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(k, "_sesion_proyecto", {})
    monkeypatch.setattr(k, "_sesion_sin_proyecto", set())
    monkeypatch.setattr(k, "_incidentes_vistos", set())
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    monkeypatch.setattr(captura.state, "log", lambda msg: None)
    # las carpetas de prueba viven bajo la temporal del sistema, que la captura excluye a proposito
    monkeypatch.setattr(captura, "temporal", lambda cwd: False)
    monkeypatch.setattr(captura.identity, "pc_id", lambda: "pcA")
    captura.olvidar()
    yield
    captura.olvidar()


def _repo(base, nombre, remote=None):
    d = base / nombre
    (d / ".git").mkdir(parents=True)
    if remote:
        (d / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {remote}\n', encoding="utf-8")
    return d


def _tarjeta(sid, cwd, pc="pcA", agent="claude", model="opus"):
    return {"session_id": sid, "agent": agent, "model": model, "pc": pc, "cwd": str(cwd)}


def _ev(tipo, tarjeta, texto="", clave=None, origen=None):
    return {
        "tipo": tipo,
        "tarjeta": tarjeta,
        "texto": texto,
        "clave": clave or f"{tipo}:{texto}",
        "origen": origen or {},
    }


# --- proyecto = carpeta -----------------------------------------------------------------------


def test_la_primera_vista_crea_el_proyecto_y_la_sesion(tmp_path):
    repo = _repo(tmp_path, "Teorema", "git@github.com:ariel/teorema.git")
    s = captura.procesar(_ev("vista", _tarjeta("s1", repo / "src")))
    assert s["tipo"] == "sesion" and s["estado"] == "viva"
    p = k.proyecto("teorema")
    assert p["carpetas"] == [{"pc": "pcA", "cwd": k.norm_cwd(str(repo))}]
    assert p["remotes"] == ["github.com/ariel/teorema"]
    # la segunda vista (otra sesion, otra subcarpeta) cae en el mismo proyecto, sin otro registro
    captura.olvidar()
    captura.procesar(_ev("vista", _tarjeta("s2", repo)))
    assert [x["id"] for x in k.proyectos()] == ["teorema"]
    assert k.resumen("teorema")["nodos"]["sesion"] == {"viva": 2}


def test_el_remote_une_la_misma_carpeta_en_otra_pc_pero_no_dos_carpetas_de_una_pc(tmp_path):
    a = _repo(tmp_path / "pcA", "lienzo", "https://github.com/ariel/lienzo")
    b = _repo(tmp_path / "pcB", "lienzo-copia", "https://github.com/ariel/lienzo.git")
    c = _repo(tmp_path / "pcA", "lienzo-clon", "https://github.com/ariel/lienzo")
    assert captura.proyecto_de(_tarjeta("s1", a)) == "lienzo"
    assert captura.proyecto_de(_tarjeta("s2", b, pc="pcB")) == "lienzo"  # misma carpeta en la otra PC
    otro = captura.proyecto_de(_tarjeta("s3", c))  # otra carpeta de pcA: otro proyecto
    assert otro == "lienzo-clon"
    assert k.proyecto(otro)["remotes"] == []  # el remote ya era de lienzo
    assert len(k.proyecto("lienzo")["carpetas"]) == 2


def test_un_worktree_es_el_proyecto_del_repo_principal(tmp_path):
    repo = _repo(tmp_path, "app")
    wt = tmp_path / "app" / ".claude" / "worktrees" / "x"
    admin = repo / ".git" / "worktrees" / "x"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..", encoding="utf-8")
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {admin}", encoding="utf-8")
    assert k.norm_cwd(k.carpeta_de(str(wt))) == k.norm_cwd(str(repo))


def test_homonimos_de_carpetas_distintas_no_se_fusionan(tmp_path):
    p1 = captura.proyecto_de(_tarjeta("s1", tmp_path / "uno" / "app"))
    p2 = captura.proyecto_de(_tarjeta("s2", tmp_path / "dos" / "app"))
    assert (p1, p2) == ("app", "app-2")


def test_carpeta_temporal_y_sin_cwd_no_registran(tmp_path, monkeypatch):
    monkeypatch.setattr(captura, "temporal", lambda cwd: True)
    assert captura.procesar(_ev("pedido", _tarjeta("s1", tmp_path / "x"), "hola")) is None
    assert captura.procesar(_ev("pedido", {"session_id": "s2"}, "hola")) is None
    assert k.proyectos() == []


def test_temporal_reconoce_la_carpeta_temporal(tmp_path):
    import importlib

    real = importlib.reload(captura)  # sin el monkeypatch del autouse
    try:
        assert real.temporal(str(tmp_path))
        assert not real.temporal(None)
    finally:
        importlib.reload(captura)


def test_resolver_por_carpeta_gana_al_remote(tmp_path):
    k.registrar_proyecto("viejo", remotes=["github.com/a/b"])
    repo = _repo(tmp_path, "b", "https://github.com/a/b")
    k.registrar_proyecto("nuevo", carpetas=[{"pc": "pcA", "cwd": str(repo)}])
    assert k.resolver_proyecto(repo_key="github.com/a/b", cwd=str(repo / "sub"), pc="pcA") == "nuevo"
    assert k.resolver_proyecto(repo_key="github.com/a/b", cwd="D:/otra", pc="pcA") == "viejo"


def test_api_carpeta_resuelve_sin_crear_y_crea_con_post(tmp_path):
    cwd = str(tmp_path / "proyecto-x")
    code, r = api.dispatch("GET", ["carpeta"], None, {"cwd": [cwd], "pc": ["pcA"]})
    assert code == 200 and r["proyecto"] is None
    code, r = api.dispatch("POST", ["carpeta"], {"cwd": cwd, "pc": "pcA"}, {})
    assert code == 200 and r["proyecto"] == "proyecto-x"
    assert api.dispatch("GET", ["carpeta"], None, {"cwd": [cwd], "pc": ["pcA"]})[1]["proyecto"] == "proyecto-x"


# --- capturas -------------------------------------------------------------------------------


def test_pedido_respuesta_y_envio_quedan_observados_con_sesion_agente_y_modelo(tmp_path):
    t = _tarjeta("s1", tmp_path / "app", agent="codex", model="gpt-5")
    captura.procesar(_ev("pedido", t, "arregla el login", "p1", {"via": "terminal"}))
    captura.procesar(_ev("respuesta", t, "listo, el login anda", "r1"))
    captura.procesar(_ev("envio", t, "encargo B", "e1", {"de": "coord", "kind": "send"}))
    assert captura.procesar(_ev("pedido", t, "arregla el login", "p1")) is None  # idempotente por clave
    caps = k.capturas("app")
    assert caps["total"] == 3
    assert {c["clase"] for c in caps["capturas"]} == {"pedido", "respuesta", "envio"}
    for c in caps["capturas"]:
        assert c["estado"] == "observado" and c["agente"] == "codex" and c["modelo"] == "gpt-5" and c["pc"] == "pcA"
        assert c["fecha"].endswith("Z")
    assert k.capturas("app", clase="envio")["capturas"][0]["origen"] == {"de": "coord", "kind": "send"}
    # nada de esto es un nodo de conocimiento ni entra al BM25 de nodos
    assert k.buscar("app", "login") == []
    with k._abrir("app") as con, pytest.raises(sqlite3.DatabaseError, match="no se modifica"):
        con.execute("UPDATE captura SET texto = 'x'")


def test_una_captura_larga_se_recorta_con_el_hash_del_original(tmp_path):
    t = _tarjeta("s1", tmp_path / "app")
    largo = "á" * (k.CAPTURA_MAX_BYTES)  # dos bytes cada una
    c = captura.procesar(_ev("respuesta", t, largo, "r"))
    assert c["recortado"] == 1 and c["bytes"] == 2 * k.CAPTURA_MAX_BYTES
    assert c["hash"] == hashlib.sha256(largo.encode()).hexdigest()
    assert len(c["texto"].encode()) < k.CAPTURA_MAX_BYTES + 100


def test_secretos_con_forma_conocida_se_tapan_antes_de_encolar(monkeypatch):
    eventos = []
    monkeypatch.setattr(captura, "encolar", eventos.append)
    s = {"session_id": "s1", "agent": "claude", "cwd": "D:/x"}
    tok = "ghp_" + "a" * 36
    captura.pedido(s, f"usa {tok} y password=hunter2hunter y Bearer {'x' * 30}", "terminal")
    ev = eventos[0]
    assert tok not in ev["texto"] and "hunter2hunter" not in ev["texto"] and "x" * 30 not in ev["texto"]
    assert ev["texto"].count(captura.TAPADO) == 3 and "password=" in ev["texto"]
    assert ev["redactado"] is True
    texto, tapado = captura.tapar("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----")
    assert texto == captura.TAPADO and tapado


def test_lo_que_tecleo_el_lienzo_no_se_captura_dos_veces_y_un_turno_una_vez(monkeypatch):
    eventos = []
    monkeypatch.setattr(captura, "encolar", eventos.append)
    s = {"session_id": "s1", "agent": "codex", "cwd": "D:/x"}
    captura.pedido(s, "encargo", "lienzo")
    captura.pedido(s, "tipeado", None, turno="t1")
    captura.pedido(s, "tipeado", None, turno="t1")  # la transcripcion se relee
    captura.envio(s, "encargo", de="coord", adjuntos=["C:/x/foto.png"], kind="send")
    assert [e["tipo"] for e in eventos] == ["pedido", "envio"]
    assert eventos[1]["origen"] == {"de": "coord", "kind": "send", "adjuntos": ["foto.png"]}


def test_el_origen_del_envio_viaja_por_contexto(monkeypatch):
    eventos = []
    monkeypatch.setattr(captura, "encolar", eventos.append)
    with captura.origen(clase="regla", de="a", rule_id="r1", kind="on_stop"):
        captura.envio({"session_id": "b", "cwd": "D:/x"}, "seguí", **captura.origen_actual())
    assert captura.origen_actual() == {}
    assert eventos[0]["tipo"] == "regla" and eventos[0]["origen"]["rule_id"] == "r1"


def test_sin_arrancar_la_cola_no_se_encola_nada():
    if captura._cola is None:  # el server la arranca; en las pruebas no existe
        captura.encolar({"tipo": "vista"})  # no levanta ni guarda nada
        assert captura._cola is None


def test_la_sesion_capturada_recibe_incidentes_sin_encargo(tmp_path):
    t = _tarjeta("s1", tmp_path / "app")
    captura.procesar(_ev("vista", t))
    n = k.incidente_operativo("s1", "permiso denegado: Bash", herramienta="Bash", clave="i1")
    assert n is not None and n["estado"] == "observado"
    k.sesion_cerrada("s1")
    assert k.nodos("app", tipo="sesion")["nodos"][0]["estado"] == "cerrada"


def test_la_cache_negativa_no_pierde_la_sesion_capturada_despues(tmp_path):
    k.registrar_proyecto("otro")
    assert k._proyecto_de_sesion("s1") is None  # cache negativa
    captura.procesar(_ev("vista", _tarjeta("s1", tmp_path / "app")))
    assert k._proyecto_de_sesion("s1") == "app"


# --- informes capturados --------------------------------------------------------------------


def test_respuesta_con_bloque_es_un_informe_con_su_conocimiento_propuesto(tmp_path):
    t = _tarjeta("s1", tmp_path / "app")
    c = captura.procesar(_ev("respuesta", t, BLOQUE, "r1"))
    inf = k.nodo("app", c["informe"])
    assert inf["estado"] == "recibido" and inf["datos"]["conocimiento"]["estado"] == "incorporado"
    h = k.nodos("app", tipo="hallazgo")["nodos"][0]
    assert h["estado"] == "propuesto"  # nunca vigente
    rel = {(v["relacion"]) for v in k.nodo("app", h["id"])["vinculos"]["salen"]}
    assert {"declarado_en", "encontrado_por", "sobre"} <= rel
    assert k.leer_cuerpo("app", inf["datos"]["ruta"]) == BLOQUE.strip()


def test_respuesta_con_bloque_de_una_sesion_con_encargo_lo_entrega_y_la_entrega_explicita_no_duplica(tmp_path):
    cwd = tmp_path / "app"
    pid = captura.proyecto_de(_tarjeta("s1", cwd))
    r = k.abrir_ronda(pid, "r", autor="coordinadora:c")
    e = k.crear_encargo(pid, r["id"], "A", "hace X", autor="coordinadora:c")
    k.encargo_enviado(pid, e["id"], _tarjeta("s1", cwd))
    c = captura.procesar(_ev("respuesta", _tarjeta("s1", cwd), BLOQUE, "r1"))
    assert k.nodo(pid, e["id"])["estado"] == "entregado"
    inf = k.nodo(pid, c["informe"])
    assert inf["datos"]["revision"] == 1 and inf["ronda"] == r["id"]
    # la coordinadora entrega lo mismo a mano (con el texto que leyo, que es el mismo): devuelve el informe
    again = k.entregar(pid, e["id"], BLOQUE.strip(), revision=2, autor="coordinadora:c")
    assert again["id"] == inf["id"] and not again["creado"]
    assert k.nodos(pid, tipo="hallazgo")["total"] == 1


def test_la_entrega_explicita_adopta_un_informe_capturado_sin_encargo(tmp_path):
    cwd = tmp_path / "app"
    c = captura.procesar(_ev("respuesta", _tarjeta("s1", cwd), BLOQUE, "r1"))
    pid = "app"
    r = k.abrir_ronda(pid, "r", autor="coordinadora:c")
    e = k.crear_encargo(pid, r["id"], "A", "hace X", autor="coordinadora:c")
    k.encargo_enviado(pid, e["id"], _tarjeta("s1", cwd))
    n = k.entregar(pid, e["id"], BLOQUE.strip(), revision=1, autor="coordinadora:c")
    assert n["id"] == c["informe"] and n["adoptado"]
    assert k.nodo(pid, e["id"])["estado"] == "entregado"
    assert k.nodo(pid, n["id"])["ronda"] == r["id"]
    assert k.nodos(pid, tipo="hallazgo")["total"] == 1  # el bloque no se incorpora dos veces
    assert any(x["accion"] == "adopcion" for x in k.nodo(pid, n["id"])["cambios"])


# --- texto roto -----------------------------------------------------------------------------


def test_texto_roto_marca_posicion_y_clase():
    marcas = k.texto_roto("bien\nrevisi\ufffdn y AcciÃ³n")
    assert [(m["clase"], m["linea"], m["columna"]) for m in marcas] == [("reemplazo", 2, 7), ("mojibake", 2, 16)]
    assert marcas[1]["reparado"] == "ó"
    assert k.texto_roto("Encargo común — «sano» → ok") == []
    assert "\ufffd" not in k.describir_roto(marcas)


def test_entregar_rechaza_texto_roto_con_posicion(tmp_path):
    k.registrar_proyecto("p")
    r = k.abrir_ronda("p", "r", autor="c")
    e = k.crear_encargo("p", r["id"], "A", "x", autor="c")
    with pytest.raises(Rechazo, match="linea 1, columna 8"):
        k.entregar("p", e["id"], "informe\ufffd", revision=1, autor="f")
    with pytest.raises(Rechazo, match="quiso decir «é»"):
        k.entregar("p", e["id"], "cafÃ© frío", revision=1, autor="f")
    assert k.nodos("p", tipo="informe")["total"] == 0


def test_post_nodos_y_bloque_rechazan_texto_roto(tmp_path):
    k.registrar_proyecto("p")
    code, res = api.dispatch(
        "POST", ["p", "nodos"], {"tipo": "tema", "texto": "revisi\ufffdn", "datos": {}, "autor": "c"}, {}
    )
    assert code == 400 and "texto:" in res["error"]
    code, res = api.dispatch(
        "POST",
        ["p", "nodos"],
        {"tipo": "hallazgo", "texto": "ok", "datos": {"donde": "dominio:Ã³", "gravedad": "baja"}, "autor": "c"},
        {},
    )
    assert code == 400 and "datos.donde" in res["error"]
    bloque = json.dumps(
        {"version": 1, "nodos": [{"id": "t1", "tipo": "tema", "texto": "tard\ufffd", "datos": {}}]}, ensure_ascii=False
    )
    with k._abrir("p") as con:
        b, err = k.validar_bloque(con, "p", bloque)
    assert b is None and err[0]["donde"] == "nodo t1" and "U+FFFD" in err[0]["error"]


def test_reparar_mojibake_por_auditoria_y_listar_lo_irrecuperable(tmp_path):
    k.registrar_proyecto("p")
    # nodos rotos como los que dejaria un cliente que decodifico mal (entran por crear_nodo, sin validar)
    roto = k.crear_nodo("p", "tema", "Encargo comÃºn → ok", {"aliases": ["revisiÃ³n"]}, autor="c")
    perdido = k.crear_nodo("p", "tema", "tard\ufffd", autor="c")
    sano = k.crear_nodo("p", "tema", "sano", autor="c")
    medida = k.texto_roto_proyecto("p")
    assert {n["id"]: n["reparable"] for n in medida["nodos_rotos"]} == {roto["id"]: True, perdido["id"]: False}
    with pytest.raises(Rechazo):
        k.reparar_texto("p", por="frente:x")
    seco = k.reparar_texto("p", por="coordinadora:c")
    assert not seco["aplicado"] and k.nodo("p", roto["id"])["texto"] == "Encargo comÃºn → ok"
    hecho = k.reparar_texto("p", por="coordinadora:c", aplicar=True)
    assert [x["id"] for x in hecho["reparados"]] == [roto["id"]]
    assert [x["id"] for x in hecho["irrecuperables"]] == [perdido["id"]]
    n = k.nodo("p", roto["id"])
    assert n["texto"] == "Encargo común → ok" and n["datos"]["aliases"] == ["revisión"]
    cambio = next(c for c in n["cambios"] if c["accion"] == "texto")
    assert cambio["anterior"]["texto"] == "Encargo comÃºn → ok" and cambio["autor"] == "coordinadora:c"
    assert (
        k.nodo("p", perdido["id"])["texto"] == "tard\ufffd"
        and k.nodo("p", sano["id"])["cambios"][-1]["accion"] == "nodo"
    )
    assert k.buscar("p", "comun")  # el FTS se actualizo
    assert k.texto_roto_proyecto("p")["nodos_rotos"][0]["id"] == perdido["id"]


# --- prosa ----------------------------------------------------------------------------------


def test_preguntar_con_prosa_es_opt_in_y_no_mezcla(tmp_path):
    k.registrar_proyecto("p")
    r = k.abrir_ronda("p", "r", autor="c")
    e = k.crear_encargo("p", r["id"], "A", "# Encargo\nmedir la latencia del espejo entre PCs", autor="c")
    k.crear_nodo("p", "tema", "latencia", autor="c")
    captura.procesar(_ev("respuesta", _tarjeta("s1", tmp_path / "p2"), "la latencia bajo a 40 ms", "x"))
    sin = veredictos.preguntar("p", ["latencia"])
    assert "prosa" not in sin
    con = veredictos.preguntar("p", ["latencia"], prosa=True)
    assert {k2: v for k2, v in con.items() if k2 != "prosa"} == sin
    assert [p["nodo"] for p in con["prosa"]] == [e["id"]]
    assert con["prosa"][0]["marca"] == "prosa, no declarado" and "[latencia]" in con["prosa"][0]["fragmento"]
    # la captura es de otro proyecto (otra carpeta): no aparece
    prosa = k.buscar_prosa("p2", "latencia")
    assert [x["fuente"] for x in prosa] == ["captura:respuesta"]
    code, res = api.dispatch("GET", ["p", "preguntar"], None, {"q": ["latencia"], "prosa": ["1"]})
    assert code == 200 and res["prosa"]
    with pytest.raises(Rechazo):
        k.buscar_prosa("p", '"sin cerrar')


# --- una base para todo el lienzo: importar las viejas por proyecto ------------------------------

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


def base_vieja(pid, texto="# Encargo\nhalving entero", con_origen=None):
    """Una base por proyecto como las que hubo hasta el esquema 3 (la viva del proyecto lienzo era 1), con
    una ronda, un encargo con su cuerpo, un tema y su vinculo. `con_origen` agrega las columnas pc y
    seq_origen del esquema 3 con cambios de esa PC. La registra en el indice sin abrir la base central."""
    carpeta = os.path.join(k.raiz(), pid)
    os.makedirs(os.path.join(carpeta, "rondas", f"r-{pid}"), exist_ok=True)
    with open(os.path.join(carpeta, "rondas", f"r-{pid}", "encargo-A.md"), "w", encoding="utf-8") as f:
        f.write(texto)
    con = sqlite3.connect(os.path.join(carpeta, "conocimiento.sqlite"))
    con.executescript(V1)
    if con_origen:
        con.executescript("ALTER TABLE cambio ADD COLUMN pc TEXT; ALTER TABLE cambio ADD COLUMN seq_origen INTEGER;")
    f = "2026-10-08T21:00:00.000Z"
    con.execute("INSERT INTO proyecto VALUES (?,?,?)", (pid, pid, f))
    nodos = [
        (f"r-{pid}", "ronda", "ronda 1", "{}", "abierta", None, None),
        (
            f"e-{pid}",
            "encargo",
            "Encargo A",
            json.dumps({"ruta": f"rondas/r-{pid}/encargo-A.md", "letra": "A"}),
            "pendiente",
            f"r-{pid}",
            f"encargo:r-{pid}:A",
        ),
        (f"t-{pid}", "tema", "halving", "{}", None, None, None),
    ]
    for nid, tipo, texto_n, datos, estado, ronda, clave in nodos:
        con.execute(
            "INSERT INTO nodo (id, proyecto, tipo, texto, datos, estado, autor, origen, ronda, fecha, clave_ingesta)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nid, pid, tipo, texto_n, datos, estado, "c", "{}", ronda, f, clave),
        )
        con.execute(
            "INSERT INTO cambio (proyecto, nodo_id, accion, nuevo, autor, motivo, origen, fecha) VALUES (?,?,?,?,?,?,?,?)",
            (pid, nid, "nodo", json.dumps({"id": nid, "tipo": tipo, "texto": texto_n}), "c", "", "{}", f),
        )
    con.execute("INSERT INTO vinculo VALUES (?,?,?,1,?,?,?,NULL)", (f"e-{pid}", "sobre", f"t-{pid}", f, "c", "{}"))
    if con_origen:
        con.execute("UPDATE cambio SET pc = ?, seq_origen = seq + 100", (con_origen,))
    con.commit()
    con.close()
    idx = k._leer_indice()
    idx["proyectos"][pid] = {"nombre": pid, "remotes": [], "carpetas": [], "creado": f}
    k._guardar_indice(idx)


def test_la_base_vieja_de_un_proyecto_pasa_entera_a_la_del_lienzo(monkeypatch):
    monkeypatch.setattr(k.identity, "pc_id", lambda: "pcA")
    base_vieja("p")
    assert not os.path.exists(k.db_path())
    assert [x["nodo"] for x in k.buscar_prosa("p", "halving")] == ["e-p"]  # la prosa se indexo del cuerpo
    assert k.nodos("p")["total"] == 3 and k.buscar("p", "halving")[0]["id"] == "t-p"
    assert [v["a"] for v in k.nodo("p", "e-p")["vinculos"]["salen"]] == ["t-p"]
    cambios = k.cambios("p")
    assert len(cambios) == 3 and all(c["pc"] == "pcA" and c["seq_origen"] == c["seq"] for c in cambios)
    vieja = os.path.join(k.raiz(), "p", "conocimiento.sqlite")
    assert not os.path.exists(vieja) and os.path.isfile(vieja + ".importada")  # renombrada, no borrada
    # despues de importar todo sigue andando en la base del lienzo
    k.crear_encargo("p", "r-p", "B", "# Encargo B", autor="c")
    with pytest.raises(Rechazo):
        k.crear_encargo("p", "r-p", "A", "repetido", autor="c")  # la clave del encargo viejo sigue valiendo


def test_dos_proyectos_viejos_y_cuatro_aperturas_a_la_vez_importan_una_vez(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    base_vieja("p")
    base_vieja("q")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pid: k.resumen(pid), ["p", "q", "p", "q"]))
    with k._abrir("p") as con:
        assert con.execute("SELECT COUNT(*) FROM prosa_fts").fetchone()[0] == 2  # uno por proyecto, no 8
        filas = con.execute("SELECT proyecto, COUNT(*) FROM nodo GROUP BY proyecto ORDER BY proyecto").fetchall()
        assert [tuple(f) for f in filas] == [("p", 3), ("q", 3)]
    assert {n["id"] for n in k.nodos("q")["nodos"]} == {"r-q", "e-q", "t-q"}


def test_una_base_vieja_que_falla_no_frena_a_las_demas_y_se_reintenta(monkeypatch):
    base_vieja("p")
    base_vieja("q")
    original = k._rellenar_prosa

    def falla_en_p(con, pid):
        if pid == "p":
            raise OSError("disco")
        return original(con, pid)

    monkeypatch.setattr(k, "_rellenar_prosa", falla_en_p)
    assert k.nodos("q")["total"] == 3  # q entro igual
    assert k.nodos("p")["total"] == 0
    assert os.path.isfile(os.path.join(k.raiz(), "p", "conocimiento.sqlite"))  # p queda donde estaba
    assert not os.path.isfile(os.path.join(k.raiz(), "q", "conocimiento.sqlite"))
    monkeypatch.setattr(k, "_rellenar_prosa", original)
    k._revisadas.clear()  # el proceso siguiente
    assert k.nodos("p")["total"] == 3 and k.nodos("q")["total"] == 3


def test_una_base_vieja_corrupta_no_deja_sin_memoria_a_nadie():
    base_vieja("q")
    os.makedirs(os.path.join(k.raiz(), "p"), exist_ok=True)
    with open(os.path.join(k.raiz(), "p", "conocimiento.sqlite"), "wb") as f:
        f.write(b"esto no es una base")
    idx = k._leer_indice()
    idx["proyectos"]["p"] = {"nombre": "p", "remotes": [], "carpetas": [], "creado": k.ahora()}
    k._guardar_indice(idx)
    assert k.nodos("q")["total"] == 3
    assert k.nodos("p")["total"] == 0
    assert k.crear_nodo("p", "tema", "p sigue andando", autor="c")["creado"]  # su fila de proyecto existe


def test_reimportar_una_base_vieja_que_no_se_renombro_no_duplica(monkeypatch):
    base_vieja("p")
    monkeypatch.setattr(k.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("abierta")))
    assert len(k.cambios("p")) == 3
    vieja = os.path.join(k.raiz(), "p", "conocimiento.sqlite")
    con = sqlite3.connect(vieja)  # el server viejo siguio escribiendo
    con.execute(
        "INSERT INTO cambio (proyecto, nodo_id, accion, nuevo, autor, motivo, origen, fecha) VALUES (?,?,?,?,?,?,?,?)",
        ("p", "t-p", "datos", "{}", "c", "tarde", "{}", k.ahora()),
    )
    con.commit()
    con.close()
    k._revisadas.clear()
    assert [c["motivo"] for c in k.cambios("p")][-1] == "tarde" and len(k.cambios("p")) == 4  # solo lo nuevo


def test_una_base_vieja_que_aparece_despues_se_importa_al_arrancar():
    k.registrar_proyecto("otro")  # la base del lienzo ya existe
    base_vieja("p")
    k._revisadas.clear()
    assert k.nodos("p")["total"] == 3


def test_la_misma_sesion_en_dos_proyectos_tiene_un_nodo_en_cada_uno(tmp_path):
    a = captura.proyecto_de(_tarjeta("s1", tmp_path / "uno"))
    b = captura.proyecto_de(_tarjeta("s1", tmp_path / "dos"))
    captura.procesar(_ev("pedido", _tarjeta("s1", tmp_path / "uno"), "en uno", "c1"))
    captura.procesar(_ev("pedido", _tarjeta("s1", tmp_path / "dos"), "en dos", "c2"))  # antes: UNIQUE nodo.id
    na, nb = k.nodos(a, tipo="sesion")["nodos"], k.nodos(b, tipo="sesion")["nodos"]
    assert len(na) == len(nb) == 1 and na[0]["id"] != nb[0]["id"]
    assert k.capturas(b)["capturas"][0]["texto"] == "en dos"


def test_el_id_de_sesion_es_el_mismo_en_dos_pcs_con_el_mismo_remote():
    k.registrar_proyecto("lienzo", remotes=["github.com/a/lienzo"])
    k.registrar_proyecto("lienzo-2", remotes=["github.com/a/otro"])
    uno = k.id_de_sesion("lienzo", "s1")
    assert uno != k.id_de_sesion("lienzo-2", "s1")
    import uuid

    assert uno == uuid.uuid5(uuid.NAMESPACE_URL, "lienzo:sesion:github.com/a/lienzo:s1").hex


def test_los_cambios_de_otra_pc_conservan_su_origen_al_importar(monkeypatch):
    monkeypatch.setattr(k.identity, "pc_id", lambda: "pcA")
    base_vieja("p", con_origen="pcB")
    cambios = k.cambios("p")
    assert {(c["pc"], c["seq_origen"]) for c in cambios} == {("pcB", 101), ("pcB", 102), ("pcB", 103)}
    k.crear_nodo("p", "tema", "nuevo", autor="c")
    assert k.cambios("p")[-1]["pc"] == "pcA"


def test_el_mismo_texto_de_clave_en_dos_proyectos_no_choca():
    k.registrar_proyecto("p")
    k.registrar_proyecto("q")
    a = k.crear_nodo("p", "tema", "x", autor="c", clave_ingesta="tema:x")
    b = k.crear_nodo("q", "tema", "x", autor="c", clave_ingesta="tema:x")
    assert a["creado"] and b["creado"] and a["id"] != b["id"]
    assert not k.crear_nodo("p", "tema", "x", autor="c", clave_ingesta="tema:x")["creado"]


# --- cuerpos byte por byte -------------------------------------------------------------------


def test_el_cuerpo_guardado_verifica_su_hash(tmp_path):
    k.registrar_proyecto("p")
    r = k.abrir_ronda("p", "r", autor="c")
    e = k.crear_encargo("p", r["id"], "A", "x", autor="c")
    cuerpo = "linea uno\nlinea dos\r\ncon tilde: acción\n"
    n = k.entregar("p", e["id"], cuerpo, revision=1, autor="f")
    with open(os.path.join(k._carpeta("p"), *n["datos"]["ruta"].split("/")), "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == n["datos"]["hash"]


# --- enganches reales: hook, cierre de turno, envio del server, touch -------------------------


@pytest.fixture
def enganche(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # el orden importa, como en test_server.py: `from lienzo import server` engancha rules a sessions
    from lienzo import server  # noqa: I001
    import rules as rl
    import sessions as ses
    import state as st

    eventos = []
    monkeypatch.setattr(captura, "encolar", eventos.append)
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "ses"))
    os.makedirs(tmp_path / "ses", exist_ok=True)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(server, "log", lambda msg: None)
    st.sessions.clear()
    yield {"eventos": eventos, "server": server, "rl": rl, "ses": ses, "st": st}
    st.sessions.clear()


def test_el_hook_del_pedido_y_el_cierre_de_turno_capturan(enganche):
    ses, rl, eventos = enganche["ses"], enganche["rl"], enganche["eventos"]
    sid = "aaaa0000-0000-4000-8000-000000000001"
    base = {"session_id": sid, "agent": "claude", "cwd": "D:/Apps/demo"}
    ses.apply_event({**base, "hook_event_name": "SessionStart"})
    ses.apply_event({**base, "hook_event_name": "UserPromptSubmit", "prompt": "medí la cola", "prompt_id": "p1"})
    ses.apply_event({**base, "hook_event_name": "Stop", "last_assistant_message": "la cola tarda 2 ms"})
    rl.fire_on_stop(sid)  # lo que dispara on_turn_end en su hilo
    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "vista" and "pedido" in tipos and tipos[-1] == "respuesta"
    pedido = next(e for e in eventos if e["tipo"] == "pedido")
    assert pedido["texto"] == "medí la cola" and pedido["clave"] == f"pedido:{sid}:p1"
    assert pedido["origen"] == {"via": "terminal"}
    assert eventos[-1]["texto"] == "la cola tarda 2 ms" and eventos[-1]["tarjeta"]["cwd"] == "D:/Apps/demo"


def test_el_envio_del_tablero_lleva_su_origen_y_el_hook_que_vuelve_no_duplica(enganche, monkeypatch):
    ses, server, eventos = enganche["ses"], enganche["server"], enganche["eventos"]
    sid = "aaaa0000-0000-4000-8000-000000000002"
    base = {"session_id": sid, "agent": "claude", "cwd": "D:/Apps/demo"}
    ses.apply_event({**base, "hook_event_name": "SessionStart"})
    s = enganche["st"].sessions[sid]
    monkeypatch.setattr(ses, "send_blocked", lambda s: None)
    monkeypatch.setattr(ses, "dialogo_abierto", lambda s: None)
    monkeypatch.setattr(ses, "run_send", lambda s, final, **kw: (200, {"chars": len(final)}))
    code, _ = server.accion_send(s, {"text": "encargo C", "from": "coord-1"})
    assert code == 200
    envio = next(e for e in eventos if e["tipo"] == "envio")
    assert envio["texto"] == "encargo C" and envio["origen"] == {"de": "coord-1", "kind": "send"}
    # el UserPromptSubmit de lo que tecleo el lienzo no se captura otra vez como pedido
    ses.apply_event({**base, "hook_event_name": "UserPromptSubmit", "prompt": "encargo C", "prompt_id": "p9"})
    assert [e["tipo"] for e in eventos].count("pedido") == 0


def test_la_regla_que_dispara_queda_como_regla_en_el_destino(enganche, monkeypatch):
    rl, eventos, st = enganche["rl"], enganche["eventos"], enganche["st"]
    origen = {"session_id": "src", "agent": "claude", "cwd": "D:/a", "state": "termino", "last_reply": "hecho"}
    destino = {"session_id": "dst", "agent": "codex", "cwd": "D:/b", "state": "termino"}
    st.sessions.update({"src": origen, "dst": destino})

    def enviar(dst, texto, adj):
        captura.envio(dst, texto, **captura.origen_actual())
        return 200, {}

    monkeypatch.setattr(rl, "send_to_session", enviar)
    monkeypatch.setattr(rl, "add_link", lambda *a, **kw: None)
    regla = {"id": "r1", "kind": "on_stop", "from": "src", "to": "dst", "text": "informe: {respuesta}", "enabled": True}
    rl.fire_rule(regla)
    ev = next(e for e in eventos if e["tipo"] == "regla")
    assert ev["tarjeta"]["session_id"] == "dst" and ev["origen"]["rule_id"] == "r1" and ev["origen"]["de"] == "src"
    assert "hecho" in ev["texto"]


# --- regresiones del code review del 2026-10-09 --------------------------------------------------


def test_la_captura_que_llega_despues_de_la_entrega_explicita_no_duplica(tmp_path):
    cwd = tmp_path / "app"
    pid = captura.proyecto_de(_tarjeta("s1", cwd))
    r = k.abrir_ronda(pid, "r", autor="coordinadora:c")
    e = k.crear_encargo(pid, r["id"], "A", "x", autor="coordinadora:c")
    k.encargo_enviado(pid, e["id"], _tarjeta("s1", cwd))
    inf = k.entregar(pid, e["id"], BLOQUE.strip(), revision=1, autor="coordinadora:c")
    c = captura.procesar(_ev("respuesta", _tarjeta("s1", cwd), BLOQUE, "r1"))
    assert c["informe"] == inf["id"]
    assert k.nodos(pid, tipo="informe")["total"] == 1 and k.nodos(pid, tipo="hallazgo")["total"] == 1


def test_dos_escritores_con_la_misma_clave_no_chocan(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    k.registrar_proyecto("p")
    for i in range(10):
        with ThreadPoolExecutor(max_workers=2) as pool:
            tarjeta = {"session_id": f"s{i}", "agent": "claude"}
            res = list(pool.map(lambda t: k.registrar_sesion("p", t), [tarjeta, dict(tarjeta)]))
        assert res[0]["id"] == res[1]["id"]
    assert k.nodos("p", tipo="sesion")["total"] == 10


def test_la_respuesta_con_secreto_tapado_no_es_informe(tmp_path):
    t = _tarjeta("s1", tmp_path / "app")
    c = captura.procesar({**_ev("respuesta", t, BLOQUE, "r1"), "redactado": True})
    assert "informe" not in c and k.nodos("app", tipo="informe")["total"] == 0


@pytest.mark.parametrize(
    "secreto",
    [
        "AZURE_CLIENT_SECRET=abcdef123456",
        "DB_PASSWORD=hunter2hunter",
        "GITHUB_TOKEN=abcdef123456",
        '{"password": "hunter2hunter"}',
        "token: abcdef123456",
        "https://x.blob.core.windows.net/c?sv=2020&sig=abcdef123456",
    ],
)
def test_tapar_cubre_las_formas_comunes(secreto):
    texto, tapado = captura.tapar(secreto)
    assert tapado and captura.TAPADO in texto
    assert "hunter2hunter" not in texto and "abcdef123456" not in texto


def test_tapar_no_toca_texto_comun():
    for sano in ("max_tokens: 4096", "prompt_tokens=12", "el secreto es la constancia", "password corta=abc"):
        assert captura.tapar(sano) == (sano, False)
