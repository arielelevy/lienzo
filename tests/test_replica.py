"""Replica de la memoria entre PCs (anexo C de v5): dos PCs simuladas en el mismo proceso, cada una con
su LIENZO_HOME y su pc_id, y el canal firmado reemplazado por una llamada directa a `replica.atender`
con ida y vuelta por JSON (lo que haria HTTP)."""

import contextlib
import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import conocimiento as k
import replica
import veredictos as v

REMOTE = "github.com/ariel/teorema"
C = "coordinadora:c"


class Red:
    """Las PCs y el reenvio entre ellas. `cortar` hace fallar el pedido numero N."""

    def __init__(self, tmp_path, monkeypatch):
        self.homes = {pc: str(tmp_path / pc) for pc in ("pcA", "pcB")}
        self.actual = None
        self.pedidos = 0
        self.cortar = None
        self.viejo = set()
        self.mp = monkeypatch
        monkeypatch.setattr(k.identity, "pc_id", lambda: self.actual)

    @contextlib.contextmanager
    def en(self, pc):
        antes = (self.actual, os.environ.get("LIENZO_HOME"))
        self.actual = pc
        os.environ["LIENZO_HOME"] = self.homes[pc]
        k._sesion_proyecto.clear()
        k._sesion_sin_proyecto.clear()
        try:
            yield
        finally:
            self.actual = antes[0]
            os.environ["LIENZO_HOME"] = antes[1]
            k._sesion_proyecto.clear()
            k._sesion_sin_proyecto.clear()

    def forward(self, pc, metodo, ruta, cuerpo):
        assert metodo == "POST" and ruta == "/conocimiento"
        self.pedidos += 1
        if self.cortar is not None and self.pedidos == self.cortar:
            raise OSError("corte de red a mitad")
        if pc in self.viejo:
            return 404, {"error": "ruta desconocida"}
        with self.en(pc):
            code, res = replica.atender(json.loads(json.dumps(cuerpo)))
        return code, json.loads(json.dumps(res))

    def sync(self, desde, hacia):
        """`desde` trae lo de `hacia`."""
        with self.en(desde):
            return replica.sincronizar(hacia, self.forward)


@pytest.fixture
def red(tmp_path, monkeypatch):
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    monkeypatch.setattr(replica.state, "log", lambda msg: None)
    replica._sin_soporte.clear()
    return Red(tmp_path, monkeypatch)


def _poblar_a(red):
    with red.en("pcA"):
        k.registrar_proyecto("teorema", "Teorema", [REMOTE], [{"pc": "pcA", "cwd": "D:/Apps/Teorema"}])
        r = k.abrir_ronda("teorema", "ronda 1", autor=C)
        e = k.crear_encargo("teorema", r["id"], "A", "# Encargo A\nmedir el halving entero", autor=C)
        k.encargo_enviado("teorema", e["id"], {"session_id": "s1", "agent": "codex", "pc": "pcA"})
        cuerpo = (
            "Informe\n```conocimiento\n"
            '{"version": 1, "nodos": [{"id": "h1", "tipo": "hallazgo", "texto": "la cota LP no controla S",'
            ' "datos": {"donde": "dominio:halving", "gravedad": "alta"}}, {"id": "t1", "tipo": "tema",'
            ' "texto": "halving", "datos": {}}], "vinculos": [{"de": "h1", "relacion": "sobre", "a": "t1"}]}\n```'
        )
        inf = k.entregar("teorema", e["id"], cuerpo, revision=1, autor=C)
        k.capturar("teorema", "pedido", "seguí con el halving", {"session_id": "s1", "agent": "codex", "pc": "pcA"})
        return {"ronda": r, "encargo": e, "informe": inf, "h1": inf["datos"]["conocimiento"]["ids"]["h1"]}


def test_b_trae_todo_lo_de_a_con_los_mismos_ids_y_cuerpos_verificados(red):
    a = _poblar_a(red)
    res = red.sync("pcB", "pcA")
    p = res["proyectos"][0]
    assert p["proyecto"] == "teorema" and p["cambios"] > 10 and p["capturas"] == 1 and p["cuerpos"] == 2
    with red.en("pcB"):
        assert k.proyecto("teorema")["remotes"] == [REMOTE] and k.proyecto("teorema")["carpetas"] == []
        h = k.nodo("teorema", a["h1"])
        assert h["estado"] == "propuesto" and h["texto"] == "la cota LP no controla S"
        assert {x["relacion"] for x in h["vinculos"]["salen"]} >= {"sobre", "declarado_en", "encontrado_por"}
        assert k.nodo("teorema", a["encargo"]["id"])["estado"] == "entregado"
        assert all(c["pc"] == "pcA" for c in k.cambios("teorema", limite=500))
        inf = k.nodo("teorema", a["informe"]["id"])
        with open(os.path.join(k._carpeta("teorema"), *inf["datos"]["ruta"].split("/")), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == inf["datos"]["hash"]
        assert [x["nodo"] for x in k.buscar_prosa("teorema", "halving") if x.get("nodo")]  # la prosa viajo
        assert k.capturas("teorema")["capturas"][0]["texto"] == "seguí con el halving"
        assert v.preguntar("teorema", ["halving"])["total"] >= 2
    # otra vuelta no aplica nada: (pc, seq_origen) unico y cursores
    again = red.sync("pcB", "pcA")["proyectos"][0]
    assert (again["cambios"], again["capturas"], again["cuerpos"]) == (0, 0, 0)


def test_un_corte_a_mitad_no_aplica_el_lote_ni_mueve_el_cursor(red, monkeypatch):
    _poblar_a(red)
    monkeypatch.setattr(replica, "LOTE", 3)
    red.cortar = 3  # proyectos, primer lote, y el segundo lote se corta
    res = red.sync("pcB", "pcA")
    assert "corte" in res["proyectos"][0]["error"]
    with red.en("pcB"):
        estado = replica.estado("teorema")
        assert [c["ultimo"] for c in estado["cursores"] if c["clase"] == "cambio"] == [3]
        a_medias = len(k.cambios("teorema", limite=500))
    assert a_medias == 3
    red.cortar = None
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        cambios_b = k.cambios("teorema", limite=500)
    with red.en("pcA"):
        cambios_a = k.cambios("teorema", limite=500)
    assert [c["seq_origen"] for c in cambios_b] == [c["seq_origen"] for c in cambios_a]


def test_lo_que_hace_b_vuelve_a_a_y_un_choque_queda_para_la_coordinadora(red):
    a = _poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcA"):
        k.cambiar_estado("teorema", a["h1"], "confirmado", por=C, motivo="revisado en A")
    with red.en("pcB"):
        k.cambiar_estado("teorema", a["h1"], "rechazado", por=C, motivo="refutado en B")  # despues: gana
        tema_b = k.crear_nodo("teorema", "tema", "cotas", autor=C)
        k.vincular("teorema", a["h1"], "sobre", tema_b["id"], autor=C)
    red.sync("pcA", "pcB")
    red.sync("pcB", "pcA")
    for pc in ("pcA", "pcB"):
        with red.en(pc):
            h = k.nodo("teorema", a["h1"])
            assert h["estado"] == "rechazado", pc
            assert tema_b["id"] in {x["a"] for x in h["vinculos"]["salen"]}
            motivos = {c["motivo"] for c in h["cambios"] if c["accion"] == "estado"}
            assert {"revisado en A", "refutado en B"} <= motivos  # las dos revisiones quedan
    with red.en("pcA"):
        conflictos = replica.estado("teorema")["conflictos"]
    assert len(conflictos) == 1 and conflictos[0]["pc"] == "pcB" and conflictos[0]["nodo"] == a["h1"]


def test_lo_mismo_registrado_en_las_dos_se_sugiere_como_duplicado_sin_fusionar(red):
    _poblar_a(red)
    red.sync("pcB", "pcA")
    for pc in ("pcA", "pcB"):
        with red.en(pc):
            k.recibir_evidencia("teorema", "salida.log", b"12 passed", clase="prueba", autor=C)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        dup = replica.estado("teorema")["duplicados"]
        assert len(dup) == 1 and dup[0]["clave"].startswith("evidencia:")
        assert k.nodos("teorema", tipo="evidencia")["total"] == 2


def test_la_sesion_registrada_en_las_dos_es_un_nodo(red):
    _poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        k.registrar_sesion("teorema", {"session_id": "s1", "agent": "codex", "model": "gpt-5", "pc": "pcA"})
    red.sync("pcA", "pcB")
    with red.en("pcA"):
        sesiones = k.nodos("teorema", tipo="sesion")["nodos"]
    assert len(sesiones) == 1 and sesiones[0]["datos"]["modelo"] == "gpt-5"


def test_un_vinculo_cuyo_nodo_no_llego_espera_y_se_aplica_despues(red):
    _poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        tema = {
            "id": "e" * 32,
            "tipo": "tema",
            "texto": "de una tercera PC",
            "datos": {},
            "estado": None,
            "estado_fecha": None,
            "estado_por": None,
            "autor": "c",
            "origen": {},
            "ronda": None,
            "fecha": k.ahora(),
            "clave_ingesta": None,
        }
        h1 = k.nodos("teorema", tipo="hallazgo")["nodos"][0]["id"]
        vinc = {
            "pc": "pcC",
            "seq_origen": 2,
            "accion": "vinculo",
            "de": h1,
            "relacion": "sobre",
            "a": tema["id"],
            "fecha": k.ahora(),
            "autor": "c",
            "motivo": "",
            "origen": {},
            "nuevo": {"de": h1, "relacion": "sobre", "a": tema["id"], "activo": 1, "autor": "c", "origen": {}},
        }
        nodo = {
            "pc": "pcC",
            "seq_origen": 1,
            "accion": "nodo",
            "nodo_id": tema["id"],
            "fecha": k.ahora(),
            "autor": "c",
            "motivo": "",
            "origen": {},
            "nuevo": tema,
        }
        with k._abrir("teorema") as con:
            assert replica.aplicar(con, "teorema", vinc) is False
        assert len(replica.estado("teorema")["pendientes"]) == 1
        with k._abrir("teorema") as con:
            assert replica.aplicar(con, "teorema", nodo) is True
        assert replica._reintentar_pendientes("teorema") == 0
        assert tema["id"] in {x["a"] for x in k.nodo("teorema", h1)["vinculos"]["salen"]}


def test_sin_remote_no_se_replica_y_un_par_viejo_se_saltea(red):
    with red.en("pcA"):
        k.registrar_proyecto("suelto")
    res = red.sync("pcB", "pcA")
    assert res["sin_remote"] == ["suelto"] and res["proyectos"] == []

    class Espejo:
        def peers_status(self):
            return [{"pc_id": "pcA", "alive": True, "name": "A"}]

        forward = staticmethod(red.forward)

    red.viejo.add("pcA")
    with red.en("pcB"):
        assert replica.sincronizar_todos(Espejo()) == []
        assert "pcA" in replica._sin_soporte


def test_atender_no_escribe_y_rechaza_lo_que_no_conoce(red):
    _poblar_a(red)
    with red.en("pcA"):
        antes = len(k.cambios("teorema", limite=500))
        assert replica.atender({"op": "cambios", "proyecto": "nadie"})[0] == 404
        assert replica.atender({"op": "otra", "proyecto": "teorema"})[0] == 400
        assert replica.atender({"op": "cuerpo", "proyecto": "teorema", "ruta": "../../peer.json"})[0] == 404
        assert len(k.cambios("teorema", limite=500)) == antes


def test_encargo_enviado_a_una_tarjeta_de_otra_pc_vale_si_ya_hay_replica(red, monkeypatch):
    import conocimiento_api as api

    a = _poblar_a(red)
    remota = {"session_id": "sB", "agent": "claude", "pc": "pcB", "cwd": "D:/Apps/Teorema"}
    monkeypatch.setattr(api.ses, "sessions", {})
    monkeypatch.setattr(api.ses, "find_session", lambda sid: remota if sid == "sB" else None)
    with red.en("pcA"):
        e2 = k.crear_encargo("teorema", a["ronda"]["id"], "B", "# Encargo B", autor=C)
        ruta = ["teorema", "encargos", e2["id"], "enviado"]
        code, res = api.dispatch("POST", ruta, {"session_id": "sB"}, {})
        assert code == 409 and "replic" in res["error"]
    red.sync("pcA", "pcB")  # B todavia no tiene el proyecto: A no queda replicando con B en el
    with red.en("pcA"):
        assert api.dispatch("POST", ruta, {"session_id": "sB"}, {})[0] == 409
    red.sync("pcB", "pcA")  # B trae el proyecto de A
    red.sync("pcA", "pcB")  # y ahora A replica con B en este proyecto
    with red.en("pcA"):
        code, res = api.dispatch("POST", ruta, {"session_id": "sB"}, {})
        assert code == 200 and res["estado"] == "enviado"
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        # el nodo sesion y el vinculo llegaron a la PC de la sesion: sus observaciones se registran aca
        assert k.incidente_operativo("sB", "permiso denegado", herramienta="Bash", clave="i") is not None


# --- regresiones del code review del 2026-10-09 --------------------------------------------------


def test_un_nodo_con_ruta_fuera_del_proyecto_no_escribe_afuera(red, tmp_path):
    _poblar_a(red)
    with red.en("pcA"):
        k.crear_nodo(
            "teorema",
            "evidencia",
            "mala",
            {"clase": "x", "referencia": "../../afuera.txt", "recibida": True},
            autor="c",
        )
    red.sync("pcB", "pcA")
    assert not (tmp_path / "pcB" / "afuera.txt").exists() and not (tmp_path / "afuera.txt").exists()
    with red.en("pcA"):
        assert replica.atender({"op": "cuerpo", "proyecto": "teorema", "ruta": "conocimiento.sqlite"})[0] == 404


def test_un_par_viejo_se_reintenta_despues_de_un_rato(red, monkeypatch):
    _poblar_a(red)

    class Espejo:
        def peers_status(self):
            return [{"pc_id": "pcA", "alive": True, "name": "A"}]

        forward = staticmethod(red.forward)

    red.viejo.add("pcA")
    with red.en("pcB"):
        assert replica.sincronizar_todos(Espejo()) == []
        red.viejo.clear()
        assert replica.sincronizar_todos(Espejo()) == []  # todavia dentro de los 15 min
        monkeypatch.setattr(replica, "SIN_SOPORTE_S", 0)
        res = replica.sincronizar_todos(Espejo())
    assert res and res[0]["proyectos"][0]["cambios"] > 0 and "pcA" not in replica._sin_soporte


def test_un_proyecto_roto_no_frena_a_los_demas(red, monkeypatch):
    _poblar_a(red)
    with red.en("pcA"):
        k.registrar_proyecto("otro", remotes=["github.com/ariel/otro"])
        k.crear_nodo("otro", "tema", "x", autor="c")
    original = replica._sincronizar_proyecto

    def rompe(pc, forward, remoto, pid):
        if remoto == "teorema":
            raise KeyError("campo")
        return original(pc, forward, remoto, pid)

    monkeypatch.setattr(replica, "_sincronizar_proyecto", rompe)
    res = red.sync("pcB", "pcA")
    por = {p["remoto"]: p for p in res["proyectos"]}
    assert "KeyError" in por["teorema"]["error"] and por["otro"]["cambios"] > 0


def test_los_cambios_desde_el_cierre_de_una_ronda_cerrada_en_otra_pc(red):
    a = _poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        for i in range(5):
            k.crear_nodo("teorema", "tema", f"de B antes {i}", autor="c")  # seq altos en B
    with red.en("pcA"):
        v.cerrar_ronda("teorema", a["ronda"]["id"], por=C)
        k.crear_nodo("teorema", "tema", "despues del cierre", autor="c")
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        textos = [c["texto"] for c in v._cambios_desde_cierre("teorema")["cambios"]]
    assert "despues del cierre" in textos and not any(t and t.startswith("de B antes") for t in textos)


def test_una_captura_mal_formada_no_avanza_el_cursor(red, monkeypatch):
    _poblar_a(red)
    original = replica._capturas_propias

    def rota(pid, desde, limite):
        res = original(pid, desde, limite)
        for c in res["capturas"]:
            c["texto"] = None
        return res

    monkeypatch.setattr(replica, "_capturas_propias", rota)
    res = red.sync("pcB", "pcA")
    assert "IntegrityError" in res["proyectos"][0]["error"]
    with red.en("pcB"):
        cur = [c for c in replica.estado("teorema")["cursores"] if c["clase"] == "captura"]
    assert cur == [] or cur[0]["ultimo"] == 0


def _reloj(monkeypatch, red, adelanto_pc, minutos):
    import datetime as dt

    real = k.ahora

    def ahora():
        if red.actual != adelanto_pc:
            return real()
        d = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutos)
        return d.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    monkeypatch.setattr(k, "ahora", ahora)


def test_con_el_reloj_de_b_adelantado_las_dos_pcs_terminan_iguales(red, monkeypatch):
    a = _poblar_a(red)
    red.sync("pcB", "pcA")
    _reloj(monkeypatch, red, "pcB", 10)
    with red.en("pcB"):
        k.cambiar_estado("teorema", a["h1"], "confirmado", por=C, motivo="b primero")
    red.sync("pcA", "pcB")
    with red.en("pcA"):  # A ve lo de B y edita despues, en tiempo real (con su reloj atrasado)
        k.cambiar_estado("teorema", a["h1"], "rechazado", por=C, motivo="a despues")
    red.sync("pcB", "pcA")
    estados = {}
    for pc in ("pcA", "pcB"):
        with red.en(pc):
            estados[pc] = k.nodo("teorema", a["h1"])["estado"]
            assert replica.estado("teorema")["conflictos"] == [], pc
    assert estados == {"pcA": "rechazado", "pcB": "rechazado"}


def test_tres_pcs_en_orden_no_inventan_choques(red, tmp_path):
    red.homes["pcC"] = str(tmp_path / "pcC")
    a = _poblar_a(red)
    red.sync("pcB", "pcA")
    red.sync("pcC", "pcA")
    with red.en("pcA"):
        k.cambiar_estado("teorema", a["h1"], "confirmado", por=C)
    red.sync("pcB", "pcA")
    with red.en("pcB"):  # B vio lo de A y edita despues
        k.cambiar_estado("teorema", a["h1"], "rechazado", por=C)
    red.sync("pcC", "pcB")  # C trae primero lo de B
    red.sync("pcC", "pcA")  # y despues lo de A
    with red.en("pcC"):
        assert k.nodo("teorema", a["h1"])["estado"] == "rechazado"
        assert replica.estado("teorema")["conflictos"] == []


def test_un_id_largo_con_sufijo_no_pasa_de_64(red):
    largo = "p" * 64
    with red.en("pcB"):
        k.registrar_proyecto(largo, remotes=["github.com/otro/otro"])
        pid = replica._proyecto_local({"id": largo, "remotes": ["github.com/x/largo"]})
    assert pid == "p" * 56 and len(pid) <= 64
