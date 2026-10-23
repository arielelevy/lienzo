"""AA lote 1: contrato de cláusulas y proyecciones, sin arrancar WSL."""

import hashlib
import json

import pytest


def programa():
    # Import diferido: el rojo debe identificar el contrato ausente por caso.
    import prolog_programa

    return prolog_programa


def regla(texto):
    return {"version": 1, "vocabulario": 1, "clausula": texto}


def test_clausula_se_convierte_en_ast_sin_ejecutar():
    ast = programa().validar(regla("impedir(C, investigador, ram) :- memoria_libre_gb(C, M), M < 3."))
    assert ast["head"] == {"pred": "impedir", "args": ["?C", "investigador", "ram"]}
    assert ast["body"] == [
        {"pred": "memoria_libre_gb", "args": ["?C", "?M"]},
        {"cmp": "<", "args": ["?M", 3]},
    ]


@pytest.mark.parametrize(
    "texto",
    [
        ":- initialization(shell('echo peligro')).",
        "impedir(C, investigador, ram) :- shell(C).",
        "impedir(C, investigador, ram) :- call(memoria_libre_gb(C, M)).",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, M); chrome_en_uso(C).",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, M), !.",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, M). halt.",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C).",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, M), N < 3.",
        "impedir(C, investigador, ram) :- chrome_en_uso(D).",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, texto).",
        "impedir(C, investigador, ram) :- memoria_libre_gb(C, -1).",
    ],
)
def test_rechaza_codigo_fuera_del_lenguaje_y_hechos_invalidos(texto):
    with pytest.raises(ValueError):
        programa().validar(regla(texto))


def test_no_acepta_version_bool_o_vocabulario_desconocido():
    mod = programa()
    for cambio in ({"version": True}, {"vocabulario": 99}, {"clausula": None}):
        with pytest.raises(ValueError):
            mod.validar({**regla("recomendar(C, memoria, medir) :- chrome_en_uso(C)."), **cambio})


def test_identidad_semantica_no_depende_de_variables_ni_evidencia():
    mod = programa()
    a = mod.validar(regla("recomendar(C, memoria, medir) :- chrome_en_uso(C)."))
    b = mod.validar(regla("recomendar(X,memoria,medir):-chrome_en_uso(X)."))
    assert mod.identidad(a) == mod.identidad(b)
    c = mod.validar(regla("recomendar(C, memoria, medir) :- chrome_en_uso(C), frentes_activos(C, 4)."))
    assert mod.identidad(a) != mod.identidad(c)


def nodo(nid="b1", proyecto="lienzo", alcance="proyecto"):
    return {
        "id": nid,
        "proyecto": proyecto,
        "estado": "propuesta",
        "texto": "Medir memoria",
        "datos": {
            "clase": "creencia_operativa",
            "alcance": alcance,
            "regla_logica": regla("recomendar(C, memoria, medir) :- chrome_en_uso(C)."),
            "metadatos": {"proyecto": proyecto, "tecnologia": [], "fuentes": {}},
        },
    }


def test_exportar_es_determinista_legible_y_no_activa_propuestas():
    mod = programa()
    nodes = [nodo("b2"), nodo("b1")]
    a = mod.renderizar("lienzo", nodes)
    assert a == mod.renderizar("lienzo", list(reversed(nodes)))
    assert "regla_logica(" in a and "chrome_en_uso" in a
    assert "vigente(" not in a
    assert any(line.startswith("% Regla") and ":-" in line for line in a.splitlines())
    assert all(":-" not in line for line in a.splitlines() if not line.startswith("%"))


def test_exportacion_no_omite_silenciosamente_clausula_invalida():
    n = nodo()
    n["datos"]["regla_logica"] = regla("recomendar(C, x, y) :- shell(C).")
    with pytest.raises(ValueError):
        programa().renderizar("lienzo", [n])


def test_legacy_sin_regla_queda_explicita_sin_inventar_formalizacion():
    n = nodo()
    del n["datos"]["regla_logica"]
    result = programa().renderizar("lienzo", [n])
    assert "sin_formalizar" in result and "b1" in result


def test_exportacion_separa_proyecto_y_proceso_y_rechaza_rutas(tmp_path):
    mod = programa()
    nodes = [nodo(), nodo("b2", alcance="proceso_lienzo")]
    result = mod.exportar("lienzo", nodes, secuencia=7, raiz=tmp_path)
    project = (tmp_path / "proyectos/lienzo.pl").read_text(encoding="utf-8")
    process = (tmp_path / "proceso_lienzo.pl").read_text(encoding="utf-8")
    assert "b1" in project and "b2" not in project
    assert "b2" in process and "b1" not in process
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["proyectos"]["lienzo"]["secuencia"] == 7
    assert result["hash"] == hashlib.sha256((tmp_path / "proyectos/lienzo.pl").read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        mod.exportar("../afuera", nodes, secuencia=8, raiz=tmp_path)


def test_fallo_validacion_no_publica_archivo_ni_manifest(tmp_path):
    mod = programa()
    mod.exportar("lienzo", [nodo()], secuencia=1, raiz=tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    bad = nodo()
    bad["datos"]["regla_logica"] = regla("impedir(C, x, y) :- shell(C).")
    with pytest.raises(ValueError):
        mod.exportar("lienzo", [bad], secuencia=2, raiz=tmp_path)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_proponer_guarda_regla_y_rechaza_invalida_sin_crear_nodo():
    import conocimiento as k
    import creencias

    k.registrar_proyecto("aa-programa")
    source = k.crear_nodo("aa-programa", "evidencia", "Chrome observado", {}, autor="persona:Ariel")
    data = {
        "dimension": "pruebas",
        "texto": "Medir antes de lanzar",
        "accion": "Medir RAM",
        "fuentes": [source["id"]],
        "regla_logica": regla("recomendar(C, memoria, medir) :- chrome_en_uso(C)."),
    }
    saved = creencias.proponer("aa-programa", data, autor="server:AA")
    assert saved["datos"]["regla_logica"] == data["regla_logica"]
    count = len(creencias.listar("aa-programa"))
    with pytest.raises(k.Rechazo):
        creencias.proponer(
            "aa-programa", {**data, "regla_logica": regla("recomendar(C,x,y):-shell(C).")}, autor="server:AA"
        )
    assert len(creencias.listar("aa-programa")) == count


def test_evidencia_nueva_se_anexa_sin_crear_otra_propuesta():
    import conocimiento as k
    import creencias

    k.registrar_proyecto("aa-dedupe")
    e1 = k.crear_nodo("aa-dedupe", "evidencia", "medición primera", {}, autor="persona:Ariel")
    e2 = k.crear_nodo("aa-dedupe", "evidencia", "medición posterior", {}, autor="persona:Ariel")
    data = {
        "dimension": "memoria",
        "texto": "Chrome dejó 1.1 GB",
        "accion": "Medir RAM antes de lanzar",
        "fuentes": [e1["id"]],
        "regla_logica": regla("recomendar(C, memoria, medir) :- chrome_en_uso(C)."),
    }
    first = creencias.proponer("aa-dedupe", data, autor="server:AA")
    second = creencias.proponer(
        "aa-dedupe", {**data, "texto": "Chrome dejó 1.3 GB", "fuentes": [e2["id"]]}, autor="server:AA"
    )
    assert first["id"] == second["id"]
    assert len(creencias.listar("aa-dedupe")) == 1
    assert set(second["datos"]["fuentes"]) == {e1["id"], e2["id"]}
    assert any(x["texto"] == "Chrome dejó 1.3 GB" for x in second["datos"]["observaciones"])


def test_clausula_puede_condicionarse_por_extension_y_ruta():
    ast = programa().validar(regla("recomendar(C, pruebas, focal) :- tipo_archivo(C, '.py'), ruta(C, 'web/src/a.py')."))
    assert ast["body"][0]["args"] == ["?C", ".py"]
    assert ast["body"][1]["args"] == ["?C", "web/src/a.py"]


def test_clausula_derivada_tiene_forma_logica_validada_y_legible():
    mod = programa()
    ast = mod.validar(
        regla(
            "impedir(C, investigador, ram) :- escenario_ram(C, chrome, 4, M), recurso_necesita_gb(investigador, N), M < N."
        )
    )
    saved = mod.desde_ast(ast)
    assert saved["version"] == 1 and saved["vocabulario"] == 1
    assert mod.validar(saved) == ast
