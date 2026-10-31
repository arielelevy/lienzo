"""`limpiar_coordinacion` no borra días de `.temp/coordinacion/` que el repo cita.

Caso real (openSeec, 2026-10): la coordinadora borró días viejos y con ellos el arnés y la evidencia de
una prueba de localidad que citaba un contrato.
"""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c
import pytest

HOY = dt.date(2026, 10, 30)


@pytest.fixture(autouse=True)
def sin_server(monkeypatch):
    """Ninguna prueba habla con el lienzo real: la carpeta no tiene proyecto en la memoria."""
    monkeypatch.setattr(c, "_conocimiento", lambda metodo, ruta, cuerpo=None: {"proyecto": None})


def test_la_carpeta_se_resuelve_sin_crear_el_proyecto(tmp_path, monkeypatch):
    _repo(tmp_path)
    pedidos = []
    monkeypatch.setattr(c, "_conocimiento", lambda m, r, cuerpo=None: pedidos.append((m, r)) or {"proyecto": None})
    r = c.limpiar_coordinacion(tmp_path, dias=7, hoy=HOY)
    assert pedidos[0][0] == "GET" and pedidos[0][1].startswith("/carpeta?cwd=")
    assert r["memoria"] == "la carpeta no tiene proyecto en la memoria"


def _repo(tmp_path):
    base = tmp_path / ".temp" / "coordinacion"
    for dia in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-29"):
        (base / dia).mkdir(parents=True)
        (base / dia / "informe-A.md").write_text("informe\n", encoding="utf-8")
    (base / "2026-10-02" / "arnes").mkdir()
    (base / "2026-10-02" / "arnes" / "localidad.py").write_text("print(1)\n", encoding="utf-8")
    (base / "notas").mkdir()  # no es un día: no se toca
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "contrato.md").write_text(
        "Evidencia: `.temp\\coordinacion\\2026-10-02\\arnes\\localidad.py` (prueba de localidad)\n", encoding="utf-8"
    )
    # una ficha de un día que queda cita a otro día viejo
    (base / "2026-10-29" / "fdd-x.md").write_text("ver .temp/coordinacion/2026-10-03/informe-A.md\n", encoding="utf-8")
    # el día viejo que se cita a sí mismo no se protege por eso
    (base / "2026-10-01" / "informe-A.md").write_text("ver .temp/coordinacion/2026-10-01/x.md\n", encoding="utf-8")
    (tmp_path / "imagen.png").write_bytes(b"\x89PNG\0.temp/coordinacion/2026-10-01")  # binario: no cuenta
    return base


def test_sin_borrar_solo_informa(tmp_path):
    base = _repo(tmp_path)
    r = c.limpiar_coordinacion(tmp_path, dias=7, hoy=HOY)
    assert r["borrables"] == ["2026-10-01"]
    assert sorted(r["protegidos"]) == ["2026-10-02", "2026-10-03"]
    assert r["protegidos"]["2026-10-02"] == ["docs/contrato.md:1"]
    assert r["protegidos"]["2026-10-03"] == [".temp/coordinacion/2026-10-29/fdd-x.md:1"]
    assert r["borrados"] == [] and (base / "2026-10-01").is_dir()


def test_borrar_respeta_la_evidencia_citada(tmp_path):
    base = _repo(tmp_path)
    r = c.limpiar_coordinacion(tmp_path, dias=7, borrar=True, hoy=HOY)
    assert r["borrados"] == ["2026-10-01"]
    assert not (base / "2026-10-01").exists()
    assert (base / "2026-10-02" / "arnes" / "localidad.py").is_file() and (base / "2026-10-03").is_dir()
    assert (base / "2026-10-29").is_dir() and (base / "notas").is_dir()


def test_un_dia_citado_solo_se_borra_con_confirmacion_explicita(tmp_path):
    base = _repo(tmp_path)
    r = c.limpiar_coordinacion(tmp_path, dias=7, borrar=True, confirmar=["2026-10-03"], hoy=HOY)
    assert r["borrados"] == ["2026-10-01", "2026-10-03"]
    assert not (base / "2026-10-03").exists() and (base / "2026-10-02").is_dir()


def test_lo_que_cita_la_memoria_del_proyecto_tambien_protege(tmp_path, monkeypatch):
    base = _repo(tmp_path)
    nodos = [
        {"id": "e1", "tipo": "encargo", "datos": {"ficha": ".temp/coordinacion/2026-10-01/fdd-x.md"}},
        {"id": "v1", "tipo": "evidencia", "texto": "arnés en .temp\\coordinacion\\2026-10-01\\arnes"},
    ]
    pedidos = []

    def conocimiento(metodo, ruta, cuerpo=None):
        pedidos.append(ruta)
        desde = int(ruta.split("desde=")[1])
        return {"total": len(nodos), "desde": desde, "nodos": nodos[desde : desde + 1]}  # de a uno: pagina

    monkeypatch.setattr(c, "_conocimiento", conocimiento)
    r = c.limpiar_coordinacion(tmp_path, dias=7, borrar=True, hoy=HOY, proyecto="app")
    assert r["borrados"] == [] and (base / "2026-10-01").is_dir()
    assert r["protegidos"]["2026-10-01"] == ["memoria app: encargo e1", "memoria app: evidencia v1"]
    assert r["memoria"] == "consultada: 2 nodos" and len(pedidos) == 2


def test_si_la_memoria_no_contesta_no_borra_nada(tmp_path, monkeypatch):
    base = _repo(tmp_path)
    monkeypatch.setattr(c, "_conocimiento", lambda *a: (_ for _ in ()).throw(RuntimeError("0 sin conexión")))
    r = c.limpiar_coordinacion(tmp_path, dias=7, borrar=True, hoy=HOY, proyecto="app")
    assert r["borrados"] == [] and (base / "2026-10-01").is_dir() and "sin conexión" in r["memoria"]


def test_sin_carpeta_de_coordinacion_no_hace_nada(tmp_path):
    assert c.limpiar_coordinacion(tmp_path, hoy=HOY) == {"borrables": [], "protegidos": {}, "borrados": []}
