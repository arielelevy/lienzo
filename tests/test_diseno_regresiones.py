"""Regresiones del informe F: transporte doble, recursos temporales y cero modelos reales."""

import builtins
import http.client
import io
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# El server instala imports del proyecto; fixtures importadas se solicitan por nombre en pytest.
# ruff: noqa: I001, F811
from lienzo import server

import conocimiento
import consulta
import restore
import rules
import sessions
import state
import xfer
from test_consulta import mundo  # noqa: F401
from test_coordinar import _envio, _tarjeta, c
from test_rules import entorno, regla  # noqa: F401


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("replacement", ["same", "newer", "card"])
def test_late_send_preserves_confirmed_or_replaced_card(monkeypatch, agent, replacement):
    field = "envio_claude" if agent == "claude" else "envio_codex"
    s = {"session_id": "fixture", "agent": agent}
    monkeypatch.setattr(sessions, "sessions", {"fixture": s})
    monkeypatch.setattr(sessions, "touch", lambda card: None)
    monkeypatch.setattr(sessions.captura, "envio", lambda *a, **k: None)
    monkeypatch.setattr(
        sessions,
        "puede_enviar",
        lambda card: {"puede": True, "transporte": "claude_pipe" if agent == "claude" else "codex_queue"},
    )
    monkeypatch.setattr(sessions.codex_queue, "message_fits", lambda *args: True)

    def transport(*args):
        s[field] = {
            "envio_id": "same" if replacement == "same" else "newer",
            "at": 10 if replacement == "same" else 20,
            "estado": "entregado",
            "confirmacion_final": True,
        }
        if replacement == "card":
            sessions.sessions["fixture"] = {**s}
        return {"envio_id": "same", "at": 10, "estado": "encolado"}

    monkeypatch.setattr(sessions.claude_pipe_runtime, "send", transport)
    monkeypatch.setattr(sessions.codex_queue, "enviar", transport)
    send = sessions.send_claude_pipe if agent == "claude" else sessions.send_codex_queue
    assert send(s, "fixture text", [])[0] == 200
    assert sessions.sessions["fixture"][field]["estado"] == "entregado"
    assert sessions.sessions["fixture"][field]["confirmacion_final"] is True


@pytest.mark.parametrize("status", ["pendiente", "encolado", "sin_confirmacion", "rechazado", "entregado"])
def test_coordinar_respects_explicit_transport_state_even_if_prompt_changed(monkeypatch, status):
    calls = _envio(
        monkeypatch,
        [(200, {"estado": status, "envio_id": "exact-id"})],
        [{"last_prompt": "old"}, {"last_prompt": "new", "state": "corriendo"}],
    )
    result = c.enviar_seguro(_tarjeta("u1"), "fixture", enlazar=False)
    assert result["ok"] is (status == "entregado")
    assert result["estado"] == status and result["envio_id"] == "exact-id"
    assert len(calls) == 1


@pytest.mark.parametrize("source", ["local", "mirror"])
def test_sse_overflow_closes_instead_of_sending_healthy_pings(monkeypatch, source):
    clients, ui = [], []
    q = queue.Queue(maxsize=1)
    monkeypatch.setattr(state, "clients", clients)
    monkeypatch.setattr(server, "clients", clients)
    monkeypatch.setattr(server, "ui_clients", ui)
    monkeypatch.setattr(server, "queue", SimpleNamespace(Queue=lambda **kw: q, Empty=queue.Empty, Full=queue.Full))

    class Writer(io.BytesIO):
        def write(self, data):
            if not self.tell():
                if source == "local":
                    state.broadcast({"seq": 1})
                    state.broadcast({"seq": 2})
                else:
                    server._push_to_ui_clients('{"seq":1}')
                    server._push_to_ui_clients('{"seq":2}')
            return super().write(data)

    output = Writer()
    handler = SimpleNamespace(
        send_response=lambda *a: None,
        send_header=lambda *a: None,
        end_headers=lambda: None,
        wfile=output,
        close_connection=False,
    )
    server._stream_sse(handler, '{"type":"snapshot"}', [ui])
    assert handler.close_connection and not clients and not ui
    assert b'"ping"' not in output.getvalue()


def test_sse_overflow_ends_real_chunked_response_and_allows_new_snapshot(monkeypatch):
    clients = []
    monkeypatch.setattr(state, "clients", clients)
    monkeypatch.setattr(server, "clients", clients)
    real_queue = queue.Queue
    monkeypatch.setattr(
        server, "queue", SimpleNamespace(Queue=lambda **kw: real_queue(maxsize=1), Empty=queue.Empty, Full=queue.Full)
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            return None

        def do_GET(self):
            writer = self.wfile

            class Writer:
                def write(inner, data):
                    result = writer.write(data)
                    if b"data:" in data:
                        state.broadcast({"seq": 1})
                        state.broadcast({"seq": 2})
                    return result

                def flush(inner):
                    return writer.flush()

                def close(inner):
                    return writer.close()

                @property
                def closed(inner):
                    return writer.closed

            self.wfile = Writer()
            server._stream_sse(self, '{"type":"snapshot","revision":2}', [])

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()
    try:
        for _ in range(2):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
            try:
                conn.request("GET", "/events")
                response = conn.getresponse()
                assert response.status == 200
                assert b'"revision":2' in response.read()
            finally:
                conn.close()
        assert clients == []
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(3)


def test_consulta_reservation_is_atomic(mundo, monkeypatch):
    barrier = threading.Barrier(2)
    monkeypatch.setattr(consulta, "now", lambda: (barrier.wait(timeout=3), "fixture-time")[1])
    monkeypatch.setattr(consulta, "_guardar", lambda c: None)
    sent = []
    monkeypatch.setattr(consulta, "_mandar_vuelta", lambda *a, **k: sent.append(a))
    results, errors = [], []

    def open_consulta():
        try:
            results.append(consulta.abrir({"pregunta": "fixture", "investigadores": ["A" * 8, "B" * 8]}))
        except Exception as error:
            errors.append(error)

    workers = [threading.Thread(target=open_consulta) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
    assert not errors and all(not worker.is_alive() for worker in workers)
    assert sorted(code for code, _ in results) == [200, 400]
    assert len(consulta.CONSULTAS) == len(sent) == 1


@pytest.mark.parametrize("body_error", [None, ValueError])
def test_sqlite_context_always_closes_on_transaction_failure(body_error):
    calls = []

    def fail():
        raise OSError("fixture transaction failure")

    context = conocimiento._Conexion("unused")
    context.con = SimpleNamespace(commit=fail, rollback=fail, close=lambda: calls.append("close"))
    with pytest.raises(OSError, match="fixture transaction failure"):
        context.__exit__(body_error, None, None)
    assert calls == ["close"]


def test_restore_unreadable_file_never_overwrites_previous_entries(tmp_path, monkeypatch):
    path = tmp_path / "restore.json"
    original = '[{"session_id":"old","agent":"claude"}]'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(restore, "path", lambda: str(path))
    real_open = builtins.open

    def deny_read(file, *args, **kwargs):
        if os.fspath(file) == str(path):
            raise PermissionError("fixture unreadable")
        return real_open(file, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", deny_read)
        with pytest.raises(OSError, match="no se guarda encima"):
            restore._store([{"session_id": "new"}], ended=False)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("bad", ['{"bad":', '{"wrong":"type"}'])
def test_restore_preserves_corrupt_bytes_before_replacement(tmp_path, monkeypatch, bad):
    path = tmp_path / "restore.json"
    path.write_text(bad, encoding="utf-8")
    monkeypatch.setattr(restore, "path", lambda: str(path))
    assert restore._read() == []
    (backup,) = tmp_path.glob("restore.json.corrupto-*")
    assert backup.read_text(encoding="utf-8") == bad


@pytest.mark.parametrize("status", ["encolado", "sin_confirmacion", "entregado"])
def test_rule_keeps_transport_result_without_replay(entorno, monkeypatch, status):
    r = regla()
    r["kind"] = "at"
    monkeypatch.setattr(
        rules, "send_to_session", lambda *a: (200, {"estado": status, "envio_id": "fixture-id", "motivo": None})
    )
    rules.fire_rule(r)
    assert r["last_envio"]["envio_id"] == "fixture-id"
    assert r["last_envio"]["estado"] == status
    assert (r["last_result"] == "ok") is (status == "entregado")
    assert r["fired"] == 1


@pytest.mark.parametrize("bad", ['{"bad":', '{"wrong":"type"}'])
def test_restore_failed_corrupt_backup_blocks_writes(tmp_path, monkeypatch, bad):
    path = tmp_path / "restore.json"
    path.write_text(bad, encoding="utf-8")
    monkeypatch.setattr(restore, "path", lambda: str(path))
    monkeypatch.setattr(state, "apartar_corrupto", lambda *a: None)
    with pytest.raises(OSError, match="no se guarda encima"):
        restore._store([{"session_id": "new"}], ended=False)
    assert path.read_text(encoding="utf-8") == bad


def test_xfer_rejects_junction_under_allowed_root(tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "private.txt").write_text("unchanged", encoding="utf-8")
    link = root / "escape"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(xfer.state, "load_config", lambda: {"copy_roots": [str(root)]})
    assert xfer.permitido(str(link / "private.txt")) is None
    with pytest.raises(xfer.Rechazo, match="enlace|físico"):
        xfer.unir(str(root), "escape/private.txt")
    assert xfer.permitido(str(root / "normal.txt")) == str(root / "normal.txt")
    assert (outside / "private.txt").read_text(encoding="utf-8") == "unchanged"


def test_server_script_entrypoint_imports_without_repo_on_pythonpath(tmp_path):
    script = Path(__file__).resolve().parents[1] / "lienzo/server.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_adapter_bootstrap_entrypoint_uses_flat_import_without_starting_child(tmp_path):
    folder = Path(__file__).resolve().parents[1] / "lienzo"
    # Isolated interpreter + foreign cwd: pytest's sys.path cannot mask entrypoint imports.
    # Bootstrap transfer and child creation are explicit doubles; no real pipe/model is used.
    code = """
import json, os, runpy, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import claude_pipe_bootstrap as bootstrap
sid = "99ba9409-9b60-405b-a771-6d475e41f4e6"
bootstrap.receive_environment = lambda *args: {"LIENZO_CLAUDE_BRIDGE_SESSION": sid}
scope = runpy.run_path(os.path.join(sys.argv[1], "claude_pipe_adapter.py"), run_name="probe")
writes = []
class Sink:
    def write(self, data): writes.append(json.loads(data))
    def close(self): pass
scope["subprocess"].Popen = lambda *args, **kwargs: SimpleNamespace(stdin=Sink())
sys.argv = ["adapter", "--bootstrap", sid, sid, "1", "2"]
scope["main"]()
assert writes == [{"session_id": sid}]
print("flat_bootstrap_import_ok")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(folder)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "flat_bootstrap_import_ok"
