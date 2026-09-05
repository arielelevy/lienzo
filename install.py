#!/usr/bin/env python
"""Instala (o desinstala) los hooks del lienzo en Claude Code y Codex.

    python install.py            # registra hooks en ~/.claude/settings.json y ~/.codex/hooks.json
    python install.py --uninstall

Hace merge, nunca pisa: guarda ~/.claude/settings.json.bak-<fecha> antes de tocar.
Los hooks apuntan a D:/Apps/lienzo/lienzo/hook.py (este repo), sin copiar nada a ~/.lienzo/bin.
"""
import datetime
import json
import os
import shutil
import sys

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
HOOK = f"{HERE}/lienzo/hook.py"

CANDIDATES = [
    os.path.join(HOME, r"AppData\Local\Python\pythoncore-3.14-64\python.exe"),   # ~200 ms de arranque
    os.path.join(HOME, r"AppData\Local\Python\bin\python.exe"),
    sys.executable,                                                             # el de la Store, ~300 ms
]
PY = next((p for p in CANDIDATES if p and os.path.exists(p)), "python").replace("\\", "/")

CLAUDE_EVENTS = {"SessionStart": (True, 5), "UserPromptSubmit": (True, 5), "Stop": (True, 5),
                 "Notification": (True, 5), "PermissionRequest": (False, 90), "SessionEnd": (False, 2)}
CODEX_EVENTS = {"SessionStart": (True, 5), "UserPromptSubmit": (True, 5), "Stop": (True, 5),
                "PermissionRequest": (False, 90), "SessionEnd": (False, 2), "Interrupt": (False, 2)}


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


def install_claude(uninstall: bool) -> None:
    path = os.path.join(HOME, ".claude", "settings.json")
    settings = {}
    if os.path.exists(path):
        bak = path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, bak)
        print("backup:", bak)
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    hooks = settings.setdefault("hooks", {})
    for ev, (asyn, to) in CLAUDE_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not is_ours(g)]
        if not uninstall:
            groups.append(entry("claude", asyn, to))
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)
    if not hooks:
        settings.pop("hooks", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(("quitados" if uninstall else "registrados"), "hooks de Claude en", path)


def install_codex(uninstall: bool) -> None:
    path = os.path.join(HOME, ".codex", "hooks.json")
    data = {"hooks": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    hooks = data.setdefault("hooks", {})
    for ev, (asyn, to) in CODEX_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not is_ours(g)]
        if not uninstall:
            groups.append(entry("codex", asyn, to))
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(("quitados" if uninstall else "registrados"), "hooks de Codex en", path)


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
    un = "--uninstall" in sys.argv
    print("python para el hook:", PY)
    ensure_state()
    if "--codex-only" not in sys.argv:
        install_claude(un)
    if "--claude-only" not in sys.argv:
        install_codex(un)
    print("listo. Las sesiones nuevas de Claude/Codex ya reportan; las abiertas antes las encuentra el barrido.")
