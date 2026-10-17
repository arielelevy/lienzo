"""Informes persistidos dentro de rules.json; sin otra cola ni acuses implícitos.

El llamador toma state.lock y guarda la regla antes de usar el transporte.
"""


def pendientes(rule):
    return any(item.get("estado") != "integrado" for item in rule.get("informes", []))


def conservar(rule, foto, timestamp):
    informes = rule.setdefault("informes", [])
    existente = next((x for x in informes if x["id"] == foto["huella"]), None)
    if existente is not None:
        return existente
    informe = {"id": foto["huella"], "respuesta": foto["texto"],
               "created": timestamp, "estado": "pendiente", "intentos": 0}
    informes.append(informe)
    return informe


def resultado(informe, code, res, timestamp):
    informe["codigo"] = code
    informe["transporte"] = dict(res)
    if informe["estado"] in ("recibido", "integrado"):
        return
    informe["estado"] = "entregado" if code == 200 and res.get("estado") == "entregado" else "pendiente"
    if informe["estado"] == "entregado":
        informe["entregado_at"] = timestamp


def acusar(rule, informe_id, estado, actor, timestamp):
    if actor != rule.get("to"):
        return 403, {"error": "el acuse debe venir de la sesion destino"}
    if estado not in ("recibido", "integrado"):
        return 400, {"error": "estado debe ser recibido o integrado"}
    informe = next((x for x in rule.get("informes", []) if x["id"] == informe_id), None)
    if informe is None:
        return 404, {"error": "informe desconocido"}
    if estado == "integrado" and informe["estado"] not in ("recibido", "integrado"):
        return 409, {"error": "falta acuse explicito de recepcion"}
    if informe["estado"] == "integrado" or informe["estado"] == estado:
        return 200, informe
    # Recepcion explicita tambien prueba entrega de un transporte asincronico.
    informe.setdefault("entregado_at", timestamp)
    informe["estado"] = estado
    informe[estado + "_at"] = timestamp
    informe[estado + "_por"] = actor
    return 200, informe


def confirmar_envio(rule, envio_id, res, timestamp):
    """Conciliar una confirmacion final del transporte, sin producir otro envio."""
    for informe in rule.get("informes", []):
        if (informe.get("transporte") or {}).get("envio_id") == envio_id:
            resultado(informe, 200, res, timestamp)
            return True
    return False
