"""Caso tarjetas-ajenas-e2e (encargo N, 2026-10-22): un server real en 7357 con LIENZO_HOME limpio en
%TEMP%, alimentado por archivos de evento como los que deja el hook. Un frente con su regla on_stop hacia
la coordinadora termina (SessionEnd) y su tarjeta se borra a los 60 s; una sesion nueva abierta despues en
la misma carpeta NO hereda la regla; renombrada en el lienzo con el titulo del frente, si. Nunca toca el
7321, ~/.lienzo ni las transcripciones reales. Sale 0 si todo se cumple, 1 si no, 2 si el server no arranca."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# otra copia del codigo (la de antes del arreglo, para ver el rojo): LIENZO_N_CODIGO=<carpeta lienzo>
CODIGO = os.environ.get("LIENZO_N_CODIGO") or os.path.join(RAIZ, "lienzo")
PUERTO = 7357
BASE = f"http://127.0.0.1:{PUERTO}"
T = os.path.join(tempfile.gettempdir(), f"lienzo-N-inst-{os.getpid()}")
CWD = os.path.join(T, "proyecto")
COORD = "c0000000-0000-4000-8000-00000000e2e1"
K = "c0000000-0000-4000-8000-00000000e2e2"
NUEVA = "c0000000-0000-4000-8000-00000000e2e3"
TITULO = "proyecto - encargo K - frente que se cierra"


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    req.add_header("X-Lienzo", "1")
    if datos is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def evento(nombre, sid, **extra):
    ev = {"hook_event_name": nombre, "session_id": sid, "agent": "claude", "cwd": CWD, **extra}
    carpeta = os.path.join(T, "home", "events")
    os.makedirs(carpeta, exist_ok=True)
    final = os.path.join(carpeta, f"{time.time_ns()}-{nombre}-{sid[:8]}.json")
    with open(final + ".tmp", "w", encoding="utf-8") as f:
        json.dump(ev, f)
    os.replace(final + ".tmp", final)


def esperar(cond, s, paso=0.5):
    fin = time.monotonic() + s
    while time.monotonic() < fin:
        try:
            if cond():
                return True
        except OSError:
            pass
        time.sleep(paso)
    return False


def tarjetas():
    return {s["session_id"]: s for s in pedir("GET", "/sessions")}


def regla_del_frente():
    return next((r for r in pedir("GET", "/rules") if r.get("id") == REGLA["id"]), {})


REGLA: dict = {}


def main() -> int:
    shutil.rmtree(T, ignore_errors=True)
    os.makedirs(CWD)
    env = {**os.environ, "LIENZO_HOME": os.path.join(T, "home"), "PYTHONIOENCODING": "utf-8"}
    for k, d in (("CLAUDE_CONFIG_DIR", "claude"), ("CODEX_HOME", "codex"), ("CODA_HOME", "coda")):
        env[k] = os.path.join(T, d)
    log = open(os.path.join(T, "server.log"), "w", encoding="utf-8")  # noqa: SIM115 (se cierra en el finally)
    srv = subprocess.Popen(
        [sys.executable, "-B", os.path.join(CODIGO, "server.py"), "--port", str(PUERTO), "--no-sweep",
         "--peer-port", str(PUERTO + 10000)],
        cwd=T, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    fallas = []
    try:
        if not esperar(lambda: pedir("GET", "/sessions") is not None, 30):
            print("el server aislado no arranco; ver", os.path.join(T, "server.log"))
            return 2
        evento("SessionStart", COORD)
        evento("SessionStart", K)
        if not esperar(lambda: {COORD, K} <= set(tarjetas()), 15):
            print("no aparecieron las tarjetas sembradas")
            return 2
        pedir("PUT", f"/sessions/{K}/title", {"title": TITULO})
        REGLA.update(
            pedir("POST", "/rules", {"kind": "on_stop", "from": K, "to": COORD, "text": "{respuesta}", "repeat": True})
        )
        REGLA.setdefault("id", (REGLA.get("rule") or {}).get("id"))
        print("regla creada:", REGLA.get("id"))
        if not REGLA.get("id"):
            print("POST /rules no devolvio un id")
            return 2

        evento("SessionEnd", K, reason="other")
        t0 = time.monotonic()
        ok = esperar(lambda: K not in tarjetas(), 120)
        print(f"tarjeta del frente borrada: {ok} ({time.monotonic() - t0:.0f} s)")
        r = regla_del_frente()
        print("estacionada:", r.get("parked_from"), r.get("enabled"))
        if not (ok and r.get("parked_from") == K and r.get("enabled") is False):
            fallas.append("la regla del frente cerrado no quedo estacionada")

        evento("SessionStart", NUEVA)
        esperar(lambda: NUEVA in tarjetas(), 15)
        time.sleep(3)  # el hilo de sucesion corre aparte
        r = regla_del_frente()
        print("con la sesion nueva sin relacion:", (r.get("from") or "")[-4:], r.get("enabled"))
        if r.get("from") != K or r.get("enabled") is not False:
            fallas.append("una sesion nueva sin relacion heredo la regla del frente cerrado (bug 2)")

        pedir("PUT", f"/sessions/{NUEVA}/title", {"title": TITULO})
        heredo = esperar(lambda: regla_del_frente().get("from") == NUEVA, 10)
        r = regla_del_frente()
        print("renombrada con el titulo del frente:", (r.get("from") or "")[-4:], r.get("enabled"))
        if not (heredo and r.get("enabled") is True and "parked_from" not in r):
            fallas.append("renombrarla con el titulo del frente no la hizo sucesora")
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
    for f in fallas:
        print("FALLA:", f)
    if not fallas:
        shutil.rmtree(T, ignore_errors=True)
    print("OK" if not fallas else f"{len(fallas)} fallas; el server.log queda en {T}")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
