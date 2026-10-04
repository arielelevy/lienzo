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

    def correr(argv, **k):
        vistos["argv"], vistos["input"], vistos["sin_prompts"] = argv, k["entrada"], k["sin_prompts"]
        return 1, "", "fallo con token-123"

    monkeypatch.setattr(sec.subproc, "correr", correr)
    ok, msg = sec.aplicar_git("https://git.x.com", "ariel", "token-123")
    assert not ok and "token-123" not in msg and "***" in msg
    assert "token-123" not in " ".join(vistos["argv"])
    assert "password=token-123" in vistos["input"] and "host=git.x.com" in vistos["input"]
    assert vistos["sin_prompts"] is True


def test_leer_git_local_vencido_da_none_sin_colgarse(monkeypatch):
    """Revisión 2026-10-04, 0.5: con subprocess.run(capture_output) un credential manager vivo
    colgaba la lectura para siempre. Ahora va por subproc.correr, que vuelve con VENCIDO."""
    monkeypatch.setattr(sec.subproc, "correr", lambda argv, **k: (sec.subproc.VENCIDO, "", "no termino"))
    assert sec.leer_git_local("https://git.x.com") is None
    monkeypatch.setattr(sec.subproc, "correr", lambda argv, **k: (0, "username=u\npassword=p\n", ""))
    assert sec.leer_git_local("https://git.x.com") == ("u", "p")


def test_recibir_en_memoria_no_devuelve_el_valor():
    code, res = sec.recibir({"destino": "memoria", "nombre": "n"}, "token-123")
    assert code == 200 and "token-123" not in str(res)
    assert sec.BOVEDA.tomar(res["id"]) == ("n", "token-123")
    assert sec.recibir({"destino": "memoria", "nombre": "n"}, "")[0] == 400


@pytest.mark.parametrize("malo", ["u\nprotocol=https", "u\r", "u\0"])
def test_validar_rechaza_saltos_de_linea_en_usuario_y_valor(malo):
    """Revisión 2026-10-04, 0.6: `git credential approve` lee líneas clave=valor; un `\n` en el
    usuario o en el valor agregaba claves propias (otro host, otro protocolo)."""
    base = {"destino": "git", "nombre": "x", "git_url": "https://h"}
    assert sec.validar({**base, "usuario": malo})
    assert sec.validar({**base, "usuario": "u", "valor": "tok" + malo})
    code, res = sec.recibir({**base, "usuario": "u"}, "tok" + malo)
    assert code == 400 and "tok" not in str(res)


def test_aplicar_git_usa_el_host_sin_credenciales_de_la_url(monkeypatch):
    """`netloc` trae `user:pass@`: el host que se le pasa a git es hostname[:puerto]."""
    vistos = {}
    monkeypatch.setattr(sec.subproc, "correr", lambda argv, **k: vistos.update(k) or (0, "", ""))
    assert (
        sec.validar({"destino": "git", "nombre": "x", "git_url": "https://a:b@git.x.com:8443/r", "usuario": "u"})
        is None
    )
    ok, msg = sec.aplicar_git("https://a:b@git.x.com:8443/r", "u", "tok")
    assert ok and "host=git.x.com:8443\n" in vistos["entrada"] and "a:b" not in vistos["entrada"] + msg
    assert sec.validar({"destino": "git", "nombre": "x", "git_url": "https://h:99999", "usuario": "u"})


def test_leer_git_local_prueba_con_la_ruta_y_despues_solo_el_host(monkeypatch):
    """Medido el 2026-10-04: el GCM solo devolvia la credencial con path=…; sin la ruta queria abrir
    una ventana de login y pasar_credencial_git daba 404."""
    pedidos = []

    def correr(argv, entrada=None, **k):
        pedidos.append(entrada)
        if "path=" in entrada:
            return 0, "protocol=https\nhost=h.com\nusername=u\npassword=p\n", ""
        return 128, "", "fatal: Cannot prompt because user interactivity has been disabled."

    monkeypatch.setattr(sec.subproc, "correr", correr)
    assert sec.leer_git_local("https://h.com/org/repo.git") == ("u", "p")
    assert "path=org/repo.git" in pedidos[0]
