"""Fase 1 del plan de refactor (docs/plan-refactor-2026-10-04.md), parte sessions/state: errores que
se perdian en silencio y escrituras que no respetaban la regla del lock. Cada prueba reproduce el
caso que el plan describe antes de que se arreglara."""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# `from lienzo import server` agrega lienzo/ al sys.path y engancha rules a sessions (ver test_server)
from lienzo import server  # noqa: F401
import sessions as ses
import state as st


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp, sin SSE; el log queda en una lista para mirarlo."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    logs: list[str] = []
    monkeypatch.setattr(st, "log", logs.append)
    monkeypatch.setattr(st, "_avisos", {})
    st.sessions.clear()
    st.transcript_stat.clear()
    yield logs
    st.sessions.clear()
    st.transcript_stat.clear()


def esperar(cond, s=2.0) -> bool:
    fin = time.monotonic() + s
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# 1.1 excepciones de los hilos ------------------------------------------------------------------


def test_en_hilo_manda_el_traceback_al_log(aislado):
    def rompe(x):
        raise ValueError(f"se rompio {x}")

    t = ses.en_hilo(rompe, 7)
    t.join(2)
    assert any("Traceback" in m and "se rompio 7" in m and "rompe" in m for m in aislado)


def test_el_cierre_de_turno_que_falla_queda_en_el_log(aislado, monkeypatch):
    """Antes el hilo de on_turn_end moria y el traceback iba a stderr, no a lienzo.log."""

    def rompe(sid):
        raise RuntimeError("regla rota")

    monkeypatch.setattr(ses, "on_turn_end", rompe)
    s = ses.new_session("a" * 8, "claude", "hook")
    s["state"] = "corriendo"
    ses.set_state(s, "termino")
    assert esperar(lambda: any("regla rota" in m for m in aislado))


def test_un_gancho_sin_cablear_avisa_una_sola_vez(aislado):
    gancho = ses._gancho_sin_cablear("on_prueba")
    gancho("x")
    gancho("y", "z")
    assert len([m for m in aislado if "on_prueba" in m]) == 1


# 1.2 touch() no resucita una tarjeta borrada ---------------------------------------------------


def test_touch_sobre_una_tarjeta_borrada_no_la_reescribe(aislado, monkeypatch):
    """E1/S10: un envio de hasta 60 s termina con touch(s) sobre una tarjeta que se borro mientras
    tanto; el archivo de la tarjeta volvia a aparecer en disco y resucitaba en el proximo arranque."""
    eventos = []
    monkeypatch.setattr(st, "broadcast", eventos.append)
    s = ses.new_session("b" * 8, "claude", "hook")
    st.sessions[s["session_id"]] = s
    assert ses.touch(s) is True
    ruta = os.path.join(st.SESSIONS, f"{s['session_id']}.json")
    assert os.path.exists(ruta)
    ses.drop_session(s["session_id"], "prueba")
    assert not os.path.exists(ruta)
    eventos.clear()
    assert ses.touch(s) is False
    assert not os.path.exists(ruta) and eventos == []


def test_touch_sobre_una_tarjeta_reemplazada_no_pisa_a_la_nueva(aislado):
    vieja = ses.new_session("c" * 8, "claude", "hook")
    nueva = ses.new_session("c" * 8, "claude", "hook")
    st.sessions[nueva["session_id"]] = nueva
    assert ses.touch(vieja) is False


# 1.3 DEAD_TARGETS bajo el lock ----------------------------------------------------------------


def test_dos_sucesoras_a_la_vez_heredan_una_sola_vez(aislado, monkeypatch):
    """E2: dos sesiones nuevas en la misma carpeta y del mismo agente nacen juntas. Sin el lock las
    dos veian a la muerta como candidata; una heredaba y la otra moria con KeyError en su hilo."""
    old = "d" * 8
    monkeypatch.setattr(ses, "DEAD_TARGETS", {old: {"cwd": "D:/x", "agent": "claude", "since": time.time()}})
    monkeypatch.setattr(ses, "mirror", None)
    heredadas = []
    monkeypatch.setattr(ses, "retarget_rules", lambda o, n: heredadas.append((o, n)) or 1)
    norm = ses._norm_cwd

    def lento(c):
        time.sleep(0.05)  # que las dos pasadas por las candidatas se solapen
        return norm(c)

    monkeypatch.setattr(ses, "_norm_cwd", lento)
    resultados, errores = [], []

    def nace(sid):
        try:
            resultados.append(ses.adopt_dead_target({"session_id": sid, "agent": "claude", "cwd": "D:\\x"}))
        except Exception as e:
            errores.append(e)

    hilos = [threading.Thread(target=nace, args=(sid,)) for sid in ("e" * 8, "f" * 8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(5)
    assert errores == []
    assert sorted(resultados, key=str) == [None, old]
    assert len(heredadas) == 1 and ses.DEAD_TARGETS == {}


# 1.4 leer afuera, escribir adentro revalidando --------------------------------------------------


def _coda_con_permiso(monkeypatch, coda_at="t1"):
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses.backend, "is_tmux", lambda s: False)
    monkeypatch.setattr(ses, "read_screen", lambda s: {"ok": True, "lines": ["Approval Required", "Enter confirm"]})
    s = ses.new_session("c0da" * 2, "coda", "hook")
    s.update(pid=123, state="te_necesita", needs={"kind": "permission", "where": "terminal", "coda_at": coda_at})
    st.sessions[s["session_id"]] = s
    return s


def test_contestar_coda_no_pisa_un_permiso_nuevo_que_llego_durante_el_envio(aislado, monkeypatch):
    """E4: entre leer `needs` y escribir «enviado» pasan el subproceso de pantalla y el de send.py.
    Si en ese rato coda abrio OTRO permiso (coda_log_activity puso un coda_at nuevo), marcarlo
    «enviado» le escondia los botones de un pedido que nadie contesto."""
    s = _coda_con_permiso(monkeypatch)

    def envio(s_, final, enter=True, key=None):
        with st.lock:
            s_["needs"] = {"kind": "permission", "where": "terminal", "coda_at": "t2"}
        return 200, {"ok": True}

    monkeypatch.setattr(ses, "run_send", envio)
    code, _ = ses.answer_coda_ask(s, "allow")
    assert code == 200
    assert s["needs"]["coda_at"] == "t2" and s["needs"]["where"] == "terminal"


def test_contestar_coda_marca_enviado_si_el_permiso_sigue_siendo_el_mismo(aislado, monkeypatch):
    s = _coda_con_permiso(monkeypatch)
    monkeypatch.setattr(ses, "run_send", lambda *a, **k: (200, {"ok": True}))
    assert ses.answer_coda_ask(s, "allow")[0] == 200
    assert s["needs"]["where"] == "enviado" and s["needs"]["coda_at"] == "t1"


def test_detener_dos_veces_a_la_vez_manda_un_solo_esc(aislado, monkeypatch):
    """E4: set_stopped miraba stopped_by afuera del lock y lo marcaba despues del Esc (un envio de
    hasta 60 s): dos pedidos juntos mandaban dos Esc y avisaban dos veces a las conectadas."""
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(ses, "_notify_async", lambda fn: None)
    s = ses.new_session("5709" * 2, "claude", "hook")
    s.update(pid=123, state="corriendo")
    st.sessions[s["session_id"]] = s
    escs, segunda = [], []

    def envio(s_, final, enter=True, key=None):
        escs.append(key)
        if len(escs) == 1:
            segunda.append(ses.set_stopped(s_, True))  # el otro pedido llega mientras se teclea
        return 200, {"ok": True}

    monkeypatch.setattr(ses, "run_send", envio)
    res = ses.set_stopped(s, True)
    assert escs == ["escape"] and res["interrupted"] is True
    assert segunda and segunda[0].get("already") is True
    assert s["stopped_by"] == "user"


# 1.5 una tarjeta rota no corta la pasada de liveness --------------------------------------------


def test_una_tarjeta_rota_no_corta_la_pasada_de_liveness(aislado, monkeypatch):
    """E7: el try envolvia la pasada entera; una tarjeta que levantaba dejaba sin revisar a las
    que venian despues, sin guardar las vivas y sin barrido, cada 2 s y para siempre."""
    for sid in ("aaaaaaaa", "bbbbbbbb"):
        st.sessions[sid] = ses.new_session(sid, "claude", "hook")
    vistas = []

    def check(sid):
        vistas.append(sid)
        if sid == "aaaaaaaa":
            raise KeyError("state")

    barridos = []
    monkeypatch.setattr(ses, "check_liveness", check)
    monkeypatch.setattr(ses, "remember_live_cards", lambda: None)
    monkeypatch.setattr(ses, "sweep_once", lambda: barridos.append(1))
    monkeypatch.setattr(ses, "last_sweep", 0.0)
    ses.liveness_pass(30)
    ses.liveness_pass(30)
    assert vistas.count("bbbbbbbb") == 2 and barridos
    # el mismo error de la misma tarjeta se loguea una vez, no cada 2 s
    assert len([m for m in aislado if "aaaaaaaa" in m]) == 1


def test_un_barrido_que_falla_queda_en_el_log_y_no_corta_la_pasada(aislado, monkeypatch):
    monkeypatch.setattr(ses, "remember_live_cards", lambda: None)
    monkeypatch.setattr(ses, "last_sweep", 0.0)

    def rompe():
        raise OSError("tasklist no respondio")

    monkeypatch.setattr(ses, "sweep_once", rompe)
    ses.liveness_pass(30)
    assert any("tasklist no respondio" in m for m in aislado)


def test_guess_claude_saltea_una_transcripcion_que_desaparece(tmp_path, monkeypatch):
    """Entre el glob y el getmtime la transcripcion puede borrarse: el OSError mataba el barrido."""
    d = tmp_path / ".claude" / "projects" / st.claude_slug(r"D:\x")
    d.mkdir(parents=True)
    (d / "viva.jsonl").write_text("{}")
    (d / "borrada.jsonl").write_text("{}")
    real = os.path.getmtime

    def mtime(p):
        if str(p).endswith("borrada.jsonl"):
            raise FileNotFoundError(p)
        return real(p)

    monkeypatch.setattr(ses.os.path, "getmtime", mtime)
    sid, path = ses.guess_claude(r"D:\x", 0, str(tmp_path))
    assert sid == "viva"


def test_guess_codex_saltea_un_rollout_que_desaparece(tmp_path, monkeypatch):
    d = tmp_path / ".codex" / "sessions" / "2026" / "10" / "04"
    d.mkdir(parents=True)
    (d / "rollout-borrado.jsonl").write_text("{}")
    real = os.path.getmtime

    def mtime(p):
        if str(p).endswith("rollout-borrado.jsonl"):
            raise FileNotFoundError(p)
        return real(p)

    monkeypatch.setattr(ses.os.path, "getmtime", mtime)
    assert ses.guess_codex(r"D:\x", 0, str(tmp_path)) == (None, None)


def test_avisar_si_cambia_loguea_solo_cuando_cambia(aislado):
    st.avisar_si_cambia("k", "falla A")
    st.avisar_si_cambia("k", "falla A")
    st.avisar_si_cambia("k", "falla B")
    st.avisar_si_cambia("k", None)  # se arreglo: lo dice una vez
    st.avisar_si_cambia("k", None)
    assert len([m for m in aislado if "falla" in m or "k:" in m]) == 3


# 1.6 un evento que no se puede borrar no se reaplica --------------------------------------------


def test_un_evento_que_no_se_puede_borrar_se_aplica_una_sola_vez(aislado, tmp_path, monkeypatch):
    """E8: si Windows no deja borrar el archivo del evento (antivirus, indexador), la vuelta
    siguiente lo volvia a leer y aplicar, cada 0,25 s: un UserPromptSubmit repetido reabria el
    turno, un Stop repetido volvia a disparar las reglas."""
    eventos = tmp_path / "events"
    eventos.mkdir()
    (eventos / "0001-ev.json").write_text('{"hook_event_name": "Stop", "session_id": "x"}', encoding="utf-8")
    monkeypatch.setattr(ses, "EVENTS", str(eventos))
    monkeypatch.setattr(ses, "_aplicados", {})
    aplicados = []
    monkeypatch.setattr(ses, "apply_event", aplicados.append)
    real_remove = os.remove

    def remove(p):
        if str(p).endswith("0001-ev.json"):
            raise PermissionError(32, "en uso por otro proceso")
        return real_remove(p)

    monkeypatch.setattr(ses.os, "remove", remove)
    for _ in range(3):
        ses.consume_once()
    assert len(aplicados) == 1
    assert len([m for m in aislado if "0001-ev.json" in m]) == 1
    # cuando por fin se puede borrar, se borra y deja de ocupar lugar en el set
    monkeypatch.setattr(ses.os, "remove", real_remove)
    ses.consume_once()
    assert not (eventos / "0001-ev.json").exists() and ses._aplicados == {}


# 1.7 transiciones: cierre de turno y muerte -----------------------------------------------------


@pytest.fixture
def hilos(monkeypatch):
    """en_hilo sincronico que anota que se lanzo: (nombre del gancho, args)."""
    lanzados = []
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: lanzados.append(("on_turn_end", sid)))
    monkeypatch.setattr(ses, "on_died_working", lambda sid, prev: lanzados.append(("on_died_working", sid, prev)))
    monkeypatch.setattr(ses, "en_hilo", lambda fn, *a: fn(*a))
    return lanzados


@pytest.mark.parametrize("agente,hooked", [("claude", True), ("claude", False), ("pi", True), ("pi", False)])
def test_el_cierre_de_turno_sale_solo_de_corriendo_o_te_necesita_a_termino(aislado, hilos, agente, hooked):
    for prev in (*st.STATES, None, "roto"):
        for nuevo in st.STATES:
            hilos.clear()
            s = ses.new_session("e" * 8, agente, "hook")
            s.update(state=prev, hooked=hooked)
            ses.set_state(s, nuevo)
            espera = nuevo == "termino" and prev in ("corriendo", "te_necesita") and (agente != "pi" or hooked)
            assert hilos == ([("on_turn_end", "e" * 8)] if espera else []), (prev, nuevo)


def test_session_end_no_avisa_que_murio_trabajando(aislado, hilos, monkeypatch):
    """SessionEnd es /exit o /clear: avisar a la coordinadora que «murio con un encargo» seria falso."""
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: True)
    ses.apply_event({"hook_event_name": "UserPromptSubmit", "session_id": "f" * 8, "prompt": "x"})
    assert st.sessions["f" * 8]["state"] == "corriendo"
    ses.apply_event({"hook_event_name": "SessionEnd", "session_id": "f" * 8, "reason": "clear"})
    s = st.sessions["f" * 8]
    assert s["state"] == "muerta" and s["alive"] is False and s["dead_since"]
    assert [h for h in hilos if h[0] == "on_died_working"] == []


def test_evento_con_pid_muerto_nace_muerta_sin_avisar(aislado, hilos, monkeypatch):
    """El evento quedo en la cola con el server apagado (o el agente lo escribio al cerrarse): prueba
    que la sesion existio, no que murio trabajando AHORA; no se avisa."""
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: False)
    ses.apply_event({"hook_event_name": "UserPromptSubmit", "session_id": "9" * 8, "prompt": "x", "pid": 4242})
    s = st.sessions["9" * 8]
    assert s["state"] == "muerta" and s["alive"] is False and s["dead_since"]
    assert [h for h in hilos if h[0] == "on_died_working"] == []


def test_el_proceso_que_desaparece_avisa_solo_si_trabajaba(aislado, hilos, monkeypatch):
    monkeypatch.setattr(ses.backend, "agent_alive", lambda s: False)
    for prev, avisa in (("corriendo", True), ("te_necesita", True), ("termino", False)):
        hilos.clear()
        s = ses.new_session("7" * 8, "claude", "hook")
        s.update(pid=1, alive=True, state=prev)
        assert ses.refresh_alive(s) is True
        assert s["state"] == "muerta" and s["alive"] is False and s["dead_since"]
        assert [h for h in hilos if h[0] == "on_died_working"] == (
            [("on_died_working", "7" * 8, prev)] if avisa else []
        )


def test_marcar_muerta_es_la_unica_forma(aislado, hilos):
    s = ses.new_session("6" * 8, "claude", "hook")
    s.update(state="corriendo", alive=True)
    ses.marcar_muerta(s, avisar=False)
    assert s["state"] == "muerta" and s["alive"] is False and s["dead_since"] and hilos == []
    s.update(state="te_necesita", alive=True, dead_since=None)
    ses.marcar_muerta(s, avisar=True)
    assert hilos == [("on_died_working", "6" * 8, "te_necesita")]


# 0.8 un JSON corrupto no borra datos sin aviso --------------------------------------------------


def _apartados(path):
    return sorted(p for p in os.listdir(os.path.dirname(path)) if p.startswith(os.path.basename(path) + ".corrupto-"))


def test_reglas_corruptas_se_apartan_y_no_se_pisan(aislado, tmp_path):
    """E3: rules.json con un byte roto se cargaba como lista vacia, sin log, y el primer save lo
    pisaba: se perdian todas las reglas sin rastro."""
    path = str(tmp_path / "rules.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('[{"id": "r1", "to": "x"')  # cortado a la mitad
    lista = st.JsonList(path, "rules")
    lista.load(lambda r: True)
    assert lista.items == []
    apartados = _apartados(path)
    assert len(apartados) == 1 and not os.path.exists(path)
    with open(os.path.join(tmp_path, apartados[0]), encoding="utf-8") as f:
        assert f.read() == '[{"id": "r1", "to": "x"'  # el contenido sigue ahi para rescatarlo
    assert any("rules.json" in m and "corrupto" in m for m in aislado)


def test_reglas_que_no_existen_arrancan_vacias_sin_log(aislado, tmp_path):
    lista = st.JsonList(str(tmp_path / "rules.json"), "rules")
    lista.load(lambda r: True)
    assert lista.items == [] and aislado == []


def test_reglas_ilegibles_no_se_pisan_al_guardar(aislado, tmp_path, monkeypatch):
    """Si el archivo existe pero no se pudo leer (bloqueado, sin permiso), guardar la lista vacia
    en memoria borraria las reglas del disco."""
    path = tmp_path / "rules.json"
    path.write_text('[{"id": "r1"}]', encoding="utf-8")
    lista = st.JsonList(str(path), "rules")
    real_open = open

    def abrir(p, *a, **k):
        if str(p) == str(path):
            raise PermissionError(13, "bloqueado")
        return real_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", abrir)
    lista.load(lambda r: True)
    monkeypatch.setattr("builtins.open", real_open)
    lista.items.append({"id": "r2"})
    lista.save()
    assert path.read_text(encoding="utf-8") == '[{"id": "r1"}]'
    assert any("rules.json" in m for m in aislado)


def test_config_corrupta_se_aparta_y_set_config_key_no_escribe(aislado, tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"ejemplos": [1, 2', encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_FILE", str(cfg))
    assert st.set_config_key("auto_continue", True) is False
    assert not cfg.exists() and len(_apartados(str(cfg))) == 1
    assert any("config.json" in m and "corrupto" in m for m in aislado)
    # apartada la corrupta, la proxima escritura arranca un archivo nuevo
    assert st.set_config_key("auto_continue", True) is True
    assert st.load_config() == {"auto_continue": True}


def test_config_que_no_existe_es_vacia_sin_log(aislado, tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CONFIG_FILE", str(tmp_path / "config.json"))
    assert st.load_config() == {} and aislado == []
