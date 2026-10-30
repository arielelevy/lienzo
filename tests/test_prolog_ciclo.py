"""AA lotes 3–6: reevaluación, pruebas de derivación, reuso y graduación."""

import datetime as dt
import os

import conocimiento as k
import creencias as c
import prolog_learning as _motor
import pytest

# lo que necesita el motor real se saltea en una PC que no tiene SWI-Prolog (ar-it33940, 2026-10-25)
MOTOR_REAL = pytest.mark.skipif(
    not _motor.motor_disponible(), reason="Falta SWI-Prolog que responda o el repo motor-logico"
)


@pytest.fixture(autouse=True)
def motor_durante_pausa(monkeypatch):
    if os.environ.get("AA_MOTOR_SIMULADO") == "1":
        import aa_motor_simulado
        import prolog_programa
        import prolog_servicio

        monkeypatch.setattr(prolog_servicio, "consultar", aa_motor_simulado.consultar)
        monkeypatch.setattr(prolog_programa, "archivos", lambda pid: [])


def ciclo():
    import prolog_ciclo

    return prolog_ciclo


def belief(pid="aa-ciclo", *, delegada=False, clausula=None):
    k.registrar_proyecto(pid)
    ev = k.crear_nodo(
        pid, "evidencia", "evidencia original", {"clase": "ia_delegada"} if delegada else {}, autor="persona:Ariel"
    )
    data = {
        "dimension": "memoria",
        "texto": "Medir recursos",
        "accion": "Medir RAM",
        "contexto": {},
        "fuentes": [ev["id"]],
    }
    if clausula:
        data["regla_logica"] = {"version": 1, "vocabulario": 1, "clausula": clausula}
    n = c.proponer(pid, data, autor="server:AA")
    c.resolver(
        pid,
        n["id"],
        {
            "por": "persona:Ariel",
            "motivo": "fixture aceptado",
            "resultado": "validada",
            "evidencia": ev["id"],
            "vigente_hasta": (dt.datetime.now(dt.UTC) + dt.timedelta(days=10)).isoformat(),
        },
    )
    return n["id"], ev["id"]


@MOTOR_REAL
def test_primera_contradiccion_de_delegada_cuestiona_y_excluye_del_checklist():
    bid, _ = belief(delegada=True)
    incident = k.crear_nodo(
        "aa-ciclo", "incidente", "La regla falló después", {"contradice_creencias": [bid]}, autor="persona:Ariel"
    )
    out = ciclo().vuelta("aa-ciclo")
    assert out["cuestionadas"] == [bid]
    node = c.listar("aa-ciclo")[0]
    assert node["estado"] == "vigente"
    reev = node["datos"]["reevaluacion"]
    assert reev["estado"] == "cuestionada" and reev["requiere_veredicto"] is True
    assert incident["id"] in reev["evidencias"]
    assert reev["prueba"]
    assert c.checklist("aa-ciclo", {})["items"] == []


@MOTOR_REAL
def test_apoyo_retirado_y_usos_no_aplico_se_revaluan():
    bid, ev = belief()
    k.retirar_vinculo("aa-ciclo", bid, "apoya", ev, por="persona:Ariel", motivo="evidencia retirada")
    assert ciclo().vuelta("aa-ciclo")["cuestionadas"] == [bid]


@MOTOR_REAL
def test_fuente_rechazada_cuestiona_la_creencia_que_motiva():
    bid, _ = belief()
    source = k.crear_nodo("aa-ciclo", "hallazgo", "medición que motivó la regla", {}, autor="persona:Ariel")
    k.vincular("aa-ciclo", bid, "motivada_por", source["id"], autor="persona:Ariel", motivo="origen")
    k.cambiar_estado("aa-ciclo", source["id"], "rechazado", por="persona:Ariel", motivo="medición incorrecta")
    out = ciclo().vuelta("aa-ciclo")
    assert bid in out["cuestionadas"]


@MOTOR_REAL
def test_dos_usos_no_aplico_cuestionan_y_uno_no():
    bid, _ = belief()
    c.registrar_uso("aa-ciclo", bid, {"resultado": "no_aplico", "por": "persona:Ariel"})
    assert bid not in ciclo().vuelta("aa-ciclo")["cuestionadas"]
    c.registrar_uso("aa-ciclo", bid, {"resultado": "no_aplico", "por": "persona:Ariel"})
    assert bid in ciclo().vuelta("aa-ciclo")["cuestionadas"]


def test_cancelacion_no_escribe_reevaluacion():
    belief()
    before = c.listar("aa-ciclo")
    with pytest.raises(ciclo().Cancelada):
        ciclo().vuelta("aa-ciclo", cancelar=lambda: True)
    assert c.listar("aa-ciclo") == before


@MOTOR_REAL
def test_nuevo_veredicto_invalida_objecion_anterior():
    bid, ev = belief(delegada=True)
    k.crear_nodo("aa-ciclo", "incidente", "falló", {"contradice_creencias": [bid]}, autor="persona:Ariel")
    ciclo().vuelta("aa-ciclo")
    c.resolver(
        "aa-ciclo",
        bid,
        {
            "por": "persona:Ariel",
            "motivo": "revisada después",
            "resultado": "validada",
            "evidencia": ev,
            "vigente_hasta": (dt.datetime.now(dt.UTC) + dt.timedelta(days=10)).isoformat(),
        },
    )
    assert ciclo().estado_actual(c.listar("aa-ciclo")[0]) is None


def test_refutada_no_se_presenta_como_datos_insuficientes():
    bid, ev = belief(delegada=True)
    c.resolver(
        "aa-ciclo",
        bid,
        {"por": "persona:Ariel", "motivo": "rechazo posterior", "resultado": "refutada", "evidencia": ev},
    )
    assert c.checklist("aa-ciclo", {})["no_aplican"][0]["estado"] == "refutada"


def test_cambiar_la_regla_exige_veredicto_de_la_revision_nueva():
    bid, _ = belief(clausula="recomendar(C, memoria, medir) :- chrome_en_uso(C).")
    k.actualizar_datos(
        "aa-ciclo",
        bid,
        {
            "regla_logica": {
                "version": 1,
                "vocabulario": 1,
                "clausula": "impedir(C, investigador, ram) :- chrome_en_uso(C).",
            }
        },
        por="persona:Ariel",
    )
    assert c.checklist("aa-ciclo", {})["items"] == []
    assert c.checklist("aa-ciclo", {})["no_aplican"][0]["estado"] == "sin_veredicto"


@MOTOR_REAL
def test_deriva_con_reglas_y_hechos_reales_y_guarda_cadena_sin_promover():
    b1, _ = belief(clausula="escenario_ram(C, chrome, 4, 1.1) :- chrome_en_uso(C), frentes_activos(C, 4).")
    b2, _ = belief(clausula="recurso_necesita_gb(investigador, 3) :- proyecto(C, lienzo).")
    facts = [
        {"pred": "chrome_en_uso", "args": ["pc"]},
        {"pred": "frentes_activos", "args": ["pc", 4]},
        {"pred": "proyecto", "args": ["pc", "lienzo"]},
    ]
    out = ciclo().vuelta("aa-ciclo", hechos=facts)
    assert len(out["derivadas"]) == 1
    derived = next(n for n in c.listar("aa-ciclo") if n["id"] == out["derivadas"][0])
    assert derived["estado"] == "propuesta"
    assert {p["id"] for p in derived["datos"]["derivacion"]["premisas"]} == {b1, b2}
    assert derived["datos"]["derivacion"]["prueba"]
    again = ciclo().vuelta("aa-ciclo", hechos=facts)
    assert again["derivadas"] == out["derivadas"]
    k.crear_nodo(
        "aa-ciclo",
        "incidente",
        "Contradicción nueva de la premisa",
        {"contradice_creencias": [b1]},
        autor="persona:Ariel",
    )
    same_round = ciclo().vuelta("aa-ciclo", hechos=facts)
    assert derived["id"] in same_round["cuestionadas"]
    ev = k.crear_nodo("aa-ciclo", "evidencia", "premisa refutada", {}, autor="persona:Ariel")
    c.resolver(
        "aa-ciclo", b1, {"por": "persona:Ariel", "motivo": "refutada", "resultado": "refutada", "evidencia": ev["id"]}
    )
    ciclo().vuelta("aa-ciclo", hechos=facts)
    node = next(n for n in c.listar("aa-ciclo") if n["id"] == derived["id"])
    assert node["datos"]["reevaluacion"]["estado"] == "cuestionada"


@MOTOR_REAL
def test_reuso_por_metadata_y_no_aplico_por_destino():
    bid, _ = belief("aa-origen", clausula="recomendar(C, pruebas, focal) :- tecnologia(C, python).")
    k.registrar_proyecto("aa-destino")
    with k._abrir("aa-origen") as con:
        k.actualizar_datos("aa-origen", bid, {"metadatos": {"tecnologia": ["python"]}}, por="server:AA", con=con)
    node = c.listar("aa-origen")[0]
    c.resolver(
        "aa-origen",
        bid,
        {
            "por": "persona:Ariel",
            "motivo": "alcance revisado",
            "resultado": "validada",
            "evidencia": node["datos"]["evidencia_veredicto"],
            "vigente_hasta": node["datos"]["vigente_hasta"],
        },
    )
    found = ciclo().reusar("aa-destino", {"tecnologia": "python"})
    assert [x["creencia"] for x in found] == [bid]
    assert found[0]["proyecto"] == "aa-origen"
    assert ciclo().reusar("aa-destino", {"tecnologia": "typescript"}) == []
    assert ciclo().reusar("aa-destino", {}) == []
    for task in ("uno", "dos"):
        ciclo().registrar_uso_destino(
            "aa-origen", bid, "aa-destino", {"resultado": "no_aplico", "por": "persona:Ariel", "clave": task}
        )
    assert ciclo().reusar("aa-destino", {"tecnologia": "python"}) == []
    k.registrar_proyecto("aa-otro")
    assert len(ciclo().reusar("aa-otro", {"tecnologia": "python"})) == 1


@MOTOR_REAL
def test_derivacion_reusa_premisa_externa_por_referencia_y_sigue_su_caida():
    external, _ = belief("aa-origen", clausula="recurso_necesita_gb(investigador, 3) :- tecnologia(C, python).")
    k.actualizar_datos("aa-origen", external, {"metadatos": {"tecnologia": ["python"]}}, por="persona:Ariel")
    node = c.listar("aa-origen")[0]
    c.resolver(
        "aa-origen",
        external,
        {
            "por": "persona:Ariel",
            "motivo": "alcance revisado",
            "resultado": "validada",
            "evidencia": node["datos"]["evidencia_veredicto"],
            "vigente_hasta": node["datos"]["vigente_hasta"],
        },
    )
    local, _ = belief(
        "aa-destino", clausula="escenario_ram(C, chrome, 4, 1.1) :- chrome_en_uso(C), frentes_activos(C, 4)."
    )
    facts = [
        {"pred": "tecnologia", "args": ["pc", "python"]},
        {"pred": "chrome_en_uso", "args": ["pc"]},
        {"pred": "frentes_activos", "args": ["pc", 4]},
    ]
    source_before = c.listar("aa-origen")
    out = ciclo().vuelta("aa-destino", contexto={"tecnologia": "python"}, hechos=facts)
    assert len(out["derivadas"]) == 1
    derived = next(n for n in c.listar("aa-destino") if n["id"] == out["derivadas"][0])
    refs = {(p["proyecto"], p["id"]) for p in derived["datos"]["derivacion"]["premisas"]}
    assert refs == {("aa-origen", external), ("aa-destino", local)}
    assert c.listar("aa-origen") == source_before
    ev = k.crear_nodo("aa-origen", "evidencia", "refutación", {}, autor="persona:Ariel")
    c.resolver(
        "aa-origen",
        external,
        {"por": "persona:Ariel", "motivo": "refutada", "resultado": "refutada", "evidencia": ev["id"]},
    )
    assert (
        derived["id"] in ciclo().vuelta("aa-destino", contexto={"tecnologia": "python"}, hechos=facts)["cuestionadas"]
    )


def test_graduacion_solo_proceso_aceptado_y_retiro_de_objecion(tmp_path):
    bid, _ = belief("lienzo", clausula="recomendar(C, memoria, medir) :- chrome_en_uso(C).")
    k.actualizar_datos("lienzo", bid, {"alcance": "proceso_lienzo", "principio": True}, por="persona:Ariel")
    node = c.listar("lienzo")[0]
    c.resolver(
        "lienzo",
        bid,
        {
            "por": "persona:Ariel",
            "motivo": "principio revisado",
            "resultado": "validada",
            "evidencia": node["datos"]["evidencia_veredicto"],
            "vigente_hasta": node["datos"]["vigente_hasta"],
        },
    )
    output = tmp_path / "reglas.md"
    ciclo().graduar(archivo=output)
    assert bid in output.read_text(encoding="utf-8")
    # El archivo es una proyección; no conserva como instrucción un principio cuestionado.
    n = c.listar("lienzo")[0]
    k.actualizar_datos(
        "lienzo",
        bid,
        {
            "reevaluacion": {
                "estado": "cuestionada",
                "requiere_veredicto": True,
                "revision_evaluada": ciclo().revision(n),
                "veredicto_fecha": n["datos"]["veredicto_fecha"],
            }
        },
        por="server:AA",
    )
    ciclo().graduar(archivo=output)
    assert bid not in output.read_text(encoding="utf-8")


@MOTOR_REAL
def test_generalizacion_inductiva_conserva_casos_y_prueba_sin_aprobar():
    b1, _ = belief(clausula="recomendar(C, memoria, medir) :- chrome_en_uso(C).")
    b2, _ = belief(clausula="recomendar(C, memoria, medir) :- frentes_activos(C, 4).")
    principle = c.proponer(
        "aa-ciclo",
        {
            "dimension": "memoria",
            "texto": "Medir recursos antes de lanzar",
            "accion": "Revisar memoria y concurrencia antes de lanzar actividades",
            "fuentes": [b1, b2],
        },
        autor="server:AA",
    )
    k.actualizar_datos("aa-ciclo", principle["id"], {"principio": True, "ejemplos": [b1, b2]}, por="server:AA")
    out = ciclo().generalizar("aa-ciclo")
    assert out["principios"] == [principle["id"]]
    node = next(n for n in c.listar("aa-ciclo") if n["id"] == principle["id"])
    assert node["estado"] == "propuesta"
    assert node["datos"]["generalizacion"]["tipo"] == "inductiva"
    assert set(node["datos"]["generalizacion"]["ejemplos"]) == {b1, b2}
    assert len(node["datos"]["generalizacion"]["pruebas"]) == 2


def test_politica_conservadora_no_se_atribuye_a_una_deduccion():
    policy = ciclo().politica_recursos()
    assert policy["tipo"] == "politica_conservadora"
    assert policy["pendiente_medicion"] == [2, 3]
    assert policy["requiere_veredicto"] is False  # aprobada expresamente con el diseño AA
    assert "2" in policy["regla_logica"]["clausula"]


def _con_meta(nid, **meta):
    k.actualizar_datos("aa-ciclo", nid, {"metadatos": {key: [val] for key, val in meta.items()}}, por="server:AA")


@MOTOR_REAL
def test_generalizacion_busca_contraejemplos_y_frena_el_veredicto():
    b1, _ = belief()
    b2, _ = belief()
    caido, ev = belief()
    sano, _ = belief()
    otro, _ = belief()
    _con_meta(b1, tecnologia="python", area="pruebas")
    _con_meta(b2, tecnologia="python", area="pruebas", fase="cierre")
    _con_meta(caido, tecnologia="python", area="pruebas")
    _con_meta(sano, tecnologia="python", area="pruebas")
    _con_meta(otro, tecnologia="node", area="pruebas")
    c.resolver(
        "aa-ciclo",
        caido,
        {"por": "persona:Ariel", "motivo": "falló", "resultado": "refutada", "evidencia": ev},
    )
    principle = c.proponer(
        "aa-ciclo",
        {
            "dimension": "memoria",
            "texto": "En Python, medir antes de probar",
            "accion": "Medir RAM",
            "fuentes": [b1, b2],
        },
        autor="server:AA",
    )
    k.actualizar_datos("aa-ciclo", principle["id"], {"principio": True, "ejemplos": [b1, b2]}, por="server:AA")
    assert ciclo().generalizar("aa-ciclo")["principios"] == [principle["id"]]
    gen = next(n for n in c.listar("aa-ciclo") if n["id"] == principle["id"])["datos"]["generalizacion"]
    assert gen["condiciones"] == [["area", "pruebas"], ["tecnologia", "python"]]
    assert set(gen["cubre"]) == {b1, b2, caido, sano}  # `otro` es de node: no lo cubre
    assert [x["caso"] for x in gen["contraejemplos"]] == [caido] and gen["contraejemplos"][0]["prueba"]
    assert gen["explica"] == [sano]
    assert gen["estado"] == "con_contraejemplos"
    with pytest.raises(k.Rechazo, match="contraejemplos"):
        c.resolver(
            "aa-ciclo",
            principle["id"],
            {"por": "persona:Ariel", "motivo": "ok", "resultado": "validada", "evidencia": ev},
        )
    # refutarlo sigue permitido
    c.resolver(
        "aa-ciclo", principle["id"], {"por": "persona:Ariel", "motivo": "no", "resultado": "refutada", "evidencia": ev}
    )


@MOTOR_REAL
def test_principio_sin_condiciones_no_se_pone_a_prueba():
    b1, _ = belief()
    b2, _ = belief()
    principle = c.proponer(
        "aa-ciclo",
        {"dimension": "memoria", "texto": "Medir", "accion": "Medir RAM", "fuentes": [b1, b2]},
        autor="server:AA",
    )
    k.actualizar_datos("aa-ciclo", principle["id"], {"principio": True, "ejemplos": [b1, b2]}, por="server:AA")
    ciclo().generalizar("aa-ciclo")
    gen = next(n for n in c.listar("aa-ciclo") if n["id"] == principle["id"])["datos"]["generalizacion"]
    assert gen["estado"] in ("sin_condiciones", "sin_contraejemplos") and gen["contraejemplos"] == []
