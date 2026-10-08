"""Ventanas reales de Chrome. Worker aislado; no controla otras aplicaciones."""
import base64
import ctypes as c
import json
import os
import struct
import sys
import zlib
from ctypes import wintypes as w
from pathlib import Path


def fail(message):
    raise ValueError(message)


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail("Valor de entrada fuera de rango")
    return value


class Windows:
    def __init__(self):
        if os.name != "nt":
            fail("La vista de ventana real requiere Windows en la PC de destino")
        self.user = c.WinDLL("user32", use_last_error=True)
        self.gdi = c.WinDLL("gdi32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.user.SetProcessDpiAwarenessContext.argtypes = [w.HANDLE]
        if not self.user.SetProcessDpiAwarenessContext(c.c_void_p(-4)):
            fail("No se pudo usar la resolución real de Windows para capturar Chrome")
        self.pressed = set()
        self.mouse_pressed = set()
        self.user.GetWindowDC.restype = w.HDC
        self.user.GetForegroundWindow.restype = w.HWND
        self.gdi.CreateCompatibleDC.restype = w.HDC
        self.gdi.CreateCompatibleBitmap.restype = w.HBITMAP
        self.gdi.SelectObject.restype = w.HANDLE
        self.kernel.OpenProcess.restype = w.HANDLE
        # Todos los handles conservan sus 64 bits al pasar a la API nativa.
        for dll, name, args in [
            (self.user, "GetWindowDC", [w.HWND]), (self.user, "ReleaseDC", [w.HWND, w.HDC]),
            (self.user, "PrintWindow", [w.HWND, w.HDC, w.UINT]),
            (self.user, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)]),
            (self.user, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "GetClassNameW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "IsWindowVisible", [w.HWND]), (self.user, "IsIconic", [w.HWND]),
            (self.user, "ShowWindow", [w.HWND, c.c_int]), (self.user, "SetForegroundWindow", [w.HWND]),
            (self.user, "IsZoomed", [w.HWND]),
            (self.user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]),
            (self.user, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL]),
            (self.user, "BringWindowToTop", [w.HWND]),
            (self.user, "SetCursorPos", [c.c_int, c.c_int]),
            (self.user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)]),
            (self.gdi, "CreateCompatibleDC", [w.HDC]),
            (self.gdi, "CreateCompatibleBitmap", [w.HDC, c.c_int, c.c_int]),
            (self.gdi, "SelectObject", [w.HDC, w.HANDLE]),
            (self.gdi, "DeleteObject", [w.HANDLE]), (self.gdi, "DeleteDC", [w.HDC]),
            (self.gdi, "GetDIBits", [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT]),
            (self.kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD]),
            (self.kernel, "CloseHandle", [w.HANDLE]),
            (self.kernel, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]),
        ]:
            getattr(dll, name).argtypes = args

    def chrome(self, hwnd):
        name = c.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, name, len(name))
        if name.value != "Chrome_WidgetWin_1" or not self.user.IsWindowVisible(hwnd):
            return False
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, c.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        try:
            path = c.create_unicode_buffer(32768)
            size = w.DWORD(len(path))
            return bool(self.kernel.QueryFullProcessImageNameW(process, 0, path, c.byref(size))) and Path(path.value).name.lower() == "chrome.exe"
        finally:
            self.kernel.CloseHandle(process)

    def windows(self):
        result = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def collect(hwnd, _):
            if self.chrome(hwnd):
                title = c.create_unicode_buffer(1024)
                self.user.GetWindowTextW(hwnd, title, len(title))
                result.append({"id": str(hwnd), "title": title.value or "Chrome"})
            return True

        self.user.EnumWindows(callback_type(collect), 0)
        foreground = str(self.user.GetForegroundWindow())
        return sorted(result, key=lambda item: item["id"] != foreground)

    def target(self, value):
        if not isinstance(value, str) or not value.isdecimal() or len(value) > 20:
            fail("Elegí una ventana de Chrome")
        hwnd = int(value)
        if not self.chrome(hwnd):
            fail("Esa ventana de Chrome ya no está disponible")
        return hwnd

    def rect(self, hwnd):
        rect = w.RECT()
        if not self.user.GetWindowRect(hwnd, c.byref(rect)):
            fail("No se pudo medir la ventana de Chrome")
        return rect

    def frame(self, hwnd, width=None, height=None):
        if width is not None or height is not None:
            bounded(width, 320, 3840)
            bounded(height, 200, 2160)
            if self.user.IsZoomed(hwnd):
                self.user.ShowWindow(hwnd, 9)
            rect = self.rect(hwnd)
            if (rect.right - rect.left, rect.bottom - rect.top) != (width, height):
                if not self.user.SetWindowPos(hwnd, None, 0, 0, width, height, 0x16):
                    fail("Windows no permitió ajustar el tamaño de Chrome")
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        rect = self.rect(hwnd)
        width, height = rect.right - rect.left, rect.bottom - rect.top
        bounded(width, 1, 3840)
        bounded(height, 1, 2160)
        dc = self.user.GetWindowDC(hwnd)
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, width, height)
        previous = self.gdi.SelectObject(memory, bitmap)
        try:
            if not dc or not memory or not bitmap or not self.user.PrintWindow(hwnd, memory, 2):
                fail("Windows no pudo capturar Chrome. La sesión debe estar abierta y desbloqueada")
            info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
            pixels = c.create_string_buffer(width * height * 4)
            self.gdi.SelectObject(memory, previous)
            if self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
                fail("Windows no pudo leer la imagen de Chrome")
            rgb = bytearray(width * height * 3)
            bgra = pixels.raw
            rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
            rows = b"".join(b"\0" + rgb[i:i + width * 3] for i in range(0, len(rgb), width * 3))
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b"")
            return {"image": base64.b64encode(png).decode(), "format": "png", "width": width, "height": height}
        finally:
            self.gdi.SelectObject(memory, previous)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(hwnd, dc)

    def input(self, hwnd, events):
        if not isinstance(events, list) or len(events) > 64:
            fail("Demasiados eventos de entrada")
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        self.user.SetForegroundWindow(hwnd)
        if self.user.GetForegroundWindow() != hwnd:
            foreground = self.user.GetForegroundWindow()
            foreground_thread = self.user.GetWindowThreadProcessId(foreground, None)
            current_thread = self.kernel.GetCurrentThreadId()
            attached = foreground_thread != current_thread and self.user.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                if attached:
                    self.user.BringWindowToTop(hwnd)
                    self.user.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    self.user.AttachThreadInput(current_thread, foreground_thread, False)
        if self.user.GetForegroundWindow() != hwnd:
            fail("Windows no permitió activar Chrome; no se envió la entrada")
        rect = self.rect(hwnd)
        for event in events:
            if self.user.GetForegroundWindow() != hwnd or not self.chrome(hwnd):
                fail("Cambió la ventana activa; la entrada se detuvo")
            kind = event.get("kind")
            if kind == "mouse":
                x = bounded(event.get("x"), 0, rect.right - rect.left - 1)
                y = bounded(event.get("y"), 0, rect.bottom - rect.top - 1)
                if not self.user.SetCursorPos(rect.left + x, rect.top + y):
                    fail("Windows no permitió mover el mouse de Chrome; no se envió el clic")
                flags = {("mousePressed", "left"): 2, ("mouseReleased", "left"): 4,
                         ("mousePressed", "right"): 8, ("mouseReleased", "right"): 16,
                         ("mousePressed", "middle"): 32, ("mouseReleased", "middle"): 64}
                if event.get("type") == "mouseWheel":
                    delta = -bounded(event.get("deltaY"), -4000, 4000)
                    self.user.mouse_event(0x800, 0, 0, delta, 0)
                elif event.get("type") != "mouseMoved":
                    flag = flags.get((event.get("type"), event.get("button")))
                    if not flag:
                        fail("Botón de mouse inválido")
                    self.user.mouse_event(flag, 0, 0, 0, 0)
                    if event["type"] == "mousePressed":
                        self.mouse_pressed.add(event["button"])
                    else:
                        self.mouse_pressed.discard(event["button"])
            elif kind == "key":
                key = bounded(event.get("keyCode"), 1, 255)
                modifiers = bounded(event.get("modifiers"), 0, 15)
                if key in (91, 92, 93) or (modifiers & 1 and key in (9, 27, 115)) or (modifiers & 2 and modifiers & 8 and key == 27):
                    fail("Ese atajo de Windows no se admite en Chrome remoto")
                if event.get("type") not in ("keyDown", "keyUp"):
                    fail("Tipo de tecla inválido")
                self.user.keybd_event(key, 0, 2 if event["type"] == "keyUp" else 0, 0)
                if event["type"] == "keyDown":
                    self.pressed.add(key)
                else:
                    self.pressed.discard(key)
            elif kind == "text":
                self.text(event.get("text"))
            else:
                fail("Entrada de ventana desconocida")
        return {"ok": True}

    def text(self, text):
        if not isinstance(text, str) or len(text) > 16000:
            fail("Texto inválido o demasiado grande")
        class Keyboard(c.Structure):
            _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        class Payload(c.Union):
            _fields_ = [("key", Keyboard), ("padding", c.c_byte * (32 if c.sizeof(c.c_void_p) == 8 else 24))]
        class Input(c.Structure):
            _fields_ = [("type", w.DWORD), ("payload", Payload)]
        codes = struct.unpack("<" + "H" * (len(text.encode("utf-16-le")) // 2), text.encode("utf-16-le"))
        inputs = (Input * (len(codes) * 2))()
        for i, code in enumerate(codes):
            for offset, flags in ((0, 4), (1, 6)):
                inputs[2 * i + offset].type = 1
                inputs[2 * i + offset].payload.key = Keyboard(0, code, flags, 0, 0)
        self.user.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
        modifiers = self.pressed & {16, 17, 18}
        for key in modifiers:
            self.user.keybd_event(key, 0, 2, 0)
        try:
            if inputs and self.user.SendInput(len(inputs), inputs, c.sizeof(Input)) != len(inputs):
                fail("Windows no permitió pegar todo el texto")
        finally:
            for key in modifiers:
                self.user.keybd_event(key, 0, 0, 0)

    def release(self):
        for key in self.pressed:
            self.user.keybd_event(key, 0, 2, 0)
        self.pressed.clear()
        for button in self.mouse_pressed:
            self.user.mouse_event({"left": 4, "right": 16, "middle": 64}[button], 0, 0, 0, 0)
        self.mouse_pressed.clear()
        return {"ok": True}


def main():
    windows = Windows()
    for line in sys.stdin:
        try:
            data = json.loads(line)
            action = data.get("action")
            if action == "windows":
                result = {"windows": windows.windows()}
            elif action == "window-frame":
                result = windows.frame(windows.target(data.get("window")), data.get("width"), data.get("height"))
            elif action == "window-input":
                result = windows.input(windows.target(data.get("window")), data.get("events"))
            elif action == "window-release":
                result = windows.release()
            else:
                fail("Acción de ventana desconocida")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result = {"status": 409, "error": str(exc)}
        print(json.dumps(result), flush=True)
    windows.release()


if __name__ == "__main__":
    main()
