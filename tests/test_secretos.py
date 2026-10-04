"""lienzo/secretos.py: el secreto viaja cifrado, se lee una vez, vence y nunca aparece en una salida."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))
import secretos as sec

K = b"k" * 32


def test_cifra_y_descifra_y_no_deja_el_texto_a_la_vista():
    c = sec.cifrar(K, "token-123 ñ")
    assert "token" not in str(c)
    assert sec.descifrar(K, c) == "token-123 ñ"
    assert sec.cifrar(K, "x")["nonce"] != sec.cifrar(K, "x")["nonce"]


@pytest.mark.parametrize("campo", ["ct", "nonce", "tag"])
def test_un_secreto_tocado_o_con_otra_clave_no_se_descifra(campo):
    c = sec.cifrar(K, "token-123")
    roto = dict(c)
    roto[campo] = ("00" if c[campo][:2] != "00" else "11") + c[campo][2:]
    with pytest.raises(ValueError):
        sec.descifrar(K, roto)
    with pytest.raises(ValueError):
        sec.descifrar(b"z" * 32, c)
    with pytest.raises(ValueError):
        sec.descifrar(K, {"ct": "zz"})


def test_boveda_un_solo_uso_y_vence():
    reloj = [0.0]
    b = sec.Boveda(ttl_s=10, reloj=lambda: reloj[0])
    a = b.guardar("forgejo", "v1")
    assert b.pendientes() == [{"id": a, "nombre": "forgejo", "vence_en_s": 10}]
    assert b.tomar(a) == ("forgejo", "v1")
    assert b.tomar(a) is None
    c = b.guardar("otro", "v2")
    reloj[0] = 11
    assert b.tomar(c) is None and b.pendientes() == []


def test_validar():
    assert sec.validar({"destino": "memoria", "nombre": "x"}) is None
    assert sec.validar({"destino": "otro", "nombre": "x"})
    assert sec.validar({"destino": "git", "nombre": "x", "git_url": "http://h", "usuario": "u"})
    assert sec.validar({"destino": "git", "nombre": "x", "git_url": "https://h", "usuario": ""})
    assert sec.validar({"destino": "git", "nombre": "x", "git_url": "https://h", "usuario": "u"}) is None


def test_aplicar_git_manda_el_valor_por_stdin_y_lo_tapa_en_los_errores(monkeypatch):
    vistos = {}

    class R:
        returncode = 1
        stderr = "fallo con token-123"

    def run(argv, **k):
        vistos["argv"], vistos["input"], vistos["env"] = argv, k["input"], k["env"]
        return R()

    monkeypatch.setattr(sec.subprocess, "run", run)
    ok, msg = sec.aplicar_git("https://git.x.com", "ariel", "token-123")
    assert not ok and "token-123" not in msg and "***" in msg
    assert "token-123" not in " ".join(vistos["argv"])
    assert "password=token-123" in vistos["input"] and "host=git.x.com" in vistos["input"]
    assert vistos["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_recibir_en_memoria_no_devuelve_el_valor():
    code, res = sec.recibir({"destino": "memoria", "nombre": "n"}, "token-123")
    assert code == 200 and "token-123" not in str(res)
    assert sec.BOVEDA.tomar(res["id"]) == ("n", "token-123")
    assert sec.recibir({"destino": "memoria", "nombre": "n"}, "")[0] == 400
