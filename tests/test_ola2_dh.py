"""Tests del emparejamiento con DH autenticado por la frase (plan-refactor-2026-10-04.md 0.4).

Las dos PCs corren en este mismo proceso: `pairing._pedir` se reemplaza por un ruteo en memoria que
le entrega cada pedido de join() al accept() de la otra PC, cambiando antes `identity.pc_id`,
`identity.pc_info` y `state.LIENZO` a los de la PC que atiende. Asi se ve el trafico entero (lo que
veria alguien escuchando la LAN) y se puede probar que con eso y la frase correcta no alcanza."""

import hashlib
import hmac
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (test_identity.py)
from lienzo import server  # noqa: F401
import federation as fed
import identity as idn
import pairing
import state as st

ID_A = "aaaaaaaaaaaa"  # la PC que ofrece la frase
ID_B = "bbbbbbbbbbbb"  # la PC que la pega


dos_pcs_hooks: dict = {}  # "pedido": body -> body y "transformar": (path, body, res) -> res


@pytest.fixture
def dos_pcs(tmp_path, monkeypatch):
    """Dos PCs en memoria. Devuelve (trafico, peers_de, ofrecer, como): `trafico` junta cada pedido
    y respuesta de /peer/pair tal como viajaria por la red; `como(pc_id, fn, *a)` corre fn como esa
    PC (por defecto el proceso es B, la que pega la frase)."""
    homes = {ID_A: str(tmp_path / "a"), ID_B: str(tmp_path / "b")}
    for h in homes.values():
        os.makedirs(h, exist_ok=True)
    actual = {"id": ID_B}
    monkeypatch.setattr(idn, "pc_id", lambda: actual["id"])
    monkeypatch.setattr(idn, "pc_info", lambda: {"pc_id": actual["id"], "name": f"pc-{actual['id'][0]}", "color": ""})
    monkeypatch.setattr(st, "LIENZO", homes[ID_B])
    pairing._offer = None
    pairing._fails.clear()
    pairing._blocked_until = 0.0
    trafico: list[tuple[str, dict | None, dict]] = []

    def como(pc_id, fn, *a):
        previo = (actual["id"], st.LIENZO)
        actual["id"], st.LIENZO = pc_id, homes[pc_id]
        try:
            return fn(*a)
        finally:
            actual["id"], st.LIENZO = previo

    def pedir(host, port, method, path, body=None, timeout=5.0):
        # copia por JSON: lo mismo que cruzaria el cable, sin referencias compartidas
        body = json.loads(json.dumps(body)) if body is not None else None
        if method == "GET" and path == "/peer/hello":
            res = {"pc_id": ID_A, "name": "pc-a"}
        elif method == "POST" and path == "/peer/pair":
            if "pedido" in dos_pcs_hooks:
                body = dos_pcs_hooks["pedido"](body)
            res = como(ID_A, pairing.accept, body)
        else:
            raise AssertionError(path)
        res = json.loads(json.dumps(res))
        if body is None:
            return res  # /peer/hello: publico, no entra en el trafico que importa
        trafico.append((path, body, res))
        if "transformar" in dos_pcs_hooks:
            res = dos_pcs_hooks["transformar"](path, body, res)
        return res

    dos_pcs_hooks.clear()
    monkeypatch.setattr(pairing, "_pedir", pedir)

    def peers_de(pc_id):
        return como(pc_id, lambda: fed.list_peers(pairing._peers_path()))

    def ofrecer():
        return como(ID_A, pairing.offer)

    return trafico, peers_de, ofrecer, como


# --- el grupo ----------------------------------------------------------------------------------


def test_el_grupo_es_el_modp_2048_del_rfc_3526():
    assert pairing.P.bit_length() == 2048
    assert pairing.P >> 1984 == 2**64 - 1 and pairing.P % 2**64 == 2**64 - 1  # 64 unos arriba y abajo
    assert pow(3, pairing.P - 1, pairing.P) == 1 and pow(3, pairing.Q - 1, pairing.Q) == 1  # primo seguro
    for elemento in (pairing.G, pairing.M, pairing.N):
        assert pairing._publico_valido(elemento)
    assert pairing.M != pairing.N


@pytest.mark.parametrize(
    "malo",
    [0, 1, pairing.P - 1, pairing.P, pairing.P + 4, pairing.P - 2, -4],
    ids=["0", "1", "p-1", "p", "p+4", "p-2", "negativo"],
)
def test_publico_invalido_se_rechaza(malo):
    # P - 2 = -2 no es residuo cuadratico (2 lo es y -1 no, porque p = 3 mod 4): fuera del subgrupo
    assert not pairing._publico_valido(malo)
    if malo >= 0:
        with pytest.raises(pairing.PairingError):
            pairing._leer_publico(format(malo, "x"))


def test_publico_mal_formado_o_gigante_se_rechaza():
    for raw in (None, "", "zz", 4, "f" * 513):
        with pytest.raises(pairing.PairingError):
            pairing._leer_publico(raw)


# --- punta a punta en memoria ------------------------------------------------------------------


def test_emparejamiento_completo_las_dos_pcs_derivan_la_misma_clave(dos_pcs):
    trafico, peers_de, ofrecer, _ = dos_pcs
    oferta = ofrecer()
    peer_visto_por_b = pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    assert peer_visto_por_b["pc_id"] == ID_A
    [peer_a_en_b] = peers_de(ID_B)
    [peer_b_en_a] = peers_de(ID_A)
    assert peer_b_en_a["pc_id"] == ID_B
    assert peer_a_en_b["key"] == peer_b_en_a["key"]
    assert len(bytes.fromhex(peer_a_en_b["key"])) == 32
    # la clave ya no es la que sale solo de la frase (la que se crackeaba offline)
    assert peer_a_en_b["key"] != fed.derive_pair_key(oferta["phrase"], ID_A, ID_B).hex()
    assert [p for p, _, _ in trafico] == ["/peer/pair", "/peer/pair"]  # start y confirm (hello no cuenta)
    assert pairing._offer is None  # la frase quedo consumida


def test_dos_emparejamientos_con_la_misma_frase_dan_claves_distintas(dos_pcs):
    _, peers_de, ofrecer, _ = dos_pcs
    claves = set()
    for _ in range(2):
        ofrecer()
        pairing._offer["phrase"] = "misma"  # la misma frase en las dos vueltas
        pairing.join("misma", "10.0.0.1", 7322)
        claves.add(peers_de(ID_B)[0]["key"])
    assert len(claves) == 2  # los exponentes efimeros cambian la clave aunque la frase no cambie


def test_atacante_pasivo_con_todo_el_trafico_y_la_frase_no_reconstruye_la_clave(dos_pcs):
    """Lo que tiene alguien que escucho la LAN y ademas sabe la frase: los dos pc_id, X, Y, el hs y
    las dos confirmaciones. Sin x ni y, K = g^(xy) es un Diffie-Hellman computacional; aca se
    prueba que las derivaciones obvias con los datos publicos no dan la clave, y que lo que antes
    alcanzaba (derive_pair_key) tampoco."""
    trafico, peers_de, ofrecer, _ = dos_pcs
    oferta = ofrecer()
    pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    clave_real = bytes.fromhex(peers_de(ID_A)[0]["key"])

    (_, start_req, start_res), (_, confirm_req, confirm_res) = trafico
    x_pub, y_pub = int(start_req["spake"], 16), int(start_res["spake"], 16)
    clave_frase = fed.derive_pair_key(oferta["phrase"], ID_A, ID_B)
    w = pairing._w(clave_frase)
    transcript = pairing._transcript(ID_B, ID_A, x_pub, y_pub)
    gx = x_pub * pow(pairing.M, -w, pairing.P) % pairing.P  # lo maximo que se saca: g^x y g^y
    gy = y_pub * pow(pairing.N, -w, pairing.P) % pairing.P
    candidatos_k = {x_pub, y_pub, gx, gy, gx * gy % pairing.P, x_pub * y_pub % pairing.P, 1, pairing.G}
    for k in candidatos_k:
        candidata = pairing._clave_final(clave_frase, transcript, k)
        assert candidata != clave_real
        assert pairing._confirmacion(candidata, b"join", transcript) != confirm_req["proof"]
    assert clave_frase != clave_real
    # y la clave con la que se firman los mensajes despues no se puede verificar con la frase sola
    firma_real = fed.sign(clave_real, "GET", "/peer/sessions", b"", 1.0, "n")
    assert fed.sign(clave_frase, "GET", "/peer/sessions", b"", 1.0, "n") != firma_real


def test_con_un_exponente_secreto_si_se_reconstruye(dos_pcs, monkeypatch):
    """Contra-prueba del anterior: la clave sale de K y de la frase, nada mas. Con el exponente del
    que pega la frase (que nunca viaja) se reconstruye exacta."""
    trafico, peers_de, ofrecer, _ = dos_pcs
    exps = []
    original = pairing._exponente

    def anotar():
        exps.append(original())
        return exps[-1]

    monkeypatch.setattr(pairing, "_exponente", anotar)
    oferta = ofrecer()
    pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    (_, start_req, start_res), _ = trafico
    x_pub, y_pub = int(start_req["spake"], 16), int(start_res["spake"], 16)
    clave_frase = fed.derive_pair_key(oferta["phrase"], ID_A, ID_B)
    w = pairing._w(clave_frase)
    x = exps[0]  # el primero lo genero join(); el segundo, accept()
    k = pairing._compartido(y_pub, w, pairing.N, x)
    reconstruida = pairing._clave_final(clave_frase, pairing._transcript(ID_B, ID_A, x_pub, y_pub), k)
    assert reconstruida.hex() == peers_de(ID_A)[0]["key"]


def test_proof_del_que_pega_alterado_falla_y_no_guarda_nada(dos_pcs):
    _, peers_de, ofrecer, _ = dos_pcs
    oferta = ofrecer()

    # se altera lo que manda B en "confirm", ya en el cable: el primer digito del proof cambiado
    def alterar(body):
        if body.get("step") == "confirm":
            p = body["proof"]
            body = {**body, "proof": ("1" if p[0] == "0" else "0") + p[1:]}
        return body

    dos_pcs_hooks["pedido"] = alterar
    with pytest.raises(pairing.PairingError, match="frase nueva"):
        pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    assert peers_de(ID_A) == [] and peers_de(ID_B) == []
    assert pairing._offer is None  # un intento por frase


def test_proof_de_vuelta_alterado_falla_y_el_que_pega_no_guarda(dos_pcs):
    _, peers_de, ofrecer, _ = dos_pcs
    oferta = ofrecer()

    def alterar(path, body, res):
        if body.get("step") == "confirm":
            res = {**res, "proof": "0" * 64}
        return res

    dos_pcs_hooks["transformar"] = alterar
    with pytest.raises(pairing.PairingError, match="proof de vuelta"):
        pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    assert peers_de(ID_B) == []


@pytest.mark.parametrize("malo", [0, 1, pairing.P - 1, pairing.P], ids=["0", "1", "p-1", "p"])
def test_join_rechaza_un_y_invalido_de_la_otra_pc(dos_pcs, malo):
    _, peers_de, ofrecer, _ = dos_pcs
    oferta = ofrecer()

    def forzar(path, body, res):
        if body.get("step") == "start":
            res = {**res, "spake": format(malo, "x")}
        return res

    dos_pcs_hooks["transformar"] = forzar
    with pytest.raises(pairing.PairingError, match="DH"):
        pairing.join(oferta["phrase"], "10.0.0.1", 7322)
    assert peers_de(ID_B) == []


@pytest.mark.parametrize("malo", [0, 1, pairing.P - 1, pairing.P], ids=["0", "1", "p-1", "p"])
def test_accept_rechaza_un_x_invalido(dos_pcs, malo):
    _, _, ofrecer, como = dos_pcs
    ofrecer()
    req = {"pc_id": ID_B, "step": "start", "spake": format(malo, "x")}
    with pytest.raises(pairing.PairingError, match="DH"):
        como(ID_A, pairing.accept, req)
    assert pairing._offer is not None and pairing._offer["hs"] is None


def test_atacante_activo_con_palabra_equivocada_no_aprende_nada_y_gasta_la_frase(dos_pcs):
    """Un atacante que se hace pasar por la PC que pega, con una palabra que no es: el "start" le
    da un Y que no puede usar, el "confirm" falla, la frase queda consumida y el intento cuenta para
    el freno. Lo unico que obtiene en todo el intercambio son mensajes de error y Y."""
    _, peers_de, ofrecer, como = dos_pcs
    oferta = ofrecer()
    frase_mala = "zzzz" if oferta["phrase"] != "zzzz" else "yyyy"
    atacante = "dddddddddddd"
    clave_frase = fed.derive_pair_key(frase_mala, ID_A, atacante)
    w = pairing._w(clave_frase)
    x = pairing._exponente()
    x_pub = pairing._cegar(x, w, pairing.M)
    res = como(ID_A, pairing.accept, {"pc_id": atacante, "step": "start", "spake": pairing._hex(x_pub)})
    assert set(res) >= {"spake", "hs"} and "proof" not in res  # el start no revela ninguna prueba
    y_pub = int(res["spake"], 16)
    k = pairing._compartido(y_pub, w, pairing.N, x)
    transcript = pairing._transcript(atacante, ID_A, x_pub, y_pub)
    proof = pairing._confirmacion(pairing._clave_final(clave_frase, transcript, k), b"join", transcript)
    with pytest.raises(pairing.PairingError, match="frase nueva"):
        como(ID_A, pairing.accept, {"pc_id": atacante, "step": "confirm", "hs": res["hs"], "proof": proof})
    assert pairing._offer is None
    assert len(pairing._fails) == 1
    assert peers_de(ID_A) == []


def test_las_confirmaciones_dependen_del_rol():
    clave, transcript = b"k" * 32, b"t"
    assert pairing._confirmacion(clave, b"join", transcript) != pairing._confirmacion(clave, b"offer", transcript)
    esperado = hmac.new(clave, b"confirm/join/t", hashlib.sha256).hexdigest()
    assert pairing._confirmacion(clave, b"join", transcript) == esperado
