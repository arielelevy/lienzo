#!/usr/bin/env python
"""Instala (o desinstala) los hooks del lienzo en Claude Code, Codex, Pi y CODA.

    python install.py            # hooks en ~/.claude/settings.json, ~/.codex/hooks.json y ~/.coda/config.json; extension de Pi
    python install.py --uninstall

Hace merge, nunca pisa: guarda ~/.claude/settings.json.bak-<fecha> antes de tocar.
Los hooks apuntan a D:/Apps/lienzo/lienzo/hook.py (este repo), sin copiar nada a ~/.lienzo/bin.
"""

import argparse
import ctypes
import datetime
import json
import os
import shutil
import subprocess
import sys

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
HOOK = f"{HERE}/lienzo/hook.py"

# El mismo interprete con el que se instala; ejecutar con py -3.14.
PY = sys.executable.replace("\\", "/")

# LIENZO_HOME (plan multi-PC §F0): si estaba definida al instalar, el hook la necesita explicita
# en su propio comando, porque el proceso que despues lo dispara (Claude Code, Codex, CODA) no
# hereda el entorno de esta instalacion.
LIENZO_HOME = os.environ.get("LIENZO_HOME")

CLAUDE_EVENTS = {
    "SessionStart": (True, 5),
    "UserPromptSubmit": (True, 5),
    "Stop": (True, 5),
    "Notification": (True, 5),
    "PermissionRequest": (False, 90),
    "SessionEnd": (False, 2),
}
# Codex sin async: en Windows envuelve el hook en `pwsh -Command`, y el async lo lanza sin consola,
# asi que Windows Terminal le abre una ventana por turno (BUG-ventanas-pwsh-hooks-codex.md). El
# hook solo escribe un archivo en ~/.lienzo/events y no habla con el server: correrlo sincronico
# cuesta el arranque de python, no el timeout.
CODEX_EVENTS = {
    "SessionStart": (False, 5),
    "UserPromptSubmit": (False, 5),
    "Stop": (False, 5),
    "PermissionRequest": (False, 90),
    "SessionEnd": (False, 2),
    "Interrupt": (False, 2),
}
# CODA no tiene PermissionRequest ni Notification: su PreToolUse corre antes de toda herramienta,
# sin saber si el motor de permisos va a preguntar, asi que no sirve para pedir permiso desde aca.
# Va igual, async, porque es lo unico que dice que hace durante el turno: CODA escribe el turno en
# su base recien al cerrarlo.
CODA_EVENTS = {
    "SessionStart": (True, 5),
    "UserPromptSubmit": (True, 5),
    # sincronico: con auto-aprobar prendido, su respuesta decide el permiso (hook.py); sin el check
    # no imprime nada y coda sigue como siempre. Cuesta el arranque de python por herramienta
    "PreToolUse": (False, 5),
    # coda compacta el contexto en medio de un turno y el Stop llega igual: PreCompact/PostCompact
    # dejan marcada la compactacion para que no cuente como fin de turno (doc de coda, hooks.md)
    "PreCompact": (True, 5),
    "PostCompact": (True, 5),
    "Stop": (True, 5),
    "SessionEnd": (False, 2),
}


def cmd(agent: str) -> str:
    # Sin comillas si la ruta no tiene espacios: Codex puede correr el hook por PowerShell,
    # y en PowerShell una linea que empieza con un string entre comillas no se ejecuta.
    py = f'"{PY}"' if " " in PY else PY
    extra = f' --lienzo-home "{LIENZO_HOME}"' if LIENZO_HOME else ""
    return f"{py} {HOOK} {agent}{extra}"


def is_ours(group: dict) -> bool:
    return any(
        "lienzo" in " ".join([h.get("command") or "", *map(str, h.get("args") or [])]) for h in group.get("hooks", [])
    )


def entry(agent: str, asyn: bool, timeout: int) -> dict:
    if agent == "coda":
        # forma exec: CODA lanza el interprete con estos argumentos, sin shell de por medio (el
        # default de la forma shell es `sh -c`, que en Windows no esta garantizado)
        args = [HOOK, agent]
        if LIENZO_HOME:
            args += ["--lienzo-home", LIENZO_HOME]
        e = {"type": "command", "command": PY, "args": args, "timeout": timeout}
    else:
        e = {"type": "command", "command": cmd(agent), "timeout": timeout}
    if asyn:
        e["async"] = True
    return {"hooks": [e]}


def merge_hooks(path: str, agent: str, events: dict, uninstall: bool, backup=False, prune=False, dry_run=False) -> None:
    """Registra (o saca) los hooks del lienzo en un archivo de configuracion sin pisar lo que ya
    hay: de cada evento se filtran solo los grupos propios (is_ours) y se vuelve a agregar el
    nuestro. `backup` guarda una copia antes de tocar, para el settings.json de Claude, que ademas
    de hooks tiene todo lo del usuario; `prune` saca la clave "hooks" entera si queda vacia.
    `dry_run` no escribe nada: solo dice que haria."""
    accion = "quitarian" if uninstall else "registrarian"
    if dry_run:
        print(f"[dry-run] se {accion} los hooks de {agent.capitalize()} en {path} (eventos: {', '.join(events)})")
        return
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


def merge_pi(path: str, uninstall: bool, dry_run=False) -> None:
    """Registra la extension por ruta absoluta sin tocar otras extensiones ni settings."""
    if uninstall and not os.path.exists(path):
        return
    if dry_run:
        print(f"[dry-run] se {'quitaria' if uninstall else 'registraria'} la extension Pi en {path}")
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


def ensure_state(dry_run=False) -> None:
    root = os.path.join(HOME, ".lienzo")
    if dry_run:
        print(f"[dry-run] se crearian las carpetas de estado y config.json en {root}")
        return
    for d in ("events", "pending", "answers", "adjuntos", "sessions"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    cfg = os.path.join(root, "config.json")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"ejemplos": f"{HERE}/ejemplos", "wait": 60}, f, indent=2)
    print("estado en", root)


# --- firewall para el emparejamiento entre PCs (plan multi-PC §3.2) --------------------------

FIREWALL_RULES = (
    ("Lienzo Peer TCP", "TCP", 7322),
    ("Lienzo Beacon UDP", "UDP", 7323),
)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def firewall_args(nombre: str, proto: str, puerto: int, uninstall: bool) -> list:
    if uninstall:
        return ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={nombre}"]
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={nombre}",
        "dir=in",
        "action=allow",
        f"protocol={proto}",
        f"localport={puerto}",
        "profile=private",
    ]


def peer_firewall(uninstall: bool, dry_run=False) -> None:
    """Regla de firewall de Windows para el listener de peers (7322 TCP) y el beacon (7323 UDP),
    solo en el perfil Privado (plan multi-PC §3.2): en una red publica el puerto no escucha. Sin
    permisos de administrador no se puede escribir una regla de firewall: se avisa claro y se sale
    sin tocar nada mas de la instalacion."""
    if not dry_run and not is_admin():
        print("regla de firewall para el emparejamiento: hace falta ser administrador, no se toco nada")
        return
    for nombre, proto, puerto in FIREWALL_RULES:
        args = firewall_args(nombre, proto, puerto, uninstall)
        if dry_run:
            print("[dry-run]", " ".join(args))
            continue
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"regla de firewall {nombre} fallo:", (r.stderr or r.stdout).strip())
        else:
            print(("quitada" if uninstall else "agregada"), "regla de firewall", nombre)


if __name__ == "__main__":
    if sys.version_info < (3, 14):  # noqa: UP036 -- instalador ejecutable antes de instalar el proyecto
        raise SystemExit("Lienzo requiere Python 3.14 o posterior. Usá: py -3.14 install.py")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--peer", action="store_true", help="regla de firewall (7322 TCP, 7323 UDP, perfil Privado) para emparejar PCs"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="imprime lo que haria (hooks y firewall), sin escribir nada"
    )
    only = parser.add_mutually_exclusive_group()
    for agent in ("claude", "codex", "pi", "coda"):
        only.add_argument(f"--{agent}-only", dest="only", action="store_const", const=agent)
    args = parser.parse_args()
    un = args.uninstall
    dry = args.dry_run
    print("python para el hook:", PY)
    ensure_state(dry_run=dry)
    if args.only in (None, "claude"):
        settings = os.path.join(HOME, ".claude", "settings.json")
        merge_hooks(settings, "claude", CLAUDE_EVENTS, un, backup=True, prune=True, dry_run=dry)
    if args.only in (None, "codex"):
        merge_hooks(os.path.join(HOME, ".codex", "hooks.json"), "codex", CODEX_EVENTS, un, dry_run=dry)
    if args.only in (None, "pi"):
        pi_dir = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent"))
        merge_pi(os.path.join(pi_dir, "settings.json"), un, dry_run=dry)
    if args.only in (None, "coda"):
        coda_home = os.environ.get("CODA_HOME") or os.path.join(HOME, ".coda")
        if os.path.isdir(coda_home):
            merge_hooks(
                os.path.join(coda_home, "config.json"), "coda", CODA_EVENTS, un, backup=True, prune=True, dry_run=dry
            )
    if args.peer:
        peer_firewall(un, dry_run=dry)
    print("listo. Pi: abrir una sesion nueva o ejecutar /reload en las abiertas. CODA: /reload-hooks en las abiertas.")
