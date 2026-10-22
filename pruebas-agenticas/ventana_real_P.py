"""Encargo P (2026-10-22): la ventana completa contra un Chrome real y aislado.

Abre un Chrome con perfil temporal y una página que scrollea sola (ventana_real_P.html), graba capturas
reales con browser_window.Windows.capture y arma la cadena de cuadros v2 como el worker. Verifica que lo
que reconstruye el visor (copia de scroll + parches PNG) sea idéntico, pixel a pixel, a cada captura, y
dice cuántos bytes viajaron. No toca el Chrome de la persona: sólo la ventana con el título de la página.
Sale 0 si todo coincide, 1 si no, 2 si no se pudo preparar.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lienzo"))
import browser_window as bw

CHROME = Path(os.environ.get("ProgramFiles", "C:/Program Files"), "Google/Chrome/Application/chrome.exe")
TITLE = "P-VENTANA-REAL"


def decode_png(data):
    """Las filas RGB de un PNG de browser_window.png (sin filtros) pasadas a BGRA."""
    width, height = int.from_bytes(data[16:20]), int.from_bytes(data[20:24])
    rows = zlib.decompress(data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 4])
    out = bytearray(b"\xff" * (width * height * 4))
    for r in range(height):
        line = rows[r * (width * 3 + 1) + 1 : (r + 1) * (width * 3 + 1)]
        out[r * width * 4 : (r + 1) * width * 4 : 4] = line[2::3]
        out[r * width * 4 + 1 : (r + 1) * width * 4 : 4] = line[1::3]
        out[r * width * 4 + 2 : (r + 1) * width * 4 : 4] = line[0::3]
    return width, height, bytes(out)


def apply(canvas, width, payload):
    """Lo que hace el visor con un cuadro v2 (RemoteBrowser.tsx): corre la imagen y pega los parches."""
    pos = bw.FRAME_HEADER.size
    *_, flags = bw.FRAME_HEADER.unpack(payload[:pos])
    dy, x0, x1, top, bottom, count = bw.SCROLL.unpack(payload[pos : pos + bw.SCROLL.size])
    pos += bw.SCROLL.size
    out = bytearray(bw.shifted(canvas, width, (dy, x0, x1, top, bottom)) if dy else canvas)
    for _ in range(count):
        x, y, w, h, n = bw.PATCH.unpack(payload[pos : pos + bw.PATCH.size])
        pos += bw.PATCH.size
        pw, ph, pixels = decode_png(payload[pos : pos + n])
        assert (pw, ph) == (w, h)
        pos += n
        for r in range(h):
            out[((y + r) * width + x) * 4 : ((y + r) * width + x + w) * 4] = pixels[r * w * 4 : (r + 1) * w * 4]
    assert pos == len(payload)
    return bytes(out), bool(flags & bw.FRAME_FULL)


def main():
    if not CHROME.is_file():
        print(f"No está Chrome en {CHROME}")
        return 2
    profile = tempfile.mkdtemp(prefix=f"P-ventana-{os.getpid()}-")
    page = (Path(__file__).with_name("ventana_real_P.html")).as_uri() + "#scroll"
    chrome = subprocess.Popen(
        [
            str(CHROME),
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-crash-restore-bubble",
            "--disable-features=CalculateNativeWinOcclusion",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--new-window",
            "--window-size=1280,800",
            page,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        win = bw.Windows()
        hwnd = None
        for _ in range(40):
            time.sleep(0.25)
            mine = [w for w in win.windows() if w["title"].startswith(TITLE)]
            if mine:
                hwnd = int(mine[0]["id"])
                break
        if hwnd is None:
            print("Chrome aislado no mostró la ventana de prueba")
            return 2
        time.sleep(1.5)
        frames = []
        for _ in range(40):
            frames.append(win.capture(hwnd))
            time.sleep(0.05)
        last = canvas = None
        sent = scrolls = mismatches = 0
        total = 0
        for seq, (pixels, width, height) in enumerate(frames, 1):
            payload = bw.frame_v2(seq, pixels, width, height, last)
            if payload is None:
                continue
            canvas, full = apply(canvas or bytes(width * height * 4), width, payload)
            sent += 1
            total += len(payload)
            scrolls += bool(bw.SCROLL.unpack(payload[bw.FRAME_HEADER.size : bw.FRAME_HEADER.size + bw.SCROLL.size])[0])
            if canvas != pixels:
                mismatches += 1
            last = pixels
        print(
            f"{width}x{height}: {len(frames)} capturas, {sent} cuadros, {scrolls} con copia de scroll, "
            f"{total / max(1, sent) / 1024:.1f} KB por cuadro, {mismatches} reconstrucciones distintas"
        )
        if mismatches or sent < 10 or scrolls < sent // 2:
            print("FALLA: la reconstrucción no coincide o casi no hubo scroll")
            return 1
        print("OK: el visor reconstruye exacto cada captura real")
        return 0
    finally:
        chrome.kill()
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
