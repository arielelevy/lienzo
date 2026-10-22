"""Dos bugs de tarjetas de la ronda del 2026-10-22 (encargo N).

1. La tarjeta de J (pid 18496, una TUI sin -p) quedo con `external.kind=batch via=comando` y el
   /send daba 409 «es una corrida headless». El barrido adivina la transcripcion de un agente sin
   hooks por carpeta y fecha (guess_claude: la mas nueva de la carpeta), y un `claude -p` del mismo
   repo (el investigador de G) adivinaba la de J: adopt_process le copiaba su marca `external` a la
   tarjeta de J aunque su pid siguiera vivo y fuera otro.
2. Al cerrarse el frente K sus reglas quedaron estacionadas, y una sesion abierta a mano despues en
   la misma carpeta («lienzo | sesion», 084623e6) las heredo y mandaba informes vacios a la
   coordinadora. La herencia exige una sucesora real: el mismo id, una restaurada desde el lienzo o
   una que el lienzo titulo igual que la muerta (lanzada con ese titulo, o renombrada a el).
"""

import os

import pytest
import rules as rl
import sessions as ses
import state as st

J = "5b5c6143-0000-4000-8000-0000000000a1"
K = "6b910349-0000-4000-8000-0000000000a2"
NUEVA = "084623e6-0000-4000-8000-0000000000a3"
COORD = "607da9a5-0000-4000-8000-0000000000a4"
CWD = r"D:\Apps\lienzo"
PID_J, PID_BATCH = 18496, 31337
BATCH = {"kind": "batch", "via": "comando"}


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "LIENZO", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    logs: list[str] = []
    monkeypatch.setattr(st, "log", logs.append)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    monkeypatch.setattr(ses, "refresh_from_transcript", lambda s: False)
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(ses, "DEAD_TARGETS", {})
    monkeypatch.setattr(ses, "SUCESORAS", {})
    monkeypatch.setattr(ses, "restore_on_drop", lambda card, muerta: None)
    monkeypatch.setattr(rl.rules, "path", str(tmp_path / "rules.json"))
    monkeypatch.setattr(rl.rules, "items", [])
    # los hilos de trabajo corren en el acto: lo que se mide es el resultado, no el orden
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *args: fn(*args))
    os.makedirs(st.SESSIONS, exist_ok=True)
    st.sessions.clear()
    yield logs
    st.sessions.clear()


# 1. «corrida headless» falsa ------------------------------------------------------------------


def tui_de_j(monkeypatch):
    s = ses.new_session(J, "claude", "hook")
    s.update(pid=PID_J, alive=True, cwd=CWD, transcript_path=rf"C:\t\{J}.jsonl", no_console=False)
    st.sessions[J] = s
    vivos = {PID_J, PID_BATCH}
    monkeypatch.setattr(ses.backend, "agent_alive", lambda d: d.get("pid") in vivos)
    monkeypatch.setattr(ses.backend, "cwd_of", lambda d: CWD)
    # guess_claude devuelve la transcripcion mas nueva de la carpeta: la de J, que esta trabajando
    monkeypatch.setattr(ses, "guess_transcript", lambda *a, **k: (J, rf"C:\t\{J}.jsonl"))
    return s


def corrida_p() -> dict:
    return {"pid": PID_BATCH, "agent": "claude", "exe": "claude.exe", "created": st.now(), "external": dict(BATCH)}


def test_un_claude_p_del_mismo_repo_no_le_pasa_su_marca_a_una_tui_viva(aislado, monkeypatch):
    j = tui_de_j(monkeypatch)
    ses.adopt_process(corrida_p())
    assert j["pid"] == PID_J
    assert j.get("external") is None and j["no_console"] is False  # J sigue recibiendo envios
    assert ses.external_blocked(j) is None


def test_la_corrida_ajena_tiene_su_propia_tarjeta_de_solo_lectura(aislado, monkeypatch):
    tui_de_j(monkeypatch)
    ses.adopt_process(corrida_p())
    propia = st.sessions.get(f"pid-{PID_BATCH}")
    assert propia is not None and propia["external"] == BATCH and propia["no_console"] is True
    assert propia["transcript_path"] is None  # la de J no es suya


def test_una_corrida_que_si_retoma_la_tarjeta_conserva_su_marca(aislado, monkeypatch):
    """La tarjeta cuyo proceso murio la toma el proceso nuevo, con su marca: eso no cambia."""
    j = tui_de_j(monkeypatch)
    j["pid"] = 4  # murio
    ses.adopt_process(corrida_p())
    assert j["pid"] == PID_BATCH and j["external"] == BATCH and j["no_console"] is True


# 2. reglas heredadas por una sesion sin relacion ------------------------------------------------


def frente_k_cerrado(titulo="lienzo - encargo K - acceso de emergencia"):
    for sid, t in ((COORD, None), (K, titulo)):
        s = ses.new_session(sid, "claude", "hook")
        s["cwd"] = CWD
        if t:
            s["title"], s["title_source"] = t, "user"
        st.sessions[sid] = s
    st.rules.items.append(
        {"id": "informe", "kind": "on_stop", "from": K, "to": COORD, "text": "{respuesta}", "enabled": True}
    )
    ses.drop_session(K, "muerta hace mas de 60 s", muerta=True)


def nace(sid=NUEVA, titulo=None):
    s = ses.new_session(sid, "claude", "hook")
    s["cwd"] = CWD
    if titulo:
        s["title"], s["title_source"] = titulo, "user"
    st.sessions[sid] = s
    return s


def test_una_sesion_nueva_sin_relacion_no_hereda_las_reglas_del_frente_cerrado(aislado):
    frente_k_cerrado()
    nueva = nace()
    assert ses.adopt_dead_target(dict(nueva)) is None
    informe = st.rules.items[0]
    assert informe["from"] == K and informe["parked_from"] == K and informe["enabled"] is False
    assert K in ses.DEAD_TARGETS  # sigue esperando a su sucesora real
    assert nueva.get("title_source") != "user"


def test_la_lanzada_por_el_lienzo_con_el_mismo_titulo_si_hereda(aislado):
    frente_k_cerrado()
    nueva = nace(titulo="lienzo - encargo K - acceso de emergencia")
    assert ses.adopt_dead_target(dict(nueva)) == K
    assert st.rules.items[0]["from"] == NUEVA and st.rules.items[0]["enabled"] is True


def test_renombrarla_en_el_lienzo_con_el_titulo_de_la_muerta_la_hace_sucesora(aislado):
    """La coordinadora que se cierra y se reabre a mano (2026-10-03): ya no hereda sola; al ponerle
    el mismo titulo en el tablero recupera sus avisos."""
    frente_k_cerrado()
    nueva = nace()
    assert ses.adopt_dead_target(dict(nueva)) is None
    ses.set_title(nueva, "lienzo - encargo K - acceso de emergencia")
    assert st.rules.items[0]["from"] == NUEVA and st.rules.items[0]["enabled"] is True
    assert ses.sucesora_de(K) == NUEVA


def test_renombrarla_con_otro_titulo_no_hereda(aislado):
    frente_k_cerrado()
    nueva = nace()
    ses.set_title(nueva, "lienzo - encargo N - bugs de tarjetas")
    assert st.rules.items[0]["from"] == K and st.rules.items[0]["enabled"] is False


def test_sin_titulo_la_muerta_espera_un_resume_o_una_restauracion(aislado):
    frente_k_cerrado(titulo=None)
    assert ses.adopt_dead_target(dict(nace())) is None
    vuelta = nace(sid=K)  # claude --resume conserva el id
    assert ses.adopt_dead_target(dict(vuelta)) == K
    assert st.rules.items[0]["from"] == K and st.rules.items[0]["enabled"] is True


def test_renombrar_no_le_quita_las_reglas_a_un_frente_que_se_esta_restaurando(aislado):
    """Revision: el renombre corria la herencia completa, y una restaurada (sin importar el titulo)
    le ganaba al titulo: cualquier sesion renombrada se llevaba las reglas del frente relanzado."""
    import server

    frente_k_cerrado()
    server.preparar_sucesion({"session_id": K, "cwd": CWD, "agent": "claude", "title": None})
    otra = nace()
    ses.set_title(otra, "lienzo - encargo N - otra cosa")
    assert st.rules.items[0]["from"] == K and K in ses.DEAD_TARGETS
    ses.set_title(otra, "lienzo - encargo K - acceso de emergencia")  # con su titulo, si
    assert st.rules.items[0]["from"] == NUEVA


def test_la_provisoria_del_barrido_no_hereda_al_titularla(aislado):
    """Revision: `pid-N` se da de baja al llegar el id real y SUCESORAS quedaba apuntando a la nada."""
    frente_k_cerrado()
    prov = nace(sid="pid-4242")
    ses.set_title(prov, "lienzo - encargo K - acceso de emergencia")
    assert st.rules.items[0]["from"] == K and ses.sucesora_de(K) is None


def test_un_segundo_renombre_rapido_cancela_la_herencia_del_primero(aislado, monkeypatch):
    frente_k_cerrado()
    nueva = nace()
    pendientes = []
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *args: pendientes.append((fn, args)))
    ses.set_title(nueva, "lienzo - encargo K - acceso de emergencia")
    ses.set_title(nueva, "lienzo - encargo N - era otro")
    for fn, args in pendientes:
        fn(*args)
    assert st.rules.items[0]["from"] == K and K in ses.DEAD_TARGETS


def test_una_tui_sin_hooks_no_le_pisa_la_tarjeta_a_otra_sesion_viva(aislado, monkeypatch):
    """Revision (altura): la guarda vale para toda transcripcion adivinada, no solo las externas."""
    j = tui_de_j(monkeypatch)
    j["backend"] = "win32"
    ses.adopt_process({"pid": PID_BATCH, "agent": "claude", "exe": "claude.exe", "created": st.now(), "external": None})
    assert j["pid"] == PID_J and j["backend"] == "win32" and j["no_console"] is False
    assert st.sessions[f"pid-{PID_BATCH}"]["transcript_path"] is None
