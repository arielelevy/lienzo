"""Clasificacion corriendo/termino en lienzo/sessions.py (antes server.py): el Stop tardio de un pedido encolado y la
correccion desde la transcripcion. Sin red ni hilos: apply_event y refresh_from_transcript directos,
con el registro de sesiones apuntando a un directorio temporal."""

import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# El orden importa y no se ordena solo: `from lienzo import server` es lo que agrega lienzo/ al
# sys.path y engancha rules a sessions; recien despues se pueden importar los modulos sueltos.
from lienzo import server
import rules as rl
import sessions as ses
import state as st

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude", "projects", "D--Apps-lienzo")
SID = "599a7e3e-0000-4000-8000-000000000000"
T0 = "2026-09-05T20:41:53.135-03:00"  # turn_duration del caso medido, en hora local


def local(offset_s: float) -> str:
    import datetime as dt

    return (dt.datetime.fromisoformat(T0) + dt.timedelta(seconds=offset_s)).isoformat(timespec="milliseconds")


def utc(offset_s: float) -> str:
    import datetime as dt

    d = dt.datetime.fromisoformat(T0).astimezone(dt.UTC) + dt.timedelta(seconds=offset_s)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp, sin SSE ni hilos de reglas: lo que se mide es el estado de la tarjeta."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(
        server, "log", lambda msg: None
    )  # server importa log por nombre: el parche sobre st no lo alcanza
    st.sessions.clear()
    # transcript_stat es estado de modulo y viaja entre tests: dos transcripciones distintas de 3
    # bytes escritas en el mismo segundo tienen la misma firma y el "crecio" del test siguiente daba False
    st.transcript_stat.clear()
    yield tmp_path
    st.sessions.clear()
    st.transcript_stat.clear()


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
        {
            "type": "assistant",
            "timestamp": utc(-0.1),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Listo el primero."}]},
        },
        {"type": "system", "subtype": "stop_hook_summary", "timestamp": utc(-0.01)},
        {"type": "system", "subtype": "turn_duration", "timestamp": utc(0)},
        {
            "type": "user",
            "timestamp": utc(0.06),
            "promptId": "B",
            "message": {"role": "user", "content": "segundo, largo"},
        },
        {
            "type": "assistant",
            "timestamp": utc(18),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Voy."}]},
        },
        {
            "type": "assistant",
            "timestamp": utc(25),
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
            },
        },
        {
            "type": "user",
            "timestamp": utc(27),
            "promptId": "B",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a b c"}]},
        },
    ]


def write_jsonl(path, rows) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
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
    # encargo X1: mientras corre, la tarjeta muestra lo ultimo que el agente escribio ("Voy."), no
    # el nombre de la herramienta; "usando Bash" quedo como respaldo para cuando no escribio nada
    assert s["last_reply"] == "Voy."


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
            nxt = next(
                (
                    j
                    for j in range(i + 1, len(rows))
                    if rows[j].get("type") in ("user", "assistant") and not rows[j].get("isSidechain")
                ),
                None,
            )
            if nxt is None or rows[nxt].get("type") != "user":
                continue
            c = (rows[nxt].get("message") or {}).get("content")
            if not isinstance(c, str) or c.lstrip().startswith("<"):
                continue
            a, b = st.parse_ts(r.get("timestamp")), st.parse_ts(rows[nxt].get("timestamp"))
            if not a or not b or (b - a).total_seconds() > 1.0:
                continue
            end = next(
                (
                    j
                    for j in range(nxt + 1, len(rows))
                    if rows[j].get("type") == "user" and isinstance((rows[j].get("message") or {}).get("content"), list)
                ),
                None,
            )
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
    ses.apply_event(
        evp("UserPromptSubmit", OLD, prompt_id="A", prompt="hace algo", transcript_path=tp_old, host_ts=local(-500))
    )
    ses.apply_event(
        evp("Stop", OLD, prompt_id="A", last_assistant_message="hecho", transcript_path=tp_old, host_ts=local(-400))
    )
    old = st.sessions[OLD]
    assert old["pid"] == PID and old["state"] == "termino"
    # lo que la apunta: la regla "cuando termine" hacia la coordinadora y un envio que recibio
    st.rules.add(
        {
            "id": "r1",
            "kind": "on_stop",
            "from": OLD,
            "to": COORD,
            "text": "{respuesta}",
            "repeat": False,
            "max_fires": 1,
            "fired": 0,
            "enabled": True,
            "created": st.now(),
        }
    )
    st.rules.add(
        {
            "id": "r2",
            "kind": "at",
            "from": COORD,
            "to": OLD,
            "text": "Continuar",
            "at": st.now(),
            "repeat": False,
            "max_fires": 1,
            "fired": 0,
            "enabled": True,
            "created": st.now(),
        }
    )
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
    ses.apply_event(
        evp("UserPromptSubmit", NEW, prompt_id="B", prompt="segui", transcript_path=tp_new, host_ts=local(0))
    )
    ses.apply_event(
        evp("Stop", NEW, prompt_id="B", last_assistant_message="listo", transcript_path=tp_new, host_ts=local(30))
    )
    assert new["state"] == "termino"


def test_sin_session_end_pero_con_transcripcion_propia_tambien_continua(aislado, con_pid):
    # el SessionEnd se perdio (hook con timeout de 2 s): la nueva trae un .jsonl propio que existe
    sesion_vieja(aislado)
    tp_new = str(aislado / f"{NEW}.jsonl")
    open(tp_new, "w").close()
    ses.apply_event(
        evp("UserPromptSubmit", NEW, prompt_id="B", prompt="hola", transcript_path=tp_new, host_ts=local(0))
    )
    assert OLD not in st.sessions
    assert st.sessions[NEW]["pid"] == PID
    assert st.rules.items[0]["from"] == NEW


def test_prueba_manual_del_hook_no_roba_el_pid(aislado, con_pid):
    logs = con_pid
    old = sesion_vieja(aislado)
    # session_id inventado, mismo pid, sin SessionEnd previo y sin transcripcion propia (o con una
    # que no existe): la duena sigue viva y se queda con el pid y con sus reglas
    for tp in (None, str(aislado / "no-existe.jsonl"), old["transcript_path"]):
        ses.apply_event(
            evp(
                "UserPromptSubmit",
                NEW,
                prompt="prueba",
                prompt_id="X",
                host_ts=local(0),
                **({"transcript_path": tp} if tp else {}),
            )
        )
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
    bad = dict(
        ses.new_session("aaaa0000-0000-4000-8000-000000000000", "claude", "hook"),
        state=None,
        pid=None,
        last_event_ts=st.now(),
    )
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
    monkeypatch.setattr(
        ses.subprocess, "run", lambda cmd, **k: (typed.append(cmd), _Run(len(cmd[cmd.index("--text") + 1])))[1]
    )
    s = ses.new_session(SID, "claude", "hook")
    s.update({"pid": PID, "state": "termino", "last_event": "Stop"})
    st.sessions[SID] = s
    # mensaje largo: viaja como adjunto .md y en la consola se tipea el envoltorio (143 caracteres)
    msg = "Sos parte de la fase 1.\n" + "x" * 1600
    code, out = ses.send_to_session(s, msg, [])
    assert code == 200
    assert typed[-1][typed[-1].index("--text") + 1].startswith(ses.ATTACH_WRAPPER)
    assert out["chars"] == len(msg.strip()), "el toast cuenta el mensaje, no el envoltorio"
    assert s["last_prompt"].startswith(
        "Sos parte de la fase 1."
    ), "la tarjeta muestra el contenido, no 'Leé el archivo adjunto'"
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
    r = {
        "id": "p1",
        "kind": "at",
        "from": None,
        "to": SID,
        "text": "continuá",
        "at": at,
        "repeat": bool(every_s),
        "every_s": every_s,
        "max_fires": max_fires,
        "skip_busy": bool(every_s),
        "fired": 0,
        "enabled": True,
        "created": st.now(),
    }
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
    r = regla_at(600, max_fires=5, at_offset_s=-5 * 3600)  # el server estuvo caido 5 h
    rl.fire_rule(r)
    ahora = dt.datetime.now().astimezone()
    assert sent == ["continuá"] and r["fired"] == 1, "los periodos perdidos no se disparan"
    assert ahora < _at(r) <= ahora + dt.timedelta(seconds=600)
    # y cae sobre la grilla original (multiplo de 600 s desde el at inicial)
    inicial = ahora - dt.timedelta(hours=5)
    resto = round((_at(r) - inicial).total_seconds()) % 600
    assert min(resto, 600 - resto) <= 1  # `at` se guarda sin microsegundos: puede caer 1 s abajo


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
    ses.apply_event(
        ev("UserPromptSubmit", prompt_id="A", prompt=f"{ses.ATTACH_WRAPPER} Adjunto: {md}", host_ts=local(0))
    )
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
    for t in (
        "Mensaje",
        "mensaje 20260906",
        "Mensaje del 20260905",
        "MENSAJE DEL 6 de septiembre",
        "Encargo",
        "Leer archivo adjunto",
        "",
        None,
    ):
        assert ses.bad_title(t), t
    for t in ("Encargo B: tarjetas", "Mensaje a Marian sobre el tablero", "Reglas periodicas"):
        assert not ses.bad_title(t), t


def test_idle_prompt_solo_es_te_necesita_con_pregunta_o_sin_pedido(aislado):
    idle = ev(
        "Notification", notification_type="idle_prompt", message="Claude is waiting for your input", host_ts=local(60)
    )
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
    code, res = server.create_rule(
        {"kind": "at", "to": SID, "text": "continua", "at": (at + dt.timedelta(seconds=90)).isoformat(), "every_s": 600}
    )
    assert code == 409
    assert (
        res["rule_id"] == r1["id"] and res["replace"] is True and res["text"] == "Continuar" and res["at"] == r1["at"]
    )
    assert res["error"] == f"ya hay una programada a las {at.strftime('%H:%M')} para esa sesión"
    assert len(st.rules.items) == 1
    # a 3 min no choca
    code, r3 = server.create_rule(
        {"kind": "at", "to": SID, "text": "otra", "at": (at + dt.timedelta(minutes=3)).isoformat()}
    )
    assert code == 200 and len(st.rules.items) == 2
    # con replace: true la nueva reemplaza a la que chocaba
    code, r4 = server.create_rule(
        {"kind": "at", "to": SID, "text": "continua", "at": at.isoformat(), "every_s": 600, "replace": True}
    )
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
        for path, headers, first in (
            ("/nada", {"X-Lienzo": "1"}, 404),
            ("/rules", {}, 403),
            ("/rules", {"X-Lienzo": "1"}, 400),
        ):
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


# 10. simplificacion del backend: las funciones chicas de turn_activity y el adjunto


def blk(name, inp=None, err=False):
    return {"kind": "tool", "name": name, "input": inp or {}, "result": {"is_error": err}}


def test_turn_activity_cuenta_archivos_comando_y_errores_en_una_pasada():
    t = {
        "blocks": [
            {"kind": "text", "text": "arranco"},
            blk("Read", {"file_path": r"D:\Apps\lienzo\lienzo\state.py"}),
            blk("Bash", {"command": r'cd "D:\Apps\lienzo" && python -m pytest tests -q'}, err=True),
            blk("Edit", {"file_path": "D:/Apps/lienzo/lienzo/sessions.py"}),
            blk("Read", {"file_path": "D:/Apps/lienzo/lienzo/sessions.py"}),  # repetido: un solo nombre
            {"kind": "thinking", "text": "no cuenta"},
        ]
    }
    a = ses.turn_activity(t)
    assert a["tool_count"] == 4
    assert a["last_files"] == ["sessions.py", "state.py"], "del mas nuevo al mas viejo, sin repetir"
    assert a["last_cmd"] == "python -m pytest tests -q", "el cd del principio no va"
    assert a["tool_errors"] == 1
    assert list(a) == ["tool_count", "last_files", "last_cmd", "tool_errors"]


def test_turn_activity_sin_herramientas_no_inventa_nada():
    a = ses.turn_activity({"blocks": [{"kind": "text", "text": "hola"}]})
    assert a == {"tool_count": 0, "last_files": [], "last_cmd": None, "tool_errors": 0}
    assert ses.turn_activity({}) == a


def test_using_tool_es_la_herramienta_mas_nueva():
    assert ses.using_tool({"blocks": [blk("Read"), blk("Bash")]}) == "usando Bash"
    assert ses.using_tool({"blocks": [{"kind": "text", "text": "x"}]}) is None
    assert ses.using_tool({}) is None


def test_turn_prompt_descarta_el_turno_cortado_por_la_cola():
    assert ses.turn_prompt({"prompt": "hace esto"}) == "hace esto"
    assert ses.turn_prompt({"prompt": "(turno anterior al corte)"}) is None
    assert ses.turn_prompt({"prompt": ""}) is None
    assert ses.turn_prompt({}) is None


def test_attachment_path_toma_el_ultimo_adjunto_md_que_existe(tmp_path):
    md = tmp_path / "mensaje.md"
    md.write_text("# Hola", encoding="utf-8")
    assert ses.attachment_path(f"{ses.ATTACH_WRAPPER} Adjunto: {md}") == str(md)
    # varios adjuntos: gana el primero que sea .md y exista
    assert ses.attachment_path(f"{ses.ATTACH_WRAPPER} Adjunto: {tmp_path / 'no-esta.md'} Adjunto: {md}") == str(md)
    assert ses.attachment_path("un pedido cualquiera") is None
    assert ses.attachment_path(f"{ses.ATTACH_WRAPPER} Adjunto: {tmp_path / 'foto.png'}") is None


# 11. la carrera del lock: lo lento corre afuera, y al volver la tarjeta puede haberse ido


def lock_libre() -> bool:
    """Si el lock global esta libre AHORA. Se prueba desde otro hilo a proposito: es reentrante, y
    desde el hilo que lo tiene tomado un acquire() siempre daria True."""
    import threading

    res = []

    def probe():
        got = st.lock.acquire(blocking=False)
        res.append(got)
        if got:
            st.lock.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join()
    return res[0]


def tarjeta_claude(sid=SID):
    s = ses.new_session(sid, "claude", "hook")
    s.update({"pid": PID, "alive": True, "state": "termino"})
    st.sessions[sid] = s
    return s


def test_el_lock_esta_libre_mientras_se_lee_la_pantalla(aislado, monkeypatch):
    """read_screen es un subproceso de 183 ms: con el lock tomado frenaria los hooks y el HTTP."""
    s = tarjeta_claude()
    visto = []
    leido = {"ok": True, "area": {"input": "hola", "placeholder": False}}
    monkeypatch.setattr(ses, "read_screen", lambda pid: (visto.append(lock_libre()), leido)[1])
    ses.screen_once()
    assert visto == [True], "screen_once tenia el lock tomado mientras corria el subproceso"
    assert s["suggestion"] == "hola"


def test_la_pantalla_no_revive_una_tarjeta_borrada_mientras_se_leia(aislado, monkeypatch):
    """Entre el read_screen y el touch la tarjeta puede haberse borrado: el touch le rehacia el
    archivo en disco y volvia como fantasma en el arranque siguiente."""
    tarjeta_claude()

    def leyendo(pid):
        ses.drop_session(SID, "borrada desde la UI mientras se leia")
        return {"ok": True, "area": {"input": "hola", "placeholder": False}}

    monkeypatch.setattr(ses, "read_screen", leyendo)
    ses.screen_once()
    assert SID not in st.sessions
    assert not os.path.exists(os.path.join(str(aislado), f"{SID}.json")), "la tarjeta borrada revivio"


def test_el_lock_esta_libre_mientras_se_parsea_la_transcripcion(aislado, monkeypatch, tmp_path):
    """El parseo son 22 ms de mediana por sesion, cada 2 s: va fuera del lock (read_transcript),
    y solo el volcado a la tarjeta (apply_transcript) va adentro."""
    tp = tmp_path / "t.jsonl"
    tp.write_text("{}\n", encoding="utf-8")
    s = tarjeta_claude()
    s["transcript_path"] = str(tp)
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    visto = []
    monkeypatch.setattr(ses, "read_transcript", lambda x: (visto.append(lock_libre()), None)[1])
    dentro = []
    monkeypatch.setattr(ses.state, "broadcast", lambda ev: dentro.append(ev.get("type")))
    ses.check_liveness(SID)
    assert visto == [True], "check_liveness tenia el lock tomado mientras parseaba la transcripcion"
    assert "transcript" in dentro, "la transcripcion crecio: hay que avisar igual"


def test_la_transcripcion_no_revive_una_tarjeta_borrada_mientras_se_leia(aislado, monkeypatch, tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text("{}\n", encoding="utf-8")
    s = tarjeta_claude()
    s["transcript_path"] = str(tp)
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)

    def leyendo(x):
        ses.drop_session(SID, "borrada mientras se leia")
        return {"meta": {}, "turns": [], "title": None}

    monkeypatch.setattr(ses, "read_transcript", leyendo)
    ses.check_liveness(SID)
    assert SID not in st.sessions
    assert not os.path.exists(os.path.join(str(aislado), f"{SID}.json")), "la tarjeta borrada revivio"


def test_el_lock_esta_libre_mientras_send_py_tipea(aislado, monkeypatch):
    """send.py puede tardar hasta 60 s: con el lock tomado congelaria el tablero entero."""
    s = tarjeta_claude()
    s["last_event"] = "Stop"
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    visto = []
    monkeypatch.setattr(ses.subprocess, "run", lambda cmd, **k: (visto.append(lock_libre()), _Run(4))[1])
    code, _ = ses.send_to_session(s, "hola", [])
    assert code == 200 and visto == [True], "send_to_session tenia el lock tomado mientras tipeaba"
    assert s["state"] == "corriendo" and s["last_prompt"] == "hola"


# 12. encargo V2: la firma que quedaba colgada, el 500 que hablaba de mas, y la carrera de verdad


def test_drop_session_limpia_la_firma_de_la_transcripcion(aislado, tmp_path):
    """transcript_stat es un dict de modulo: sin limpiarlo quedaba una entrada por cada tarjeta que
    existio desde que arranco el server, para siempre."""
    tp = tmp_path / "t.jsonl"
    tp.write_text("{}", encoding="utf-8")
    s = tarjeta_claude()
    s["transcript_path"] = str(tp)
    st.transcript_stat[SID] = (1, 2)
    ses.drop_session(SID, "borrada en el test")
    assert SID not in st.transcript_stat, "la firma de una tarjeta borrada quedo colgada"
    assert SID not in st.sessions


def test_el_500_no_le_manda_al_cliente_el_texto_de_la_excepcion(aislado, monkeypatch):
    """Por el tunel, str(e) sale hacia afuera y puede llevar rutas y nombres de la maquina. Al
    cliente le tiene que llegar un id corto, y el detalle quedar en el log con el mismo id."""
    import http.client
    import threading

    secreto = r"C:\Users\alguien\.lienzo\secreto.json no existe"
    monkeypatch.setattr(server, "public_config", lambda: (_ for _ in ()).throw(RuntimeError(secreto)))
    logueado = []
    monkeypatch.setattr(server, "log", lambda msg: logueado.append(str(msg)))
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
        c.request("GET", "/config")
        r = c.getresponse()
        cuerpo = json.loads(r.read())
        c.close()
    finally:
        srv.shutdown()
    assert r.status == 500
    assert secreto not in json.dumps(cuerpo), f"el 500 le mando la excepcion al cliente: {cuerpo}"
    eid = cuerpo["error_id"]
    assert len(eid) == 8 and eid in cuerpo["error"], "el id tiene que verse en el campo que muestra la UI"
    detalle = "\n".join(logueado)
    assert eid in detalle and secreto in detalle, "el detalle tiene que quedar en el log, con el mismo id"


def test_dos_hilos_sobre_la_misma_tarjeta_no_la_dejan_en_un_estado_imposible(aislado, monkeypatch):
    """El invariante de set_state: si el estado no es te_necesita, `needs` va en None. Con
    check_liveness escribiendo el dict sin el lock, este intercalado lo rompia y quedaba una tarjeta
    'muerta' con un permiso pendiente colgado, que la UI muestra y nadie puede contestar:

        apply_event  set_state(te_necesita) -> state="te_necesita"
        liveness     set_state(muerta)      -> state="muerta"; needs=None
        apply_event  s["needs"] = {...}     -> state="muerta" CON needs

    El muestreo tambien toma el lock: con el arreglo no puede ver un estado a medio escribir.
    Medido contra el check_liveness viejo: 12 de 12 corridas lo detectan (200 a 390 muestras rotas
    cada una); contra el nuevo, 0 de 12."""
    import threading

    tarjeta_claude()
    monkeypatch.setattr(ses, "save_session", lambda s: None)  # sin tocar disco: esto corre miles de veces
    vivo = [True]
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: vivo[0])
    rondas, parar, rotos = 300, threading.Event(), []

    def hooks():
        for _ in range(rondas):
            ses.apply_event(ev("PermissionRequest", tool_name="Bash", tool_use_id="t1", host_ts=local(0)))
            ses.apply_event(ev("PermissionDecision", host_ts=local(1)))
        parar.set()

    def liveness():
        while not parar.is_set():
            vivo[0] = not vivo[0]
            ses.check_liveness(SID)

    def mirar():
        while not parar.is_set():
            with st.lock:
                s = st.sessions.get(SID)
                if s and s["state"] != "te_necesita" and s.get("needs") is not None:
                    rotos.append((s["state"], s["needs"]))

    hilos = [threading.Thread(target=f) for f in (hooks, liveness, mirar)]
    antes = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # sin esto el GIL casi no cambia de hilo y la ventana no se pisa nunca
    try:
        for t in hilos:
            t.start()
        for t in hilos:
            t.join(timeout=30)
    finally:
        parar.set()
        sys.setswitchinterval(antes)
    assert not any(t.is_alive() for t in hilos), "algun hilo quedo trabado: revisar deadlocks"
    assert not rotos, f"{len(rotos)} muestras con la tarjeta en un estado imposible, la primera {rotos[0]}"


# 13. encargo X1: mientras corre, la tarjeta dice lo que el agente esta escribiendo


def texto(t, phase=None):
    return {"kind": "text", "text": t, "phase": phase}


def turno(blocks, final="", ended=False):
    """Turno como lo arma transcripts.turns: `final` es el ultimo bloque de texto no vacio."""
    return {"blocks": blocks, "final": final, "ended": ended}


def test_turn_say_es_el_ultimo_texto_del_agente_no_la_herramienta():
    t = turno(
        [
            texto("Arranco por el backend."),
            blk("Read", {"file_path": "a.py"}),
            texto("Ahora parto refresh_from_transcript en dos:"),
            blk("Bash", {"command": "pytest"}),
        ],
        final="Ahora parto refresh_from_transcript en dos:",
    )
    assert ses.turn_say(t) == "Ahora parto refresh_from_transcript en dos:"
    assert ses.using_tool(t) == "usando Bash", "la herramienta sigue estando, pero ya no es lo que se muestra"


def test_turn_say_cae_a_la_herramienta_si_todavia_no_escribio_nada():
    t = turno([blk("Bash", {"command": "pytest"})])
    assert ses.turn_say(t) == "usando Bash"
    assert ses.turn_say(turno([])) is None, "sin texto ni herramientas no hay nada que decir"
    # un bloque de texto en blanco no cuenta: transcripts no lo pone en `final`
    assert ses.turn_say(turno([texto("   ")])) is None


def test_turn_say_no_recorta_la_respuesta():
    """Estaba cortada a 600 caracteres: la tarjeta no lo notaba (el CSS la corta en 6 lineas) pero
    su boton de copiar copiaba media respuesta y el freno del on_stop nunca veia el '?' del final.
    Medido: 86 de 124 finales pasan de 600 caracteres."""
    largo = "Lo que medí: " + "un renglón más de detalle. " * 60 + "¿Sigo con el resto?"
    assert len(largo) > 600
    t = turno([texto(largo)], final=largo)
    assert ses.turn_say(t) == largo
    assert "…" not in ses.turn_say(t)
    assert ses.turn_say(t).endswith("?"), "el freno del on_stop mira justo esto"


def test_turn_say_no_muestra_el_pensamiento():
    """kind 'thinking' no pasa por add_text, asi que nunca entra en `final`: el toggle
    "Pensamiento" del menu es para la conversacion, no para la tarjeta."""
    t = turno(
        [{"kind": "thinking", "text": "El usuario quiere que revise el lock..."}, blk("Read", {"file_path": "a.py"})]
    )
    dicho = ses.turn_say(t)
    assert dicho == "usando Read", "sin texto del agente, el respaldo es la herramienta"
    assert "lock" not in (dicho or ""), "el pensamiento no puede llegar a la tarjeta"


def test_la_tarjeta_con_hooks_muestra_el_comentario_del_turno_abierto(aislado):
    """El caso de la captura: sesion corriendo con hooks. Antes decia 'usando Bash'."""
    rows = rows_encolado() + [
        {
            "type": "assistant",
            "timestamp": utc(30),
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Ahora mido cuanto tarda el parseo antes de tocar el lock."}],
            },
        },
        {
            "type": "assistant",
            "timestamp": utc(31),
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python -m pytest"}}],
            },
        },
    ]
    path = write_jsonl(aislado / "t.jsonl", rows)
    s = tarjeta(path, "corriendo", local(-50))
    ses.refresh_from_transcript(s)
    assert s["state"] == "corriendo"
    assert s["last_reply"] == "Ahora mido cuanto tarda el parseo antes de tocar el lock."
    # la linea de actividad (que herramienta, cuantos pasos) sigue estando: es lo otro
    assert s["tool_count"] == 2 and s["last_cmd"] == "python -m pytest"


def test_al_cerrar_el_turno_sigue_mandando_el_final(aislado):
    rows = rows_encolado()[:4]  # el turno cierra con turn_duration
    path = write_jsonl(aislado / "t.jsonl", rows)
    s = tarjeta(path, "corriendo", local(-50))
    s["hooked"] = False
    ses.refresh_from_transcript(s)
    assert s["state"] == "termino"
    assert s["last_reply"] == "Listo el primero."


# 14. encargo Z2: la tarjeta de Codex, y una forma sola para todas las tarjetas


def test_tool_paths_reconoce_las_formas_de_los_dos_agentes():
    assert ses.tool_paths({"file_path": "D:/x/a.py"}) == ["D:/x/a.py"]
    assert ses.tool_paths({"notebook_path": "D:/x/a.ipynb"}) == ["D:/x/a.ipynb"]
    assert ses.tool_paths({"path": "D:/x/foto.png"}) == ["D:/x/foto.png"]
    # apply_patch de Codex: varios archivos en un solo bloque
    assert ses.tool_paths({"paths": [{"path": "a.md", "type": "add"}, {"path": "b.jl", "type": "update"}]}) == [
        "a.md",
        "b.jl",
    ]
    assert ses.tool_paths({"command": "ls"}) == []
    assert ses.tool_paths({}) == []


def test_turn_activity_lee_un_turno_de_codex_de_verdad():
    """Bloques copiados de rollout-2026-09-05T14-57-26-01a072b7 (~/.codex). Antes de este arreglo
    la tarjeta de Codex mostraba archivos: [] porque apply_patch trae `paths`, no `file_path`."""
    t = {
        "blocks": [
            blk("shell", {"command": "rg -n 'biregular' documentos -g '*.md'", "cwd": "file:///D:/Apps/Teorema"}),
            blk(
                "apply_patch",
                {
                    "paths": [
                        {"path": r"D:\Apps\Teorema\documentos\ensamblaje_interfaces_2026-09-05.md", "type": "add"},
                        {"path": r"D:\Apps\Teorema\codigo\ensamblaje_interfaces.jl", "type": "add"},
                    ]
                },
            ),
            blk("shell", {"command": "julia.exe --startup-file=no codigo/ensamblaje_interfaces.jl"}),
        ],
        "final": "",
    }
    a = ses.turn_activity(t)
    assert a["tool_count"] == 3
    assert a["last_files"] == ["ensamblaje_interfaces_2026-09-05.md", "ensamblaje_interfaces.jl"]
    assert a["last_cmd"] == "julia.exe --startup-file=no codigo/ensamblaje_interfaces.jl"
    assert a["tool_errors"] == 0


def test_el_tope_de_tres_archivos_vale_tambien_dentro_de_un_bloque():
    t = {"blocks": [blk("apply_patch", {"paths": [{"path": f"{i}.md"} for i in range(6)]})], "final": ""}
    assert ses.turn_activity(t)["last_files"] == ["0.md", "1.md", "2.md"]


def test_view_image_de_codex_cuenta_como_archivo_tocado():
    t = {"blocks": [blk("view_image", {"path": "D:/Apps/lienzo/docs/img/tablero.png"})], "final": ""}
    assert ses.turn_activity(t)["last_files"] == ["tablero.png"]


def test_una_transcripcion_real_de_codex_muestra_sus_archivos():
    """Contra ~/.codex de esta maquina: si hay un turno con apply_patch, la tarjeta lo tiene que ver."""
    import lienzo.transcripts as tr

    paths = sorted(
        glob.glob(os.path.join(HOME, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl")),
        key=os.path.getmtime,
        reverse=True,
    )
    for p in paths[:60]:
        try:
            turnos = tr.turns("codex", p, 40)["turns"]
        except OSError:
            continue
        for t in turnos:
            if any(b.get("kind") == "tool" and b.get("name") == "apply_patch" for b in t["blocks"]):
                a = ses.turn_activity(t)
                assert a["tool_count"] > 0
                assert a["last_files"], f"turno de Codex con apply_patch y sin archivos, en {os.path.basename(p)}"
                return
    pytest.skip("sin turnos de Codex con apply_patch en ~/.codex")


def test_la_tarjeta_tiene_la_misma_forma_venga_de_hook_o_de_barrido():
    """Un campo que a veces esta y a veces no es lo que despues rompe el front: `orphan` venia bool
    en las tarjetas del barrido y ausente en las de hooks."""
    por_hook = ses.new_session("aaa", "claude", "hook")
    por_barrido = ses.new_session("bbb", "codex", "sweep")
    assert set(por_hook) == set(por_barrido)
    for campo in ("orphan", "in_vscode", "no_console", "typing", "coordinator"):
        assert por_hook[campo] is False, f"{campo} tiene que ser bool, no None ni ausente"
    for campo in ("suggestion", "last_error", "limit_until", "continue_scheduled_for", "title_source", "last_cmd"):
        assert campo in por_hook and por_hook[campo] is None
    assert por_hook["last_files"] == [] and por_hook["tool_count"] == 0 and por_hook["tool_errors"] == 0


def test_una_tarjeta_vieja_recupera_la_forma_al_cargarla(aislado, monkeypatch):
    """Las guardadas por versiones anteriores tienen la mitad de los campos: al cargarlas se
    completan, para que GET /sessions no devuelva un campo en unas tarjetas y no en otras."""
    monkeypatch.setattr(ses.procs, "agent_alive", lambda pid: True)
    vieja = {
        "session_id": SID,
        "agent": "claude",
        "source": "hook",
        "state": "termino",
        "state_since": local(0),
        "started": local(0),
        "last_event_ts": local(0),
        "pid": PID,
    }
    (aislado / f"{SID}.json").write_text(json.dumps(vieja), encoding="utf-8")
    ses.load_sessions()
    s = st.sessions[SID]
    assert set(s) == set(ses.new_session(SID, "claude", "hook"))
    assert s["orphan"] is False and s["suggestion"] is None and s["last_files"] == []
    assert s["state"] == "termino", "lo que ya tenia no se pisa"


# 15. encargo A5: los handlers en tandas y create_rule partido en validar y armar --------------


def test_edit_rule_valida_todo_antes_de_escribir(aislado, con_pid):
    """PUT /rules/<id> rechaza con 400 y no deja la regla editada por partes: el texto viene bien y
    el every_s mal, y lo que queda guardado es la regla entera como estaba."""
    import datetime as dt

    st.sessions[SID] = ses.new_session(SID, "claude", "hook")
    at = dt.datetime.now().astimezone().replace(microsecond=0) + dt.timedelta(hours=2)
    code, r = server.create_rule({"kind": "at", "to": SID, "text": "Continuar", "at": at.isoformat()})
    assert code == 200
    antes = dict(r)

    code, res = server.edit_rule(r["id"], {"text": "pisado", "every_s": 10})
    assert code == 400 and res == {"error": "every_s debe ser al menos 60 segundos"}
    assert st.rules.items[0] == antes, "un 400 no puede dejar la mitad del cambio escrita"

    code, res = server.edit_rule(r["id"], {"text": 9})
    assert code == 400 and res == {"error": "text debe ser un texto"}
    assert st.rules.items[0] == antes

    assert server.edit_rule("nadie", {"text": "x"}) == (404, {"error": "conexion desconocida"})
    assert server.edit_rule(r["id"], {"at": "ayer"})[0] == 400
    assert st.rules.items[0] == antes


def test_edit_rule_reprograma_una_at_que_ya_disparo(aislado, con_pid):
    """Una programada que disparo queda deshabilitada; darle una hora nueva la vuelve a poner
    vigente, con la cuenta de disparos en cero y sin la marca de cuando se apago."""
    import datetime as dt

    st.sessions[SID] = ses.new_session(SID, "claude", "hook")
    regla_at(None, max_fires=1, at_offset_s=-60, enabled=False, fired=1, disabled_at=st.now())
    nueva = (dt.datetime.now().astimezone().replace(microsecond=0) + dt.timedelta(hours=3)).isoformat()

    code, r = server.edit_rule("p1", {"at": nueva, "text": "de nuevo"})
    assert code == 200
    assert r["enabled"] is True and r["fired"] == 0 and "disabled_at" not in r
    assert r["at"] == nueva and r["text"] == "de nuevo"


def test_las_claves_de_una_regla_nueva_no_cambian_de_orden(aislado, con_pid):
    """El cuerpo de POST /rules es json.dumps de este dict, asi que el orden en que se arma es el
    orden que ve la UI. new_rule pone los campos comunes y cada clase agrega los suyos detras."""
    import datetime as dt

    st.sessions[SID] = ses.new_session(SID, "claude", "hook")
    st.sessions[NEW] = ses.new_session(NEW, "claude", "hook")
    at = (dt.datetime.now().astimezone().replace(microsecond=0) + dt.timedelta(hours=4)).isoformat()

    code, r = server.create_rule({"kind": "at", "to": SID, "text": "x", "at": at, "every_s": 600})
    assert code == 200
    assert list(r) == [
        "id",
        "kind",
        "from",
        "to",
        "text",
        "at",
        "fired",
        "enabled",
        "created",
        "every_s",
        "max_fires",
        "skip_busy",
        "repeat",
    ]

    code, r = server.create_rule({"kind": "on_stop", "to": SID, "from": NEW, "text": "y"})
    assert code == 200
    assert list(r) == ["id", "kind", "from", "to", "text", "at", "repeat", "max_fires", "fired", "enabled", "created"]


def test_check_rule_rechaza_sin_tocar_la_lista_de_reglas(aislado, con_pid):
    """La validacion comun de POST /rules es lo unico que corre cuando el pedido no sirve: ni
    on_stop ni at llegan a armar nada."""
    st.sessions[SID] = ses.new_session(SID, "claude", "hook")
    assert server.check_rule({"kind": "nada", "to": SID}) == (400, {"error": "kind debe ser on_stop o at"})
    assert server.check_rule({"kind": "at", "to": "nadie"}) == (404, {"error": "sesion destino desconocida"})
    assert server.check_rule({"kind": "on_stop", "to": SID}) == (404, {"error": "sesion origen desconocida"})
    assert server.check_rule({"kind": "at", "to": SID}) is None
    assert server.check_rule({"kind": "on_stop", "to": SID, "from": SID}) is None
    assert st.rules.items == []


def test_una_vista_desconocida_de_una_tarjeta_no_dice_sesion_desconocida(aislado):
    """Las vistas de /sessions/<id>/... se atienden juntas y con una sola busqueda de la sesion,
    pero la lista de vistas se mira primero: /sessions/<id>/loquesea sigue siendo ruta desconocida.
    Y en las que validan el cuerpo, el 400 sigue ganandole al 404 de la sesion."""
    import http.client
    import threading

    st.sessions[SID] = ses.new_session(SID, "claude", "hook")
    srv = server.QuietServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        casos = (
            ("GET", f"/sessions/{SID}/loquesea", None, 404, "ruta desconocida"),
            ("GET", f"/sessions/{SID}", None, 404, "ruta desconocida"),
            ("GET", f"/sessions/{SID}/screen/extra", None, 404, "ruta desconocida"),
            ("GET", "/sessions/nadie/screen", None, 404, "sesion desconocida"),
            ("GET", "/sessions/nadie/connections", None, 404, "sesion desconocida"),
            ("GET", "/sessions/nadie/turns", None, 404, "sesion desconocida"),
            ("GET", "/sessions/nadie/digest", None, 404, "sesion desconocida"),
            ("PUT", "/sessions/nadie/title", '{"title": 7}', 400, "title debe ser un texto"),
            ("PUT", "/sessions/nadie/title", '{"title": "hola"}', 404, "sesion desconocida"),
            ("PUT", "/sessions/nadie/coordinator", '{"on": "si"}', 400, "on debe ser true o false"),
            ("PUT", "/sessions/nadie/coordinator", '{"on": true}', 404, "sesion desconocida"),
        )
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
        for metodo, path, body, code, error in casos:
            c.request(metodo, path, body=body, headers={"X-Lienzo": "1", "Content-Type": "application/json"})
            r = c.getresponse()
            cuerpo = json.loads(r.read())
            assert (r.status, cuerpo.get("error")) == (code, error), (metodo, path, r.status, cuerpo)
        c.close()
    finally:
        srv.shutdown()
