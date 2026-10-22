"""Caso rechazos-run-e2e (encargo H, ronda 2026-10-22; decisiones 2 y 10 de Ariel): un server real en
el puerto 7352 con LIENZO_HOME propio, sin barrido, con el listener de peers en 127.0.0.1:17352 y una
PC emparejada falsa (clave escrita a mano en peers.json). Oráculo: cada 401/403/Host no válido de los
dos listeners queda en GET /rechazos con hora, origen, ruta, método y motivo, sin cuerpo ni query; un
POST /peer/run firmado corre `git status` dentro de launch_roots y deja su línea en GET /run/log; uno
fuera de launch_roots se niega y también queda. Evidencia en resultados/rechazos-run-e2e.json; sale
con 1 si algún paso falla. Nunca toca ~/.lienzo ni el server de 7321."""

import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUERTO, PUERTO_PEER = 7352, 17352
HOME = tempfile.mkdtemp(prefix=f"lienzo-H-{os.getpid()}-")
SECRETO = "s3cr3t0-e2e-" + secrets.token_hex(4)
PEER = "e2e-pc-" + secrets.token_hex(3)
CLAVE = secrets.token_bytes(32)
evidencia = {"home": HOME, "pasos": []}

sys.path.insert(0, os.path.join(RAIZ, "lienzo"))
import federation as fed

ARRANQUE = f"""
import sys
sys.path.insert(0, {os.path.join(RAIZ, "lienzo")!r})
import console_titles, harness_updates, optimization_scheduler
harness_updates.start = console_titles.start = optimization_scheduler.start = lambda *a, **k: None
import server
sys.argv = ["lienzo-server", "--port", "{PUERTO}", "--no-sweep", "--peers",
            "--peer-host", "127.0.0.1", "--peer-port", "{PUERTO_PEER}"]
raise SystemExit(server.main())
"""


def paso(nombre, ok, **datos):
    evidencia["pasos"].append({"paso": nombre, "ok": bool(ok), **datos})
    print(("OK  " if ok else "MAL ") + nombre, flush=True)


def pedir(port, method, path, body=b"", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        crudo = r.read()
        try:
            return r.status, json.loads(crudo or b"{}")
        except ValueError:
            return r.status, {"crudo": crudo[:200].decode("utf-8", "replace")}
    finally:
        c.close()


def firmado(path, obj):
    body = json.dumps(obj).encode()
    ts, nonce = time.time(), secrets.token_hex(16)
    headers = {
        "Content-Type": "application/json",
        "X-Lienzo-Peer": PEER,
        "X-Lienzo-Ts": repr(ts),
        "X-Lienzo-Nonce": nonce,
        "X-Lienzo-Sig": fed.sign(CLAVE, "POST", path, body, ts, nonce),
    }
    return pedir(PUERTO_PEER, "POST", path, body, headers)


with open(os.path.join(HOME, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"launch_roots": [RAIZ]}, f)
fed.add_peer(
    os.path.join(HOME, "peers.json"),
    {"pc_id": PEER, "name": "pc-e2e", "color": "#123456", "ip": "127.0.0.1", "port": 1, "key": CLAVE.hex()},
)
entorno = {**os.environ, "LIENZO_HOME": HOME, "LIENZO_PEER_PORT": str(PUERTO_PEER)}
server = subprocess.Popen(
    [sys.executable, "-c", ARRANQUE],
    cwd=RAIZ,
    env=entorno,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
codigo = 1
try:
    fin = time.time() + 60
    listo = False
    while time.time() < fin and not listo:
        try:
            listo = pedir(PUERTO, "GET", "/health")[0] == 200 and pedir(PUERTO_PEER, "GET", "/peer/hello")[0] == 200
        except OSError:
            time.sleep(0.5)
    paso("server aislado arriba (7352 y peer 17352)", listo)

    cuerpo = json.dumps({"text": SECRETO}).encode()
    hdr = {"Content-Type": "application/json", "Origin": "http://evil.example", "User-Agent": "Dot-e2e/1"}
    code, _ = pedir(PUERTO, "POST", f"/rules?token={SECRETO}", cuerpo, hdr)
    paso("POST sin X-Lienzo: 403", code == 403, codigo=code)
    code, _ = pedir(PUERTO, "GET", "/health", headers={"Host": "rebind.example"})
    paso("Host ajeno: 400", code == 400, codigo=code)
    code, _ = pedir(PUERTO_PEER, "POST", "/peer/run", cuerpo, {"X-Lienzo-Peer": "intrusa", "X-Lienzo-Sig": SECRETO})
    paso("peer sin firma: 401", code == 401, codigo=code)

    code, res = firmado("/peer/run", {"command": "status", "cwd": RAIZ})
    paso("run firmado status en launch_roots: 200 y exit 0", code == 200 and res.get("exit_code") == 0, codigo=code)
    code, res = firmado("/peer/run", {"command": "status", "cwd": os.path.dirname(RAIZ)})
    paso("run firmado fuera de launch_roots: 403", code == 403, codigo=code, error=res.get("error"))

    code, res = pedir(PUERTO, "GET", "/rechazos")
    rech = res.get("rechazos") or []
    evidencia["rechazos"] = rech
    por = {(e["listener"], e["codigo"], e["ruta"]) for e in rech}
    paso("GET /rechazos: 200", code == 200)
    paso("rechazo CSRF registrado", ("tablero", 403, "/rules") in por)
    paso("rechazo Host registrado", any(e["motivo"] == "Host no valido" for e in rech))
    paso("rechazo de firma registrado", ("peer", 401, "/peer/run") in por)
    paso("run fuera de raíz también como rechazo", ("peer", 403, "/peer/run") in por)
    paso(
        "cada rechazo trae hora, ip, metodo y motivo",
        bool(rech) and all(e.get("hora") and e.get("ip") and e.get("metodo") and e.get("motivo") for e in rech),
    )

    code, res = pedir(PUERTO, "GET", "/run/log")
    corridas = res.get("run") or []
    evidencia["run"] = corridas
    paso(
        "GET /run/log: una línea por comando",
        code == 200 and [c["codigo"] for c in corridas] == [200, 403] and corridas[0]["peer"] == PEER,
    )
    crudo = ""
    for nombre in ("rechazos.jsonl", "remote_run.jsonl"):
        with open(os.path.join(HOME, nombre), encoding="utf-8") as f:
            crudo += f.read()
    paso("ningún secreto, cuerpo ni query en disco", SECRETO not in crudo)
    codigo = 0 if all(p["ok"] for p in evidencia["pasos"]) else 1
finally:
    server.terminate()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()
    destino = os.path.join(RAIZ, "pruebas-agenticas", "resultados", "rechazos-run-e2e.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(evidencia, f, ensure_ascii=False, indent=1)
    shutil.rmtree(HOME, ignore_errors=True)
raise SystemExit(codigo)
