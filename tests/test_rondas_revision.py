"""Regresiones de la revision del 2026-10-16 sobre rondas largas (code-review high): cada prueba es un
hallazgo confirmado, con el escenario que lo rompia."""

import datetime as dt
import os
import sys

import pytest
import rondas
import rules as rl
import server
import sessions as ses
import state as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import coordinar as c

COORD = "c0000000-0000-4000-8000-0000000000f0"
A = "a0000000-0000-4000-8000-0000000000f1"
B = "b0000000-0000-4000-8000-0000000000f2"
N = "e0000000-0000-4000-8000-0000000000f3"


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(ses, "SUCESORAS", {})
    monkeypatch.setattr(ses, "DEAD_TARGETS", {})
    monkeypatch.setattr(ses, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(ses, "restore_on_drop", lambda card, muerta: None)
    monkeypatch.setattr(rondas, "_datos", {"avisos": {}, "turnos": {}, "politicas": {}})
    monkeypatch.setattr(rl.rules, "items", [])
    monkeypatch.setattr(rl.rules, "save", lambda *a, **k: None)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    hilos, enviados = [], []
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *args: hilos.append((fn, args)))
    envio = lambda s, t, att: (enviados.append((s["session_id"], t)), (200, {}))[1]
    monkeypatch.setattr(ses, "send_to_session", envio)
    monkeypatch.setattr(rl, "send_to_session", envio)
    st.sessions.clear()
    for sid in (COORD, A, B):
        s = ses.new_session(sid, "claude", "hook")
        s.update(alive=True, cwd=r"D:\Apps\opensyync", repo_key="opensyync")
        st.sessions[sid] = s
    yield hilos, enviados
    st.sessions.clear()
    rl._on_stop_en_vuelo.clear()
    rl._fotos.clear()


def regla(**extra):
    r = {"id": "rv", "kind": "on_stop", "from": A, "to": COORD, "text": "{respuesta}", "enabled": True, "repeat": True}
    r.update(fired=0, **extra)
    st.rules.items.append(r)
    return r


def enfriar(r):
    last = rl.local_dt(r["last_fired"]) - dt.timedelta(seconds=rl.ON_STOP_COOLDOWN_S + 1)
    r["last_fired"] = r["recent_fires"][-1] = last.isoformat(timespec="seconds")


def test_el_marcador_al_final_de_un_informe_largo_avisa(entorno):
    _, enviados = entorno
    regla(solo_si="ESTADO:")
    st.sessions[A]["last_reply"] = "x" * 8000 + "\nESTADO: listo"
    rl.fire_on_stop(A)
    assert len(enviados) == 1 and len(enviados[0][1]) <= rl.REPLY_CAP + 3  # va recortado, pero va


def test_la_misma_respuesta_a_otro_pedido_si_avisa(entorno):
    _, enviados = entorno
    r = regla()
    st.sessions[A].update(last_prompt="tarea 1", last_reply="Listo.")
    rl.fire_on_stop(A)
    enfriar(r)
    st.sessions[A].update(last_prompt="tarea 2")
    rl.fire_on_stop(A)
    assert [t for _, t in enviados] == ["Listo.", "Listo."]


def test_una_regla_apagada_vuelve_apagada_tras_restaurar(entorno):
    st.rules.items.append({"id": "uno", "kind": "on_stop", "from": A, "to": COORD, "text": "x", "enabled": False})
    st.rules.items.append({"id": "on", "kind": "on_stop", "from": COORD, "to": A, "text": "y", "enabled": False})
    ses.drop_session(A, "muerta", muerta=True)
    nueva = ses.new_session(N, "claude", "hook")
    nueva["cwd"] = r"D:\Apps\opensyync"
    st.sessions[N] = nueva
    assert ses.adopt_dead_target(dict(nueva)) == A
    assert [(r["id"], r["enabled"]) for r in st.rules.items] == [("uno", False), ("on", False)]


def test_un_relanzado_fallido_no_deja_la_marca_restaurada(entorno, monkeypatch):
    monkeypatch.setattr(
        server.restore,
        "restorables",
        lambda live=(): [{"session_id": A, "agent": "claude", "cwd": r"D:\Apps\opensyync"}],
    )
    monkeypatch.setattr(server.launch, "launch", lambda *a, **k: {"ok": False, "error": "cwd fuera de launch_roots"})
    st.sessions[A]["alive"] = False
    st.rules.items.append({"id": "i", "kind": "on_stop", "from": A, "to": COORD, "text": "x", "enabled": True})
    code, res = server.restore_local({"session_id": A})
    assert code == 400 and res["failed"]
    assert "restaurada" not in ses.DEAD_TARGETS[A]


def test_los_avisos_de_rondas_no_frenan_el_bucle(entorno):
    hilos, enviados = entorno
    rondas.pedir_turno("suite", {"session_id": A})
    rondas.pedir_turno("suite", {"session_id": B})
    hilos.clear()
    rondas.liberar_turno("suite", A)
    assert enviados == [] and [fn.__name__ for fn, _ in hilos] == ["_mandar"]  # el mensaje sale en un hilo


def test_una_duenia_restaurada_suelta_y_renueva_su_turno(entorno):
    rondas.pedir_turno("suite", {"session_id": A})
    st.sessions[N] = {**st.sessions.pop(A), "session_id": N}
    ses.SUCESORAS[A] = {"new": N, "ts": 0}
    assert rondas.pedir_turno("suite", {"session_id": N})[1].get("renovado") is True
    rondas.revisar()
    assert rondas._datos["turnos"]["suite"]["dueno"]["session_id"] == N
    assert rondas.liberar_turno("suite", N)[0] == 200


def test_un_id_viejo_y_su_sucesora_no_reciben_el_aviso_dos_veces(entorno):
    ses.SUCESORAS["viejo-a"] = {"new": A, "ts": 0}
    code, res = rondas.crear_aviso({"texto": "x", "a": ["viejo-a", A]})
    assert code == 400 and "misma sesion" in res["error"]


def test_el_tope_cuenta_por_carpeta_si_la_clave_local_no_coincide(entorno, monkeypatch):
    monkeypatch.setattr(rondas.identity, "repo_key", lambda cwd: "opensyync-local")
    monkeypatch.setattr(st, "load_config", lambda: {"max_sesiones_por_repo": 3})
    assert rondas.tope_repo(r"D:\Apps\opensyync", list(st.sessions.values()))["code"] == "tope_repo"


def test_enviar_seguro_va_a_la_sucesora_aunque_no_queden_reintentos(monkeypatch):
    pedidos = []

    def pedir(metodo, ruta, cuerpo=None, timeout=20):
        pedidos.append(ruta)
        return (404, {"code": "unknown_session", "sucesora": N}) if A in ruta else (200, {"ok": True})

    vistas = [{"session_id": A, "state": "termino", "last_prompt": "a"}]
    monkeypatch.setattr(c, "pedir", pedir)
    monkeypatch.setattr(c, "sesiones", lambda: vistas)
    monkeypatch.setattr(
        c.time, "sleep", lambda s: vistas.append({"session_id": N, "state": "corriendo", "last_prompt": "b"})
    )
    out = c.enviar_seguro({"session_id": A}, "hola", reintentos=0, espera=2)
    assert pedidos == [f"/sessions/{A}/send", f"/sessions/{N}/send"] and out["ok"] and out["sid"] == N


def test_pedir_turno_sin_ttl_no_lo_manda(monkeypatch):
    cuerpos = []
    monkeypatch.setattr(c, "pedir", lambda m, r, cuerpo=None, timeout=20: (cuerpos.append(cuerpo), (200, {}))[1])
    c.pedir_turno("navegador", A)
    assert "ttl_min" not in cuerpos[0]
