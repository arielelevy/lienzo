"""Las guardias de la particion (tests/guardia_monkeypatch.py): un monkeypatch sin efecto falla, y
ningun modulo de lienzo/ importa server."""

import sys
import types

import guardia_monkeypatch as guardia
import pytest

MODELO = """\
from otro import reexportado

LEIDA = 1
SOLO_AL_IMPORTAR = 2
COPIA = SOLO_AL_IMPORTAR
SOLO_DEFAULT = 3


def usado():
    return LEIDA


def llama():
    return usado()


def con_default(x=SOLO_DEFAULT):
    return x


def solo_asigna():
    global SOLO_ASIGNADA
    SOLO_ASIGNADA = {}


def cuenta():
    global CONTADOR
    CONTADOR += 1


def tapada(TAPADA):
    return TAPADA
"""

OTRO = """\
import modelo as m


def reexportado():
    m.solo_escrito = 1
    return m.leido_de_afuera


def por_nombre():
    return getattr(m, "por_texto")


def clave(d):
    return d["como_clave"]


def importa_al_correr():
    from modelo import por_import_local

    return por_import_local


def suma():
    m.sumado += 1


def de_un_objeto(self):
    return self.modelo.por_objeto


def importa_al_correr_el_modulo():
    import modelo as mm

    return mm.por_import_funcion


def con_comprension(xs):
    ys = [m for m in xs]
    return ys, m.por_comprension
"""

NOMBRES = (
    "reexportado",
    "LEIDA",
    "SOLO_AL_IMPORTAR",
    "SOLO_DEFAULT",
    "usado",
    "leido_de_afuera",
    "por_texto",
    "solo_escrito",
    "huerfano",
    "por_relativo",
    "por_cadena",
    "como_clave",
    "por_tabla",
    "SOLO_ASIGNADA",
    "CONTADOR",
    "TAPADA",
    "por_import_local",
    "sumado",
    "por_objeto",
    "por_import_funcion",
    "por_comprension",
    "solo_reexportado",
    "por_reexport",
)


def _limpiar_caches():
    guardia.olvidar()


@pytest.fixture
def lienzo_falso(tmp_path, monkeypatch):
    raiz = tmp_path / "lienzo"
    (raiz / "paq" / "sub").mkdir(parents=True)
    (raiz / "modelo.py").write_text(MODELO, encoding="utf-8")
    (raiz / "otro.py").write_text(OTRO, encoding="utf-8")
    # un modulo que no importa modelo: su texto "huerfano" no salva un parche sobre modelo
    (raiz / "suelto.py").write_text('TABLA = {"huerfano": 1}\n', encoding="utf-8")
    (raiz / "paq" / "__init__.py").write_text("def catalogo():\n    return []\n", encoding="utf-8")
    (raiz / "paq" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "paq" / "sub" / "hijo.py").write_text(
        "from ... import modelo\n\n\ndef f():\n    return modelo.por_relativo\n", encoding="utf-8"
    )
    (raiz / "cadena.py").write_text("import otro\n\n\ndef f():\n    return otro.m.por_cadena\n", encoding="utf-8")
    (raiz / "dinamico.py").write_text(
        'import modelo\n\nNOMBRES = ["por_tabla"]\n\n\ndef f(n):\n    return getattr(modelo, n)\n', encoding="utf-8"
    )
    (raiz / "reexporta.py").write_text(
        'import modelo\n\n_NOMBRES = {"solo_reexportado"}\n\n\ndef __getattr__(n):\n    return getattr(modelo, n)\n',
        encoding="utf-8",
    )
    (raiz / "via.py").write_text("from otro import m\n\n\ndef f():\n    return m.por_reexport\n", encoding="utf-8")
    (raiz / "usa_paq.py").write_text("import paq\n\n\ndef f():\n    return paq.catalogo()\n", encoding="utf-8")
    monkeypatch.setattr(guardia, "LIENZO", raiz)
    _limpiar_caches()
    modulo = types.ModuleType("modelo")
    modulo.__file__ = str(raiz / "modelo.py")
    for nombre in NOMBRES:
        setattr(modulo, nombre, object())
    yield modulo
    _limpiar_caches()


@pytest.mark.parametrize(
    "nombre",
    [
        "usado",
        "LEIDA",
        "leido_de_afuera",
        "por_texto",
        "por_cadena",
        "por_tabla",
        "CONTADOR",
        "por_import_local",
        "sumado",
        "por_import_funcion",
        "por_comprension",
        "por_reexport",
    ],
)
def test_parche_que_el_codigo_lee_pasa(lienzo_falso, nombre):
    assert guardia.parche_sin_efecto(lienzo_falso, nombre) is None


@pytest.mark.parametrize(
    "nombre",
    [
        "reexportado",
        "SOLO_AL_IMPORTAR",
        "SOLO_DEFAULT",
        "solo_escrito",
        "huerfano",
        "como_clave",
        "SOLO_ASIGNADA",
        "TAPADA",
        "por_objeto",
        "solo_reexportado",
    ],
)
def test_parche_que_nadie_lee_al_correr_se_detecta(lienzo_falso, nombre):
    assert "no tiene efecto" in guardia.parche_sin_efecto(lienzo_falso, nombre)


def test_import_relativo_de_dos_niveles_cuenta(lienzo_falso):
    """`from ... import modelo` en paq/sub/hijo.py es el `modelo` de arriba de todo."""
    assert guardia.parche_sin_efecto(lienzo_falso, "por_relativo") is None


def test_paquete_se_nombra_sin_init(lienzo_falso):
    paq = types.ModuleType("paq")
    paq.__file__ = str(guardia.LIENZO / "paq" / "__init__.py")
    paq.catalogo = object()
    assert guardia.parche_sin_efecto(paq, "catalogo") is None


def test_un_modulo_que_se_lee_por_globals_deja_pasar_todo(lienzo_falso):
    (guardia.LIENZO / "tabla.py").write_text("def f(n):\n    return globals()[n]\n", encoding="utf-8")
    tabla = types.ModuleType("tabla")
    tabla.__file__ = str(guardia.LIENZO / "tabla.py")
    tabla.parse_x = object()
    assert guardia.parche_sin_efecto(tabla, "parse_x") is None


def test_monkeypatch_sobre_una_reexportacion_falla(lienzo_falso, monkeypatch):
    """La guardia esta instalada por conftest: parchear lo que el modulo solo reexporta levanta."""
    with pytest.raises(AssertionError, match="no tiene efecto"):
        monkeypatch.setattr(lienzo_falso, "reexportado", lambda: None)
    monkeypatch.setattr(lienzo_falso, "usado", lambda: None)  # el que se lee, pasa


def test_la_forma_de_texto_tambien_se_revisa(lienzo_falso, monkeypatch):
    monkeypatch.setitem(sys.modules, "modelo", lienzo_falso)
    with pytest.raises(AssertionError, match="no tiene efecto"):
        monkeypatch.setattr("modelo.reexportado", lambda: None)
    monkeypatch.setattr("modelo.usado", lambda: None)


def test_un_archivo_que_no_parsea_deja_pasar_y_no_se_recuerda(lienzo_falso):
    """Mientras otra sesion guarda un archivo, la guardia deja pasar; cuando termina, vuelve a mirar
    (antes quedaba apagada toda la sesion de pytest)."""
    a_medias = guardia.LIENZO / "a_medias.py"
    a_medias.write_text("def roto(:\n", encoding="utf-8")
    _limpiar_caches()
    assert guardia.parche_sin_efecto(lienzo_falso, "reexportado") is None
    a_medias.write_text("def sano():\n    return 1\n", encoding="utf-8")
    assert "no tiene efecto" in guardia.parche_sin_efecto(lienzo_falso, "reexportado")


def test_import_dentro_de_una_funcion_del_repo_cuenta():
    """El caso de D (codex_identity.py importa codex_status adentro de una funcion) y los del review."""
    import claude_pipe_runtime
    import codex_observation
    import codex_status

    casos = (
        (codex_status, "discover"),
        (codex_observation, "observe"),
        (codex_status, "request_scan"),
        (claude_pipe_runtime, "register"),
    )
    for modulo, nombre in casos:
        assert guardia.parche_sin_efecto(modulo, nombre) is None, nombre


def test_objetivos_fuera_de_lienzo_no_se_revisan(lienzo_falso):
    assert guardia.parche_sin_efecto(types, "nada_que_ver") is None
    assert guardia.parche_sin_efecto(object(), "x") is None


def test_ningun_modulo_de_lienzo_importa_server():
    assert guardia.importadores_de_server() == []


def test_importar_server_se_detecta_de_todas_las_formas(lienzo_falso):
    formas = {
        "malo1.py": "import server\n",
        "malo2.py": "from . import server\n",
        "malo3.py": "import lienzo.server\n",
        "malo4.py": "from lienzo.server import lock\n",
        "malo5.py": "from lienzo import server\n",
        "malo6.py": "from server import lock\n",
        "malo7.py": "import importlib\n\n\ndef f():\n    return importlib.import_module('server')\n",
        "malo8.py": "def f():\n    return __import__('lienzo.server')\n",
        "malo9.py": "import importlib\n\n\ndef f():\n    return importlib.import_module('.server', 'lienzo')\n",
        "bueno.py": "from rules import server_name\n",
    }
    for nombre, texto in formas.items():
        (guardia.LIENZO / nombre).write_text(texto, encoding="utf-8")
    # el `server` de un subpaquete no es el script de arriba
    (guardia.LIENZO / "paq" / "server.py").write_text("", encoding="utf-8")
    (guardia.LIENZO / "paq" / "usa.py").write_text("from . import server\n", encoding="utf-8")
    _limpiar_caches()
    assert sorted(guardia.importadores_de_server()) == [f"malo{i}.py" for i in range(1, 10)]
