"""Tests de install.py --peer y --dry-run (plan-multi-pc-2026-09-26.md, ronda 2 encargo A):
regla de firewall del emparejamiento (7322 TCP, 7323 UDP, perfil Privado) y el modo --dry-run que
tiene que cubrir tambien los hooks. `subprocess.run` va siempre mockeado: ni con --dry-run ni sin
el se ejecuta un netsh de verdad desde un test."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import install


@pytest.fixture(autouse=True)
def _sin_netsh_de_verdad(monkeypatch):
    """Red de seguridad: si algun test se olvida de mockear subprocess.run, que reviente en vez
    de tocar el firewall de la maquina."""

    def _no_deberia_llamarse(*a, **kw):
        raise AssertionError("subprocess.run no deberia llamarse sin mockear en un test")

    monkeypatch.setattr(install.subprocess, "run", _no_deberia_llamarse)


# --- firewall_args: la forma del comando, sin ejecutar nada -------------------------------------


def test_firewall_args_alta_perfil_privado():
    args = install.firewall_args("Lienzo Peer TCP", "TCP", 7322, uninstall=False)
    assert args[:4] == ["netsh", "advfirewall", "firewall", "add"]
    assert "name=Lienzo Peer TCP" in args
    assert "protocol=TCP" in args
    assert "localport=7322" in args
    assert "profile=private" in args


def test_firewall_args_baja():
    args = install.firewall_args("Lienzo Beacon UDP", "UDP", 7323, uninstall=True)
    assert args == ["netsh", "advfirewall", "firewall", "delete", "rule", "name=Lienzo Beacon UDP"]


def test_reglas_son_7322_tcp_y_7323_udp():
    assert [r[:3] for r in install.FIREWALL_RULES[:2]] == [
        ("Lienzo Peer TCP", "TCP", 7322),
        ("Lienzo Beacon UDP", "UDP", 7323),
    ]
    assert all(r[3] == ("profile=private",) for r in install.FIREWALL_RULES[:2])


def test_por_tailscale_cualquier_perfil_pero_solo_entre_ip_de_la_tailnet():
    tailscale = [r for r in install.FIREWALL_RULES if "Tailscale" in r[0]]
    assert [(r[1], r[2]) for r in tailscale] == [("TCP", 7322), ("UDP", 7323)]
    for _nombre, _proto, _puerto, extra in tailscale:
        assert set(extra) == {"profile=any", "localip=100.64.0.0/10", "remoteip=100.64.0.0/10"}


# --- peer_firewall con dry_run: nunca llama a subprocess.run ------------------------------------


def test_peer_firewall_dry_run_no_ejecuta_nada(monkeypatch, capsys):
    monkeypatch.setattr(install, "is_admin", lambda: True)
    install.peer_firewall(uninstall=False, dry_run=True)
    salida = capsys.readouterr().out
    assert "[dry-run]" in salida
    assert "localport=7322" in salida
    assert "localport=7323" in salida


def test_peer_firewall_dry_run_no_requiere_admin(monkeypatch, capsys):
    monkeypatch.setattr(install, "is_admin", lambda: False)
    install.peer_firewall(uninstall=False, dry_run=True)  # no explota ni pide admin en dry-run
    assert "[dry-run]" in capsys.readouterr().out


# --- peer_firewall real (subprocess mockeado): admin, sin admin, alta y baja --------------------


def test_peer_firewall_sin_admin_no_toca_nada(monkeypatch, capsys):
    """Sin admin, peer_firewall no debe ni intentar llamar a subprocess.run: si lo hiciera, el
    fixture autouse (_no_deberia_llamarse) tira AssertionError y este test fallaria."""
    monkeypatch.setattr(install, "is_admin", lambda: False)
    install.peer_firewall(uninstall=False, dry_run=False)
    assert "administrador" in capsys.readouterr().out


def test_peer_firewall_con_admin_llama_netsh_para_cada_regla(monkeypatch, capsys):
    llamadas = []

    def _run(args, **kw):
        llamadas.append(args)

        class _R:
            returncode = 0
            stdout = "Ok.\n"
            stderr = ""

        return _R()

    monkeypatch.setattr(install, "is_admin", lambda: True)
    monkeypatch.setattr(install.subprocess, "run", _run)
    install.peer_firewall(uninstall=False, dry_run=False)
    assert len(llamadas) == len(install.FIREWALL_RULES) == 4
    assert any("localport=7322" in a for a in llamadas)
    assert any("localport=7323" in a for a in llamadas)
    salida = capsys.readouterr().out
    assert "agregada" in salida


def test_peer_firewall_uninstall_borra_las_dos_reglas(monkeypatch):
    llamadas = []

    def _run(args, **kw):
        llamadas.append(args)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(install, "is_admin", lambda: True)
    monkeypatch.setattr(install.subprocess, "run", _run)
    install.peer_firewall(uninstall=True, dry_run=False)
    assert all("delete" in a for a in llamadas)


def test_peer_firewall_informa_el_fallo_de_netsh_sin_reventar(monkeypatch, capsys):
    def _run(args, **kw):
        class _R:
            returncode = 1
            stdout = ""
            stderr = "No se encontro la regla especificada.\n"

        return _R()

    monkeypatch.setattr(install, "is_admin", lambda: True)
    monkeypatch.setattr(install.subprocess, "run", _run)
    install.peer_firewall(uninstall=True, dry_run=False)  # no debe levantar
    assert "fallo" in capsys.readouterr().out


# --- --dry-run tambien cubre los hooks, no solo el firewall -------------------------------------


def test_merge_hooks_dry_run_no_escribe_nada(tmp_path, capsys):
    destino = tmp_path / "settings.json"
    install.merge_hooks(
        str(destino), "claude", install.CLAUDE_EVENTS, uninstall=False, backup=True, prune=True, dry_run=True
    )
    assert not destino.exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_merge_hooks_sin_dry_run_si_escribe(tmp_path):
    destino = tmp_path / "settings.json"
    install.merge_hooks(
        str(destino), "claude", install.CLAUDE_EVENTS, uninstall=False, backup=True, prune=True, dry_run=False
    )
    assert destino.exists()
    with open(destino, encoding="utf-8") as f:
        data = json.load(f)
    assert "hooks" in data


def test_hooks_de_codex_sin_async(tmp_path):
    # async en Codex abre una ventana de pwsh por turno (BUG-ventanas-pwsh-hooks-codex.md)
    destino = tmp_path / "hooks.json"
    install.merge_hooks(str(destino), "codex", install.CODEX_EVENTS, uninstall=False)
    with open(destino, encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    assert set(hooks) == set(install.CODEX_EVENTS)
    assert not any("async" in h for groups in hooks.values() for g in groups for h in g["hooks"])


def test_ensure_state_dry_run_no_crea_carpetas(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install, "HOME", str(tmp_path))
    install.ensure_state(dry_run=True)
    assert not (tmp_path / ".lienzo").exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_merge_pi_dry_run_no_escribe_nada(tmp_path, capsys):
    destino = tmp_path / "settings.json"
    install.merge_pi(str(destino), uninstall=False, dry_run=True)
    assert not destino.exists()
    assert "[dry-run]" in capsys.readouterr().out
