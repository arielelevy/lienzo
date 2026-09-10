#!/usr/bin/env python
"""lienzo-server: watcher de ~/.lienzo/events, registro de sesiones, cola de transcripciones,
liveness por PID, SSE y envio por inyeccion. Solo stdlib. Bind 127.0.0.1:7321.

    python server.py [--port 7321] [--no-sweep]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth
import transcripts
from rules import at_near, connections_of, local_dt, purge_stale_at_rules, rules_loop
from sessions import (
    add_link,
    answer_dialog,
    answer_pending,
    clean_attachments,
    consume_events,
    drop_session,
    hand_over,
    interrupt_session,
    liveness_loop,
    load_sessions,
    public_pending,
    read_screen,
    save_attachment,
    scan_pending,
    screen_loop,
    send_to_session,
    set_coordinator,
    set_stopped,
    set_title,
    sweep_once,
    touch,
)
from state import (
    ADJUNTOS,
    ANSWERS,
    DIST,
    EVENTS,
    MIME,
    PENDING,
    SESSIONS,
    STALE_SESSION_H,
    UI_CONFIG_KEYS,
    clients,
    is_disconnect,
    links,
    lock,
    log,
    now,
    pending,
    public_config,
    rules,
    sessions,
    set_config_key,
    short,
)

CLOUDFLARED = os.path.join(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared", "cloudflared.exe"
)
remote_url: str | None = None
# alta desde el celular con un solo QR: token de 15 min que entrega passphrase + otpauth una vez
enroll: dict | None = None
ENROLL_S = 15 * 60

# Techos del cuerpo del pedido (hallazgo A3 del pentest): se rechaza con 413 antes de leer un byte,
# asi un cuerpo gigante y sin autenticar no puede inflar la memoria. /attach sube archivos e
# imagenes, por eso tiene su propio techo, mas alto.
MAX_BODY = 8 * 1024 * 1024
MAX_ATTACH = 64 * 1024 * 1024

# --- HTTP ------------------------------------------------------------------------------


MIN_EVERY_S = 60
MAX_FIRES = 50


def clamp_fires(value) -> int:
    """max_fires: cuantas veces puede disparar una regla, entre 1 y MAX_FIRES."""
    return max(1, min(int(value), MAX_FIRES))


def parse_every_s(v) -> tuple[int | None, str | None]:
    """Periodo de una regla 'at': (segundos, error). None sin error es un solo disparo."""
    malo = "every_s debe ser un entero en segundos"
    if v is None:
        return None, None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None, malo
    try:
        f = float(v)
    except ValueError:
        return None, malo
    if f != int(f):
        return None, malo
    if int(f) < MIN_EVERY_S:
        return None, f"every_s debe ser al menos {MIN_EVERY_S} segundos"
    return int(f), None


def at_fields(d: dict, current: dict | None = None) -> tuple[dict | None, str | None]:
    """Campos de repeticion de una regla 'at' (POST o PUT): every_s (entero >= MIN_EVERY_S, o None
    = un solo disparo), max_fires (1..MAX_FIRES; 5 por defecto si es periodica), skip_busy (True por
    defecto si es periodica). `current` es la regla que se edita (PUT), para no pisar lo que no
    vino. Devuelve (campos, error)."""
    cur = current or {}
    every = cur.get("every_s")
    if "every_s" in d:
        every, err = parse_every_s(d["every_s"])
        if err:
            return None, err
    max_fires = cur.get("max_fires")
    if d.get("max_fires") is not None:
        try:
            max_fires = clamp_fires(d["max_fires"])
        except (TypeError, ValueError):
            return None, "max_fires debe ser un numero"
    elif every and (max_fires or 1) <= 1:
        max_fires = 5  # pasa a periodica sin tope explicito: 5 disparos
    skip_busy = cur.get("skip_busy")
    if "skip_busy" in d:
        skip_busy = bool(d["skip_busy"])
    elif skip_busy is None:
        skip_busy = bool(every)
    return {
        "every_s": every,
        "max_fires": int(max_fires or 1),
        "skip_busy": bool(skip_busy),
        "repeat": bool(every),
    }, None


def parse_at(value) -> dt.datetime:
    """Hora de una regla `at`, siempre local: naive se asume local, aware (la UI manda UTC con Z) se
    convierte, asi todas las reglas guardan `at` con el mismo offset. Es rules.local_dt, que es de
    donde sale toda hora del lienzo, pero levantando ValueError: aca un `at` ilegible es un 400 al
    cliente, no una regla que se saltea en silencio."""
    at = local_dt(value)
    if at is None:
        raise ValueError(f"{value!r} no es una fecha ISO")
    return at


def find_enabled(pred) -> dict | None:
    """La primera regla habilitada que cumple `pred`, leyendo la lista con el lock tomado. Es el
    "¿ya hay una parecida?" de las tres validaciones que miran las reglas que ya existen."""
    with lock:
        return next((r for r in rules.items if r.get("enabled") and pred(r)), None)


def check_rule(d: dict) -> tuple[int, dict] | None:
    """Lo que se valida igual para las dos clases de regla: el kind y que las sesiones existan.
    Devuelve el (codigo, cuerpo) del rechazo, o None si el pedido pasa."""
    if d.get("kind") not in ("on_stop", "at"):
        return 400, {"error": "kind debe ser on_stop o at"}
    if d.get("to") not in sessions:
        return 404, {"error": "sesion destino desconocida"}
    if d["kind"] == "on_stop" and d.get("from") not in sessions:
        return 404, {"error": "sesion origen desconocida"}
    return None


def new_rule(d: dict, text: str, **extra) -> dict:
    """Los campos que toda regla nueva tiene iguales; `extra` agrega los propios de cada clase. El
    orden de las claves es el del cuerpo que devuelve /rules, asi que se arma en ese orden."""
    return {
        "id": secrets.token_hex(6),
        "kind": d["kind"],
        "from": d.get("from") or None,
        "to": d["to"],
        "text": text,
        **extra,
    }


def create_on_stop(d: dict, text: str) -> tuple[int, dict]:
    """Regla on_stop nueva: se rechaza el bucle (ya hay una en sentido inverso) y la conexion
    repetida (mismo origen, mismo destino y mismo texto)."""
    inverse = find_enabled(
        lambda r: r.get("kind") == "on_stop" and r.get("from") == d["to"] and r.get("to") == d["from"]
    )
    if inverse:
        return 409, {
            "error": f"crearía un bucle {d['from'][:8]}↔{d['to'][:8]}: "
            f"ya existe la regla {inverse['id']} en sentido inverso"
        }
    dup = find_enabled(
        lambda r: (
            r.get("kind") == "on_stop"
            and r.get("to") == d["to"]
            and (r.get("from") or None) == (d.get("from") or None)
            and (r.get("text") or "").strip() == text.strip()
        )
    )
    if dup:
        return 409, {"error": "ya existe esa conexión", "rule_id": dup["id"]}
    rule = new_rule(
        d,
        text,
        at=None,
        repeat=bool(d.get("repeat")),
        max_fires=clamp_fires(d.get("max_fires") or 1),
        fired=0,
        enabled=True,
        created=now(),
    )
    rules.add(rule, cap=500)
    log(f"regla nueva {rule['id']}: on_stop -> {rule['to'][:8]}")
    return 200, rule


def create_at(d: dict, text: str) -> tuple[int, dict]:
    """Regla at nueva: una programada, con repeticion o de un solo disparo."""
    try:
        at = parse_at(d.get("at"))
    except ValueError:
        return 400, {"error": "at debe ser una fecha ISO"}
    extra, err = at_fields(d)
    if err:
        return 400, {"error": err}
    # dos programadas a la misma consola en el mismo minuto se inyectan juntas ("Continuar" y
    # "continua" a las 01:01): choca cualquier `at` habilitada a +-2 min, periodica o no, sea cual
    # sea el texto; con "replace": true la nueva reemplaza a la existente
    clash = find_enabled(lambda r: r.get("kind") == "at" and r.get("to") == d["to"] and at_near(r, at))
    if clash:
        if d.get("replace") is not True:
            hhmm = parse_at(clash["at"]).strftime("%H:%M")
            return 409, {
                "error": f"ya hay una programada a las {hhmm} para esa sesión",
                "rule_id": clash["id"],
                "at": clash["at"],
                "text": clash.get("text") or "",
                "replace": True,
            }
        rules.remove(lambda r: r["id"] == clash["id"])
        log(
            f"regla {clash['id']} ({clash.get('at')} {short(clash.get('text') or '', 40)!r}) reemplazada por una nueva a la misma hora"
        )
    # de at_fields salen every_s, max_fires, skip_busy y repeat=bool(every_s)
    rule = new_rule(d, text, at=at.isoformat(timespec="seconds"), fired=0, enabled=True, created=now(), **extra)
    rules.add(rule, cap=500)
    cada = f" cada {rule['every_s']} s x{rule['max_fires']}" if rule.get("every_s") else ""
    log(f"regla nueva {rule['id']}: at -> {rule['to'][:8]} {rule['at']}{cada}")
    return 200, rule


def create_rule(d: dict) -> tuple[int, dict]:
    """POST /rules: valida lo comun y deja el armado en la funcion de la clase que corresponda.
    Devuelve (codigo, cuerpo)."""
    rechazo = check_rule(d)
    if rechazo is not None:
        return rechazo
    text = str(d.get("text") or "")
    return create_on_stop(d, text) if d["kind"] == "on_stop" else create_at(d, text)


def edit_rule(rule_id: str, d: dict) -> tuple[int, dict]:
    """PUT /rules/<id>: edita una conexion pendiente (doble click en la flecha): texto, hora,
    repeticion. Una programada que ya disparo se puede reprogramar: vuelve a quedar vigente.
    Devuelve (codigo, cuerpo), como create_rule. Primero valida todo y despues escribe: un 400 a
    mitad de camino dejaria la regla editada por partes."""
    at = None
    if d.get("at") is not None:
        try:
            at = parse_at(d["at"])
        except ValueError:
            return 400, {"error": "at debe ser una fecha ISO"}
    if "text" in d and not isinstance(d["text"], str):
        return 400, {"error": "text debe ser un texto"}
    try:
        max_fires = clamp_fires(d["max_fires"]) if d.get("max_fires") is not None else None
    except (TypeError, ValueError):
        return 400, {"error": "max_fires debe ser un numero"}
    with lock:
        r = next((x for x in rules.items if x["id"] == rule_id), None)
        if r is None:
            return 404, {"error": "conexion desconocida"}
        extra = None
        if r.get("kind") == "at":
            extra, err = at_fields(d, r)
            if err:
                return 400, {"error": err}
        # de aca en adelante no se rechaza nada mas: `extra` con algo adentro es la regla 'at' ya validada
        if "text" in d:
            r["text"] = d["text"]
        if extra is not None:
            r.update(extra)  # every_s (null = un disparo), max_fires, skip_busy, repeat
            if at is not None:
                r["at"] = at.isoformat(timespec="seconds")
                if not r.get("enabled"):
                    r["enabled"] = True
                    r["fired"] = 0
                    r.pop("disabled_at", None)
        if r.get("kind") == "on_stop":
            if "repeat" in d:
                r["repeat"] = bool(d["repeat"])
            if max_fires is not None:
                r["max_fires"] = max_fires
        rules.save()
    rules.publish()
    log(f"regla {r['id']} editada: {r['kind']} -> {r['to'][:8]} {r.get('at') or ''} {short(r.get('text') or '', 60)!r}")
    return 200, r


class QuietServer(ThreadingHTTPServer):
    """socketserver imprime un traceback entero en stderr cada vez que el navegador cierra una
    conexion keep-alive mientras se lee la proxima peticion (WinError 10053). Eso no es un error
    nuestro: se calla. Cualquier otra excepcion va al log propio, en una linea en consola."""

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if e is not None and is_disconnect(e):
            return
        log(traceback.format_exc())


# Las vistas de una tarjeta, /sessions/<id>/<vista>: las atiende _session_view con una sola busqueda.
SESSION_VIEWS = ("screen", "connections", "turns", "digest")


class Handler(BaseHTTPRequestHandler):
    server_version = "lienzo/0.1"
    protocol_version = "HTTP/1.1"
    # cierra un socket que no manda nada en 30 s (slow-loris, hallazgo A3 del pentest): un cuerpo
    # declarado y no enviado retenia el hilo para siempre. El SSE escribe un latido cada 15 s, asi
    # que las conexiones /events largas no lo alcanzan.
    timeout = 30

    def log_message(self, fmt, *args):  # silencio; el log propio alcanza
        pass

    def _server_error(self, e: BaseException) -> None:
        """Final de todos los do_*: si el navegador cerro la conexion a mitad de la respuesta no hay
        a quien contestar. Cualquier otra excepcion va entera al log con un id corto, y al cliente le
        llega ese id y nada mas: str(e) podia llevar rutas y nombres de la maquina, y por el tunel
        eso sale hacia afuera. El id esta en las dos puntas para poder cruzarlas."""
        if is_disconnect(e):
            return
        eid = secrets.token_hex(4)
        log(f"error {eid} en {self.command} {self.path}:\n{traceback.format_exc()}")
        # el id va tambien dentro de `error`: la UI muestra ese campo tal cual, asi se ve sin tocar web/
        return self._json(500, {"error": f"error interno del lienzo ({eid})", "error_id": eid})

    def _json(self, code: int, obj, extra_headers: dict | None = None) -> None:
        return self._send_json(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), extra_headers)

    def _send_json(self, code: int, body: bytes, extra_headers: dict | None = None) -> None:
        """Cuerpo JSON ya serializado. Lo que se arma con el lock tomado se escribe con esto sin el:
        el write al socket tarda lo que tarde el cliente en leer (por el tunel, un celular), y con el
        lock tomado eso frena los hooks y todo lo demas."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> list[str]:
        """Primera linea de cada do_*, antes de decidir nada. Lee el cuerpo: si queda sin leer en el
        socket (un 403 o un 404 tempranos), el siguiente request de la misma conexion keep-alive lo
        toma como linea de pedido y contesta 501. Y parte la ruta: devuelve los tramos de la URL, que
        es con lo que cada handler elige, y deja la query en `self.query`."""
        u = urllib.parse.urlparse(self.path)
        self.query = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        n = int(self.headers.get("Content-Length") or 0)
        # hallazgo A3: rechazar un cuerpo gigante ANTES de leerlo. /attach sube archivos (techo
        # alto); el resto son cuerpos JSON chicos. Si excede, no se drena: se cierra la conexion.
        cap = MAX_ATTACH if (len(parts) == 3 and parts[0] == "sessions" and parts[2] == "attach") else MAX_BODY
        if n > cap:
            self.oversize = n
            self.raw = b""
            self.close_connection = True
            return parts
        self.oversize = 0
        self.raw = self.rfile.read(n) if n else b""
        return parts

    def _too_big(self) -> bool:
        """True (con el 413 ya contestado) si el cuerpo excedio el techo de _route."""
        if getattr(self, "oversize", 0):
            self._json(413, {"error": "cuerpo demasiado grande"})
            return True
        return False

    def _host_ok(self) -> bool:
        """Valida el Host de cada pedido (hallazgo C1: sin esto un reencuadre DNS le entrega el
        lienzo entero a cualquier pagina web que la victima abra). Acepta solo los nombres locales
        y, si el tunel esta arriba, exactamente el host de remote_url. Cualquier otro Host: afuera.
        Con esto _csrf_ok queda parado sobre un Host ya de confianza."""
        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0].strip("[]") if host else ""
        if hostname in ("127.0.0.1", "localhost", "::1"):
            return True
        if remote_url:
            rh = (urllib.parse.urlparse(remote_url).hostname or "").lower()
            if rh and hostname == rh:
                return True
        return False

    def _session(self, sid: str) -> dict | None:
        """La tarjeta pedida, o None con el 404 ya contestado. Es el arranque de toda ruta
        /sessions/<id>/..., que si no repite la busqueda con el lock y el mismo mensaje de error."""
        with lock:
            s = sessions.get(sid)
        if s is None:
            self._json(404, {"error": "sesion desconocida"})
        return s

    def _json_body(self) -> dict:
        """JSON del cuerpo tolerante a clientes que mandan latin-1 (un curl desde Git Bash)."""
        raw = self.raw
        if not raw:
            return {}
        try:
            d = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            d = json.loads(raw.decode("cp1252", errors="replace"))
        return d if isinstance(d, dict) else {}

    # --- identidad del cliente ------------------------------------------------------
    def _client_ip(self) -> str:
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _via_tunnel(self) -> bool:
        return bool(self.headers.get("CF-Connecting-IP")) or self.headers.get("X-Forwarded-Proto") == "https"

    def _is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1") and not self._via_tunnel()

    def _authed(self) -> bool:
        """Decision del autor (2026-09-05): en la propia PC no se pide login. El server solo
        escucha en 127.0.0.1, asi que 'local' es una conexion sin cabeceras del tunel. Lo que
        entra por cloudflared trae CF-Connecting-IP y exige la cookie (passphrase + TOTP).
        Hallazgo A2: cae CERRADA. Si auth.json desaparece con el tunel arriba, lo remoto pasa a
        exigir cookie igual (auth.check da False sin sesiones), no queda abierto. El alta (/setup,
        /enroll, /login) sigue saliendo por su lista blanca de rutas, antes de este chequeo."""
        return self._is_local() or auth.check(auth.parse_cookie(self.headers.get("Cookie")))

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Lienzo") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        ohost = origin.split("//", 1)[-1].lower()
        host = (self.headers.get("Host") or "").lower()
        # el propio host, o el dev server de Vite en la misma maquina (hallazgo A1: puerto fijo
        # 5173, no cualquier puerto de localhost)
        return ohost == host or ohost in ("localhost:5173", "127.0.0.1:5173")

    def do_GET(self):
        parts = self._route()
        if not self._host_ok():
            return self._json(400, {"error": "Host no valido"})
        try:
            if not parts:
                index = os.path.join(DIST, "index.html")
                if not os.path.exists(index):
                    return self._json(503, {"error": "falta el build de la UI: cd web && npm install && npm run build"})
                return self._file(index, "text/html; charset=utf-8")
            if parts[0] == "assets" and len(parts) == 2 and os.path.isdir(DIST):
                return self._asset(parts[1])
            if parts == ["favicon.svg"] and os.path.isdir(DIST):
                # el icono de la pestaña: vive en la raiz del build, no en assets/
                return self._file(os.path.join(DIST, "favicon.svg"), "image/svg+xml", cache="public, max-age=86400")
            if parts == ["health"]:
                return self._json(200, {"ok": True, "sessions": len(sessions), "pending": len(pending), "ts": now()})
            if parts == ["auth"]:
                return self._json(
                    200,
                    {
                        "configured": auth.configured(),
                        "authenticated": self._authed(),
                        "local": self._is_local(),
                        "remote_url": remote_url,
                        "mode": auth.mode(),
                    },
                )
            if parts == ["totp"]:
                # volver a ver el QR de Authenticator (segundo telefono, o alta interrumpida): solo local
                if not self._is_local():
                    return self._json(403, {"error": "solo desde la PC"})
                cur = auth.current_otpauth(os.environ.get("USERNAME", "lienzo"))
                return self._json(200, cur) if cur else self._json(404, {"error": "sin acceso configurado"})
            if parts == ["enroll"]:
                return self._enroll()
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["sessions"]:
                # serializar con el lock (es CPU pura) y escribir afuera: es el cuerpo mas grande
                # que manda el server, y antes se escribia al socket con el lock tomado
                with lock:
                    tablero = json.dumps(
                        sorted(sessions.values(), key=lambda s: (s["repo"], s["started"])), ensure_ascii=False
                    ).encode("utf-8")
                return self._send_json(200, tablero)
            if parts == ["pending"]:
                return self._json(200, public_pending())
            if parts == ["links"]:
                return self._json(200, links.snapshot())
            if parts == ["rules"]:
                return self._json(200, rules.snapshot())
            if parts == ["config"]:
                return self._json(200, public_config())
            # el sello del bundle servido: el tablero lo consulta cada 30 s y se recarga cuando
            # cambia (ver `build_id`). Ruta propia y no el latido del SSE porque el latido sale
            # solo cuando la cola esta en silencio 15 s, y con el tablero activo casi nunca lo esta
            if parts == ["build"]:
                return self._json(200, {"build": build_id()})
            if parts == ["events"]:
                return self._sse()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] in SESSION_VIEWS:
                return self._session_view(parts[1], parts[2])
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _asset(self, name: str) -> None:
        """Un estatico del build de Vite. Sin ".." posibles: el nombre sale de partir la ruta por
        "/", y de ahi no puede venir un separador de Windows ni un archivo oculto."""
        if "\\" in name or name.startswith("."):
            return self._json(404, {"error": "ruta invalida"})
        return self._file(
            os.path.join(DIST, "assets", name),
            MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
            cache="public, max-age=31536000, immutable",
        )

    def _enroll(self) -> None:
        """GET /enroll?token=...: entrega passphrase y otpauth una sola vez, para el alta desde el
        celular con un QR. El token es la credencial; vale 15 min desde el alta y se apaga solo."""
        global enroll
        tok = self.query.get("token", [""])[0]
        with lock:
            e = enroll
            if e and time.time() > e["expires"]:
                enroll = e = None
        if not e or not tok or not secrets.compare_digest(tok, e["token"]):
            log(f"enroll rechazado desde {self._client_ip()}")
            return self._json(410, {"error": "el enlace de alta vencio o no es valido; rehacer desde la PC"})
        log(f"enroll entregado a {self._client_ip()} (token consumido)")
        # hallazgo M4: el token es de un solo uso. Consumirlo aca deja que una filtracion del enlace
        # (queda en el historial del celular y en los logs de Cloudflare) se note: el canje legitimo
        # invalida el token, un segundo intento con el mismo cae en el 410.
        with lock:
            enroll = None
        return self._json(
            200,
            {"passphrase": e["passphrase"], "otpauth": e["otpauth"], "expires_in": int(e["expires"] - time.time())},
        )

    def _session_view(self, sid: str, view: str) -> None:
        """Las cuatro vistas de una tarjeta (SESSION_VIEWS), con una sola busqueda de la sesion. Una
        vista que no este en la lista no llega hasta aca: sigue cayendo en el 404 de ruta
        desconocida de do_GET, no en el de sesion desconocida."""
        s = self._session(sid)
        if s is None:
            return None
        if view == "connections":
            return self._json(200, connections_of(sid))
        if view == "screen":
            if not s.get("pid") or s.get("orphan"):
                return self._json(409, {"ok": False, "error": "sin consola que leer"})
            return self._json(200, read_screen(s["pid"]))
        if not s.get("transcript_path") or not os.path.exists(s["transcript_path"]):
            return self._json(200, {"meta": {}, "turns": [], "has_more": False, "note": "sin transcripcion"})
        try:
            n = int(self.query.get("n", ["10"])[0])
        except ValueError:
            return self._json(400, {"error": "n debe ser un numero"})  # hallazgo B3: antes tiraba 500
        if view == "turns":
            before = self.query.get("before", [None])[0]
            return self._json(200, transcripts.turns(s["agent"], s["transcript_path"], n, before))
        return self._json(200, transcripts.digest(s["agent"], s["transcript_path"], n))

    def do_POST(self):
        parts = self._route()
        if self._too_big():
            return
        if not self._host_ok():
            return self._json(400, {"error": "Host no valido"})
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo o el Origin no es propio"})
        try:
            if parts == ["login"]:
                return self._login()
            if parts == ["logout"]:
                auth.logout(auth.parse_cookie(self.headers.get("Cookie")))
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{auth.COOKIE}=; Path=/; Max-Age=0"})
            if parts == ["setup"]:
                return self._setup()
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["rescan"]:
                threading.Thread(target=sweep_once, daemon=True).start()
                return self._json(202, {"ok": True})
            if parts == ["rules"]:
                code, res = create_rule(self._json_body())
                return self._json(code, res)
            if len(parts) == 2 and parts[0] == "pending":
                d = self._json_body()
                if d.get("decision") not in ("allow", "deny"):
                    return self._json(400, {"error": "decision debe ser allow o deny"})
                code, res = answer_pending(parts[1], d["decision"], d.get("reason", ""), d.get("answers"))
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "sessions":
                s = self._session(parts[1])
                if s is None:
                    return None
                if parts[2] == "send":
                    return self._send(s)
                if parts[2] == "interrupt":
                    code, res = interrupt_session(s)
                    return self._json(code, res)
                if parts[2] == "dialog":
                    d = self._json_body()
                    if not isinstance(d.get("choice"), int) or isinstance(d.get("choice"), bool):
                        return self._json(400, {"error": "choice debe ser el numero de la opcion"})
                    code, res = answer_dialog(s, d["choice"])
                    return self._json(code, res)
                if parts[2] == "attach":
                    name = urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin")
                    data = self.raw
                    if not data:
                        return self._json(400, {"error": "cuerpo vacio"})
                    path = save_attachment(s["session_id"], name, data)
                    return self._json(200, {"path": path, "bytes": len(data)})
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _login(self) -> None:
        """POST /login: passphrase mas codigo TOTP a cambio de la cookie. Hacia afuera va un solo
        mensaje de error, salvo el bloqueo por intentos, que conviene que se vea."""
        d = self._json_body()
        ok, motivo, token = auth.login(
            str(d.get("passphrase", "")), str(d.get("code", "")), self._client_ip(), self.headers.get("User-Agent", "")
        )
        if not ok:
            log(f"login fallido desde {self._client_ip()}: {motivo}")
            msg = motivo if motivo.startswith("bloqueado") or "no configurado" in motivo else "codigo incorrecto"
            return self._json(401, {"ok": False, "error": msg})
        log(f"login ok desde {self._client_ip()}")
        return self._json(200, {"ok": True}, {"Set-Cookie": auth.cookie_header(token, secure=self._via_tunnel())})

    def _setup(self) -> None:
        """POST /setup: alta del acceso remoto, solo desde la propia PC y solo una vez. Deja armado
        el enlace de alta, un token de 15 min que el celular canjea una sola vez por /enroll."""
        if not self._is_local():
            return self._json(403, {"error": "el alta se hace desde la PC"})
        if auth.configured():
            return self._json(409, {"error": "ya esta configurado; borrar ~/.lienzo/auth.json para rehacerlo"})
        d = self._json_body()
        res = auth.setup(
            account=os.environ.get("USERNAME", "lienzo"), mode="full" if d.get("mode") == "full" else "code"
        )
        global enroll
        with lock:
            enroll = {
                "token": secrets.token_urlsafe(24),
                "passphrase": res["passphrase"],
                "otpauth": res["otpauth"],
                "expires": time.time() + ENROLL_S,
            }
            res["enroll_token"] = enroll["token"]
            res["enroll_expires_s"] = ENROLL_S
        log("acceso remoto configurado (passphrase + TOTP); enlace de alta valido 15 min")
        return self._json(200, res)

    def _send(self, s: dict) -> None:
        """POST /sessions/<id>/send: inyecta el texto en la consola y, solo si entro, deja la flecha
        en el historial. Quien queda de cada lado depende de como se pidio el envio."""
        d = self._json_body()
        code, res = send_to_session(s, d.get("text", ""), list(d.get("attachments") or []))
        if code == 200:
            sid, text = s["session_id"], d.get("text", "")
            src, link_to = d.get("from"), d.get("link_to")
            kind = "native" if d.get("native") else "send"
            if link_to and link_to in sessions and link_to != sid:
                # canal nativo: se le habla a A para que abra conversacion con B; la flecha es A -> B
                add_link(sid, link_to, text, kind)
            elif src and src in sessions and src != sid:
                add_link(src, sid, text, kind)
                if d.get("copycat") is True:
                    # pegar trabajo: la copia hereda el titulo; el origen se detiene salvo "Duplicar"
                    res.update(hand_over(s, sessions[src], stop=d.get("stop_origin") is not False))
            elif not src and not link_to:
                # lo que el usuario escribio desde el lienzo: queda en el historial de la sesion
                # (pestana Conexiones) como 'recibido de vos'; sin flecha
                add_link(None, sid, text, "user")
        return self._json(code, res)

    def do_PUT(self):
        parts = self._route()
        if self._too_big():
            return
        if not self._host_ok():
            return self._json(400, {"error": "Host no valido"})
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo o el Origin no es propio"})
        if not self._authed():
            return self._json(401, {"error": "hace falta iniciar sesion"})
        try:
            if parts == ["config"]:
                return self._put_config()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "title":
                return self._put_title(parts[1])
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "coordinator":
                return self._put_coordinator(parts[1])
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "stopped":
                return self._put_stopped(parts[1])
            if len(parts) == 2 and parts[0] == "rules":
                code, res = edit_rule(parts[1], self._json_body())
                return self._json(code, res)
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:
            return self._server_error(e)

    def _put_config(self) -> None:
        """PUT /config: solo las claves de UI_CONFIG_KEYS (auto_continue, auto_retry) y solo como bool; el
        resto de config.json (ejemplos, wait) es de hook.py y no se toca. Se valida todo el cuerpo
        antes de escribir nada: media tanda aplicada seria peor que ninguna."""
        d = self._json_body()
        if not d or [k for k in d if k not in UI_CONFIG_KEYS]:
            return self._json(400, {"error": f"solo se puede cambiar {', '.join(UI_CONFIG_KEYS)}"})
        for k, v in d.items():
            if not isinstance(v, bool):
                return self._json(400, {"error": f"{k} debe ser true o false"})
        for k, v in d.items():
            set_config_key(k, v)
            log(f"config: {k} = {v} (desde la UI, {self._client_ip()})")
        return self._json(200, public_config())

    def _put_title(self, sid: str) -> None:
        """PUT /sessions/<id>/title: titulo a mano. Vacio vuelve a la logica automatica."""
        title = self._json_body().get("title")
        if title is not None and not isinstance(title, str):
            return self._json(400, {"error": "title debe ser un texto"})
        s = self._session(sid)
        if s is None:
            return None
        set_title(s, title or "")  # toma el lock por dentro; leer la transcripcion, no
        with lock:
            touch(s)
        log(f"titulo de {sid[:8]} -> {s['title']!r} ({s.get('title_source')})")
        return self._json(200, {"ok": True, "title": s["title"], "title_source": s.get("title_source")})

    def _put_stopped(self, sid: str) -> None:
        """PUT /sessions/<id>/stopped: la llave. {on: true} la detiene (Esc si corre, aviso a sus
        conectadas, no recibe nada); {on: false} la habilita."""
        on = self._json_body().get("on")
        if not isinstance(on, bool):
            return self._json(400, {"error": "on debe ser true o false"})
        s = self._session(sid)
        if s is None:
            return None
        res = set_stopped(s, on)
        return self._json(200, {"ok": True, "stopped_by": s.get("stopped_by"), **res})

    def _put_coordinator(self, sid: str) -> None:
        """PUT /sessions/<id>/coordinator: marca la coordinadora del repo (a lo sumo una)."""
        on = self._json_body().get("on")
        if not isinstance(on, bool):
            return self._json(400, {"error": "on debe ser true o false"})
        s = self._session(sid)
        if s is None:
            return None
        changed = set_coordinator(s, on)
        log(
            f"coordinadora de {s.get('repo')}: {sid[:8]} -> {on} "
            f"({', '.join(x['session_id'][:8] for x in changed) or 'sin cambios'})"
        )
        return self._json(200, {"ok": True, "coordinator": bool(s.get("coordinator"))})

    def do_DELETE(self):
        parts = self._route()
        if not self._host_ok():
            return self._json(400, {"error": "Host no valido"})
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo"})
        if not self._authed():
            return self._json(401, {"error": "hace falta iniciar sesion"})
        if len(parts) == 2 and parts[0] == "sessions":
            drop_session(parts[1], "borrada desde la UI")
            return self._json(200, {"ok": True})
        if len(parts) == 2 and parts[0] in ("links", "rules"):
            log(f"{parts[0][:-1]} {parts[1]} borrada desde la UI ({self._client_ip()})")
            (links if parts[0] == "links" else rules).remove(lambda x: x["id"] == parts[1])
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "ruta desconocida"})

    def _file(self, path: str, ctype: str, cache: str = "no-store") -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            # hallazgo M3: la ruta absoluta (letra de unidad, arbol del repo) va solo al log, no al
            # cliente, que por el tunel podria ser un anonimo. Mismo criterio que _server_error.
            log(f"404 estatico: {path}")
            return self._json(404, {"error": "no encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _sse(self) -> None:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with lock:
            clients.append(q)
            # serializar aca adentro: `sessions.values()` son los dicts vivos, y armar el JSON
            # afuera podia leer una tarjeta a medio escribir (o reventar si el dict cambia de tamaño)
            snapshot = json.dumps(
                {
                    "type": "snapshot",
                    "sessions": list(sessions.values()),
                    "pending": public_pending(),
                    "links": links.snapshot(),
                    "rules": rules.snapshot(),
                    "build": build_id(),
                },
                ensure_ascii=False,
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        # chunked explicito: sin esto, cloudflared (y cualquier proxy HTTP/1.1) no sabe donde
        # termina la respuesta y la retiene entera; el navegador directo la toleraba igual
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(payload: bytes) -> None:
            self.wfile.write(f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n")
            self.wfile.flush()

        try:
            chunk(f"data: {snapshot}\n\n".encode())
            while True:
                try:
                    data = q.get(timeout=15)
                    chunk(f"data: {data}\n\n".encode())
                except queue.Empty:
                    # evento real, no comentario: el navegador lo cuenta como "el stream sigue
                    # vivo". Lleva el sello del build (ver `build_id`) para avisar de una version
                    # nueva sin agregar ni una ruta ni un timer
                    chunk(f'data: {{"type": "ping", "build": "{build_id()}"}}\n\n'.encode())
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)


def build_id() -> str:
    """Sello del bundle que hay en web/dist. Viaja en cada latido del SSE para que un tablero
    abierto se entere de que hay una version nueva: el lienzo es una pagina sola y no se recarga
    sola, asi que despues de un `npm run build` seguia corriendo el bundle viejo y los cambios
    parecian no haberse aplicado. Vite reescribe index.html en cada build, asi que su mtime y su
    tamano alcanzan; sin build todavia, cadena vacia y el front no hace nada."""
    try:
        st = os.stat(os.path.join(DIST, "index.html"))
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return ""


def tunnel_loop(port: int) -> None:
    """Camino A (§7.6.2): cloudflared publica 127.0.0.1:<port> en una URL https de trycloudflare.
    Solo se levanta si hay login configurado; sin auth.json no se expone nada."""
    global remote_url
    if not os.path.exists(CLOUDFLARED):
        log(f"--remote: no encuentro {CLOUDFLARED} (winget install Cloudflare.cloudflared)")
        return
    if not auth.configured():
        log("--remote: esperando el alta del acceso (boton 'Acceso remoto' en la UI) para levantar el tunel")
        while not auth.configured():
            time.sleep(3)
    while True:
        remote_url = None
        try:
            # --protocol http2: con QUIC el SSE (/events) llegaba con cabeceras pero sin cuerpo
            p = subprocess.Popen(
                [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate", "--protocol", "http2"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000,
            )  # CREATE_NO_WINDOW
        except OSError as e:
            log(f"--remote: cloudflared no arranca: {e}")
            return
        for line in p.stderr or []:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and remote_url != m.group(0):
                remote_url = m.group(0)
                log(f"tunel: {remote_url}")
            elif any(k in line for k in ("ERR", "error", "Registered", "Connection")):
                log(f"cloudflared: {line.strip()[:200]}")
        p.wait()
        log(f"cloudflared termino (codigo {p.returncode}); reintento en 10 s")
        time.sleep(10)


def main() -> int:
    ap = argparse.ArgumentParser(prog="lienzo-server")
    ap.add_argument("--port", type=int, default=7321)
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--sweep-every", type=float, default=30.0)
    ap.add_argument("--remote", action="store_true", help="publicar por cloudflared (exige login configurado)")
    a = ap.parse_args()
    for d in (EVENTS, PENDING, ANSWERS, ADJUNTOS, SESSIONS):
        os.makedirs(d, exist_ok=True)
    purged, retitled = load_sessions()
    links.load(lambda l: l.get("to") in sessions and (not l.get("from") or l["from"] in sessions))
    rules.load(lambda r: r.get("to") in sessions and (not r.get("from") or r["from"] in sessions))
    purge_stale_at_rules()
    clean_attachments()
    if not a.no_sweep:
        sweep_once()
    threading.Thread(target=consume_events, daemon=True).start()
    threading.Thread(target=scan_pending, daemon=True).start()
    threading.Thread(target=liveness_loop, args=(0 if a.no_sweep else a.sweep_every,), daemon=True).start()
    threading.Thread(target=screen_loop, daemon=True).start()
    threading.Thread(target=rules_loop, daemon=True).start()
    if a.remote:
        threading.Thread(target=tunnel_loop, args=(a.port,), daemon=True).start()
    srv = QuietServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    with lock:
        n_alive = sum(1 for s in sessions.values() if s.get("alive"))
        n_rules = sum(1 for r in rules.items if r.get("enabled"))
        n_links = len(links.items)
    log(
        f"lienzo-server en http://127.0.0.1:{a.port}  sesiones={len(sessions)} (vivas={n_alive}, purgadas={purged}"
        f" de mas de {STALE_SESSION_H} h, retituladas={retitled})  reglas_activas={n_rules}  links={n_links}"
        f"  login={'si' if auth.configured() else 'no'}"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
