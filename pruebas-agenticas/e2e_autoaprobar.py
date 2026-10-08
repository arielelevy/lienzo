"""Prueba de punta a punta REAL del auto-aprobar de dialogos (pedido de Ariel, 2026-10-08).

Lanza desde el lienzo una sesion de Codex en una carpeta de `launch_roots`, le manda un pedido que
obliga a correr un comando (Codex pide «Would you like to run the following command?» como dialogo
de la TUI, sin hook), y verifica que, con auto-aprobar prendido, el lienzo lo contesta solo: la
tarjeta sale de «te necesita» y en lienzo.log queda «AUTO-APROBADO (dialogo) codex ...» de ESA
sesion. Al final cierra la sesion (POST /sessions/<sid>/kill, confirmado con su id).

Gasta un turno de Codex (es un caso pago: lo informa el plugin, no lo corre solo). Exige el lienzo
real en 127.0.0.1:7321 con `auto_aprobar: true`; si esta apagado NO lo prende: sale con 2 y lo dice.

    py -I pruebas-agenticas/e2e_autoaprobar.py [--cwd D:/Apps/pruebas-agenticas] [--espera 180]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7321"
LOG = os.path.join(os.environ.get("LIENZO_HOME") or os.path.join(os.path.expanduser("~"), ".lienzo"), "lienzo.log")
PEDIDO = (
    "Prueba del lienzo: ejecutá exactamente este comando con tu herramienta de shell y no hagas "
    "nada más, ni expliques: python -c \"print('lienzo e2e auto-aprobar ok')\""
)


def pedir(metodo: str, ruta: str, cuerpo: dict | None = None, timeout: float = 30) -> tuple[int, dict | list]:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers={"X-Lienzo": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {"error": str(e)}


def sesiones() -> list[dict]:
    _c, d = pedir("GET", "/sessions")
    return d if isinstance(d, list) else (d or {}).get("sessions", [])


def tarjeta(sid: str) -> dict | None:
    return next((s for s in sesiones() if s.get("session_id") == sid), None)


def log_desde(t0: dt.datetime) -> str:
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lineas = f.read().splitlines()[-2000:]
    except OSError:
        return ""
    out = []
    for l in lineas:
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", l)
        if m and dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= t0.replace(microsecond=0):
            out.append(l)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", default="D:/Apps/pruebas-agenticas")
    ap.add_argument("--espera", type=float, default=180)
    ap.add_argument("--agent", default="codex")
    args = ap.parse_args()
    evidencia: dict = {"inicio": dt.datetime.now().isoformat(timespec="seconds"), "cwd": args.cwd, "agent": args.agent}

    code, cfg = pedir("GET", "/config")
    if code != 200:
        print(json.dumps({**evidencia, "veredicto": "no_ejecutado", "motivo": f"GET /config {code}"}, ensure_ascii=False))
        return 2
    if not cfg.get("auto_aprobar"):
        print(json.dumps({**evidencia, "veredicto": "no_ejecutado", "motivo": "auto_aprobar apagado: no se prende solo"}, ensure_ascii=False))
        return 2

    t0 = dt.datetime.now()
    antes = {s.get("session_id") for s in sesiones()}
    code, res = pedir("POST", "/sessions/launch", {"cwd": args.cwd, "title": "e2e auto-aprobar", "agent": args.agent}, timeout=60)
    evidencia["launch"] = {"code": code, "res": res}
    if code != 200:
        print(json.dumps({**evidencia, "veredicto": "fallo", "motivo": "launch"}, ensure_ascii=False))
        return 1
    sid = None
    fin = time.time() + 90
    while time.time() < fin and sid is None:
        time.sleep(2)
        nuevas = [s for s in sesiones() if s.get("session_id") not in antes and s.get("agent") == args.agent and s.get("alive")]
        sid = nuevas[0]["session_id"] if nuevas else None
    if sid is None:
        print(json.dumps({**evidencia, "veredicto": "fallo", "motivo": "la tarjeta nueva no aparecio en 90 s"}, ensure_ascii=False))
        return 1
    evidencia["session_id"] = sid
    try:
        # esperar a que la TUI este lista (termino / idle) antes de escribirle: mandar el pedido a
        # una terminal que todavia arranca no prueba nada del auto-aprobar
        fin = time.time() + 60
        lista = False
        while time.time() < fin and not lista:
            s = tarjeta(sid) or {}
            lista = s.get("state") == "termino" or (s.get("needs") or {}).get("kind") == "idle"
            if not lista:
                time.sleep(2)
        evidencia["tui_lista"] = lista
        if not lista:
            s = tarjeta(sid) or {}
            print(json.dumps({**evidencia, "veredicto": "no_ejecutado", "motivo": "la TUI no quedo lista en 60 s", "estado": s.get("state"), "needs": s.get("needs")}, ensure_ascii=False))
            return 2
        code, res = pedir("POST", f"/sessions/{sid}/send", {"text": PEDIDO}, timeout=60)
        evidencia["send"] = {"code": code, "res": res}
        if code != 200:
            print(json.dumps({**evidencia, "veredicto": "fallo", "motivo": "send"}, ensure_ascii=False))
            return 1
        # el permiso: la tarjeta pasa por te_necesita/dialog y el auto-aprobar lo contesta
        vio_dialogo = False
        aprobado = None
        fin = time.time() + args.espera
        while time.time() < fin:
            s = tarjeta(sid) or {}
            if (s.get("needs") or {}).get("kind") == "dialog":
                vio_dialogo = True
                evidencia["dialogo"] = s.get("dialog")
                evidencia["omitido"] = s.get("auto_aprobar_omitido")
            lineas = [l for l in log_desde(t0).splitlines() if "AUTO-APROBADO (dialogo)" in l and sid[:8] in l]
            if lineas:
                aprobado = lineas[-1]
                break
            time.sleep(2)
        evidencia["vio_dialogo"] = vio_dialogo
        evidencia["auto_aprobado"] = aprobado
        if aprobado is None:
            s = tarjeta(sid) or {}
            print(json.dumps({**evidencia, "veredicto": "fallo", "motivo": "sin AUTO-APROBADO (dialogo) en el log", "estado_final": s.get("state"), "needs": s.get("needs")}, ensure_ascii=False))
            return 1
        # despues de aprobar, la tarjeta sigue (corriendo o termino), no en te_necesita por el dialogo
        fin = time.time() + 30
        estado = None
        while time.time() < fin:
            s = tarjeta(sid) or {}
            estado = s.get("state")
            if (s.get("needs") or {}).get("kind") != "dialog":
                break
            time.sleep(2)
        evidencia["estado_despues"] = estado
        ok = estado in ("corriendo", "termino")
        print(json.dumps({**evidencia, "veredicto": "ok" if ok else "fallo"}, ensure_ascii=False))
        return 0 if ok else 1
    finally:
        code, res = pedir("POST", f"/sessions/{sid}/kill", {"confirm": sid}, timeout=30)
        print(json.dumps({"kill": {"code": code, "res": res}}, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
