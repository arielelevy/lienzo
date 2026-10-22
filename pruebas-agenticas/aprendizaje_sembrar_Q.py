"""Caso aprendizaje-por-proyecto (encargo Q, 2026-10-22): siembra por la API real de una instancia aislada
(LIENZO_URL, LIENZO_HOME temporal) un proyecto con una carpeta, un encargo en curso con su tipo de trabajo,
una propuesta propia, una de proceso de Lienzo en el proyecto `lienzo`, y una sesión viva de Claude en esa
carpeta entregada por el hook real (`hook.py claude`), con una transcripción que anota la versión de la CLI.
Comprueba por la API lo que la interfaz va a mostrar. Deja la evidencia en aprendizaje-e2e-Q.json.
Nunca toca el server de 7321."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["LIENZO_URL"]
HOME = os.environ["LIENZO_HOME"]
CODE = sys.argv[1]  # la copia del código de la instancia (su lienzo/)
CARPETA = sys.argv[2]  # la carpeta del proyecto, fuera del repo
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados", "aprendizaje-Q", "aprendizaje-e2e-Q.json")
P = "demo-q"
SID = "q0e2e000-0000-4000-8000-00000000000q"
evidencia = {"base": BASE, "pasos": []}


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo, ensure_ascii=False).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("X-Lienzo", "1")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def paso(nombre, codigo, cuerpo, ok=None):
    ok = codigo == 200 if ok is None else ok
    evidencia["pasos"].append({"paso": nombre, "codigo": codigo, "ok": bool(ok), "cuerpo": cuerpo})
    print(("OK  " if ok else "MAL ") + nombre, codigo, flush=True)
    if not ok:
        raise SystemExit(json.dumps(cuerpo, ensure_ascii=False)[:2000])
    return cuerpo


def main():
    os.makedirs(CARPETA, exist_ok=True)
    sys.path.insert(0, CODE)
    import identity  # la de la instancia: mismo LIENZO_HOME, mismo pc_id

    pc = identity.pc_id()
    paso(
        "proyecto con carpeta",
        *pedir(
            "POST", "/conocimiento/proyectos", {"id": P, "nombre": "Demo Q", "carpetas": [{"pc": pc, "cwd": CARPETA}]}
        ),
    )
    paso("proyecto lienzo", *pedir("POST", "/conocimiento/proyectos", {"id": "lienzo", "nombre": "Lienzo"}))
    ronda = paso(
        "ronda", *pedir("POST", f"/conocimiento/{P}/rondas", {"objetivo": "demo del aprendizaje por proyecto"})
    )
    paso(
        "encargo en curso",
        *pedir(
            "POST",
            f"/conocimiento/{P}/encargos",
            {
                "ronda": ronda["id"],
                "letra": "Q",
                "texto": "# Q",
                "contexto_desarrollo": {"tipo_trabajo": "feature", "tecnologia": "react"},
            },
        ),
    )
    fuente = paso(
        "hallazgo",
        *pedir(
            "POST",
            f"/conocimiento/{P}/nodos",
            {
                "tipo": "hallazgo",
                "texto": "La pestaña pedía 8 campos",
                "datos": {"donde": "Learning.tsx", "gravedad": "media"},
                "autor": "persona:Ariel",
            },
        ),
    )
    propia = paso(
        "propuesta del proyecto",
        *pedir(
            "POST",
            f"/conocimiento/{P}/creencias",
            {
                "texto": "Abrir con lo aprendido, sin pedir contexto",
                "accion": "Mostrar las creencias del proyecto al abrir",
                "dimension": "contexto",
                "contexto": {"tipo_trabajo": "feature"},
                "fuentes": [fuente["id"]],
            },
        ),
    )
    fuente_l = paso(
        "hallazgo en lienzo",
        *pedir(
            "POST",
            "/conocimiento/lienzo/nodos",
            {
                "tipo": "hallazgo",
                "texto": "Frente cerrado sin verificar en uso real",
                "datos": {"donde": "ronda 2026-10-22", "gravedad": "media"},
                "autor": "persona:Ariel",
            },
        ),
    )
    proceso = paso(
        "propuesta de proceso de Lienzo",
        *pedir(
            "POST",
            "/conocimiento/lienzo/creencias",
            {
                "texto": "Un frente no cierra sin uso real",
                "accion": "Verificar en uso real antes de cerrar un frente",
                "dimension": "coordinacion",
                "fuentes": [fuente_l["id"]],
                "alcance": "proceso_lienzo",
            },
        ),
    )
    # la sesión viva: el hook real, con una transcripción que anota la versión de la CLI
    transcript = os.path.join(CARPETA, "transcript.jsonl")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "version": "2.9.0", "cwd": CARPETA}) + "\n")
        f.write(json.dumps({"type": "assistant", "version": "2.9.1", "message": {"model": "claude-opus-5-5"}}) + "\n")
    evento = {
        "hook_event_name": "SessionStart",
        "session_id": SID,
        "cwd": CARPETA,
        "transcript_path": transcript,
        "source": "startup",
        "model": "claude-opus-5-5",
    }
    r = subprocess.run(
        [sys.executable, os.path.join(CODE, "hook.py"), "claude", "--lienzo-home", HOME],
        input=json.dumps(evento).encode(),  # por tubería, como lo manda Claude Code
        capture_output=True,
        timeout=30,
    )
    paso(
        "hook SessionStart",
        200 if r.returncode == 0 else r.returncode,
        {"stderr": r.stderr.decode(errors="replace")[-500:]},
    )
    sugerido = None
    for _ in range(40):  # el server lee los eventos cada tanto
        code, sugerido = pedir("GET", f"/conocimiento/{P}/contexto-sugerido")
        if code == 200 and sugerido.get("session_id") == SID:
            break
        time.sleep(0.5)
    paso(
        "contexto sugerido sin sesión elegida: la viva más reciente del proyecto y el encargo en curso",
        200,
        sugerido,
        ok=sugerido.get("session_id") == SID
        and sugerido["contexto"].get("tipo_trabajo") == "feature"
        and sugerido["contexto"].get("agente") == "claude"
        and sugerido["contexto"].get("version_agente") == "2.9.1"
        and sugerido["fuentes"].get("version_agente", "").startswith("la sesión"),
    )
    vista = paso("vista del proyecto", *pedir("GET", f"/conocimiento/{P}/creencias-proyecto"))
    paso(
        "propia y de proceso, sin pedir contexto",
        200,
        vista,
        ok=[x["creencia"] for x in vista["proyecto"]["items"]] == [propia["id"]]
        and [x["creencia"] for x in vista["lienzo"]["items"]] == [proceso["id"]],
    )
    evidencia["ids"] = {"propia": propia["id"], "proceso": proceso["id"], "sesion": SID}


os.makedirs(os.path.dirname(OUT), exist_ok=True)
try:
    main()
    evidencia["ok"] = True
finally:
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(evidencia, f, ensure_ascii=False, indent=1)
sys.exit(0 if evidencia.get("ok") else 1)
