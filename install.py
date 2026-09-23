#!/usr/bin/env python
"""Instala (o desinstala) los hooks del lienzo en Claude Code, Codex y Pi.

    python install.py            # registra hooks en ~/.claude/settings.json y ~/.codex/hooks.json, y la extension de Pi
    python install.py --uninstall

Hace merge, nunca pisa: guarda ~/.claude/settings.json.bak-<fecha> antes de tocar.
Los hooks apuntan a D:/Apps/lienzo/lienzo/hook.py (este repo), sin copiar nada a ~/.lienzo/bin.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
HOOK = f"{HERE}/lienzo/hook.py"

# El mismo interprete con el que se instala; ejecutar con py -3.14.
PY = sys.executable.replace("\\", "/")

CLAUDE_EVENTS = {
    "SessionStart": (True, 5),
    "UserPromptSubmit": (True, 5),
    "Stop": (True, 5),
    "Notification": (True, 5),
    "PermissionRequest": (False, 90),
    "SessionEnd": (False, 2),
}
CODEX_EVENTS = {
    "SessionStart": (True, 5),
    "UserPromptSubmit": (True, 5),
    "Stop": (True, 5),
    "PermissionRequest": (False, 90),
    "SessionEnd": (False, 2),
    "Interrupt": (False, 2),
}


def cmd(agent: str) -> str:
    # Sin comillas si la ruta no tiene espacios: Codex puede correr el hook por PowerShell,
    # y en PowerShell una linea que empieza con un string entre comillas no se ejecuta.
    py = f'"{PY}"' if " " in PY else PY
    return f"{py} {HOOK} {agent}"


def is_ours(group: dict) -> bool:
    return any("lienzo" in (h.get("command") or "") for h in group.get("hooks", []))


def entry(agent: str, asyn: bool, timeout: int) -> dict:
    e = {"type": "command", "command": cmd(agent), "timeout": timeout}
    if asyn:
        e["async"] = True
    return {"hooks": [e]}


def merge_hooks(path: str, agent: str, events: dict, uninstall: bool, backup=False, prune=False) -> None:
    """Registra (o saca) los hooks del lienzo en un archivo de configuracion sin pisar lo que ya
    hay: de cada evento se filtran solo los grupos propios (is_ours) y se vuelve a agregar el
    nuestro. `backup` guarda una copia antes de tocar, para el settings.json de Claude, que ademas
    de hooks tiene todo lo del usuario; `prune` saca la clave "hooks" entera si queda vacia."""
    data = {}
    if os.path.exists(path):
        if backup:
            bak = path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, bak)
            print("backup:", bak)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    hooks = data.setdefault("hooks", {})
    for ev, (asyn, to) in events.items():
        groups = [g for g in hooks.get(ev, []) if not is_ours(g)]
        if not uninstall:
            groups.append(entry(agent, asyn, to))
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)
    if prune and not hooks:
        data.pop("hooks", None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(("quitados" if uninstall else "registrados"), f"hooks de {agent.capitalize()} en", path)


def merge_pi(path: str, uninstall: bool) -> None:
    """Registra la extension por ruta absoluta sin tocar otras extensiones ni settings."""
    if uninstall and not os.path.exists(path):
        return
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    extension = f"{HERE}/extensions/pi-lienzo.ts"
    existing = data.get("extensions", [])
    if not isinstance(existing, list):
        raise TypeError(f"extensions no es una lista en {path}")
    paths = [
        p
        for p in existing
        if not (isinstance(p, str) and os.path.normcase(os.path.abspath(p)) == os.path.normcase(extension))
    ]
    if not uninstall:
        paths.append(extension)
    if paths:
        data["extensions"] = paths
    else:
        data.pop("extensions", None)
    if os.path.exists(path):
        bak = path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, bak)
        print("backup:", bak)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".lienzo.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    print("extension Pi", "quitada de" if uninstall else "registrada en", path)


def ensure_state() -> None:
    root = os.path.join(HOME, ".lienzo")
    for d in ("events", "pending", "answers", "adjuntos", "sessions"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    cfg = os.path.join(root, "config.json")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"ejemplos": f"{HERE}/ejemplos", "wait": 60}, f, indent=2)
    print("estado en", root)


if __name__ == "__main__":
    if sys.version_info < (3, 14):  # noqa: UP036 -- instalador ejecutable antes de instalar el proyecto
        raise SystemExit("Lienzo requiere Python 3.14 o posterior. Usá: py -3.14 install.py")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    only = parser.add_mutually_exclusive_group()
    for agent in ("claude", "codex", "pi"):
        only.add_argument(f"--{agent}-only", dest="only", action="store_const", const=agent)
    args = parser.parse_args()
    un = args.uninstall
    print("python para el hook:", PY)
    ensure_state()
    if args.only in (None, "claude"):
        settings = os.path.join(HOME, ".claude", "settings.json")
        merge_hooks(settings, "claude", CLAUDE_EVENTS, un, backup=True, prune=True)
    if args.only in (None, "codex"):
        merge_hooks(os.path.join(HOME, ".codex", "hooks.json"), "codex", CODEX_EVENTS, un)
    if args.only in (None, "pi"):
        pi_dir = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent"))
        merge_pi(os.path.join(pi_dir, "settings.json"), un)
    print("listo. Pi: abrir una sesion nueva o ejecutar /reload en las abiertas.")
