"""Tanda 1 de PENDIENTES.md (2026-10-10): /health sin datos del usuario antes de autenticar y con las
fuentes del barrido, request_id validado antes de armar la ruta, GET /links con el espejo, el puerto de
peers unificado con el del emparejado y cablear en paralelo."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import backend
import pairing
import sessions as ses


def test_health_sin_autenticar_no_dice_cuantas_sesiones_ni_permisos_hay():
    assert set(server.salud_publica(False)) == {"ok", "ts"}
    completa = server.salud_publica(True)
    assert {"ok", "sessions", "pending", "ts", "fuentes"} <= set(completa)
    assert completa["fuentes"] == backend.fuentes_activas()


def test_fuentes_activas_dice_que_mira_el_barrido(monkeypatch):
    monkeypatch.setattr(backend, "HAS_TMUX", True)
    assert "tmux" in backend.fuentes_activas()
    monkeypatch.setattr(backend, "HAS_TMUX", False)
    assert "tmux" not in backend.fuentes_activas()


def test_request_id_con_barras_o_puntos_no_arma_una_ruta(monkeypatch):
    escritos = []
    monkeypatch.setattr(ses, "atomic_write", lambda path, texto: escritos.append(path))
    for malo in ("../../x", "a/b", "a\\b", "", "x" * 200, None):
        code, res = ses.answer_pending(malo, "allow")
        assert code == 400 and "invalido" in res["error"]
    assert escritos == []
    # un id bien formado que no esta pendiente sigue siendo 410, como siempre
    assert ses.answer_pending("abc-123_DEF", "allow")[0] == 410


def test_get_links_suma_las_del_espejo(monkeypatch):
    monkeypatch.setattr(server.links, "snapshot", lambda: [{"id": "l1", "pc": "a"}])
    monkeypatch.setattr(server.mirror.MIRROR, "links", lambda: [{"id": "l2", "pc": "b"}])
    assert [x["id"] for x in server.links.snapshot() + server.mirror.MIRROR.links()] == ["l1", "l2"]


def test_el_puerto_de_peers_por_defecto_es_el_que_anuncia_el_emparejado(monkeypatch):
    monkeypatch.setenv("LIENZO_PEER_PORT", "7442")
    assert pairing._my_port() == 7442
    monkeypatch.delenv("LIENZO_PEER_PORT")
    assert pairing._my_port() == pairing.PEER_PORT


def test_cablear_crea_las_reglas_en_paralelo(monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "coord_tanda1", Path(__file__).parents[1] / "skills/lienzo/coordinar.py"
    )
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    c.YO = "coord"
    tarjetas = [{"session_id": f"s{i}", "alive": True, "title": f"t{i}"} for i in range(6)]
    en_vuelo, maximo, lock = [0], [0], threading.Lock()

    def pedir(metodo, ruta, cuerpo=None, timeout=20):
        if metodo == "GET":
            return 200, []
        with lock:
            en_vuelo[0] += 1
            maximo[0] = max(maximo[0], en_vuelo[0])
        time.sleep(0.2)  # una PC lenta
        with lock:
            en_vuelo[0] -= 1
        return (503, {"error": "caida"}) if cuerpo["from"] == "s3" else (200, {"id": "r"})

    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: tarjetas)
    t0 = time.monotonic()
    out = c.cablear()
    assert time.monotonic() - t0 < 0.9  # en serie serian 1,2 s
    assert maximo[0] > 1
    assert sorted(out["creadas"]) == ["s0", "s1", "s2", "s4", "s5"]
    assert [f["sid"] for f in out["fallaron"]] == ["s3"]
