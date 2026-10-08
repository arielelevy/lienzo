"""Límites de la vista de Chrome, sin inyectar entrada en ventanas del usuario."""
import io
import json
import struct
import zlib
from types import SimpleNamespace

import browser_window as module
import pytest


@pytest.mark.parametrize("value", [True, -1, 3841, "12", None])
def test_capture_dimensions_reject_invalid_values(value):
    with pytest.raises(ValueError):
        module.bounded(value, 1, 3840)


@pytest.mark.parametrize("value", ["", "-1", "123;calc", "1" * 21, 123])
def test_window_identifier_is_not_executable_or_arbitrary(value):
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: pytest.fail("inválido antes de consultar Windows")
    with pytest.raises(ValueError):
        windows.target(value)


def test_non_chrome_window_cannot_be_targeted():
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: False
    with pytest.raises(ValueError, match="no está disponible"):
        windows.target("123")


def test_no_keyboard_or_mouse_if_foreground_changed():
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd  # procesos distintos: la ventana activa no es de Chrome
    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 456,
                                   GetWindowThreadProcessId=lambda hwnd, pid: 2, AttachThreadInput=lambda source, target, attach: False,
                                   keybd_event=lambda *a: None, SwitchToThisWindow=lambda hwnd, alt: None, ShowWindow=lambda hwnd, cmd: None,
                                   SystemParametersInfoW=lambda *a: 1)
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.describe = lambda hwnd: "ConsoleWindowClass · Teorema · WindowsTerminal.exe"
    with pytest.raises(ValueError, match="no se envió la entrada. Al frente está: ConsoleWindowClass · Teorema · WindowsTerminal.exe"):
        windows.input(123, [{"kind": "key", "keyCode": 65, "modifiers": 0, "type": "keyDown"}])


def test_focus_taps_shift_before_the_second_try_and_then_attaches_the_foreground_thread():
    """Windows solo deja cambiar la ventana activa al proceso que recibio la ultima entrada: el toque
    de Shift sintetico convierte al worker en ese proceso (medido el 2026-10-08: con el escritorio
    abierto y otra ventana al frente, el aviso «no permitio activar Chrome» salia siempre)."""
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    calls = []
    foreground = [456]

    def set_foreground(hwnd):
        calls.append("foreground")
        if "shift" in calls:  # recien despues del Shift, Windows acepta
            foreground[0] = hwnd

    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=set_foreground,
                                   GetForegroundWindow=lambda: foreground[0],
                                   keybd_event=lambda vk, scan, flags, extra: calls.append("shift" if vk == 16 and flags == 0 else "shift-up"),
                                   GetWindowThreadProcessId=lambda hwnd, pid: 2,
                                   AttachThreadInput=lambda source, target, attach: calls.append("attach") or True,
                                   BringWindowToTop=lambda hwnd: calls.append("top"),
                                   SwitchToThisWindow=lambda hwnd, alt: calls.append("switch"),
                                   ShowWindow=lambda hwnd, cmd: calls.append({6: "min", 9: "restore"}.get(cmd, cmd)),
                                   SystemParametersInfoW=lambda *a: calls.append("lock0") or 1)
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.describe = lambda hwnd: "ConsoleWindowClass · x · conhost.exe"
    windows.focus(123)
    assert calls == ["lock0", "foreground", "shift", "shift-up", "foreground"]  # sin llegar al AttachThreadInput
    # si tampoco alcanza: enganchar el hilo del frente, SwitchToThisWindow, minimizar y restaurar,
    # y recien ahi el error, diciendo quien tiene el frente. El tiempo de bloqueo se pone una sola vez
    calls.clear()
    foreground[0] = 456
    windows.user.SetForegroundWindow = lambda hwnd: calls.append("foreground")
    with pytest.raises(ValueError, match="Al frente está: ConsoleWindowClass"):
        windows.focus(123)
    assert calls == ["foreground", "shift", "shift-up", "foreground", "attach", "top", "foreground", "attach", "switch", "min", "restore"]


def test_focus_succeeds_through_switch_or_restore_without_failing():
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    foreground = [456]

    def switch(hwnd, alt):
        foreground[0] = hwnd

    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None,
                                   GetForegroundWindow=lambda: foreground[0], keybd_event=lambda *a: None,
                                   GetWindowThreadProcessId=lambda hwnd, pid: 2, AttachThreadInput=lambda s_, t, a: False,
                                   SwitchToThisWindow=switch, ShowWindow=lambda hwnd, cmd: None, SystemParametersInfoW=lambda *a: 1)
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.focus(123)  # SwitchToThisWindow alcanzo: no hay error
    foreground[0] = 456
    windows.user.SwitchToThisWindow = lambda hwnd, alt: None
    windows.user.ShowWindow = lambda hwnd, cmd: foreground.__setitem__(0, hwnd) if cmd == 9 else None
    windows.focus(123)  # restaurar alcanzo


def test_focus_says_when_the_pc_is_locked():
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 0,
                                   keybd_event=lambda *a: None, GetWindowThreadProcessId=lambda hwnd, pid: 0,
                                   AttachThreadInput=lambda source, target, attach: False, SwitchToThisWindow=lambda hwnd, alt: None,
                                   ShowWindow=lambda hwnd, cmd: None, SystemParametersInfoW=lambda *a: 1)
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    with pytest.raises(ValueError, match="bloqueada"):
        windows.focus(123)


@pytest.mark.parametrize("key,modifiers", [(91, 0), (9, 1), (27, 10), (115, 1)])
def test_system_shortcuts_rejected_before_injection(key, modifiers):
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=1280, bottom=800)
    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 123)
    with pytest.raises(ValueError, match="atajo de Windows"):
        windows.input(123, [{"kind": "key", "keyCode": key, "modifiers": modifiers, "type": "keyDown"}])


def test_input_allows_chrome_popup_of_same_process():
    """Un menú contextual o un desplegable de Chrome es otra ventana del mismo proceso: traer la
    principal al frente lo cerraría, así que la entrada sigue sin cambiar el foco."""
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: True
    windows.owner = lambda hwnd: 99
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=100, bottom=100)
    calls = []

    def cursor(point):
        point._obj.x, point._obj.y = 5, 6  # byref(POINT): el fake escribe donde escribiría Windows
        return True

    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, GetForegroundWindow=lambda: 456,
                                   SetForegroundWindow=lambda hwnd: calls.append("foreground"),
                                   SetCursorPos=lambda x, y: True, mouse_event=lambda *a: calls.append(a), GetCursorPos=cursor)
    windows.mouse_pressed = set()
    windows.send_mouse = lambda flag: calls.append((flag, 0, 0, 0, 0))
    windows.input(123, [{"kind": "mouse", "type": "mousePressed", "x": 5, "y": 6, "button": "left"}])
    assert "foreground" not in calls and calls == [(2, 0, 0, 0, 0)]


def test_mouse_injection_reports_windows_rejection():
    class SendInput:
        def __call__(self, count, entry, size):
            return 0

    windows = module.Windows.__new__(module.Windows)
    windows.user = SimpleNamespace(SendInput=SendInput())
    with pytest.raises(ValueError, match="no aceptó el clic"):
        windows.send_mouse(2)


def test_control_a_restores_modifier_before_key_and_releases_it():
    windows = module.Windows.__new__(module.Windows)
    windows.focus = lambda hwnd: None
    windows.active = windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=1280, bottom=800)
    calls = []
    windows.user = SimpleNamespace(keybd_event=lambda *args: calls.append(args))
    windows.pressed = set()
    windows.input(1, [{"kind": "key", "keyCode": 65, "modifiers": 2, "type": "keyDown"},
                      {"kind": "key", "keyCode": 65, "modifiers": 2, "type": "keyUp"},
                      {"kind": "key", "keyCode": 17, "modifiers": 0, "type": "keyUp"}])
    assert calls == [(17, 0, 0, 0), (65, 0, 0, 0), (65, 0, 2, 0), (17, 0, 2, 0)]
    assert windows.pressed == set()


def test_popups_are_owned_by_selected_chrome_only_in_paint_order(monkeypatch):
    monkeypatch.setattr(module.c, "WINFUNCTYPE", module.c.CFUNCTYPE, raising=False)
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: 10 if hwnd != 4 else 20
    def enumerate_windows(callback, data):
        for hwnd in [1, 2, 3, 4, 5]:
            callback(hwnd, data)
        return True
    windows.user = SimpleNamespace(EnumWindows=enumerate_windows, IsWindowVisible=lambda hwnd: hwnd != 5,
                                   GetAncestor=lambda hwnd, flag: 1 if hwnd in [2, 4, 5] else hwnd)
    assert windows.popups(1) == [2]  # no otra ventana principal ni otro proceso ni un menú oculto


# --- captura continua (Streamer) y caja de cambios, sin Win32 ---------------------------------


def rgb(width, height, color=(255, 255, 255)):
    return bytes(color) * (width * height)


def paint(frame, width, x, y, w, h, color):
    data = bytearray(frame)
    for row in range(y, y + h):
        data[(row * width + x) * 3:(row * width + x + w) * 3] = bytes(color) * w
    return bytes(data)


def test_dirty_box_none_when_equal_and_tight_when_small_change():
    base = rgb(200, 100)
    assert module.dirty_box(base, base, 200, 100) is None
    changed = paint(base, 200, 70, 10, 5, 3, (0, 0, 0))
    assert module.dirty_box(base, changed, 200, 100) == (64, 10, 128, 13)


def test_dirty_box_full_width_when_most_rows_changed():
    base = rgb(200, 100)
    changed = paint(base, 200, 100, 0, 1, 80, (1, 2, 3))
    assert module.dirty_box(base, changed, 200, 100) == (0, 0, 200, 80)


def test_png_of_patch_decodes_to_the_region():
    frame = paint(rgb(8, 4), 8, 2, 1, 3, 2, (9, 8, 7))
    data = module.png(frame, 8, (2, 1, 5, 3))
    assert data.startswith(b"\x89PNG") and struct.unpack(">II", data[16:24]) == (3, 2)
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 4]
    assert zlib.decompress(idat) == (b"\x00" + bytes((9, 8, 7)) * 3) * 2


class FakeWindows:
    def __init__(self):
        self.inputs = []
        self.released = 0
        self.fits = []
        self.alive = True

    def target(self, value):
        return int(value)

    def chrome(self, hwnd):
        return self.alive

    def fit(self, hwnd, width, height):
        self.fits.append((hwnd, width, height))

    def input(self, hwnd, events):
        self.inputs.append((hwnd, events))

    def release(self):
        self.released += 1

    def windows(self):
        return [{"id": "7", "title": "Chrome"}]

    def cursor(self):
        return "default"


def make_streamer(frames):
    out = io.BytesIO()
    windows = FakeWindows()
    captures = []

    def capture(hwnd, width=None, height=None):
        captures.append((hwnd, width, height))
        return frames.pop(0), 8, 4

    streamer = module.Streamer(windows, out, capture=capture, clock=lambda: 0.0, sleep=lambda s: None)
    return streamer, out, windows, captures


def records(out):
    data = out.getvalue()
    items = []
    while data:
        n, kind = module.RECORD.unpack(data[:5])
        items.append((chr(kind), data[5:4 + n]))
        data = data[4 + n:]
    return items


def test_streamer_sends_full_then_patch_then_nothing_and_waits_for_acks():
    base = rgb(8, 4)
    changed = paint(base, 8, 1, 1, 1, 1, (0, 0, 0))
    streamer, out, windows, captures = make_streamer([base, base, changed, changed])
    streamer.handle({"t": "open", "window": "7", "width": 1280, "height": 720})
    assert json.loads(records(out)[0][1]) == {"t": "opened", "window": "7"}
    first = streamer.step()
    assert module.FRAME_HEADER.unpack(first[:module.FRAME_HEADER.size]) == (1, 0, 0, 8, 4, 8, 4, module.FRAME_FULL)
    assert captures[0] == (7, None, None) and windows.fits == [(7, 1280, 720)]
    assert streamer.step() is None  # sin cambios: nada viaja
    assert windows.fits == [(7, 1280, 720)]  # el ajuste de tamano no se repite cuadro a cuadro
    patch = streamer.step()
    assert module.FRAME_HEADER.unpack(patch[:module.FRAME_HEADER.size])[:5] == (2, 0, 1, 8, 1)
    assert streamer.in_flight == module.MAX_IN_FLIGHT
    streamer.handle({"t": "ack", "n": 1})
    assert streamer.in_flight == 1
    assert streamer.step() is None and streamer.in_flight == 1  # igual al último enviado


def test_cursor_changes_are_sent_even_when_image_is_unchanged():
    base = rgb(8, 4)
    streamer, out, windows, _ = make_streamer([base, base])
    streamer.handle({"t": "open", "window": "7"})
    assert streamer.step() is not None
    windows.cursor = lambda: "pointer"
    assert streamer.step() is None
    assert json.loads(records(out)[-1][1]) == {"t": "cursor", "cursor": "pointer"}


def test_streamer_input_acks_and_reports_failures():
    streamer, out, windows, _ = make_streamer([])
    streamer.handle({"t": "open", "window": "7"})
    streamer.handle({"t": "input", "n": 3, "events": [{"kind": "mouse"}]})
    assert windows.inputs == [(7, [{"kind": "mouse"}])]
    windows.input = lambda hwnd, events: module.fail("Cambió la ventana activa")
    streamer.handle({"t": "input", "n": 4, "events": []})
    texts = [json.loads(payload) for kind, payload in records(out) if kind == "J"]
    assert texts[1] == {"t": "input", "n": 3}
    assert texts[2] == {"t": "error", "input": True, "n": 4, "message": "Cambió la ventana activa"}


def test_streamer_capture_error_closes_window_and_release_on_eof():
    streamer, out, windows, _ = make_streamer([])
    streamer.capture = lambda hwnd, width=None, height=None: module.fail("Windows no pudo capturar Chrome")
    streamer.handle({"t": "open", "window": "7"})
    assert streamer.step() is None and streamer.hwnd is None
    assert b"no pudo capturar" in records(out)[-1][1]
    streamer.run(iter(['{"t": "windows"}', "no es json", '{"t": "raro"}']))
    texts = [json.loads(payload) for kind, payload in records(out) if kind == "J"]
    assert texts[-3]["windows"] == [{"id": "7", "title": "Chrome"}]
    assert texts[-2]["t"] == "error" and texts[-1]["message"] == "Pedido de ventana desconocido"
    assert streamer.closed and windows.released == 1


def test_streamer_reports_a_closed_window_and_pauses_when_hidden():
    streamer, out, windows, captures = make_streamer([rgb(8, 4)])
    streamer.handle({"t": "open", "window": "7"})
    streamer.handle({"t": "pause"})
    assert streamer.paused
    streamer.handle({"t": "resume"})
    assert not streamer.paused
    windows.alive = False
    assert streamer.step() is None and streamer.hwnd is None
    assert json.loads(records(out)[-1][1])["message"] == "Esa ventana de Chrome ya no está disponible"
    assert captures == []


def test_capture_thread_crash_is_reported_and_ends_the_worker():
    streamer, out, windows, _ = make_streamer([])

    def boom():
        raise AttributeError("argtypes")

    streamer.step = boom
    streamer.run_capture()
    assert streamer.closed
    assert "AttributeError" in json.loads(records(out)[-1][1])["message"]
    streamer.run(iter(['{"t": "windows"}']))
    assert not any(b"Chrome" in payload for _, payload in records(out))  # stdin ya no se atiende
