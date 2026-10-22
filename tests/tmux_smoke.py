"""Fase 0 del port a tmux: prueba send / screen / discover del backend contra un pane real, en
WSL o Linux (python3 tests/tmux_smoke.py). No usa pytest para no depender de instalarlo. Levanta un
tmux propio con un REPL de python adentro, lo maneja por el backend, y limpia al final."""

import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))
import tmux as T

SESS = "lienzo_smoke_" + uuid.uuid4().hex[:6]
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FALLA ") + msg)
    if not cond:
        FAIL.append(msg)


def sh(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *a], capture_output=True, text=True, stdin=subprocess.DEVNULL)


try:
    check(T.available(), "tmux disponible")
    cwd = "/tmp"
    # un pane con un REPL de python interactivo y sin buffer, en un cwd conocido
    sh("new-session", "-d", "-s", SESS, "-x", "200", "-y", "50", "-c", cwd, "python3", "-i", "-u")
    time.sleep(1.2)

    # 1) DISCOVER: el pane del python aparece en list_panes, con su cwd
    pane_id = sh("display-message", "-p", "-t", SESS, "#{pane_id}").stdout.strip()
    ag = [p for p in T.list_panes() if p["target"] == pane_id and p["cwd"] == cwd]
    check(bool(ag), "list_panes encuentra el pane del python con su cwd (/tmp)")
    target = pane_id or f"{SESS}:0.0"

    # 2) SEND: el REPL ejecuta lo que se le teclea (prueba dura: escribe un archivo)
    marca = "MARCA_" + uuid.uuid4().hex[:8]
    out = f"/tmp/{SESS}.txt"
    r = T.send(target, f"open({out!r}, 'w').write({marca!r})")
    check(r.get("ok"), "send devuelve ok")
    time.sleep(1.0)
    got = ""
    if os.path.exists(out):
        with open(out) as f:
            got = f.read()
    check(got == marca, "send inyecta y el proceso del pane lo ejecuta (archivo con la marca)")

    # 3) SCREEN: capture-pane devuelve lo que se ve, incluida la linea que tecleamos
    scr = T.screen(target, scrollback=100)
    check(scr.get("ok") and marca in scr.get("text", ""), "capture-pane lee la pantalla del pane")
finally:
    sh("kill-session", "-t", SESS)
    try:
        os.remove(f"/tmp/{SESS}.txt")
    except OSError:
        pass

print("\n" + ("TODO OK — Fase 0 verde" if not FAIL else f"{len(FAIL)} FALLAS: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
