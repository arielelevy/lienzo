"""Caso memoria-e2e (pruebas agenticas, ronda 3 de la memoria): un server real en un puerto aparte, con
LIENZO_HOME propio y sin barrido. Los eventos de hook se escriben en <home>/events como los escribe
lienzo/hook.py; lo demas, por HTTP. Oraculo: el anexo A de v5 (pedido de Ariel del 2026-10-09).
Deja la evidencia en resultados/memoria-e2e.json y sale con 1 si algun paso falla. Nunca toca
~/.lienzo ni el server de 7321."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUERTO = 7391
HOME = tempfile.mkdtemp(prefix="lienzo-explorer-")
BASE = f"http://127.0.0.1:{PUERTO}"
SID = "e0e0e0e0-0000-4000-8000-000000000301"
CWD = RAIZ  # fuera de la temporal: la captura excluye carpetas temporales
evidencia = {"home": HOME, "pasos": []}


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo, ensure_ascii=False).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("X-Lienzo", "1")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def paso(nombre, ok, **datos):
    evidencia["pasos"].append({"paso": nombre, "ok": bool(ok), **datos})
    print(("OK  " if ok else "MAL ") + nombre, flush=True)


def evento(nombre, **campos):
    ev = {"hook_event_name": nombre, "session_id": SID, "agent": "claude", "cwd": CWD, **campos}
    d = os.path.join(HOME, "events")
    os.makedirs(d, exist_ok=True)
    n = f"{time.time_ns()}-{nombre}.json"
    with open(os.path.join(d, n + ".tmp"), "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False)
    os.replace(os.path.join(d, n + ".tmp"), os.path.join(d, n))


def esperar(cond, segundos=20):
    fin = time.time() + segundos
    while time.time() < fin:
        r = cond()
        if r:
            return r
        time.sleep(0.5)
    return None


env = {**os.environ, "LIENZO_HOME": HOME, "PYTHONIOENCODING": "utf-8"}
srv = subprocess.Popen(
    [
        sys.executable,
        os.path.join(RAIZ, "lienzo", "server.py"),
        "--port",
        str(PUERTO),
        "--no-sweep",
        "--peer-port",
        "7392",
    ],
    cwd=RAIZ,
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def _ok_health():
    try:
        return pedir("GET", "/health")[0] == 200
    except OSError:
        return False


try:
    paso("server real arriba en 7391 con LIENZO_HOME temporal", esperar(_ok_health, 30))
    # 1. una sesion pasa por el lienzo: proyecto y sesion solos, sin registrar nada
    evento("SessionStart")
    evento("UserPromptSubmit", prompt="medí la cola de captura con ghp_" + "x" * 36, prompt_id="p-301")
    cuerpo = (
        "Listo, la cola anda.\n```conocimiento\n"
        '{"version": 1, "nodos": [{"id": "h1", "tipo": "hallazgo", "texto": "la cola de captura no bloquea",'
        ' "datos": {"donde": "lienzo/captura.py:1", "gravedad": "baja"}}, {"id": "t1", "tipo": "tema",'
        ' "texto": "captura", "datos": {}}], "vinculos": [{"de": "h1", "relacion": "sobre", "a": "t1"}]}\n```'
    )
    evento("Stop", last_assistant_message=cuerpo, stop_reason="end_turn")
    pid = esperar(lambda: pedir("GET", "/conocimiento/carpeta?cwd=" + urllib.request.quote(CWD))[1].get("proyecto"))
    paso("el proyecto de la carpeta se creo solo", pid, proyecto=pid)

    def _dos_capturas():
        r = pedir("GET", f"/conocimiento/{pid}/capturas")[1]
        return r if r and r.get("total", 0) >= 2 else None

    caps = esperar(_dos_capturas) or {"capturas": []}
    clases = sorted(c["clase"] for c in caps["capturas"])
    paso(
        "pedido y respuesta capturados como observado",
        clases == ["pedido", "respuesta"] and all(c["estado"] == "observado" for c in caps["capturas"]),
        clases=clases,
    )
    pedido = next((c for c in caps["capturas"] if c["clase"] == "pedido"), {})
    paso(
        "el token del pedido quedo tapado",
        "ghp_" not in pedido.get("texto", "") and pedido.get("redactado") == 1,
        texto=pedido.get("texto"),
    )
    inf = esperar(lambda: pedir("GET", f"/conocimiento/{pid}/nodos?tipo=informe")[1].get("nodos"))
    hall = pedir("GET", f"/conocimiento/{pid}/nodos?tipo=hallazgo")[1].get("nodos") or []
    paso(
        "la respuesta con bloque es un informe y su hallazgo nace propuesto",
        bool(inf) and [h["estado"] for h in hall] == ["propuesto"],
        informes=len(inf or []),
    )
    # 2. texto roto se rechaza con posicion
    code, res = pedir(
        "POST", f"/conocimiento/{pid}/nodos", {"tipo": "tema", "texto": "revisi�n", "datos": {}, "autor": "x"}
    )
    paso(
        "POST /nodos rechaza U+FFFD con posicion",
        code == 400 and "columna" in res.get("error", ""),
        error=res.get("error"),
    )
    # 3. prosa opt-in
    sin = pedir("GET", f"/conocimiento/{pid}/preguntar?q=cola")[1]
    con = pedir("GET", f"/conocimiento/{pid}/preguntar?q=cola&prosa=1")[1]
    paso(
        "preguntar sin prosa no trae prosa; con prosa=1 la trae marcada",
        "prosa" not in sin and con.get("prosa") and all(p["marca"] == "prosa, no declarado" for p in con["prosa"]),
        prosa=len(con.get("prosa") or []),
    )
    # 4. consultas del plan v5 por HTTP
    b = pedir("GET", f"/conocimiento/{pid}/briefing?markdown=1&q=cola")[1]
    paso("briefing en Markdown", isinstance(b.get("markdown"), str) and "nodo:" in b["markdown"])
    paso("estado de replica sin pares", pedir("GET", f"/conocimiento/{pid}/replica")[0] == 200)
    code, rep = pedir("POST", "/conocimiento/replicar", {})
    paso("replicar sin pares no falla", code == 200 and rep == [], respuesta=rep)
    code, roto = pedir("GET", f"/conocimiento/{pid}/texto/roto")
    paso("texto roto medido en la base nueva: nada", code == 200 and not roto["nodos_rotos"], medida=roto)
    code, resp = pedir("POST", f"/conocimiento/{pid}/respaldo", {})
    paso(
        "respaldo con la API de backup",
        code == 200 and os.path.isfile(os.path.join(resp["destino"], "conocimiento.sqlite")),
    )
    paso("una sola base para el lienzo", os.path.isfile(os.path.join(HOME, "conocimiento.sqlite")))
    # 5. el comando que usa cualquier agente desde su terminal, contra este server
    cli_env = {**env, "LIENZO_URL": BASE}
    memoria = [sys.executable, os.path.join(RAIZ, "skills", "lienzo", "memoria.py")]

    def cli(*args):
        p = subprocess.run([*memoria, *args], cwd=CWD, env=cli_env, capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout

    code, out = cli("cola")
    paso("memoria.py busca en el proyecto de la carpeta", code == 0 and "la cola de captura no bloquea" in out)
    code, out = cli()
    paso("memoria.py sin argumentos da el briefing con lo abierto", code == 0 and "[hallazgo, propuesto]" in out)
    code, out = cli('"sin cerrar')
    paso("memoria.py con una consulta FTS rota sale con 3", code == 3)
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()
    evidencia["veredicto"] = all(p["ok"] for p in evidencia["pasos"])
    salida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados", "memoria-e2e.json")
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(evidencia, f, ensure_ascii=False, indent=1)
    shutil.rmtree(HOME, ignore_errors=True)
    print("veredicto", evidencia["veredicto"])
sys.exit(0 if evidencia["veredicto"] and evidencia["pasos"] else 1)
