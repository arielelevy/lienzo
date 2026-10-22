"""Registros JSONL rotados por tamaño: los pedidos que el server rechaza y cada POST /peer/run.

Decisión 2 de Ariel (2026-10-22): la próxima falla de Dot tiene que dejar evidencia. Cada 401, 403
o Host no válido queda con hora, origen, ruta, método y motivo; si un cliente dice que la API le
negó el acceso y acá no hay nada, el bloqueo fue antes del server (sandbox, firewall, proxy).
Decisión 10: cada comando remoto deja su línea. Nunca se guardan cuerpos, query, cookies ni firmas;
la salida de un comando, sólo su tamaño. El archivo pasa a `.1` al llegar a TOPE_BYTES: como mucho
quedan dos, y un pedido rechazado en loop no llena el disco."""

import datetime as dt
import json
import os
import re
import threading
import time

import state

RECHAZOS = "rechazos"
RUN = "remote_run"
TOPE_BYTES = 1 << 20
CODIGOS_RECHAZO = (401, 403)
MOTIVOS_400 = ("Host no valido",)  # el 400 del reencuadre DNS (hallazgo C1) también es un rechazo
AGRUPAR_S = 60.0  # el mismo rechazo (listener, ip, código, método, ruta, motivo) va una vez por minuto
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.Lock()
_vistos: dict[tuple, list] = {}  # clave -> [última línea escrita (monotonic), omitidos desde entonces]


def _archivo(nombre: str) -> str:
    return os.path.join(state.LIENZO, f"{nombre}.jsonl")


def corto(valor, largo: int = 200) -> str:
    """Texto de una línea y acotado: una ruta o un User-Agent no meten saltos en el registro."""
    return _CONTROL.sub(" ", str(valor or ""))[:largo]


def anexar(nombre: str, entrada: dict) -> None:
    """Agrega una línea con la hora local; un error de disco no tumba la respuesta que se loguea."""
    linea = json.dumps({"hora": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **entrada})
    path = _archivo(nombre)
    with _lock:
        try:
            if os.path.getsize(path) >= TOPE_BYTES:
                os.replace(path, path + ".1")
        except FileNotFoundError:
            pass
        except OSError as e:
            state.log(f"bitacora {nombre}: no se pudo rotar ({type(e).__name__})")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError as e:
            state.log(f"bitacora {nombre}: no se pudo escribir ({type(e).__name__})")


def ultimas(nombre: str, n: int = 200) -> list[dict]:
    """Las últimas `n` entradas, de la más vieja a la más nueva, contando la rotada."""
    path = _archivo(nombre)
    lineas: list[str] = []
    # sin el lock: el archivo sólo crece o se renombra entero, y un rechazo no espera a esta lectura
    for p in (path + ".1", path):
        try:
            with open(p, encoding="utf-8") as f:
                lineas.extend(f.read().splitlines())
        except FileNotFoundError:
            pass
    salida = []
    for linea in lineas[-n:] if n > 0 else []:
        try:
            salida.append(json.loads(linea))
        except ValueError:
            continue
    return salida


def es_rechazo(codigo: int, motivo) -> bool:
    return codigo in CODIGOS_RECHAZO or (codigo == 400 and motivo in MOTIVOS_400)


def rechazo(*, listener: str, metodo: str, ruta: str, ip: str, codigo: int, motivo, **extra) -> None:
    """`extra`: peer (el X-Lienzo-Peer que dice ser), origin, agente (User-Agent), tunel.

    Un peer con el reloj corrido reintenta cada pocos segundos: sin agrupar, el tope de 1 MB se
    llenaría en horas y se llevaría el rechazo que se quería guardar. La línea siguiente a la ventana
    lleva `omitidos`."""
    clave = (listener, ip, codigo, metodo, ruta, motivo)
    ahora = time.monotonic()
    with _lock:
        visto = _vistos.get(clave)
        if visto and ahora - visto[0] < AGRUPAR_S:
            visto[1] += 1
            return
        omitidos = visto[1] if visto else 0
        if len(_vistos) > 512:  # no crece sin límite con rutas o IPs inventadas
            _vistos.clear()
        _vistos[clave] = [ahora, 0]
    entrada = {
        "listener": listener,
        "codigo": codigo,
        "metodo": corto(metodo, 16),
        "ruta": corto(ruta),
        "ip": corto(ip, 64),
        "motivo": corto(motivo),
    }
    entrada.update({k: corto(v) if isinstance(v, str) else v for k, v in extra.items()})
    if omitidos:
        entrada["omitidos"] = omitidos
    anexar(RECHAZOS, entrada)
