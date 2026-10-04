"""El comando de un cartel «Approval Required» de coda, leído de la pantalla.

Vive en el paquete y no en el skill porque lo usan los dos lados de la aprobación con `expect`
(revisión 2026-10-04, 0.2): el aprobador del skill (skills/lienzo/aprobador.py) arma la huella del
comando que juzgó, y el server rearma la misma cuenta sobre la pantalla del momento antes de teclear.
Si cada lado tuviera su copia, un cambio en una sola haría que ninguna aprobación coincida.
"""

import hashlib
import re

SEP = chr(0x2502)  # │: el panel lateral de coda; lo que va a su derecha no es el comando


def comando_visible(lineas):
    """El comando del último cartel «Approval Required», o None si no hay cartel.

    Junta las líneas del cartel sin separador: la pantalla parte el comando en cualquier lado, a
    veces en medio de una palabra. Los espacios DENTRO de cada línea se conservan (sirven para
    separar palabras); `compacto` los saca todos cuando hace falta comparar."""
    izq = [ln.split(SEP)[0].rstrip() for ln in lineas if ln.strip()]
    i = max((k for k, ln in enumerate(izq) if "Approval Required" in ln), default=None)
    if i is None:
        return None
    cuerpo = []
    for ln in izq[i + 1 :]:
        if "ask by command policy" in ln or ln.strip().startswith(("Yes", "❯ Yes", "No")):
            break
        cuerpo.append(ln.strip())
    return "".join(cuerpo)


def compacto(cmd):
    """El comando sin ningún espacio: así no depende de dónde cortó la línea la pantalla."""
    return re.sub(r"\s+", "", cmd)


def huella_comando(cmd):
    """sha256 hex del comando compacto. Solo del comando, no de la pantalla entera: el spinner y
    el reloj de coda la cambian sin que cambie lo que se aprueba."""
    return hashlib.sha256(compacto(cmd).encode("utf-8")).hexdigest()


def huella(lineas):
    """La huella del comando del cartel en `lineas`, o None si no hay cartel."""
    cmd = comando_visible(lineas)
    return None if cmd is None else huella_comando(cmd)
