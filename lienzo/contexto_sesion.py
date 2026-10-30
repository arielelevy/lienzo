"""Que las creencias lleguen a cada sesión (pedido de Ariel, 2026-10-30: «con todas las creencias, después
¿qué se hace?»). Hasta ahora sólo llegaban hasta 3 en los encargos de la coordinadora; una sesión abierta a
mano no veía ninguna.

El server escribe `<LIENZO_HOME>/contexto-sesion.json` cada CADA_S: por carpeta de proyecto de esta PC, el
texto con los principios de proceso y las creencias vigentes del proyecto, y los controles activos. El hook
de Claude (hook.py) lo lee sin hablar con el server: en SessionStart lo inyecta como contexto y en
PreToolUse de Bash aplica los controles. A los otros agentes que lanza Lienzo el texto les llega con las
instrucciones de lanzamiento (launch.py).

Un control es un chequeo concreto del catálogo CONTROLES; se activa sólo si una creencia vigente lo nombra
en `datos.control`, y aplica donde aplica esa creencia (todo, si es de proceso de Lienzo)."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import traceback

import conocimiento as k
import creencias
import identity
import state
from atomico import atomic_write

CADA_S = 600
POR_BLOQUE = 8
TEXTO_CORTO = 180

# id -> chequeo sobre el comando de Bash. `patron` dispara, `excepto` lo deja pasar.
CONTROLES = {
    "pipefail_pruebas": {
        "herramienta": "Bash",
        "descripcion": "pruebas con su salida por un pipe sin pipefail: el código de salida es el del último comando",
        "patron": r"\b(pytest|py\.test|npm (run )?test|npx (vitest|jest|playwright)|vitest|jest|go test|cargo test|dotnet test)\b[^|;&]*\|\s*(tail|head|grep|tee|less|more)\b",
        "excepto": r"pipefail",
        "mensaje": "Las pruebas van por un pipe sin pipefail: si fallan, el código de salida es 0. Anteponé "
        "`set -o pipefail;` (o corré sin pipe y leé la salida completa).",
    },
}


def path() -> str:
    return os.path.join(os.environ.get("LIENZO_HOME") or state.LIENZO, "contexto-sesion.json")


def _corto(texto: str) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= TEXTO_CORTO else texto[: TEXTO_CORTO - 1] + "…"


def _linea(item: dict) -> str:
    accion, texto = _corto(item.get("accion") or item["texto"]), _corto(item["texto"])
    return f"- {accion}" + (f" (por qué: {texto})" if texto and texto != accion else "")


def _vigentes(vista_bloque: dict) -> list[dict]:
    return [x for x in vista_bloque["items"] if x["estado"] == "vigente"]


def texto(pid: str) -> str | None:
    """Principios de proceso y creencias vigentes del proyecto, cortos. None si no hay ninguna."""
    vista = creencias.vista_proyecto(pid)
    proceso, propias = _vigentes(vista["lienzo"]), _vigentes(vista["proyecto"])
    if not proceso and not propias:
        return None
    partes = [
        "## Aprendizajes de Lienzo",
        "Creencias validadas de la memoria de Lienzo. Aplicalas cuando correspondan al trabajo; si una no "
        "aplica, seguí tu criterio y decilo al cerrar.",
    ]
    if proceso:
        partes += ["### Cómo se trabaja con Lienzo", *map(_linea, proceso[:POR_BLOQUE])]
    if propias:
        partes += [f"### De este proyecto ({pid})", *map(_linea, propias[:POR_BLOQUE])]
    return "\n".join(partes)


def controles_activos() -> list[dict]:
    """Controles del catálogo nombrados por una creencia vigente, con dónde aplican."""
    out = []
    for project in k.proyectos():
        pid = project["id"]
        try:
            with k._abrir(pid) as con:
                rows = con.execute(
                    "SELECT id, datos FROM nodo WHERE proyecto=? AND tipo='decision' AND estado='vigente' "
                    "AND json_extract(datos,'$.clase')='creencia_operativa' "
                    "AND json_extract(datos,'$.control') IS NOT NULL",
                    (pid,),
                ).fetchall()
        except k.Rechazo:
            continue
        for row in rows:
            datos = json.loads(row["datos"])
            control = CONTROLES.get(datos.get("control"))
            if control is None:
                continue
            global_ = pid == creencias.PROYECTO_LIENZO and datos.get("alcance") == "proceso_lienzo"
            out.append(
                {
                    "id": datos["control"],
                    "creencia": row["id"],
                    "proyecto": None if global_ else pid,
                    **{key: control[key] for key in ("herramienta", "patron", "excepto", "mensaje")},
                }
            )
    return out


def escribir() -> dict:
    """El archivo que leen el hook y launch.py: carpetas de esta PC -> proyecto, textos y controles."""
    yo = identity.pc_id()
    carpetas, textos = {}, {}
    for project in k.proyectos():
        pid = project["id"]
        locales = [c["cwd"] for c in project.get("carpetas", []) if c.get("pc") == yo and c.get("cwd")]
        if not locales:
            continue
        try:
            contenido = texto(pid)
        except k.Rechazo:
            continue
        for cwd in locales:
            carpetas[identity.norm_cwd(cwd)] = pid
        if contenido:
            textos[pid] = contenido
    data = {
        "generado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "carpetas": carpetas,
        "textos": textos,
        "controles": controles_activos(),
    }
    atomic_write(path(), json.dumps(data, ensure_ascii=False, indent=1))
    return data


def proyecto_de(data: dict, cwd: str | None) -> str | None:
    """El proyecto de la carpeta más específica que contiene a `cwd` (una sesión en una subcarpeta también)."""
    actual = identity.norm_cwd(cwd)
    mejor = None
    for carpeta, pid in data.get("carpetas", {}).items():
        if (actual == carpeta or actual.startswith(carpeta + "/")) and (mejor is None or len(carpeta) > len(mejor[0])):
            mejor = (carpeta, pid)
    return mejor[1] if mejor else None


def texto_para(cwd: str | None) -> str | None:
    """Para launch.py: el texto de la carpeta, leído del último archivo escrito."""
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
    except OSError, ValueError:
        return None
    pid = proyecto_de(data, cwd)
    return data.get("textos", {}).get(pid) if pid else None


def bucle(stop: threading.Event | None = None) -> None:
    while True:
        try:
            escribir()
        except Exception:
            state.log(f"contexto de sesión: no se pudo escribir\n{traceback.format_exc()}")
        if stop is not None and stop.wait(CADA_S):
            return
        if stop is None:
            time.sleep(CADA_S)
