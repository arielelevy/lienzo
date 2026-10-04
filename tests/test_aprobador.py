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


def test_comando_visible_lee_el_cartel_y_corta_en_las_opciones():
    lineas = [
        "┃ ⚠  Approval Required",
        '   cd "D:/apps/ai-development-students" && git status   │ panel',
        "  ask by command policy",
        "  ❯ Yes",
    ]
    assert a.comando_visible(lineas) == 'cd "D:/apps/ai-development-students" && git status'
    assert a.comando_visible(["nada"]) is None
