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
import json
import os
import re
import sys

# la lectura de la consola es Win32; los parsers de abajo (input_area, dialog) son texto puro y
# los usa tambien la pantalla de tmux en Mac/Linux/WSL, asi que el modulo tiene que importar ahi
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

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
    kiro = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip().startswith("› ")), None)
    if kiro is not None and any("/sessions to resume" in l or "Kiro is working" in l for l in lines[kiro:]):
        text = sin_cursor(lines[kiro])
        placeholder = text.startswith(("ask a question or describe a task", "Kiro is working"))
        return {
            "input": "" if placeholder else text,
            "placeholder": placeholder or not text,
            "queued": [],
            "status": text if text.startswith("Kiro is working") else "",
        }
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


BOX_CHARS = "│┃║|╭╮╰╯"


def _sin_borde(raw: str) -> str:
    """La linea sin el borde de un recuadro: el dialogo de confianza de Claude («Do you trust the files
    in this folder?») se dibuja adentro de uno (│ ❯ 1. Yes, proceed │) y la opcion no empezaba con el
    numero, asi que no se reconocia (medido el 2026-10-04: tres sesiones lanzadas en una carpeta sin
    confianza recibieron el encargo + Enter, eligieron «No, exit» y murieron)."""
    return raw.strip().strip(BOX_CHARS).strip()


def dialog(lines: list[str]) -> dict | None:
    """El dialogo de opciones numeradas que la TUI de Claude dibuja donde va la caja de entrada
    ("Switch model?", "Do you want to...?"). No dispara ningun hook --no es una herramienta pidiendo
    permiso-- asi que si nadie mira la pantalla la sesion se queda esperando para siempre: es el
    caso de `/model` mandado desde el lienzo, que abre el dialogo y nadie confirma.

    Devuelve {"question", "options": [{"n", "text"}], "selected"} o None. Para no confundirlo con
    una lista numerada cualquiera de la salida se piden tres cosas: dos opciones o mas, numeradas
    1..n corridas, y exactamente una con el cursor (❯ o >) adelante."""
    if kiro := _dialog_kiro(lines):
        return kiro
    run: list[tuple[int, dict]] = []
    best: list[tuple[int, dict]] = []
    for i, raw in enumerate(lines):
        m = _OPT_RE.match(_sin_borde(raw))
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
        return _dialog_de_flechas(lines)
    result = _armar(lines, best)
    if result["question"] == "Would you like to run the following command?" and any(
        "Press enter to confirm" in l for l in lines
    ):
        result["teclas"] = "flechas"
    return result


def _dialog_kiro(lines: list[str]) -> dict | None:
    """Permiso observado en Kiro V3: opciones sin numero y pie con flechas."""
    if not any("esc to close" in l and "to navigate" in l and "to select" in l for l in lines):
        return None
    question = next((i for i in range(len(lines) - 1, -1, -1) if "requires approval" in lines[i]), None)
    best = []
    for i in range(question + 1 if question is not None else 0, len(lines)):
        raw = lines[i].strip()
        selected = raw.startswith(("❯", "›", ">"))
        label = sin_cursor(raw)
        if label in ("Allow", "Always allow", "Deny", "Always deny"):
            best.append((i, {"n": len(best) + 1, "text": label, "cursor": selected}))
    if [o["text"] for _, o in best] != ["Allow", "Always allow", "Deny", "Always deny"]:
        return None
    if sum(o["cursor"] for _, o in best) != 1:
        return None
    result = _armar(lines, best, teclas="flechas")
    if question is None:
        result["question"] = "Kiro requiere permiso (comando parcialmente visible)"
        result["truncated"] = True
    return result


# como arranca la pregunta de un dialogo de la TUI (permiso de Codex o Claude, confianza, modelo)
PREGUNTA_RE = re.compile(r"^(would you like|do you want|do you trust|switch model)", re.IGNORECASE)


def _armar(lines: list[str], best: list[tuple[int, dict]], **extra) -> dict:
    top = best[0][0]

    # el cuerpo del dialogo es lo que va entre la regla horizontal de arriba y la primera opcion;
    # su primera linea es la pregunta ("Switch model?") y el resto, la explicacion
    def es_regla(l: str) -> bool:
        t = l.strip()
        return bool(t) and set(t) <= set(RULE_CHARS) | set(BOX_CHARS)

    rule = max((i for i, l in enumerate(lines[:top]) if es_regla(l)), default=-1)
    body = [_sin_borde(l) for l in lines[max(rule + 1, top - 12) : top] if _sin_borde(l)]
    # la pregunta de un permiso puede quedar mucho mas arriba de las opciones: Codex dibuja el
    # comando entero entre las dos (medido el 2026-10-08: con un `python -c` largo, la «pregunta»
    # era un pedazo del comando y el auto-aprobar no lo reconocia). Se busca hacia arriba, hasta la
    # regla o 40 lineas, la ultima linea que arranca como una pregunta de la TUI
    ventana = [_sin_borde(l) for l in lines[max(rule + 1, top - 40) : top] if _sin_borde(l)]
    idx = next((i for i in range(len(ventana) - 1, -1, -1) if PREGUNTA_RE.match(ventana[i])), None)
    if idx is not None:
        body = ventana[idx:]
    return {
        "question": body[0] if body else "",
        "detail": " ".join(body[1:])[:400],
        "options": [{"n": o["n"], "text": o["text"]} for _, o in best],
        "selected": next(o["n"] for _, o in best if o["cursor"]),
        **extra,
    }


PIE_FLECHAS = "Enter to confirm"
# «  > No, exit» / «    Yes, I trust this folder»: borde opcional, cursor opcional, el texto
_OPT_FLECHA_RE = re.compile(r"^\s*[│┃║|]?\s*(?P<cur>[>❯›])?\s*(?P<txt>\S.*)$")


def _dialog_de_flechas(lines: list[str]) -> dict | None:
    """El dialogo de opciones SIN numero que la TUI de Claude dibuja sin recuadro (el de confianza de
    una carpeta nueva desde 2.1.x: «Accessing workspace:» ... «> No, exit / Yes, I trust this folder»
    y abajo «Enter to confirm · Esc to cancel»). El numero no elige nada: se contesta con flechas y
    Enter, y por eso va `"teclas": "flechas"`. Para no confundirlo con texto cualquiera se pide el
    pie, y justo arriba (salteando blancos) un bloque de dos lineas o mas con el texto en la misma
    columna y exactamente una con el cursor adelante. Las opciones se numeran 1..k en orden (medido
    el 2026-10-04 en ar-it33940: `dialog` daba None, el encargo + Enter eligio «No, exit» y la
    sesion murio)."""
    pie = next((i for i in range(len(lines) - 1, -1, -1) if PIE_FLECHAS in lines[i]), None)
    if pie is None:
        return None
    fin = pie - 1
    while fin >= 0 and not _sin_borde(lines[fin]):
        fin -= 1
    ini = fin
    while ini - 1 >= 0 and _sin_borde(lines[ini - 1]):
        ini -= 1
    best: list[tuple[int, dict]] = []
    columnas = set()
    for i in range(ini, fin + 1):
        m = _OPT_FLECHA_RE.match(lines[i].replace(" ", " ").rstrip().rstrip(BOX_CHARS).rstrip())
        if not m:
            return None
        columnas.add(m.start("txt"))
        best.append((i, {"n": len(best) + 1, "text": m.group("txt"), "cursor": bool(m.group("cur"))}))
    if len(best) < 2 or len(columnas) != 1 or sum(1 for _, o in best if o["cursor"]) != 1:
        return None
    return _armar(lines, best, teclas="flechas")


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
