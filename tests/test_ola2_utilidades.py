"""Refactor, ola 2, punto 3: utilidades compartidas. atomico.atomic_write (la unica escritura
atomica, con el reintento de Windows que a auth le faltaba), CacheEnSegundoPlano de health y el
config.json corrupto que hook.py ya no calla."""

import json
import os

import atomico
import auth
import hook
import pytest
import state


def _replace_que_falla(monkeypatch, veces: int) -> list[str]:
    """os.replace levanta PermissionError las primeras `veces` (el antivirus con el archivo
    abierto); despues anda. Devuelve la lista de intentos."""
    intentos: list[str] = []
    real = os.replace

    def replace(src, dst):
        intentos.append(dst)
        if len(intentos) <= veces:
            raise PermissionError(13, "otro proceso tiene el archivo abierto")
        real(src, dst)

    monkeypatch.setattr(atomico.os, "replace", replace)
    monkeypatch.setattr(atomico.time, "sleep", lambda s: None)
    return intentos


def test_atomic_write_reintenta_ante_el_antivirus(tmp_path, monkeypatch):
    intentos = _replace_que_falla(monkeypatch, 2)
    p = tmp_path / "x.json"
    atomico.atomic_write(str(p), "hola ñandú")
    assert p.read_text(encoding="utf-8") == "hola ñandú"
    assert len(intentos) == 3
    assert os.listdir(tmp_path) == ["x.json"], "no queda ningun .tmp"


def test_atomic_write_se_rinde_y_no_deja_el_tmp(tmp_path, monkeypatch):
    _replace_que_falla(monkeypatch, 99)
    p = tmp_path / "x.json"
    with pytest.raises(PermissionError):
        atomico.atomic_write(str(p), "x")
    assert os.listdir(tmp_path) == []


def test_state_auth_y_hook_usan_la_misma_escritura(tmp_path, monkeypatch):
    """La de auth no tenia el reintento: un login podia dar 500 por el antivirus."""
    intentos = _replace_que_falla(monkeypatch, 1)
    auth._atomic(str(tmp_path / "auth.json"), {"a": 1})
    assert json.loads((tmp_path / "auth.json").read_text(encoding="utf-8")) == {"a": 1}
    state.atomic_write(str(tmp_path / "s.json"), "s")
    hook.atomic_write(str(tmp_path / "h.json"), "h")
    assert len(intentos) == 4  # el primero de auth fallo y se reintento
    assert hook.atomic_write is atomico.atomic_write


def test_atomico_es_una_hoja_liviana():
    """hook.py lo importa en cada evento: nada del lienzo ni `threading`."""
    with open(atomico.__file__, encoding="utf-8") as f:
        codigo = f.read()
    imports = {ln.split()[1] for ln in codigo.splitlines() if ln.startswith(("import ", "from "))}
    assert imports <= {"__future__", "os", "time", "_thread"}
