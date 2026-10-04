"""skills/lienzo/aprobador.py: la lista permitida frena lo peligroso, lo truncado y lo que sale de las
carpetas permitidas, y deja pasar lo benigno (los casos salen de permisos reales de las codas)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "lienzo"))
import aprobador as a

POL = a.Politica(
    raices=("d:/apps/gestor_finanzas", "d:/apps/ai-development-students"),
    rm_solo=("students/ariel.levy/",),
    pushes=("gitpush-uoriginstudent/ariel.levy--follow-tags",),
)
CLON = 'cd"D:/apps/ai-development-students"'


def test_aprueba_lo_benigno():
    assert a.permitido(CLON + "&&gitstatus--shortstudents/ariel.levy|head-20", POL)[0]
    tar = (
        'cd"D:/apps/gestor_finanzas"&&tar--exclude=.git--exclude=.coda/tmp-cf-.|'
        '(cd"D:/apps/ai-development-students/students/ariel.levy"&&tar-xf-)&&echoCOPIA_OK'
    )
    assert a.permitido(tar, POL)[0]
    assert a.permitido("gitpush-uoriginstudent/ariel.levy--follow-tags", POL)[0]


def test_frena_lo_peligroso():
    for cmd in ("gitpush--forceoriginstudent/ariel.levy", "gitresetHEAD~1", "curlhttp://x", "gitstashpush"):
        assert not a.permitido(cmd, POL)[0], cmd


def test_frena_un_push_no_autorizado():
    assert not a.permitido("gitpushoriginmain", POL)[0]
    assert not a.permitido("gitpush", a.Politica(raices=POL.raices))[0]


def test_frena_rutas_y_rm_fuera_de_lo_permitido():
    assert not a.permitido('cd"C:/Users/otro"&&ls', POL)[0]
    assert not a.permitido("rm-rf/c/users", POL)[0]
    assert not a.permitido("rm-rfstudents/ariel.levy/..", POL)[0]
    assert a.permitido(CLON + "&&rm-rfstudents/ariel.levy/src", POL)[0]


def test_frena_lo_truncado_y_los_verbos_desconocidos():
    assert not a.permitido(CLON + "&&python-mpytest… (truncated)", POL)[0]
    assert not a.permitido("node-e1", POL)[0]


def test_frena_los_atajos_que_pasaban_la_lista():
    """Revisión 2026-10-04 (0.1): cada uno de estos pasaba. El push se buscaba como substring en
    todo el comando (bastaba un `echo` con el push permitido), git se aceptaba si el subcomando
    aparecía en cualquier parte del tramo (`filter-branch` contiene `branch`), y `python`/`py`/`find`
    eran verbos (ejecutan cualquier cosa o borran con `-delete`)."""
    for cmd in (
        "gitpushoriginmain&&echogitpushoriginstudent/ariel.levy",
        "gitpushoriginmain&&echogitpush-uoriginstudent/ariel.levy--follow-tags",
        "find.-delete",
        "gitfilter-branch",
        "gitcheckout--.",
        "gitcheckout.",
        "gitbranch-Dmain",
        "gitbranch-dmain",
        "gitconfigcore.sshCommandx",
        "gitconfiguser.emailx@y",
        "cp../../../.bashrc.",
        'python-c"x"',
        "py-3.14-c1",
        "cd..&&ls",
        "git-ccore.sshCommand=xfetch",
        "gitclone--upload-pack=xa",
        "gittag-dv1",
        "git_ssh_command=xgitfetch",
        "exportGIT_SSH_COMMAND=x",
        "cp~/.ssh/id_rsa.",
        "cp/etc/passwd.",
        "echox>~/.bashrc",
        "tar--to-command=shx-xf-",
        "ls&gitpushoriginmain",
    ):
        assert not a.permitido(cmd, POL)[0], cmd


def test_sigue_aprobando_git_benigno():
    for cmd in (
        CLON + "&&gitlog--oneline-5",
        CLON + "&&gitdiffmain..head--stat",
        CLON + "&&gitconfig--getuser.email",
        CLON + "&&gitconfig--list",
        CLON + "&&gitbranch-a",
        CLON + "&&gitcheckout-bstudent/ariel.levy",
        CLON + "&&gitcheckoutstudent/ariel.levy",
        CLON + '&&gitcommit-m"S4lista"',
        CLON + "&&gitstatus2>&1",
    ):
        assert a.permitido(cmd, POL)[0], (cmd, a.permitido(cmd, POL))


def test_con_espacios_el_verbo_es_la_palabra_entera():
    """Así llega de `comando_visible`. Antes el verbo se comparaba por prefijo y las palabras de
    control o una asignación habilitaban el resto del tramo."""
    for cmd in (
        "for f in *; do rm -rf $f; done",
        "do rm -rf x",
        "FOO=1 node evil.js",
        "dotnet run",
        "ifconfig",
        "thenevil x",
        "git reflog expire --all",
        "echo x > a.txt",
        "echo x >> a.txt",
        "rm -rf /etc",
        "rm -rf students/ariel.levy/x /etc",
        "git config core.sshCommand x",
        "git config user.email x@y",
        "git branch -D main",
        "git branch -m main x",
        "git filter-branch --all",
        "git checkout -- .",
        "git -c core.sshCommand=x fetch",
        "GIT_SSH_COMMAND=x git fetch",
        "git push origin main && echo git push origin student/ariel.levy",
        "cp ../../../.bashrc .",
        "cd /etc && ls",
        "cd && cp a b",
        "python -c 1",
    ):
        assert not a.permitido(cmd, POL)[0], cmd
    for cmd in (
        'cd "D:/apps/ai-development-students" && git status --short students/ariel.levy | head -20',
        "git push -u origin student/ariel.levy --follow-tags",
        'cd "D:/apps/ai-development-students" && rm -rf students/ariel.levy/src',
        "git branch --show-current",
        "git branch my-dev",
        "git config --get user.email",
        "FOO=1 git status",
        "git log --oneline main..HEAD",
        'git commit -m "S4 lista"',
        "if test -f x; then echo si; fi",
    ):
        assert a.permitido(cmd, POL)[0], (cmd, a.permitido(cmd, POL))


def test_huella_es_el_sha256_del_comando_compacto():
    import hashlib

    lineas = ["┃ ⚠  Approval Required", "   git  status   │ panel", "  ❯ Yes"]
    assert a.huella(lineas) == hashlib.sha256(b"gitstatus").hexdigest()
    assert a.huella(["nada"]) is None


def test_comando_visible_lee_el_cartel_y_corta_en_las_opciones():
    lineas = [
        "┃ ⚠  Approval Required",
        '   cd "D:/apps/ai-development-students" && git status   │ panel',
        "  ask by command policy",
        "  ❯ Yes",
    ]
    assert a.comando_visible(lineas) == 'cd "D:/apps/ai-development-students" && git status'
    assert a.comando_visible(["nada"]) is None
