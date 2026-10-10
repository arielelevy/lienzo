"""Tanda 2 de PENDIENTES.md (2026-10-10): cupo de streams SSE, cuota de adjuntos por sesion, sesiones web
listables y revocables, rutas de adjuntos para agentes de WSL y el aviso de coda --model."""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
from lienzo import server
import auth
import launch
import sessions as ses
import tmux


class _HandlerFalso:
    def __init__(self):
        self.codigos, self.wfile = [], io.BytesIO()

    def send_response(self, code):
        self.codigos.append(code)

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass


def test_con_el_cupo_de_sse_lleno_el_stream_nuevo_recibe_503_y_no_se_registra(monkeypatch):
    monkeypatch.setattr(server, "MAX_SSE", 2)
    monkeypatch.setattr(server, "clients", [object(), object()])
    extra: list = []
    h = _HandlerFalso()
    server._stream_sse(h, "{}", [extra])
    assert h.codigos == [503] and b"demasiados streams" in h.wfile.getvalue()
    assert len(server.clients) == 2 and extra == []


def test_la_cuota_de_adjuntos_es_por_sesion(monkeypatch, tmp_path):
    monkeypatch.setattr(ses, "ADJUNTOS", str(tmp_path))
    monkeypatch.setattr(server, "save_attachment", ses.save_attachment)
    monkeypatch.setattr(server, "ADJUNTOS_CUOTA", 10)
    assert ses.adjuntos_bytes("s1") == 0
    s = {"session_id": "s1"}
    assert server.accion_attach(s, {"filename": "a.txt", "data": b"123456"})[0] == 200
    assert ses.adjuntos_bytes("s1") == 6
    code, res = server.accion_attach(s, {"filename": "b.txt", "data": b"12345"})
    assert code == 413 and "tope" in res["error"]
    # otra sesion tiene su propia cuota
    assert server.accion_attach({"session_id": "s2"}, {"filename": "b.txt", "data": b"12345"})[0] == 200


def test_sesiones_web_se_listan_sin_el_token_y_se_revocan(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "WEB_SESSIONS", str(tmp_path / "sessions-web.json"))
    vence = (auth.now() + auth.dt.timedelta(days=1)).isoformat(timespec="seconds")
    viejo = (auth.now() - auth.dt.timedelta(days=1)).isoformat(timespec="seconds")
    sesiones = {
        auth._key("tok-a"): {"created": "2026-10-01T10:00:00", "expires": vence, "ip": "1.1.1.1", "ua": "cel"},
        auth._key("tok-b"): {"created": "2026-10-02T10:00:00", "expires": vence, "ip": "2.2.2.2", "ua": "pc"},
        auth._key("tok-c"): {"created": "2026-09-01T10:00:00", "expires": viejo, "ip": "3.3.3.3", "ua": "x"},
    }
    auth._atomic(auth.WEB_SESSIONS, sesiones)
    filas = auth.sesiones_web("tok-a")
    assert [f["ip"] for f in filas] == ["2.2.2.2", "1.1.1.1"]  # la vencida no, la mas nueva primero
    assert [f["actual"] for f in filas] == [False, True]
    assert all(len(f["id"]) == 16 and "tok" not in str(f) for f in filas)
    assert auth.check("tok-b")
    assert auth.revocar(filas[0]["id"]) is True
    assert not auth.check("tok-b") and auth.check("tok-a")
    for malo in ("", "../x", filas[0]["id"], "z" * 16, None):
        assert auth.revocar(malo) is False


def test_la_ruta_de_un_adjunto_se_traduce_para_wsl():
    assert tmux.ruta_wsl("C:\\Users\\a\\.lienzo\\adjuntos\\s\\m.md") == "/mnt/c/Users/a/.lienzo/adjuntos/s/m.md"
    assert tmux.ruta_wsl("D:/x/y.png") == "/mnt/d/x/y.png"
    assert tmux.ruta_wsl("/home/a/x") == "/home/a/x"


def test_compose_send_tipea_la_ruta_de_wsl_y_guarda_la_de_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(ses, "ADJUNTOS", str(tmp_path))
    ruta = ses.save_attachment("s1", "a.txt", b"x")
    final, _, adjuntos = ses.compose_send("s1", "mira", [ruta], wsl=True)
    assert adjuntos == [ruta]
    assert tmux.ruta_wsl(ruta) in final and ruta not in final
    final, _, _ = ses.compose_send("s1", "mira", [ruta])
    assert ruta in final


def test_lanzar_coda_con_modelo_avisa_que_cambia_el_default(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "_launch_cmd", lambda *a: {"ok": True})
    monkeypatch.setattr(launch, "_launch_tmux", lambda *a: {"ok": True})
    monkeypatch.setattr(launch, "_exe_path", lambda name: "coda.exe")
    monkeypatch.setattr(launch, "_cuota_coda", lambda: "ok")
    monkeypatch.setattr(launch, "_allowed_roots", lambda: [os.path.normcase(os.path.normpath(tmp_path))])
    res = launch.launch(str(tmp_path), "t", "coda", model="globant_dgx/GLM-5.3-Flash")
    assert res.get("model_applied") is True and "modelo por defecto" in res["aviso"]
    res = launch.launch(str(tmp_path), "t", "coda")
    assert "aviso" not in res
