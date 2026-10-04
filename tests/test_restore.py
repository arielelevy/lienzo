"""Restaurar sesiones tras un reinicio de PC: lienzo/restore.py (registro en ~/.lienzo/restaurar.json,
siempre en una ruta temporal: ver el fixture autouse de conftest.py), los ganchos de sessions.py
(drop_session, load_sessions, el barrido de liveness), launch.launch(resume=...) y las rutas de
server.py (GET /restaurables, POST /restaurar y sus espejos /peer/...)."""

import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001, F811
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server
import launch
import mirror
import restore
import sessions as ses
import state as st
from test_launch import FakePopen, aislado as aislado_launch, con_roots  # noqa: F401
from test_server import _TransporteFalso, _espejo_con

UUID = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
UUID2 = "1b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """Registro de sesiones y de restaurables aislados; carpeta de trabajo real para los cwd."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    os.makedirs(st.SESSIONS)
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(server, "log", lambda msg: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    monkeypatch.setattr(server.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(restore.identity, "pc_id", lambda: "pcA")
    monkeypatch.setattr(restore.state, "LIENZO", str(tmp_path))
    monkeypatch.setattr(restore, "path", lambda: str(tmp_path / "restaurar.json"))
    st.sessions.clear()
    st.transcript_stat.clear()
    st.links.items.clear()
    st.rules.items.clear()
    (tmp_path / "cwd").mkdir()
    yield tmp_path
    st.sessions.clear()
    st.transcript_stat.clear()


def card(reg, sid=UUID, agent="claude", **k) -> dict:
    s = ses.new_session(sid, agent, "hook")
    s.update({"cwd": str(reg / "cwd"), "repo": "cwd", "title": "mi sesion", "pc": "pcA", "hooked": True, **k})
    return s


def archivo(reg) -> list:
    with open(reg / "restaurar.json", encoding="utf-8") as f:
        return json.load(f)


# --- remember: solo lo que se puede relanzar ---------------------------------------------------


def test_remember_guarda_los_campos(reg):
    assert restore.remember(card(reg)) is True
    (e,) = restore.restorables()
    assert {k: e[k] for k in ("session_id", "agent", "cwd", "title", "repo", "pc")} == {
        "session_id": UUID,
        "agent": "claude",
        "cwd": str(reg / "cwd"),
        "title": "mi sesion",
        "repo": "cwd",
        "pc": "pcA",
    }
    assert e["saved_at"] and e["ended_at"]


def test_remember_filtra_lo_que_no_corresponde(reg):
    assert not restore.remember(card(reg, agent="gemini"))
    assert not restore.remember(card(reg, cwd=None))
    assert not restore.remember(card(reg, cwd=str(reg / "no-existe")))
    assert not restore.remember(card(reg, cwd=str(reg / "restaurar.json-no")))
    assert not restore.remember(card(reg, sid="pid-123"))  # claude sin id de verdad
    assert not restore.remember(card(reg, sid="pid-123", agent="codex"))
    assert not restore.remember(card(reg, sid="no-es-uuid"))
    assert restore.restorables() == []
    assert not os.path.exists(reg / "restaurar.json")


def test_remember_pi_y_coda_alcanzan_con_el_cwd_y_pid_no_se_duplica(reg):
    assert restore.remember(card(reg, sid="pid-100", agent="pi"))
    assert restore.remember(card(reg, sid="pid-200", agent="pi"))  # otro arranque, misma carpeta
    assert restore.remember(card(reg, sid="pid-300", agent="coda"))
    ids = sorted(e["session_id"] for e in restore.restorables())
    assert ids == ["pid-200", "pid-300"]


def test_forget(reg):
    restore.remember(card(reg))
    assert restore.forget(UUID) is True and restore.forget(UUID) is False
    assert restore.restorables() == []


def test_list_mas_nuevas_primero_y_excluye_las_vivas(reg):
    restore.remember(card(reg, sid=UUID))
    restore.remember(card(reg, sid=UUID2))
    assert [e["session_id"] for e in restore.restorables()] == [UUID2, UUID]
    assert [e["session_id"] for e in restore.restorables(live={UUID2})] == [UUID]


# --- poda --------------------------------------------------------------------------------------


def _escribir(reg, entradas):
    with open(reg / "restaurar.json", "w", encoding="utf-8") as f:
        json.dump(entradas, f)


def _e(i, dias=0.0):
    t = (dt.datetime.now().astimezone() - dt.timedelta(days=dias)).isoformat()
    return {
        "session_id": f"pid-{i}",
        "agent": "pi",
        "cwd": "x",
        "title": None,
        "repo": "x",
        "pc": "pcA",
        "saved_at": t,
        "ended_at": t,
    }


def test_poda_de_mas_de_7_dias(reg):
    _escribir(reg, [_e(1, dias=8), _e(2, dias=6.9), _e(3)])
    assert sorted(e["session_id"] for e in restore.restorables()) == ["pid-2", "pid-3"]
    restore.remember(card(reg))  # al escribir, la poda queda en el archivo
    assert "pid-1" not in {e["session_id"] for e in archivo(reg)}


def test_poda_tope_de_200_se_queda_con_las_mas_nuevas(reg):
    _escribir(reg, [_e(i, dias=i / 100) for i in range(250)])
    restore.remember(card(reg))
    en_disco = archivo(reg)
    assert len(en_disco) == restore.MAX_ENTRIES
    ids = {e["session_id"] for e in en_disco}
    assert UUID in ids and "pid-0" in ids and "pid-249" not in ids


def test_escritura_atomica_no_deja_tmp(reg):
    restore.remember(card(reg))
    assert [n for n in os.listdir(reg) if n.endswith(".tmp")] == []


# --- ganchos de sessions.py --------------------------------------------------------------------


def test_drop_session_por_muerte_recuerda(reg):
    s = card(reg, state="muerta", alive=False, last_event="Stop")
    st.sessions[UUID] = s
    ses.drop_session(UUID, "muerta hace mas de 60 s", muerta=True)
    assert UUID not in st.sessions
    (e,) = restore.restorables()
    assert e["session_id"] == UUID and e["ended_at"]


@pytest.mark.parametrize(
    "reason", ["borrada desde la UI", "borrada desde otra PC", "continuada", "duplicada por barrido"]
)
def test_drop_session_por_otra_razon_olvida(reg, reason):
    restore.remember(card(reg), ended=False)
    st.sessions[UUID] = card(reg)
    ses.drop_session(UUID, reason)
    assert restore.restorables() == []


def test_drop_session_de_agente_desconocido_no_guarda(reg):
    st.sessions[UUID] = card(reg, agent="gemini")
    ses.drop_session(UUID, "muerta hace mas de 60 s", muerta=True)
    assert restore.restorables() == []


@pytest.mark.parametrize("reason", ["exit", "logout", "prompt_input_exit", "clear", "resume"])
def test_sessionend_a_proposito_no_queda_restaurable(reg, reason):
    # estaba guardada de forma incremental, viva; el usuario escribe /exit: el SessionEnd la borra
    restore.remember(card(reg), ended=False)
    ses.apply_event(
        {
            "hook_event_name": "SessionEnd",
            "session_id": UUID,
            "agent": "claude",
            "reason": reason,
            "cwd": str(reg / "cwd"),
        }
    )
    s = st.sessions[UUID]
    assert s["state"] == "muerta" and s["end_reason"] == reason
    ses.drop_session(UUID, "muerta hace mas de 60 s", muerta=True)
    assert restore.restorables() == []


@pytest.mark.parametrize("reason", ["other", None])
def test_sessionend_other_o_sin_razon_si_queda_restaurable(reg, reason):
    ev = {"hook_event_name": "SessionEnd", "session_id": UUID, "agent": "claude", "cwd": str(reg / "cwd")}
    if reason:
        ev["reason"] = reason
    ses.apply_event(ev)
    ses.drop_session(UUID, "muerta hace mas de 60 s", muerta=True)
    assert [e["session_id"] for e in restore.restorables()] == [UUID]


def test_sessionstart_limpia_la_razon_de_la_vida_anterior(reg):
    ses.apply_event({"hook_event_name": "SessionEnd", "session_id": UUID, "agent": "claude", "reason": "exit"})
    ses.apply_event({"hook_event_name": "SessionStart", "session_id": UUID, "agent": "claude"})
    assert st.sessions[UUID]["end_reason"] is None


def test_liveness_guarda_las_vivas_con_hooks_con_debounce(reg, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(restore, "_clock", lambda: t[0])
    st.sessions[UUID] = card(reg, alive=True)
    st.sessions[UUID2] = card(reg, sid=UUID2, alive=True, hooked=False)  # sin hooks: no
    ses.remember_live_cards()
    assert [e["session_id"] for e in archivo(reg)] == [UUID]
    assert archivo(reg)[0]["ended_at"] is None  # viva: todavia no murio
    # dentro de los 30 s no mira de nuevo aunque cambie el titulo
    st.sessions[UUID]["title"] = "otro"
    t[0] += 10
    ses.remember_live_cards()
    assert archivo(reg)[0]["title"] == "mi sesion"
    t[0] += 25
    ses.remember_live_cards()
    assert archivo(reg)[0]["title"] == "otro"


def test_liveness_no_guarda_las_que_terminaron_a_proposito(reg):
    restore.remember(card(reg), ended=False)
    st.sessions[UUID] = card(reg, alive=True, last_event="SessionEnd", end_reason="exit")
    ses.remember_live_cards()
    assert [e["session_id"] for e in archivo(reg)] == [UUID]  # lo viejo no se toca aca; lo borra drop/start


def test_load_sessions_deja_registro_de_las_muertas_y_de_las_vivas(reg, monkeypatch):
    vivas = {UUID2}
    monkeypatch.setattr(ses.backend, "agent_alive", lambda d: d["session_id"] in vivas)
    muerta = card(reg, alive=True, state="termino", last_event="Stop", last_event_ts=st.now(), pid=5)
    viva = card(reg, sid=UUID2, alive=True, state="termino", last_event="Stop", last_event_ts=st.now(), pid=6)
    salio = card(
        reg,
        sid="2b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
        alive=True,
        last_event="SessionEnd",
        end_reason="exit",
        last_event_ts=st.now(),
        pid=7,
    )
    for s in (muerta, viva, salio):
        with open(os.path.join(st.SESSIONS, f"{s['session_id']}.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)
    ses.load_sessions()
    por_id = {e["session_id"]: e for e in archivo(reg)}
    assert set(por_id) == {UUID, UUID2}
    assert por_id[UUID]["ended_at"] and por_id[UUID2]["ended_at"] is None


# --- launch.launch(resume=...) -----------------------------------------------------------------


def _cuerpo(res) -> str:
    with open(res["cmd_path"], encoding="cp1252") as f:
        return f.read()


@pytest.mark.parametrize(
    "agent,final",
    [("claude", f" --resume {UUID}"), ("codex", f" resume {UUID}"), ("pi", " --resume"), ("coda", " --lastsession")],
)
def test_resume_agrega_el_retomar_de_cada_agente(aislado_launch, monkeypatch, agent, final):
    root = aislado_launch / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", agent, resume=UUID)
    assert res["ok"] is True and res["resumed"] is True
    exe = os.path.join(st.HOME, ".local", "bin", launch.AGENT_EXES[agent])
    assert _cuerpo(res).endswith(f'"{exe}"{final}\n')
    with open(res["cmd_path"], "rb") as f:
        assert f.read().endswith(f'"{exe}"{final}\r\n'.encode("cp1252"))


def test_sin_resume_no_cambia_nada_ni_agrega_la_marca(aislado_launch, monkeypatch):
    root = aislado_launch / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "claude")
    assert set(res) == {"ok", "cmd_path"} and _cuerpo(res).splitlines()[-1].endswith('claude.exe"')


MALOS = [
    "x & calc",
    f"{UUID} & calc",
    f"{UUID}\r\ncalc",
    f"{UUID}%PATH%",
    'a"b-c-d-e-f-0123',
    f"{UUID}|calc",
    "pid-123",
    "abc",
    "g" * 12,
    "a" * 41,
    "",
]


@pytest.mark.parametrize("malo", MALOS)
@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_resume_invalido_lanza_sin_retomar_y_nunca_lo_interpola(aislado_launch, monkeypatch, malo, agent):
    root = aislado_launch / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", agent, resume=malo)
    assert res["ok"] is True and res["resumed"] is False
    cuerpo = _cuerpo(res)
    exe = os.path.join(st.HOME, ".local", "bin", launch.AGENT_EXES[agent])
    assert cuerpo.splitlines()[-1] == f'"{exe}"' and "calc" not in cuerpo and "%PATH%" not in cuerpo


def test_resume_de_pi_ignora_el_id_y_no_lo_escribe(aislado_launch, monkeypatch):
    root = aislado_launch / "repos"
    con_roots(monkeypatch, root)
    res = launch.launch(str(root / "p"), "t", "pi", resume="x & calc")
    assert res["resumed"] is True and "calc" not in _cuerpo(res)


def test_resume_respeta_launch_roots(aislado_launch, monkeypatch):
    con_roots(monkeypatch, aislado_launch / "repos")
    res = launch.launch(str(aislado_launch / "otra"), "t", "claude", resume=UUID)
    assert res == {"ok": False, "error": "cwd fuera de launch_roots"} and FakePopen.calls == []


def test_resume_en_tmux_va_como_argumentos_separados(aislado_launch, monkeypatch):
    root = aislado_launch / "repos"
    con_roots(monkeypatch, root)
    monkeypatch.setattr(launch, "WINDOWS", False)
    monkeypatch.setattr(launch, "_exe_path", lambda n: "/usr/bin/" + n)
    res = launch.launch(str(root / "p"), "t", "codex", resume=UUID)
    assert res["ok"] is True and res["resumed"] is True
    assert FakePopen.calls[0][-3:] == ["/usr/bin/codex", "resume", UUID]
    FakePopen.calls.clear()
    res = launch.launch(str(root / "p"), "t", "claude", resume="x & calc")
    assert res["resumed"] is False and FakePopen.calls[0][-1] == "/usr/bin/claude"


# --- restore_local / rutas ---------------------------------------------------------------------


@pytest.fixture
def lanzador(reg, monkeypatch):
    """launch.launch falso: anota cada pedido; el sleep entre relanzados tambien."""
    llamadas, pausas = [], []
    resultados = {}

    def falso(cwd, title, agent, resume=None):
        llamadas.append((cwd, title, agent, resume))
        return resultados.get(resume, {"ok": True, "resumed": True})

    monkeypatch.setattr(server.launch, "launch", falso)
    monkeypatch.setattr(server.time, "sleep", lambda s: pausas.append(s))
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": 32.0})
    return SimpleNamespace(llamadas=llamadas, pausas=pausas, resultados=resultados)


def guardar(reg, n):
    ids = [f"{i:08x}-4f50-4a6b-8c7d-9e0f1a2b3c4d" for i in range(1, n + 1)]
    for sid in ids:
        restore.remember(card(reg, sid=sid))
    return ids


def test_restaurar_una_la_relanza_y_la_olvida(reg, lanzador):
    ids = guardar(reg, 2)
    code, res = server.restore_local({"session_id": ids[0]})
    assert code == 200 and res["failed"] == []
    assert [r["session_id"] for r in res["restored"]] == [ids[0]]
    assert lanzador.llamadas == [(str(reg / "cwd"), "mi sesion", "claude", ids[0])]
    assert [e["session_id"] for e in restore.restorables()] == [ids[1]]


def test_restaurar_todas_una_por_una_con_pausa_y_cuenta_los_fallos(reg, lanzador):
    ids = guardar(reg, 3)
    lanzador.resultados[ids[1]] = {"ok": False, "error": "cwd fuera de launch_roots"}
    code, res = server.restore_local({"all": True})
    assert code == 200
    assert sorted(r["session_id"] for r in res["restored"]) == sorted([ids[0], ids[2]])
    assert res["failed"] == [{"session_id": ids[1], "error": "cwd fuera de launch_roots"}]
    assert lanzador.pausas == [server.RESTORE_GAP_S, server.RESTORE_GAP_S] and server.RESTORE_GAP_S >= 2
    assert [e["session_id"] for e in restore.restorables()] == [ids[1]]  # la fallida queda para reintentar


def test_restaurar_pide_session_id_o_all_y_desconocida_es_404(reg, lanzador):
    assert server.restore_local({})[0] == 400
    assert server.restore_local({"all": True, "session_id": UUID})[0] == 400
    assert server.restore_local({"session_id": 5})[0] == 400
    assert server.restore_local({"session_id": UUID})[0] == 404
    assert lanzador.llamadas == []


def test_restaurar_no_toca_las_que_hoy_estan_vivas(reg, lanzador):
    (sid,) = guardar(reg, 1)
    st.sessions[sid] = card(reg, sid=sid, alive=True, state="corriendo")
    code, res = server.restore_local({"all": True})
    assert code == 200 and res["restored"] == [] and lanzador.llamadas == []


def test_all_respeta_la_memoria_y_dice_cuantas_entran(reg, lanzador, monkeypatch):
    guardar(reg, 5)
    # 1.5 + 0.7*5 = 5.0 GB hacen falta: con 3.0 entran int((3.0-1.5)/0.7) = 2
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": 3.0})
    code, res = server.restore_local({"all": True})
    assert code == 409 and res["fit"] == 2 and res["restorable"] == 5
    assert "entran 2" in res["error"] and lanzador.llamadas == []
    assert len(restore.restorables()) == 5


def test_all_con_limit_by_memory_relanza_solo_las_que_entran(reg, lanzador, monkeypatch):
    ids = guardar(reg, 5)
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": 3.0})
    code, res = server.restore_local({"all": True, "limit_by_memory": True})
    assert code == 200 and len(res["restored"]) == 2 and len(res["skipped"]) == 3
    assert len(lanzador.llamadas) == 2 and len(restore.restorables()) == 3
    assert set(res["skipped"]) <= set(ids)


def test_all_sin_memoria_ni_para_una_se_rechaza_aun_con_limit(reg, lanzador, monkeypatch):
    guardar(reg, 2)
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": 1.0})
    code, res = server.restore_local({"all": True, "limit_by_memory": True})
    assert code == 409 and res["fit"] == 0 and lanzador.llamadas == []


def test_all_con_memoria_justa_y_sin_dato_de_memoria(reg, lanzador, monkeypatch):
    guardar(reg, 2)
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": 2.9})  # 1.5+1.4 = 2.9: entran 2
    assert server.restore_local({"all": True})[0] == 200
    guardar(reg, 2)
    monkeypatch.setattr(server.health, "snapshot", lambda: {"mem_free_gb": None})
    assert server.restore_local({"all": True})[0] == 200


def test_una_restauracion_en_curso_rechaza_a_la_segunda(reg, lanzador):
    guardar(reg, 1)
    assert server._restore_busy.acquire(blocking=False)
    try:
        assert server.restore_local({"all": True})[0] == 409
    finally:
        server._restore_busy.release()


class _Handler:
    """Lo minimo de Handler para probar _restaurar sin sockets."""

    def __init__(self, body):
        self.body, self.out = body, None

    def _json_body(self):
        return self.body

    def _json(self, code, res, headers=None):
        self.out = (code, res)


def test_restaurar_de_otra_pc_se_reenvia_al_peer(reg, lanzador, monkeypatch):
    t = _TransporteFalso([(200, {"restored": [{"session_id": UUID}], "failed": []})])
    m, _ = _espejo_con(t)
    monkeypatch.setattr(mirror, "MIRROR", m)
    h = _Handler({"session_id": UUID, "pc": "pcB", "limit_by_memory": True, "basura": 1})
    server.Handler._restaurar(h)
    assert h.out == (200, {"restored": [{"session_id": UUID}], "failed": []})
    assert t.llamadas == [("POST", "/peer/restaurar")] and lanzador.llamadas == []


def test_restaurar_con_mi_pc_o_sin_pc_corre_local(reg, lanzador):
    ids = guardar(reg, 1)
    for pc in (None, "pcA"):
        h = _Handler({"session_id": ids[0], **({"pc": pc} if pc else {})})
        server.Handler._restaurar(h)
        assert h.out[0] in (200, 404)
    assert len(lanzador.llamadas) == 1


def test_restaurar_peer_caido_devuelve_503(reg, lanzador, monkeypatch):
    t = _TransporteFalso([ConnectionRefusedError(), ConnectionRefusedError()])
    m, _ = _espejo_con(t)
    monkeypatch.setattr(mirror, "MIRROR", m)
    monkeypatch.setattr(mirror.time, "sleep", lambda s: None)
    h = _Handler({"all": True, "pc": "pcB"})
    server.Handler._restaurar(h)
    assert h.out[0] == 503


def test_restaurables_junta_las_locales_y_las_de_peers_vivos(reg, monkeypatch):
    restore.remember(card(reg))
    remota = {"session_id": UUID2, "agent": "codex", "cwd": "C:/x", "ended_at": st.now(), "saved_at": st.now()}
    t = _TransporteFalso([(200, {"restaurables": [remota]})])
    m, pm = _espejo_con(t)
    pm.last_seen = __import__("time").time()
    monkeypatch.setattr(mirror, "MIRROR", m)
    res = server.restorables_all()
    assert {(e["session_id"], e["pc"]) for e in res} == {(UUID, "pcA"), (UUID2, "pcB")}
    assert t.llamadas == [("GET", "/peer/restaurables")]


def test_restaurables_ignora_peer_muerto(reg, monkeypatch):
    t = _TransporteFalso([])
    m, pm = _espejo_con(t)  # last_seen en 0: no esta vivo
    monkeypatch.setattr(mirror, "MIRROR", m)
    assert server.restorables_all() == [] and t.llamadas == []


def test_peer_handler_expone_las_rutas_espejo(reg, lanzador):
    (sid,) = guardar(reg, 1)
    h = SimpleNamespace(out=None, _body_json=lambda raw: json.loads(raw or b"{}"))
    h._json = lambda code, res, headers=None: setattr(h, "out", (code, res))
    h._launch = h._events = lambda *a: None
    server.PeerHandler._route(h, "GET", ["restaurables"], b"", "pcB")
    assert h.out[0] == 200 and [e["session_id"] for e in h.out[1]["restaurables"]] == [sid]
    server.PeerHandler._route(h, "POST", ["restaurar"], json.dumps({"session_id": sid}).encode(), "pcB")
    assert h.out[0] == 200 and h.out[1]["restored"][0]["session_id"] == sid


@pytest.mark.parametrize(
    "razon,voluntaria",
    [("exit", True), ("clear", True), ("other", False), (None, False), ("razon-nueva-de-claude", False)],
)
def test_ended_on_purpose_es_lista_blanca(razon, voluntaria):
    """Una razon de SessionEnd que no conocemos cuenta como muerte a restaurar, no como salida."""
    assert restore.ended_on_purpose({"last_event": "SessionEnd", "end_reason": razon}) is voluntaria
