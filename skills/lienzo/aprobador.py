"""Aprobador con lista permitida para los permisos de una coda (o de varias), por sesion.

NO es un «aprobar todo»: aprueba solo un comando cuyos TRAMOS (separados por && ; | & ( ) $( )
empiezan con un verbo de la politica, sin nada de la lista de peligro, con rutas dentro de las
carpetas permitidas y con un `rm` solo sobre las rutas permitidas. Todo lo demas se frena y se
informa para que lo decida una persona. Un comando cortado en pantalla («truncated») se frena
siempre: no se aprueba lo que no se puede leer entero.

El verbo se compara por PALABRA entera cuando el comando trae espacios (lo normal: así lo devuelve
`comando_visible`), y lo que no se puede leer sin ambigüedad se frena. Un comando ya compacto (sin
ningún espacio) se sigue aceptando por prefijo, pero con las mismas listas de peligro.

    import aprobador as a
    pol = a.Politica(
        raices=("d:/apps/ai-development-students",),
        rm_solo=("students/ariel.levy/",),
        pushes=("gitpush-uoriginstudent/ariel.levy--follow-tags", "gitpushoriginstudent/ariel.levy"),
    )
    a.vigilar(lambda s: s["session_id"].startswith("84c38b25"), pol, hasta=lambda s: "S4 LISTA" in (s.get("last_reply") or ""))

Se corre con autorizacion expresa del usuario para ESA tarea, y se detiene al terminar.
"""

import os
import re
import sys
import time
from dataclasses import dataclass, field

import coordinar as c

# `comando_visible` y la huella viven en el paquete del lienzo: el server rearma la misma cuenta
# para `expect` y no puede importar el skill. Esta carpeta es una junction al repo (skills/lienzo),
# así que la raíz del repo sale de la ruta real de este archivo.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from lienzo.pantalla_coda import SEP, comando_visible, compacto, huella

__all__ = ["SEP", "Politica", "comando_visible", "compacto", "huella", "permitido", "tramos", "vigilar"]

VERBOS = (
    # Sin `python`, `py` ni `find` (revisión 2026-10-04, 0.1): los dos primeros corren cualquier
    # código (`python -c`) y `find` borra o ejecuta (`-delete`, `-exec`). Lo decide una persona.
    "cd",
    "git",
    "tar",
    "cp",
    "mkdir",
    "pytest",
    "ruff",
    "grep",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "echo",
    "sort",
    "uniq",
    "test",
    "export",
    "type",
    "dir",
)
GIT_OK = (
    "status",
    "log",
    "diff",
    "add",
    "commit",
    "tag",
    "switch",
    "checkout",
    "clone",
    "am",
    "format-patch",
    "show",
    "rev-list",
    "branch",
    "config",
    "ls-files",
    "ls-remote",
    "remote",
    "fetch",
    "pull",
    "push",
)
PELIGRO = re.compile(
    r"reset|stash|rebase|amend|force|curl|wget|pip|npm|taskkill|shutdown|sudo|powershell|cmd/c|mkfs|chmod|chown|`"
    # Lo que hace que git o tar ejecuten un programa ajeno (una clave de config, un transporte o una
    # opción que corre un comando), `--output` (escribe un archivo donde diga) y el reflog.
    r"|sshcommand|hookspath|fsmonitor|upload-pack|receive-pack|--exec|ext::|--output|reflog"
    r"|to-command|checkpoint-action|compress-program|rsh-command|volume-script|info-script",
    re.IGNORECASE,
)
# Variables de entorno que cambian qué programa corre git, ssh o la shell: `GIT_SSH_COMMAND=x git
# fetch` es lo mismo que `core.sshCommand`. Se miran en minúsculas, con o sin `export` delante.
VAR_PELIGROSA = re.compile(
    r"^(?:export)?(?:git_|ssh|ld_|dyld_|path=|pythonpath|pythonstartup|bash_env|env=|pager=|editor=|"
    r"visual=|less|home=|prompt_command|shellopts|bashopts|ifs=)"
)
ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Palabras de la shell que pueden ir delante del verbo; no habilitan nada, se mira lo que sigue.
# `for`/`while`/`until` no están: un bucle lo decide una persona.
CONTROL = ("then", "else", "do", "if", "fi", "done", "{", "}", "!")
# Por subcomando de git, lo que no se aprueba solo. Se mira sobre los argumentos con las mayúsculas
# originales (`-B` fuerza, `-b` no). Conservador a propósito: lo dudoso lo decide una persona.
GIT_PROHIBIDO = {
    # `checkout -- .`, `checkout .`, `checkout -f`, `-B` y `checkout-index` pisan cambios.
    "checkout": re.compile(r"--|(?:^|\s)\.(?:\s|$)|\.$|(?:^|\s)-f|-B|^-index|--ours|--theirs"),
    "switch": re.compile(r"--discard|(?:^|\s)-f|-C"),
    # `-c clave=valor` y `-u <programa>` en un clone/fetch corren lo que digan.
    "clone": re.compile(r"(?i)--config|--template|separate-git-dir|-c\s*[a-z0-9_.-]+=|(?:^|\s|\")-u"),
    "fetch": re.compile(r"(?i)--config|-c\s*[a-z0-9_.-]+="),
    "pull": re.compile(r"(?i)--config|-c\s*[a-z0-9_.-]+="),
}
# Borrar, mover o copiar ramas y tags. Con espacios se mira cada opción; compacto, cualquier `-d`
# del texto (también el de una rama `x-dev`: se frena de más, no de menos).
RAMA_PELIGRO = re.compile(r"(?i)^-[a-z]*[dmcf]|^--(?:delete|move|copy|force|edit-description)")
TAG_PELIGRO = re.compile(r"(?i)^-[a-z]*[df]|^--(?:delete|force)")
GIT_LARGAS_LECTURA = re.compile(r"--(?:show-current|list|all|remotes|merged|no-merged|contains|verbose)")
# Los únicos `git config` que pasan son de lectura. Compacto no se distingue `config clave` (leer)
# de `config clave valor` (escribir, p. ej. `core.sshCommand`), así que solo `--get…`/`--list`/`-l`.
GIT_CONFIG_LECTURA = re.compile(r"--get|--list|-l(?![a-z])")
GIT_REMOTE_LECTURA = re.compile(r"(?:-v|-vv)?|(?:show|get-url)\b.*")
# Subcomandos donde `a..b` es un rango y no una ruta.
GIT_RANGOS = ("log", "diff", "show", "rev-list", "format-patch")
# Redirecciones inofensivas; cualquier otro `>` o `>>` escribe un archivo y se frena.
REDIR_OK = re.compile(r"\d?>&\d|\d?>(?:/dev/null|nul)(?![a-z])")


@dataclass
class Politica:
    raices: tuple = ()  # carpetas con letra de unidad que se pueden nombrar (minusculas, barras /)
    verbos: tuple = VERBOS
    git_ok: tuple = GIT_OK
    rm_solo: tuple = ()  # un `rm` solo vale sobre estos prefijos de ruta (relativos); vacio = ningun rm
    pushes: tuple = ()  # los unicos `git push` permitidos, compactos y en minusculas; vacio = ningun push
    peligro: re.Pattern = field(default=PELIGRO)


def tramos(cmd):
    # `&` suelto también separa (manda el anterior al fondo y sigue), salvo en `2>&1`.
    return [t.strip() for t in re.split(r"&&|\|\||;|\||(?<!>)&|\n|\$\(|\(|\)", cmd) if t.strip()]


def _en_raices(ruta, raices):
    return any(ruta == r or ruta.startswith(r.rstrip("/") + "/") for r in raices)


def _palabras(tramo, con_espacios):
    """Las palabras del tramo sin las de control ni las asignaciones `X=…` de adelante: esas no
    habilitan el resto, se juzga lo que sigue. (ok, motivo, palabras)."""
    if not con_espacios:
        # Compacto no se sabe dónde termina el valor de `X=…` (`FOO=1nodeevil.js`): se frena.
        t = tramo
        for p in CONTROL:
            if t.lower().startswith(p) and p.isalpha():
                t = t[len(p) :]
                break
        if ASIGNACION.match(t):
            return False, "asignacion pegada al comando: " + tramo[:60], []
        return True, "ok", [t] if t else []
    pals = tramo.split()
    while pals and pals[0].lower() in CONTROL:
        pals = pals[1:]
    while pals and ASIGNACION.match(pals[0]):
        if VAR_PELIGROSA.match(pals[0].lower()):
            return False, "variable de entorno que cambia que programa corre: " + pals[0][:60], []
        pals = pals[1:]
    return True, "ok", pals


def _verbo(pals, pol, con_espacios):
    """(verbo, argumentos) o (None, None). Con espacios el verbo es la palabra entera; compacto, el
    prefijo más largo (no hay otra). `gitstatus` pegado por el corte de línea vale como git."""
    if not pals:
        return None, None
    p0 = pals[0].lower()
    if p0 in pol.verbos:
        return p0, pals[1:]
    if p0.startswith("git") and any(p0[3:].startswith(g) for g in pol.git_ok):
        return "git", [pals[0][3:]] + pals[1:]
    if not con_espacios:
        v = max((v for v in pol.verbos if p0.startswith(v)), key=len, default=None)
        if v:
            return v, [pals[0][len(v) :]] if len(pals[0]) > len(v) else []
    return None, None


def _git_ok(args, con_espacios, pol):
    """(ok, motivo) de los argumentos de un `git` (el primero empieza con el subcomando)."""
    primero = (args[0] if args else "").lower()
    if con_espacios and primero in pol.git_ok:
        sub = primero
        resto = args[1:]
    else:
        # Compacto o pegado: el subcomando es el prefijo más largo de la lista. Una opción global
        # antes del subcomando (`git -c clave=valor …`, `git --git-dir=…`) no coincide y se frena.
        sub = max((g for g in pol.git_ok if primero.startswith(g)), key=len, default=None)
        # Lo que queda pegado al subcomando cuenta como argumento: `checkout-index` deja `-index`
        # y lo frena la regla de checkout; `remote-ext` deja `-ext` y no es de lectura.
        if sub is None:
            return False, "git no permitido: " + " ".join(args)[:60]
        resto = ([args[0][len(sub) :]] if len(args[0]) > len(sub) else []) + args[1:]
    texto = " ".join(resto)
    texto_l = texto.lower()
    if sub == "push":
        return False, "push no autorizado"  # los permitidos se aceptan antes, completos
    if sub == "config":
        lectura = GIT_CONFIG_LECTURA.match(compacto(texto_l)) or (con_espacios and resto[:1] == ["list"])
        if not lectura:
            return False, "git config que no es de lectura: " + texto[:60]
    if sub == "remote" and not GIT_REMOTE_LECTURA.fullmatch(texto_l if con_espacios else compacto(texto_l)):
        return False, "git remote que no es de lectura: " + texto[:60]
    if sub in ("branch", "tag"):
        peligro = RAMA_PELIGRO if sub == "branch" else TAG_PELIGRO
        if con_espacios:
            malo = any(peligro.match(a) for a in resto)
        else:
            sin_lectura = GIT_LARGAS_LECTURA.sub("", texto)
            malo = re.search(r"--(?:delete|move|copy|force)", texto) or re.search(
                peligro.pattern.replace("^", ""), sin_lectura
            )
        if malo:
            return False, f"git {sub} que borra, mueve o fuerza: " + texto[:60]
    prohibido = GIT_PROHIBIDO.get(sub)
    if prohibido and prohibido.search(texto):
        return False, f"git {sub} con una opcion que no se aprueba sola: " + texto[:60]
    if ".." in texto_l and (sub not in GIT_RANGOS or re.search(r"\.\./|/\.\.|(?:^|\s)\.\.|\.\.(?:\s|$)", texto_l)):
        return False, "ruta con '..': " + texto[:60]
    return True, "ok"


def _rm_ok(args, pol):
    """Con espacios: cada ruta del `rm` tiene que estar bajo `rm_solo` (antes se miraba solo la
    primera: `rm -rf students/ariel.levy/x /etc` pasaba)."""
    rutas = [a.replace("\\", "/").lower() for a in args if not a.startswith("-")]
    if not pol.rm_solo or not rutas:
        return False
    return all(".." not in r and r.startswith(pol.rm_solo) for r in rutas)


def permitido(cmd, pol):
    """(ok, motivo). `cmd` es el comando como lo devuelve `comando_visible` (con los espacios de cada
    línea) o ya compacto.

    Cada tramo se juzga por separado y el verbo por palabra entera (revisión 2026-10-04, 0.1):
    antes el push permitido se buscaba como substring de todo el comando (bastaba un `echo` con él
    para colar otro push), el subcomando de git en cualquier parte del tramo (`filter-branch`
    contiene `branch`) y el verbo por prefijo (`dotnet` empieza con `do`, `ifconfig` con `if`)."""
    base = cmd.replace("\\", "/")
    low = compacto(base).lower()
    con_espacios = bool(re.search(r"\s", base.strip()))
    if "(truncated)" in low or "\u2026" in low:
        return False, "comando truncado: no se puede leer entero"
    if pol.peligro.search(low):
        return False, "patron peligroso"
    for ruta in re.findall(r"[a-z]:/[^\"'\s&|;()<>]*", base.lower()):
        if not _en_raices(ruta, pol.raices):
            return False, "ruta fuera de las carpetas permitidas: " + ruta[:60]
    # Rutas que no tienen letra de unidad pero salen de las raíces: el home y las variables.
    if re.search(r"~(?:/|$|[\"'])|\$\{|\$[a-z_]|%[a-z_]+%", low):
        return False, "ruta o variable que puede salir de las carpetas permitidas"
    if ">" in REDIR_OK.sub("", low):
        return False, "redireccion a un archivo"
    for m in re.finditer(r"rm-(?:rf|fr|r|f)", low):
        resto = re.split(r"&&|\|\||;|\||&", low[m.end() :], maxsplit=1)[0]
        if ".." in resto or not pol.rm_solo or not any(resto.startswith(p) for p in pol.rm_solo):
            return False, "rm fuera de las rutas permitidas"
    for tramo in tramos(base):
        ok, motivo, pals = _palabras(tramo, con_espacios)
        if not ok:
            return ok, motivo
        if not pals:
            continue  # solo palabras de control o asignaciones inofensivas
        tc = compacto(" ".join(pals)).lower()
        if tc.startswith("rm") and (pals[0].lower() == "rm" or tc.startswith("rm-")):
            if con_espacios and not _rm_ok(pals[1:], pol):
                return False, "rm fuera de las rutas permitidas"
            continue
        if VAR_PELIGROSA.match(tc):
            return False, "variable de entorno que cambia que programa corre: " + tc[:60]
        if "push" in tc:
            if tc in pol.pushes:
                continue
            return False, "push no autorizado"
        verbo, args = _verbo(pals, pol, con_espacios)
        if verbo is None:
            return False, "verbo no permitido: " + " ".join(pals)[:60]
        if verbo == "git":
            ok, motivo = _git_ok(args, con_espacios, pol)
            if not ok:
                return ok, motivo
        elif ".." in tc:
            return False, "ruta con '..': " + tc[:60]
        if verbo in ("cd", "cp", "tar", "mkdir"):
            texto = " ".join(args)
            # Una ruta absoluta sin letra de unidad (`/etc`, `/c/Users`, `tar -C /x`) no se puede
            # comparar con las raíces; `cd` solo o `cd -` vuelven a un lugar que no se ve.
            if re.search(r"(?:^|[\s\"'=])/|-C\s*/|(?:^|\s)[a-zA-Z]:(?!/)", texto) or (
                verbo == "cd" and texto[:1] in ("", "-")
            ):
                return False, "ruta fuera de las carpetas permitidas: " + tc[:60]
            if re.search(r"\.git/|hooks", texto.lower()):
                return False, "escribe en .git: " + tc[:60]
    return True, "ok"


def vigilar(elegir, pol, hasta=None, max_s=7000, cada_s=6, log=print):
    """Mira las tarjetas que cumplen `elegir(s)`; si piden un permiso que la politica admite, lo aprueba.
    Frena (y avisa con `log`) lo que no. Corta cuando `hasta(s)` da True, si la tarjeta desaparece o a
    los `max_s`. Devuelve (aprobados, frenados). Pensado para correr en segundo plano.

    La aprobación lleva `expect` (la huella del comando juzgado): el server solo teclea si la
    pantalla sigue mostrando ese comando, y si cambió contesta 409 y se vuelve a mirar."""
    t0 = time.time()
    aprobados, frenados, vistos = [], [], set()
    while time.time() - t0 < max_s:
        tarjetas = [s for s in c.sesiones() if elegir(s)]
        if not tarjetas:
            log("la tarjeta ya no esta")
            break
        s = tarjetas[0]
        if hasta and hasta(s) and s["state"] == "termino":
            log("terminó: se deja de vigilar")
            break
        if s["state"] == "te_necesita":
            pantalla = c.pedir("GET", f"/sessions/{s['session_id']}/screen")[1]
            lineas = (pantalla.get("lines") or []) if isinstance(pantalla, dict) else []
            cmd = comando_visible(lineas)
            if cmd:
                ok, motivo = permitido(cmd, pol)
                clave = cmd[-60:] + str((s.get("needs") or {}).get("since"))
                if ok:
                    code, _ = c.pedir(
                        "POST",
                        f"/sessions/{s['session_id']}/approve",
                        {"decision": "allow", "expect": huella(lineas)},
                    )
                    aprobados.append((time.strftime("%H:%M:%S"), cmd[:120], code))
                    time.sleep(3)
                elif clave not in vistos:
                    vistos.add(clave)
                    frenados.append((motivo, cmd[:160]))
                    log(f"REQUIERE DECISION: {motivo} | {cmd[:220]}")
        time.sleep(cada_s)
    return aprobados, frenados
