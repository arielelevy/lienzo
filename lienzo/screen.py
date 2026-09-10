#!/usr/bin/env python
"""lienzo-screen: lee el texto visible de la consola de un agente por PID (AttachConsole +
ReadConsoleOutputCharacterW sobre CONOUT$). Es la unica excepcion a "no raspar la pantalla"
(DISENO §10) y existe para lo que la TUI de Claude Code muestra y no queda en ningun archivo ni
hook: las sugerencias de prompt, y los dialogos de opciones numeradas ("Switch model?"), que no
son un pedido de permiso y por eso no los ve nadie desde afuera.

    python screen.py --pid N            # imprime la pantalla
    python screen.py --pid N --json     # {"ok":true,"cols":..,"rows":..,"lines":[...]}
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procs

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


class COORD(ctypes.Structure):
    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wt.SHORT), ("Top", wt.SHORT), ("Right", wt.SHORT), ("Bottom", wt.SHORT)]


class CSBI(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wt.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


k32.AttachConsole.argtypes = [wt.DWORD]
k32.AttachConsole.restype = wt.BOOL
k32.FreeConsole.restype = wt.BOOL
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
k32.GetConsoleScreenBufferInfo.argtypes = [wt.HANDLE, ctypes.POINTER(CSBI)]
k32.GetConsoleScreenBufferInfo.restype = wt.BOOL
k32.ReadConsoleOutputCharacterW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, COORD, ctypes.POINTER(wt.DWORD)]
k32.ReadConsoleOutputCharacterW.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]


def read_screen(pid: int, whole_buffer: bool = False) -> dict:
    if not procs.agent_alive(pid):
        return {"ok": False, "pid": pid, "error": "el proceso no existe"}
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        return {"ok": False, "pid": pid, "error": f"AttachConsole fallo (error {ctypes.get_last_error()})"}
    try:
        h = k32.CreateFileW(
            "CONOUT$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
        )
        if h == INVALID_HANDLE_VALUE or not h:
            return {"ok": False, "pid": pid, "error": f"no pude abrir CONOUT$ (error {ctypes.get_last_error()})"}
        try:
            info = CSBI()
            if not k32.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
                return {
                    "ok": False,
                    "pid": pid,
                    "error": f"GetConsoleScreenBufferInfo fallo (error {ctypes.get_last_error()})",
                }
            cols = info.dwSize.X
            top, bottom = (0, info.dwSize.Y - 1) if whole_buffer else (info.srWindow.Top, info.srWindow.Bottom)
            lines = []
            buf = ctypes.create_unicode_buffer(cols + 1)
            for y in range(top, bottom + 1):
                got = wt.DWORD(0)
                if k32.ReadConsoleOutputCharacterW(h, buf, cols, COORD(0, y), ctypes.byref(got)):
                    lines.append(buf.value[: got.value].rstrip())
                else:
                    lines.append("")
            return {
                "ok": True,
                "pid": pid,
                "cols": cols,
                "rows": len(lines),
                "buffer_rows": info.dwSize.Y,
                "cursor": [info.dwCursorPosition.X, info.dwCursorPosition.Y],
                "lines": lines,
            }
        finally:
            k32.CloseHandle(h)
    finally:
        k32.FreeConsole()


PLACEHOLDERS = ("Press up to edit queued messages", 'Try "', 'Try "', "Type a message", "? for shortcuts")
# el simbolo del cursor de la caja de entrada. Segun la version y la fuente, el buffer de consola
# lo devuelve como ❯ o como > pelado, y lo que sigue puede ser un espacio duro
PROMPT_CHARS = ("❯", ">", "›")
# la raya que abre y cierra la caja de entrada. Claude Code 2.1.267 la dibuja con medio bloque
# (▔) y las versiones anteriores con guion de caja (─): valen las dos
RULE_CHARS = ("─", "━", "═", "▔", "▁", "▄", "▀")


def sin_cursor(line: str) -> str:
    """La linea de la caja sin el simbolo del cursor. Sin esto una caja vacia se lee como ">" y el
    lienzo la toma por texto tipeado: la tarjeta decia "estan tipeando en esa terminal" en toda
    sesion ocupada (medido el 2026-09-09: 4 de 4 sesiones corriendo)."""
    s = line.lstrip().replace(" ", " ")
    if s[:1] in PROMPT_CHARS:
        s = s[1:]
    return s.strip()


def input_area(lines: list[str]) -> dict:
    """Caja de entrada de la TUI de Claude Code: las lineas entre las dos reglas horizontales.
    Devuelve el texto de la caja y las lineas '❯ ...' encoladas arriba de ella.
    Las sugerencias de prompt aparecen en esa zona; el server decide si son sugerencia o
    placeholder con PLACEHOLDERS."""
    rules = [i for i, l in enumerate(lines) if l.strip() and set(l.strip()) <= set(RULE_CHARS)]
    box, queued = [], []
    if len(rules) >= 2:
        top, bottom = rules[-2], rules[-1]
        box = [l.strip() for l in lines[top + 1 : bottom] if l.strip()]
        for l in lines[:top]:
            s = l.strip()
            if s.startswith("❯ ") and not any(p in s for p in PLACEHOLDERS):
                queued.append(s[2:].strip())
    text = " ".join(sin_cursor(b) for b in box).strip()
    is_placeholder = any(p in text for p in PLACEHOLDERS) or not text
    return {
        "input": text,
        "placeholder": is_placeholder,
        "queued": queued,
        "status": (lines[-1].strip() if lines else ""),
    }


# "❯ 1. Yes, switch to Opus 5" / "  2. No, go back": una opcion del menu, con o sin el cursor
_OPT_RE = re.compile(r"^(?P<cur>[>❯›])?\s*(?P<n>\d{1,2})\.\s+(?P<txt>\S.*)$")


def dialog(lines: list[str]) -> dict | None:
    """El dialogo de opciones numeradas que la TUI de Claude dibuja donde va la caja de entrada
    ("Switch model?", "Do you want to...?"). No dispara ningun hook --no es una herramienta pidiendo
    permiso-- asi que si nadie mira la pantalla la sesion se queda esperando para siempre: es el
    caso de `/model` mandado desde el lienzo, que abre el dialogo y nadie confirma.

    Devuelve {"question", "options": [{"n", "text"}], "selected"} o None. Para no confundirlo con
    una lista numerada cualquiera de la salida se piden tres cosas: dos opciones o mas, numeradas
    1..n corridas, y exactamente una con el cursor (❯ o >) adelante."""
    run: list[tuple[int, dict]] = []
    best: list[tuple[int, dict]] = []
    for i, raw in enumerate(lines):
        m = _OPT_RE.match(raw.strip())
        if m and int(m.group("n")) == len(run) + 1:
            run.append((i, {"n": int(m.group("n")), "text": m.group("txt").strip(), "cursor": bool(m.group("cur"))}))
            continue
        if len(run) >= 2:
            best = run
        run = (
            []
            if not m or int(m.group("n")) != 1
            else [(i, {"n": 1, "text": m.group("txt").strip(), "cursor": bool(m.group("cur"))})]
        )
    if len(run) >= 2:
        best = run
    if len(best) < 2 or sum(1 for _, o in best if o["cursor"]) != 1:
        return None
    top = best[0][0]
    # el cuerpo del dialogo es lo que va entre la regla horizontal de arriba y la primera opcion;
    # su primera linea es la pregunta ("Switch model?") y el resto, la explicacion
    rule = max((i for i, l in enumerate(lines[:top]) if l.strip() and set(l.strip()) <= set(RULE_CHARS)), default=-1)
    body = [l.strip() for l in lines[max(rule + 1, top - 12) : top] if l.strip()]
    return {
        "question": body[0] if body else "",
        "detail": " ".join(body[1:])[:400],
        "options": [{"n": o["n"], "text": o["text"]} for _, o in best],
        "selected": next(o["n"] for _, o in best if o["cursor"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="lienzo-screen")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="todo el buffer, no solo la ventana visible")
    a = ap.parse_args()
    r = read_screen(a.pid, a.all)
    if r.get("ok"):
        r["area"] = input_area(r["lines"])
        r["dialog"] = dialog(r["lines"])
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    elif r.get("ok"):
        print(f"--- {r['cols']}x{r['rows']} (buffer {r['buffer_rows']} filas, cursor {r['cursor']}) ---")
        for i, l in enumerate(r["lines"]):
            print(f"{i:3d}| {l}")
    else:
        print(r["error"])
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
