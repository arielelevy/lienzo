import importlib.util
import urllib.parse
from pathlib import Path


def cliente():
    spec = importlib.util.spec_from_file_location(
        "cliente_memoria", Path(__file__).parents[1] / "skills/lienzo/coordinar.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_preguntar_conserva_consultas_repetidas_y_paginacion(monkeypatch):
    c = cliente()
    requests = []
    monkeypatch.setattr(c, "_conocimiento", lambda metodo, ruta: requests.append((metodo, ruta)))
    c.preguntar("lienzo", ["error OR timeout", "regla"], temas=["memoria", "red"], offset=100, limite=25)
    metodo, ruta = requests[0]
    assert metodo == "GET"
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(ruta).query)
    assert query["q"] == ["error OR timeout", "regla"]
    assert query["temas"] == ["memoria", "red"]
    assert query["offset"] == ["100"] and query["limite"] == ["25"]


def test_texto_encargo_conserva_estado_y_referencias(monkeypatch):
    c = cliente()
    pedidos = []

    def briefing(*args, **kwargs):
        pedidos.append(kwargs)
        return {"markdown": "## Memoria del proyecto\n- [hallazgo, propuesto] cola lenta (nodo:h1)"}

    monkeypatch.setattr(c, "briefing", briefing)
    texto = c.preparar_encargo("lienzo", "Revisar conexiones")
    assert texto.startswith("Revisar conexiones")
    assert pedidos[0]["markdown"] is True  # texto legible (v5 etapa 5), no el JSON del briefing
    assert "nodo:h1" in texto and "propuesto" in texto
    assert c.INSTRUCCION_CONOCIMIENTO in texto
