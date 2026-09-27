"""Ronda 3, encargo B: el pendiente que escribe hook.py (PermissionRequest) lleva `pc`, el pc_id
de esta PC leido directo de peer.json (hook.py no importa identity.py/state.py a proposito: arranca
por evento y tiene que ser liviano). Sin peer.json (server nunca arranco en esta PC): None, y no lo
crea -- eso es cosa del server. Ver docs/ronda3/encargo-B.md."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server  # noqa: F401  (agrega lienzo/ al sys.path)
import hook


def peer_json(tmp_path, pc_id) -> None:
    (tmp_path / "peer.json").write_text(json.dumps({"pc_id": pc_id, "name": "x", "color": "#fff"}), encoding="utf-8")


# --- read_pc_id: leido directo, sin crear nada -------------------------------------------------


def test_read_pc_id_de_peer_json(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path))
    peer_json(tmp_path, "abc123abc123")
    assert hook.read_pc_id() == "abc123abc123"


def test_read_pc_id_sin_peer_json_da_none_y_no_lo_crea(tmp_path, monkeypatch):
    # LIENZO_HOME ni siquiera existe todavia (el server nunca arranco en esta PC): read_pc_id no
    # debe crear ni la carpeta ni el archivo, eso es cosa del server
    home = tmp_path / "no-existe-todavia"
    monkeypatch.setattr(hook, "LIENZO", str(home))
    assert hook.read_pc_id() is None
    assert not os.path.exists(home)


def test_read_pc_id_con_json_corrupto_da_none(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path))
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "peer.json").write_text("no es json", encoding="utf-8")
    assert hook.read_pc_id() is None


def test_read_pc_id_sin_pc_id_adentro_da_none(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path))
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "peer.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert hook.read_pc_id() is None


# --- el pendiente que arma wait_for_answer lleva pc ---------------------------------------------


def capturar_pending(monkeypatch) -> dict:
    """Intercepta el atomic_write del pendiente (los `os.makedirs` de PENDING/ANSWERS corren de
    verdad, sobre tmp_path: no hace falta mockearlos) y devuelve el dict que se hubiera escrito."""
    monkeypatch.setattr(hook.time, "sleep", lambda s: None)  # que no espere de verdad los 0 s
    escrito = {}

    def fake_atomic_write(path, text):
        if os.path.dirname(path) == hook.PENDING:
            escrito["pending"] = json.loads(text)

    monkeypatch.setattr(hook, "atomic_write", fake_atomic_write)
    return escrito


def test_pendiente_lleva_pc(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path))
    monkeypatch.setattr(hook, "PENDING", str(tmp_path / "pending"))
    monkeypatch.setattr(hook, "ANSWERS", str(tmp_path / "answers"))
    peer_json(tmp_path, "deadbeef0000")
    escrito = capturar_pending(monkeypatch)
    hook.wait_for_answer("claude", {"session_id": "sid-1", "tool_name": "Bash", "tool_input": {}}, 0)
    assert escrito["pending"]["pc"] == "deadbeef0000"


def test_pendiente_sin_peer_json_lleva_pc_none(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LIENZO", str(tmp_path / "no-existe"))
    monkeypatch.setattr(hook, "PENDING", str(tmp_path / "pending"))
    monkeypatch.setattr(hook, "ANSWERS", str(tmp_path / "answers"))
    escrito = capturar_pending(monkeypatch)
    hook.wait_for_answer("claude", {"session_id": "sid-1", "tool_name": "Bash", "tool_input": {}}, 0)
    assert escrito["pending"]["pc"] is None
