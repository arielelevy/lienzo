"""Foto de recursos y contexto con proveedores fijos: no WSL ni IA."""

import datetime as dt


def hechos():
    import prolog_hechos

    return prolog_hechos


def test_mide_ram_y_contexto_sin_inventar_chrome_wsl_o_cuotas():
    now = dt.datetime(2026, 10, 22, tzinfo=dt.UTC)
    out = hechos().medir(
        "aa", {"tecnologia": "python", "tipo_archivo": ".py"}, leer_memoria=lambda: (4.5, 16), sesiones=None, ahora=now
    )
    facts = {(f["pred"], tuple(f["args"])) for f in out["hechos"]}
    assert ("memoria_libre_gb", ("trabajo:aa", 4.5)) in facts
    assert ("tecnologia", ("trabajo:aa", "python")) in facts
    assert ("tipo_archivo", ("trabajo:aa", ".py")) in facts
    assert not any(
        p in {"chrome_en_uso", "wsl_arranque_gb", "cuota_semanal_disponible_pct", "frentes_activos"} for p, _ in facts
    )
    memory = next(f for f in out["hechos"] if f["pred"] == "memoria_libre_gb")
    assert memory["observada_en"] == now.isoformat()
    assert memory["vigente_hasta"] == (now + dt.timedelta(seconds=30)).isoformat()
    assert out["limitaciones"]


def test_cuenta_solo_frentes_vivos_locales_de_la_foto():
    rows = [
        {"alive": True},
        {"alive": True, "state": "terminó"},
        {"alive": False},
        {"alive": True, "stopped_by": "otra"},
        {"alive": True, "coordinator": True},
        {"alive": True, "remote": True},
    ]
    out = hechos().medir("aa", {}, leer_memoria=lambda: (None, None), sesiones=rows)
    facts = {(f["pred"], tuple(f["args"])) for f in out["hechos"]}
    assert ("frentes_activos", ("trabajo:aa", 2)) in facts
    assert not any(p == "memoria_libre_gb" for p, _ in facts)


def test_hechos_volatiles_vencidos_no_entran_al_motor():
    import prolog_ciclo

    out = prolog_ciclo._validar_hechos(
        [{"pred": "memoria_libre_gb", "args": ["pc", 9], "vigente_hasta": "2000-01-01T00:00:00+00:00"}]
    )
    assert out == []


def test_todas_las_dimensiones_de_metadata_son_hechos_de_la_creencia():
    metadata = {
        "proyecto": "aa",
        "tecnologia": ["python"],
        "tipo_archivo": [".py"],
        "rutas": ["lienzo/creencias.py"],
        "area": ["backend"],
        "fase": ["verificacion"],
        "tipo_trabajo": ["bugfix"],
        "agente": ["codex"],
        "modelo": ["gpt-6"],
    }
    node = {"id": "b", "datos": {"metadatos": metadata}}
    facts = {(f["pred"], tuple(f["args"])) for f in hechos().desde_creencia(node)}
    assert facts == {
        (key if key != "rutas" else "ruta", ("b", value))
        for key, values in metadata.items()
        for value in ([values] if key == "proyecto" else values)
    }
    assert hechos().desde_creencia({"id": "desconocida", "datos": {"metadatos": {"area": []}}}) == []
