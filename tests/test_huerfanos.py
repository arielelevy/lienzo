"""Continuidad con relaciones explícitas; no toca consolas ni mata sesiones reales."""

import http.client
import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import auditoria
import huerfanos as h
import pytest
import server


def card(sid, **kw):
    return {
        "session_id": sid,
        "repo_key": "r",
        "repo": "proyecto",
        "alive": True,
        "state": "termino",
        "pc": "local",
        **kw,
    }


def rule(src, dst, **kw):
    return {"id": src + dst, "kind": "on_stop", "from": src, "to": dst, "enabled": True, **kw}


@pytest.mark.parametrize(
    "vieja", [[], [card("old", alive=False)], [card("old", state="muerta")], [card("old", pc="offline")]]
)
def test_elegir_ante_cierre_muerte_y_pc_caida(vieja):
    ss = [card("B"), card("A"), *vieja]
    rs = [rule("A", "old"), rule("B", "old")]
    esperado = [{"session_id": "A", "repo": "r", "old": ["old"]}]
    assert h.planes(ss, [], rs, {"offline"}) == esperado
    assert h.planes(list(reversed(ss)), [], list(reversed(rs)), {"offline"}) == esperado


@pytest.mark.parametrize("kw", [{"coordinator": True}, {"coordinator": True, "pc": "remote"}])
def test_no_reemplaza_coordinadora_viva(kw):
    assert h.planes([card("A"), card("C", **kw)], [], [rule("A", "old")], set()) == []


def test_lanzador_de_otro_repo_y_sin_parentesco_no_promueve():
    ln = [{"kind": "send", "from": "old", "to": "B"}]
    assert h.planes([card("A"), card("B")], ln, [], set())[0]["session_id"] == "B"
    assert h.planes([card("B"), card("old", repo_key="otro", coordinator=True)], ln, [], set()) == []
    assert h.planes([card("A")], [], [], set()) == []


def test_encargo_viejo_no_reemplaza_relacion_actual_viva():
    ss = [card("A"), card("nuevo", repo_key="otro")]
    ln = [
        {"kind": "send", "from": "old", "to": "A", "ts": "2026-10-20"},
        {"kind": "send", "from": "nuevo", "to": "A", "ts": "2026-10-25"},
    ]
    assert h.planes(ss, ln, [], set()) == []
    assert h.planes(ss, [], [rule("A", "old"), rule("A", "nuevo")], set()) == []


@pytest.mark.parametrize(
    "sid,kw", [("A", {"stopped_by": "x"}), ("A", {"external": {"kind": "headless"}}), ("pid-5", {}), ("tmux-5", {})]
)
def test_excluye_frentes_no_elegibles(sid, kw):
    assert h.planes([card(sid, **kw)], [], [rule(sid, "old")], set()) == []


def test_recableado_solo_on_stop_del_repo_sin_autoenvio():
    ss = [card("A"), card("B"), card("X", repo_key="otro")]
    rs = [
        rule("A", "old"),
        rule("B", "old", enabled=False, parked_to="old", parked_was_enabled=True),
        rule("X", "old"),
        rule("B", "old", kind="at"),
        rule("B", "old", enabled=False),
    ]
    assert h.recablear(rs, ss, "old", "A", "r") == 3
    assert rs[0]["to"] == "A" and rs[0]["enabled"] is False
    assert rs[1]["to"] == "A" and rs[1]["enabled"] is True and "parked_to" not in rs[1]
    assert rs[2]["to"] == "old" and rs[3]["to"] == "old"
    assert rs[4]["to"] == "A" and rs[4]["enabled"] is False
    assert h.recablear(rs, ss, "old", "A", "r") == 0


@pytest.fixture
def entorno(monkeypatch):
    ss = {x: card(x) for x in "AB"}
    rs = [rule("A", "old"), rule("B", "old")]
    espejo = SimpleNamespace(peers_status=list, all_synced=lambda: True, sessions=list, links=list, rules=list)
    monkeypatch.setattr(server.mirror, "MIRROR", espejo)
    monkeypatch.setattr(server, "sessions", ss)
    monkeypatch.setattr(server.identity, "pc_id", lambda: "local")
    monkeypatch.setattr(server.links, "items", [])
    monkeypatch.setattr(server.rules, "items", rs)
    monkeypatch.setattr(server.rules, "save", lambda: None)
    monkeypatch.setattr(server.rules, "publish", lambda: None)
    monkeypatch.setattr(server, "touch", lambda s: None)
    monkeypatch.setattr(server, "set_coordinator", lambda s, on, **kw: [])
    monkeypatch.setattr(server.ses, "find_session", lambda sid: ss.get(sid))
    monkeypatch.setattr(server, "fan_out", lambda *a, **kw: ({}, {}))
    avisos = []
    monkeypatch.setattr(server, "send_to_session", lambda s, texto, adj: (avisos.append(s["session_id"]) or 200, {}))
    return ss, rs, espejo, avisos


def test_accion_revalida_promueve_titula_y_recablea(entorno):
    ss, rs, _, avisos = entorno
    assert server.accion_huerfano(ss["B"], {})[0] == 409  # snapshot del llamador desactualizado
    code, out = server.accion_huerfano(ss["A"], {})
    assert code == 200 and out["pending"] == []
    assert ss["A"]["coordinator"] and "coordinadora" in ss["A"]["title"]
    assert all(r["to"] == "A" for r in rs)
    assert rs[0]["enabled"] is False and avisos == ["A"]
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert avisos == ["A"]


def test_no_toma_control_sin_snapshot_inicial(entorno):
    ss, _, espejo, _ = entorno
    espejo.peers_status = lambda: [{"pc_id": "remote", "alive": True}]
    espejo.all_synced = lambda: False
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert not ss["A"].get("coordinator")


def test_reintenta_recableado_remoto_sin_repetir_aviso(entorno, monkeypatch):
    ss, _, _, avisos = entorno
    monkeypatch.setattr(server, "fan_out", lambda *a, **kw: ({}, {"remote": "caida"}))
    assert server.accion_huerfano(ss["A"], {})[1]["pending"] == ["old"]
    assert h.planes(list(ss.values()), [], [], set())[0]["old"] == ["old"]
    monkeypatch.setattr(server, "fan_out", lambda *a, **kw: ({}, {}))
    assert server.accion_huerfano(ss["A"], {})[1]["pending"] == []
    assert avisos == ["A"]


def test_auditoria_solo_pide_traspaso_en_pc_elegida(monkeypatch):
    ss = [card("B"), card("A", pc="remote")]
    rutas = {"/rules": [rule("A", "old"), rule("B", "old")], "/links": []}
    monkeypatch.setattr(auditoria, "_get", lambda base, path: rutas[path])
    enviados = []
    monkeypatch.setattr(auditoria, "_post", lambda base, path, body: enviados.append((path, body)))
    auditoria.recuperar_huerfanos("http://fixture", deepcopy(ss), [], "local")
    assert enviados == []
    auditoria.recuperar_huerfanos("http://fixture", ss, [], "remote")
    assert enviados == [("/sessions/A/orphan", {})]


def test_aviso_fallido_se_reintenta_sin_repetir_traspaso(entorno, monkeypatch):
    ss, _, _, avisos = entorno
    monkeypatch.setattr(server, "send_to_session", lambda *a: (409, {"error": "dialogo"}))
    server.accion_huerfano(ss["A"], {})
    assert ss["A"]["orphaned_notice_pending"] is True
    assert h.planes(list(ss.values()), [], [], set())[0]["old"] == []
    monkeypatch.setattr(server, "send_to_session", lambda s, *a: (avisos.append(s["session_id"]) or 200, {}))
    assert server.accion_huerfano(ss["A"], {})[0] == 200
    assert avisos == ["A"] and ss["A"]["orphaned_notice_pending"] is False


def test_frente_restaurado_recupera_destino_de_coordinadora_nueva(entorno):
    ss, rs, _, avisos = entorno
    server.accion_huerfano(ss["A"], {})
    ss["C"] = card("C")
    rs.append(rule("C", "old", enabled=False, parked_to="old", parked_was_enabled=True))
    assert h.planes(list(ss.values()), [], rs, set())[0]["old"] == ["old"]
    assert server.accion_huerfano(ss["A"], {})[0] == 200
    assert rs[-1]["to"] == "A" and rs[-1]["enabled"] is True
    assert avisos == ["A"]


def test_pc_confirmada_caida_permite_traspaso_aunque_no_haya_snapshot(entorno):
    ss, _, espejo, _ = entorno
    espejo.peers_status = lambda: [{"pc_id": "remote", "alive": False, "diagnostico": "sin conexion"}]
    espejo.all_synced = lambda: False
    assert server.accion_huerfano(ss["A"], {})[0] == 200


def test_ruta_http_real_promueve_sin_tocar_consolas(entorno, monkeypatch):
    ss, rs, _, avisos = entorno
    monkeypatch.setattr(server.Handler, "_authed", lambda self: True)
    monkeypatch.setattr(server, "_route_session", lambda sid: (ss.get(sid), None))
    monkeypatch.setattr(server, "log", lambda *a: None)
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection(*srv.server_address, timeout=3)
    try:
        client.request("POST", "/sessions/A/orphan", "{}", {"X-Lienzo": "1", "Content-Type": "application/json"})
        res = client.getresponse()
        body = json.loads(res.read())
        assert res.status == 200 and body["coordinator"] is True
        assert ss["A"]["coordinator"] is True and rs[1]["to"] == "A" and avisos == ["A"]
    finally:
        client.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def comportamiento(entorno):
    ss, rs, _, _ = entorno
    ss["C"] = card("C")
    ss["A"]["title"] = "titulo elegido por Ariel"
    rs[:] = [rule("B", "A"), rule("C", "A")]
    server.links.items[:] = [{"kind": "send", "from": "A", "to": x} for x in "BC"]
    return ss, rs


def test_coordinadora_de_hecho_unica_se_marca_sin_pisar_titulo(entorno):
    ss, _ = comportamiento(entorno)
    assert server.accion_huerfano(ss["A"], {})[1]["coordinator"] is True
    assert ss["A"]["coordinator_inferred"] == {"informes": 2, "frentes": 2}
    assert ss["A"]["title"] == "titulo elegido por Ariel"
    assert ss["A"]["coordinator_proposal"]["kind"] == "title"
    assert entorno[3] == []  # reconocer su rol no despierta un modelo


@pytest.mark.parametrize("parte", ["reglas", "envios", "repo", "apagada"])
def test_no_infiere_con_duplicados_o_fuera_del_repo(entorno, parte):
    ss, rs = comportamiento(entorno)
    if parte == "reglas":
        rs[1] = dict(rs[0])
    elif parte == "envios":
        server.links.items[1] = dict(server.links.items[0])
    elif parte == "repo":
        ss["C"]["repo_key"] = "otro"
    else:
        rs[1]["enabled"] = False
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert not ss["A"].get("coordinator")


def test_dos_candidatas_solo_proponen_y_luego_limpian_propuesta(entorno):
    ss, rs = comportamiento(entorno)
    ss["D"] = card("D")
    rs.extend([rule("B", "D"), rule("C", "D")])
    server.links.items.extend({"kind": "send", "from": "D", "to": x} for x in "BC")
    assert server.accion_huerfano(ss["A"], {})[1]["proposal"] is True
    assert server.accion_huerfano(ss["D"], {})[1]["proposal"] is True
    assert not any(s.get("coordinator") for s in ss.values())
    ss["D"]["coordinator"] = True  # una persona eligió otra; no debe seguir proponiendo A
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert "coordinator_proposal" not in ss["A"]


def test_descartar_propuesta_se_respeta_en_rondas_siguientes(entorno):
    ss, rs = comportamiento(entorno)
    rs.append(rule("A", "old"))  # tampoco usar el camino de huérfanos para imponer el rol rechazado
    assert server.accion_huerfano(ss["A"], {"dismiss_proposal": True})[0] == 200
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert ss["A"]["coordinator_declined"] is True


def test_coordinadora_viva_impide_inferencia(entorno):
    ss, _ = comportamiento(entorno)
    ss["D"] = card("D", coordinator=True, pc="remote")
    assert server.accion_huerfano(ss["A"], {})[0] == 409


def test_quitar_rol_manual_impide_remarcar(entorno):
    ss, _ = comportamiento(entorno)
    server.accion_huerfano(ss["A"], {})
    ss["A"]["coordinator"] = False  # set_coordinator es fixture en este entorno
    server.accion_coordinator(ss["A"], {"on": False})
    assert server.accion_huerfano(ss["A"], {})[0] == 409


def test_decision_manual_durante_deteccion_tiene_prioridad(entorno, monkeypatch):
    ss, _ = comportamiento(entorno)

    def quitar(s, on, **kw):
        s.update(coordinator=False, coordinator_declined=True)
        return []

    monkeypatch.setattr(server, "set_coordinator", quitar)
    assert server.accion_huerfano(ss["A"], {})[0] == 409
    assert not ss["A"]["coordinator"]


def test_guardia_atomica_no_pisa_rol_retirado_manualmente(monkeypatch):
    s = card("A", coordinator=False, coordinator_declined=True)
    monkeypatch.setattr(server.ses, "sessions", {"A": s})
    monkeypatch.setattr(server.ses, "touch", lambda s: None)
    monkeypatch.setattr(server.ses, "_mirror_sessions", list)
    assert server.ses.set_coordinator(s, True, automatic=True) == []
    assert s["coordinator"] is False
    server.ses.set_coordinator(s, True)  # una elección explícita sigue permitida
    assert s["coordinator"] is True
