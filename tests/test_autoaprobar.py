"""lienzo/autoaprobar.py: con el check prendido aprueba todo lo que piden los agentes de esta PC
(hook de Claude/Codex/Pi y cartel de coda), menos las preguntas con opciones; apagado no toca nada."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401
import autoaprobar as au
import sessions as ses
import state as st


def _armar(monkeypatch, prendido):
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": prendido})
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(au, "_intentados", {})
    monkeypatch.setattr(
        st,
        "pending",
        {
            "r1": {"request_id": "r1", "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "rm -rf x"}},
            "q1": {
                "request_id": "q1",
                "session_id": "s2",
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "¿A o B?"}]},
            },
        },
    )
    monkeypatch.setattr(
        st,
        "sessions",
        {
            "s1": {"session_id": "s1", "agent": "claude"},
            "c1": {
                "session_id": "c1",
                "agent": "coda",
                "state": "te_necesita",
                "last_cmd": "git push",
                "needs": {"kind": "permission", "tool": "bash", "where": "terminal", "coda_at": "t1"},
            },
        },
    )
    hechos = []
    monkeypatch.setattr(
        ses, "answer_pending", lambda rid, dec, reason="": (hechos.append(("hook", rid, dec)), (200, {}))[1]
    )
    monkeypatch.setattr(
        ses, "answer_coda_ask", lambda s, dec: (hechos.append(("coda", s["session_id"], dec)), (200, {}))[1]
    )
    return hechos


def test_apagado_no_aprueba_nada(monkeypatch):
    hechos = _armar(monkeypatch, False)
    assert au.ronda(ahora=100) == [] and hechos == []


def test_prendido_aprueba_hook_y_coda_y_salta_las_preguntas(monkeypatch):
    hechos = _armar(monkeypatch, True)
    au.ronda(ahora=100)
    assert sorted(hechos) == [("coda", "c1", "allow"), ("hook", "r1", "allow")]


def test_no_repite_el_mismo_pedido_hasta_el_reintento(monkeypatch):
    hechos = _armar(monkeypatch, True)
    au.ronda(ahora=100)
    au.ronda(ahora=105)
    assert len(hechos) == 2
    au.ronda(ahora=100 + au.REINTENTO_S + 1)
    # pasado el reintento, solo el cartel de coda se vuelve a contestar (un Enter puede no hacer
    # efecto); el pendiente de hook ya contestado no se repite
    assert len(hechos) == 3 and hechos[-1][0] == "coda"


def test_un_proveedor_roto_no_frena_a_los_demas(monkeypatch):
    hechos = _armar(monkeypatch, True)

    class Roto(au.ProveedorPermisos):
        nombre = "roto"

        def abiertos(self):
            raise RuntimeError("se rompio")

        def aprobar(self, p):
            return 500, {}

    monkeypatch.setattr(au, "PROVEEDORES", [Roto(), *au.PROVEEDORES])
    au.ronda(ahora=100)
    assert len(hechos) == 2


def test_un_error_de_disco_no_deja_el_pedido_sin_aprobar_para_siempre(monkeypatch):
    """E16 (plan de refactor 1.14): el pedido se marcaba como intentado ANTES de contestar; si
    answer_pending fallaba (disco lleno, answers/ bloqueado), el pendiente de hook no se volvia a
    contestar nunca y el agente quedaba esperando. Un 5xx o una excepcion se reintentan, con espera."""
    hechos = _armar(monkeypatch, True)
    monkeypatch.setattr(st, "sessions", {})  # solo el pendiente de hook
    intentos = []

    def falla(rid, dec, reason=""):
        intentos.append(rid)
        if len(intentos) == 1:
            raise OSError(28, "No space left on device")
        if len(intentos) == 2:
            return 500, {"ok": False}
        hechos.append(("hook", rid, dec))
        return 200, {"ok": True}

    monkeypatch.setattr(ses, "answer_pending", falla)
    au.ronda(ahora=100)
    au.ronda(ahora=101)  # antes de la espera no se insiste
    assert intentos == ["r1"]
    au.ronda(ahora=100 + au.REINTENTO_S + 1)
    assert intentos == ["r1", "r1"]
    au.ronda(ahora=100 + 2 * au.REINTENTO_S + 2)
    assert hechos == [("hook", "r1", "allow")]
    au.ronda(ahora=100 + 5 * au.REINTENTO_S)  # contestado: no se repite
    assert len(intentos) == 3


@pytest.mark.parametrize("code", [404, 409, 410])
def test_un_pedido_que_ya_no_esta_no_se_reintenta(monkeypatch, code):
    """Un pendiente ya contestado o vencido devuelve 4xx: reintentarlo seria insistir cada 20 s
    sobre algo que no existe."""
    _armar(monkeypatch, True)
    monkeypatch.setattr(st, "sessions", {})
    intentos = []
    monkeypatch.setattr(ses, "answer_pending", lambda rid, dec, reason="": (intentos.append(rid), (code, {}))[1])
    for t in (100, 100 + au.REINTENTO_S + 1, 100 + 10 * au.REINTENTO_S):
        au.ronda(ahora=t)
    assert intentos == ["r1"]


def _dialogo(question, options, **extra):
    return {
        "question": question,
        "options": [{"n": i + 1, "text": t} for i, t in enumerate(options)],
        "selected": 1,
        **extra,
    }


# tal cual lo leyo screen.dialog en Teorema el 2026-10-08: la opcion «No, ...» no entro en la pantalla
CODEX = _dialogo(
    "Would you like to run the following command?",
    ["Yes, proceed (y)", "Yes, and don't ask again for commands that start with `python -c`"],
    teclas="flechas",
)
CLAUDE = _dialogo(
    "Do you want to proceed?",
    ["Yes", "Yes, and don't ask again for similar commands", "No, and tell Claude what to do differently (esc)"],
)


def test_opcion_de_permiso_reconoce_los_dialogos_de_permiso_y_nada_mas():
    assert au.opcion_de_permiso(CODEX, "codex") == 1
    assert au.opcion_de_permiso(CLAUDE, "claude") == 1
    assert au.opcion_de_permiso(_dialogo("Do you want to make this edit to x.py?", ["Yes", "No"]), "claude") == 1
    # una pregunta de verdad, el cambio de modelo o la confianza en una carpeta no son permisos
    assert au.opcion_de_permiso(_dialogo("Which library?", ["Yes, requests", "No, httpx"]), "claude") is None
    assert au.opcion_de_permiso(_dialogo("Switch model?", ["Default", "Opus"]), "claude") is None
    assert (
        au.opcion_de_permiso(_dialogo("Do you trust the files in this folder?", ["Yes, proceed", "No, exit"]), "claude")
        is None
    )
    assert (
        au.opcion_de_permiso(_dialogo("Would you like to run the following command?", ["Proceed", "Cancel"]), "claude")
        is None
    )
    assert (
        au.opcion_de_permiso(_dialogo("Do you want to use this API key?", ["Yes", "No (recommended)"]), "claude")
        is None
    )
    assert au.opcion_de_permiso(None, "claude") is None


def _armar_dialogo(monkeypatch, dialog, **tarjeta):
    monkeypatch.setattr(au, "_estaba_prendido", False)
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": True})
    monkeypatch.setattr(st, "log", lambda m: None)
    monkeypatch.setattr(au, "_intentados", {})
    monkeypatch.setattr(st, "pending", {})
    monkeypatch.setattr(
        st,
        "sessions",
        {
            "d1": {
                "session_id": "d1",
                "agent": "codex",
                "state": "te_necesita",
                "needs": {"kind": "dialog", "detail": dialog["question"], "where": "terminal", "since": "t1"},
                "dialog": dialog,
                **tarjeta,
            }
        },
    )
    hechos = []
    monkeypatch.setattr(
        ses, "answer_dialog", lambda s, n: (hechos.append((s["session_id"], n)), (200, {"ok": True}))[1]
    )
    return hechos


def test_aprueba_el_dialogo_de_permiso_de_codex_eligiendo_si_y_reintenta(monkeypatch):
    """Medido el 2026-10-08: la tarjeta de Teorema (Codex) quedaba en «Espera que elijas en la
    terminal» con el auto-aprobar prendido: el permiso de Codex es un dialogo de la TUI, sin hook."""
    hechos = _armar_dialogo(monkeypatch, CODEX)
    assert [(p.agente, p.que.startswith("Would you like to run")) for p, _ in au.ronda(ahora=100)] == [("codex", True)]
    assert hechos == [("d1", 1)]
    au.ronda(ahora=105)
    assert len(hechos) == 1  # el numero tecleado todavia puede estar haciendo efecto
    au.ronda(ahora=100 + au.REINTENTO_S + 1)
    assert len(hechos) == 2  # sigue abierto: se vuelve a teclear


def test_el_mismo_dialogo_redibujado_no_se_vuelve_a_contestar_antes_del_reintento(monkeypatch):
    """Code review 2026-10-08: con el detalle en el id, otra linea envuelta en la pantalla hacia un
    pedido nuevo y se tecleaba otra vez a los 2 s (en Claude caia como texto en la caja de entrada)."""
    hechos = _armar_dialogo(monkeypatch, CODEX)
    au.ronda(ahora=100)
    st.sessions["d1"]["dialog"] = {**CODEX, "detail": "la misma orden, envuelta distinto"}
    au.ronda(ahora=103)
    assert hechos == [("d1", 1)]


def test_un_permiso_con_la_pregunta_mal_leida_se_reconoce_por_el_dont_ask_again():
    """Medido el 2026-10-08 (tarjetas Teorema y A): con un comando largo, screen.dialog tomaba un
    pedazo del comando como pregunta y el auto-aprobar no lo contestaba."""
    roto = _dialogo(
        "smartBI/claude-skills/lienzo');import coordinar as",
        ["Yes, proceed (y)", "Yes, and don't ask again for commands that start with `python -u -c`"],
        teclas="flechas",
    )
    assert au.opcion_de_permiso(roto, "codex") == 1
    assert au.opcion_de_permiso(_dialogo("Environment: local", ["Yes, proceed (y)", "No"]), "claude") is None


def test_el_motivo_de_no_contestar_queda_en_la_tarjeta_y_se_va_con_el_dialogo(monkeypatch):
    """Antes la tarjeta decia solo «Espera que elijas en la terminal» y no se sabia si el
    auto-aprobar lo habia mirado y descartado, o si fallaba."""
    hechos = _armar_dialogo(monkeypatch, _dialogo("Switch model?", ["Default", "Opus"]))
    tocadas = []
    monkeypatch.setattr(ses, "touch", lambda s: tocadas.append(s["session_id"]) or True)
    au.ronda(ahora=100)
    assert hechos == [] and st.sessions["d1"][au.OMITIDO] == "el cambio de modelo lo decide el humano"
    assert tocadas == ["d1"]
    au.ronda(ahora=101)
    assert tocadas == ["d1"]  # el mismo motivo no se vuelve a publicar
    st.sessions["d1"]["dialog"] = _dialogo("Do you trust the files in this folder?", ["Yes, proceed", "No, exit"])
    au.ronda(ahora=102)
    assert st.sessions["d1"][au.OMITIDO] == "la confianza en una carpeta la decide el humano"
    st.sessions["d1"]["dialog"] = _dialogo("Which library?", ["requests", "httpx"])
    au.ronda(ahora=103)
    assert st.sessions["d1"][au.OMITIDO] == "no es un permiso: es una pregunta con opciones"
    # un permiso de verdad lo contesta y borra el aviso; apagado, el aviso tampoco corresponde
    st.sessions["d1"]["dialog"] = CODEX
    au.ronda(ahora=104)
    assert hechos == [("d1", 1)] and st.sessions["d1"][au.OMITIDO] is None
    st.sessions["d1"]["dialog"] = _dialogo("Which library?", ["requests", "httpx"])
    au.ronda(ahora=105)
    assert st.sessions["d1"][au.OMITIDO]
    monkeypatch.setattr(st, "load_config", lambda: {"auto_aprobar": False})
    au.ronda(ahora=106)
    assert st.sessions["d1"][au.OMITIDO] is None


def test_frases_que_cada_tui_usa_para_un_permiso():
    """Code review 2026-10-08: al pasar a perfiles se habian perdido «Would you like to proceed?» de
    Claude (salir del plan) y el parche de Codex («Would you like to make the following edits?»)."""
    plan = _dialogo("Would you like to proceed?", ["Yes", "Yes, and auto-accept edits", "No, keep planning"])
    assert au.opcion_de_permiso(plan, "claude") == 1
    parche = _dialogo(
        "Would you like to make the following edits?",
        ["Yes, proceed (y)", "No, and tell Codex what to do differently (esc)"],
    )
    assert au.opcion_de_permiso(parche, "codex") == 1
    assert au.opcion_de_permiso(CODEX, None) is None  # sin agente no se sabe con que reglas leerlo


def test_el_motivo_mira_como_arranca_la_pregunta_y_kiro_tiene_el_suyo():
    assert (
        au.motivo_omitido(_dialogo("Which model should the pipeline use?", ["Star", "Snowflake"]), "claude")
        == "no es un permiso: es una pregunta con opciones"
    )
    assert (
        au.motivo_omitido(_dialogo("Switch model?", ["Default", "Opus"]), "codex")
        == "el cambio de modelo lo decide el humano"
    )
    assert au.motivo_omitido(_dialogo("Tool requires approval", ["Allow (a)", "Deny"]), "kiro").startswith(
        "es un permiso de Kiro"
    )
    assert au.motivo_omitido(CODEX, None) == "agente desconocido"


def test_el_permiso_de_kiro_con_allow_y_deny_tambien_es_un_permiso():
    kiro = _dialogo(
        "Tool requires approval: run command", ["Allow", "Always allow", "Deny", "Always deny"], teclas="flechas"
    )
    assert au.opcion_de_permiso(kiro, "kiro") == 1
    assert au.opcion_de_permiso(kiro, "claude") is None  # cada TUI redacta distinto
    truncado = _dialogo(
        "Kiro requiere permiso (comando parcialmente visible)", ["Allow", "Always allow", "Deny", "Always deny"]
    )
    assert au.opcion_de_permiso(truncado, "kiro") == 1
    assert (
        au.opcion_de_permiso(_dialogo("Which one?", ["Allow", "Deny"]), "kiro") == 1
    )  # Allow/Deny solo lo tiene un permiso
    assert au.opcion_de_permiso(_dialogo("Which one?", ["Allow", "Reject"]), "kiro") is None
    assert au.opcion_de_permiso(CODEX, "pi") is None and au.opcion_de_permiso(CODEX, "coda") is None
    assert au.opcion_de_permiso(CODEX, "desconocido") is None


def test_no_contesta_un_dialogo_que_no_es_permiso_ni_uno_con_pendiente_de_hook(monkeypatch):
    hechos = _armar_dialogo(monkeypatch, _dialogo("Switch model?", ["Default", "Opus"]))
    au.ronda(ahora=100)
    assert hechos == []
    hechos = _armar_dialogo(monkeypatch, CLAUDE, pending_id="r9")  # el permiso de verdad va por el hook
    au.ronda(ahora=100)
    assert hechos == []
    hechos = _armar_dialogo(monkeypatch, CLAUDE, state="corriendo")  # ya se cerro
    au.ronda(ahora=100)
    assert hechos == []
