"""Salud de la PC: memoria, CPU y temperatura de Windows, sin dependencias nuevas.

Memoria por GlobalMemoryStatusEx; CPU por dos muestras de GetSystemTimes (la primera llamada no
tiene con que comparar y da None: el modulo guarda la muestra anterior); temperatura de
LibreHardwareMonitor (su servidor web en :8085) si esta corriendo, y si no por WMI (\\_TZ.THRM,
deciKelvin) via un powershell corto, cara y por eso cacheada 30 s. `snapshot()` nunca
levanta: un fallo de cualquier pieza deja ese campo en None y no interrumpe a las demas.

Fuera de Windows (Mac/Linux/WSL, backend tmux) el modulo tiene que importar igual: la memoria sale de
/proc/meminfo donde existe, y CPU y temperatura quedan en None.

Ademas, si ~/.lienzo/config.json trae "git_check", si las credenciales de git siguen valiendo
(`git_auth`, renovado en segundo plano cada GIT_TTL_S).

Lo usa server.py: GET /peer/health (que cada PC le pide a las otras, ver mirror.py), la fila de
esta PC en GET /peers, la capacidad de /restaurar (agentes_que_entran) y `health.log`, que el
server apunta a su log.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import json
import os
import sys
import threading
import time
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable

try:
    from . import subproc
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import subproc

WINDOWS = sys.platform == "win32"
GB = 1024**3
TEMP_TTL_S = 30
# Capacidad: la UNICA regla de cuantos agentes mas entran en una PC (la usan /restaurar del server y
# coordinar.capacidad, que antes repetian estas constantes). Con menos de RESERVA_GB libres Windows
# empieza a paginar y arrastra al resto; cada agente ocupa unos GB_POR_AGENTE.
RESERVA_GB = 1.5
GB_POR_AGENTE = 0.7


if WINDOWS:
    import ctypes.wintypes as wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wt.DWORD),
            ("dwMemoryLoad", wt.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    _k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    _k32.GlobalMemoryStatusEx.restype = wt.BOOL
    _k32.GetSystemTimes.argtypes = [
        ctypes.POINTER(wt.FILETIME),
        ctypes.POINTER(wt.FILETIME),
        ctypes.POINTER(wt.FILETIME),
    ]
    _k32.GetSystemTimes.restype = wt.BOOL


def _memoria_unix() -> tuple[float | None, float | None]:
    """(libre, total) en GB desde /proc/meminfo (Linux, WSL). En Mac no existe: (None, None)."""
    campos = {}
    with open("/proc/meminfo", encoding="ascii") as f:
        for linea in f:
            k, _, v = linea.partition(":")
            campos[k] = int(v.split()[0]) * 1024  # viene en kB
    if "MemAvailable" not in campos or "MemTotal" not in campos:
        return None, None
    return campos["MemAvailable"] / GB, campos["MemTotal"] / GB


def _memoria() -> tuple[float | None, float | None]:
    """(libre, total) en GB, o (None, None) si GlobalMemoryStatusEx falla."""
    if not WINDOWS:
        return _memoria_unix()
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    if not _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None, None
    return m.ullAvailPhys / GB, m.ullTotalPhys / GB


def _filetime_to_int(ft: wt.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


# Muestra anterior de GetSystemTimes (ocioso, kernel, usuario), para el delta entre dos llamadas.
# Vive a nivel de modulo: es la unica forma de medir CPU sin una libreria como psutil.
_ultima_muestra: tuple[int, int, int] | None = None


def _cpu_pct() -> float | None:
    """% de CPU usado desde la ultima llamada. La primera no tiene con que comparar: None."""
    global _ultima_muestra
    if not WINDOWS:
        return None
    idle, kernel, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    ahora = (_filetime_to_int(idle), _filetime_to_int(kernel), _filetime_to_int(user))
    anterior = _ultima_muestra
    _ultima_muestra = ahora
    if anterior is None:
        return None
    idle_d = ahora[0] - anterior[0]
    # kernel incluye el tiempo ocioso; el total ocupado es (kernel + user) - idle
    total_d = (ahora[1] - anterior[1]) + (ahora[2] - anterior[2])
    if total_d <= 0:
        return None
    return max(0.0, min(100.0, round(100 * (1 - idle_d / total_d), 1)))


def _now() -> str:
    # la misma forma que state.now(); aparte porque health.py se importa suelto, sin lienzo/ en el path
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


# A donde van los avisos de las fuentes; server.py lo cambia por su log. Por defecto a stderr: un
# import suelto (tests, scripts) tampoco falla en silencio.
log: Callable[[str], None] = lambda msg: print(f"health: {msg}", file=sys.stderr)


class CacheEnSegundoPlano:
    """El ultimo valor de una medicion cara (temperatura, credenciales de git), que se renueva en
    un hilo aparte cuando vence: quien pregunta nunca espera a la medicion, salvo la primera si lo
    pide (`esperar_primera`). Un solo hilo de refresco a la vez (el lock); los demas pedidos
    devuelven lo que hay.

    `clave` son los argumentos de `medir`: si cambian (otras urls de git), se mide enseguida sin
    esperar el TTL, y mientras tanto no se devuelve el valor de la clave vieja (es de otra cosa).
    Si `medir` levanta, el hilo no muere en silencio: va al log (una vez por cambio de motivo, no
    en cada vuelta) y se queda con el ultimo valor hasta el proximo intento, pasado el TTL."""

    def __init__(self, nombre: str, ttl_s: float, medir: Callable[..., object]) -> None:
        self.nombre = nombre
        self.ttl_s = ttl_s
        self.medir = medir
        self._refrescando = threading.Lock()
        self.limpiar()

    def limpiar(self) -> None:
        """Olvida lo medido: el proximo pedido arranca como el primero."""
        self._valor: object = None
        self._momento: float | None = None  # time.monotonic() de la ultima medicion (o intento)
        self._clave: tuple = ()
        self._error: str | None = None

    def valor(self, *clave, esperar_primera: bool = False) -> object:
        ahora = time.monotonic()
        if self._momento is None and esperar_primera:
            self._medir(clave, ahora)
        elif (
            self._momento is None or ahora - self._momento >= self.ttl_s or self._clave != clave
        ) and self._refrescando.acquire(blocking=False):
            threading.Thread(target=self._refrescar, args=(clave,), daemon=True).start()
        return self._valor if self._clave == clave else None

    def _refrescar(self, clave: tuple) -> None:
        try:
            self._medir(clave, time.monotonic())
        finally:
            self._refrescando.release()

    def _medir(self, clave: tuple, momento: float) -> None:
        try:
            valor = self.medir(*clave)
        except Exception as e:  # un hilo que muere sin decir nada deja el valor viejo para siempre
            self._momento = momento  # se reintenta pasado el TTL, no en cada pedido
            self._avisar(f"falla ({type(e).__name__}: {e}); queda el ultimo valor")
            return
        self._valor, self._momento, self._clave = valor, momento, clave
        self._avisar(None)

    def _avisar(self, error: str | None) -> None:
        if error != self._error:
            self._error = error
            log(f"{self.nombre}: {error or 'se recupero'}")


TEMP_MIN_C = 25.0  # por debajo es un sensor fijo o de ambiente (TZ01 da 20 °C siempre)
TEMP_MAX_C = 120.0  # por encima es una lectura rota


def _plausible(c: float) -> bool:
    return TEMP_MIN_C <= c <= TEMP_MAX_C


class FuenteTemperatura(ABC):
    """Un proveedor de la temperatura de la PC. `medir()` es fija (template method): `leer()` hace la
    entrada/salida y `elegir()` interpreta lo leido sin tocar nada, asi cada fuente se prueba con
    datos de verdad sin hardware. Cualquier falla de una fuente da None y la cadena sigue con la
    proxima: un sensor roto o un formato nuevo nunca deja a las demas sin medir."""

    nombre: str
    # el ultimo estado avisado («ok», «sin lectura» o el error): se loguea solo cuando cambia, para
    # que una fuente rota quede en el log sin repetir la misma linea cada 30 s
    _estado: str | None = None

    @abstractmethod
    def leer(self) -> object:
        """Lo crudo de la fuente (texto, JSON). Puede levantar: medir() lo absorbe."""

    @abstractmethod
    def elegir(self, crudo: object) -> float | None:
        """De lo crudo, la temperatura de la PC en °C, o None si no hay una lectura plausible."""

    def medir(self) -> float | None:
        """La lectura, o None. Nunca levanta (una fuente rota no corta la cadena), pero tampoco
        calla: cada cambio de estado (empieza a fallar, cambia el motivo, se recupera) va al log."""
        try:
            t = self.elegir(self.leer())
        except Exception as e:
            self._avisar(f"falla ({type(e).__name__}: {e})")
            return None
        self._avisar("ok" if t is not None else "sin lectura plausible")
        return t

    def _avisar(self, estado: str) -> None:
        if estado == self._estado:
            return
        primera = self._estado is None
        self._estado = estado
        if not (primera and estado == "ok"):  # arrancar bien no es noticia
            log(f"temperatura, fuente {self.nombre}: {estado}")


class LibreHardwareMonitor(FuenteTemperatura):
    """El servidor web de LibreHardwareMonitor (corriendo como admin, Options > Remote Web Server).
    Hay PCs sin ninguna zona termica y con MSAcpi «no soportado» (Dell Pro 14, medido el 2026-10-03):
    ahi es la unica fuente. Si no esta corriendo, la conexion se rechaza al instante."""

    nombre = "lhm"
    # Sensores que LHM informa como temperatura pero son limites o umbrales fijos, no una lectura
    NO_LECTURA = ("limit", "resolution", "warning", "critical", "tjmax", "distance")

    def __init__(self, url: str | None = None, timeout_s: float = 1.0) -> None:
        self.url = url or os.environ.get("LIENZO_LHM_URL", "http://127.0.0.1:8085/data.json")
        self.timeout_s = timeout_s

    def leer(self) -> object:
        # sin proxy: el de la empresa no tiene que ver a 127.0.0.1
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.url, timeout=self.timeout_s) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    def elegir(self, crudo: object) -> float | None:
        """El paquete del CPU si LHM lo lee; si no (CPUs nuevos que la version de LHM todavia no
        conoce), el sensor plausible mas caliente."""
        plausibles: list[tuple[str, str, float]] = []  # (SensorId, nombre, °C)
        pendientes = [crudo]
        while pendientes:  # iterativo: un arbol muy hondo no llega al limite de recursion
            nodo = pendientes.pop()
            if not isinstance(nodo, dict):
                continue
            pendientes.extend(nodo.get("Children") or [])
            nombre = str(nodo.get("Text") or "")
            valor = str(nodo.get("Value") or "")
            es_lectura = not any(p in nombre.lower() for p in self.NO_LECTURA)
            if nodo.get("Type") != "Temperature" or "°C" not in valor or not es_lectura:
                continue
            try:
                # Value viene con el formato regional: «47,8 °C»
                c = round(float(valor.replace("°C", "").strip().replace(",", ".")), 1)
            except ValueError:
                continue
            if _plausible(c):
                plausibles.append((str(nodo.get("SensorId") or ""), nombre, c))
        cpu = [(n, c) for sid, n, c in plausibles if "cpu/" in sid]
        paquete = [c for n, c in cpu if "package" in n.lower()]
        if paquete:
            return paquete[0]
        if cpu:
            return max(c for _, c in cpu)
        return max(c for _, _, c in plausibles) if plausibles else None


class ZonasTermicasWMI(FuenteTemperatura):
    r"""Las zonas termicas de Windows por un powershell corto (~1 s). Cada PC nombra distinto su
    sensor: en una el bueno es \_TZ.THRM (\_TZ.TZ01 da 20 °C fijo, medido el 2026-09-26), y otra no
    tiene THRM (medido el 2026-10-03). Se leen todas las zonas (y, si hay permisos,
    MSAcpi_ThermalZoneTemperature) y elegir() decide."""

    nombre = "wmi"
    PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation |
  ForEach-Object { "$($_.Name)|$($_.HighPrecisionTemperature)" }
Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature |
  ForEach-Object { "acpi:$($_.InstanceName)|$($_.CurrentTemperature)" }
"""

    def leer(self) -> object:
        # por subproc.correr: sin stdin heredado (WinError 50 en un server sin consola), sin
        # ventana, y al vencer se mata el arbol en vez de quedar leyendo una tuberia
        rc, out, err = subproc.correr(["powershell", "-NoProfile", "-NonInteractive", "-Command", self.PS], timeout=5)
        if rc in (subproc.VENCIDO, subproc.NO_ARRANCO):
            raise OSError(err)  # medir() lo absorbe y lo deja en el log
        return out

    def elegir(self, crudo: object) -> float | None:
        r"""De las lineas «nombre|deciKelvin»: \_TZ.THRM si esta y es plausible; si no, la zona
        plausible mas caliente (la que importa para saber si la PC se cocina)."""
        plausibles: dict[str, float] = {}
        for linea in str(crudo).splitlines():
            nombre, _, valor = linea.strip().rpartition("|")
            try:
                c = round(float(valor) / 10 - 273.15, 1)
            except ValueError:
                continue
            if nombre and _plausible(c):
                plausibles[nombre] = c
        thrm = [v for k, v in plausibles.items() if k.upper().endswith("THRM")]
        if thrm:
            return thrm[0]
        return max(plausibles.values()) if plausibles else None


# La cadena, en orden de preferencia: LHM primero porque es la mas precisa y contesta en
# milisegundos (o rechaza al instante); WMI despues. Una fuente nueva se agrega aca.
FUENTES: list[FuenteTemperatura] = [LibreHardwareMonitor(), ZonasTermicasWMI()]


def _medir_temp() -> float | None:
    """La primera fuente de FUENTES que da una lectura plausible."""
    for fuente in FUENTES:
        t = fuente.medir()
        if t is not None:
            return t
    return None


# cara (~1 s de powershell): cacheada TEMP_TTL_S. Por lambda y no _medir_temp directo, para que se
# busque al medir (las pruebas lo cambian)
_temp = CacheEnSegundoPlano("temperatura", TEMP_TTL_S, lambda: _medir_temp())


def _temp_c() -> float | None:
    """La primera medicion espera al powershell; despues, con la cache vencida, se devuelve el
    ultimo valor y se mide de nuevo en un hilo aparte: /peers y /peer/health (que cada PC le pide a
    las otras cada 15 s) no quedan colgados un segundo esperando a WMI."""
    if not WINDOWS:
        return None
    return _temp.valor(esperar_primera=True)


# --- credenciales de git -------------------------------------------------------------------
# Las urls a probar salen de ~/.lienzo/config.json (clave "git_check": ["https://..."]). Cada
# GIT_TTL_S se corre `git ls-remote` en un hilo, sin ventana de login: si la credencial vencio, se ve
# en /peers ANTES de que una coda llegue al push (medido el 2026-10-03: la otra PC perdio el login y
# el push de la sesion 4 no salio).
GIT_TTL_S = 300


def _git_urls() -> list[str]:
    home = os.environ.get("LIENZO_HOME") or os.path.join(os.path.expanduser("~"), ".lienzo")
    try:
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            urls = json.load(f).get("git_check") or []
    except OSError, ValueError:
        return []
    return [u for u in urls if isinstance(u, str) and u.startswith("https://")]


def clasificar_git(returncode: int, stderr: str) -> str:
    """ok, vencida (pide login o lo rechaza) o error (red, repo, otra cosa)."""
    if returncode == 0:
        return "ok"
    e = (stderr or "").lower()
    pistas = (
        "authentication failed",
        "could not read username",
        "terminal prompts disabled",
        "401",
        "403",
        "credentials are incorrect",
        "invalid username or password",
        # el Git Credential Manager con la credencial vencida quiere abrir una ventana de login y,
        # sin interactividad, falla asi: es «vencida», no un error de red (medido el 2026-10-04)
        "cannot prompt because user interactivity has been disabled",
    )
    return "vencida" if any(p in e for p in pistas) else "error"


def _medir_git(urls: list[str] | None = None) -> dict | None:
    urls = _git_urls() if urls is None else urls
    if not urls:
        return None
    out = {url: _ls_remote(url) for url in urls}
    return out


def _ls_remote(url: str, timeout_s: float = 20) -> str:
    """ok, vencida o error para una url. Va por subproc.correr: salida a un ARCHIVO y no a una
    tuberia (con la credencial vencida el Git Credential Manager queda vivo como nieto de git y
    retiene la tuberia; medido el 2026-10-03, el server de la otra PC nunca termino de medir y
    git_auth quedo en None) y, al vencer, se mata el arbol entero y no solo git."""
    argv = ["git", "-c", "credential.interactive=false", "ls-remote", "--heads", url]
    rc, _out, err = subproc.correr(argv, timeout=timeout_s, sin_prompts=True)
    if rc in (subproc.VENCIDO, subproc.NO_ARRANCO):
        return "error"
    return clasificar_git(rc, err)


# la clave son las urls: si cambian, CacheEnSegundoPlano mide enseguida sin esperar GIT_TTL_S
_git = CacheEnSegundoPlano("credenciales de git", GIT_TTL_S, lambda urls: _medir_git(list(urls)))


def _git_auth() -> dict | None:
    """El ultimo resultado (None sin urls configuradas); se renueva en un hilo: nunca bloquea."""
    urls = _git_urls()  # leer el config es barato: un cambio de urls se toma enseguida, sin esperar GIT_TTL_S
    return _git.valor(tuple(urls))


# --- cuota de coda ------------------------------------------------------------------------------
# Medido el 2026-10-04: en una PC toda corrida de coda devolvia «Quota exceeded (code 154)» y el
# tablero no lo mostraba. Se mira sin gastar tokens: la hora del ultimo «Quota exceeded» del log de
# coda contra la del ultimo consumo de la tabla `usage` de su base. Lo mas nuevo gana.
CODA_CUOTA_TTL_S = 60
CODA_LOG_TAIL = 1024 * 1024
CUOTA_ERR = "Quota exceeded"
# lo formal es el codigo de la API de Globant que coda deja en el log (HTTP 401 con
# {"error":{"message":"Quota exceeded","code":154}}); el texto queda como respaldo
CUOTA_CODIGO = '"code":154'


def _coda_home() -> str:
    return os.environ.get("CODA_HOME") or os.path.join(os.path.expanduser("~"), ".coda")


def _ultimo_error_de_cuota(home: str) -> float | None:
    """Epoch (s) del ultimo «Quota exceeded» en coda.log (la cola), o None."""
    p = os.path.join(home, "logs", "coda.log")
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            f.seek(max(0, size - CODA_LOG_TAIL))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    ultimo = None
    for linea in data.splitlines():
        if CUOTA_ERR not in linea and CUOTA_CODIGO not in linea and "(code 154)" not in linea:
            continue
        try:
            t = json.loads(linea).get("time")
            ultimo = dt.datetime.fromisoformat(str(t)).timestamp()
        except ValueError, AttributeError, TypeError:
            continue
    return ultimo


def _ultimo_uso(home: str) -> float | None:
    """Epoch (s) del ultimo consumo registrado en la base de coda (tabla usage), o None."""
    import sqlite3

    p = os.path.join(home, "coda.db")
    if not os.path.isfile(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
        try:
            fila = con.execute("SELECT MAX(created_at) FROM usage").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return fila[0] / 1000 if fila and fila[0] else None


def clasificar_cuota(error_s: float | None, uso_s: float | None) -> str:
    """ok, agotada o desconocida: el hecho mas nuevo manda."""
    if error_s is None and uso_s is None:
        return "desconocida"
    if error_s is not None and (uso_s is None or error_s > uso_s):
        return "agotada"
    return "ok"


def _medir_cuota() -> str | None:
    home = _coda_home()
    if not os.path.isdir(home):
        return None  # coda no esta instalado en esta PC: no hay nada que decir
    return clasificar_cuota(_ultimo_error_de_cuota(home), _ultimo_uso(home))


_cuota = CacheEnSegundoPlano("cuota de coda", CODA_CUOTA_TTL_S, lambda: _medir_cuota())


def coda_cuota(esperar: bool = False) -> str | None:
    """ok, agotada, desconocida, o None si coda no esta en esta PC. Nunca bloquea (salvo `esperar`)."""
    try:
        return _cuota.valor(esperar_primera=esperar)
    except Exception:  # la salud nunca levanta
        return None


# {agente: "agotada hasta HH:MM" | "agotada"} de las tarjetas de esta PC (Claude, Codex, Pi avisan el
# limite de uso en su transcripcion): lo enchufa server.py; health se importa suelto y no ve sesiones
cuotas_de_sesiones: Callable[[], dict] = dict


def cuotas() -> dict:
    """Cuota por agente en esta PC: ok, agotada (o «agotada hasta HH:MM») o desconocida. Coda por su log
    y su base; los demas por el limite de uso que sus tarjetas tienen vigente. Nunca levanta."""
    out: dict = {}
    c = coda_cuota()
    if c is not None:
        out["coda"] = c
    try:
        out.update(cuotas_de_sesiones() or {})
    except Exception as e:  # la salud nunca levanta: sin el dato de sesiones queda lo de coda
        log(f"cuotas de las sesiones: {type(e).__name__}: {e}")
    return out


def agentes_que_entran(mem_free_gb: float | None) -> int | None:
    """Cuantos agentes mas se pueden abrir sin bajar de RESERVA_GB libres. None sin dato de memoria."""
    if mem_free_gb is None:
        return None
    return max(0, int((mem_free_gb - RESERVA_GB) // GB_POR_AGENTE)) if mem_free_gb > RESERVA_GB else 0


def _git_auth_seguro() -> dict | None:
    try:
        return _git_auth()
    except Exception:  # la salud nunca levanta; un fallo aca no puede tapar memoria ni CPU
        return None


def snapshot() -> dict:
    """Memoria, CPU y temperatura de esta PC, ahora mismo. Nunca levanta una excepcion."""
    try:
        mem_free_gb, mem_total_gb = _memoria()
    except OSError:
        mem_free_gb = mem_total_gb = None
    try:
        cpu_pct = _cpu_pct()
    except OSError:
        cpu_pct = None
    try:
        temp_c = _temp_c()
    except OSError:
        temp_c = None
    return {
        "mem_free_gb": round(mem_free_gb, 2) if mem_free_gb is not None else None,
        "mem_total_gb": round(mem_total_gb, 2) if mem_total_gb is not None else None,
        "cpu_pct": cpu_pct,
        "temp_c": temp_c,
        "agentes_libres": agentes_que_entran(mem_free_gb),
        "git_auth": _git_auth_seguro(),
        "coda_cuota": coda_cuota(),
        "cuotas": cuotas(),
        "ts": _now(),
    }
