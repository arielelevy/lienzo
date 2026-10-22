"""El titulo pedido en POST /sessions/launch, para la tarjeta del proceso que nacio de ese lanzamiento.

launch.py escribe `<token>.cmd` en `<LIENZO_HOME>/launch/` y lo abre con explorer.exe: el agente queda
como hijo de `cmd.exe /c "...\\launch\\<token>.cmd"`. Al lado se guarda `<token>.json` con el titulo y el
agente; la tarjeta nueva lo recupera subiendo por los padres de su PID hasta ese cmd.exe. Medido el
2026-10-22: sin esto la tarjeta salia como «sesion sin transcripcion identificada» o con el primer
pedido, y el titulo solo llegaba a la ventana. Sin shell ni cwd de por medio: un .cmd ajeno a la
carpeta de lanzamiento, otro agente o un archivo roto no titulan nada.
"""

from __future__ import annotations

import json
import os
import re

import procinfo
import state

SALTOS = 4  # agente <- cmd.exe en el lanzamiento directo; con margen para un .cmd de npm (pi.cmd)
_CMD_RE = re.compile(r"([^\"]*[\\/]launch[\\/]([0-9a-f]{12})\.cmd)", re.IGNORECASE)


def carpeta() -> str:
    return os.path.join(state.LIENZO, "launch")


def guardar(cmd_path: str, title: str, agent: str) -> None:
    """Junto al .cmd recien escrito. Un fallo no frena el lanzamiento: la tarjeta sale sin el titulo."""
    title = state.short(title or "", 120)
    if not title:
        return
    try:
        with open(os.path.splitext(cmd_path)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump({"title": title, "agent": agent}, f, ensure_ascii=False)
    except OSError as e:
        state.log(f"lanzamiento: no se guardo el titulo pedido de {os.path.basename(cmd_path)}: {e}")


def _token_de(cmdline: str | None) -> str | None:
    match = _CMD_RE.search(cmdline or "")
    if not match:
        return None
    try:
        propia = os.path.samefile(os.path.dirname(match.group(1)), carpeta())
    except OSError:
        return None
    return match.group(2).lower() if propia else None


def pedido(pid: int | None, agent: str) -> str | None:
    """El titulo del lanzamiento del que nacio `pid`, si fue de este Lienzo y para este agente."""
    if not pid or not procinfo._WIN:
        return None
    hop = int(pid)
    for _ in range(SALTOS):
        parent, _exe = procinfo.proc_info(hop)
        if not parent or parent == hop:
            return None
        if token := _token_de(procinfo.command_line(parent)):
            try:
                with open(os.path.join(carpeta(), f"{token}.json"), encoding="utf-8") as f:
                    data = json.load(f)
            except OSError, ValueError:
                return None
            if not isinstance(data, dict) or data.get("agent") != agent or not isinstance(data.get("title"), str):
                return None
            return state.short(data["title"], 120) or None
        hop = parent
    return None


def aplicar(s: dict) -> bool:
    """Titula la tarjeta con lo pedido al lanzarla, salvo que ya tenga un titulo del usuario. Con el
    lock del registro tomado, como cualquier cambio de tarjeta; no lo toma."""
    if s.get("title_source") == "user":
        return False
    title = pedido(s.get("pid"), s.get("agent") or "")
    if not title:
        return False
    s["title"], s["title_source"] = title, "user"
    return True
