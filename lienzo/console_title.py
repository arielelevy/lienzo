"""Leer/cambiar el título de una consola Windows por PID, sin eventos de teclado."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys

import procinfo


def update(pid: int, agent: str, title: str | None) -> dict:
    if sys.platform != "win32":
        return {"ok": False, "error": "esta operación requiere Windows"}
    if procinfo.process_agent(pid) != agent:
        return {"ok": False, "error": "el PID ya no pertenece al agente esperado"}
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.AttachConsole.argtypes, k32.AttachConsole.restype = [wt.DWORD], wt.BOOL
    k32.FreeConsole.restype = wt.BOOL
    k32.GetConsoleTitleW.argtypes, k32.GetConsoleTitleW.restype = [wt.LPWSTR, wt.DWORD], wt.DWORD
    k32.SetConsoleTitleW.argtypes, k32.SetConsoleTitleW.restype = [wt.LPCWSTR], wt.BOOL
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        return {"ok": False, "error": str(ctypes.WinError(ctypes.get_last_error()))}
    try:
        before = ctypes.create_unicode_buffer(32768)
        k32.GetConsoleTitleW(before, len(before))
        if title is None:
            return {"ok": True, "pid": pid, "changed": False, "title": before.value}
        changed = before.value != title
        if changed and not k32.SetConsoleTitleW(title):
            raise ctypes.WinError(ctypes.get_last_error())
        after = ctypes.create_unicode_buffer(32768)
        k32.GetConsoleTitleW(after, len(after))
        if after.value != title:
            return {"ok": False, "error": "la consola no conservó el título solicitado", "title": after.value}
        return {"ok": True, "pid": pid, "changed": changed, "title": after.value}
    except OSError as e:
        return {"ok": False, "error": str(e)}
    finally:
        k32.FreeConsole()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--agent", required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--title")
    operation.add_argument("--read", action="store_true")
    args = parser.parse_args()
    result = update(args.pid, args.agent, args.title)
    print(json.dumps(result))  # ASCII JSON: estable aunque AttachConsole cambie la página de códigos
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
