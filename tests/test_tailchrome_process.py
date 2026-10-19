"""Inventario completo y ciclo del proceso; ninguna conexión a la tailnet real."""

import io
import json
import struct
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

import federation
import pytest
import state
import tailchrome_native as native
import tailchrome_process as automatic


@pytest.mark.parametrize("raw", [b"", b"\x01", struct.pack("<I", 2**30), struct.pack("<I", 3) + b"{}"])
def test_protocolo_rechaza_frames_truncados_o_grandes(raw):
    with pytest.raises((EOFError, ValueError)):
        native.read_message(io.BytesIO(raw))


def test_helper_real_por_pipes_perfil_propio_y_cierre(tmp_path, monkeypatch):
    # Python simula sólo el programa externo. El cliente, framing y pipes son reales.
    script = tmp_path / "helper.py"
    script.write_text(
        "import json, struct, sys\n"
        "def send(d):\n"
        " b=json.dumps(d).encode(); sys.stdout.buffer.write(struct.pack('<I',len(b))+b); sys.stdout.buffer.flush()\n"
        "send({'cmd':'procRunning','procRunning':{'port':12345,'proxyAuth':{'version':1,'username':'local','password':'SECRET'}}})\n"
        "while True:\n"
        " p=sys.stdin.buffer.read(4)\n"
        " if not p: break\n"
        " d=json.loads(sys.stdin.buffer.read(struct.unpack('<I',p)[0]))\n"
        " if d['cmd']=='init':\n"
        "  send({'cmd':'init','init':{}})\n"
        "  send({'cmd':'status','status':{'running':True,'profile':d['initID'],'peers':[]}})\n",
        encoding="utf-8",
    )
    real_popen = native.subprocess.Popen
    launched = []

    def popen(argv, **kwargs):
        launched.append(argv)
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(native.subprocess, "Popen", popen)
    host = native.Host("lienzo-aaaaaaaaaaaa", executable="INSTALLED_HELPER.exe")
    try:
        host.start()
        deadline = time.monotonic() + 3
        while not host.snapshot() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert host.snapshot()["profile"] == "lienzo-aaaaaaaaaaaa"
        assert launched == [["INSTALLED_HELPER.exe"]]
        assert host.proxy == (12345, "local", "SECRET")
    finally:
        host.close()
    assert host.process.poll() == 0
    assert host.proxy is None


class FakeHost:
    def __init__(self, profile):
        self.profile = profile
        self.dead = threading.Event()
        self.error = None
        self.commands = []
        self.data = {"running": True, "peers": []}

    def start(self):
        pass

    def send(self, message):
        self.commands.append(message)

    def snapshot(self):
        return self.data

    def close(self):
        self.dead.set()


class FakeRelay:
    launched: ClassVar[list] = []

    def __init__(self, host, board_port, peer, ip, log):
        self.pc_id = peer["pc_id"]
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.launched.append((self.pc_id, ip))

    def start(self):
        self.ready.set()

    def close(self):
        self.closed.set()


def test_descubre_todos_incluye_offline_y_conecta_todos_los_pares_conocidos(monkeypatch):
    root = Path(state.LIENZO)
    root.mkdir(parents=True, exist_ok=True)
    for pc_id in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        federation.add_peer(str(root / "peers.json"), {"pc_id": pc_id, "port": 7322, "key": "ab" * 32})
    monkeypatch.setattr(automatic, "Relay", FakeRelay)
    monkeypatch.setattr(FakeRelay, "launched", [])
    visits = []
    ids = {"100.64.1.1": "aaaaaaaaaaaa", "100.64.1.2": "bbbbbbbbbbbb", "100.64.1.3": "cccccccccccc"}

    def probe(host, ip, port):
        visits.append(ip)
        return {"pc_id": ids[ip], "name": "same-name"}

    monkeypatch.setattr(automatic, "probe", probe)
    data = {
        "running": True,
        "selfNode": {"id": "self", "hostname": "local-lienzo", "online": True, "tailscaleIPs": ["100.64.1.9"]},
        "peers": [
            {"id": str(i), "hostname": "same-name", "online": i != 4, "tailscaleIPs": [f"100.64.1.{i}"]}
            for i in range(1, 5)
        ],
    }
    service = automatic.Service(1)
    service._scan(FakeHost("profile"), data)
    public = service.public()
    assert len(public["devices"]) == 5  # self, dos pares, uno nuevo y uno offline
    assert set(visits) == set(ids)
    assert set(FakeRelay.launched) == {("aaaaaaaaaaaa", "100.64.1.1"), ("bbbbbbbbbbbb", "100.64.1.2")}
    assert sum(row["connected"] for row in public["devices"]) == 2
    assert sum(row["lienzo"] is not None and not row["paired"] for row in public["devices"]) == 1
    service._scan(FakeHost("profile"), data)
    assert len(FakeRelay.launched) == 2  # no duplica procesos ni puentes
    service.close()
    assert not any(row["connected"] for row in service.public()["devices"])


def test_persistencia_autostart_nombre_y_stop_sin_filtrar_credenciales(monkeypatch):
    hosts = []

    def factory(profile):
        host = FakeHost(profile)
        hosts.append(host)
        return host

    monkeypatch.setattr(automatic.identity, "pc_id", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(automatic.socket, "gethostname", lambda: "AR-IT33940")
    service = automatic.Service(1, host_factory=factory)
    try:
        service.configure(True)
        deadline = time.monotonic() + 3
        while (not hosts or not hosts[0].commands) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert hosts[0].profile == "lienzo-aaaaaaaaaaaa"
        assert {"cmd": "set-prefs", "prefs": {"hostname": "ar-it33940-lienzo"}} in hosts[0].commands
        assert json.loads(service.config_path.read_text()) == {"enabled": True}
        service.configure(False)
        assert hosts[0].dead.is_set()
        assert json.loads(service.config_path.read_text()) == {"enabled": False}
        assert not service.thread.is_alive()
        service.config_path.write_text('{"enabled":true}')
        service.autostart()
        assert service.enabled
    finally:
        service.close()
        if service.thread:
            service.thread.join(3)


def test_publico_no_expone_proxy_ni_acepta_links_arbitrarios():
    service = automatic.Service(1)
    service.host = FakeHost("profile")
    service.host.data.update({"proxyAuth": {"password": "SECRET"}, "authURL": "https://evil.example/"})
    assert "SECRET" not in json.dumps(service.public())
    assert service.public()["login_url"] is None
    service.host.data["authURL"] = "https://login.tailscale.com/a/example"
    assert service.public()["login_url"] == "https://login.tailscale.com/a/example"


def test_inventario_truncado_no_se_presenta_como_completo():
    service = automatic.Service(1)
    service._scan(FakeHost("profile"), {"peers": [], "peersTruncated": True, "totalPeers": 500})
    assert service.public()["truncated"] is True
    assert service.public()["total"] == 500
