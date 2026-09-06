"""Clasificacion corriendo/termino en lienzo/sessions.py (antes server.py): el Stop tardio de un pedido encolado y la
correccion desde la transcripcion. Sin red ni hilos: apply_event y refresh_from_transcript directos,
con el registro de sesiones apuntando a un directorio temporal."""
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import server  # noqa: E402,F401  (pone lienzo/ en sys.path y engancha rules a sessions)
import rules as rl  # noqa: E402
import sessions as ses  # noqa: E402
import state as st  # noqa: E402

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude", "projects", "D--Apps-lienzo")
SID = "599a7e3e-0000-4000-8000-000000000000"
T0 = "2026-09-05T20:41:53.135-03:00"      # turn_duration del caso medido, en hora local


def local(offset_s: float) -> str:
    import datetime as dt
    return (dt.datetime.fromisoformat(T0) + dt.timedelta(seconds=offset_s)).isoformat(timespec="milliseconds")


def utc(offset_s: float) -> str:
    import datetime as dt
    d = dt.datetime.fromisoformat(T0).astimezone(dt.timezone.utc) + dt.timedelta(seconds=offset_s)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp, sin SSE ni hilos de reglas: lo que se mide es el estado de la tarjeta."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(server, "log", lambda msg: None)   # server importa log por nombre: el parche sobre st no lo alcanza
    st.sessions.clear()
    yield tmp_path
    st.sessions.clear()


def ev(name: str, **k) -> dict:
    return {"hook_event_name": name, "session_id": SID, "agent": "claude", **k}


# 1. hooks al reves ---------------------------------------------------------------

def test_stop_tardio_del_pedido_anterior_no_pisa_el_corriendo(aislado):
    ses.apply_event(ev("UserPromptSubmit", prompt_id="A", prompt="primero", host_ts=local(-60)))
    ses.apply_event(ev("Stop", prompt_id="A", last_assistant_message="listo el primero", host_ts=local(-30)))
    s = st.sessions[SID]
    assert s["state"] == "termino" and s["last_reply"] == "listo el primero"

    # el segundo pedido estaba encolado: Claude Code lo arranca 60 ms despues del turn_duration y
    # los dos hooks (async) corren juntos; el UserPromptSubmit de B queda escrito antes que el Stop de A
    ses.apply_event(ev("UserPromptSubmit", prompt_id="B", prompt="segundo", host_ts=local(0.2)))
    ses.apply_event(ev("Stop", prompt_id="A", last_assistant_message="listo el primero", host_ts=local(0.3)))
    assert s["state"] == "corriendo", "el Stop del pedido A no debe cerrar el turno del pedido B"
    assert s["last_prompt"] == "segundo"

    # el Stop del propio pedido si cierra
    ses.apply_event(ev("Stop", prompt_id="B", last_assistant_message="listo el segundo", host_ts=local(40)))
    assert s["state"] == "termino" and s["last_reply"] == "listo el segundo"


def test_stop_lejano_con_otro_prompt_id_si_cierra(aislado):
    # un Stop con prompt_id distinto pero lejos del ultimo UserPromptSubmit no es "tardio": es un
    # turno que arranco sin hook (aviso de tarea en segundo plano, por ejemplo) y termino
    ses.apply_event(ev("UserPromptSubmit", prompt_id="A", prompt="uno", host_ts=local(-60)))
    ses.apply_event(ev("Stop", prompt_id="Z", host_ts=local(-20)))
    assert st.sessions[SID]["state"] == "termino"


def test_stop_sin_prompt_id_cierra_como_siempre(aislado):
    ses.apply_event(ev("UserPromptSubmit", prompt_id="A", prompt="uno", host_ts=local(-60)))
    ses.apply_event(ev("Stop", host_ts=local(-59.9)))
    assert st.sessions[SID]["state"] == "termino"


# 2. la transcripcion corrige a los hooks ----------------------------------------------

def rows_encolado() -> list[dict]:
    """La forma medida en 599a7e3e: turn_duration y, en el mismo segundo, el pedido que estaba
    encolado; despues herramientas durante minutos."""
    return [
        {"type": "user", "timestamp": utc(-50), "promptId": "A", "message": {"role": "user", "content": "primero"}},
        {"type": "assistant", "timestamp": utc(-0.1), "message": {"role": "assistant", "content": [{"type": "text", "text": "Listo el primero."}]}},
        {"type": "system", "subtype": "stop_hook_summary", "timestamp": utc(-0.01)},
        {"type": "system", "subtype": "turn_duration", "timestamp": utc(0)},
        {"type": "user", "timestamp": utc(0.06), "promptId": "B", "message": {"role": "user", "content": "segundo, largo"}},
        {"type": "assistant", "timestamp": utc(18), "message": {"role": "assistant", "content": [{"type": "text", "text": "Voy."}]}},
        {"type": "assistant", "timestamp": utc(25), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "timestamp": utc(27), "promptId": "B", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "a b c"}]}},
    ]


def write_jsonl(path, rows) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(path)


def tarjeta(path: str, state: str, since: str) -> dict:
    s = ses.new_session(SID, "claude", "hook")
    s.update({"transcript_path": path, "state": state, "state_since": since, "hooked": True, "last_event": "Stop"})
    st.sessions[SID] = s
    return s


def test_transcripcion_reabre_el_termino_que_dejo_un_stop_tardio(aislado):
    path = write_jsonl(aislado / "t.jsonl", rows_encolado())
    # el Stop tardio dejo la tarjeta en termino 300 ms despues del turn_duration
    s = tarjeta(path, "termino", local(0.3))
    assert ses.refresh_from_transcript(s) is True
    assert s["state"] == "corriendo"
    assert s["last_prompt"] == "segundo, largo"
    assert s["last_reply"] == "usando Bash"


def test_transcripcion_no_toca_un_termino_legitimo(aislado):
    # sin el pedido encolado: el turno termino y la tarjeta esta bien en termino
    path = write_jsonl(aislado / "t.jsonl", rows_encolado()[:4])
    s = tarjeta(path, "termino", local(0.3))
    ses.refresh_from_transcript(s)
    assert s["state"] == "termino"


def test_transcripcion_cierra_un_corriendo_sin_stop(aislado):
    # el Stop se perdio (hook con timeout): el turn_duration es posterior al ultimo cambio de estado
    path = write_jsonl(aislado / "t.jsonl", rows_encolado()[:4])
    s = tarjeta(path, "corriendo", local(-50))
    ses.refresh_from_transcript(s)
    assert s["state"] == "termino"


def test_transcripcion_respeta_te_necesita_y_el_envio_reciente(aislado):
    path = write_jsonl(aislado / "t.jsonl", rows_encolado()[:4])
    # te_necesita es de los hooks: la transcripcion no lo pisa
    s = tarjeta(path, "te_necesita", local(-50))
    s["needs"] = {"kind": "permission"}
    ses.refresh_from_transcript(s)
    assert s["state"] == "te_necesita"
    # recien enviado desde el lienzo (send_to_session puso corriendo hace nada): el turno viejo de
    # la transcripcion, anterior a ese cambio, no lo vuelve a termino
    s = tarjeta(path, "corriendo", local(5))
    ses.refresh_from_transcript(s)
    assert s["state"] == "corriendo"


# 3. la transcripcion real ------------------------------------------------------------

def caso_real():
    """(ruta, filas hasta el primer tool_result del pedido encolado, ts del turn_duration) en la
    primera transcripcion de ~/.claude/projects/D--Apps-lienzo que tenga un turn_duration seguido
    en menos de un segundo por un pedido humano. None si no hay."""
    import datetime as dt
    for p in sorted(glob.glob(os.path.join(CLAUDE_DIR, "*.jsonl")), key=os.path.getsize, reverse=True):
        rows = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        for i, r in enumerate(rows):
            if r.get("type") != "system" or r.get("subtype") != "turn_duration":
                continue
            nxt = next((j for j in range(i + 1, len(rows)) if rows[j].get("type") in ("user", "assistant")
                        and not rows[j].get("isSidechain")), None)
            if nxt is None or rows[nxt].get("type") != "user":
                continue
            c = (rows[nxt].get("message") or {}).get("content")
            if not isinstance(c, str) or c.lstrip().startswith("<"):
                continue
            a, b = st.parse_ts(r.get("timestamp")), st.parse_ts(rows[nxt].get("timestamp"))
            if not a or not b or (b - a).total_seconds() > 1.0:
                continue
            end = next((j for j in range(nxt + 1, len(rows)) if rows[j].get("type") == "user"
                        and isinstance((rows[j].get("message") or {}).get("content"), list)), None)
            if end is None:
                continue
            return p, rows[: end + 1], a
    return None


def test_caso_real_pedido_encolado(aislado):
    caso = caso_real()
    if caso is None:
        pytest.skip(f"ninguna transcripcion en {CLAUDE_DIR} tiene un pedido encolado tras un turn_duration")
    src, rows, td = caso
    path = write_jsonl(aislado / "real.jsonl", rows)
    import datetime as dt
    since = (td + dt.timedelta(milliseconds=300)).astimezone().isoformat(timespec="milliseconds")
    s = tarjeta(path, "termino", since)
    ses.refresh_from_transcript(s)
    assert s["state"] == "corriendo", f"{os.path.basename(src)}: el pedido encolado tras {td} no reabrio la tarjeta"
    assert s["last_prompt"]


# 4. /config y el link del usuario --------------------------------------------------------

def test_set_config_key_solo_toca_esa_clave(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ejemplos": "D:/x", "wait": 60, "auto_continue": True}), encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_FILE", str(cfg))
    assert st.public_config() == {"auto_continue": True}
    st.set_config_key("auto_continue", False)
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"ejemplos": "D:/x", "wait": 60, "auto_continue": False}
    assert st.public_config() == {"auto_continue": False}
    # sin archivo: se crea con la clave sola
    cfg.unlink()
    st.set_config_key("auto_continue", True)
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"auto_continue": True}


def test_connections_of_muestra_lo_que_mando_el_usuario(aislado, monkeypatch):
    monkeypatch.setattr(st.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    s = ses.new_session(SID, "claude", "hook")
    s["repo"] = "lienzo"
    st.sessions[SID] = s
    ses.add_link(None, SID, "revisá el panel", "user")
    c = rl.connections_of(SID)
    assert len(c["links"]) == 1
    l = c["links"][0]
    assert l["from"] is None and l["kind"] == "user" and l["direction"] == "in"
    assert l["other"] == {"session_id": None, "name": "vos (lienzo)"}
    # al recargar, el link sin origen se conserva (antes se descartaba por from not in sessions)
    st.links.load(lambda l: l.get("to") in st.sessions and (not l.get("from") or l["from"] in st.sessions))
    assert len(st.links.items) == 1


# 5. el mismo pid cambia de session_id (/clear, resume) -----------------------------------

OLD = "7bb119b6-0000-4000-8000-000000000000"
NEW = "43e4160d-0000-4000-8000-000000000000"
COORD = "599a7e3e-0000-4000-8000-000000000001"
PID = 26356


@pytest.fixture
def con_pid(aislado, monkeypatch):
    """El pid siempre esta vivo y es una TUI; reglas y links en tmp; el log se guarda para mirarlo."""
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: pid == PID)
    monkeypatch.setattr(ses.procs, "is_tui", lambda pid: True)
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    logs: list[str] = []
    monkeypatch.setattr(st, "log", logs.append)
    coord = ses.new_session(COORD, "claude", "hook")
    st.sessions[COORD] = coord
    return logs


def evp(name: str, sid: str, **k) -> dict:
    return {"hook_event_name": name, "session_id": sid, "agent": "claude", "pid": PID, "cwd": r"D:\Apps\lienzo", **k}


def sesion_vieja(aislado):
    tp_old = str(aislado / f"{OLD}.jsonl")
    open(tp_old, "w").close()
    ses.apply_event(evp("SessionStart", OLD, transcript_path=tp_old, host_ts=local(-600)))
    ses.apply_event(evp("UserPromptSubmit", OLD, prompt_id="A", prompt="hace algo", transcript_path=tp_old, host_ts=local(-500)))
    ses.apply_event(evp("Stop", OLD, prompt_id="A", last_assistant_message="hecho", transcript_path=tp_old, host_ts=local(-400)))
    old = st.sessions[OLD]
    assert old["pid"] == PID and old["state"] == "termino"
    # lo que la apunta: la regla "cuando termine" hacia la coordinadora y un envio que recibio
    st.rules.add({"id": "r1", "kind": "on_stop", "from": OLD, "to": COORD, "text": "{respuesta}", "repeat": False,
                      "max_fires": 1, "fired": 0, "enabled": True, "created": st.now()})
    st.rules.add({"id": "r2", "kind": "at", "from": COORD, "to": OLD, "text": "Continuar", "at": st.now(),
                      "repeat": False, "max_fires": 1, "fired": 0, "enabled": True, "created": st.now()})
    ses.add_link(COORD, OLD, "revisá esto", "send")
    return old


def test_clear_la_sesion_nueva_hereda_pid_reglas_y_links(aislado, con_pid):
    logs = con_pid
    sesion_vieja(aislado)
    ses.apply_event(evp("SessionEnd", OLD, reason="clear", host_ts=local(-10)))
    assert st.sessions[OLD]["state"] == "muerta"

    tp_new = str(aislado / f"{NEW}.jsonl")
    ses.apply_event(evp("SessionStart", NEW, source="clear", transcript_path=tp_new, host_ts=local(-9.9)))
    assert OLD not in st.sessions, "la vieja se da de baja"
    new = st.sessions[NEW]
    assert new["pid"] == PID and new["no_console"] is False
    assert [(r["from"], r["to"]) for r in st.rules.items] == [(NEW, COORD), (COORD, NEW)]
    assert [(l["from"], l["to"]) for l in st.links.items] == [(COORD, NEW)]
    assert any("continua como" in m and OLD[:8] in m and NEW[:8] in m for m in logs), logs
    assert not any("ya pertenece" in m for m in logs)
    assert not os.path.exists(os.path.join(st.SESSIONS, f"{OLD}.json"))

    # y la nueva sigue recibiendo sus eventos con normalidad
    ses.apply_event(evp("UserPromptSubmit", NEW, prompt_id="B", prompt="segui", transcript_path=tp_new, host_ts=local(0)))
    ses.apply_event(evp("Stop", NEW, prompt_id="B", last_assistant_message="listo", transcript_path=tp_new, host_ts=local(30)))
    assert new["state"] == "termino"


def test_sin_session_end_pero_con_transcripcion_propia_tambien_continua(aislado, con_pid):
    # el SessionEnd se perdio (hook con timeout de 2 s): la nueva trae un .jsonl propio que existe
    sesion_vieja(aislado)
    tp_new = str(aislado / f"{NEW}.jsonl")
    open(tp_new, "w").close()
    ses.apply_event(evp("UserPromptSubmit", NEW, prompt_id="B", prompt="hola", transcript_path=tp_new, host_ts=local(0)))
    assert OLD not in st.sessions
    assert st.sessions[NEW]["pid"] == PID
    assert st.rules.items[0]["from"] == NEW


def test_prueba_manual_del_hook_no_roba_el_pid(aislado, con_pid):
    logs = con_pid
    old = sesion_vieja(aislado)
    # session_id inventado, mismo pid, sin SessionEnd previo y sin transcripcion propia (o con una
    # que no existe): la duena sigue viva y se queda con el pid y con sus reglas
    for tp in (None, str(aislado / "no-existe.jsonl"), old["transcript_path"]):
        ses.apply_event(evp("UserPromptSubmit", NEW, prompt="prueba", prompt_id="X", host_ts=local(0),
                               **({"transcript_path": tp} if tp else {})))
    assert OLD in st.sessions and old["pid"] == PID
    assert st.sessions[NEW]["pid"] is None
    assert [(r["from"], r["to"]) for r in st.rules.items] == [(OLD, COORD), (COORD, OLD)]
    assert sum("ya pertenece" in m for m in logs) == 3
    assert not any("continua como" in m for m in logs)


# 6. state nunca None ------------------------------------------------------------------

def test_state_nunca_queda_en_none(aislado, monkeypatch):
    s = ses.new_session(SID, "claude", "hook")
    assert s["state"] in st.STATES
    # tarjeta guardada con el estado roto: apply_event la normaliza antes de tocarla
    s["state"] = None
    st.sessions[SID] = s
    ses.apply_event(ev("Notification", notification_type="tool_use", host_ts=local(0)))
    assert s["state"] in st.STATES
    # set_state rechaza valores fuera del contrato
    ses.set_state(s, "corriendo")
    ses.set_state(s, "cualquiera")  # type: ignore[arg-type]
    assert s["state"] == "corriendo"
    # y load_sessions repara el archivo al arrancar
    bad = dict(ses.new_session("aaaa0000-0000-4000-8000-000000000000", "claude", "hook"), state=None, pid=None,
               last_event_ts=st.now())
    with open(os.path.join(st.SESSIONS, f"{bad['session_id']}.json"), "w", encoding="utf-8") as f:
        json.dump(bad, f)
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: False)
    st.sessions.clear()
    ses.load_sessions()
    assert st.sessions[bad["session_id"]]["state"] == "muerta"


# 7. envio desde la UI: chars y pedido reales, y no revivir una sesion con SessionEnd -------------

class _Run:
    def __init__(self, chars):
        self.stdout = json.dumps({"ok": True, "pid": PID, "chars": chars, "enter": 1})
        self.stderr = ""


def test_send_cuenta_y_muestra_el_mensaje_real(aislado, monkeypatch):
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    monkeypatch.setattr(st, "ADJUNTOS", str(aislado / "adjuntos"))
    monkeypatch.setattr(ses, "ADJUNTOS", str(aislado / "adjuntos"))
    typed = []
    monkeypatch.setattr(ses.subprocess, "run", lambda cmd, **k: (typed.append(cmd), _Run(len(cmd[cmd.index("--text") + 1])))[1])
    s = ses.new_session(SID, "claude", "hook")
    s.update({"pid": PID, "state": "termino", "last_event": "Stop"})
    st.sessions[SID] = s
    # mensaje largo: viaja como adjunto .md y en la consola se tipea el envoltorio (143 caracteres)
    msg = "Sos parte de la fase 1.\n" + "x" * 1600
    code, out = ses.send_to_session(s, msg, [])
    assert code == 200
    assert typed[-1][typed[-1].index("--text") + 1].startswith(ses.ATTACH_WRAPPER)
    assert out["chars"] == len(msg.strip()), "el toast cuenta el mensaje, no el envoltorio"
    assert s["last_prompt"].startswith("Sos parte de la fase 1."), "la tarjeta muestra el contenido, no 'Leé el archivo adjunto'"
    assert s["state"] == "corriendo"
    # sesion terminada por SessionEnd (/clear, resume): la consola es de otra; el envio sale pero
    # esta tarjeta no vuelve a 'corriendo'
    s.update({"state": "muerta", "last_event": "SessionEnd"})
    code, out = ses.send_to_session(s, "hola", [])
    assert code == 200 and out["chars"] == 4
    assert s["state"] == "muerta" and s["last_prompt"] == "hola"


# 8. reglas 'at' periodicas: cada every_s segundos, con tope max_fires ------------------------

@pytest.fixture
def periodica(aislado, con_pid, monkeypatch):
    """Destino con consola; el envio no tipea de verdad, se anota. Devuelve (sesion, envios)."""
    sent: list[str] = []
    monkeypatch.setattr(rl, "send_to_session", lambda s, text, atts: (sent.append(text), (200, {"ok": True}))[1])
    s = ses.new_session(SID, "claude", "hook")
    s.update({"pid": PID, "state": "termino", "last_event": "Stop"})
    st.sessions[SID] = s
    return s, sent


def regla_at(every_s, max_fires=3, at_offset_s=-1.0, **k) -> dict:
    import datetime as dt
    at = (dt.datetime.now().astimezone() + dt.timedelta(seconds=at_offset_s)).isoformat(timespec="seconds")
    r = {"id": "p1", "kind": "at", "from": None, "to": SID, "text": "continuá", "at": at,
         "repeat": bool(every_s), "every_s": every_s, "max_fires": max_fires, "skip_busy": bool(every_s),
         "fired": 0, "enabled": True, "created": st.now()}
    r.update(k)
    st.rules.add(r)
    return r


def _at(r: dict):
    import datetime as dt
    return dt.datetime.fromisoformat(r["at"])


def test_at_periodica_dispara_y_queda_habilitada_con_at_corrido(periodica):
    s, sent = periodica
    r = regla_at(600, max_fires=3)
    antes = _at(r)
    rl.fire_rule(r)
    assert sent == ["continuá"]
    assert r["enabled"] is True and r["fired"] == 1 and r["last_result"] == "ok"
    assert (_at(r) - antes).total_seconds() == 600
    assert "disabled_at" not in r
    assert not st.links.items, "sin origen distinto del destino no hay flecha"


def test_at_periodica_se_deshabilita_al_llegar_a_max_fires(periodica):
    s, sent = periodica
    r = regla_at(600, max_fires=3)
    for i in range(3):
        r["at"] = st.now()  # vencida otra vez
        rl.fire_rule(r)
    assert len(sent) == 3 and r["fired"] == 3
    assert r["enabled"] is False and r.get("disabled_at")
    # una cuarta pasada del bucle no la toma (esta deshabilitada) y aunque se fuerce no dispara de mas
    assert not any(x.get("enabled") for x in st.rules.items if x["id"] == "p1")


def test_at_periodica_saltea_sin_contar_si_el_destino_corre(periodica):
    s, sent = periodica
    s["state"] = "corriendo"
    r = regla_at(600, max_fires=3)
    antes = _at(r)
    rl.fire_rule(r)
    assert sent == [] and r["fired"] == 0 and r["enabled"] is True
    assert r["last_result"] == "salteado: destino ocupado"
    assert (_at(r) - antes).total_seconds() == 600
    # sin skip_busy se manda igual aunque este corriendo
    r["skip_busy"] = False
    r["at"] = st.now()
    rl.fire_rule(r)
    assert sent == ["continuá"] and r["fired"] == 1


def test_at_periodica_atrasada_horas_avanza_hasta_el_futuro_de_un_salto(periodica):
    import datetime as dt
    s, sent = periodica
    r = regla_at(600, max_fires=5, at_offset_s=-5 * 3600)   # el server estuvo caido 5 h
    rl.fire_rule(r)
    ahora = dt.datetime.now().astimezone()
    assert sent == ["continuá"] and r["fired"] == 1, "los periodos perdidos no se disparan"
    assert ahora < _at(r) <= ahora + dt.timedelta(seconds=600)
    # y cae sobre la grilla original (multiplo de 600 s desde el at inicial)
    inicial = ahora - dt.timedelta(hours=5)
    resto = round((_at(r) - inicial).total_seconds()) % 600
    assert min(resto, 600 - resto) <= 1   # `at` se guarda sin microsegundos: puede caer 1 s abajo


def test_at_sin_every_s_sigue_siendo_de_un_disparo(periodica):
    s, sent = periodica
    r = regla_at(None, max_fires=1)
    antes = r["at"]
    rl.fire_rule(r)
    assert sent == ["continuá"] and r["fired"] == 1
    assert r["enabled"] is False and r.get("disabled_at") and r["at"] == antes


def test_at_fields_valida_every_s_y_pone_los_defaults():
    ok, err = server.at_fields({"every_s": 30})
    assert ok is None and err == "every_s debe ser al menos 60 segundos"
    for malo in ("x", 12.5, True, [600]):
        ok, err = server.at_fields({"every_s": malo})
        assert ok is None and "entero" in err, malo
    # periodica sin mas datos: 5 disparos, saltea ocupado, repeat para las etiquetas (fired/max_fires)
    ok, err = server.at_fields({"every_s": 1800})
    assert err is None and ok == {"every_s": 1800, "max_fires": 5, "skip_busy": True, "repeat": True}
    ok, _ = server.at_fields({"every_s": "600", "max_fires": 99, "skip_busy": False})
    assert ok == {"every_s": 600, "max_fires": 50, "skip_busy": False, "repeat": True}
    # un disparo (como hoy): sin every_s no aplica el salteo
    ok, _ = server.at_fields({"max_fires": 1})
    assert ok == {"every_s": None, "max_fires": 1, "skip_busy": False, "repeat": False}
    # PUT: null explicito la vuelve de un disparo; sin every_s en el body se conserva lo que tenia
    cur = {"every_s": 600, "max_fires": 5, "skip_busy": True, "repeat": True}
    ok, _ = server.at_fields({"every_s": None}, cur)
    assert ok["every_s"] is None and ok["repeat"] is False and ok["max_fires"] == 5
    ok, _ = server.at_fields({"max_fires": 2}, cur)
    assert ok == {"every_s": 600, "max_fires": 2, "skip_busy": True, "repeat": True}


# 9. fase 2: titulo desde el adjunto, idle_prompt sin pregunta, programadas que chocan, coordinadora

def test_titulo_del_adjunto_le_gana_al_ai_title(aislado):
    md = aislado / "20260906-encargo.md"
    md.write_text("\n# Encargo B: tarjetas y flechas de la fase 2\n\ntexto del encargo\n", encoding="utf-8")
    s = ses.new_session(SID, "claude", "hook")
    st.sessions[SID] = s
    # tarjeta vieja: el envoltorio quedo en last_prompt y la transcripcion trae el ai-title inutil
    s["last_prompt"] = f"{ses.ATTACH_WRAPPER} Adjunto: {md}"
    ses.choose_title(s, "Mensaje 20260906")
    assert s["title"] == "Encargo B: tarjetas y flechas de la fase 2" and s["title_source"] == "prompt"
    assert s["last_prompt"].startswith("# Encargo B"), "la tarjeta muestra el contenido, no el envoltorio"
    assert s["last_attachment"] == str(md)
    # el hook real: UserPromptSubmit con el envoltorio, y despues el ai-title de la transcripcion no lo pisa
    ses.apply_event(ev("UserPromptSubmit", prompt_id="A", prompt=f"{ses.ATTACH_WRAPPER} Adjunto: {md}", host_ts=local(0)))
    assert s["title"] == "Encargo B: tarjetas y flechas de la fase 2"
    ses.choose_title(s, "Revisar archivo de tareas")
    assert s["title"] == "Encargo B: tarjetas y flechas de la fase 2"
    # sin encabezado: la primera linea no vacia
    md.write_text("\n\nprimera linea del pedido\nsegunda\n", encoding="utf-8")
    ses.choose_title(s, "Mensaje")
    assert s["title"] == "primera linea del pedido"
    # el titulo puesto a mano sigue mandando
    ses.set_title(s, "Mi titulo")
    ses.choose_title(s, "Mensaje 20260906")
    assert s["title"] == "Mi titulo" and s["title_source"] == "user"


def test_bad_title_reconoce_mensaje_y_encargo():
    for t in ("Mensaje", "mensaje 20260906", "Mensaje del 20260905", "MENSAJE DEL 6 de septiembre", "Encargo", "Leer archivo adjunto", "", None):
        assert ses.bad_title(t), t
    for t in ("Encargo B: tarjetas", "Mensaje a Marian sobre el tablero", "Reglas periodicas"):
        assert not ses.bad_title(t), t


def test_idle_prompt_solo_es_te_necesita_con_pregunta_o_sin_pedido(aislado):
    idle = ev("Notification", notification_type="idle_prompt", message="Claude is waiting for your input", host_ts=local(60))
    # informe entregado sin pregunta: queda en termino, sin needs
    ses.apply_event(ev("UserPromptSubmit", prompt_id="A", prompt="hace X", host_ts=local(-60)))
    ses.apply_event(ev("Stop", prompt_id="A", last_assistant_message="Listo, quedó en X.", host_ts=local(0)))
    ses.apply_event(idle)
    s = st.sessions[SID]
    assert s["state"] == "termino" and s["needs"] is None
    # la respuesta termina en pregunta: si te necesita
    ses.apply_event(ev("UserPromptSubmit", prompt_id="B", prompt="hace Y", host_ts=local(10)))
    ses.apply_event(ev("Stop", prompt_id="B", last_assistant_message="Hice Y. ¿Sigo con Z?", host_ts=local(20)))
    ses.apply_event(idle)
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "idle"
    # tarjeta libre, nunca tuvo pedido: te_necesita/idle como hoy (para "Darle trabajo")
    st.sessions.clear()
    ses.apply_event(ev("SessionStart", host_ts=local(0)))
    ses.apply_event(idle)
    s = st.sessions[SID]
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "idle"
    # permission_prompt no cambia
    ses.apply_event(ev("UserPromptSubmit", prompt_id="C", prompt="hace W", host_ts=local(30)))
    ses.apply_event(ev("Notification", notification_type="permission_prompt", message="Bash", host_ts=local(31)))
    assert s["state"] == "te_necesita" and s["needs"]["kind"] == "permission"


def test_dos_programadas_al_mismo_minuto_chocan_y_replace_reemplaza(aislado, con_pid, monkeypatch):
    import datetime as dt
    s = ses.new_session(SID, "claude", "hook")
    st.sessions[SID] = s
    at = dt.datetime.now().astimezone().replace(microsecond=0) + dt.timedelta(hours=1)
    code, r1 = server.create_rule({"kind": "at", "to": SID, "text": "Continuar", "at": at.isoformat()})
    assert code == 200
    # otro texto, 90 s despues, periodica: choca igual
    code, res = server.create_rule({"kind": "at", "to": SID, "text": "continua", "at": (at + dt.timedelta(seconds=90)).isoformat(), "every_s": 600})
    assert code == 409
    assert res["rule_id"] == r1["id"] and res["replace"] is True and res["text"] == "Continuar" and res["at"] == r1["at"]
    assert res["error"] == f"ya hay una programada a las {at.strftime('%H:%M')} para esa sesión"
    assert len(st.rules.items) == 1
    # a 3 min no choca
    code, r3 = server.create_rule({"kind": "at", "to": SID, "text": "otra", "at": (at + dt.timedelta(minutes=3)).isoformat()})
    assert code == 200 and len(st.rules.items) == 2
    # con replace: true la nueva reemplaza a la que chocaba
    code, r4 = server.create_rule({"kind": "at", "to": SID, "text": "continua", "at": at.isoformat(), "every_s": 600, "replace": True})
    assert code == 200 and r4["every_s"] == 600
    assert [r["id"] for r in st.rules.items] == [r3["id"], r4["id"]]
    # validaciones que ya existian siguen pasando por aca
    assert server.create_rule({"kind": "at", "to": SID, "text": "x", "at": at.isoformat(), "every_s": 30})[0] == 400
    assert server.create_rule({"kind": "at", "to": "nadie", "text": "x", "at": at.isoformat()})[0] == 404
    assert server.create_rule({"kind": "at", "to": SID, "text": "x", "at": "ayer"})[0] == 400


def test_coordinadora_una_por_repo(aislado, con_pid):
    A, B, C = COORD, SID, NEW
    for sid, repo in ((A, "lienzo"), (B, "lienzo"), (C, "otro")):
        s = st.sessions.get(sid) or ses.new_session(sid, "claude", "hook")
        s["repo"] = repo
        st.sessions[sid] = s
    assert st.sessions[A]["coordinator"] is False
    ses.set_coordinator(st.sessions[B], True)
    ses.set_coordinator(st.sessions[C], True)
    changed = ses.set_coordinator(st.sessions[A], True)
    assert [x["session_id"] for x in changed] == [B, A]
    assert st.sessions[A]["coordinator"] is True and st.sessions[B]["coordinator"] is False
    assert st.sessions[C]["coordinator"] is True, "otro repo: no se toca"
    # persistido, y apagar solo apaga esa
    with open(os.path.join(st.SESSIONS, f"{A}.json"), encoding="utf-8") as f:
        assert json.load(f)["coordinator"] is True
    ses.set_coordinator(st.sessions[A], False)
    assert st.sessions[A]["coordinator"] is False and st.sessions[C]["coordinator"] is True


def test_coordinadora_se_hereda_con_el_pid(aislado, con_pid):
    old = sesion_vieja(aislado)
    old["coordinator"] = True
    ses.apply_event(evp("SessionEnd", OLD, reason="clear", host_ts=local(-10)))
    tp_new = str(aislado / f"{NEW}.jsonl")
    ses.apply_event(evp("SessionStart", NEW, source="clear", transcript_path=tp_new, host_ts=local(-9.9)))
    assert st.sessions[NEW]["coordinator"] is True


# 10. HTTP: el body se lee siempre, aunque la respuesta sea 403 o 404 -----------------------------

def test_keep_alive_tras_un_404_sigue_contestando(aislado):
    """Antes, un POST a una ruta desconocida (o sin X-Lienzo) contestaba sin leer el cuerpo; el
    siguiente request de la misma conexion keep-alive leia ese cuerpo como linea de pedido y daba 501."""
    import http.client
    import threading
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for path, headers, first in (("/nada", {"X-Lienzo": "1"}, 404), ("/rules", {}, 403), ("/rules", {"X-Lienzo": "1"}, 400)):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
            c.request("POST", path, body='{"kind": "x"}', headers={"Content-Type": "application/json", **headers})
            r = c.getresponse()
            r.read()
            assert r.status == first, (path, r.status)
            c.request("GET", "/health")
            r2 = c.getresponse()
            r2.read()
            assert r2.status == 200, f"tras {first} en {path}: {r2.status}"
            c.close()
    finally:
        srv.shutdown()


def test_la_cabecera_de_un_informe_recibido_no_es_titulo():
    assert ses.bad_title("Mensaje de lienzo (claude) sobre 'Encargo R1: revisión':")
    assert ses.bad_title("Mensaje 20260906")
    assert not ses.bad_title("Encargo R1: revisión de código")


def test_el_adjunto_de_un_informe_recibido_no_titula_la_coordinadora(tmp_path):
    md = tmp_path / "informe.md"
    md.write_text("Mensaje de lienzo (claude) sobre 'Encargo R1':\nTodo listo.", encoding="utf-8")
    s = {"last_prompt": "Mensaje de lienzo (claude) sobre 'Encargo R1':\nTodo listo.", "last_attachment": str(md)}
    assert ses.attachment_title(s) is None
    md2 = tmp_path / "encargo.md"
    md2.write_text("# Encargo R1: revisión\nSos una sesión…", encoding="utf-8")
    assert ses.attachment_title({"last_attachment": str(md2)}) == "Encargo R1: revisión"
