"""Caso rondas-e2e (pruebas agenticas, rondas largas, pedido de Ariel del 2026-10-16): un server real en
un puerto aparte, con LIENZO_HOME propio, sin barrido, sin actualizar harness ni titular consolas. Las
tarjetas se inyectan como eventos de hook en <home>/events; lo demas va por HTTP con coordinar.py.
Oraculo: el encargo «lienzo mas fluido» (avisos sin duplicados, aviso con ack, turnos, memoria, tope
por repo, 404 de un id viejo) y el README, seccion «Rondas largas». Deja la evidencia en
resultados/rondas-e2e.json y sale con 1 si algun paso falla. Nunca toca ~/.lienzo ni el server de 7321."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUERTO = 7393
HOME = tempfile.mkdtemp(prefix="lienzo-rondas-")
CWD = RAIZ  # una carpeta real: el tope por repo cuenta por repo_key
evidencia = {"home": HOME, "pasos": []}

os.environ["LIENZO_URL"] = f"http://127.0.0.1:{PUERTO}"
sys.path.insert(0, os.path.join(RAIZ, "skills", "lienzo"))
import coordinar as c

# el server sin efectos sobre la maquina: no actualiza harness, no titula consolas ni corre el scheduler
ARRANQUE = f"""
import sys
sys.path.insert(0, {os.path.join(RAIZ, "lienzo")!r})
import console_titles, harness_updates, optimization_scheduler
harness_updates.start = console_titles.start = optimization_scheduler.start = lambda *a, **k: None
import server
sys.argv = ["lienzo-server", "--port", "{PUERTO}", "--no-sweep", "--peer-port", "{PUERTO + 1}"]
raise SystemExit(server.main())
"""


def paso(nombre, ok, **datos):
    evidencia["pasos"].append({"paso": nombre, "ok": bool(ok), **datos})
    print(("OK  " if ok else "MAL ") + nombre, flush=True)


def esperar(fn, segundos):
    fin = time.time() + segundos
    while time.time() < fin:
        r = fn()
        if r:
            return r
        time.sleep(0.5)
    return None


def evento(sid, nombre, **k):
    d = {
        "hook_event_name": nombre,
        "session_id": sid,
        "agent": "claude",
        "cwd": CWD,
        "host_ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        **k,
    }
    os.makedirs(os.path.join(HOME, "events"), exist_ok=True)
    p = os.path.join(HOME, "events", f"{time.time_ns()}-{sid[:8]}-{nombre}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(p + ".tmp", p)


def regla(rid):
    return next((x for x in c.pedir("GET", "/rules")[1] or [] if x["id"] == rid), {})


env = {**os.environ, "LIENZO_HOME": HOME, "PYTHONIOENCODING": "utf-8"}
srv = subprocess.Popen(
    [sys.executable, "-c", ARRANQUE], cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

try:
    paso(
        f"server real arriba en {PUERTO} con LIENZO_HOME temporal",
        esperar(lambda: c.pedir("GET", "/health")[0] == 200, 40),
    )
    sids = [str(uuid.uuid4()) for _ in range(5)]
    coord, fa, fb, fc, _ = sids
    for s in sids:
        evento(s, "SessionStart")
    vistas = esperar(lambda: (v := {s["session_id"] for s in c.sesiones()}) >= set(sids) and v, 15)
    paso("5 tarjetas inyectadas por hook", vistas)
    c.YO = coord

    # 1. avisos sin turnos intermedios ni repetidos
    code, r = c.pedir(
        "POST",
        "/rules",
        {"kind": "on_stop", "from": fa, "to": coord, "text": "{respuesta}", "repeat": True, "solo_si": "ESTADO:"},
    )
    paso(
        "POST /rules acepta solo_si y deja dedupe prendido",
        code == 200 and r.get("solo_si") == "ESTADO:" and r.get("dedupe") is True,
    )
    code, _ = c.pedir("POST", "/rules", {"kind": "on_stop", "from": fb, "to": coord, "text": "x", "solo_si": 5})
    paso("solo_si que no es texto da 400", code == 400)
    evento(fa, "UserPromptSubmit", prompt="corré la suite")
    time.sleep(1)
    evento(fa, "Stop", last_assistant_message="sigo esperando la suite")
    res = esperar(lambda: "turno intermedio" in (regla(r["id"]).get("last_result") or "") and regla(r["id"]), 15)
    paso("un turno sin ESTADO: no avisa y queda dicho en la regla", res, last_result=(res or {}).get("last_result"))

    # 2. aviso coordinado: sin consola los envios quedan en fallo; las confirmaciones por API lo cierran
    code, a = c.aviso("subí el contrato a v3", [fb, fc])
    paso("POST /avisos crea el aviso", code == 200 and a["id"].startswith("av-"))
    esperar(lambda: all(d["estado"] != "enviando" for d in c.aviso_estado(a["id"])["destinos"].values()), 15)
    paso("ack por API con nota", c.ack(a["id"], fb, "listo en backend")[0] == 200)
    code, fin = c.ack(a["id"], fc)
    paso("con todos confirmados el aviso queda completo", code == 200 and fin["estado"] == "completo")
    paso("un ack a un aviso cerrado da 409", c.ack(a["id"], fc)[0] == 409)

    # 3. turno de un recurso pesado
    code, t = c.pedir_turno("navegador", fa, motivo="agénticas")
    paso("el primero recibe el turno", code == 200 and t["otorgado"])
    code, t = c.pedir_turno("navegador", fb)
    paso("el segundo queda en cola", code == 202 and t["posicion"] == 1)
    code, t = c.liberar_turno("navegador", fa)
    paso("al soltarlo pasa al siguiente de la cola", code == 200 and (t.get("dueno") or {}).get("session_id") == fb)
    paso("la politica se fija", c.politica_turno("motores", ttl_max_min=10)[0] == 200)
    paso("un ttl sobre la politica da 400", c.pedir_turno("motores", fa, ttl_min=11)[0] == 400)

    # 4. memoria y tope por repo (con launch_roots vacio nada se lanza aunque pase el tope)
    m = c.memoria()
    paso(
        "GET /memoria con umbral y tope", isinstance(m, dict) and "bajo" in m and m["max_sesiones_por_repo"] == 0, mem=m
    )
    code, res = c.lanzar(None, CWD, "lienzo - encargo E - prueba", "claude")
    # sin tope por defecto: pasa al lanzador, que lo rechaza porque launch_roots esta vacia (no se lanza nada)
    paso(
        "sin tope por repo: lanzar no da tope_repo",
        code != 409 and "launch_roots" in str((res or {}).get("error")),
        code=code,
        res=res,
    )

    # 5. un id desconocido sigue dando el 404 de siempre
    code, res = c.pedir("POST", f"/sessions/{uuid.uuid4()}/send", {"text": "hola"})
    paso(
        "id sin sucesora: 404 de siempre",
        code == 404 and res.get("code") == "unknown_session" and "sucesora" not in res,
    )
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()
    evidencia["veredicto"] = all(p["ok"] for p in evidencia["pasos"])
    salida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados", "rondas-e2e.json")
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(evidencia, f, ensure_ascii=False, indent=1, default=str)
    shutil.rmtree(HOME, ignore_errors=True)
    print("veredicto", evidencia["veredicto"])
sys.exit(0 if evidencia["veredicto"] and evidencia["pasos"] else 1)
