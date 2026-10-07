"""Propuesta de prueba real aislada. Chrome headless propio + web local; no usa cuentas ni peers reales.

Ejecutar desde la raíz: py tests/browser_smoke.py
"""

import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lienzo"))
import browser_remote
import state

PAGE = b"""<!doctype html><title>Inicio</title><style>body{margin:0}input,button{display:block;width:220px;height:50px}</style>
<input autofocus aria-label="Texto" oninput="document.title=this.value">
<button onclick="document.title='Click remoto'">Probar click</button>
<a href="/segunda">Segunda</a>"""


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b"<!doctype html><title>Segunda</title><p>Otra pagina</p>" if self.path == "/segunda" else PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        return  # fixture local: el resultado se registra por aserciones


def main():
    web = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    host = browser_remote.BrowserHost()
    evidence = ROOT / "pruebas-agenticas/resultados/chrome"
    evidence.mkdir(parents=True, exist_ok=True)

    def call(action, **kwargs):
        code, result = host.request({"action": action, **kwargs})
        assert code == 200, (action, code, result)
        return result

    def wait_title(tab, title):
        for _ in range(40):
            if any(t["id"] == tab and t["title"] == title for t in call("state")["tabs"]):
                return
            time.sleep(0.1)
        raise AssertionError(f"Chrome no mostro {title}")

    try:
        with tempfile.TemporaryDirectory(prefix="lienzo-chrome-test-") as folder:
            state.LIENZO = folder
            try:
                tab = call("start")["tabs"][0]["id"]
                url = f"http://127.0.0.1:{web.server_port}"
                call("navigate", tab=tab, url=url)
                wait_title(tab, "Inicio")
                call("input", tab=tab, events=[{"kind": "text", "text": "Teclado desde Lienzo"}])
                wait_title(tab, "Teclado desde Lienzo")
                events = [
                    {
                        "kind": "mouse",
                        "type": kind,
                        "x": 100,
                        "y": 78,
                        "button": "left",
                        "buttons": buttons,
                        "modifiers": 0,
                        "clickCount": 1,
                    }
                    for kind, buttons in [("mousePressed", 1), ("mouseReleased", 0)]
                ]
                call("input", tab=tab, events=events)
                wait_title(tab, "Click remoto")
                frame = call("frame", tab=tab, width=1280, height=800)
                image = base64.b64decode(frame["image"])
                assert image.startswith(b"\xff\xd8") and len(image) > 1000
                (evidence / "chrome-real.jpg").write_bytes(image)
                call("navigate", tab=tab, url=url + "/segunda")
                wait_title(tab, "Segunda")
                call("history", tab=tab, direction=-1)
                # La primera pagina puede volver desde bfcache con su titulo modificado.
                for _ in range(40):
                    current = next(t for t in call("state")["tabs"] if t["id"] == tab)
                    if current["url"].rstrip("/") == url:
                        break
                    time.sleep(0.1)
                assert current["url"].rstrip("/") == url
                second = call("new", url="about:blank")["id"]
                assert len(call("state")["tabs"]) == 2
                call("close", tab=second)
                assert len(call("state")["tabs"]) == 1
                assert host.request({"action": "navigate", "tab": tab, "url": "file:///C:/Windows/win.ini"})[0] == 400
                if sys.platform == "win32":
                    # Sólo se comparte el Chrome de prueba, sin perfiles/cuentas del usuario.
                    port = (Path(folder) / "chrome-remoto/DevToolsActivePort").read_text()
                    mock_local = Path(folder) / "localappdata"
                    mock_data = mock_local / "Google/Chrome/User Data"
                    mock_data.mkdir(parents=True)
                    (mock_data / "DevToolsActivePort").write_text(port)
                    saved_local = os.environ.get("LOCALAPPDATA")
                    attached = browser_remote.BrowserHost()
                    try:
                        os.environ["LOCALAPPDATA"] = str(mock_local)
                        assert attached.request({"action": "connect"})[0] == 200
                        for _ in range(40):
                            code, result = attached.request({"action": "state"})
                            assert code == 200, result
                            if result.get("running"):
                                break
                            time.sleep(0.1)
                        assert result.get("running"), result
                        assert result["mode"] == "existing"
                        assert attached.request({"action": "frame", "tab": tab, "width": 1280, "height": 800})[0] == 200
                        assert attached.request({"action": "stop"})[0] == 200
                        assert call("state")["running"], "Desconectar no debe cerrar el Chrome compartido"
                        assert call("frame", tab=tab, width=1280, height=800)["image"]
                    finally:
                        attached.close()
                        if saved_local is None:
                            os.environ.pop("LOCALAPPDATA", None)
                        else:
                            os.environ["LOCALAPPDATA"] = saved_local
                call("stop")
                assert call("state")["running"] is False
                print(
                    json.dumps(
                        {
                            "chrome_real": True,
                            "checks": [
                                "start",
                                "navigate",
                                "text",
                                "mouse",
                                "screenshot",
                                "history",
                                "tabs",
                                "reject-file",
                                "attach-and-detach-without-closing" if sys.platform == "win32" else "attach-not-tested",
                                "stop",
                            ],
                        }
                    )
                )
            finally:
                host.close()
    finally:
        web.shutdown()
        web.server_close()


if __name__ == "__main__":
    main()
