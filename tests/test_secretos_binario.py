"""Versión binaria de secretos (sellar/abrir) para el canal vivo de Chrome remoto."""

import pytest
import secretos


def test_sellar_abrir_roundtrip_with_associated_data():
    clave = bytes(range(32))
    datos = bytes(range(256)) * 4000
    aad = b">" + (7).to_bytes(8, "big")
    sellado = secretos.sellar(clave, datos, aad)
    assert len(sellado) == len(datos) + secretos.NONCE_BYTES + secretos.TAG_BYTES
    assert datos not in sellado
    assert secretos.abrir(clave, sellado, aad) == datos


def test_two_seals_of_same_data_differ():
    clave = bytes(range(32))
    assert secretos.sellar(clave, b"igual") != secretos.sellar(clave, b"igual")


@pytest.mark.parametrize("cambio", ["aad", "tag", "cuerpo", "clave", "corto", "tipo"])
def test_abrir_rejects_any_alteration(cambio):
    clave = bytes(range(32))
    sellado = secretos.sellar(clave, b"cuadro", b"aad")
    i = secretos.NONCE_BYTES
    casos = {
        "aad": (clave, sellado, b"otro"),
        "tag": (clave, sellado[:-1] + bytes([sellado[-1] ^ 1]), b"aad"),
        "cuerpo": (clave, sellado[:i] + bytes([sellado[i] ^ 1]) + sellado[i + 1:], b"aad"),
        "clave": (bytes(32), sellado, b"aad"),
        "corto": (clave, sellado[:40], b"aad"),
        "tipo": (clave, sellado.hex(), b"aad"),
    }
    with pytest.raises(ValueError):
        secretos.abrir(*casos[cambio])


def test_keystream_is_deterministic_nonce_sensitive_and_long():
    k = bytes(32)
    assert secretos._keystream(k, b"n" * 16, 70) == secretos._keystream(k, b"n" * 16, 70)
    assert secretos._keystream(k, b"n" * 16, 70) != secretos._keystream(k, b"m" * 16, 70)
    assert len(secretos._keystream(k, b"n" * 16, 1_000_001)) == 1_000_001


def test_text_api_still_roundtrips_after_keystream_change():
    clave = bytes(range(32))
    texto = "ñandú " * 50000
    assert secretos.descifrar(clave, secretos.cifrar(clave, texto)) == texto
