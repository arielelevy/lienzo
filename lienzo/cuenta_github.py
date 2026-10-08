"""Cuenta de GitHub por repo (pedido de Ariel, 2026-10-08).

`gh` guarda varias cuentas de github.com, pero su credential helper (`gh auth git-credential`) solo
sirve la ACTIVA, aunque git le pase el usuario. Medido con gh 2.81 el 2026-10-08: con la activa en
ariel-levy_globant, `git push` a arielelevy/lienzo daba «Permission denied ... 403», y pedirle a gh
la credencial de arielelevy no devolvia nada. Cambiar la cuenta activa (`gh auth switch`) es global
a la PC: dos sesiones vivas en repos de cuentas distintas se pisarian.

Entonces cada repo con `origin` en github.com queda FIJADO, en su propio .git/config, a la cuenta
que tiene permiso de push sobre ese repo: un helper de git que, cuando git lo pide, saca el token
de esa cuenta con `gh auth token --user <cuenta>` (eso si sirve cuentas inactivas). El token no se
guarda en ningun lado ni pasa por el lienzo: lo pide git al momento de usarlo. Cambiar la cuenta
activa de gh ya no afecta a ese repo, y un GH_TOKEN heredado del entorno tampoco (se vacia al
consultar a gh y adentro del helper: con uno puesto, gh lo devuelve para cualquier --user).

Que cuenta: primero la que se llama como el dueño del repo (github.com/<dueño>/...), despues la
activa, despues el resto; gana la primera con `permissions.push` en `gh api repos/<dueño>/<repo>`.
Sin red no se decide nada (no se toca el repo).

Lo corre health.py en cada medicion de git_auth para los repos con sesion viva (todos los que
tengan ese origin, no solo uno), y de nuevo (`forzar`) cuando el ls-remote dio «vencida»: un 403
por cuenta equivocada se arregla solo. Una re-eleccion forzada que no cambio nada no se repite
hasta REELECCION_TTL_S: con el token vencido de verdad, cada vuelta de health volvia a preguntar
a la API por todas las cuentas.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import threading
import time
from collections.abc import Callable

try:
    from . import subproc
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import subproc

log: Callable[[str], None] = lambda msg: print(f"cuenta_github: {msg}", file=sys.stderr)

HOST = "github.com"
CLAVE_HELPER = f"credential.https://{HOST}.helper"
GH_TIMEOUT_S = 15
CUENTAS_TTL_S = 60  # `gh auth status` valida cada token contra la API: no por cada url ni cada vuelta
REELECCION_TTL_S = 3600  # una re-eleccion forzada que no cambio nada no se repite antes de esto
# sin GH_TOKEN heredado: con uno puesto, `gh auth status` y `gh auth token --user X` contestan por el
ENV_GH = {"GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_TOKEN": "", "GITHUB_TOKEN": ""}

_RE_CUENTA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
_RE_LOGUEADA = re.compile(r"(Logged in to|Failed to log in to) github\.com account (\S+)")
_RE_ACTIVA = re.compile(r"Active account:\s*true", re.IGNORECASE)
_RE_HELPER_USER = re.compile(r"gh auth token --user (\S+)")

_lock = threading.Lock()
_cuentas_cache: tuple[float, tuple[list[str], str | None]] | None = None
_reelecciones: dict[str, tuple[str | None, float]] = {}  # url -> (lo que dio la ultima forzada, monotonic)


def duenio_y_repo(url: str | None) -> tuple[str, str] | None:
    """(dueño, repo) de una url https de github.com, o None. `git@github.com:` queda afuera: ssh va
    con llaves, no con el token de gh."""
    if not isinstance(url, str):
        return None
    m = re.match(r"^https://(?:[^/@]*@)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    if not m:
        return None
    duenio, repo = m.group(1), m.group(2)
    if not _RE_CUENTA.match(duenio) or not re.match(r"^[A-Za-z0-9._-]{1,100}$", repo):
        return None
    return duenio, repo


def _gh(args: list[str], env: dict | None = None, timeout: float = GH_TIMEOUT_S) -> tuple[int, str, str]:
    return subproc.correr(["gh", *args], timeout=timeout, sin_prompts=True, env={**ENV_GH, **(env or {})})


def _leer_cuentas() -> tuple[list[str], str | None]:
    rc, out, err = _gh(["auth", "status", "--hostname", HOST])
    if rc in (subproc.NO_ARRANCO, subproc.VENCIDO):
        return [], None
    logins: list[str] = []
    activa = None
    actual = None
    # gh escribe el estado por stdout o por stderr segun la version; cada cuenta abre con la linea
    # «Logged in to github.com account X» y abajo dice «Active account: true/false». Una que fallo
    # («Failed to log in to github.com account Y») no sirve, y sus lineas no son de la anterior
    for linea in (out + "\n" + err).splitlines():
        m = _RE_LOGUEADA.search(linea)
        if m:
            actual = m.group(2) if m.group(1) == "Logged in to" and _RE_CUENTA.match(m.group(2)) else None
            if actual and actual not in logins:
                logins.append(actual)
        elif actual and _RE_ACTIVA.search(linea):
            activa = actual
    return logins, activa


def cuentas(ahora: float | None = None) -> tuple[list[str], str | None]:
    """(logins guardados en gh para github.com, el activo o None), con CUENTAS_TTL_S de cache. Sin
    gh, o sin cuentas: ([], None) (y eso no se cachea: puede ser que gh todavia no respondia)."""
    global _cuentas_cache
    ahora = time.monotonic() if ahora is None else ahora
    with _lock:
        cache = _cuentas_cache
    if cache and ahora - cache[0] < CUENTAS_TTL_S:
        return cache[1]
    res = _leer_cuentas()
    if res[0]:
        with _lock:
            _cuentas_cache = (ahora, res)
    return res


def tiene_push(cuenta: str, duenio: str, repo: str) -> bool | None:
    """True si `cuenta` puede hacer push a dueño/repo, False si no (o el repo no existe para ella),
    None si no se pudo saber (sin red, sin token). El token vive solo en el entorno del `gh api`."""
    if not _RE_CUENTA.match(cuenta):
        return None
    rc, token, _err = _gh(["auth", "token", "--user", cuenta, "--hostname", HOST])
    token = token.strip()
    if rc != 0 or not token or any(c.isspace() for c in token):
        return None
    rc, out, err = _gh(["api", f"repos/{duenio}/{repo}", "--jq", ".permissions.push"], env={"GH_TOKEN": token})
    if rc == 0:
        return out.strip().lower() == "true"
    if rc in (subproc.NO_ARRANCO, subproc.VENCIDO):
        return None
    e = (err or "").lower()
    # 404: para esa cuenta el repo no existe (privado de otra) ; 403/401: sin permiso o token vencido
    if "404" in e or "not found" in e or "403" in e or "401" in e or "bad credentials" in e:
        return False
    return None  # red, rate limit u otra cosa: no prueba nada


def elegir(
    url: str, logins: list[str], activa: str | None, probar: Callable[..., bool | None] | None = None
) -> str | None:
    """La primera cuenta con push sobre el repo de `url`, probando en orden: la que se llama como
    el dueño, la activa, el resto. None si ninguna tiene (o no se pudo saber)."""
    dr = duenio_y_repo(url)
    if not dr or not logins:
        return None
    probar = probar or tiene_push  # se resuelve al llamar: las pruebas reemplazan tiene_push
    duenio, repo = dr
    orden: list[str] = []
    for c in [*(l for l in logins if l.lower() == duenio.lower()), *([activa] if activa else []), *logins]:
        if c and c in logins and c not in orden:
            orden.append(c)
    for c in orden:
        if probar(c, duenio, repo):
            return c
    return None


def helper_de(cuenta: str) -> str:
    """El valor de credential.helper que fija el repo a `cuenta`: git lo corre con sh (el `!`), solo
    responde al `get` y saca el token en ese momento, sin el GH_TOKEN que tenga la sesion."""
    if not _RE_CUENTA.match(cuenta):
        raise ValueError(f"cuenta invalida: {cuenta!r}")
    q = shlex.quote(cuenta)
    return (
        f'!f() {{ if [ "$1" = get ]; then echo username={q}; '
        f"printf 'password=%s\\n' \"$(GH_TOKEN= GITHUB_TOKEN= gh auth token --user {q} --hostname {HOST})\"; fi; }}; f"
    )


def _git_config(repo_dir: str, args: list[str]) -> tuple[int, str, str]:
    return subproc.correr(["git", "config", "--local", *args], timeout=10, sin_prompts=True, cwd=repo_dir)


def cuenta_fijada(repo_dir: str) -> str | None:
    """La cuenta a la que ya esta fijado el repo (por el helper que dejo `fijar`), o None."""
    rc, out, _err = _git_config(repo_dir, ["--get-all", CLAVE_HELPER])
    if rc != 0:
        return None
    hits = _RE_HELPER_USER.findall(out)
    return hits[-1] if hits else None


def fijar(repo_dir: str, cuenta: str) -> bool:
    """Deja en el .git/config del repo, solo para github.com: un helper vacio (borra la lista que
    venia del config global, el Git Credential Manager o `gh auth git-credential`) y el de `cuenta`.
    Son dos escrituras de git (la clave lleva dos valores): entre una y otra el repo queda sin helper
    unos milisegundos, y un push justo ahi falla sin pedir nada; con el .git/config.lock tomado por
    un git de la sesion, falla y se vuelve a intentar en la proxima vuelta."""
    helper = helper_de(cuenta)
    with _lock:
        rc1, _o, e1 = _git_config(repo_dir, ["--replace-all", CLAVE_HELPER, ""])
        rc2, _o, e2 = _git_config(repo_dir, ["--add", CLAVE_HELPER, helper]) if rc1 == 0 else (rc1, "", e1)
    if rc1 != 0 or rc2 != 0:
        log(f"no se pudo fijar {cuenta} en {repo_dir}: {(e1 or e2).strip()[:200]}")
        return False
    return True


def asegurar(repo_dir: str | None, url: str | None, forzar: bool = False) -> str | None:
    """Que el repo en `repo_dir` (con `origin` = `url`) use la cuenta de gh con push sobre el; la
    cuenta que quedo, o None si no es github.com, no hay gh, o no se pudo decidir. Si ya esta fijado
    a una cuenta que gh sigue teniendo, se la deja (salvo `forzar`: el ls-remote dio «vencida»).
    Una forzada que no encontro otra cuenta no se repite hasta REELECCION_TTL_S."""
    if not repo_dir or not os.path.isdir(repo_dir) or not duenio_y_repo(url):
        return None
    try:
        logins, activa = cuentas()
        if not logins:
            return None
        fijada = cuenta_fijada(repo_dir)
        if fijada not in logins:
            fijada = None  # fijado a una cuenta que gh ya no tiene: como si no estuviera
        if fijada and not forzar:
            return fijada
        ahora = time.monotonic()
        if forzar:
            with _lock:
                memo = _reelecciones.get(url)
            if memo and ahora - memo[1] < REELECCION_TTL_S and memo[0] in (None, fijada):
                return fijada  # hace poco se volvio a elegir y no habia nada mejor
        cuenta = elegir(url, logins, activa)
        if forzar:
            with _lock:
                _reelecciones[url] = (cuenta, ahora)
        if cuenta is None or cuenta == fijada:
            return fijada
        if not fijar(repo_dir, cuenta):
            return fijada
        log(f"{url}: fijado a la cuenta {cuenta} en {repo_dir}" + (f" (antes {fijada})" if fijada else ""))
        return cuenta
    except Exception as e:  # nunca tumba la medicion de salud
        log(f"{url}: {type(e).__name__}: {e}")
        return None


def olvidar() -> None:
    """Para las pruebas: sin cache de cuentas ni memoria de re-elecciones."""
    global _cuentas_cache
    with _lock:
        _cuentas_cache = None
        _reelecciones.clear()
