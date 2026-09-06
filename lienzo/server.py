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
import auth  # noqa: E402
import transcripts  # noqa: E402
from rules import connections_of, purge_stale_at_rules, rules_loop  # noqa: E402
from sessions import (add_link, answer_pending, clean_attachments, consume_events, drop_session, liveness_loop,  # noqa: E402
                      load_sessions, public_pending, read_screen, save_attachment, scan_pending, screen_loop,
                      send_to_session, set_coordinator, set_title, sweep_once, touch)
from state import (ADJUNTOS, ANSWERS, DIST, EVENTS, MIME, PENDING, SESSIONS, STALE_SESSION_H, UI_CONFIG_KEYS, clients,  # noqa: E402
                   is_disconnect, links, lock, log, now, pending, public_config, rules, sessions, set_config_key, short)

CLOUDFLARED = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared", "cloudflared.exe")
remote_url: str | None = None
# alta desde el celular con un solo QR: token de 15 min que entrega passphrase + otpauth una vez
enroll: dict | None = None
ENROLL_S = 15 * 60

# --- HTTP ------------------------------------------------------------------------------

def at_fields(d: dict, current: dict | None = None) -> tuple[dict | None, str | None]:
    """Campos de repeticion de una regla 'at' (POST o PUT): every_s (entero >= 60, o None = un solo
    disparo), max_fires (1..50; 5 por defecto si es periodica), skip_busy (True por defecto si es
    periodica). `current` es la regla que se edita (PUT), para no pisar lo que no vino. Devuelve
    (campos, error)."""
    cur = current or {}
    every = cur.get("every_s")
    if "every_s" in d:
        v = d["every_s"]
        if v is None:
            every = None
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                return None, "every_s debe ser un entero en segundos"
            try:
                f = float(v)
            except ValueError:
                return None, "every_s debe ser un entero en segundos"
            if f != int(f):
                return None, "every_s debe ser un entero en segundos"
            every = int(f)
            if every < 60:
                return None, "every_s debe ser al menos 60 segundos"
    max_fires = cur.get("max_fires")
    if d.get("max_fires") is not None:
        try:
            max_fires = max(1, min(int(d["max_fires"]), 50))
        except (TypeError, ValueError):
            return None, "max_fires debe ser un numero"
    elif every and (max_fires or 1) <= 1:
        max_fires = 5          # pasa a periodica sin tope explicito: 5 disparos
    skip_busy = cur.get("skip_busy")
    if "skip_busy" in d:
        skip_busy = bool(d["skip_busy"])
    elif skip_busy is None:
        skip_busy = bool(every)
    return {"every_s": every, "max_fires": int(max_fires or 1), "skip_busy": bool(skip_busy),
            "repeat": bool(every)}, None


AT_CLASH_S = 120   # dos programadas a la misma consola a menos de 2 min se pisan (misma tolerancia que ensure_continue_rule)


def create_rule(d: dict) -> tuple[int, dict]:
    """POST /rules: valida y crea una regla on_stop o at. Devuelve (codigo, cuerpo)."""
    kind = d.get("kind")
    if kind not in ("on_stop", "at"):
        return 400, {"error": "kind debe ser on_stop o at"}
    if d.get("to") not in sessions:
        return 404, {"error": "sesion destino desconocida"}
    if kind == "on_stop" and d.get("from") not in sessions:
        return 404, {"error": "sesion origen desconocida"}
    text = str(d.get("text") or "")
    if kind == "on_stop":
        with lock:
            inverse = next((r for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop"
                            and r.get("from") == d["to"] and r.get("to") == d["from"]), None)
            dup = next((r for r in rules.items if r.get("enabled") and r.get("kind") == "on_stop"
                        and r.get("to") == d["to"] and (r.get("from") or None) == (d.get("from") or None)
                        and (r.get("text") or "").strip() == text.strip()), None)
        if inverse:
            return 409, {"error": f"crearía un bucle {d['from'][:8]}↔{d['to'][:8]}: "
                                  f"ya existe la regla {inverse['id']} en sentido inverso"}
        if dup:
            return 409, {"error": "ya existe esa conexión", "rule_id": dup["id"]}
        rule = {"id": secrets.token_hex(6), "kind": kind, "from": d.get("from") or None, "to": d["to"],
                "text": text, "at": None, "repeat": bool(d.get("repeat")),
                "max_fires": max(1, min(int(d.get("max_fires") or 1), 50)),
                "fired": 0, "enabled": True, "created": now()}
        rules.add(rule, cap=500)
        log(f"regla nueva {rule['id']}: {kind} -> {rule['to'][:8]}")
        return 200, rule
    try:
        # siempre en hora local: naive se asume local, aware (la UI manda UTC con Z) se convierte,
        # asi todas las reglas guardan `at` con el mismo offset
        at = dt.datetime.fromisoformat(str(d.get("at"))).astimezone()
    except ValueError:
        return 400, {"error": "at debe ser una fecha ISO"}
    extra, err = at_fields(d)
    if err:
        return 400, {"error": err}

    def clashes(r: dict) -> bool:
        if not r.get("enabled") or r.get("kind") != "at" or r.get("to") != d["to"]:
            return False
        try:
            return abs((dt.datetime.fromisoformat(str(r.get("at"))) - at).total_seconds()) <= AT_CLASH_S
        except ValueError:
            return False

    # dos programadas a la misma consola en el mismo minuto se inyectan juntas ("Continuar" y
    # "continua" a las 01:01): choca cualquier `at` habilitada a +-2 min, periodica o no, sea cual
    # sea el texto; con "replace": true la nueva reemplaza a la existente
    with lock:
        clash = next((r for r in rules.items if clashes(r)), None)
    if clash:
        if d.get("replace") is not True:
            hhmm = dt.datetime.fromisoformat(clash["at"]).astimezone().strftime("%H:%M")
            return 409, {"error": f"ya hay una programada a las {hhmm} para esa sesión", "rule_id": clash["id"],
                         "at": clash["at"], "text": clash.get("text") or "", "replace": True}
        rules.remove(lambda r: r["id"] == clash["id"])
        log(f"regla {clash['id']} ({clash.get('at')} {short(clash.get('text') or '', 40)!r}) reemplazada por una nueva a la misma hora")
    rule = {"id": secrets.token_hex(6), "kind": kind, "from": d.get("from") or None, "to": d["to"],
            "text": text, "at": at.isoformat(timespec="seconds"), "fired": 0, "enabled": True, "created": now()}
    rule.update(extra)   # every_s, max_fires, skip_busy, repeat=bool(every_s)
    rules.add(rule, cap=500)
    cada = f" cada {rule['every_s']} s x{rule['max_fires']}" if rule.get("every_s") else ""
    log(f"regla nueva {rule['id']}: {kind} -> {rule['to'][:8]} {rule['at']}{cada}")
    return 200, rule


class QuietServer(ThreadingHTTPServer):
    """socketserver imprime un traceback entero en stderr cada vez que el navegador cierra una
    conexion keep-alive mientras se lee la proxima peticion (WinError 10053). Eso no es un error
    nuestro: se calla. Cualquier otra excepcion va al log propio, en una linea en consola."""

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if e is not None and is_disconnect(e):
            return
        log(traceback.format_exc())


class Handler(BaseHTTPRequestHandler):
    server_version = "lienzo/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencio; el log propio alcanza
        pass

    def _json(self, code: int, obj, extra_headers: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        """JSON del cuerpo tolerante a clientes que mandan latin-1 (un curl desde Git Bash)."""
        raw = self._body()
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
        entra por cloudflared trae CF-Connecting-IP y exige la cookie (passphrase + TOTP)."""
        if self._is_local() or not auth.configured():
            return True
        return auth.check(auth.parse_cookie(self.headers.get("Cookie")))

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Lienzo") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        ohost = origin.split("//", 1)[-1]
        host = self.headers.get("Host") or ""
        # el propio host, o el dev server de Vite en la misma maquina (localhost:5173)
        return ohost == host or ohost.split(":")[0] in ("localhost", "127.0.0.1")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = urllib.parse.parse_qs(u.query)
        try:
            if not parts:
                index = os.path.join(DIST, "index.html")
                if not os.path.exists(index):
                    return self._json(503, {"error": "falta el build de la UI: cd web && npm install && npm run build"})
                return self._file(index, "text/html; charset=utf-8")
            if parts[0] == "assets" and len(parts) == 2 and os.path.isdir(DIST):
                # estaticos del build de Vite; sin ".." posibles porque parts viene partido por "/"
                name = parts[1]
                if "\\" in name or name.startswith("."):
                    return self._json(404, {"error": "ruta invalida"})
                path = os.path.join(DIST, "assets", name)
                return self._file(path, MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
                                  cache="public, max-age=31536000, immutable")
            if parts == ["health"]:
                return self._json(200, {"ok": True, "sessions": len(sessions), "pending": len(pending), "ts": now()})
            if parts == ["auth"]:
                return self._json(200, {"configured": auth.configured(), "authenticated": self._authed(),
                                        "local": self._is_local(), "remote_url": remote_url, "mode": auth.mode()})
            if parts == ["totp"]:
                # volver a ver el QR de Authenticator (segundo telefono, o alta interrumpida): solo local
                if not self._is_local():
                    return self._json(403, {"error": "solo desde la PC"})
                cur = auth.current_otpauth(os.environ.get("USERNAME", "lienzo"))
                return self._json(200, cur) if cur else self._json(404, {"error": "sin acceso configurado"})
            if parts == ["enroll"]:
                # el token del QR es la credencial; vale 15 min desde el alta y se apaga solo
                global enroll
                tok = q.get("token", [""])[0]
                with lock:
                    e = enroll
                    if e and time.time() > e["expires"]:
                        enroll = e = None
                if not e or not tok or not secrets.compare_digest(tok, e["token"]):
                    log(f"enroll rechazado desde {self._client_ip()}")
                    return self._json(410, {"error": "el enlace de alta vencio o no es valido; rehacer desde la PC"})
                log(f"enroll entregado a {self._client_ip()}")
                return self._json(200, {"passphrase": e["passphrase"], "otpauth": e["otpauth"],
                                        "expires_in": int(e["expires"] - time.time())})
            if not self._authed():
                return self._json(401, {"error": "hace falta iniciar sesion"})
            if parts == ["sessions"]:
                with lock:
                    return self._json(200, sorted(sessions.values(), key=lambda s: (s["repo"], s["started"])))
            if parts == ["pending"]:
                return self._json(200, public_pending())
            if parts == ["links"]:
                return self._json(200, links.snapshot())
            if parts == ["rules"]:
                return self._json(200, rules.snapshot())
            if parts == ["config"]:
                return self._json(200, public_config())
            if parts == ["events"]:
                return self._sse()
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "screen":
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if not s.get("pid") or s.get("orphan"):
                    return self._json(409, {"ok": False, "error": "sin consola que leer"})
                return self._json(200, read_screen(s["pid"]))
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "connections":
                with lock:
                    known = parts[1] in sessions
                if not known:
                    return self._json(404, {"error": "sesion desconocida"})
                return self._json(200, connections_of(parts[1]))
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] in ("turns", "digest"):
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if not s.get("transcript_path") or not os.path.exists(s["transcript_path"]):
                    return self._json(200, {"meta": {}, "turns": [], "has_more": False, "note": "sin transcripcion"})
                n = int(q.get("n", ["10"])[0])
                before = q.get("before", [None])[0]
                if parts[2] == "turns":
                    return self._json(200, transcripts.turns(s["agent"], s["transcript_path"], n, before))
                return self._json(200, transcripts.digest(s["agent"], s["transcript_path"], n))
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:  # noqa: BLE001
            if is_disconnect(e):
                return   # el navegador cerro la conexion a mitad de la respuesta: no hay a quien contestar
            log(traceback.format_exc())
            return self._json(500, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo o el Origin no es propio"})
        try:
            if parts == ["login"]:
                d = self._json_body()
                ok, motivo, token = auth.login(str(d.get("passphrase", "")), str(d.get("code", "")),
                                               self._client_ip(), self.headers.get("User-Agent", ""))
                if not ok:
                    log(f"login fallido desde {self._client_ip()}: {motivo}")
                    # hacia afuera un solo mensaje, salvo el bloqueo, que conviene que se vea
                    msg = motivo if motivo.startswith("bloqueado") or "no configurado" in motivo else "codigo incorrecto"
                    return self._json(401, {"ok": False, "error": msg})
                log(f"login ok desde {self._client_ip()}")
                return self._json(200, {"ok": True}, {"Set-Cookie": auth.cookie_header(token, secure=self._via_tunnel())})
            if parts == ["logout"]:
                auth.logout(auth.parse_cookie(self.headers.get("Cookie")))
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{auth.COOKIE}=; Path=/; Max-Age=0"})
            if parts == ["setup"]:
                # alta del acceso remoto: solo desde la propia PC y solo una vez
                if not self._is_local():
                    return self._json(403, {"error": "el alta se hace desde la PC"})
                if auth.configured():
                    return self._json(409, {"error": "ya esta configurado; borrar ~/.lienzo/auth.json para rehacerlo"})
                d = self._json_body()
                res = auth.setup(account=os.environ.get("USERNAME", "lienzo"),
                                 mode="full" if d.get("mode") == "full" else "code")
                global enroll
                with lock:
                    enroll = {"token": secrets.token_urlsafe(24), "passphrase": res["passphrase"],
                              "otpauth": res["otpauth"], "expires": time.time() + ENROLL_S}
                    res["enroll_token"] = enroll["token"]
                    res["enroll_expires_s"] = ENROLL_S
                log("acceso remoto configurado (passphrase + TOTP); enlace de alta valido 15 min")
                return self._json(200, res)
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
                code, res = answer_pending(parts[1], d["decision"], d.get("reason", ""))
                return self._json(code, res)
            if len(parts) == 3 and parts[0] == "sessions":
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                if parts[2] == "send":
                    d = self._json_body()
                    code, res = send_to_session(s, d.get("text", ""), list(d.get("attachments") or []))
                    src, link_to = d.get("from"), d.get("link_to")
                    kind = "native" if d.get("native") else "send"
                    if code == 200 and link_to and link_to in sessions and link_to != s["session_id"]:
                        # canal nativo: se le habla a A para que abra conversacion con B; la flecha es A -> B
                        add_link(s["session_id"], link_to, d.get("text", ""), kind)
                    elif code == 200 and src and src in sessions and src != s["session_id"]:
                        add_link(src, s["session_id"], d.get("text", ""), kind)
                    elif code == 200 and not src and not link_to:
                        # lo que el usuario escribio desde el lienzo: queda en el historial de la
                        # sesion (pestana Conexiones) como 'recibido de vos'; sin flecha
                        add_link(None, s["session_id"], d.get("text", ""), "user")
                    return self._json(code, res)
                if parts[2] == "attach":
                    name = urllib.parse.unquote(self.headers.get("X-Filename") or "adjunto.bin")
                    data = self._body()
                    if not data:
                        return self._json(400, {"error": "cuerpo vacio"})
                    path = save_attachment(s["session_id"], name, data)
                    return self._json(200, {"path": path, "bytes": len(data)})
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:  # noqa: BLE001
            if is_disconnect(e):
                return   # el navegador cerro la conexion a mitad de la respuesta: no hay a quien contestar
            log(traceback.format_exc())
            return self._json(500, {"error": str(e)})

    def do_PUT(self):
        parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p]
        if not self._csrf_ok():
            return self._json(403, {"error": "falta X-Lienzo o el Origin no es propio"})
        if not self._authed():
            return self._json(401, {"error": "hace falta iniciar sesion"})
        try:
            if parts == ["config"]:
                # solo auto_continue, y solo como bool; el resto de config.json (ejemplos, wait) no se toca
                d = self._json_body()
                unknown = [k for k in d if k not in UI_CONFIG_KEYS]
                if unknown or not d:
                    return self._json(400, {"error": f"solo se puede cambiar {', '.join(UI_CONFIG_KEYS)}"})
                for k, v in d.items():
                    if not isinstance(v, bool):
                        return self._json(400, {"error": f"{k} debe ser true o false"})
                for k, v in d.items():
                    set_config_key(k, v)
                    log(f"config: {k} = {v} (desde la UI, {self._client_ip()})")
                return self._json(200, public_config())
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "title":
                d = self._json_body()
                title = d.get("title")
                if title is not None and not isinstance(title, str):
                    return self._json(400, {"error": "title debe ser un texto"})
                with lock:
                    s = sessions.get(parts[1])
                    if s is None:
                        return self._json(404, {"error": "sesion desconocida"})
                    set_title(s, title or "")
                    touch(s)
                log(f"titulo de {parts[1][:8]} -> {s['title']!r} ({s.get('title_source')})")
                return self._json(200, {"ok": True, "title": s["title"], "title_source": s.get("title_source")})
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "coordinator":
                d = self._json_body()
                if not isinstance(d.get("on"), bool):
                    return self._json(400, {"error": "on debe ser true o false"})
                with lock:
                    s = sessions.get(parts[1])
                if s is None:
                    return self._json(404, {"error": "sesion desconocida"})
                changed = set_coordinator(s, d["on"])
                log(f"coordinadora de {s.get('repo')}: {parts[1][:8]} -> {d['on']} "
                    f"({', '.join(x['session_id'][:8] for x in changed) or 'sin cambios'})")
                return self._json(200, {"ok": True, "coordinator": bool(s.get("coordinator"))})
            if len(parts) == 2 and parts[0] == "rules":
                # editar una conexion pendiente (doble click en la flecha): texto, hora, repeticion.
                # Una programada que ya disparo se puede reprogramar: vuelve a quedar vigente.
                d = self._json_body()
                at = None
                if d.get("at") is not None:
                    try:
                        at = dt.datetime.fromisoformat(str(d["at"]))
                        # siempre en hora local: naive se asume local, aware (la UI manda UTC con Z)
                        # se convierte, asi todas las reglas guardan `at` con el mismo offset
                        at = at.astimezone()
                    except ValueError:
                        return self._json(400, {"error": "at debe ser una fecha ISO"})
                if "text" in d and not isinstance(d["text"], str):
                    return self._json(400, {"error": "text debe ser un texto"})
                try:
                    max_fires = max(1, min(int(d["max_fires"]), 50)) if d.get("max_fires") is not None else None
                except (TypeError, ValueError):
                    return self._json(400, {"error": "max_fires debe ser un numero"})
                with lock:
                    r = next((x for x in rules.items if x["id"] == parts[1]), None)
                    if r is None:
                        return self._json(404, {"error": "conexion desconocida"})
                    if r.get("kind") == "at":
                        extra, err = at_fields(d, r)
                        if err:
                            return self._json(400, {"error": err})
                    if "text" in d:
                        r["text"] = d["text"]
                    if r.get("kind") == "at":
                        r.update(extra)   # every_s (null = un disparo), max_fires, skip_busy, repeat
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
                return self._json(200, r)
            return self._json(404, {"error": "ruta desconocida"})
        except Exception as e:  # noqa: BLE001
            if is_disconnect(e):
                return   # el navegador cerro la conexion a mitad de la respuesta: no hay a quien contestar
            log(traceback.format_exc())
            return self._json(500, {"error": str(e)})

    def do_DELETE(self):
        parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p]
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
            return self._json(404, {"error": f"no encuentro {path}"})
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
            snapshot = {"type": "snapshot", "sessions": list(sessions.values()), "pending": public_pending(),
                        "links": links.snapshot(), "rules": rules.snapshot()}
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
            chunk(f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n".encode("utf-8"))
            while True:
                try:
                    data = q.get(timeout=15)
                    chunk(f"data: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    # evento real, no comentario: el navegador lo cuenta como "el stream sigue vivo"
                    chunk(b'data: {"type": "ping"}\n\n')
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)

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
            p = subprocess.Popen([CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate",
                                  "--protocol", "http2"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", creationflags=0x08000000)  # CREATE_NO_WINDOW
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
    log(f"lienzo-server en http://127.0.0.1:{a.port}  sesiones={len(sessions)} (vivas={n_alive}, purgadas={purged}"
        f" de mas de {STALE_SESSION_H} h, retituladas={retitled})  reglas_activas={n_rules}  links={n_links}"
        f"  login={'si' if auth.configured() else 'no'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
