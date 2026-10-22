"""Sincronizacion por marcas (encargo B, punto 2): un pedido `marcas` dice, por proyecto, hasta donde llegan
los cambios y las capturas que nacieron en el par; el que pide solo trae lo que pasa su cursor. Un par de
la version anterior contesta 400 a `marcas` y se vuelve al ciclo de antes (proyectos + cambios + capturas
por proyecto). Las dos PCs simuladas de test_replica, con ida y vuelta por JSON."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_replica as tr
from test_replica import k, replica


class RedConOps(tr.Red):
    """La red de test_replica, contando las ops pedidas. Un par en `anterior` atiende como la version
    previa: no conoce `marcas` y, como su `atender` pide el proyecto antes de mirar la op, contesta 400."""

    def __init__(self, *a):
        super().__init__(*a)
        self.ops = []
        self.anterior = set()

    def forward(self, pc, metodo, ruta, cuerpo):
        self.ops.append(cuerpo["op"])
        if pc in self.anterior and cuerpo["op"] == "marcas":
            self.pedidos += 1
            return 400, {"error": "proyecto debe ser un texto no vacio"}
        return super().forward(pc, metodo, ruta, cuerpo)


@pytest.fixture
def red(tmp_path, monkeypatch):
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    monkeypatch.setattr(replica.state, "log", lambda msg: None)
    replica._sin_soporte.clear()
    replica._sin_marcas.clear()
    replica._cuerpos_completos.clear()
    return RedConOps(tmp_path, monkeypatch)


def test_marcas_dice_hasta_donde_llega_cada_proyecto(red):
    tr._poblar_a(red)
    with red.en("pcA"):
        code, res = replica.atender({"op": "marcas"})
        with k._abrir("teorema") as con:
            ultimo = con.execute("SELECT MAX(seq_origen) FROM cambio WHERE pc = 'pcA'").fetchone()[0]
            cap = con.execute("SELECT MAX(rowid) FROM captura WHERE pc = 'pcA'").fetchone()[0]
    assert code == 200 and res["pc"] == "pcA" and res["esquema"] == k.VERSION_ESQUEMA
    (p,) = res["proyectos"]
    assert p["id"] == "teorema" and p["remotes"] == [tr.REMOTE]
    assert p["marcas"] == {"cambio": ultimo, "captura": cap}


def test_un_par_al_dia_no_pide_cambios_ni_capturas(red):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    red.ops.clear()
    res = red.sync("pcB", "pcA")
    assert red.ops == ["marcas"]
    p = res["proyectos"][0]
    assert (p["cambios"], p["capturas"], p["cuerpos"]) == (0, 0, 0)


def test_lo_nuevo_alla_se_trae_y_solo_lo_que_cambio(red):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcA"):
        k.crear_nodo("teorema", "tema", "nuevo en A", autor=tr.C)
    red.ops.clear()
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert red.ops == ["marcas", "cambios"]  # las capturas siguen al dia
    assert p["cambios"] == 1
    with red.en("pcB"):
        assert any(n["texto"] == "nuevo en A" for n in k.nodos("teorema")["nodos"])
    with red.en("pcA"):
        k.capturar("teorema", "pedido", "otra", {"session_id": "s1", "agent": "codex", "pc": "pcA"})
    red.ops.clear()
    assert red.sync("pcB", "pcA")["proyectos"][0]["capturas"] == 1
    assert red.ops == ["marcas", "capturas"]


def test_un_par_anterior_cae_al_ciclo_de_antes_y_no_se_le_vuelve_a_preguntar(red):
    tr._poblar_a(red)
    red.anterior.add("pcA")
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert red.ops[:2] == ["marcas", "proyectos"] and p["cambios"] > 10 and p["capturas"] == 1
    red.ops.clear()
    red.sync("pcB", "pcA")
    assert red.ops == ["proyectos", "cambios", "capturas"]  # sin volver a probar marcas


def test_un_par_anterior_se_vuelve_a_probar_despues_de_un_rato(red, monkeypatch):
    tr._poblar_a(red)
    red.anterior.add("pcA")
    red.sync("pcB", "pcA")
    red.anterior.clear()  # la otra PC se actualizo
    reloj = [replica.time.monotonic() + replica.SIN_SOPORTE_S + 1]
    monkeypatch.setattr(replica.time, "monotonic", lambda: reloj[0])
    red.ops.clear()
    red.sync("pcB", "pcA")
    assert red.ops == ["marcas"]


def test_un_par_anterior_que_me_pide_a_mi_sigue_andando(red):
    """El que pide con la version anterior usa proyectos, cambios y capturas: siguen iguales."""
    tr._poblar_a(red)
    with red.en("pcA"):
        code, res = replica.atender({"op": "proyectos"})
        assert code == 200 and res["proyectos"][0]["id"] == "teorema" and "marcas" not in res["proyectos"][0]
        code, res = replica.atender({"op": "cambios", "proyecto": "teorema", "desde": 0})
        assert code == 200 and res["cambios"]


def test_un_404_a_marcas_sigue_siendo_un_par_sin_replica(red):
    tr._poblar_a(red)
    red.viejo.add("pcA")
    with pytest.raises(replica.SinSoporte):
        red.sync("pcB", "pcA")


def test_una_pc_sin_proyectos_contesta_marcas_sin_crear_la_base(red):
    with red.en("pcB"):
        assert replica.atender({"op": "marcas"}) == (200, {"pc": "pcB", "esquema": k.VERSION_ESQUEMA, "proyectos": []})
        assert not os.path.exists(k.db_path())


def test_un_proyecto_quieto_no_abre_la_base_y_su_cursor_igual_dice_cuando_se_vio(red, monkeypatch):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    aperturas = []
    original = k._abrir

    def contar(pid):
        aperturas.append((red.actual, pid))
        return original(pid)

    monkeypatch.setattr(k, "_abrir", contar)
    monkeypatch.setattr(k, "ahora", lambda: "2099-01-01T00:00:00.000Z")
    red.sync("pcB", "pcA")
    assert [a for a in aperturas if a[0] == "pcB"] == []  # el que pide no abrio la base por el proyecto
    with red.en("pcB"):
        fechas = {c["clase"]: c["fecha"] for c in replica.estado("teorema")["cursores"]}
    assert fechas == {"cambio": "2099-01-01T00:00:00.000Z", "captura": "2099-01-01T00:00:00.000Z"}


def test_un_proyecto_al_dia_igual_reintenta_lo_que_esperaba(red):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"), k._abrir("teorema") as con:
        con.execute(
            "INSERT INTO replica_pendiente (proyecto, pc, seq_origen, cambio, error, fecha) VALUES (?,?,?,?,?,?)",
            ("teorema", "pcC", 1, '{"pc": "pcC", "seq_origen": 1, "accion": "nota"}', "falta un nodo", k.ahora()),
        )
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert p["pendientes"] == 0  # se reintento (y una accion sin nodo queda solo en el historial)


# --- code review del delta de marcas (2026-10-21) ---


def test_un_cuerpo_que_falta_se_vuelve_a_buscar_pasado_el_plazo_aunque_el_proyecto_este_quieto(red, monkeypatch):
    a = tr._poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        inf = k.nodo("teorema", a["informe"]["id"])
        os.remove(os.path.join(k._carpeta("teorema"), *inf["datos"]["ruta"].split("/")))
    reloj = [replica.time.monotonic() + replica.REINTENTO_CUERPO_S + 1]
    monkeypatch.setattr(replica.time, "monotonic", lambda: reloj[0])
    assert red.sync("pcB", "pcA")["proyectos"][0]["cuerpos"] == 1


def test_un_cursor_que_apunta_a_otro_proyecto_no_cuenta_como_quieto(red):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"), k._abrir("teorema") as con:
        con.execute("UPDATE replica_cursor SET proyecto = 'otro'")
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        assert {c["proyecto"] for c in replica.estado("teorema")["cursores"]} == {"teorema"}


def test_un_proyecto_sin_carpeta_sigue_dando_error_aunque_este_quieto(red):
    import shutil

    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    with red.en("pcB"):
        shutil.rmtree(k._carpeta("teorema"))
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert "error" in p


@pytest.mark.parametrize("code,error", [(400, "cuerpo ilegible"), (500, "database is locked")])
def test_marcas_que_falla_por_otra_cosa_hace_la_vuelta_con_proyectos_sin_apagarlas(red, monkeypatch, code, error):
    """Un error de marcas que no es el de la version anterior (la base del par ocupada, un cuerpo ilegible)
    no frena la replica: esa vuelta se hace como antes, y la siguiente vuelve a probar marcas."""
    tr._poblar_a(red)
    original = red.forward

    def forward(pc, metodo, ruta, cuerpo):
        if cuerpo["op"] == "marcas":
            red.ops.append("marcas")
            return code, {"error": error}
        return original(pc, metodo, ruta, cuerpo)

    monkeypatch.setattr(red, "forward", forward)
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert red.ops[:2] == ["marcas", "proyectos"] and p["cambios"] > 10
    assert "pcA" not in replica._sin_marcas


def test_marcas_no_crea_la_base_aunque_el_indice_tenga_proyectos(red):
    with red.en("pcB"):
        idx = k._leer_indice()
        idx["proyectos"]["solo-indice"] = {"nombre": "x", "remotes": ["github.com/x/y"], "carpetas": [], "creado": "x"}
        k._guardar_indice(idx)
        code, res = replica.atender({"op": "marcas"})
        assert code == 200 and res["proyectos"][0]["marcas"] == {"cambio": 0, "captura": 0}
        assert not os.path.exists(k.db_path())


def test_cambios_de_otro_par_en_el_proyecto_vuelven_a_revisar_los_cuerpos_con_todos(red, tmp_path):
    """Un nodo que llega de una tercera PC puede citar un cuerpo que tiene otro par: el proyecto deja de
    estar quieto con todos los pares hasta que se revisen sus cuerpos."""
    tr._poblar_a(red)
    red.sync("pcB", "pcA")
    assert ("pcA", "teorema") in replica._cuerpos_completos
    red.homes["pcC"] = str(tmp_path / "pcC")
    with red.en("pcC"):
        k.registrar_proyecto("teorema", "Teorema", [tr.REMOTE])
        k.crear_nodo("teorema", "tema", "de C", autor=tr.C)
    red.sync("pcB", "pcC")
    assert ("pcA", "teorema") not in replica._cuerpos_completos


def test_si_no_se_puede_leer_el_estado_local_la_vuelta_sigue_proyecto_por_proyecto(red, monkeypatch):
    tr._poblar_a(red)
    red.sync("pcB", "pcA")

    def ocupada(pc):
        raise replica.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(replica, "_estado_local", ocupada)
    with red.en("pcA"):
        k.crear_nodo("teorema", "tema", "nuevo", autor=tr.C)
    p = red.sync("pcB", "pcA")["proyectos"][0]
    assert p.get("error") is None and p["cambios"] == 1
