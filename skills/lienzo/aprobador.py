"""Aprobador con lista permitida para los permisos de una coda (o de varias), por sesion.

NO es un «aprobar todo»: aprueba solo un comando cuyos TRAMOS (separados por && ; | ( ) $( )
empiezan con un verbo de la politica, sin nada de la lista de peligro, con rutas dentro de las
carpetas permitidas y con un `rm` solo sobre las rutas permitidas. Todo lo demas se frena y se
informa para que lo decida una persona. Un comando cortado en pantalla («truncated») se frena
siempre: no se aprueba lo que no se puede leer entero.

La pantalla de coda parte las lineas en cualquier lado, asi que el comando se compara sin espacios.

    import aprobador as a
    pol = a.Politica(
        raices=("d:/apps/ai-development-students",),
        rm_solo=("students/ariel.levy/",),
        pushes=("gitpush-uoriginstudent/ariel.levy--follow-tags", "gitpushoriginstudent/ariel.levy"),
    )
    a.vigilar(lambda s: s["session_id"].startswith("84c38b25"), pol, hasta=lambda s: "S4 LISTA" in (s.get("last_reply") or ""))

Se corre con autorizacion expresa del usuario para ESA tarea, y se detiene al terminar.
"""

import re
import time
from dataclasses import dataclass, field

import coordinar as c

SEP = chr(0x2502)  # │: el panel lateral de coda; lo que va a su derecha no es el comando

VERBOS = (
    "cd",
    "git",
    "tar",
    "cp",
    "mkdir",
    "python",
    "py",
    "pytest",
    "ruff",
    "grep",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "echo",
    "find",
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
    r"reset|stash|rebase|amend|force|curl|wget|pip|npm|taskkill|shutdown|sudo|powershell|cmd/c|mkfs|chmod|chown|`",
    re.IGNORECASE,
)


@dataclass
class Politica:
    raices: tuple = ()  # carpetas con letra de unidad que se pueden nombrar (minusculas, barras /)
    verbos: tuple = VERBOS
    git_ok: tuple = GIT_OK
    rm_solo: tuple = ()  # un `rm` solo vale sobre estos prefijos de ruta (relativos); vacio = ningun rm
    pushes: tuple = ()  # los unicos `git push` permitidos, compactos y en minusculas; vacio = ningun push
    peligro: re.Pattern = field(default=PELIGRO)


def comando_visible(lineas):
    """El comando de un cartel «Approval Required», compacto; None si no hay cartel."""
    izq = [ln.split(SEP)[0].rstrip() for ln in lineas if ln.strip()]
    i = max((k for k, ln in enumerate(izq) if "Approval Required" in ln), default=None)
    if i is None:
        return None
    cuerpo = []
    for ln in izq[i + 1 :]:
        if "ask by command policy" in ln or ln.strip().startswith(("Yes", "\u276f Yes", "No")):
            break
        cuerpo.append(ln.strip())
    return "".join(cuerpo)


def tramos(compacto):
    return [t.strip() for t in re.split(r"&&|\|\||;|\||\$\(|\(|\)", compacto) if t.strip()]


def permitido(cmd, pol):
    """(ok, motivo). `cmd` viene compacto (sin espacios)."""
    low = cmd.lower().replace("\\", "/")
    if "(truncated)" in low or "\u2026" in low:
        return False, "comando truncado: no se puede leer entero"
    pushes_ok = any(p in low for p in pol.pushes)
    if pol.peligro.search(low):
        return False, "patron peligroso"
    if "push" in low and not pushes_ok:
        return False, "push no autorizado"
    for ruta in re.findall(r"[a-z]:/[^\"'\s]*", low):
        if not ruta.startswith(pol.raices):
            return False, "ruta fuera de las carpetas permitidas: " + ruta[:60]
    for m in re.finditer(r"rm-(?:rf|fr|r|f)", low):
        resto = re.split(r"&&|\|\||;|\|", low[m.end() :], maxsplit=1)[0]
        if ".." in resto or not pol.rm_solo or not any(resto.startswith(p) for p in pol.rm_solo):
            return False, "rm fuera de las rutas permitidas"
    for t in tramos(low):
        t = t.lstrip("!{} ")
        if t.startswith("rm-"):
            continue
        ok_verbo = t.startswith(pol.verbos) or re.match(r"^[a-z_]+=", t)
        if not ok_verbo and not t.startswith(("done", "fi", "then", "do", "for", "if", "else")):
            return False, "verbo no permitido: " + t[:60]
        if t.startswith("git") and not any(g in t[:70] for g in pol.git_ok):
            return False, "git no permitido: " + t[:60]
    return True, "ok"


def vigilar(elegir, pol, hasta=None, max_s=7000, cada_s=6, log=print):
    """Mira las tarjetas que cumplen `elegir(s)`; si piden un permiso que la politica admite, lo aprueba.
    Frena (y avisa con `log`) lo que no. Corta cuando `hasta(s)` da True, si la tarjeta desaparece o a
    los `max_s`. Devuelve (aprobados, frenados). Pensado para correr en segundo plano."""
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
                    code, _ = c.pedir("POST", f"/sessions/{s['session_id']}/approve", {"decision": "allow"})
                    aprobados.append((time.strftime("%H:%M:%S"), cmd[:120], code))
                    time.sleep(3)
                elif clave not in vistos:
                    vistos.add(clave)
                    frenados.append((motivo, cmd[:160]))
                    log(f"REQUIERE DECISION: {motivo} | {cmd[:220]}")
        time.sleep(cada_s)
    return aprobados, frenados
