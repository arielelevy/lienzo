"""Recorrido E2E de las features del 2026-10-26 contra el lienzo real de esta PC (127.0.0.1:7321).

1. reglas: DELETE de una regla ya apagada con informes sin integrar -> 409 con desactivada, pendientes y
   el motivo original intacto. No crea ni borra nada: la regla ya estaba apagada y sigue igual.
2. auditoria: una ronda real sin enviar; el hallazgo informe_no_entregado sólo aparece para un frente cuya
   regla hacia la coordinadora está apagada.
3. xfer: con la config real sin copy_roots, la raíz del repo sigue permitida por launch_roots.

Sale con 0 si todo pasa y 1 con el detalle de lo que falló."""

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "lienzo"))
BASE = "http://127.0.0.1:7321"
fallas = []


def pedir(metodo, ruta):
    req = urllib.request.Request(BASE + ruta, method=metodo, headers={"X-Lienzo": "1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def reglas():
    r = pedir("GET", "/rules")[1]
    return r if isinstance(r, list) else r.get("rules", [])


def caso_reglas():
    candidatas = [
        r
        for r in reglas()
        if r.get("kind") == "on_stop"
        and not r.get("enabled")
        and any(i.get("estado") != "integrado" for i in r.get("informes", []))
    ]
    if not candidatas:
        fallas.append("reglas: no hay una regla apagada con informes pendientes para probar")
        return
    r = candidatas[0]
    antes = r.get("disabled_reason")
    code, body = pedir("DELETE", f"/rules/{r['id']}")
    if code != 409 or not body.get("conservada") or not body.get("desactivada"):
        fallas.append(f"reglas: esperaba 409 conservada+desactivada, vino {code} {body}")
    if not body.get("pendientes"):
        fallas.append("reglas: la respuesta no lista los informes pendientes")
    if "desactivada" not in (body.get("error") or ""):
        fallas.append("reglas: el texto del error no dice que quedó desactivada")
    despues = next((x for x in reglas() if x["id"] == r["id"]), None)
    if despues is None:
        fallas.append("reglas: la regla con informes pendientes desapareció")
    elif despues.get("enabled") or despues.get("disabled_reason") != antes:
        fallas.append(f"reglas: cambió el estado o el motivo ({antes!r} -> {despues.get('disabled_reason')!r})")
    print(f"reglas: {r['id']} -> {code}, {len(body.get('pendientes', []))} pendientes, motivo intacto")


def caso_auditoria():
    import auditoria as au

    with tempfile.TemporaryDirectory() as d:
        r = au.ronda_local(BASE, os.path.join(d, "estado.json"), enviar=False)
    todas = reglas()
    sesiones = {s["session_id"]: s for s in pedir("GET", "/sessions")[1]}
    coord = {s.get("repo_key"): s["session_id"] for s in sesiones.values() if s.get("coordinator") and s.get("alive")}
    for h in r["hallazgos"]:
        if h["tipo"] != "informe_no_entregado":
            continue
        c = coord.get(h.get("repo"))
        if not au._regla_apagada(todas, h["session_id"], c):
            fallas.append(f"auditoria: falso positivo para {h['session_id']}")
    print(f"auditoria: ronda real en {r['costo_ms']} ms, {len(r['hallazgos'])} hallazgos, sin falsos positivos")


def caso_xfer():
    import state
    import xfer

    real = state.load_config()
    sin_copy = {k: v for k, v in real.items() if k != "copy_roots"}
    state.load_config = lambda: sin_copy
    destino = os.path.join(RAIZ, "PENDIENTES.md")
    if xfer.permitido(destino) is None:
        fallas.append("xfer: con launch_roots y sin copy_roots, la raíz del repo no quedó permitida")
    state.load_config = lambda: {**sin_copy, "copy_incluye_launch_roots": False}
    if xfer.permitido(destino) is not None:
        fallas.append("xfer: copy_incluye_launch_roots false no apagó launch_roots")
    print("xfer: la raíz del repo entra por launch_roots y se apaga con la opción")


for caso in (caso_reglas, caso_auditoria, caso_xfer):
    try:
        caso()
    except Exception as e:  # una excepción es una falla del caso, no del script
        fallas.append(f"{caso.__name__}: {type(e).__name__}: {e}")

for f in fallas:
    print("FALLA", f)
sys.exit(1 if fallas else 0)
