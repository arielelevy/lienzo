"""Tests de lienzo/auditoria.py: clasificación determinista, deduplicación, enfriamiento y agrupado.
Todo con datos armados a mano y un reloj fijo: ni red ni server."""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))
import auditoria as au

T0 = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3)))


def iso(minutos):
    return (T0 + dt.timedelta(minutes=minutos)).isoformat()


def ses(sid, estado="termino", desde=-20, coord=False, repo="r", **kw):
    return {
        "session_id": sid,
        "state": estado,
        "state_since": iso(desde),
        "alive": True,
        "coordinator": coord,
        "repo_key": repo,
        "title": f"r - {sid}",
        **kw,
    }


def link(i, de, a, ts, kind="send"):
    return {"id": i, "from": de, "to": a, "ts": iso(ts), "kind": kind}


def tipos(sesiones, links, ahora=T0):
    return {h["session_id"]: h["tipo"] for h in au.clasificar(sesiones, links, ahora)}


def test_trabajando_y_cuota_no_avisan():
    s = [ses("C", "corriendo", coord=True), ses("A", "corriendo", desde=-60), ses("B", desde=-60, limit_until=iso(30))]
    assert tipos(s, []) == {}


def test_caso_opensyync_cuatro_quietos_con_entrega_sin_leer():
    # 4 frentes entregaron por regla a la coordinadora hace 14 min; ella quieta y sin contestarles
    s = [ses("C", coord=True, desde=-14)] + [ses(x, desde=-14) for x in "ABDE"]
    links = [link(f"e{x}", "C", x, -40) for x in "ABDE"] + [link(f"r{x}", x, "C", -14, "rule") for x in "ABDE"]
    t = tipos(s, links)
    assert {t[x] for x in "ABDE"} == {"entrega_sin_leer"}
    # la coordinadora: le llegaron 4 reglas y no se movió -> sus envíos no se tomaron
    assert t["C"] == "envio_no_tomado"


def test_coordinadora_contesto_entonces_idle_evitable_si_no_asigno():
    s = [ses("C", coord=True, desde=-30), ses("A", desde=-20)]
    links = [link("r", "A", "C", -25, "rule"), link("acuse", "C", "A", -24)]
    # el acuse llegó y A cambió de estado después (desde=-20 > -24): no es envío no tomado
    assert tipos(s, links)["A"] == "idle_evitable"


def test_quieto_poco_tiempo_no_avisa():
    s = [ses("C", coord=True), ses("A", desde=-5)]
    assert "A" not in tipos(s, [])


def test_bloqueo_declarado_es_espera_legitima_y_no_se_avisa():
    s = [ses("C", coord=True), ses("A", last_reply="...\nESTADO: bloqueado — falta el permiso X")]
    h = au.clasificar(s, [], T0)
    assert [x["tipo"] for x in h if x["session_id"] == "A"] == ["bloqueado_permiso"]
    avisar, _ = au.filtrar(h, {}, T0)
    assert all(x["session_id"] != "A" for x in avisar)


def test_esperar_en_la_cola_de_un_turno_es_espera_legitima():
    # openSeec, 2026-10-30: un frente en la cola de un turno salía como idle_evitable
    s = [ses("C", coord=True, desde=-30), ses("A", desde=-20), ses("B", desde=-20)]
    turnos = {"motores": {"dueno": {"session_id": "B"}, "cola": [{"session_id": "A", "pedido": iso(-20)}]}}
    h = au.clasificar(s, [], T0, turnos=turnos)
    porsid = {x["session_id"]: x for x in h}
    assert porsid["A"]["tipo"] == "espera_turno" and porsid["A"]["recurso"] == "motores"
    assert porsid["B"]["tipo"] == "idle_evitable"  # el dueño quieto sí se avisa
    avisar, _ = au.filtrar(h, {}, T0)
    assert [x["session_id"] for x in avisar] == ["B"]
    assert {x["session_id"]: x["tipo"] for x in au.ronda(s, [], {}, T0, turnos=turnos)["hallazgos"]}[
        "A"
    ] == "espera_turno"


def test_te_necesita_avisa_despues_del_umbral():
    s = [ses("C", coord=True), ses("A", "te_necesita", desde=-6), ses("B", "te_necesita", desde=-2)]
    t = tipos(s, [])
    assert t["A"] == "bloqueado_humano" and "B" not in t


def test_envio_no_tomado_caso_a480da47():
    # le mandaron algo a las -10 y sigue en el mismo estado desde -30: quedó en el editor o un diálogo
    s = [ses("C", coord=True, desde=-1), ses("A", desde=-30)]
    assert tipos(s, [link("x", "C", "A", -10)])["A"] == "envio_no_tomado"
    # recién mandado: todavía no
    assert tipos(s, [link("x", "C", "A", -1)])["A"] == "idle_evitable"


def test_sin_coordinadora():
    assert tipos([ses("A", desde=-30)], [])["A"] == "sin_coordinadora"


def test_muertas_y_detenidas_no_cuentan():
    s = [
        ses("C", coord=True),
        ses("A", "muerta", desde=-90),
        ses("B", desde=-90, stopped_by="X"),
        {**ses("D", desde=-90), "alive": False},
    ]
    assert tipos(s, []) == {}


def test_no_repite_misma_evidencia_y_vuelve_a_avisar_si_cambia():
    s = [ses("C", coord=True), ses("A", desde=-20)]
    r1 = au.ronda(s, [], {}, T0)
    assert [h["session_id"] for h in r1["avisar"]] == ["A"]
    # 5 min después, mismo estado: no se repite (como el aviso duplicado de 12:33 y 12:35)
    r2 = au.ronda(s, [], r1["estado"], T0 + dt.timedelta(minutes=5))
    assert r2["avisar"] == []
    # A trabajó y volvió a quedar quieta (evidencia nueva) pero dentro del enfriamiento: no avisa
    s2 = [ses("C", coord=True), ses("A", desde=-3 + 15)]
    r3 = au.ronda(s2, [], r2["estado"], T0 + dt.timedelta(minutes=25))
    assert r3["avisar"] == []
    # pasado el enfriamiento, sí
    r4 = au.ronda(s2, [], r3["estado"], T0 + dt.timedelta(minutes=45))
    assert [h["tipo"] for h in r4["avisar"]] == ["idle_evitable"]


def test_rondas_cada_5_min_no_generan_bucle():
    # 12 rondas (una hora) sobre el mismo tablero: un solo aviso por sesión
    s = [ses("C", coord=True)] + [ses(x, desde=-20) for x in "ABDE"]
    estado, total = {}, 0
    for i in range(12):
        r = au.ronda(s, [], estado, T0 + dt.timedelta(minutes=5 * i))
        estado, total = r["estado"], total + len(r["avisar"])
    assert total == 4


def test_un_texto_por_coordinadora():
    s = [
        ses("C", coord=True),
        ses("A", desde=-20),
        ses("B", desde=-20),
        ses("K", coord=True, repo="otro"),
        ses("Z", desde=-20, repo="otro"),
    ]
    r = au.ronda(s, [], {}, T0)
    assert set(r["textos"]) == {"C", "K"}
    assert r["textos"]["C"].count("\n- ") == 2 and r["textos"]["K"].count("\n- ") == 1


def test_olvida_claves_viejas():
    previo = {"emitidos": {"idle_evitable|A|x": iso(-60 * 30)}, "ultimo": {}}
    _, estado = au.filtrar([], previo, T0)
    assert estado["emitidos"] == {}


def test_costo_es_barato():
    s = [ses("C", coord=True)] + [ses(f"S{i}", desde=-20) for i in range(300)]
    links = [link(f"l{i}", "C", f"S{i}", -40) for i in range(300)]
    assert au.ronda(s, links, {}, T0)["costo_ms"] < 200


def test_sin_enviar_del_server_es_envio_no_tomado_sin_esperar_umbral():
    # hooks_eventos.envio_sin_confirmar marca needs.kind=sin_enviar a los 25 s: se avisa ya
    s = [ses("C", coord=True), ses("A", "te_necesita", desde=-1, needs={"kind": "sin_enviar", "since": iso(-1)})]
    assert tipos(s, [])["A"] == "envio_no_tomado"


def test_ronda_local_audita_solo_esta_pc_y_no_escribe_a_una_coordinadora_trabada(monkeypatch, tmp_path):
    sesiones = [
        ses("C", coord=True, pc="yo", desde=-30),
        ses("A", desde=-20, pc="yo"),
        ses("R", desde=-20, pc="otra"),
        ses("K", coord=True, repo="k", pc="yo", desde=-30),
        ses("B", desde=-20, repo="k", pc="yo"),
    ]
    links = [link("x", "B", "K", -10, "rule")]  # a K le llegó una entrega y no se movió: trabada
    rutas = {"/sessions": sesiones, "/peers": [{"pc_id": "yo", "local": True}], "/links": links, "/rules": []}
    monkeypatch.setattr(au, "_get", lambda base, ruta: rutas[ruta])
    enviados = []
    monkeypatch.setattr(au, "_post", lambda base, ruta, cuerpo: enviados.append((ruta, cuerpo)))
    r = au.ronda_local("http://x", str(tmp_path / "estado.json"), enviar=True)
    assert "R" not in {h["session_id"] for h in r["hallazgos"]}  # la otra PC audita lo suyo
    assert [ruta for ruta, _ in enviados] == ["/sessions/C/send"]  # a K no: tiene un envío sin tomar
    assert all(set(c) == {"text"} for _, c in enviados)  # sin `sin_aviso`: el server lo exige con from
    # la ronda siguiente no repite
    enviados.clear()
    au.ronda_local("http://x", str(tmp_path / "estado.json"), enviar=True)
    assert enviados == []


def test_bloqueo_declarado_vence_segun_categoria():
    casos = [
        ("ESTADO: bloqueado — falta que Ariel apruebe el permiso", "permiso", 30),
        ("ESTADO: bloqueado: espero el contrato v3 del frente B", "dependencia", 60),
        ("ESTADO: bloqueada, en pausa hasta mañana", "pausa", 240),
    ]
    for texto, cat, vence in casos:
        antes = [ses("C", coord=True), ses("A", desde=-(vence - 1), last_reply=texto)]
        despues = [ses("C", coord=True), ses("A", desde=-(vence + 1), last_reply=texto)]
        assert tipos(antes, [])["A"] == f"bloqueado_{cat}"
        h = au.clasificar(despues, [], T0)
        assert [(x["tipo"], x["categoria"]) for x in h if x["session_id"] == "A"] == [("bloqueo_olvidado", cat)]
        assert [x["session_id"] for x in au.filtrar(h, {}, T0)[0]] == ["A"]


def test_politica_ronda_5_min_cubre_4_quietos_14_min():
    # los 4 frentes quedan quietos en cualquier segundo del ciclo de la ronda: el aviso llega antes de 14 min
    for fase_s in range(0, 300, 7):
        quietos = T0 - dt.timedelta(seconds=fase_s)
        avisado = None
        estado = {}
        for i in range(6):
            ahora = T0 + dt.timedelta(minutes=5 * i)
            s = [ses("C", coord=True, desde=-60)] + [{**ses(x), "state_since": quietos.isoformat()} for x in "ABDE"]
            r = au.ronda(s, [], estado, ahora)
            estado = r["estado"]
            if r["avisar"] and avisado is None:
                avisado = (ahora - quietos).total_seconds() / 60
                assert {h["session_id"] for h in r["avisar"]} == set("ABDE")
        assert avisado is not None and avisado < 14, (fase_s, avisado)


def test_tarjeta_stale_de_pc_caida_no_recibe_avisos_de_coordinadora(monkeypatch, tmp_path):
    sesiones = [ses("C", coord=True, pc="yo"), ses("A", pc="yo"), ses("vieja", coord=True, pc="caida")]
    rutas = {
        "/sessions": sesiones,
        "/peers": [{"pc_id": "yo", "local": True, "alive": True}, {"pc_id": "caida", "alive": False}],
        "/links": [],
        "/rules": [],
    }
    monkeypatch.setattr(au, "_get", lambda base, ruta: rutas[ruta])
    enviados = []
    monkeypatch.setattr(au, "_post", lambda base, ruta, cuerpo: enviados.append(ruta))
    au.ronda_local("http://fixture", str(tmp_path / "estado.json"), enviar=True)
    assert enviados == ["/sessions/C/send"]


def regla(i, de, a, enabled=False, **kw):
    return {"id": i, "kind": "on_stop", "from": de, "to": a, "repeat": True, "enabled": enabled, **kw}


def test_informe_no_entregado_caso_opensyync_regla_apagada():
    # L cerró con ESTADO: hace 3 min y su regla hacia K quedó apagada por un borrado rechazado
    s = [ses("K", coord=True, desde=-30), ses("L", desde=-3, last_reply="listo.\nESTADO: L3 entregado")]
    reglas = [regla("86e3", "L", "K", disabled_reason="borrado rechazado: hay informes pendientes de integrar")]
    h = au.clasificar(s, [], T0, reglas=reglas)
    assert [(x["session_id"], x["tipo"]) for x in h] == [("L", "informe_no_entregado")]
    assert h[0]["coordinadora"] == "K" and "86e3" in h[0]["sugerencia"]


def test_informe_no_entregado_no_avisa_si_hay_regla_viva_archivada_o_sin_estado():
    s = [ses("K", coord=True, desde=-30), ses("L", desde=-3, last_reply="ESTADO: hecho")]
    viva = [regla("vieja", "L", "K"), regla("nueva", "L", "K", enabled=True)]
    assert au.clasificar(s, [], T0, reglas=viva) == []
    assert au.clasificar(s, [], T0, reglas=[regla("a", "L", "K", archived_at="x")]) == []
    assert au.clasificar(s, [], T0, reglas=[regla("p", "L", "K", parked_since="x")]) == []
    assert au.clasificar(s, [], T0, reglas=[regla("u", "L", "K", repeat=False)]) == []
    sin_estado = [ses("K", coord=True, desde=-30), ses("L", desde=-3, last_reply="sigo esperando")]
    assert au.clasificar(sin_estado, [], T0, reglas=[regla("x", "L", "K")]) == []


def test_informe_no_entregado_no_avisa_si_la_regla_entrego_antes_de_apagarse():
    # la regla entregó el ESTADO (link rule después del último turno) y recién después se apagó (tope, borrado)
    s = [ses("K", coord=True, desde=-30), ses("L", desde=-5, last_reply="ESTADO: entregado")]
    reglas = [regla("r", "L", "K", disabled_reason="tope total alcanzado")]
    hallazgos = au.clasificar(s, [link("e", "L", "K", -4, "rule")], T0, reglas=reglas)
    assert "L" not in {h["session_id"] for h in hallazgos}  # K sí: recibió la entrega y no se movió


def test_informe_no_entregado_respeta_el_marcador_de_la_regla():
    s = [ses("K", coord=True, desde=-30), ses("L", desde=-3, last_reply="ESTADO: listo")]
    assert au.clasificar(s, [], T0, reglas=[regla("r", "L", "K", solo_si="LISTO:")]) == []
    s2 = [ses("K", coord=True, desde=-30), ses("L", desde=-3, last_reply="LISTO: hecho")]
    assert tipos_r(s2, [regla("r", "L", "K", solo_si="LISTO:")])["L"] == "informe_no_entregado"


def test_informe_no_entregado_ve_la_regla_que_quedo_en_una_coordinadora_anterior():
    s = [ses("M", coord=True, desde=-30), ses("L", desde=-3, last_reply="ESTADO: hecho")]
    reglas = [regla("vieja", "L", "K-muerta", parked_since="x")]
    assert tipos_r(s, reglas)["L"] == "informe_no_entregado"


def test_un_bloqueo_declarado_sigue_su_camino_aunque_la_regla_este_apagada():
    s = [ses("K", coord=True, desde=-30), ses("L", desde=-40, last_reply="ESTADO: bloqueado esperando permiso")]
    assert tipos_r(s, [regla("r", "L", "K")])["L"] == "bloqueo_olvidado"


def tipos_r(sesiones, reglas):
    return {h["session_id"]: h["tipo"] for h in au.clasificar(sesiones, [], T0, reglas=reglas)}


def test_informe_leido_por_mensaje_nativo_o_acuse_no_es_entrega_sin_leer():
    # openSeec, 2026-10-30: la coordinadora leyó el informe (le llegó como adjunto por la regla) y le contestó
    # por SendMessage, o acusó recibo; la auditoría igual decía «entrega_sin_leer»
    s = [ses("C", coord=True, desde=-30), ses("A", desde=-20), ses("B", desde=-20)]
    links = [
        link("rA", "A", "C", -25, "rule"),
        link("nA", "C", "A", -24, "native"),
        link("rB", "B", "C", -25, "rule"),
    ]
    reglas = [{"from": "B", "to": "C", "informes": [{"id": "i", "recibido_at": iso(-23)}]}]
    t = {h["session_id"]: h["tipo"] for h in au.clasificar(s, links, T0, reglas=reglas)}
    assert t["A"] == "idle_evitable" and t["B"] == "idle_evitable"
    # sin respuesta ni acuse, sigue avisando
    assert tipos(s, links[:1] + links[2:])["B"] == "entrega_sin_leer"


def test_turno_cortado_por_error_no_es_ocioso():
    # openSeec P, 2026-10-31: un grep sin `pattern` del modelo cortó la coda sin ESTADO: y figuraba idle_evitable
    s = [ses("C", coord=True, desde=-30), ses("P", desde=-20, last_error="coda: error de red o del servicio (x)")]
    h = {x["session_id"]: x for x in au.clasificar(s, [], T0)}
    assert h["P"]["tipo"] == "turno_cortado" and "Continuar" in h["P"]["sugerencia"]
