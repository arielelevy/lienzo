"""Actualizaciones locales al arrancar, periódicas y antes de lanzar una sesión."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

import state
import subproc

INTERVAL_S = 6 * 60 * 60
RETRY_S = 15 * 60
TIMEOUT_S = 120
COMMANDS = {
    "claude": ("update",),
    "codex": ("update",),
    "pi": ("update", "--self", "--no-approve"),
    "coda": ("upgrade", "--yes"),
    "kiro": ("update",),
}


def command(exe: str, agent: str, distro: str | None) -> list[str] | str:
    argv = [exe, *COMMANDS[agent]]
    if distro and sys.platform == "win32":
        return ["wsl.exe", "-d", distro, "--exec", *argv]
    if sys.platform == "win32" and exe.lower().endswith(".cmd"):
        # cmd expande % y metacaracteres incluso con ciertas comillas: no se aceptan.
        if any(c in exe for c in '%!"&|<>^\r\n'):
            raise ValueError("ruta del harness insegura para cmd.exe")
        # Pasar texto a CreateProcess: list2cmdline sobre la lista completa escaparía
        # las comillas con barras, que cmd.exe no interpreta como escapes.
        prefix = subprocess.list2cmdline([os.environ["COMSPEC"], "/d", "/s", "/c"])
        return prefix + ' "' + subprocess.list2cmdline(argv) + '"'
    return argv


@dataclass
class Check:
    exe: str
    next_check: float = 0
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class Updater:
    def __init__(self):
        self.checks: dict[tuple[str, str | None], Check] = {}
        self.lock = threading.Lock()

    def ensure(self, agent: str, exe: str, distro: str | None = None) -> str | None:
        """Una comprobación por harness/entorno; los lanzamientos concurrentes comparten resultado."""
        with self.lock:
            check = self.checks.setdefault((agent, distro), Check(exe))
        with check.lock:
            check.exe = exe
            if time.monotonic() < check.next_check:
                return check.error
            label = f"{agent} ({distro or 'local'})"
            state.log(f"harness: comprobando actualizaciones de {label}")
            try:
                rc, out, err = subproc.correr(
                    command(exe, agent, distro),
                    timeout=TIMEOUT_S,
                    max_output=8000,
                    cwd=state.HOME,
                    env={"CLAUDECODE": "", "CLAUDE_CODE_ENTRYPOINT": ""},
                )
                detail = (out + "\n" + err).strip()
                check.error = f"{label}: actualización falló (código {rc}): {detail}" if rc else None
                state.log(f"harness: {check.error or (label + ': ' + detail)}")
            except (OSError, ValueError, KeyError) as e:
                check.error = f"{label}: no se pudo comprobar la actualización: {e}"
                state.log(f"harness: {check.error}")
            check.next_check = time.monotonic() + (RETRY_S if check.error else INTERVAL_S)
            return check.error

    def cycle(self, resolve) -> None:
        for agent in COMMANDS:
            exe = resolve(agent)
            if exe:
                self.ensure(agent, exe)
        # Entornos WSL registrados por lanzamientos: no actualizar Windows por una sesión Linux.
        with self.lock:
            remote = [(agent, distro, check.exe) for (agent, distro), check in self.checks.items() if distro]
        for agent, distro, exe in remote:
            self.ensure(agent, exe, distro)

    def loop(self, resolve, stop: threading.Event) -> None:
        while not stop.is_set():
            self.cycle(resolve)
            stop.wait(60)


_updater: Updater | None = None
_start_lock = threading.Lock()


def start(resolve) -> None:
    global _updater
    with _start_lock:
        if _updater is not None:
            return
        _updater = Updater()
        threading.Thread(
            target=_updater.loop,
            args=(resolve, threading.Event()),
            name="harness-updates",
            daemon=True,
        ).start()


def before_launch(agent: str, exe: str, distro: str | None = None) -> str | None:
    return _updater.ensure(agent, exe, distro) if _updater is not None else None
