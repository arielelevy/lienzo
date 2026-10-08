"""Ventanas reales de Chrome. Worker aislado; no controla otras aplicaciones.

Dos modos sobre el mismo codigo Win32:
- pedido/respuesta por lineas JSON (`windows`, `window-frame`, `window-input`, `window-release`);
- `--stream`: captura continua con acuse por cuadro y entrada por el mismo canal. stdout pasa a
  ser binario: registros `>IB` (largo, tipo) con J = JSON y F = cuadro (FRAME_HEADER + PNG).
"""
import base64
import ctypes as c
import json
import os
import secrets
import struct
import sys
import threading
import time
import zlib
from ctypes import wintypes as w
from pathlib import Path

FRAME_HEADER = struct.Struct(">IHHHHHHB")  # seq, x, y, ancho, alto, ancho total, alto total, flags
FRAME_FULL = 1  # flags: el cuadro es completo (reemplaza todo), no un parche
SYSTEM_CURSORS = {32512: "default", 32513: "text", 32514: "wait", 32515: "crosshair", 32642: "nwse-resize",
                  32643: "nesw-resize", 32644: "ew-resize", 32645: "ns-resize", 32646: "move", 32648: "not-allowed",
                  32649: "pointer", 32650: "progress", 32651: "help"}
RECORD = struct.Struct(">IB")
MAX_IN_FLIGHT = 2  # cuadros sin acusar antes de frenar la captura: acota la cola, no la pierde
MIN_INTERVAL_S = 1 / 60
IDLE_INTERVAL_S = 0.04  # sin cambios se mira 25 veces por segundo durante IDLE_FAST_STEPS lecturas...
IDLE_SLOW_S = 0.15  # ...y despues 6 veces por segundo; la entrada del visor vuelve al ritmo rapido
IDLE_FAST_STEPS = 50


def fail(message):
    raise ValueError(message)


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail("Valor de entrada fuera de rango")
    return value


def dirty_box(old, new, width, height, step=64):
    """(left, top, right, bottom) de lo que cambio entre dos cuadros RGB del mismo tamano, o None.
    Las filas se comparan enteras (memcmp); las columnas de a `step` pixeles y solo en las filas
    que cambiaron; si cambio mas de la mitad de las filas (scroll) va el ancho entero sin mirar."""
    stride = width * 3
    o, n = memoryview(old), memoryview(new)
    changed = [y for y in range(height) if n[y * stride:(y + 1) * stride] != o[y * stride:(y + 1) * stride]]
    if not changed:
        return None
    top, bottom = changed[0], changed[-1] + 1
    if len(changed) > height // 2:
        return 0, top, width, bottom
    left, right = width, 0
    for y in changed:
        offset = y * stride
        for x in range(0, width, step):
            end = min(width, x + step)
            if left <= x and end <= right:
                continue  # ya adentro de la caja
            if n[offset + x * 3:offset + end * 3] != o[offset + x * 3:offset + end * 3]:
                left, right = min(left, x), max(right, end)
    return left, top, right, bottom


def png(rgb, width, box):
    """PNG RGB de 8 bits de la caja (left, top, right, bottom) de un cuadro de `width` pixeles."""
    left, top, right, bottom = box
    rows = b"".join(b"\0" + rgb[(y * width + left) * 3:(y * width + right) * 3] for y in range(top, bottom))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", right - left, bottom - top, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b"")


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
        self.previous_frame = None
        self.user.GetWindowDC.restype = w.HDC
        self.user.GetForegroundWindow.restype = w.HWND
        self.user.GetAncestor.restype = w.HWND
        self.user.LoadCursorW.restype = w.HANDLE
        self.user.LoadCursorW.argtypes = [w.HINSTANCE, c.c_void_p]
        self.cursor_shapes = {self.user.LoadCursorW(None, c.c_void_p(number)): shape for number, shape in SYSTEM_CURSORS.items()}
        self.user.MonitorFromWindow.restype = w.HANDLE
        self.gdi.CreateCompatibleDC.restype = w.HDC
        self.gdi.CreateCompatibleBitmap.restype = w.HBITMAP
        self.gdi.SelectObject.restype = w.HANDLE
        self.kernel.OpenProcess.restype = w.HANDLE
        # Todos los handles conservan sus 64 bits al pasar a la API nativa.
        for dll, name, args in [
            (self.user, "GetWindowDC", [w.HWND]), (self.user, "ReleaseDC", [w.HWND, w.HDC]),
            (self.user, "PrintWindow", [w.HWND, w.HDC, w.UINT]),
            (self.user, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)]),
            (self.user, "GetAncestor", [w.HWND, w.UINT]),
            (self.user, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "GetClassNameW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "IsWindowVisible", [w.HWND]), (self.user, "IsIconic", [w.HWND]),
            (self.user, "ShowWindow", [w.HWND, c.c_int]), (self.user, "SetForegroundWindow", [w.HWND]),
            (self.user, "IsZoomed", [w.HWND]),
            (self.user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]),
            (self.user, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL]),
            (self.user, "BringWindowToTop", [w.HWND]),
            (self.user, "SetCursorPos", [c.c_int, c.c_int]),
            (self.user, "GetCursorPos", [c.POINTER(w.POINT)]),
            (self.user, "MonitorFromWindow", [w.HWND, w.DWORD]),
            (self.user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)]),
            (self.gdi, "CreateCompatibleDC", [w.HDC]),
            (self.gdi, "CreateCompatibleBitmap", [w.HDC, c.c_int, c.c_int]),
            (self.gdi, "SelectObject", [w.HDC, w.HANDLE]),
            (self.gdi, "BitBlt", [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.HDC, c.c_int, c.c_int, w.DWORD]),
            (self.gdi, "DeleteObject", [w.HANDLE]), (self.gdi, "DeleteDC", [w.HDC]),
            (self.gdi, "GetDIBits", [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT]),
            (self.kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD]),
            (self.kernel, "CloseHandle", [w.HANDLE]),
            (self.kernel, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]),
        ]:
            getattr(dll, name).argtypes = args

    def owner(self, hwnd):
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, c.byref(pid))
        return pid.value

    def chrome(self, hwnd):
        name = c.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, name, len(name))
        if name.value != "Chrome_WidgetWin_1" or not self.user.IsWindowVisible(hwnd):
            return False
        process = self.kernel.OpenProcess(0x1000, False, self.owner(hwnd))
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

    def fit(self, hwnd, width, height):
        """Deja la ventana del tamano pedido, dentro del area util de su monitor, sin moverla si
        ya entra. Solo toca la ventana validada de chrome.exe."""
        bounded(width, 320, 3840)
        bounded(height, 200, 2160)
        if self.user.IsZoomed(hwnd):
            self.user.ShowWindow(hwnd, 9)

        class MonitorInfo(c.Structure):
            _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]

        self.user.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = c.sizeof(info)
        if not self.user.GetMonitorInfoW(self.user.MonitorFromWindow(hwnd, 2), c.byref(info)):
            fail("Windows no pudo medir el escritorio de Chrome")
        width = min(width, info.work.right - info.work.left)
        height = min(height, info.work.bottom - info.work.top)
        rect = self.rect(hwnd)
        left = max(info.work.left, min(rect.left, info.work.right - width))
        top = max(info.work.top, min(rect.top, info.work.bottom - height))
        current = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        if current != (left, top, width, height) and not self.user.SetWindowPos(hwnd, None, left, top, width, height, 0x14):
            fail("Windows no permitió ajustar el tamaño de Chrome")

    def popups(self, hwnd):
        """Ventanas visibles propiedad de esta ventana de Chrome, en orden de abajo a arriba."""
        result = []
        pid = self.owner(hwnd)
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def collect(candidate, _):
            if candidate != hwnd and self.user.IsWindowVisible(candidate) and self.owner(candidate) == pid and self.user.GetAncestor(candidate, 3) == hwnd:
                result.append(candidate)
            return True

        self.user.EnumWindows(callback_type(collect), 0)
        return list(reversed(result))

    def cursor(self):
        class CursorInfo(c.Structure):
            _fields_ = [("size", w.DWORD), ("flags", w.DWORD), ("handle", w.HANDLE), ("position", w.POINT)]

        info = CursorInfo()
        info.size = c.sizeof(info)
        self.user.GetCursorInfo.argtypes = [c.POINTER(CursorInfo)]
        if not self.user.GetCursorInfo(c.byref(info)):
            fail("Windows no pudo leer el cursor de Chrome")
        return self.cursor_shapes.get(info.handle, "default")

    def paint_popup(self, hwnd, target, base):
        rect = self.rect(hwnd)
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if rect.right <= base.left or rect.left >= base.right or rect.bottom <= base.top or rect.top >= base.bottom:
            return
        bounded(width, 1, 3840)
        bounded(height, 1, 2160)
        memory = self.gdi.CreateCompatibleDC(target)
        bitmap = self.gdi.CreateCompatibleBitmap(target, width, height)
        old = self.gdi.SelectObject(memory, bitmap)
        try:
            if not memory or not bitmap or not self.user.PrintWindow(hwnd, memory, 2):
                if not self.user.IsWindowVisible(hwnd):
                    return  # se cerró durante la captura
                fail("Windows no pudo capturar el aviso o menú de Chrome")
            if not self.gdi.BitBlt(target, rect.left - base.left, rect.top - base.top, width, height, memory, 0, 0, 0x00CC0020):
                fail("Windows no pudo mostrar el aviso o menú de Chrome")
        finally:
            self.gdi.SelectObject(memory, old)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)

    def capture(self, hwnd, width=None, height=None):
        """(rgb, ancho, alto) de la ventana; si se pide tamano, primero la ajusta."""
        if width is not None or height is not None:
            self.fit(hwnd, width, height)
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        rect = self.rect(hwnd)
        width, height = rect.right - rect.left, rect.bottom - rect.top
        bounded(width, 1, 3840)
        bounded(height, 1, 2160)
        dc = self.user.GetWindowDC(hwnd)
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, width, height)
        old_bitmap = self.gdi.SelectObject(memory, bitmap)
        try:
            if not dc or not memory or not bitmap or not self.user.PrintWindow(hwnd, memory, 2):
                fail("Windows no pudo capturar Chrome. La sesión debe estar abierta y desbloqueada")
            for popup in self.popups(hwnd):
                self.paint_popup(popup, memory, rect)
            info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
            pixels = c.create_string_buffer(width * height * 4)
            self.gdi.SelectObject(memory, old_bitmap)
            if self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
                fail("Windows no pudo leer la imagen de Chrome")
            rgb = bytearray(width * height * 3)
            bgra = pixels.raw
            rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
            return bytes(rgb), width, height
        finally:
            self.gdi.SelectObject(memory, old_bitmap)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(hwnd, dc)

    def frame(self, hwnd, width=None, height=None, delta=False, base=None):
        """Modo pedido/respuesta: un cuadro (o un parche sobre `base`) en base64."""
        if type(delta) is not bool or (base is not None and (not isinstance(base, str) or len(base) > 32)):
            fail("Referencia de imagen inválida")
        if width is not None or height is not None:
            bounded(width, 320, 3840)
            bounded(height, 200, 2160)
        rgb, width, height = self.capture(hwnd, width, height)
        box = (0, 0, width, height)
        previous = self.previous_frame
        patch_base = None
        if delta and previous and previous[:3] == (hwnd, width, height) and base == previous[3]:
            box = dirty_box(previous[4], rgb, width, height)
            if box is None:
                return {"unchanged": True, "frameId": base, "width": width, "height": height}
            if (box[2] - box[0]) * (box[3] - box[1]) < width * height * 0.7:
                patch_base = base
            else:
                box = (0, 0, width, height)
        frame_id = secrets.token_hex(16)
        self.previous_frame = (hwnd, width, height, frame_id, rgb)
        result = {"image": base64.b64encode(png(rgb, width, box)).decode(), "format": "png", "width": width, "height": height, "frameId": frame_id}
        if patch_base:
            result["patch"] = {"base": patch_base, "x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]}
        return result

    def active(self, hwnd):
        """Chrome recibe la entrada si su ventana esta al frente o si lo esta uno de sus menus o
        desplegables (ventanas del mismo proceso): traerla al frente ahi cerraria el menu."""
        foreground = self.user.GetForegroundWindow()
        return foreground == hwnd or (bool(foreground) and self.owner(foreground) == self.owner(hwnd))

    def focus(self, hwnd):
        """Trae la ventana de Chrome al frente para mandarle la entrada. Windows solo le deja cambiar
        la ventana activa al proceso que recibio la ultima entrada del usuario (el worker nunca la
        recibe): primero se pide derecho; despues con un toque de Shift sintetico (keybd_event: baja
        y sube, solo no hace nada en ninguna ventana) que convierte al worker en ese proceso; y al
        final enganchando la cola de entrada del hilo que tiene el frente (AttachThreadInput). Sin
        ventana al frente no hay escritorio activo (PC bloqueada o protector de pantalla) y ningun
        truco sirve: se dice eso. Medido el 2026-10-08: el aviso «no permitio activar Chrome» salia
        con el escritorio abierto y otra ventana al frente."""
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        if self.active(hwnd):
            return
        self.user.SetForegroundWindow(hwnd)
        if self.user.GetForegroundWindow() != hwnd:
            # Shift y no Alt: un Alt solo deja a la ventana que lo recibe (una consola, Explorer, el
            # mismo Chrome) con la barra de menu enfocada y se traga la tecla siguiente
            self.user.keybd_event(16, 0, 0, 0)  # Shift abajo
            self.user.keybd_event(16, 0, 2, 0)  # Shift arriba
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
            if not self.user.GetForegroundWindow():
                fail("La PC está bloqueada o sin escritorio activo: Chrome no puede recibir la entrada")
            fail("Windows no permitió activar Chrome; no se envió la entrada")

    def input(self, hwnd, events):
        if not isinstance(events, list) or len(events) > 64:
            fail("Demasiados eventos de entrada")
        self.focus(hwnd)
        rect = self.rect(hwnd)
        for event in events:
            if not self.active(hwnd) or not self.chrome(hwnd):
                fail("Cambió la ventana activa; la entrada se detuvo")
            kind = event.get("kind")
            if kind == "mouse":
                x = bounded(event.get("x"), 0, rect.right - rect.left - 1)
                y = bounded(event.get("y"), 0, rect.bottom - rect.top - 1)
                if not self.user.SetCursorPos(rect.left + x, rect.top + y):
                    fail("Windows no permitió mover el mouse de Chrome; no se envió el clic")
                actual = w.POINT()
                if not self.user.GetCursorPos(c.byref(actual)) or (actual.x, actual.y) != (rect.left + x, rect.top + y):
                    fail("Windows limitó la posición del mouse; no se envió el clic fuera de lugar")
                flags = {("mousePressed", "left"): 2, ("mouseReleased", "left"): 4,
                         ("mousePressed", "right"): 8, ("mouseReleased", "right"): 16,
                         ("mousePressed", "middle"): 32, ("mouseReleased", "middle"): 64}
                if event.get("type") == "mouseWheel":
                    delta = -bounded(event.get("deltaY"), -4000, 4000)
                    self.send_mouse(0x800, delta)
                elif event.get("type") != "mouseMoved":
                    flag = flags.get((event.get("type"), event.get("button")))
                    if not flag:
                        fail("Botón de mouse inválido")
                    self.send_mouse(flag)
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
                if key not in (16, 17, 18):
                    for bit, modifier in ((1, 18), (2, 17), (8, 16)):
                        desired = bool(modifiers & bit)
                        if desired != (modifier in self.pressed):
                            self.user.keybd_event(modifier, 0, 0 if desired else 2, 0)
                            if desired:
                                self.pressed.add(modifier)
                            else:
                                self.pressed.discard(modifier)
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

    def send_mouse(self, flags, delta=0):
        """Entrada Win32 con resultado verificable; mouse_event no informa si se insertó."""
        class Mouse(c.Structure):
            _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("data", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]

        class Payload(c.Union):
            _fields_ = [("mouse", Mouse)]

        class Input(c.Structure):
            _fields_ = [("type", w.DWORD), ("payload", Payload)]

        entry = Input(0, Payload(mouse=Mouse(0, 0, delta & 0xFFFFFFFF, flags, 0, 0)))
        self.user.SendInput.argtypes = [w.UINT, c.c_void_p, c.c_int]
        if self.user.SendInput(1, c.byref(entry), c.sizeof(Input)) != 1:
            fail("Windows no aceptó el clic o la rueda de Chrome; revisá que Chrome no esté ejecutándose como administrador")

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
            self.send_mouse({"left": 4, "right": 16, "middle": 64}[button])
        self.mouse_pressed.clear()
        return {"ok": True}


class Streamer:
    """Captura continua de una ventana con acuse por cuadro; la entrada llega por stdin y sale por
    el mismo stdout binario. `capture(hwnd, width, height)` se inyecta en las pruebas."""

    def __init__(self, windows, out, capture=None, clock=time.monotonic, sleep=time.sleep):
        self.windows = windows
        self.out = out
        self.capture = capture or windows.capture
        self.clock = clock
        self.sleep = sleep
        self.out_lock = threading.Lock()
        self.cv = threading.Condition()
        self.hwnd = None
        self.size = None
        self.refit = False  # ajustar la ventana al tamano pedido en la proxima captura (open/size)
        self.last_cursor = None
        self.paused = False  # el visor esta en una solapa oculta: no capturar hasta que vuelva
        self.in_flight = 0
        self.seq = 0
        self.idle = 0  # lecturas seguidas sin cambios
        self.last = None  # (hwnd, ancho, alto, rgb) del ultimo cuadro enviado
        self.closed = False

    def emit(self, kind, payload):
        with self.out_lock:
            self.out.write(RECORD.pack(len(payload) + 1, ord(kind)) + payload)
            self.out.flush()

    def json(self, data):
        self.emit("J", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def handle(self, data):
        kind = data.get("t")
        if kind == "open":
            hwnd = self.windows.target(data.get("window"))
            size = None
            if data.get("width") is not None or data.get("height") is not None:
                size = (bounded(data.get("width"), 320, 3840), bounded(data.get("height"), 200, 2160))
            with self.cv:
                self.hwnd, self.size, self.last, self.in_flight = hwnd, size, None, 0
                self.refit = size is not None
                self.paused = False
                self.cv.notify_all()
            self.json({"t": "opened", "window": str(hwnd)})
        elif kind == "size":
            size = (bounded(data.get("width"), 320, 3840), bounded(data.get("height"), 200, 2160))
            with self.cv:
                if size != self.size:
                    self.size, self.refit = size, True
                self.cv.notify_all()
        elif kind in ("pause", "resume"):
            with self.cv:
                self.paused = kind == "pause"
                self.cv.notify_all()
        elif kind == "input":
            if self.hwnd is None:
                fail("Todavía no hay una ventana abierta")
            with self.cv:
                self.idle = 0  # algo va a cambiar en pantalla: mirar seguido otra vez
                self.cv.notify_all()
            try:
                self.windows.input(self.hwnd, data.get("events"))
            except ValueError as exc:
                self.json({"t": "error", "input": True, "n": data.get("n"), "message": str(exc)})
                return
            self.json({"t": "input", "n": data.get("n")})
        elif kind == "ack":
            with self.cv:
                self.in_flight = max(0, self.in_flight - 1)
                self.cv.notify_all()
        elif kind == "release":
            self.windows.release()
        elif kind == "windows":
            self.json({"t": "windows", "windows": self.windows.windows()})
        else:
            fail("Pedido de ventana desconocido")

    def rest(self, seconds):
        """Pausa en reposo que la entrada del visor interrumpe (handle("input") avisa por `cv`)."""
        if seconds <= 0:
            return
        with self.cv:
            self.cv.wait(seconds)

    def step(self):
        """Una vuelta de captura: devuelve el cuadro emitido (cabecera, PNG) o None. Espera si hay
        demasiados cuadros sin acusar o no hay ventana."""
        with self.cv:
            while not self.closed and (self.hwnd is None or self.paused or self.in_flight >= MAX_IN_FLIGHT):
                self.cv.wait(1)
            if self.closed:
                return None
            hwnd, size, refit = self.hwnd, self.size, self.refit
            self.refit = False
        started = self.clock()
        try:
            if not self.windows.chrome(hwnd):
                fail("Esa ventana de Chrome ya no está disponible")
            if refit and size:
                # solo al abrir o cambiar de tamano: cuadro a cuadro pelearia con quien maximiza alla
                self.windows.fit(hwnd, *size)
            rgb, width, height = self.capture(hwnd)
            cursor = self.windows.cursor()
            if cursor != self.last_cursor:
                self.json({"t": "cursor", "cursor": cursor})
                self.last_cursor = cursor
        except ValueError as exc:
            self.json({"t": "error", "message": str(exc)})
            with self.cv:
                if self.hwnd == hwnd:
                    self.hwnd = None
            return None
        last = self.last
        box = (0, 0, width, height)
        full = True
        if last and last[:3] == (hwnd, width, height):
            box = dirty_box(last[3], rgb, width, height)
            if box is None:
                self.idle += 1
                pause = IDLE_INTERVAL_S if self.idle < IDLE_FAST_STEPS else IDLE_SLOW_S
                self.rest(max(0, pause - (self.clock() - started)))
                return None
            if (box[2] - box[0]) * (box[3] - box[1]) < width * height * 0.7:
                full = False
            else:
                box = (0, 0, width, height)
        self.idle = 0
        self.seq += 1
        header = FRAME_HEADER.pack(self.seq, box[0], box[1], box[2] - box[0], box[3] - box[1], width, height, FRAME_FULL if full else 0)
        payload = header + png(rgb, width, box)
        with self.cv:
            if self.hwnd != hwnd:
                return None  # cambio la ventana mientras se capturaba: el cuadro ya no vale
            self.last = (hwnd, width, height, rgb)
            self.in_flight += 1
        self.emit("F", payload)
        self.sleep(max(0, MIN_INTERVAL_S - (self.clock() - started)))
        return payload

    def run_capture(self):
        try:
            while not self.closed:
                self.step()
        except Exception as exc:  # cualquier falla del hilo de captura se informa y cierra la sesion
            try:
                self.json({"t": "error", "message": f"Se detuvo la captura: {type(exc).__name__}: {exc}"})
            except OSError:
                pass
        finally:
            with self.cv:
                self.closed = True
                self.cv.notify_all()

    def run(self, lines):
        thread = threading.Thread(target=self.run_capture, daemon=True)
        thread.start()
        try:
            for line in lines:
                if self.closed:
                    break  # murio la captura: el proceso termina y el server relanza uno nuevo
                try:
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        fail("Pedido inválido")
                    self.handle(data)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    if isinstance(exc, OSError):
                        raise
                    self.json({"t": "error", "message": str(exc)})
        except OSError:
            pass  # stdout cerrado: el server se fue
        finally:
            with self.cv:
                self.closed = True
                self.cv.notify_all()
            self.windows.release()


def main():
    windows = Windows()
    if "--stream" in sys.argv[1:]:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        Streamer(windows, sys.stdout.buffer).run(sys.stdin)
        return
    for line in sys.stdin:
        try:
            data = json.loads(line)
            action = data.get("action")
            if action == "windows":
                result = {"windows": windows.windows()}
            elif action == "window-frame":
                result = windows.frame(windows.target(data.get("window")), data.get("width"), data.get("height"), data.get("delta", False), data.get("base"))
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
