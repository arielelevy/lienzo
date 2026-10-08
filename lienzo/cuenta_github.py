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
consultar a gh y adentro del helper: con uno puesto, gh lo devuelve para cualquier --user). Si gh
no tiene token para esa cuenta, el helper no contesta y git sigue con los helpers de siempre (el
Git Credential Manager, donde `pasar_credencial_git` deja una credencial que llego de otra PC):
la lista del repo es «vacio (resetea), el de la cuenta, los de sistema y global sin el de gh», y
se vuelve a escribir si los globales cambian.

Que cuenta: primero la que se llama como el dueño del repo (github.com/<dueño>/...), despues la
activa, despues el resto; gana la primera con `permissions.push` en `gh api repos/<dueño>/<repo>`.
Sin red no se decide nada (no se toca el repo ni se guarda). La eleccion de cada url vale
ELECCION_TTL_S: en el medio no se vuelve a preguntar a la API, ni para fijar una copia nueva del
mismo repo ni para una url que ninguna cuenta puede pushear.

Lo corre health.py en cada medicion de git_auth para los repos con sesion viva (todos los que
tengan ese origin), y de nuevo (`forzar`) cuando el ls-remote dio «vencida»: un 403 por cuenta
equivocada se arregla solo. Una forzada que no cambio nada tampoco se repite hasta el TTL: con el
token vencido de verdad, cada vuelta de health volvia a preguntar a la API por todas las cuentas.
Para una url sin repo vivo (una sesion que se cerro hace menos de GIT_GRACIA_S, o `git_check`),
health mide con la misma cadena de helpers que tendria el repo (`config_de`), no con la activa de gh.
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
# el de `gh auth setup-git` (solo sirve la cuenta activa); en Windows gh lo escribe como
# `!'C:/Program Files/GitHub CLI/gh.exe' auth git-credential`, asi que se reconoce por el final
GH_HELPER = "auth git-credential"
GH_TIMEOUT_S = 15
CUENTAS_TTL_S = 60  # `gh auth status` valida cada token contra la API: no por cada url ni cada vuelta
ELECCION_TTL_S = 3600  # cuanto vale la eleccion de una url antes de volver a preguntar a la API
HELPERS_TTL_S = 3600  # los helpers de sistema y global casi no cambian: cuatro `git config` por hora
# sin GH_TOKEN heredado: con uno puesto, `gh auth status` y `gh auth token --user X` contestan por el
ENV_GH = {"GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_TOKEN": "", "GITHUB_TOKEN": ""}

_RE_CUENTA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
# gh >= 2.40: «Logged in to github.com account X»; antes: «Logged in to github.com as X»
_RE_LOGUEADA = re.compile(r"(Logged in to|Failed to log in to) github\.com (?:account|as) (\S+)")
_RE_ACTIVA = re.compile(r"Active account:\s*true", re.IGNORECASE)
_RE_HELPER_USER = re.compile(r"gh auth token --user (\S+)")

_lock = threading.Lock()
_cuentas_cache: tuple[float, tuple[list[str], str | None]] | None = None
_helpers_cache: tuple[float, list[str]] | None = None
_elecciones: dict[str, tuple[str | None, float, bool]] = {}  # url -> (cuenta o None, monotonic, fue forzada)


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
    if logins and activa is None and len(logins) == 1 and "Active account:" not in out + err:
        activa = logins[0]  # un gh viejo, con una sola cuenta, no dice cual es la activa
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
    None si no se pudo saber (sin red, sin token, rate limit). El token vive solo en el entorno
    del `gh api`."""
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
    if "rate limit" in e:
        return None  # tambien es un 403, pero no dice nada del permiso
    # 404: para esa cuenta el repo no existe (privado de otra); 403/401: sin permiso o token vencido
    if "404" in e or "not found" in e or "403" in e or "401" in e or "bad credentials" in e:
        return False
    return None  # red u otra cosa: no prueba nada


def elegir(
    url: str, logins: list[str], activa: str | None, probar: Callable[..., bool | None] | None = None
) -> str | None:
    """La primera cuenta con push sobre el repo de `url`, probando en orden: la que se llama como
    el dueño, la activa, el resto. None si ninguna tiene (o no se pudo saber)."""
    return _elegir(url, logins, activa, probar)[0]


def _elegir(
    url: str, logins: list[str], activa: str | None, probar: Callable[..., bool | None] | None = None
) -> tuple[str | None, bool]:
    """(cuenta, seguro): `seguro` dice si la respuesta vale para guardarla: hubo una con push, o
    TODAS contestaron que no. Si alguna no se pudo probar (sin red, rate limit), no es un no."""
    dr = duenio_y_repo(url)
    if not dr or not logins:
        return None, False
    probar = probar or tiene_push  # se resuelve al llamar: las pruebas reemplazan tiene_push
    duenio, repo = dr
    orden: list[str] = []
    for c in [*(l for l in logins if l.lower() == duenio.lower()), *([activa] if activa else []), *logins]:
        if c and c in logins and c not in orden:
            orden.append(c)
    seguro = True
    for c in orden:
        r = probar(c, duenio, repo)
        if r:
            return c, True
        seguro = seguro and r is False
    return None, seguro


def _eleccion(url: str, logins: list[str], activa: str | None, forzar: bool, ahora: float) -> str | None:
    """`elegir`, con memoria por url: una eleccion vale ELECCION_TTL_S salvo que esta sea forzada y
    la guardada no (el ls-remote dio «vencida» despues de elegir: algo cambio, se vuelve a preguntar)
    o que la cuenta guardada ya no este en gh (`gh auth logout`). Lo que no se pudo decidir (sin red)
    no se guarda: se vuelve a probar en la proxima vuelta."""
    with _lock:
        memo = _elecciones.get(url)
    if memo and ahora - memo[1] < ELECCION_TTL_S and (memo[2] or not forzar) and memo[0] in (None, *logins):
        return memo[0]
    cuenta, seguro = _elegir(url, logins, activa)
    if seguro:
        with _lock:
            _elecciones[url] = (cuenta, ahora, forzar)
    return cuenta


def helper_de(cuenta: str) -> str:
    """El valor de credential.helper que fija el repo a `cuenta`: git lo corre con sh (el `!`), solo
    responde al `get` y saca el token en ese momento, sin el GH_TOKEN que tenga la sesion. Si gh no
    tiene token para esa cuenta no contesta nada, y git sigue con el helper que venga despues."""
    if not _RE_CUENTA.match(cuenta):
        raise ValueError(f"cuenta invalida: {cuenta!r}")
    q = shlex.quote(cuenta)
    return (
        f'!f() {{ if [ "$1" = get ]; then '
        f"t=$(GH_TOKEN= GITHUB_TOKEN= gh auth token --user {q} --hostname {HOST} 2>/dev/null); "
        f'if [ -n "$t" ]; then echo username={q}; printf \'password=%s\\n\' "$t"; fi; fi; }}; f'
    )


def helpers_de(cuenta: str) -> list[str]:
    """La lista de helpers de github.com que lleva un repo fijado a `cuenta`: vacio (resetea lo que
    venga de los otros configs, con el gh de la cuenta activa), el de la cuenta, y los de sistema y
    global que no sean el de gh (el Git Credential Manager), para una credencial guardada de otra forma."""
    return ["", helper_de(cuenta), *_helpers_globales()]


def config_de(cuenta: str) -> list[str]:
    """Los `-c` para que UN comando de git (el ls-remote de health, sin repo vivo) use en github.com
    la misma cadena de helpers que tendria un repo fijado a `cuenta`."""
    return [x for h in helpers_de(cuenta) for x in ("-c", f"{CLAVE_HELPER}={h}")]


def _git_config(repo_dir: str | None, args: list[str]) -> tuple[int, str, str]:
    return subproc.correr(["git", "config", *args], timeout=10, sin_prompts=True, cwd=repo_dir)


def _helpers_globales(ahora: float | None = None) -> list[str]:
    """Los credential.helper del config de sistema y global, generales o solo para github.com, sin
    el de gh; con HELPERS_TTL_S de cache (son cuatro `git config`)."""
    global _helpers_cache
    ahora = time.monotonic() if ahora is None else ahora
    with _lock:
        cache = _helpers_cache
    if cache and ahora - cache[0] < HELPERS_TTL_S:
        return list(cache[1])
    out: list[str] = []
    for ambito in ("--system", "--global"):
        for clave in ("credential.helper", CLAVE_HELPER):
            rc, texto, _err = _git_config(None, [ambito, "--get-all", clave])
            if rc == 0:
                out.extend(h for h in texto.splitlines() if h.strip() and GH_HELPER not in h and h not in out)
    with _lock:
        _helpers_cache = (ahora, list(out))
    return out


def _lista_fijada(repo_dir: str) -> list[str]:
    """Los valores de credential.https://github.com.helper del config local del repo."""
    rc, out, _err = _git_config(repo_dir, ["--local", "--get-all", CLAVE_HELPER])
    return out.splitlines() if rc == 0 else []


def cuenta_fijada(repo_dir: str) -> str | None:
    """La cuenta a la que ya esta fijado el repo (por el helper que dejo `fijar`), o None."""
    hits = [h for v in _lista_fijada(repo_dir) for h in _RE_HELPER_USER.findall(v)]
    return hits[-1] if hits else None


def fijar(repo_dir: str, cuenta: str) -> bool:
    """Deja en el .git/config del repo la lista de `helpers_de(cuenta)`. Son varias escrituras de git
    (la clave lleva varios valores): entre una y otra el repo queda unos milisegundos sin helper, y un
    push justo ahi falla sin pedir nada; con el .git/config.lock tomado por un git de la sesion, falla
    y se vuelve a intentar en la proxima vuelta."""
    valores = helpers_de(cuenta)
    with _lock:
        rc, _o, err = _git_config(repo_dir, ["--local", "--replace-all", CLAVE_HELPER, valores[0]])
        for v in valores[1:]:
            if rc != 0:
                break
            rc, _o, err = _git_config(repo_dir, ["--local", "--add", CLAVE_HELPER, v])
    if rc != 0:
        log(f"no se pudo fijar {cuenta} en {repo_dir}: {(err or '').strip()[:200]}")
        return False
    return True


def asegurar(repo_dir: str | None, url: str | None, forzar: bool = False) -> str | None:
    """Que el repo en `repo_dir` (con `origin` = `url`) use la cuenta de gh con push sobre el; la
    cuenta que quedo, o None si no es github.com, no hay gh, o no se pudo decidir. Si ya esta fijado
    a una cuenta que gh sigue teniendo, se la deja (salvo `forzar`: el ls-remote dio «vencida»),
    refrescando la lista si los helpers globales cambiaron desde que se fijo."""
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
            if _lista_fijada(repo_dir) != helpers_de(fijada) and fijar(repo_dir, fijada):
                log(f"{url}: helpers de {fijada} renovados en {repo_dir}")
            return fijada
        cuenta = _eleccion(url, logins, activa, forzar, time.monotonic())
        if cuenta is None or cuenta == fijada or not fijar(repo_dir, cuenta):
            return fijada
        log(f"{url}: fijado a la cuenta {cuenta} en {repo_dir}" + (f" (antes {fijada})" if fijada else ""))
        return cuenta
    except Exception as e:  # nunca tumba la medicion de salud
        log(f"{url}: {type(e).__name__}: {e}")
        return None


def cuenta_para(url: str | None, forzar: bool = False) -> str | None:
    """La cuenta con push sobre `url` (con la misma memoria que `asegurar`), sin tocar ningun repo:
    para medir una url que no tiene repo vivo. None si no es github.com o no se pudo decidir."""
    if not duenio_y_repo(url):
        return None
    try:
        logins, activa = cuentas()
        return _eleccion(url, logins, activa, forzar, time.monotonic()) if logins else None
    except Exception as e:
        log(f"{url}: {type(e).__name__}: {e}")
        return None


def olvidar() -> None:
    """Para las pruebas: sin cache de cuentas ni de helpers ni memoria de elecciones."""
    global _cuentas_cache, _helpers_cache
    with _lock:
        _cuentas_cache = None
        _helpers_cache = None
        _elecciones.clear()
