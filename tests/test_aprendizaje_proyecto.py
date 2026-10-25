"""Aprendizaje por proyecto (encargo Q, 2026-10-22): abrir la pestaña muestra todas las creencias del
proyecto con su estado y deja dar veredicto en un clic; el contexto pasa a filtro opcional que se completa
solo desde la sesión viva más reciente; el texto libre lo interpreta la IA sin guardar nada.

La IA nunca se llama en la suite: el parser se prueba con respuestas fijas y el lanzamiento con un runner falso."""

import json

import conocimiento as k
import conocimiento_api as api
import contexto_ia as ia
import creencias as c
import pytest


def _propuesta(pid, texto="Diagnosticar antes de corregir", contexto=None, **extra):
    k.registrar_proyecto(pid)
    source = k.crear_nodo(pid, "hallazgo", "visto en " + texto, {}, autor="server")
    return c.proponer(
        pid,
        {
            "texto": texto,
            "accion": "Hacer: " + texto,
            "dimension": "pruebas",
            "contexto": contexto if contexto is not None else {"tipo_trabajo": "bugfix"},
            "fuentes": [source["id"]],
            **extra,
        },
        autor="server",
    )


def _ids(vista, bloque):
    return [x["creencia"] for x in vista[bloque]["items"]]


# --- vista del proyecto, sin contexto ---


def test_la_vista_del_proyecto_muestra_todas_sin_pedir_contexto():
    pid = "q-vista"
    b = _propuesta(pid)
    vista = c.vista_proyecto(pid)
    item = vista["proyecto"]["items"][0]
    assert item["creencia"] == b["id"] and item["estado"] == "sin_veredicto"
    # el contexto exigido se informa, no se exige: nada de «Falta contexto»
    assert item["contexto"] == {"tipo_trabajo": "bugfix"}
    assert vista["proyecto"]["total"] == 1


def test_aceptar_en_un_clic_la_vuelve_vigente_con_evidencia_de_la_revision():
    pid = "q-aceptar"
    b = _propuesta(pid)
    out = c.revisar(pid, b["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    assert out["creencia"]["estado"] == "vigente"
    datos = out["creencia"]["datos"]
    assert datos["veredicto_por"] == "persona:Ariel" and datos["resultado"] == "validada"
    ev = k.nodo(pid, datos["evidencia_veredicto"])
    assert ev["tipo"] == "evidencia" and ev["datos"]["clase"] == "revision_humana"
    item = c.vista_proyecto(pid)["proyecto"]["items"][0]
    assert item["estado"] == "vigente"  # sin contexto: vigente, no «aplicable a un contexto»
    # y con el contexto pedido, aplica en el checklist
    assert [x["creencia"] for x in c.checklist(pid, {"tipo_trabajo": "bugfix"})["items"]] == [b["id"]]


def test_rechazar_la_refuta_y_no_se_puede_aceptar_despues():
    pid = "q-rechazar"
    b = _propuesta(pid)
    out = c.revisar(pid, b["id"], {"accion": "rechazar", "por": "persona:Ariel", "motivo": "no aplica"})
    assert out["creencia"]["estado"] == "revertida"
    assert c.vista_proyecto(pid)["proyecto"]["items"][0]["estado"] == "refutada"
    with pytest.raises(k.Rechazo) as e:
        c.revisar(pid, b["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    assert e.value.codigo == 409


def test_corregir_crea_la_sucesora_vigente_y_retira_la_original():
    pid = "q-corregir"
    b = _propuesta(pid)
    out = c.revisar(
        pid,
        b["id"],
        {"accion": "corregir", "por": "persona:Ariel", "accion_nueva": "Diagnosticar y medir antes de corregir"},
    )
    nueva = out["nueva"]
    assert nueva["estado"] == "vigente" and nueva["datos"]["accion"] == "Diagnosticar y medir antes de corregir"
    assert nueva["datos"]["contexto"] == {"tipo_trabajo": "bugfix"}  # hereda contexto y dimensión
    # corregir no es refutar (2026-10-25): la original queda reemplazada y su evidencia sigue en la sucesora
    assert out["creencia"]["estado"] == "reemplazada"
    assert out["creencia"]["datos"]["reemplazada_por"] == nueva["id"]
    salen = k.nodo(pid, nueva["id"])["vinculos"]["salen"]
    assert any(v["relacion"] == "reemplaza" and v["a"] == b["id"] for v in salen)
    estados = {x["creencia"]: x["estado"] for x in c.vista_proyecto(pid)["proyecto"]["items"]}
    assert estados == {nueva["id"]: "vigente", b["id"]: "reemplazada"}


def test_corregir_una_vigente_la_marca_reemplazada():
    pid = "q-corregir-vigente"
    b = _propuesta(pid)
    c.revisar(pid, b["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    out = c.revisar(pid, b["id"], {"accion": "corregir", "por": "persona:Ariel", "accion_nueva": "Otra acción"})
    assert out["creencia"]["estado"] == "reemplazada" and out["nueva"]["estado"] == "vigente"


@pytest.mark.parametrize(
    "body",
    [
        {"accion": "aceptar", "por": "server"},
        {"accion": "aceptar", "por": "persona:"},
        {"accion": "aceptar", "por": "coordinadora:x"},
        {"accion": "inventada", "por": "persona:Ariel"},
        {"accion": "corregir", "por": "persona:Ariel"},
        {"accion": "corregir", "por": "persona:Ariel", "accion_nueva": "  "},
    ],
)
def test_revision_invalida_no_escribe_nada(body):
    pid = "q-invalida"
    b = _propuesta(pid)
    antes = k.cambios(pid)
    evidencias = k.nodos(pid, tipo="evidencia")["total"]
    with pytest.raises(k.Rechazo):
        c.revisar(pid, b["id"], body)
    assert k.cambios(pid) == antes and k.nodos(pid, tipo="evidencia")["total"] == evidencias


def test_revision_por_http():
    pid = "q-http"
    b = _propuesta(pid)
    code, out = api.dispatch("GET", [pid, "creencias-proyecto"], None, {})
    assert code == 200 and _ids(out, "proyecto") == [b["id"]]
    code, out = api.dispatch(
        "POST", [pid, "creencias", b["id"], "revision"], {"accion": "aceptar", "por": "persona:Ariel"}, {}
    )
    assert code == 200 and out["creencia"]["estado"] == "vigente"


# --- dos alcances: del proyecto y de cómo se trabaja con Lienzo ---


def test_alcance_proceso_lienzo_sólo_en_el_proyecto_lienzo():
    with pytest.raises(k.Rechazo):
        _propuesta("q-alcance-otro", alcance="proceso_lienzo")
    with pytest.raises(k.Rechazo):
        _propuesta("lienzo", texto="alcance raro", alcance="global")
    b = _propuesta("lienzo", texto="Coordinar en .temp q-alcance", alcance="proceso_lienzo")
    assert b["datos"]["alcance"] == "proceso_lienzo"


def test_otro_proyecto_ve_las_de_proceso_de_lienzo_aparte():
    proceso = _propuesta("lienzo", texto="Verificar en uso real antes de cerrar q-dos", alcance="proceso_lienzo")
    propia_lienzo = _propuesta("lienzo", texto="Achicar el tablero q-dos")
    otra = _propuesta("q-otro", texto="Leer antes de aplicar")
    vista = c.vista_proyecto("q-otro")
    assert _ids(vista, "proyecto") == [otra["id"]]
    assert proceso["id"] in _ids(vista, "lienzo") and propia_lienzo["id"] not in _ids(vista, "lienzo")
    # en lienzo se ven las dos cosas: las de proceso marcadas en su bloque, no repetidas en el otro
    vista = c.vista_proyecto("lienzo")
    assert proceso["id"] in _ids(vista, "lienzo") and proceso["id"] not in _ids(vista, "proyecto")
    assert propia_lienzo["id"] in _ids(vista, "proyecto")


def test_cambiar_el_alcance_no_recrea_la_creencia():
    b = _propuesta("lienzo", texto="Una ronda, una carpeta q-cambio")
    out = c.cambiar_alcance("lienzo", b["id"], {"alcance": "proceso_lienzo", "por": "coordinadora:c7"})
    assert out["id"] == b["id"] and out["estado"] == "propuesta" and out["datos"]["alcance"] == "proceso_lienzo"
    code, out = api.dispatch(
        "POST", ["lienzo", "creencias", b["id"], "alcance"], {"alcance": "proyecto", "por": "persona:Ariel"}, {}
    )
    assert code == 200 and out["datos"]["alcance"] == "proyecto"
    for body in ({"alcance": "proceso_lienzo", "por": "server"}, {"alcance": "x", "por": "persona:Ariel"}):
        with pytest.raises(k.Rechazo):
            c.cambiar_alcance("lienzo", b["id"], body)
    otra = _propuesta("q-cambio-otro")
    with pytest.raises(k.Rechazo):
        c.cambiar_alcance("q-cambio-otro", otra["id"], {"alcance": "proceso_lienzo", "por": "persona:Ariel"})


# --- contexto sugerido: la sesión viva más reciente del proyecto ---


def test_sin_sesion_elegida_toma_la_viva_mas_reciente_del_proyecto(monkeypatch, tmp_path):
    import sessions as ses

    pid = "q-sugerido"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(k, "resolver_proyecto", lambda repo_key, cwd, pc=None: pid if cwd == str(tmp_path) else None)
    base = {"cwd": str(tmp_path), "alive": True, "agent": "claude"}
    monkeypatch.setitem(
        ses.sessions,
        "s-vieja",
        {**base, "session_id": "s-vieja", "model": "viejo", "last_event_ts": "2026-10-22T10:00:00Z"},
    )
    monkeypatch.setitem(
        ses.sessions,
        "s-nueva",
        {**base, "session_id": "s-nueva", "model": "opus", "last_event_ts": "2026-10-22T11:00:00Z"},
    )
    monkeypatch.setitem(
        ses.sessions,
        "s-muerta",
        {**base, "session_id": "s-muerta", "model": "muerto", "alive": False, "last_event_ts": "2026-10-22T12:00:00Z"},
    )
    monkeypatch.setitem(
        ses.sessions,
        "s-ajena",
        {**base, "session_id": "s-ajena", "cwd": "D:/otro", "model": "ajeno", "last_event_ts": "2026-10-22T13:00:00Z"},
    )
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {})
    assert code == 200 and out["contexto"] == {"agente": "claude", "modelo": "opus"}
    assert out["session_id"] == "s-nueva"
    assert out["fuentes"]["modelo"].startswith("la sesión") and "s-nueva"[:8] in out["fuentes"]["modelo"]


def test_cada_dato_dice_de_donde_salio():
    pid = "q-fuentes"
    k.registrar_proyecto(pid)
    ronda = k.abrir_ronda(pid, "ronda", autor="coordinadora")
    k.crear_encargo(pid, ronda["id"], "Q", "# Q", autor="coordinadora", contexto_desarrollo={"tipo_trabajo": "feature"})
    out = c.contexto_sugerido(pid, tarjeta={"agent": "claude", "version": "2.9.1", "session_id": "abcdef123"})
    assert out["contexto"] == {"tipo_trabajo": "feature", "agente": "claude", "version_agente": "2.9.1"}
    assert "encargo Q" in out["fuentes"]["tipo_trabajo"]
    assert "abcdef12" in out["fuentes"]["agente"] and out["fuentes"]["version_agente"] == out["fuentes"]["agente"]


def test_version_del_agente_desde_la_transcripcion(tmp_path):
    claude = tmp_path / "c.jsonl"
    claude.write_text(
        "\n".join(
            json.dumps(x) for x in ({"type": "user", "version": "2.9.0"}, {"type": "assistant", "version": "2.9.1"})
        ),
        encoding="utf-8",
    )
    assert api._version_agente({"agent": "claude", "transcript_path": str(claude)}) == "2.9.1"
    codex = tmp_path / "x.jsonl"
    codex.write_text(
        json.dumps({"type": "session_meta", "payload": {"cli_version": "0.80.0"}}) + "\n", encoding="utf-8"
    )
    assert api._version_agente({"agent": "codex", "transcript_path": str(codex)}) == "0.80.0"
    assert api._version_agente({"agent": "claude", "transcript_path": str(tmp_path / "no")}) is None
    assert api._version_agente({}) is None


# --- texto libre interpretado por la IA (parser con respuestas fijas) ---


def _evento(salida):
    return json.dumps({"type": "result", "is_error": False, "structured_output": salida, "result": ""})


def test_parser_toma_los_cuatro_campos_validos():
    out = ia.parsear(
        _evento({"tipo_trabajo": "bugfix", "tecnologia": " python ", "area": "memoria", "fase": "implementacion"})
    )
    assert out == {
        "contexto": {"tipo_trabajo": "bugfix", "tecnologia": "python", "area": "memoria", "fase": "implementacion"},
        "descartados": {},
    }


def test_parser_descarta_lo_que_no_es_del_vocabulario():
    out = ia.parsear(
        _evento(
            {"tipo_trabajo": "arreglo", "tecnologia": "", "area": "x" * 300, "fase": "sin_clasificar", "agente": "pi"}
        )
    )
    assert out["contexto"] == {"area": "x" * 100}
    assert set(out["descartados"]) == {"tipo_trabajo", "fase"}


def test_parser_toma_como_vacio_lo_que_la_ia_escribe_como_vacio():
    """Medido con Claude real (2026-10-22): para «no lo dice» devolvió la cadena `""` con las comillas."""
    out = ia.parsear(_evento({"tipo_trabajo": "documentacion", "tecnologia": '""', "area": "''", "fase": " null "}))
    assert out == {"contexto": {"tipo_trabajo": "documentacion"}, "descartados": {}}
    out = ia.parsear(_evento({"tipo_trabajo": "feature", "tecnologia": "N/A", "area": "-", "fase": "ninguna"}))
    assert out["contexto"] == {"tipo_trabajo": "feature"}


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "no es json",
        json.dumps({"type": "result", "is_error": True, "structured_output": {"tipo_trabajo": "bugfix"}}),
        json.dumps({"type": "result", "is_error": False}),
        json.dumps([1, 2]),
    ],
)
def test_parser_ante_respuesta_rota_devuelve_none(stdout):
    assert ia.parsear(stdout) is None


def test_parser_acepta_el_json_en_result_cuando_falta_structured_output():
    stdout = json.dumps({"type": "result", "is_error": False, "result": '```json\n{"tipo_trabajo": "feature"}\n```'})
    assert ia.parsear(stdout)["contexto"] == {"tipo_trabajo": "feature"}


def _runner(resultado, visto):
    def run(argv, **kw):
        visto.update(argv=argv, **kw)
        return {
            "code": 0,
            "stdout": "",
            "stderr": "",
            "seconds": 1.0,
            "timed_out": False,
            "output_exceeded": False,
            **resultado,
        }

    return run


def test_interpretar_lanza_claude_restringido_sin_clave_y_no_guarda(monkeypatch):
    pid = "q-ia"
    _propuesta(pid, contexto={"tipo_trabajo": "bugfix", "tecnologia": "react"})
    monkeypatch.setattr(ia.shutil, "which", lambda name: "C:/claude.exe")
    visto = {}
    antes = k.cambios(pid)
    code, out = ia.interpretar(
        pid,
        "Voy a arreglar el filtro de la pestaña de aprendizaje en React",
        runner=_runner(
            {"stdout": _evento({"tipo_trabajo": "bugfix", "tecnologia": "react", "area": "aprendizaje", "fase": ""})},
            visto,
        ),
    )
    assert code == 200 and out["contexto"] == {"tipo_trabajo": "bugfix", "tecnologia": "react", "area": "aprendizaje"}
    assert out["via"] == "claude" and k.cambios(pid) == antes
    argv = visto["argv"]
    assert "--restricted" in argv and "--safe-mode" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert "ANTHROPIC_API_KEY" in visto["env_remove"] and visto["timeout"] <= 60
    assert "react" in visto["stdin_text"] and "bugfix" in visto["stdin_text"]  # vocabulario del proyecto


@pytest.mark.parametrize(
    "resultado,codigo,texto",
    [
        ({"timed_out": True, "code": -2}, 504, "no respondió"),
        ({"code": 1, "stderr": "boom"}, 502, "boom"),
        ({"stdout": "basura"}, 502, "no se pudo leer"),
    ],
)
def test_interpretar_cae_claro_y_deja_los_campos_a_mano(monkeypatch, resultado, codigo, texto):
    pid = "q-ia-caida"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(ia.shutil, "which", lambda name: "C:/claude.exe")
    code, out = ia.interpretar(pid, "algo para hacer", runner=_runner(resultado, {}))
    assert code == codigo and texto in out["error"] and "a mano" in out["error"]


def test_interpretar_sin_claude_ni_texto(monkeypatch):
    pid = "q-ia-sin"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(ia.shutil, "which", lambda name: None)
    code, out = ia.interpretar(pid, "algo para hacer", runner=_runner({}, {}))
    assert code == 503 and "a mano" in out["error"]
    with pytest.raises(k.Rechazo):
        ia.interpretar(pid, "  ", runner=_runner({}, {}))
    with pytest.raises(k.Rechazo):
        ia.interpretar(pid, "x" * 2001, runner=_runner({}, {}))


def test_interpretar_por_http_usa_el_modulo(monkeypatch):
    pid = "q-ia-http"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(
        ia, "interpretar", lambda p, texto, **kw: (200, {"contexto": {"fase": "diseno"}, "p": p, "t": texto})
    )
    code, out = api.dispatch("POST", [pid, "interpretar-contexto"], {"texto": "diseñar"}, {})
    assert code == 200 and out["p"] == pid and out["t"] == "diseñar"


# --- revisión V (2026-10-22): el motor en la apertura y el proceso de Lienzo en el checklist de los demás ---


def test_v4_la_vista_trae_el_contraste_guardado_y_las_reglas_cuestionadas():
    """V-4: abrir Aprendizaje distingue una propuesta que el motor sostiene de una que contradice, y marca
    una vigente con una regla derivada cuestionada, sin pedir contexto."""
    pid = "q-v4"
    sost = _propuesta(pid, texto="Sostenida por el motor")
    contra = _propuesta(pid, texto="Contradicha por el motor")
    caida = _propuesta(pid, texto="Sin motor al contrastar")
    for nid, found in (
        (sost["id"], {"resultado": "sostenida", "fecha": "2026-10-22T20:00:00Z"}),
        (contra["id"], {"resultado": "contradice", "observaciones": ["contradice"], "fecha": "2026-10-22T20:00:00Z"}),
        (caida["id"], {"resultado": "sin_motor", "motivo": "WSL no respondió", "fecha": "2026-10-22T20:00:00Z"}),
    ):
        k.actualizar_datos(pid, nid, {"contraste": found}, por="server", motivo="contraste")
    vigente = _propuesta(pid, texto="Vigente con regla cuestionada")
    c.revisar(pid, vigente["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    regla = k.crear_nodo(pid, "regla", "Regla derivada", {"ambito": "proyecto"}, autor="persona:Ariel")
    k.vincular(pid, regla["id"], "derivada_de", vigente["id"], autor="persona:Ariel")
    with k._abrir(pid) as con:  # el ciclo real (recurrencia) lo prueba el e2e de J; acá sólo el estado
        con.execute("UPDATE nodo SET estado='cuestionada' WHERE id=?", (regla["id"],))
    items = {x["creencia"]: x for x in c.vista_proyecto(pid)["proyecto"]["items"]}
    assert items[sost["id"]]["contraste"]["resultado"] == "sostenida"
    assert items[contra["id"]]["contraste"]["resultado"] == "contradice"
    assert items[caida["id"]]["contraste"] == {
        "resultado": "sin_motor",
        "motivo": "WSL no respondió",
        "fecha": "2026-10-22T20:00:00Z",
    }
    assert items[vigente["id"]]["estado"] == "vigente" and items[vigente["id"]]["reglas_cuestionadas"] == [regla["id"]]
    assert items[sost["id"]]["reglas_cuestionadas"] == []


def test_v5_el_checklist_de_otro_proyecto_suma_las_de_proceso_de_lienzo():
    """V-5: una creencia de proceso de Lienzo validada para bugfix aplica al checklist de cualquier proyecto,
    una sola vez, con su proyecto dueño; otro contexto la excluye y la propia de lienzo nunca se filtra."""
    import prolog_checklist as pk

    proceso = _propuesta("lienzo", texto="Verificar en uso real q-v5", alcance="proceso_lienzo")
    c.revisar("lienzo", proceso["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    propia = _propuesta("lienzo", texto="Achicar el tablero q-v5")
    c.revisar("lienzo", propia["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    k.registrar_proyecto("q-v5-otro")
    out = pk.checklist("q-v5-otro", {"tipo_trabajo": "bugfix"}, limite=20)
    todos = out["items"] + out["cuestionadas"] + out["no_aplican"]
    assert [x["creencia"] for x in todos].count(proceso["id"]) == 1
    assert propia["id"] not in [x["creencia"] for x in todos]
    item = next(x for x in todos if x["creencia"] == proceso["id"])
    assert item["proyecto"] == "lienzo" and item["estado"] in ("aplicable", "cuestionada")
    assert "motor_proceso" in out
    otro = pk.checklist("q-v5-otro", {"tipo_trabajo": "refactor"}, limite=20)
    assert proceso["id"] not in [x["creencia"] for x in otro["items"]]
    # en lienzo no se duplica: ya es suya
    en_lienzo = pk.checklist("lienzo", {"tipo_trabajo": "bugfix"}, limite=20)
    ids = [x["creencia"] for x in en_lienzo["items"] + en_lienzo["cuestionadas"] + en_lienzo["no_aplican"]]
    assert ids.count(proceso["id"]) == 1 and "motor_proceso" not in en_lienzo


# --- code review del delta Q (review/2026-10-22/code-review-Q.md) ---


def test_cr1_una_tarjeta_elegida_de_otro_proyecto_no_cae_a_otra_sesion(monkeypatch, tmp_path):
    import sessions as ses

    pid = "q-cr1"
    k.registrar_proyecto(pid)
    mia, ajena = str(tmp_path / "mia"), str(tmp_path / "ajena")
    monkeypatch.setattr(k, "resolver_proyecto", lambda repo_key, cwd, pc=None: pid if cwd == mia else "otro")
    monkeypatch.setitem(ses.sessions, "s-viva", {"session_id": "s-viva", "cwd": mia, "alive": True, "agent": "codex"})
    monkeypatch.setitem(
        ses.sessions, "s-elegida", {"session_id": "s-elegida", "cwd": ajena, "alive": True, "agent": "pi"}
    )
    code, out = api.dispatch("GET", [pid, "contexto-sugerido"], None, {"session_id": "s-elegida"})
    assert code == 200 and out["contexto"] == {} and out["session_id"] is None


def test_cr2_la_vista_no_tapa_un_contexto_roto():
    pid = "q-cr2"
    b = _propuesta(pid)
    c.revisar(pid, b["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    k.actualizar_datos(pid, b["id"], {"contexto": {"inventado": "x"}}, por="persona:Ariel", motivo="rompe")
    assert c.vista_proyecto(pid)["proyecto"]["items"][0]["estado"] == "contexto_invalido"


def test_cr4_renovar_no_acorta_una_vigencia_mas_larga():
    import datetime as dt

    pid = "q-cr4"
    b = _propuesta(pid)
    ev = k.crear_nodo(pid, "evidencia", "revisión larga", {}, autor="persona:Ariel")
    lejos = (dt.datetime.now(dt.UTC) + dt.timedelta(days=500)).isoformat()
    c.resolver(
        pid,
        b["id"],
        {"por": "persona:Ariel", "motivo": "m", "resultado": "validada", "evidencia": ev["id"], "vigente_hasta": lejos},
    )
    out = c.revisar(pid, b["id"], {"accion": "aceptar", "por": "persona:Ariel"})
    assert dt.datetime.fromisoformat(out["creencia"]["datos"]["vigente_hasta"]) >= dt.datetime.fromisoformat(lejos)


def test_cr5_una_revision_que_falla_no_deja_evidencia():
    pid = "q-cr5"
    b = _propuesta(pid)
    k.actualizar_datos(pid, b["id"], {"dimension": "rota"}, por="persona:Ariel", motivo="dimensión vieja")
    antes = k.nodos(pid, tipo="evidencia")["total"]
    with pytest.raises(k.Rechazo):
        c.revisar(pid, b["id"], {"accion": "corregir", "por": "persona:Ariel", "accion_nueva": "Otra"})
    assert k.nodos(pid, tipo="evidencia")["total"] == antes


def test_cr6_version_con_lineas_que_no_son_objetos(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text(
        "null\n42\n[1]\n" + json.dumps({"type": "session_meta", "payload": {"cli_version": "0.81.0"}}) + "\n",
        encoding="utf-8",
    )
    assert api._version_agente({"agent": "codex", "transcript_path": str(path)}) == "0.81.0"
    # la versión de Claude no se toma de una transcripción de otro agente
    other = tmp_path / "k.jsonl"
    other.write_text(json.dumps({"version": "9.9.9"}) + "\n", encoding="utf-8")
    assert api._version_agente({"agent": "kiro", "transcript_path": str(other)}) is None


def test_cr7_una_interpretacion_por_proyecto_a_la_vez(monkeypatch):
    import threading

    pid = "q-cr7"
    k.registrar_proyecto(pid)
    monkeypatch.setattr(ia.shutil, "which", lambda name: "C:/claude.exe")
    adentro, soltar = threading.Event(), threading.Event()

    def lento(argv, **kw):
        adentro.set()
        soltar.wait(5)
        return {"code": 0, "stdout": _evento({"tipo_trabajo": "bugfix"}), "stderr": "", "timed_out": False}

    hilo = threading.Thread(target=ia.interpretar, args=(pid, "uno"), kwargs={"runner": lento})
    hilo.start()
    assert adentro.wait(5)
    code, out = ia.interpretar(pid, "dos", runner=lento)
    soltar.set()
    hilo.join(5)
    assert code == 409 and "en curso" in out["error"]
    assert ia.interpretar(pid, "tres", runner=_runner({"stdout": _evento({"tipo_trabajo": "feature"})}, {}))[0] == 200


def test_v5_el_texto_del_encargo_nombra_el_proyecto_de_una_de_proceso():
    item = {
        "accion": "Verificar en uso real",
        "creencia": "abc",
        "evidencia": "ev",
        "excepciones": "",
        "sostenida": None,
    }
    texto = c.texto_aprendizajes([{**item, "alcance": "proceso_lienzo", "proyecto": "lienzo"}])
    assert "creencia abc del proyecto lienzo" in texto
    assert "(creencia abc, evidencia" in c.texto_aprendizajes([{**item, "alcance": "proyecto", "proyecto": "otro"}])
