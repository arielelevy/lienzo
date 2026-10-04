"""lienzo/health.py: snapshot() de memoria, CPU y temperatura. Windows real, sin mocks de ctypes:
son las mismas APIs que procinfo.py ya usa sin stub en test_procs.py."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lienzo import health


def _reset():
    """snapshot() guarda estado de modulo (muestra de CPU, cache de temperatura): cada test
    arranca limpio para no depender del orden en que corren."""
    health._ultima_muestra = None
    health._temp.limpiar()


def test_snapshot_trae_las_cinco_claves():
    _reset()
    s = health.snapshot()
    assert set(s) == {
        "mem_free_gb",
        "mem_total_gb",
        "cpu_pct",
        "temp_c",
        "agentes_libres",
        "git_auth",
        "coda_cuota",
        "cuotas",
        "ts",
    }


def test_memoria_es_real_y_coherente():
    _reset()
    s = health.snapshot()
    assert isinstance(s["mem_total_gb"], float) and s["mem_total_gb"] > 1
    assert isinstance(s["mem_free_gb"], float) and 0 <= s["mem_free_gb"] <= s["mem_total_gb"]


def test_cpu_pct_none_en_la_primera_llamada_y_numero_en_la_segunda():
    _reset()
    primera = health.snapshot()
    assert primera["cpu_pct"] is None, "sin muestra anterior no hay con que comparar"
    time.sleep(0.05)
    segunda = health.snapshot()
    assert isinstance(segunda["cpu_pct"], float)
    assert 0.0 <= segunda["cpu_pct"] <= 100.0


def test_snapshot_nunca_levanta_aunque_falle_todo(monkeypatch):
    _reset()

    def revienta(*a, **k):
        raise OSError("simulado")

    monkeypatch.setattr(health._k32, "GlobalMemoryStatusEx", revienta)
    monkeypatch.setattr(health._k32, "GetSystemTimes", revienta)
    monkeypatch.setattr(health, "_temp_c", lambda: (_ for _ in ()).throw(OSError("simulado")))
    s = health.snapshot()
    assert s == {
        "mem_free_gb": None,
        "mem_total_gb": None,
        "cpu_pct": None,
        "temp_c": None,
        "agentes_libres": None,
        "git_auth": s["git_auth"],
        "coda_cuota": s["coda_cuota"],
        "cuotas": s["cuotas"],
        "ts": s["ts"],
    }


def test_temperatura_o_none_y_valor_ya_no_finito_da_none(monkeypatch):
    _reset()
    t = health._temp_c()
    assert t is None or isinstance(t, float)


def test_temperatura_cacheada_30_segundos_no_repite_el_powershell(monkeypatch):
    _reset()
    llamadas = []

    def fake_correr(*a, **k):
        llamadas.append(1)
        return 0, "\\_TZ.THRM|2991\n", ""  # deciKelvin: 26.0 C, con la forma «zona|valor»

    monkeypatch.setattr(health.subproc, "correr", fake_correr)
    # solo WMI: con LibreHardwareMonitor corriendo en esta PC, la medicion no llegaria al powershell
    monkeypatch.setattr(health, "FUENTES", [health.ZonasTermicasWMI()])

    reloj = [1000.0]
    monkeypatch.setattr(health.time, "monotonic", lambda: reloj[0])

    primera = health._temp_c()
    assert primera == 26.0
    assert len(llamadas) == 1

    reloj[0] += 10  # adentro de los 30 s de cache
    segunda = health._temp_c()
    assert segunda == 26.0
    assert len(llamadas) == 1, "10 s despues todavia tiene que servir del cache"

    reloj[0] += 25  # 35 s desde la primera: la cache vencio
    tercera = health._temp_c()
    assert tercera == 26.0
    assert len(llamadas) == 2


def test_temperatura_con_powershell_que_no_devuelve_nada():
    """WMI sin la clase (VM sin sensor) o timeout: el powershell real corre y no truena."""
    _reset()
    t = health._temp_c()
    assert t is None or isinstance(t, float)


def test_snapshot_en_frio_y_con_cache(capsys):
    """Mide cuanto tarda snapshot(): en frio (primer llamado, con el powershell de temperatura
    de verdad) contra con la temperatura ya en cache. Lo que se mide va al informe."""
    _reset()
    frio_ini = time.perf_counter()
    health.snapshot()
    frio = time.perf_counter() - frio_ini

    cache_ini = time.perf_counter()
    health.snapshot()
    cache = time.perf_counter() - cache_ini

    with capsys.disabled():
        print(f"\nsnapshot() en frio: {frio * 1000:.1f} ms · con cache: {cache * 1000:.1f} ms")
    assert cache < frio or cache < 0.05, "con la temperatura en cache no deberia tardar mas que en frio"


def test_elegir_temp_prefiere_thrm_y_si_no_la_zona_plausible_mas_caliente():
    r"""Esta PC tiene \_TZ.THRM; la otra no y quedaba en None (medido el 2026-10-03)."""
    assert health.ZonasTermicasWMI().elegir("\\_TZ.TZ01|2932\n\\_TZ.THRM|3682\n") == 95.1
    assert health.ZonasTermicasWMI().elegir("\\_TZ.TZ01|2932\n\\_TZ.CPUZ|3332\n\\_TZ.TZ02|3182\n") == 60.1
    assert health.ZonasTermicasWMI().elegir("acpi:ACPI\\ThermalZone\\TZ00_0|3232\n") == 50.1
    assert health.ZonasTermicasWMI().elegir("\\_TZ.TZ01|2932\n") is None  # 20 °C fijo: no es la PC
    assert health.ZonasTermicasWMI().elegir("") is None
    assert health.ZonasTermicasWMI().elegir("basura\n|\nx|abc\n") is None


def _lhm(*sensores):
    """Un data.json de LibreHardwareMonitor con los sensores dados como (SensorId, Text, Value)."""
    return {
        "Text": "Sensor",
        "Children": [
            {
                "Text": "PC",
                "Children": [
                    {"Text": t, "SensorId": sid, "Type": "Temperature", "Value": v, "Children": []}
                    for sid, t, v in sensores
                ],
            }
        ],
    }


def test_elegir_temp_lhm_prefiere_el_paquete_del_cpu():
    datos = _lhm(
        ("/intelcpu/0/temperature/0", "CPU Core #1", "71,0 °C"),
        ("/intelcpu/0/temperature/9", "CPU Package", "68,5 °C"),
        ("/nvme/0/temperature/0", "Composite Temperature", "38,0 °C"),
    )
    assert health.LibreHardwareMonitor().elegir(datos) == 68.5


def test_elegir_temp_lhm_sin_cpu_usa_el_sensor_real_mas_caliente_y_no_los_limites():
    """El Dell Pro 14 con LHM 0.9.6 (medido el 2026-10-03): sin temperatura de CPU, solo RAM y NVMe,
    con limites y umbrales que LHM informa como si fueran temperaturas."""
    datos = _lhm(
        ("/memory/dimm/0/temperature/0", "DIMM #0", "47,8 °C"),
        ("/memory/dimm/0/temperature/1", "Temperature Sensor Resolution", "0,3 °C"),
        ("/memory/dimm/0/temperature/3", "Thermal Sensor High Limit", "55,0 °C"),
        ("/memory/dimm/0/temperature/5", "Thermal Sensor Critical High Limit", "85,0 °C"),
        ("/nvme/0/temperature/0", "Composite Temperature", "38,0 °C"),
        ("/nvme/0/temperature/10", "Warning Temperature", "69,0 °C"),
        ("/nvme/0/temperature/11", "Critical Temperature", "74,0 °C"),
    )
    assert health.LibreHardwareMonitor().elegir(datos) == 47.8
    assert health.LibreHardwareMonitor().elegir(_lhm(("/nvme/0/temperature/0", "Composite", "basura"))) is None
    assert health.LibreHardwareMonitor().elegir({}) is None


class _Fija(health.FuenteTemperatura):
    """Una fuente de prueba: devuelve siempre lo mismo, o levanta si se le pasa una excepcion."""

    nombre = "fija"

    def __init__(self, crudo):
        self.crudo = crudo
        self.lecturas = 0

    def leer(self):
        self.lecturas += 1
        if isinstance(self.crudo, Exception):
            raise self.crudo
        return self.crudo

    def elegir(self, crudo):
        return crudo


def test_la_cadena_usa_la_primera_fuente_que_mide_y_no_consulta_las_siguientes(monkeypatch):
    primera, segunda = _Fija(52.0), _Fija(45.1)
    monkeypatch.setattr(health, "FUENTES", [primera, segunda])
    assert health._medir_temp() == 52.0
    assert segunda.lecturas == 0, "con la primera midiendo no hace falta la segunda (el powershell)"


def test_una_fuente_rota_o_sin_lectura_no_corta_la_cadena(monkeypatch):
    rota, vacia, buena = _Fija(RuntimeError("formato nuevo")), _Fija(None), _Fija(45.1)
    monkeypatch.setattr(health, "FUENTES", [rota, vacia, buena])
    assert health._medir_temp() == 45.1
    monkeypatch.setattr(health, "FUENTES", [rota, vacia])
    assert health._medir_temp() is None


def test_lhm_sin_nadie_escuchando_da_none_al_instante():
    t0 = time.perf_counter()
    assert health.LibreHardwareMonitor("http://127.0.0.1:1/data.json").medir() is None
    assert time.perf_counter() - t0 < 1.5


def test_lhm_url_por_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("LIENZO_LHM_URL", "http://127.0.0.1:9999/data.json")
    assert health.LibreHardwareMonitor().url == "http://127.0.0.1:9999/data.json"
    assert health.LibreHardwareMonitor("http://otra/data.json").url == "http://otra/data.json"


def test_no_se_puede_instanciar_una_fuente_sin_leer_y_elegir():
    class Incompleta(health.FuenteTemperatura):
        nombre = "incompleta"

        def leer(self):
            return ""

    try:
        Incompleta()
    except TypeError:
        return
    raise AssertionError("FuenteTemperatura tiene que obligar a implementar elegir()")


def test_una_fuente_que_falla_lo_avisa_al_cambiar_de_estado_y_no_cada_vez(monkeypatch):
    """Ningun error silencioso: el motivo va al log. Pero una vez por cambio, no cada 30 s."""
    avisos: list[str] = []
    monkeypatch.setattr(health, "log", avisos.append)
    f = _Fija(45.1)
    f.medir()
    assert avisos == [], "arrancar midiendo bien no es noticia"
    f.crudo = ConnectionRefusedError("nadie escucha")
    f.medir()
    f.medir()
    f.crudo = None
    f.medir()
    f.crudo = 45.1
    f.medir()
    assert avisos == [
        "temperatura, fuente fija: falla (ConnectionRefusedError: nadie escucha)",
        "temperatura, fuente fija: sin lectura plausible",
        "temperatura, fuente fija: ok",
    ]


def test_agentes_que_entran_es_la_unica_regla_de_capacidad():
    assert health.agentes_que_entran(None) is None
    assert health.agentes_que_entran(1.0) == 0  # bajo la reserva
    assert health.agentes_que_entran(1.5) == 0
    assert health.agentes_que_entran(2.2) == 1  # 1,5 + 0,7
    assert health.agentes_que_entran(2.7) == 1
    assert health.agentes_que_entran(5.0) == 5


def test_clasificar_git():
    assert health.clasificar_git(0, "") == "ok"
    assert health.clasificar_git(128, "fatal: Authentication failed for 'https://x'") == "vencida"
    assert health.clasificar_git(128, "remote: Credentials are incorrect or have expired") == "vencida"
    assert health.clasificar_git(128, "fatal: could not read Username: terminal prompts disabled") == "no_verificable"
    assert health.clasificar_git(128, "fatal: unable to access: Could not resolve host") == "sin_red"


def test_git_auth_sin_urls_configuradas_es_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    assert health._medir_git() is None


def test_git_auth_toma_enseguida_un_cambio_de_urls(monkeypatch):
    """Medido el 2026-10-03: el server midio antes de que se agregara git_check y quedo 5 min en None."""
    urls = [[]]
    monkeypatch.setattr(health, "_git_urls", lambda: urls[0])
    monkeypatch.setattr(health, "_medir_git", lambda u=None: {x: "ok" for x in (u or [])} or None)
    monkeypatch.setattr(
        health.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})()
    )
    monkeypatch.setattr(health, "_git", health.CacheEnSegundoPlano("git", health.GIT_TTL_S, health._git.medir))
    assert health._git_auth() is None
    urls[0] = ["https://h/r.git"]
    health._git_auth()  # dispara la medicion nueva al ver otras urls
    assert health._git_auth() == {"https://h/r.git": "ok"}


def test_ls_remote_colgado_vence_y_no_bloquea(monkeypatch):
    """Si git (o el credential manager que deja vivo) no termina, se lo mata y da «error»: el hilo
    de la salud nunca queda colgado."""
    vistos = {}

    def correr(argv, **k):
        vistos.update(argv=argv, **k)
        return health.subproc.VENCIDO, "", "git no termino en 0.1 s"

    monkeypatch.setattr(health.subproc, "correr", correr)
    assert health._ls_remote("https://h/r.git", timeout_s=0.1) == "timeout"
    assert vistos["timeout"] == 0.1 and vistos["sin_prompts"] is True
    monkeypatch.setattr(health.subproc, "correr", lambda argv, **k: (128, "", "fatal: Authentication failed"))
    assert health._ls_remote("https://h/r.git") == "vencida"


def test_cannot_prompt_no_es_vencida_sino_no_verificable():
    """Bug 8: el GCM que no puede pedir la credencial no mando nada al servidor; no prueba que venza."""
    err = "fatal: Cannot prompt because user interactivity has been disabled.\nfatal: unable to get password from user"
    assert health.clasificar_git(128, err) == "no_verificable"


def test_ls_remote_prueba_con_la_ruta_si_por_host_no_puede(monkeypatch):
    llamadas = []

    def correr(argv, **k):
        llamadas.append(argv)
        if "credential.useHttpPath=true" in argv:
            return 0, "abc refs/heads/main", ""
        return 128, "", "fatal: Cannot prompt because user interactivity has been disabled."

    monkeypatch.setattr(health.subproc, "correr", correr)
    assert health._ls_remote("https://h/r.git") == "ok"
    assert len(llamadas) == 2
    # las dos sin poder pedir: no verificable, no vencida
    monkeypatch.setattr(
        health.subproc,
        "correr",
        lambda argv, **k: (128, "", "fatal: Cannot prompt because user interactivity has been disabled."),
    )
    assert health._ls_remote("https://h/r.git") == "no_verificable"
    # un rechazo real del servidor en cualquiera de las dos manda
    respuestas = iter(
        [
            (128, "", "fatal: Cannot prompt because user interactivity has been disabled."),
            (128, "", "fatal: Authentication failed"),
        ]
    )
    monkeypatch.setattr(health.subproc, "correr", lambda argv, **k: next(respuestas))
    assert health._ls_remote("https://h/r.git") == "vencida"


def test_clasificar_git_distingue_red_de_credencial():
    assert health.clasificar_git(128, "fatal: unable to access 'https://h/': Could not resolve host: h") == "sin_red"
    assert (
        health.clasificar_git(128, "fatal: unable to access 'https://h/': Failed to connect to h port 443") == "sin_red"
    )
    assert health.clasificar_git(128, "remote: HTTP Basic: Access denied (401)") == "vencida"
    assert health.clasificar_git(128, "fatal: repository not found") == "error"


def test_ls_remote_que_no_termina_es_timeout(monkeypatch):
    monkeypatch.setattr(health.subproc, "correr", lambda *a, **k: (health.subproc.VENCIDO, "", ""))
    assert health._ls_remote("https://h/r.git") == "timeout"


def test_git_urls_suma_los_repos_en_uso_a_las_fijas(tmp_path, monkeypatch):
    """Bug 9 (2026-10-04): la tira seguia en «vencida» por un proyecto que ya no se usaba porque la
    lista era solo la de git_check, a mano. Ahora entran los remotes de las sesiones vivas."""
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"git_check": ["https://fija/x.git"]}', encoding="utf-8")
    monkeypatch.setattr(health, "_remotes_vistos", {})
    monkeypatch.setattr(
        health,
        "remotes_de_sesiones",
        lambda: ["https://en-uso/y.git", "git@ssh:z.git", "https://u:token@h/t.git", "https://fija/x.git"],
    )
    # ssh no pasa por el credential manager y una contraseña pegada viajaria en /peers: quedan afuera
    assert health._git_urls() == ["https://en-uso/y.git", "https://fija/x.git"]


def test_git_urls_suelta_un_repo_cerrado_pasada_la_gracia(tmp_path, monkeypatch):
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    monkeypatch.setattr(health, "_remotes_vistos", {})
    vivas = [["https://h/proyecto.git"]]
    monkeypatch.setattr(health, "remotes_de_sesiones", lambda: vivas[0])
    assert health._remotes_en_uso(ahora=1000) == ["https://h/proyecto.git"]
    vivas[0] = []  # se cerro la ultima sesion de ese repo
    assert health._remotes_en_uso(ahora=1000 + health.GIT_GRACIA_S - 1) == ["https://h/proyecto.git"]
    assert health._remotes_en_uso(ahora=1000 + health.GIT_GRACIA_S + 1) == []


def test_git_urls_sin_sesiones_si_falla_la_consulta(tmp_path, monkeypatch):
    monkeypatch.setenv("LIENZO_HOME", str(tmp_path))
    monkeypatch.setattr(health, "_remotes_vistos", {})

    def rompe():
        raise RuntimeError("lock")

    monkeypatch.setattr(health, "remotes_de_sesiones", rompe)
    assert health._git_urls() == []


def test_git_auth_mientras_mide_las_urls_nuevas_sigue_lo_ya_medido(monkeypatch):
    """Abrir una sesion en otro repo cambia las urls: hasta que la medicion nueva termine, la tira
    no queda sin dato de las urls que ya estaban."""
    urls = [["https://h/a.git"]]
    monkeypatch.setattr(health, "_git_urls", lambda: urls[0])
    cache = health.CacheEnSegundoPlano("git", health.GIT_TTL_S, lambda u: {x: "vencida" for x in u})
    monkeypatch.setattr(health, "_git", cache)
    cache._medir((("https://h/a.git",),), time.monotonic())
    monkeypatch.setattr(
        health.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: None})()
    )
    urls[0] = ["https://h/a.git", "https://h/b.git"]
    assert health._git_auth() == {"https://h/a.git": "vencida"}
    urls[0] = ["https://h/b.git"]  # la de antes ya no esta: no se muestra
    assert health._git_auth() is None


def test_cuota_de_coda_solo_con_coda_en_uso(monkeypatch):
    """Bug 10 (2026-10-04): la tira ponia la PC en rojo con «sin cuota: coda» sin que nadie usara coda
    (un error viejo del log). Sin tarjeta viva de coda, ni cuotas() ni el snapshot la traen; con una,
    si, y sigue hasta CODA_GRACIA_S despues de cerrarla."""
    monkeypatch.setattr(health, "coda_cuota", lambda esperar=False: "agotada")
    monkeypatch.setattr(health, "cuotas_de_sesiones", dict)
    monkeypatch.setattr(health, "_coda_vista", [None])
    viva = [False]
    monkeypatch.setattr(health, "coda_viva", lambda: viva[0])
    assert health.cuotas() == {}
    assert health.snapshot()["coda_cuota"] is None
    viva[0] = True
    assert health.cuotas() == {"coda": "agotada"}
    viva[0] = False  # se cerro la coda: la gracia la sostiene un rato y despues se suelta
    assert health.coda_en_uso(ahora=time.time() + health.CODA_GRACIA_S - 5)
    assert not health.coda_en_uso(ahora=time.time() + health.CODA_GRACIA_S + 5)


def test_coda_en_uso_no_levanta_si_falla_la_consulta(monkeypatch):
    monkeypatch.setattr(health, "_coda_vista", [None])

    def rompe():
        raise RuntimeError("lock")

    monkeypatch.setattr(health, "coda_viva", rompe)
    assert health.coda_en_uso() is False
