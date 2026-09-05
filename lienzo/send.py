#!/usr/bin/env python
"""lienzo-send: inyecta texto + Enter en la consola de un agente (claude.exe / codex.exe)
por PID, con AttachConsole + WriteConsoleInputW. Generaliza codex-inject.py (§6.2).

    python send.py --pid N --text "decime hola" [--no-enter] [--enter-presses 1]
                   [--key-delay 0.3] [--chunk 200] [--chunk-delay 0.05]

Imprime un JSON en stdout: {"ok": true, "pid": N, "chars": 42} o {"ok": false, "error": "..."}.
El server lo lanza como subproceso DETACHED (sin consola propia) por cada envio.
Saltos de linea se colapsan a espacio (v1): el texto largo va como adjunto (§6.5).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procs  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

KEY_EVENT = 0x0001
SHIFT_PRESSED = 0x0010
LEFT_CTRL_PRESSED = 0x0008
LEFT_ALT_PRESSED = 0x0002
VK_RETURN = 0x0D
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


class _Char(ctypes.Union):
    _fields_ = [("UnicodeChar", wt.WCHAR), ("AsciiChar", ctypes.c_char)]


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wt.BOOL), ("wRepeatCount", wt.WORD), ("wVirtualKeyCode", wt.WORD),
                ("wVirtualScanCode", wt.WORD), ("uChar", _Char), ("dwControlKeyState", wt.DWORD)]


class _Event(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wt.WORD), ("Event", _Event)]


k32.AttachConsole.argtypes = [wt.DWORD]
k32.AttachConsole.restype = wt.BOOL
k32.FreeConsole.restype = wt.BOOL
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
k32.WriteConsoleInputW.argtypes = [wt.HANDLE, ctypes.POINTER(INPUT_RECORD), wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.WriteConsoleInputW.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]
u32.VkKeyScanW.argtypes = [wt.WCHAR]
u32.VkKeyScanW.restype = ctypes.c_short
u32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
u32.MapVirtualKeyW.restype = wt.UINT


def key_records(text: str, shift_enter: bool = False) -> list[INPUT_RECORD]:
    recs: list[INPUT_RECORD] = []

    def push(vk: int, ch: str, state: int) -> None:
        scan = u32.MapVirtualKeyW(vk, 0) if vk else 0
        for down in (True, False):
            r = INPUT_RECORD()
            r.EventType = KEY_EVENT
            k = r.Event.KeyEvent
            k.bKeyDown = down
            k.wRepeatCount = 1
            k.wVirtualKeyCode = vk
            k.wVirtualScanCode = scan
            k.uChar.UnicodeChar = ch
            k.dwControlKeyState = state
            recs.append(r)

    for ch in text:
        if ch in ("\r", "\n"):
            push(VK_RETURN, "\r", SHIFT_PRESSED if shift_enter else 0)
            continue
        res = u32.VkKeyScanW(ch)
        if res == -1:
            push(0, ch, 0)
            continue
        vk = res & 0xFF
        mods = (res >> 8) & 0xFF
        state = 0
        if mods & 1:
            state |= SHIFT_PRESSED
        if mods & 2:
            state |= LEFT_CTRL_PRESSED
        if mods & 4:
            state |= LEFT_ALT_PRESSED
        push(vk, ch, state)
    return recs


def inject(pid: int, text: str, enter_presses: int = 1, key_delay: float = 0.3,
           chunk: int = 200, chunk_delay: float = 0.05) -> dict:
    if not procs.alive(pid):
        return {"ok": False, "pid": pid, "error": "el proceso no existe"}
    if not procs.is_tui(pid):
        return {"ok": False, "pid": pid, "error": "el PID no es una TUI de claude.exe/codex.exe"}

    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        return {"ok": False, "pid": pid, "error": f"AttachConsole fallo (error {ctypes.get_last_error()})"}
    try:
        hin = k32.CreateFileW("CONIN$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              None, OPEN_EXISTING, 0, None)
        if hin == INVALID_HANDLE_VALUE or not hin:
            return {"ok": False, "pid": pid, "error": f"no pude abrir CONIN$ (error {ctypes.get_last_error()})"}
        try:
            def write(recs: list[INPUT_RECORD]) -> str | None:
                arr = (INPUT_RECORD * len(recs))(*recs)
                written = wt.DWORD(0)
                ok = k32.WriteConsoleInputW(hin, arr, len(recs), ctypes.byref(written))
                if not ok or written.value != len(recs):
                    return f"WriteConsoleInputW fallo (error {ctypes.get_last_error()}, {written.value}/{len(recs)})"
                return None

            for i in range(0, len(text), chunk):
                err = write(key_records(text[i:i + chunk]))
                if err:
                    return {"ok": False, "pid": pid, "error": err}
                time.sleep(chunk_delay)
            if enter_presses > 0:
                time.sleep(key_delay)
                for _ in range(enter_presses):
                    err = write(key_records("\r"))
                    if err:
                        return {"ok": False, "pid": pid, "error": err}
                    time.sleep(key_delay)
            return {"ok": True, "pid": pid, "chars": len(text), "enter": enter_presses}
        finally:
            k32.CloseHandle(hin)
    finally:
        k32.FreeConsole()


def main() -> int:
    p = argparse.ArgumentParser(prog="lienzo-send")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--text", default=None)
    p.add_argument("--text-file", default=None, help="leer el texto de un archivo utf-8")
    p.add_argument("--enter-presses", type=int, default=1)
    p.add_argument("--no-enter", action="store_true")
    p.add_argument("--key-delay", type=float, default=0.3)
    p.add_argument("--chunk", type=int, default=200)
    p.add_argument("--chunk-delay", type=float, default=0.05)
    p.add_argument("--keep-newlines", action="store_true", help="mandar Enter por cada salto (prueba T5)")
    a = p.parse_args()
    text = a.text
    if a.text_file:
        with open(a.text_file, encoding="utf-8") as f:
            text = f.read()
    if text is None:
        print(json.dumps({"ok": False, "error": "falta --text o --text-file"}))
        return 2
    if not a.keep_newlines:
        text = " ".join(text.replace("\r", "").split("\n")).strip()
    res = inject(a.pid, text, 0 if a.no_enter else a.enter_presses, a.key_delay, a.chunk, a.chunk_delay)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
