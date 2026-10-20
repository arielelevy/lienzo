"""Actualización explícita por PC; prepara y compila antes de avanzar el checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import tomllib
import uuid
from pathlib import Path

import state


class UpdateError(Exception):
    pass


class Updater:
    def __init__(self, root, journal, restart, supervised):
        self.root = Path(root)
        self.journal = Path(journal)
        self.restart = restart
        self.supervised = supervised
        self.lock = threading.RLock()
        self.busy = False
        self.data = {"phase": "idle", "available": False, "checked_at": None, "changes": []}
        self.running = self.git("rev-parse", "HEAD")
        if self.journal.exists():
            saved = json.loads(self.journal.read_text(encoding="utf-8"))
            if saved.get("phase") == "restarting" and saved.get("target") == self.running:
                self.data.update(saved, phase="applied", available=False, head=self.running,
                                 message="Actualización aplicada")
            elif saved.get("phase") not in ("idle", "applied", "error"):
                self.data.update(phase="error", error="La actualización anterior se interrumpió; revisá el checkout")

    def run(self, args, *, cwd=None, timeout=60):
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"}
        result = subprocess.run(args, cwd=cwd or self.root, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            # No publicar stderr de git/npm: puede incluir credenciales en URLs del remoto.
            raise UpdateError(f"Falló {Path(args[0]).name} (código {result.returncode})")
        return result.stdout.strip()

    def git(self, *args):
        return self.run(["git", *args])

    def snapshot(self):
        with self.lock:
            data = json.loads(json.dumps(self.data))
            data.update(running=self.running, supervised=self.supervised, busy=self.busy)
            return data

    def set(self, **data):
        with self.lock:
            self.data.update(data)
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            temp = self.journal.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.journal)

    def inspect(self):
        branch = self.git("branch", "--show-current")
        upstream = self.git("rev-parse", "--abbrev-ref", "@{upstream}")
        if branch != "main" or upstream != "origin/main":
            raise UpdateError("La actualización requiere main siguiendo origin/main")
        dirty = bool(self.git("status", "--porcelain"))
        self.git("fetch", "--no-tags", "origin", "main:refs/remotes/origin/main")
        head, target = self.git("rev-parse", "HEAD"), self.git("rev-parse", "refs/remotes/origin/main")
        ahead, behind = map(int, self.git("rev-list", "--left-right", "--count", f"{head}...{target}").split())
        package = json.loads(self.git("show", f"{target}:web/package.json"))
        changes = self.git("log", "-15", "--format=%h %s", f"{self.running}..{target}").splitlines()
        blocked = ("Hay cambios locales; guardalos en Git antes de actualizar" if dirty else
                   "La rama tiene commits propios; requiere revisión" if ahead else
                   "El servidor necesita arrancar con lienzo-server.cmd para aplicar la actualización" if not self.supervised else "")
        return {"head": head, "target": target, "available": behind > 0 or head != self.running, "ahead": ahead,
                "behind": behind, "blocked": blocked, "version": package["version"],
                "changes": changes, "checked_at": time.time()}

    def submit(self, action, target=None):
        with self.lock:
            if self.busy:
                return 409, {"error": "Ya hay una consulta o actualización en curso"}
            if action == "apply":
                if not self.supervised:
                    return 409, {"error": "Arrancá Lienzo con lienzo-server.cmd para poder recargarlo"}
                if not self.data.get("available") or target != self.data.get("target"):
                    return 409, {"error": "Consultá las novedades antes de actualizar"}
                if self.data.get("blocked"):
                    return 409, {"error": self.data["blocked"]}
            self.busy = True
            try:
                self.set(phase="checking" if action == "check" else "preparing", error=None, message=None)
                threading.Thread(target=self.worker, args=(action, target), daemon=True, name="lienzo-update").start()
            except (OSError, RuntimeError):
                self.busy = False
                self.data.update(phase="error", error="No se pudo registrar o iniciar la actualización")
                return 503, {"error": self.data["error"]}
            return 202, self.snapshot()

    def worker(self, action, target):
        try:
            info = self.inspect()
            self.set(**info)
            if action == "check":
                self.set(phase="available" if info["available"] else "current")
            else:
                if info["target"] != target or not info["available"] or info["blocked"]:
                    raise UpdateError(info["blocked"] or "La versión cambió; consultá nuevamente")
                self.apply(info)
        except Exception as exc:
            message = str(exc) if isinstance(exc, UpdateError) else f"No se pudo actualizar ({type(exc).__name__})"
            self.set(phase="error", error=message)
        finally:
            with self.lock:
                self.busy = False

    def prepare(self, folder):
        project = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        current = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        if project.get("requires-python") != current.get("requires-python"):
            raise UpdateError("La nueva versión cambia el requisito de Python; requiere instalación revisada")
        if project.get("dependencies"):
            raise UpdateError("La nueva versión agrega dependencias Python; requiere instalación revisada")
        for path in (folder / "lienzo").rglob("*.py"):
            compile(path.read_bytes(), str(path), "exec")
        self.set(phase="building", message="Preparando la interfaz antes de aplicar")
        for script in ("npm.cmd ci --ignore-scripts --no-audit --no-fund", "npm.cmd run build"):
            command = [os.environ["COMSPEC"], "/d", "/c", script] if os.name == "nt" else script.replace("npm.cmd", "npm").split()
            self.run(command, cwd=folder / "web", timeout=300)
        if not (folder / "web/dist/index.html").is_file():
            raise UpdateError("La compilación no produjo una interfaz")

    def publish(self, folder):
        source, dest = folder / "web/dist", self.root / "web/dist"
        dest.mkdir(parents=True, exist_ok=True)
        # Conservar assets viejos para pestañas abiertas; publicar index al final.
        for path in source.iterdir():
            if path.name == "index.html":
                continue
            if path.is_dir():
                shutil.copytree(path, dest / path.name, dirs_exist_ok=True)
            else:
                shutil.copy2(path, dest / path.name)
        temp = dest / "index.update.html"
        shutil.copy2(source / "index.html", temp)
        temp.replace(dest / "index.html")

    def apply(self, info):
        self.set(**info)
        folder = (self.root / ".temp/updates" / uuid.uuid4().hex).resolve()
        if not folder.is_relative_to(self.root.resolve()) or folder.parent.name != "updates":
            raise UpdateError("La carpeta de preparación queda fuera del repositorio")
        folder.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "--detach", str(folder), info["target"])
        try:
            self.prepare(folder)
            if self.git("status", "--porcelain") or self.git("rev-parse", "HEAD") != info["head"]:
                raise UpdateError("El checkout cambió durante la preparación; no se aplicó")
            self.set(phase="applying", message="Aplicando la versión preparada")
            self.git("merge", "--ff-only", info["target"])
            self.publish(folder)
        finally:
            self.git("worktree", "remove", "--force", str(folder))
        self.set(phase="restarting", available=False, message="Reconectando Lienzo; las terminales siguen abiertas")
        code, result = self.restart()
        if code != 202:
            raise UpdateError(result.get("error", "No se pudo recargar el servidor"))


SERVICE = None


def start(restart):
    global SERVICE
    SERVICE = Updater(state.ROOT, Path(state.LIENZO) / "update.json", restart,
                      os.environ.get("LIENZO_RELOAD") == "1")

    def poll():
        while True:
            SERVICE.submit("check")
            time.sleep(300)

    threading.Thread(target=poll, daemon=True, name="lienzo-update-check").start()


def dispatch(method, action, data=None):
    if SERVICE is None:
        return 503, {"error": "El actualizador no está iniciado"}
    if method == "GET" and not action:
        return 200, SERVICE.snapshot()
    if method == "POST" and action in ("check", "apply"):
        return SERVICE.submit(action, (data or {}).get("target"))
    return 404, {"error": "ruta desconocida"}
