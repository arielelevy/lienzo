"""Nivel 3 para el bot de ChatGPT: un server aparte, sólo GET y con clave, que es lo único que se expone por
el túnel. El server del lienzo (7321) no sale nunca: tiene rutas que escriben y manejan sesiones. Las
Actions de un GPT las llaman los servers de OpenAI, no esta PC: por eso hace falta URL pública y clave.

Configuración en `<LIENZO_HOME>/bot-externo.json` (fuera del repo), creada en el primer arranque:
  clave      Bearer que se carga en la Action del GPT.
  url        URL pública del túnel; va como `servers` del OpenAPI.
  proyectos  lista de proyectos que pueden salir; null = todos.

Uso: python lienzo/bot_externo.py [--puerto 7330]"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conocimiento as k
import registro_niveles
import state

PUERTO = 7330


def config_path() -> str:
    return os.path.join(os.environ.get("LIENZO_HOME") or state.LIENZO, "bot-externo.json")


def config() -> dict:
    """La config, creándola con una clave nueva si no existe."""
    path = config_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    datos = {"clave": secrets.token_urlsafe(32), "url": "https://CAMBIAR", "proyectos": None}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(datos, f, indent=2)
    return datos


def _permitido(cfg: dict, pid: str) -> bool:
    lista = cfg.get("proyectos")
    return lista is None or pid in lista


def openapi(url: str) -> dict:
    texto = {"type": "string"}
    item = {
        "type": "object",
        "properties": {
            "tipo": texto,
            "texto": texto,
            "estado": texto,
            "fecha": texto,
            "temas": {"type": "array", "items": texto},
        },
    }
    pid = {"name": "proyecto", "in": "path", "required": True, "schema": texto}
    limite = {"name": "limite", "in": "query", "required": False, "schema": {"type": "integer", "maximum": 30}}

    def ok(props: dict) -> dict:
        return {
            "200": {
                "description": "ok",
                "content": {"application/json": {"schema": {"type": "object", "properties": props}}},
            }
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Lienzo, memoria de proyectos",
            "version": "1",
            "description": "Qué pasó en los proyectos de Ariel: temas, decisiones, hallazgos y preguntas abiertas. Sólo lectura.",
        },
        "servers": [{"url": url}],
        "paths": {
            "/proyectos": {
                "get": {
                    "operationId": "listarProyectos",
                    "summary": "Proyectos con actividad y cuánto tiene cada uno. Empezar por acá para saber qué proyectos hay.",
                    "responses": ok({"proyectos": {"type": "array", "items": {"type": "object"}}}),
                }
            },
            "/proyectos/{proyecto}": {
                "get": {
                    "operationId": "verProyecto",
                    "summary": "Qué se hizo día por día (que_se_hizo), temas, decisiones vigentes y propuestas, hallazgos y preguntas abiertas de un proyecto, lo más reciente primero.",
                    "parameters": [pid, limite],
                    "responses": ok(
                        {
                            "que_se_hizo": {"type": "array", "items": {"type": "object"}},
                            "temas": {"type": "array", "items": {"type": "object"}},
                            "decisiones": {"type": "array", "items": item},
                            "hallazgos": {"type": "array", "items": item},
                            "preguntas": {"type": "array", "items": item},
                        }
                    ),
                }
            },
            "/proyectos/{proyecto}/buscar": {
                "get": {
                    "operationId": "buscarEnProyecto",
                    "summary": "Busca por palabras (sin acentos, prefijo con *) en resúmenes diarios, temas, decisiones, hallazgos y preguntas del proyecto.",
                    "parameters": [pid, {"name": "q", "in": "query", "required": True, "schema": texto}, limite],
                    "responses": ok({"resultados": {"type": "array", "items": item}}),
                }
            },
        },
        "components": {"securitySchemes": {"clave": {"type": "http", "scheme": "bearer"}}},
        "security": [{"clave": []}],
    }


def responder(cfg: dict, metodo: str, ruta: str, autorizacion: str | None) -> tuple[int, dict]:
    """(código, cuerpo) de un pedido. Aparte del handler para probarlo sin sockets."""
    if metodo != "GET":
        return 405, {"error": "sólo lectura"}
    url = urllib.parse.urlsplit(ruta)
    partes = [urllib.parse.unquote(p) for p in url.path.strip("/").split("/") if p]
    query = {a: b[0] for a, b in urllib.parse.parse_qs(url.query).items()}
    if partes == ["openapi.json"]:
        return 200, openapi(cfg["url"])
    esperado = "Bearer " + cfg["clave"]
    if not autorizacion or not hmac.compare_digest(autorizacion.encode(), esperado.encode()):
        return 401, {"error": "falta la clave"}
    try:
        limite = int(query.get("limite") or 30)
    except ValueError:
        return 400, {"error": "limite debe ser un entero"}
    try:
        if partes == ["proyectos"]:
            indice = registro_niveles.externo_indice()
            indice["proyectos"] = [p for p in indice["proyectos"] if _permitido(cfg, p["proyecto"])]
            return 200, indice
        if len(partes) in (2, 3) and partes[0] == "proyectos":
            pid = partes[1]
            if not _permitido(cfg, pid):
                return 404, {"error": f"proyecto desconocido: {pid}"}
            if len(partes) == 2:
                return 200, registro_niveles.externo_detalle(pid, limite=limite)
            if partes[2] == "buscar":
                return 200, registro_niveles.externo_buscar(pid, query.get("q", ""), limite=limite)
    except k.Rechazo as e:
        return e.codigo, {"error": str(e)}
    return 404, {"error": "ruta desconocida"}


class Handler(BaseHTTPRequestHandler):
    cfg: ClassVar[dict] = {}

    def _responder(self) -> None:
        code, cuerpo = responder(self.cfg, self.command, self.path, self.headers.get("Authorization"))
        data = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        state.log(f"bot-externo {self.command} {urllib.parse.urlsplit(self.path).path} -> {code}")

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _responder

    def log_message(self, *args) -> None:  # al log del lienzo, sin la query
        pass


def arrancar(log, *, puerto: int = PUERTO, reintento_s: float = 60) -> threading.Thread | None:
    """Desde el server del lienzo: sólo en la PC que tiene `bot-externo.json` (no crea la clave en las
    demás). Si el puerto está ocupado (otra copia corriendo) reintenta hasta poder ligarlo."""
    if not os.path.isfile(config_path()):
        return None

    def bucle() -> None:
        avisado = False
        while True:
            try:
                Handler.cfg = config()
                server = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
            except (OSError, ValueError) as error:
                if not avisado:
                    log(f"bot-externo: no arranca en {puerto} ({type(error).__name__}: {error}); reintento")
                    avisado = True
                time.sleep(reintento_s)
                continue
            server.daemon_threads = True
            log(f"bot-externo en http://127.0.0.1:{puerto}")
            server.serve_forever()
            return

    hilo = threading.Thread(target=bucle, name="bot-externo", daemon=True)
    hilo.start()
    return hilo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--puerto", type=int, default=PUERTO)
    args = ap.parse_args()
    Handler.cfg = config()
    server = ThreadingHTTPServer(("127.0.0.1", args.puerto), Handler)  # sólo loopback: lo saca el túnel
    print(f"bot-externo en http://127.0.0.1:{args.puerto} · config {config_path()}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
