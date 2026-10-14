"""Cargador de plugins locales (lienzo/plugins.py): modulos que viven solo en la PC que los tiene."""

import plugins
import procinfo
import pytest

PLUGIN = """
RUNNERS_EXTERNOS = {"Orq.exe": "orquestador"}
iniciado = []


def iniciar():
    iniciado.append(True)


def get(partes, query):
    return 200, {"partes": partes, "q": query}


def post(partes, cuerpo, ctx):
    return 201, {"partes": partes, "cuerpo": cuerpo, "autor": ctx["autor"]}
"""


@pytest.fixture
def limpio(monkeypatch):
    monkeypatch.setattr(plugins, "_cargados", {})
    monkeypatch.setattr(procinfo, "EXTERNAL_RUNNERS", {})


def test_sin_carpeta_no_carga_nada(limpio, tmp_path):
    assert plugins.cargar(str(tmp_path / "no-existe")) == []
    assert plugins.get("x", [], {})[0] == 404 and plugins.post("x", [], {}, {"autor": "a"})[0] == 404


def test_carga_registra_rutas_y_lanzadores(limpio, tmp_path):
    (tmp_path / "orq.py").write_text(PLUGIN, encoding="utf-8")
    (tmp_path / "Mayus.py").write_text(PLUGIN, encoding="utf-8")  # nombre invalido: no se carga
    (tmp_path / "notas.txt").write_text("x", encoding="utf-8")
    assert plugins.cargar(str(tmp_path)) == ["orq"]
    assert procinfo.EXTERNAL_RUNNERS == {"orq.exe": "orquestador"}
    plugins.iniciar()
    assert plugins._cargados["orq"].iniciado == [True]
    assert plugins.get("orq", ["a", "b"], {"k": ["v"]}) == (200, {"partes": ["a", "b"], "q": {"k": ["v"]}})
    assert plugins.post("orq", ["c"], {"x": 1}, {"autor": "yo"})[1]["autor"] == "yo"
    assert plugins.get("otro", [], {})[0] == 404


def test_un_plugin_roto_no_frena_a_los_demas(limpio, tmp_path):
    (tmp_path / "roto.py").write_text("raise RuntimeError('mal')\n", encoding="utf-8")
    (tmp_path / "sano.py").write_text("def get(p, q):\n    return 200, {}\n", encoding="utf-8")
    assert plugins.cargar(str(tmp_path)) == ["sano"]


def test_ruta_ext_del_server(limpio, tmp_path, monkeypatch):
    import server

    (tmp_path / "orq.py").write_text(PLUGIN, encoding="utf-8")
    plugins.cargar(str(tmp_path))
    assert plugins.nombres() == ["orq"]
    import pathlib

    fuente = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    assert 'parts[0] == "ext"' in fuente and "plugins.cargar()" in fuente
