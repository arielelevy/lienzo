"""El sueño busca cómo trabajar mejor (pedido de Ariel, 2026-10-16): métricas sobre las capturas,
hallazgos propuestos idempotentes y el envío sin_aviso para los acuses."""

import datetime as dt
import itertools
import os
import sys

import optimizacion_trabajo as t
import optimization_scheduler as sch
import pytest
import rules as rl
import server
import sessions as ses
import state as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))

COORD, A, B = "coord", "fa", "fb"
T0 = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.UTC)
_ids = itertools.count()


def cap(clase, sid, minuto, texto="x", de=None, h=None):
    return {
        "id": f"c{next(_ids)}",
        "clase": clase,
        "session_id": sid,
        "origen": {"de": de} if de else {},
        "texto": texto,
        "bytes": len(texto.encode()),
        "hash": h or str(hash((clase, texto))),
        "fecha": T0 + dt.timedelta(minutes=minuto),
    }


def ronda():
    """A entrega a los 0 min y espera 40 min mientras la coordinadora atiende a B; un acuse a B vuelve
    como aviso; un aviso de A se repite; uno es intermedio; el mismo texto va a A y B a la vez."""
    caps = [
        cap("envio", A, -5, "encargo A", de=COORD),
        cap("respuesta", A, 0, "Listo A. ESTADO: entregado"),
        cap("regla", COORD, 0, "Terminó A. Listo A. ESTADO: entregado", de=A),
        cap(
            "regla", COORD, 1, "[lienzo: un aviso demorado por el limite]\nTerminó A. Listo A. ESTADO: entregado", de=A
        ),
        cap("envio", B, 2, "entrega recibida, quedate quieta", de=COORD),
        cap("respuesta", B, 3, "ok"),
        cap("regla", COORD, 3, "Terminó B. ok", de=B),
        cap("regla", COORD, 10, "Terminó B. sigo esperando la suite", de=B),
        cap("envio", B, 15, "revisá esto", de=COORD),
        cap("envio", B, 25, "y esto otro", de=COORD),
        cap("envio", A, 40, "subí la versión del contrato a la 3 y avisá", de=COORD, h="mismo"),
        cap("envio", B, 40.5, "subí la versión del contrato a la 3 y avisá", de=COORD, h="mismo"),
    ]
    return sorted(caps, key=lambda c: c["fecha"])


def test_medir_encuentra_cada_patron():
    m = t.medir(ronda())
    assert m["coordinadora"]["valor"] == COORD
    assert m["esperas_h"]["n"] == 1 and abs(m["esperas_h"]["valor"] - 40 / 60) < 0.01  # A esperó 40 min
    assert m["acuses_vuelta"]["valor"] == 1
    assert m["avisos_repetidos"]["valor"] == 1  # el demorado con el mismo cuerpo
    assert m["avisos_intermedios"]["valor"] == 1
    assert m["difusiones"]["valor"] == 1
    assert m["pico_sesiones"]["valor"] == 3
    assert "pico_sesiones" not in t.UMBRALES  # sin tope de sesiones: se informa, no es un hallazgo


def test_sin_coordinadora_no_mide_nada():
    assert t.medir([cap("respuesta", A, 0)]) == {}


def test_hallazgos_solo_sobre_el_umbral(monkeypatch):
    m = t.medir(ronda())
    assert t.hallazgos(m) == []  # una ronda chica no pasa ningun umbral
    monkeypatch.setitem(t.UMBRALES, "difusiones", (1, *t.UMBRALES["difusiones"][1:]))
    hs = t.hallazgos(m)
    assert [h["metrica"] for h in hs] == ["difusiones"] and "c.aviso" in hs[0]["sugerencia"]


def test_registrar_es_idempotente_por_metrica_y_dia(monkeypatch):
    creados = {}

    def crear_nodo(pid, tipo, texto, datos=None, *, autor, origen=None, clave_ingesta=None, con=None, **k):
        nuevo = clave_ingesta not in creados
        creados.setdefault(clave_ingesta, {"id": f"n{len(creados)}", "tipo": tipo, "datos": datos})
        return {**creados[clave_ingesta], "creado": nuevo}

    class Con:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    monkeypatch.setattr(t.conocimiento, "crear_nodo", crear_nodo)
    monkeypatch.setattr(t.optimization_memory, "_connect", lambda: Con())
    propuestas = []
    monkeypatch.setattr(t.creencias, "proponer", lambda pid, data, **kw: propuestas.append(data))
    analisis = {
        "ventana_h": 72,
        "capturas": 12,
        "hasta": "2026-10-16T12:40:30+00:00",
        "hallazgos": [
            {"metrica": "difusiones", "texto": "x", "valor": 4, "umbral": 3, "sugerencia": "s", "ejemplos": []}
        ],
    }
    assert t.registrar("p", analisis) == ["n0"]
    assert t.registrar("p", analisis) == []  # mismo dia: el mismo hallazgo, que no es nuevo
    assert list(creados) == ["trabajo:difusiones:2026-10-16"]
    assert creados["trabajo:difusiones:2026-10-16"]["tipo"] == "hallazgo"
    assert creados["trabajo:difusiones:2026-10-16"]["datos"]["requiere_veredicto"] is True
    assert t.registrar("p", {**analisis, "hallazgos": []}) == []
    assert propuestas[0]["fuentes"] == ["n0"]
    assert propuestas[0]["dimension"] == "coordinacion"


def test_el_scheduler_analiza_como_se_trabaja_a_lo_sumo_cada_hora(monkeypatch):
    llamadas = []
    monkeypatch.setattr(sch.trabajo, "analizar", lambda p: llamadas.append(p) or {"hallazgos": []})
    monkeypatch.setattr(sch.trabajo, "registrar", lambda p, a: [])
    monkeypatch.setattr(sch.activity, "cancellation_reason", lambda last: None)
    s = sch.Scheduler.__new__(sch.Scheduler)
    s.trabajo_visto, s.last_ui, s.reason = {}, 0, ""
    s.queue = type("Q", (), {"view": lambda self: {"enabled": True}})()
    s._trabajo("opensyync")
    s._trabajo("opensyync")
    assert llamadas == ["opensyync"]


def test_si_la_ui_lo_cancela_el_analisis_se_retoma_en_el_proximo_rato_quieto(monkeypatch):
    llamadas, cancelar = [], ["el usuario esta mirando"]
    monkeypatch.setattr(sch.trabajo, "analizar", lambda p: llamadas.append(p) or {"hallazgos": []})
    monkeypatch.setattr(sch.trabajo, "registrar", lambda p, a: [])
    monkeypatch.setattr(sch.activity, "cancellation_reason", lambda last: cancelar[0])
    s = sch.Scheduler.__new__(sch.Scheduler)
    s.trabajo_visto, s.last_ui, s.reason = {}, 0, ""
    s.queue = type("Q", (), {"view": lambda self: {"enabled": True}})()
    s._trabajo("p")
    cancelar[0] = None
    s._trabajo("p")
    assert llamadas == ["p", "p"]


def test_un_encargo_con_perfecto_no_es_un_acuse():
    caps = sorted(
        [
            cap("envio", A, 0, "Perfecto, ahora implementá el endpoint /x y corré los tests", de=COORD),
            cap("regla", COORD, 2, "Terminó A. listo", de=A),
            cap("envio", B, 3, "entrega recibida, quedate quieta", de=COORD),
            cap("regla", COORD, 4, "Terminó B. ok", de=B),
        ],
        key=lambda c: c["fecha"],
    )
    assert t.medir(caps)["acuses_vuelta"]["valor"] == 1


def test_difusiones_por_tandas_y_sin_textos_cortos():
    largo = "Subí el contrato a la versión 3 y avisá cuando esté"
    caps = [
        cap("regla", COORD, 0, "x", de=A),
        cap("envio", A, 1, largo, de=COORD, h="L"),
        cap("envio", B, 1.5, largo, de=COORD, h="L"),
        cap("envio", "fc", 1.8, largo, de=COORD, h="L"),
        cap("envio", A, 300, largo, de=COORD, h="L"),  # reenviado horas despues: otra tanda, de uno solo
        cap("envio", A, 400, "ok", de=COORD, h="ok"),
        cap("envio", B, 401, "ok", de=COORD, h="ok"),  # un «ok» a dos no es una difusion
    ]
    assert t.medir(sorted(caps, key=lambda c: c["fecha"]))["difusiones"]["valor"] == 1


def test_una_fecha_sin_zona_no_rompe_el_analisis():
    assert t._ts("2026-10-16T12:00:00").tzinfo is not None


# --- sin_aviso -------------------------------------------------------------------------------------

ORIGEN = "10000000-0000-4000-8000-0000000000aa"
DESTINO = "20000000-0000-4000-8000-0000000000bb"


@pytest.fixture
def reglas(monkeypatch):
    monkeypatch.setattr(ses, "mirror", None)
    monkeypatch.setattr(rl.captura, "respuesta", lambda s: None)
    monkeypatch.setattr(rl, "add_link", lambda *a, **k: None)
    monkeypatch.setattr(rl.rules, "save", lambda: None)
    monkeypatch.setattr(rl.rules, "publish", lambda: None)
    monkeypatch.setattr(rl.rules, "items", [])
    st.sessions[ORIGEN] = ses.new_session(ORIGEN, "claude", "hook")
    st.sessions[DESTINO] = ses.new_session(DESTINO, "claude", "hook")
    monkeypatch.setattr(rl, "find_session", lambda sid: st.sessions.get(sid))
    enviados = []
    envio = lambda dst, text, att: (enviados.append(text), (200, {"ok": True}))[1]
    monkeypatch.setattr(rl, "send_to_session", envio)
    monkeypatch.setattr(server, "send_to_session", envio)
    yield enviados
    st.sessions.pop(ORIGEN, None)
    st.sessions.pop(DESTINO, None)
    rl._on_stop_en_vuelo.clear()
    rl._fotos.clear()


def test_un_acuse_sin_aviso_no_vuelve_como_aviso_una_sola_vez(reglas):
    st.rules.items.append(
        {
            "id": "inf",
            "kind": "on_stop",
            "from": ORIGEN,
            "to": DESTINO,
            "text": "{respuesta}",
            "enabled": True,
            "repeat": True,
        }
    )
    frente = st.sessions[ORIGEN]
    code, _ = server.accion_send(frente, {"text": "entrega recibida", "from": DESTINO, "sin_aviso": True})
    assert code == 200 and frente["sin_aviso"]["a"] == DESTINO
    reglas.clear()
    frente.update(last_prompt="entrega recibida", last_reply="ok")  # el turno que empezo el acuse
    rl.fire_on_stop(ORIGEN)
    assert reglas == [] and "sin_aviso" in st.rules.items[0]["last_result"] and frente["sin_aviso"] is None
    frente.update(last_prompt="seguí con B", last_reply="Listo. ESTADO: entregado")
    rl.fire_on_stop(ORIGEN)  # el turno siguiente avisa como siempre
    assert reglas == ["Listo. ESTADO: entregado"]


def _regla_informe():
    st.rules.items.append(
        {"id": "inf", "kind": "on_stop", "from": ORIGEN, "to": DESTINO, "text": "{respuesta}", "enabled": True}
    )


def test_un_acuse_en_medio_de_la_entrega_no_la_calla(reglas):
    _regla_informe()
    frente = st.sessions[ORIGEN]
    frente.update(state="corriendo", last_prompt="implementá B")
    server.accion_send(frente, {"text": "gracias por lo anterior", "sin_aviso": DESTINO})
    reglas.clear()
    frente.update(last_reply="B listo. ESTADO: entregado")  # el turno que cierra es el de B
    rl.fire_on_stop(ORIGEN)
    assert reglas == ["B listo. ESTADO: entregado"] and frente["sin_aviso"] is None


@pytest.fixture
def envio_real(reglas, monkeypatch):
    """Como send_to_session de verdad: el texto enviado pasa a last_prompt, en medio de un turno o no."""
    _regla_informe()
    st.rules.items[0]["repeat"] = True  # como la que cablea lanzar_y_titular
    monkeypatch.setattr(ses, "en_hilo", lambda *a, **k: None)
    real = lambda dst, text, att: (dst.update(last_prompt=text), (200, {"ok": True}))[1]
    monkeypatch.setattr(server, "send_to_session", real)
    return reglas


@pytest.mark.parametrize("necesidad", [None, {"kind": "permission"}])
def test_un_acuse_tecleado_en_medio_de_la_entrega_no_la_calla(envio_real, necesidad):
    # OpenSyync, 2026-10-22 (K2): el envío real pisa last_prompt con el acuse aunque el agente lo tome
    # dentro del turno en curso (queued_command, sin UserPromptSubmit); el Stop de la entrega se callaba
    frente = st.sessions[ORIGEN]
    ses.set_state(frente, "corriendo")
    if necesidad:
        ses.set_needs(frente, necesidad)  # un permiso del mismo turno: sigue en curso
    frente.update(last_prompt="implementá B")
    server.accion_send(frente, {"text": "recibido, seguí", "sin_aviso": DESTINO})
    assert frente["sin_aviso"] is None
    frente.update(last_reply="B listo. ESTADO: entregado")
    ses.set_state(frente, "termino")
    rl.fire_on_stop(ORIGEN)
    assert envio_real == ["B listo. ESTADO: entregado"]


def test_un_acuse_a_una_tarjeta_que_espera_respuesta_calla_su_turno(envio_real):
    # te_necesita por idle_prompt: el turno anterior ya cerró, el acuse empieza el suyo y ése se calla
    frente = st.sessions[ORIGEN]
    ses.set_state(frente, "corriendo")
    ses.set_needs(frente, {"kind": "idle"})
    server.accion_send(frente, {"text": "recibido", "sin_aviso": DESTINO})
    assert frente["sin_aviso"]["a"] == DESTINO
    ses.set_state(frente, "corriendo")
    frente.update(last_reply="ok")
    ses.set_state(frente, "termino")
    rl.fire_on_stop(ORIGEN)
    assert envio_real == [] and "sin_aviso" in st.rules.items[0]["last_result"]


def test_un_acuse_que_termina_en_pregunta_no_calla_el_turno_siguiente(reglas):
    _regla_informe()
    frente = st.sessions[ORIGEN]
    server.accion_send(frente, {"text": "recibido", "sin_aviso": DESTINO})
    reglas.clear()
    frente.update(last_prompt="recibido", last_reply="¿sigo con la parte B?")
    rl.fire_on_stop(ORIGEN)  # termina en pregunta: no dispara nada
    frente.update(last_prompt="sí, seguí", last_reply="B lista. ESTADO: entregado")
    rl.fire_on_stop(ORIGEN)
    assert reglas == ["B lista. ESTADO: entregado"]


def test_sin_aviso_valida_su_forma():
    assert server.validar_send({"text": "x", "sin_aviso": True}) is not None  # true sin from
    assert server.validar_send({"text": "x", "sin_aviso": 3}) is not None
    assert server.validar_send({"text": "x", "sin_aviso": True, "from": DESTINO}) is None
    assert server.validar_send({"text": "x", "sin_aviso": DESTINO}) is None


def test_coordinar_sin_aviso_no_dibuja_la_flecha_y_exige_yo(monkeypatch):
    import coordinar as c

    monkeypatch.setattr(c, "YO", "coord")
    cuerpo = c._cuerpo_envio("f", "recibido", enlazar=False, sin_aviso=True)
    assert cuerpo == {"text": "recibido", "sin_aviso": "coord"}
    monkeypatch.setattr(c, "YO", "")
    with pytest.raises(ValueError):
        c._cuerpo_envio("f", "recibido", enlazar=False, sin_aviso=True)


def test_sin_aviso_vencido_no_calla(reglas):
    st.rules.items.append(
        {"id": "inf", "kind": "on_stop", "from": ORIGEN, "to": DESTINO, "text": "{respuesta}", "enabled": True}
    )
    st.sessions[ORIGEN].update(sin_aviso={"a": DESTINO, "desde": 0}, last_reply="Listo")
    rl.fire_on_stop(ORIGEN)
    assert reglas == ["Listo"]


# --- hallazgos resueltos: se vuelven a medir desde la correccion -----------------------------------


def test_un_hallazgo_corregido_se_mide_desde_la_correccion_y_si_reaparece_se_vincula(monkeypatch):
    import conocimiento as k
    import veredictos as v

    monkeypatch.setattr(k.state, "log", lambda msg: None)
    k.registrar_proyecto("ptrab", "trabajo", [])
    h = k.crear_nodo(
        "ptrab", "hallazgo", "difusiones", {"clase": "optimizacion_trabajo", "metrica": "difusiones"}, autor="server"
    )
    e = k.crear_nodo(
        "ptrab",
        "evidencia",
        "corregido por abc123",
        {"desde": "2026-10-16T12:30:00Z", "commit": "abc123"},
        autor="persona:x",
    )
    v.veredicto(
        "ptrab",
        [
            {"nodo": h["id"], "estado": "confirmado"},
            {"nodo": h["id"], "estado": "corregido"},
            {"de": h["id"], "relacion": "corregido_en", "a": e["id"]},
        ],
        por="persona:x",
    )
    assert t.correcciones("ptrab") == {
        "difusiones": {"hallazgo": h["id"], "desde": "2026-10-16T12:30:00Z", "commit": "abc123"}
    }
    largo = "Subí el contrato a la versión 3 y avisá cuando esté"
    antes = [cap("regla", COORD, 0, "x", de=A)] + [
        cap("envio", f, 1 + i, largo, de=COORD, h=f"L{j}") for j in range(4) for i, f in enumerate((A, B))
    ]
    monkeypatch.setattr(t, "capturas", lambda p, ventana_h=72: sorted(antes, key=lambda c: c["fecha"]))
    a = t.analizar("ptrab")
    assert a["metricas"]["difusiones"]["valor"] == 0 and a["metricas"]["difusiones"]["antes"] == 4
    assert a["hallazgos"] == []  # lo de antes de la correccion ya no cuenta
    despues = antes + [
        cap("envio", f, 40 + i, largo, de=COORD, h=f"D{j}") for j in range(3) for i, f in enumerate((A, B))
    ]
    monkeypatch.setattr(t, "capturas", lambda p, ventana_h=72: sorted(despues, key=lambda c: c["fecha"]))
    a = t.analizar("ptrab")
    assert [x["texto"].startswith("Reaparece después de abc123") for x in a["hallazgos"]] == [True]
    (nuevo,) = t.registrar("ptrab", a)
    import sqlite3

    con = sqlite3.connect(k.db_path())
    assert (
        con.execute(
            "SELECT count(*) FROM vinculo WHERE de=? AND relacion='mismo_que' AND a=?", (nuevo, h["id"])
        ).fetchone()[0]
        == 1
    )
    assert t.registrar("ptrab", a) == []  # la misma reaparicion no se duplica


def test_tras_la_correccion_se_mide_con_la_coordinadora_de_ese_tramo(monkeypatch):
    """La coordinadora puede cambiar: la de la ventana (la vieja) no ve los avisos de la nueva."""
    monkeypatch.setattr(
        t,
        "correcciones",
        lambda p: {"avisos_intermedios": {"hallazgo": "h", "desde": "2026-10-16T13:00:00Z", "commit": "x"}},
    )
    vieja = [cap("regla", "vieja", i, "Terminó. ok", de=A) for i in range(5)]
    nueva = [cap("regla", "nueva", 61 + i, "Terminó B. sigo esperando la suite", de=B) for i in range(2)]
    monkeypatch.setattr(t, "capturas", lambda p, ventana_h=72: sorted(vieja + nueva, key=lambda c: c["fecha"]))
    assert t.analizar("p")["metricas"]["avisos_intermedios"]["valor"] == 2
