"""Ruta de Chrome remoto: destino explícito y contenido cifrado con la clave del par."""

import hashlib
import hmac
import json
import secrets

import browser_remote
import identity
import mirror
import secretos


def channel_key(key):
    return hmac.new(key, b"lienzo/chrome-remoto/v1", hashlib.sha256).digest()


def dispatch(data):
    pc = data.get("pc")
    if not isinstance(pc, str) or not pc:
        return 400, {"error": "Elegí la PC donde querés abrir Chrome"}
    command = {k: v for k, v in data.items() if k != "pc"}
    if len(json.dumps(command)) > 65536:
        return 400, {"error": "Pedido demasiado grande"}
    if pc == identity.pc_id():
        return browser_remote.HOST.request(command)
    conn = mirror.MIRROR.conn_of(pc)
    if conn is None:
        return 404, {"error": "La PC elegida no está emparejada"}
    if mirror.MIRROR.supports(pc, "browser.remote") is False:
        return 409, {"error": "Actualizá y reiniciá Lienzo en la otra PC para usar Chrome remoto"}
    key = channel_key(conn.key)
    request_id = secrets.token_hex(16)
    body = secretos.cifrar(key, json.dumps({"id": request_id, "command": command}))
    code, result = mirror.MIRROR.forward(pc, "POST", "/browser", body, timeout=28)
    if code != 200:
        return code, result
    try:
        reply = json.loads(secretos.descifrar(key, result))
        if reply["id"] != request_id:
            raise ValueError("respuesta de otro pedido")
        return reply["status"], reply["result"]
    except ValueError, KeyError, TypeError:
        return 502, {"error": "La respuesta de Chrome remoto no se pudo verificar"}


def from_peer(data, pair_key):
    try:
        key = channel_key(pair_key)
        request = json.loads(secretos.descifrar(key, data))
        if not isinstance(request["id"], str) or len(request["id"]) != 32:
            raise ValueError("id invalido")
        code, result = browser_remote.HOST.request(request["command"])
        return 200, secretos.cifrar(key, json.dumps({"id": request["id"], "status": code, "result": result}))
    except ValueError, KeyError, TypeError:
        return 400, {"error": "Pedido de Chrome remoto inválido"}
