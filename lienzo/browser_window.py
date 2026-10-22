"""Ventanas reales de Chrome. Worker aislado; no controla otras aplicaciones.

Dos modos sobre el mismo codigo Win32:
- pedido/respuesta por lineas JSON (`windows`, `window-frame`, `window-input`, `window-release`);
- `--stream`: captura continua con acuse por cuadro y entrada por el mismo canal. stdout pasa a
  ser binario: registros `>IB` (largo, tipo) con J = JSON y F = cuadro (FRAME_HEADER + PNG).
"""

import base64
import concurrent.futures
import ctypes as c
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import uuid
import zlib
from ctypes import wintypes as w
from pathlib import Path

FRAME_HEADER = struct.Struct(">IHHHHHHB")  # seq, x, y, ancho, alto, ancho total, alto total, flags
FRAME_FULL = 1  # flags: el cuadro es completo (reemplaza todo), no un parche
PIXEL = 4  # bytes por pixel de la captura: BGRA, tal como la deja Windows
SYSTEM_CURSORS = {
    32512: "default",
    32513: "text",
    32514: "wait",
    32515: "crosshair",
    32642: "nwse-resize",
    32643: "nesw-resize",
    32644: "ew-resize",
    32645: "ns-resize",
    32646: "move",
    32648: "not-allowed",
    32649: "pointer",
    32650: "progress",
    32651: "help",
}
RECORD = struct.Struct(">IB")
MAX_IN_FLIGHT = 2  # cuadros sin acusar antes de frenar la captura: acota la cola, no la pierde
MIN_INTERVAL_S = 1 / 60
IDLE_INTERVAL_S = 0.04  # sin cambios se mira 25 veces por segundo durante IDLE_FAST_STEPS lecturas...
IDLE_SLOW_S = 0.15  # ...y despues 6 veces por segundo; la entrada del visor vuelve al ritmo rapido
IDLE_FAST_STEPS = 50
PREFETCH_MAX_AGE_S = 0.15  # una captura adelantada mas vieja (se espero un acuse) se descarta
PASTE_MAX_CHARS = 16000  # lo pegado viaja en un pedido del visor, acotado a 64 KiB por browser_stream
CLIPBOARD_MAX_BYTES = 2_000_000  # lo copiado alla que se trae a esta PC
CLIPBOARD_FRESH_S = 1.0  # una copia se atribuye a Chrome solo si la mirada anterior es asi de reciente
LOCK_CHECK_S = 0.5  # cada cuanto se mira si la PC esta bloqueada
LOCK_ON_READS = 2  # lecturas seguidas de bloqueo para avisarlo (~1 s)
LOCK_OFF_S = 3.0  # segundos seguidos sin bloqueo para avisar que se desbloqueo: el visor no oscila


def ctrl(key):
    """Ctrl + tecla y Ctrl suelto al final, como lo manda el visor."""
    return [
        {"kind": "key", "type": "keyDown", "keyCode": key, "modifiers": 2},
        {"kind": "key", "type": "keyUp", "keyCode": key, "modifiers": 2},
        {"kind": "key", "type": "keyUp", "keyCode": 17, "modifiers": 0},
    ]


CTRL_C, CTRL_V = ctrl(67), ctrl(86)


class LockWatch:
    """Bloqueo de la PC con histeresis: entra con LOCK_ON_READS lecturas seguidas y sale despues de
    LOCK_OFF_S sin ninguna. `update` devuelve el estado nuevo cuando cambia, si no None."""

    def __init__(self):
        self.locked = False
        self.reads = 0
        self.clear_since = None

    def update(self, now, raw):
        if not self.locked:
            self.reads = self.reads + 1 if raw else 0
            return self.force() if self.reads >= LOCK_ON_READS else None
        if raw:
            self.clear_since = None
        elif self.clear_since is None:
            self.clear_since = now
        elif now - self.clear_since >= LOCK_OFF_S:
            self.locked, self.reads, self.clear_since = False, 0, None
            return False
        return None

    def force(self):
        """Bloqueada ya, sin esperar otra lectura (la captura fallo y Windows lo confirma)."""
        changed = not self.locked
        self.locked, self.clear_since = True, None
        return True if changed else None


# --- perfil de cada ventana --------------------------------------------------------------------
# Windows sabe de que perfil es cada ventana de Chrome: Chrome le pone un AppUserModelID por perfil
# («Chrome.UserData.Profile3») y el comando para relanzarla (--profile-directory="Profile 3"), que
# es como la barra de tareas las agrupa. CDP no lo dice: solo da un browserContextId por perfil.
PROFILE_ID = re.compile(r"^(Default|Profile \d+)$")


class GUID(c.Structure):
    _fields_ = [("data", c.c_byte * 16)]


class PropertyKey(c.Structure):
    _fields_ = [("fmtid", GUID), ("pid", w.DWORD)]


class PropVariant(c.Structure):
    _fields_ = [
        ("vt", w.USHORT),
        ("r1", w.USHORT),
        ("r2", w.USHORT),
        ("r3", w.USHORT),
        ("value", c.c_void_p),
        ("pad", c.c_void_p),
    ]


def guid(text):
    value = GUID()
    c.memmove(c.byref(value), uuid.UUID(text).bytes_le, 16)
    return value


COM = threading.local()  # COM iniciado en el hilo que pide la lista de ventanas
IID_PROPERTY_STORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
APP_USER_MODEL = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"  # PKEY_AppUserModel_*: 5 el id, 2 el relanzado


def profile_names(text):
    """{carpeta: nombre} de los perfiles que lista el Local State de Chrome (como browser_profiles.mjs)."""
    try:
        info = json.loads(text)["profile"]["info_cache"]
    except ValueError, KeyError, TypeError:
        return {}
    if not isinstance(info, dict):
        return {}
    return {
        key: value["name"]
        for key, value in info.items()
        if PROFILE_ID.match(key) and isinstance(value, dict) and isinstance(value.get("name"), str)
    }


def profile_label(app_id, relaunch, names):
    """El nombre del perfil de una ventana («Ariel», «globant.com») o None. Solo el de la carpeta de
    datos de siempre (UserData): la de un Chrome aislado tiene otros perfiles y otro Local State."""
    parts = (app_id or "").split(".")
    # el perfil Default de la carpeta de siempre tiene el id «Chrome» a secas; los demas, «Chrome.UserData.X»
    if parts != ["Chrome"] and (len(parts) != 3 or parts[0] != "Chrome" or parts[1] != "UserData"):
        return None
    match = re.search(r'--profile-directory="([^"]+)"', relaunch or "")
    if match and "--user-data-dir" not in relaunch:
        return names.get(match.group(1))
    if len(parts) != 3:
        return None
    return next((name for key, name in names.items() if key.replace(" ", "") == parts[2]), None)


class MonitorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


def fail(message):
    raise ValueError(message)


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail("Valor de entrada fuera de rango")
    return value


def dirty_box(old, new, width, height, step=64):
    """(left, top, right, bottom) de lo que cambio entre dos cuadros BGRA del mismo tamano, o None.
    Las filas se comparan enteras (memcmp); las columnas de a `step` pixeles y solo en las filas
    que cambiaron; si cambio mas de la mitad de las filas (scroll) va el ancho entero sin mirar."""
    stride = width * PIXEL
    o, n = bytes(old), bytes(new)  # comparar bytes es 8 veces mas rapido que memoryview
    changed = [y for y in range(height) if n[y * stride : (y + 1) * stride] != o[y * stride : (y + 1) * stride]]
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
            if n[offset + x * PIXEL : offset + end * PIXEL] != o[offset + x * PIXEL : offset + end * PIXEL]:
                left, right = min(left, x), max(right, end)
    return left, top, right, bottom


# --- cuadros v2: copia de scroll y varios parches (el visor la pide con "v": 2 al abrir) -----------
# FRAME_HEADER con x/y/ancho/alto en 0 y flags | FRAME_V2, despues SCROLL (dy en 0 = sin copia) y
# la cantidad de parches; cada parche es PATCH + PNG. Medido el 2026-10-21 por la LAN contra
# ar-it33940, scrolleando Wikipedia: 7 cuadros/s de 470 KB, casi todos completos. Un scroll
# corre lo que ya tiene el visor y solo viaja la franja nueva, como el CopyRect de VNC.
FRAME_V2 = 0x80
SCROLL = struct.Struct(">hHHHHH")  # dy, x0, x1, top, bottom, parches: destino [x0,x1) x [top,bottom)
PATCH = struct.Struct(">HHHHI")  # x, y, ancho, alto, largo del PNG
MAX_PATCHES = 16
ROW_GAP = 8  # filas iguales que todavia unen dos tramos cambiados en un mismo parche


def changed_rows(old, new, width, rows, block=8):
    """Las filas de `rows` (un range) que difieren entre dos cuadros BGRA. Compara de a `block` filas
    y baja a fila solo en los bloques distintos: casi siempre son pocos."""
    stride = width * PIXEL
    o, n = bytes(old), bytes(new)  # comparar bytes es 8 veces mas rapido que memoryview
    out = []
    for start in range(rows.start, rows.stop, block):
        end = min(rows.stop, start + block)
        if n[start * stride : end * stride] != o[start * stride : end * stride]:
            out += [
                y for y in range(start, end) if n[y * stride : (y + 1) * stride] != o[y * stride : (y + 1) * stride]
            ]
    return out


def row_spans(rows, gap=ROW_GAP):
    """[(top, bottom)] de filas cambiadas, uniendo los tramos separados por menos de `gap` filas."""
    spans = []
    for y in rows:
        if spans and y - spans[-1][1] < gap:
            spans[-1][1] = y + 1
        else:
            spans.append([y, y + 1])
    return [tuple(s) for s in spans]


def span_box(old, new, width, top, bottom):
    """(left, top, right, bottom) de lo que cambio dentro de las filas [top, bottom), o None. Exacta
    al pixel: el XOR de cada fila como entero junta lo distinto de todas y sus bits extremos dan los
    bordes. Medido el 2026-10-22: la mitad que mirar de a 32 pixeles, que mandaba mas ancho."""
    stride = width * PIXEL
    o, n = bytes(old), bytes(new)
    diff = 0
    for y in range(top, bottom):
        row_new, row_old = n[y * stride : (y + 1) * stride], o[y * stride : (y + 1) * stride]
        if row_new != row_old:
            diff |= int.from_bytes(row_new) ^ int.from_bytes(row_old)
    if not diff:
        return None
    first = stride - 1 - (diff.bit_length() - 1) // 8  # el byte mas a la izquierda que cambio
    last = stride - 1 - ((diff & -diff).bit_length() - 1) // 8
    return first // PIXEL, top, last // PIXEL + 1, bottom


def dirty_rects(old, new, width, height, changed=None):
    """Los parches que cubren lo que cambio, uno por tramo de filas (`changed`: las filas distintas,
    si ya se sabe). Con mas de MAX_PATCHES se unen en uno solo (la caja de todos)."""
    changed = changed_rows(old, new, width, range(height)) if changed is None else changed
    boxes = [b for t, bt in row_spans(changed) if (b := span_box(old, new, width, t, bt))]
    return merge_boxes(boxes) if len(boxes) > MAX_PATCHES else boxes


def merge_boxes(boxes, limit=MAX_PATCHES, near=32):
    """Junta parches hasta quedar en `limit`, siempre el par que menos area agrega. Primero solo
    vecinos de arriba a abajo hasta `near` (muchos tramos: costo lineal), despues cualquier par: dos
    columnas de cambios lejanas quedan como dos parches angostos. Antes se mandaba la caja de todos,
    que con cambios en dos esquinas era el cuadro entero. Los parches pueden pisarse: todos salen del
    mismo cuadro nuevo."""

    def union(a, b):
        return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])

    def area(b):
        return (b[2] - b[0]) * (b[3] - b[1])

    def cost(a, b):
        return area(union(a, b)) - area(a) - area(b)

    boxes = list(boxes)
    while len(boxes) > max(limit, near):
        i = min(range(len(boxes) - 1), key=lambda i: cost(boxes[i], boxes[i + 1]))
        boxes[i : i + 2] = [union(boxes[i], boxes[i + 1])]
    while len(boxes) > limit:
        _, i, j = min((cost(a, b), i, j) for i, a in enumerate(boxes) for j, b in enumerate(boxes) if i < j)
        boxes[i] = union(boxes[i], boxes.pop(j))
    return boxes


def find_scroll(old, new, width, height, changed, min_rows=24):
    """(dy, x0, x1, top, bottom) si el cambio es un corrimiento vertical, o None. Vota con la banda
    central de cada fila: una fila cambiada que es igual a una sola fila del cuadro anterior dice
    cuanto se corrio (las repetidas, como las filas en blanco, no votan). Despues busca el tramo
    corrido mas largo y hasta donde llega a los costados (barras laterales fijas quedan afuera)."""
    if len(changed) < min_rows:
        return None
    stride = width * PIXEL
    o, n = bytes(old), bytes(new)  # comparar bytes es 8 veces mas rapido que memoryview
    # la mitad central del ancho: una banda angosta cae en el blanco entre columnas y no vota.
    # Las claves son bytes (hashear un memoryview lo copia igual y cuesta el triple)
    c0, c1 = width // 4 * PIXEL, width * 3 // 4 * PIXEL
    seen = {}
    for y in range(height):
        key = old[y * stride + c0 : y * stride + c1]
        seen[key] = -1 if key in seen else y
    votes = {}
    for y in changed:
        yo = seen.get(new[y * stride + c0 : y * stride + c1], -1)
        if yo >= 0 and yo != y:
            votes[y - yo] = votes.get(y - yo, 0) + 1
    if not votes:
        return None
    dy, count = max(votes.items(), key=lambda kv: kv[1])
    if count < max(min_rows // 2, len(changed) // 6):
        return None

    def same(y, a, b):
        return n[y * stride + a : y * stride + b] == o[(y - dy) * stride + a : (y - dy) * stride + b]

    lo, hi = max(0, dy), min(height, height + dy)
    best, run = (0, 0), None
    for y in range(lo, hi + 1):
        if y < hi and same(y, c0, c1):
            run = y if run is None else run
        elif run is not None:
            best = max(best, (run, y), key=lambda r: r[1] - r[0])
            run = None
    top, bottom = best
    if bottom - top < min_rows:
        return None

    # hacia los costados se mira columna por columna (el verde de cada pixel) en todas las filas del
    # tramo, con un corte de bytes por columna. Con 24 filas de muestra un menu fijo de fondo parejo y
    # un renglon cada tanto pasaba por corrido: medido el 2026-10-22, 15 parches de mas por cuadro.
    # Una columna corrida salvo en una franja corta (un boton o un reloj fijo encima, la barra de
    # scroll) entra igual: esa franja la corrigen los parches. Si no, el resto de la fila a ese lado
    # viajaba como un parche por renglon. Lo fijo da distinto donde esta y donde estaba: alto + |dy|
    tolerance = (bottom - top) // 8 + abs(dy)

    def columns(a, b):
        for x in range(a, b):
            col_new = n[top * stride + x * PIXEL + 1 : bottom * stride : stride]
            col_old = o[(top - dy) * stride + x * PIXEL + 1 : (bottom - dy) * stride : stride]
            if col_new != col_old and mismatch_band(col_new, col_old) > tolerance:
                return False
        return True

    x0, x1 = c0 // PIXEL, c1 // PIXEL
    while x0 >= 16 and columns(x0 - 16, x0):
        x0 -= 16
    x0 = 0 if x0 < 16 and columns(0, x0) else x0
    while x1 + 16 <= width and columns(x1, x1 + 16):
        x1 += 16
    x1 = width if width - x1 < 16 and columns(x1, width) else x1
    return dy, x0, x1, top, bottom


def mismatch_band(a, b):
    """Cuantas posiciones hay entre la primera y la ultima distinta de dos bytes del mismo largo.
    Con el XOR como entero: la primera es el bit mas alto, la ultima el mas bajo, todo en C."""
    diff = int.from_bytes(a) ^ int.from_bytes(b)
    if not diff:
        return 0
    return (diff.bit_length() - 1) // 8 - ((diff & -diff).bit_length() - 1) // 8 + 1


def shifted(old, width, scroll):
    """El cuadro anterior con la copia de `scroll` ya aplicada: lo que el visor tiene despues de
    correr su imagen. Contra esto se buscan los parches."""
    dy, x0, x1, top, bottom = scroll
    stride = width * PIXEL
    out = bytearray(old)
    for y in range(top, bottom):
        out[y * stride + x0 * PIXEL : y * stride + x1 * PIXEL] = old[
            (y - dy) * stride + x0 * PIXEL : (y - dy) * stride + x1 * PIXEL
        ]
    return bytes(out)


def frame_v2(seq, pixels, width, height, last):
    """El cuadro v2 contra `last` (BGRA del cuadro anterior del mismo tamano, o None): bytes, o None si
    no cambio nada. Completo si no hay anterior o si los parches cubren mas del 70 %."""
    full = last is None
    scroll = None
    boxes = []
    if not full:
        if pixels == last:  # un memcmp: el caso de siempre cuando nadie toca nada
            return None
        changed = changed_rows(last, pixels, width, range(height))
        if not changed:
            return None
        scroll = find_scroll(last, pixels, width, height, changed)
        base = shifted(last, width, scroll) if scroll else last
        boxes = dirty_rects(base, pixels, width, height, None if scroll else changed) if base != pixels else []
        if not boxes and not scroll:
            return None
        full = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes) > width * height * 0.7
    if full:
        scroll, boxes = None, [(0, 0, width, height)]
    out = [
        FRAME_HEADER.pack(seq, 0, 0, 0, 0, width, height, FRAME_V2 | (FRAME_FULL if full else 0)),
        SCROLL.pack(*(scroll or (0, 0, 0, 0, 0)), len(boxes)),
    ]
    for box in boxes:
        data = png(pixels, width, box)
        out += [PATCH.pack(box[0], box[1], box[2] - box[0], box[3] - box[1], len(data)), data]
    return b"".join(out)


def png(bgra, width, box):
    """PNG RGB de 8 bits de la caja (left, top, right, bottom) de un cuadro BGRA de `width` pixeles.
    Solo se convierte lo que viaja: cada fila con su byte de filtro (0) adelante."""
    left, top, right, bottom = box
    w = right - left
    line = w * 3 + 1
    rows = bytearray(line * (bottom - top))
    for i, y in enumerate(range(top, bottom)):
        src = bgra[(y * width + left) * PIXEL : (y * width + right) * PIXEL]
        at, end = i * line + 1, (i + 1) * line
        rows[at:end:3], rows[at + 1 : end : 3], rows[at + 2 : end : 3] = src[2::4], src[1::4], src[0::4]

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
        # copy/paste y la mirada del hilo de captura no se pisan; lo visto o escrito por el visor no
        # se anuncia como copia hecha alla
        self.clipboard_lock = threading.RLock()
        self.user.GetWindowDC.restype = w.HDC
        self.user.GetDC.restype = w.HDC
        self.user.WindowFromPoint.restype = w.HWND
        self.user.GetForegroundWindow.restype = w.HWND
        self.user.GetAncestor.restype = w.HWND
        self.user.LoadCursorW.restype = w.HANDLE
        self.user.LoadCursorW.argtypes = [w.HINSTANCE, c.c_void_p]
        self.cursor_shapes = {
            self.user.LoadCursorW(None, c.c_void_p(number)): shape for number, shape in SYSTEM_CURSORS.items()
        }
        self.user.MonitorFromWindow.restype = w.HANDLE
        self.user.OpenInputDesktop.restype = w.HANDLE
        self.gdi.CreateCompatibleDC.restype = w.HDC
        self.gdi.CreateCompatibleBitmap.restype = w.HBITMAP
        self.gdi.CreateDIBSection.restype = w.HBITMAP
        self.gdi.SelectObject.restype = w.HANDLE
        self.kernel.OpenProcess.restype = w.HANDLE
        self.user.GetClipboardData.argtypes = [w.UINT]
        self.user.GetClipboardData.restype = w.HANDLE
        self.user.GetClipboardSequenceNumber.restype = w.DWORD
        self.user.OpenClipboard.argtypes = [w.HWND]
        self.user.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
        self.user.SetClipboardData.restype = w.HANDLE
        self.user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, *[c.c_int] * 4]
        self.user.CreateWindowExW.argtypes += [w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
        self.user.CreateWindowExW.restype = w.HWND
        self.user.DestroyWindow.argtypes = [w.HWND]
        self.kernel.GlobalAlloc.argtypes = [w.UINT, c.c_size_t]
        self.kernel.GlobalAlloc.restype = w.HANDLE
        self.kernel.GlobalFree.argtypes = [w.HANDLE]
        self.kernel.GlobalFree.restype = w.HANDLE
        self.kernel.GlobalLock.argtypes = [w.HANDLE]
        self.kernel.GlobalLock.restype = c.c_void_p
        self.kernel.GlobalUnlock.argtypes = [w.HANDLE]
        self.kernel.GlobalSize.argtypes = [w.HANDLE]
        self.kernel.GlobalSize.restype = c.c_size_t
        # Todos los handles conservan sus 64 bits al pasar a la API nativa.
        for dll, name, args in [
            (self.user, "GetWindowDC", [w.HWND]),
            (self.user, "GetDC", [w.HWND]),
            (self.user, "WindowFromPoint", [w.POINT]),
            (self.user, "ReleaseDC", [w.HWND, w.HDC]),
            (self.user, "PrintWindow", [w.HWND, w.HDC, w.UINT]),
            (self.user, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)]),
            (self.user, "GetAncestor", [w.HWND, w.UINT]),
            (self.user, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "GetClassNameW", [w.HWND, w.LPWSTR, c.c_int]),
            (self.user, "IsWindowVisible", [w.HWND]),
            (self.user, "IsIconic", [w.HWND]),
            (self.user, "ShowWindow", [w.HWND, c.c_int]),
            (self.user, "SetForegroundWindow", [w.HWND]),
            (self.user, "IsZoomed", [w.HWND]),
            (self.user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]),
            (self.user, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL]),
            (self.user, "BringWindowToTop", [w.HWND]),
            (self.user, "SwitchToThisWindow", [w.HWND, w.BOOL]),
            (self.user, "SystemParametersInfoW", [w.UINT, w.UINT, c.c_void_p, w.UINT]),
            (self.user, "SetCursorPos", [c.c_int, c.c_int]),
            (self.user, "GetCursorPos", [c.POINTER(w.POINT)]),
            (self.user, "GetClipCursor", [c.POINTER(w.RECT)]),
            (self.user, "MonitorFromWindow", [w.HWND, w.DWORD]),
            (self.user, "GetMonitorInfoW", [w.HANDLE, c.POINTER(MonitorInfo)]),
            (self.user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)]),
            (self.user, "OpenInputDesktop", [w.DWORD, w.BOOL, w.DWORD]),
            (self.user, "CloseDesktop", [w.HANDLE]),
            (self.user, "GetUserObjectInformationW", [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]),
            (self.gdi, "CreateCompatibleDC", [w.HDC]),
            (self.gdi, "CreateCompatibleBitmap", [w.HDC, c.c_int, c.c_int]),
            (self.gdi, "CreateDIBSection", [w.HDC, c.c_void_p, w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD]),
            (self.gdi, "SelectObject", [w.HDC, w.HANDLE]),
            (self.gdi, "BitBlt", [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.HDC, c.c_int, c.c_int, w.DWORD]),
            (self.gdi, "DeleteObject", [w.HANDLE]),
            (self.gdi, "DeleteDC", [w.HDC]),
            (self.gdi, "GetDIBits", [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT]),
            (self.kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD]),
            (self.kernel, "CloseHandle", [w.HANDLE]),
            (self.kernel, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]),
        ]:
            getattr(dll, name).argtypes = args
        self.clipboard_seen = self.user.GetClipboardSequenceNumber()

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
            return (
                bool(self.kernel.QueryFullProcessImageNameW(process, 0, path, c.byref(size)))
                and Path(path.value).name.lower() == "chrome.exe"
            )
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
        names = self.profile_names()
        for item in result:
            profile = self.profile(int(item["id"]), names)
            if profile:
                item["profile"] = profile
        foreground = str(self.user.GetForegroundWindow())
        return sorted(result, key=lambda item: item["id"] != foreground)

    def app_user_model(self, hwnd):
        """(AppUserModelID, comando de relanzado) de la ventana, o None donde no hay."""
        shell, ole = c.WinDLL("shell32"), c.WinDLL("ole32")
        if not getattr(COM, "ready", False):
            ole.CoInitializeEx(None, 2)  # una vez por hilo; si ya estaba en otro modo, sigue igual
            COM.ready = True
        store = c.c_void_p()
        shell.SHGetPropertyStoreForWindow.argtypes = [w.HWND, c.c_void_p, c.POINTER(c.c_void_p)]
        if shell.SHGetPropertyStoreForWindow(hwnd, c.byref(guid(IID_PROPERTY_STORE)), c.byref(store)) or not store:
            return None, None
        table = c.cast(c.cast(store, c.POINTER(c.c_void_p))[0], c.POINTER(c.c_void_p))
        get_value = c.WINFUNCTYPE(c.HRESULT, c.c_void_p, c.POINTER(PropertyKey), c.POINTER(PropVariant))(table[5])
        values = []
        try:
            for pid in (5, 2):
                value = PropVariant()
                try:
                    get_value(store, c.byref(PropertyKey(guid(APP_USER_MODEL), pid)), c.byref(value))
                except OSError:
                    values.append(None)
                    continue
                values.append(c.wstring_at(value.value) if value.vt == 31 and value.value else None)  # VT_LPWSTR
                ole.PropVariantClear(c.byref(value))
        finally:
            c.WINFUNCTYPE(c.c_ulong, c.c_void_p)(table[2])(store)  # Release
        return tuple(values)

    def profile_names(self):
        """{carpeta: nombre} de los perfiles de la carpeta de datos de siempre, o {} si no se puede leer."""
        root = os.environ.get("LOCALAPPDATA")
        state = Path(root, "Google/Chrome/User Data/Local State") if root else None
        try:
            return profile_names(state.read_text(encoding="utf-8")) if state and state.is_file() else {}
        except OSError, UnicodeError:
            return {}

    def profile(self, hwnd, names):
        """El nombre del perfil de Chrome de esa ventana, o None si Windows o Chrome no lo dicen."""
        try:
            app_id, relaunch = self.app_user_model(hwnd)
        except OSError:
            return None
        return profile_label(app_id, relaunch, names)

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

        info = self.monitor(hwnd)
        width = min(width, info.work.right - info.work.left)
        height = min(height, info.work.bottom - info.work.top)
        rect = self.rect(hwnd)
        left = max(info.work.left, min(rect.left, info.work.right - width))
        top = max(info.work.top, min(rect.top, info.work.bottom - height))
        current = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        if current != (left, top, width, height) and not self.user.SetWindowPos(
            hwnd, None, left, top, width, height, 0x14
        ):
            fail("Windows no permitió ajustar el tamaño de Chrome")

    def popups(self, hwnd):
        """Ventanas visibles propiedad de esta ventana de Chrome, en orden de abajo a arriba."""
        result = []
        pid = self.owner(hwnd)
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def collect(candidate, _):
            if (
                candidate != hwnd
                and self.user.IsWindowVisible(candidate)
                and self.owner(candidate) == pid
                and self.user.GetAncestor(candidate, 3) == hwnd
            ):
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
            if not self.gdi.BitBlt(
                target, rect.left - base.left, rect.top - base.top, width, height, memory, 0, 0, 0x00CC0020
            ):
                fail("Windows no pudo mostrar el aviso o menú de Chrome")
        finally:
            self.gdi.SelectObject(memory, old)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)

    def capture(self, hwnd, width=None, height=None):
        """(bgra, ancho, alto) de la ventana; si se pide tamano, primero la ajusta."""
        if width is not None or height is not None:
            self.fit(hwnd, width, height)
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        rect = self.rect(hwnd)
        width, height = rect.right - rect.left, rect.bottom - rect.top
        bounded(width, 1, 3840)
        bounded(height, 1, 2160)
        on_screen = self.on_screen(hwnd, rect)
        source = None if on_screen else hwnd
        dc = self.user.GetDC(None) if on_screen else self.user.GetWindowDC(hwnd)
        memory = self.gdi.CreateCompatibleDC(dc)
        # seccion DIB de 32 bits de arriba a abajo: BitBlt y PrintWindow escriben directo en memoria
        # del proceso y no hace falta GetDIBits (que con un bitmap compatible con la pantalla volvia
        # a leer de la GPU: 68 ms contra 32 de la copia sola, medido el 2026-10-21)
        info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
        bits = c.c_void_p()
        bitmap = self.gdi.CreateDIBSection(dc, info, 0, c.byref(bits), None, 0)
        old_bitmap = self.gdi.SelectObject(memory, bitmap)
        try:
            if on_screen:
                # visible y sin tapar: se copia lo que ya compuso el escritorio, sin pedirle nada a
                # Chrome. PrintWindow(PW_RENDERFULLCONTENT) lo hace redibujar en cada cuadro y la
                # ventana real parpadeaba en la otra PC (reportado el 2026-10-21). Los menus y avisos
                # de Chrome ya estan en pantalla, encima.
                if (
                    not dc
                    or not memory
                    or not bitmap
                    or not self.gdi.BitBlt(memory, 0, 0, width, height, dc, rect.left, rect.top, 0x00CC0020)
                ):
                    fail("Windows no pudo capturar Chrome. La sesión debe estar abierta y desbloqueada")
            else:
                if not dc or not memory or not bitmap or not self.user.PrintWindow(hwnd, memory, 2):
                    fail("Windows no pudo capturar Chrome. La sesión debe estar abierta y desbloqueada")
                for popup in self.popups(hwnd):
                    self.paint_popup(popup, memory, rect)
            self.gdi.GdiFlush()
            if not bits.value:
                fail("Windows no pudo leer la imagen de Chrome")
            # BGRA tal cual: pasarlo entero a RGB costaba 8-12 ms por captura con el GIL tomado
            # (medido el 2026-10-22); png() convierte solo lo que viaja
            return c.string_at(bits.value, width * height * PIXEL), width, height
        finally:
            self.gdi.SelectObject(memory, old_bitmap)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(source, dc)

    def monitor(self, hwnd):
        """MONITORINFO del monitor de la ventana (`monitor` entero y `work` sin la barra de tareas)."""
        info = MonitorInfo()
        info.size = c.sizeof(info)
        if not self.user.GetMonitorInfoW(self.user.MonitorFromWindow(hwnd, 2), c.byref(info)):
            fail("Windows no pudo medir el escritorio de Chrome")
        return info

    def on_screen(self, hwnd, rect, grid=5):
        """La ventana se ve entera: no esta minimizada, entra en su monitor (sin contar el borde
        invisible de una maximizada) y en una grilla de puntos de adentro lo que hay arriba es
        ella o algo de su mismo proceso (un menu o aviso de Chrome). Si no, hay que pedirle la imagen
        con PrintWindow: una ventana que se sale de la pantalla traia la barra de tareas y franjas negras."""
        if self.user.IsIconic(hwnd):
            return False
        screen = self.monitor(hwnd).monitor
        border = 16  # el borde invisible de una maximizada: 8 px al 100 %, 11 al 125-150 %
        if (
            rect.left + border < screen.left
            or rect.top + border < screen.top
            or rect.right - border > screen.right
            or rect.bottom - border > screen.bottom
        ):
            return False
        inset = 16
        left, top, right, bottom = rect.left + inset, rect.top + inset, rect.right - inset, rect.bottom - inset
        if right <= left or bottom <= top:
            return False
        pid = self.owner(hwnd)
        for i in range(grid):
            for j in range(grid):
                point = w.POINT(left + (right - left) * i // (grid - 1), top + (bottom - top) * j // (grid - 1))
                over = self.user.WindowFromPoint(point)
                root = self.user.GetAncestor(over, 2) if over else None  # GA_ROOT
                if not root or (root != hwnd and self.owner(root) != pid):
                    return False
        return True

    def frame(self, hwnd, width=None, height=None, delta=False, base=None):
        """Modo pedido/respuesta: un cuadro (o un parche sobre `base`) en base64."""
        if type(delta) is not bool or (base is not None and (not isinstance(base, str) or len(base) > 32)):
            fail("Referencia de imagen inválida")
        if width is not None or height is not None:
            bounded(width, 320, 3840)
            bounded(height, 200, 2160)
        pixels, width, height = self.capture(hwnd, width, height)
        box = (0, 0, width, height)
        previous = self.previous_frame
        patch_base = None
        if delta and previous and previous[:3] == (hwnd, width, height) and base == previous[3]:
            box = dirty_box(previous[4], pixels, width, height)
            if box is None:
                return {"unchanged": True, "frameId": base, "width": width, "height": height}
            if (box[2] - box[0]) * (box[3] - box[1]) < width * height * 0.7:
                patch_base = base
            else:
                box = (0, 0, width, height)
        frame_id = secrets.token_hex(16)
        self.previous_frame = (hwnd, width, height, frame_id, pixels)
        result = {
            "image": base64.b64encode(png(pixels, width, box)).decode(),
            "format": "png",
            "width": width,
            "height": height,
            "frameId": frame_id,
        }
        if patch_base:
            result["patch"] = {
                "base": patch_base,
                "x": box[0],
                "y": box[1],
                "width": box[2] - box[0],
                "height": box[3] - box[1],
            }
        return result

    def active(self, hwnd):
        """Chrome recibe la entrada si su ventana esta al frente o si lo esta uno de sus menus o
        desplegables (ventanas del mismo proceso): traerla al frente ahi cerraria el menu."""
        foreground = self.user.GetForegroundWindow()
        return foreground == hwnd or (bool(foreground) and self.owner(foreground) == self.owner(hwnd))

    def describe(self, hwnd):
        """«clase · titulo · proceso» de una ventana, para decir que tiene el frente cuando Chrome no
        lo consigue (sin eso el aviso no daba ninguna pista de por que)."""
        try:
            name = c.create_unicode_buffer(128)
            self.user.GetClassNameW(hwnd, name, len(name))
            title = c.create_unicode_buffer(256)
            self.user.GetWindowTextW(hwnd, title, len(title))
            image = "?"
            process = self.kernel.OpenProcess(0x1000, False, self.owner(hwnd))
            if process:
                try:
                    path = c.create_unicode_buffer(32768)
                    size = w.DWORD(len(path))
                    if self.kernel.QueryFullProcessImageNameW(process, 0, path, c.byref(size)):
                        image = Path(path.value).name
                finally:
                    self.kernel.CloseHandle(process)
            return f"{name.value or '?'} · {title.value[:80] or 'sin título'} · {image}"
        except Exception:  # un fake sin esas funciones, o una ventana que ya no esta
            return "?"

    def input_desktop(self):
        """El nombre del escritorio que recibe la entrada («Default» con la sesion abierta,
        «Winlogon» pidiendo la contrasena o con el aviso seguro de UAC), o None si Windows no deja
        abrirlo: con la PC bloqueada es el de otra sesion."""
        desktop = self.user.OpenInputDesktop(0, False, 0)
        if not desktop:
            return None
        try:
            name = c.create_unicode_buffer(256)
            size = w.DWORD()
            if not self.user.GetUserObjectInformationW(desktop, 2, name, c.sizeof(name), c.byref(size)):  # UOI_NAME
                return None
            return name.value
        finally:
            self.user.CloseDesktop(desktop)

    def locked(self):
        """La PC esta bloqueada: el escritorio de entrada no es el de la sesion, o al frente esta la
        pantalla de bloqueo (LockApp.exe; la detecto E el 2026-10-08 desde la otra PC). Un instante
        sin ventana al frente, como en un Alt+Tab, no cuenta."""
        desktop = self.input_desktop()
        front = self.user.GetForegroundWindow()
        if desktop is None:
            # sin permiso para mirar el escritorio pero con una ventana normal al frente no es bloqueo:
            # un contexto asi dejaba la vista quieta para siempre (revision del 2026-10-22)
            return not front or self.describe(front).endswith("LockApp.exe")
        if desktop != "Default":
            return True
        return bool(front) and self.describe(front).endswith("LockApp.exe")

    def focus(self, hwnd):
        """Trae la ventana de Chrome al frente para mandarle la entrada. Windows solo le deja cambiar
        la ventana activa al proceso que recibio la ultima entrada del usuario (el worker nunca la
        recibe). Se intenta, en orden: pedirlo derecho; un toque de Shift sintetico (keybd_event:
        baja y sube, solo no hace nada en ninguna ventana) que convierte al worker en ese proceso;
        enganchar la cola de entrada del hilo que tiene el frente (AttachThreadInput);
        SwitchToThisWindow (lo que hace Alt+Tab); y minimizar y restaurar la ventana (restaurar da
        el foco). Antes, una sola vez, se pone en cero el tiempo de bloqueo del frente de esta
        sesion (SPI_SETFOREGROUNDLOCKTIMEOUT, sin persistir). Sin ventana al frente no hay
        escritorio activo (PC bloqueada o protector de pantalla) y ningun truco sirve: se dice eso;
        si hay una, el aviso dice cual. Medido el 2026-10-08 desde la otra PC: con solo Shift seguia
        «no permitio activar Chrome»."""
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        if self.active(hwnd):
            return
        # medido el 2026-10-08 desde la otra PC: al frente estaba «Windows.UI.Core.CoreWindow ·
        # Pantalla de bloqueo predeterminada de Windows · LockApp.exe». Con la sesion bloqueada la
        # entrada no llega a ningun programa: no hay truco que probar, hay que desbloquearla alla
        frente = self.user.GetForegroundWindow()
        if frente and self.describe(frente).endswith("LockApp.exe"):
            fail(
                "La PC está bloqueada (pantalla de bloqueo de Windows): desbloqueala allá, mientras tanto Chrome no puede recibir la entrada"
            )
        if not getattr(self, "_sin_bloqueo_de_frente", False):
            self._sin_bloqueo_de_frente = True
            self.user.SystemParametersInfoW(0x2001, 0, None, 0x2)  # SPI_SETFOREGROUNDLOCKTIMEOUT = 0, SPIF_SENDCHANGE
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
            attached = foreground_thread != current_thread and self.user.AttachThreadInput(
                current_thread, foreground_thread, True
            )
            try:
                if attached:
                    self.user.BringWindowToTop(hwnd)
                    self.user.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    self.user.AttachThreadInput(current_thread, foreground_thread, False)
        if self.user.GetForegroundWindow() != hwnd:
            self.user.SwitchToThisWindow(hwnd, True)
        if self.user.GetForegroundWindow() != hwnd:
            self.user.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            self.user.ShowWindow(hwnd, 9)  # SW_RESTORE: al restaurar, Windows le da el foco
        if self.user.GetForegroundWindow() != hwnd:
            foreground = self.user.GetForegroundWindow()
            if not foreground:
                fail(
                    "La PC no tiene escritorio activo (bloqueada o con el protector de pantalla): Chrome no puede recibir la entrada"
                )
            fail(
                f"Windows no permitió activar Chrome; no se envió la entrada. Al frente está: {self.describe(foreground)}"
            )

    def position_mouse(self, x, y):
        if not self.user.SetCursorPos(x, y):
            fail("Windows no permitió mover el mouse de Chrome; no se envió el clic")
        actual = w.POINT()
        if not self.user.GetCursorPos(c.byref(actual)):
            fail("Windows no permitió comprobar la posición del mouse; no se envió el clic")
        if (actual.x, actual.y) == (x, y):
            return
        area = w.RECT()
        bounds = (
            f"área permitida=({area.left},{area.top},{area.right},{area.bottom})"
            if self.user.GetClipCursor(c.byref(area))
            else "área permitida no disponible"
        )
        fail(
            "El mouse no quedó en la posición pedida; no se envió el clic fuera de lugar. "
            f"pedido=({x},{y}); observado=({actual.x},{actual.y}); {bounds}"
        )

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
                self.position_mouse(rect.left + x, rect.top + y)
                flags = {
                    ("mousePressed", "left"): 2,
                    ("mouseReleased", "left"): 4,
                    ("mousePressed", "right"): 8,
                    ("mouseReleased", "right"): 16,
                    ("mousePressed", "middle"): 32,
                    ("mouseReleased", "middle"): 64,
                }
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
                if (
                    key in (91, 92, 93)
                    or (modifiers & 1 and key in (9, 27, 115))
                    or (modifiers & 2 and modifiers & 8 and key == 27)
                ):
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
            elif kind == "paste":
                self.paste(hwnd, event.get("text"))
            else:
                fail("Entrada de ventana desconocida")
        return {"ok": True}

    def copy(self, hwnd):
        """Copia sólo por pedido del visor; nunca devuelve el portapapeles anterior."""
        with self.clipboard_lock:
            previous = self.user.GetClipboardSequenceNumber()
            try:
                self.release()
                self.input(hwnd, CTRL_C)
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if not self.active(hwnd) or not self.chrome(hwnd):
                        fail("Cambió la ventana activa; no se leyó el portapapeles")
                    if self.user.GetClipboardSequenceNumber() != previous:
                        text = self.clipboard_text()
                        if text is not None:
                            return text
                    time.sleep(0.02)
                fail("Chrome no copió texto nuevo. Seleccioná el texto y volvé a copiar.")
            finally:
                self.clipboard_seen = self.user.GetClipboardSequenceNumber()

    def clipboard_text(self):
        """El texto del portapapeles de esta PC, o None si otro programa lo tiene abierto. Solo lo
        llaman copy y pull, que ya comprobaron que es lo recién copiado en Chrome."""
        if not self.user.OpenClipboard(None):
            return None
        try:
            handle = self.user.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                fail("Lo copiado no es texto; sólo se trae texto")
            size = self.kernel.GlobalSize(handle)
            if size > CLIPBOARD_MAX_BYTES:
                fail("El texto copiado es demasiado grande para traerlo")
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                fail("Windows no permitió leer el texto copiado")
            try:
                return c.string_at(pointer, size).decode("utf-16-le").split("\0", 1)[0]
            finally:
                self.kernel.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()

    def paste(self, hwnd, text):
        """Pegar del visor: el texto de la otra PC pasa al portapapeles de esta y Chrome recibe
        Ctrl+V; la página ve un pegado real y lo pegado queda para volver a pegarlo acá."""
        if not isinstance(text, str) or not text:
            fail("Sólo se pega texto, y el portapapeles no tenía")
        if len(text) > PASTE_MAX_CHARS:
            fail(f"El texto pegado supera {PASTE_MAX_CHARS} caracteres; no se pegó")
        data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
        with self.clipboard_lock:
            # sin ventana dueña, Windows rechaza SetClipboardData: una de mensajes, sólo para esto
            owner = self.user.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, c.c_void_p(-3), None, None, None)
            if not owner:
                fail("Windows no dejó preparar el portapapeles; no se pegó")
            try:
                for _ in range(10):
                    if self.user.OpenClipboard(owner):
                        break
                    time.sleep(0.02)
                else:
                    fail("Otro programa tiene abierto el portapapeles allá; volvé a pegar")
                try:
                    self.user.EmptyClipboard()
                    handle = self.kernel.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
                    pointer = handle and self.kernel.GlobalLock(handle)
                    if not pointer:
                        if handle:
                            self.kernel.GlobalFree(handle)
                        fail("Windows no dio memoria para el portapapeles; no se pegó")
                    c.memmove(pointer, data, len(data))
                    self.kernel.GlobalUnlock(handle)
                    if not self.user.SetClipboardData(13, handle):
                        self.kernel.GlobalFree(handle)
                        fail("Windows no aceptó el texto en el portapapeles; no se pegó")
                finally:
                    self.user.CloseClipboard()
            finally:
                self.user.DestroyWindow(owner)
            self.clipboard_seen = self.user.GetClipboardSequenceNumber()
            self.input(hwnd, CTRL_V)

    def clipboard_changed(self, hwnd):
        """El número del portapapeles si cambió desde la última mirada, con esa misma ventana de
        Chrome al frente y la mirada anterior reciente (una copia hecha allá, p. ej. con el menú
        contextual); si no, None. Otra ventana del mismo Chrome o un hueco sin mirar (visor en
        pausa, cuadros sin acusar) no se atribuyen: ahí pudo copiarse una contraseña. No lee el
        contenido: el visor lo pide con un gesto (pull). Con copy o paste en curso, espera."""
        if not self.clipboard_lock.acquire(blocking=False):
            return None
        try:
            now = time.monotonic()
            fresh = now - getattr(self, "clipboard_checked", float("-inf")) <= CLIPBOARD_FRESH_S
            self.clipboard_checked = now
            sequence = self.user.GetClipboardSequenceNumber()
            if sequence == self.clipboard_seen:
                return None
            self.clipboard_seen = sequence
            return sequence if fresh and self.user.GetForegroundWindow() == hwnd else None
        finally:
            self.clipboard_lock.release()

    def pull(self, sequence):
        """Lo copiado allá, sólo si sigue siendo la copia anunciada por clipboard_changed."""
        with self.clipboard_lock:
            if self.user.GetClipboardSequenceNumber() != sequence:
                fail("Lo copiado allá cambió; copiá de nuevo")
            text = self.clipboard_text()
            if text is None:
                fail("Otro programa tiene abierto el portapapeles allá; volvé a intentar")
            return text

    def send_mouse(self, flags, delta=0):
        """Entrada Win32 con resultado verificable; mouse_event no informa si se insertó."""

        class Mouse(c.Structure):
            _fields_ = [
                ("dx", w.LONG),
                ("dy", w.LONG),
                ("data", w.DWORD),
                ("flags", w.DWORD),
                ("time", w.DWORD),
                ("extra", c.c_size_t),
            ]

        class Payload(c.Union):
            _fields_ = [("mouse", Mouse)]

        class Input(c.Structure):
            _fields_ = [("type", w.DWORD), ("payload", Payload)]

        entry = Input(0, Payload(mouse=Mouse(0, 0, delta & 0xFFFFFFFF, flags, 0, 0)))
        self.user.SendInput.argtypes = [w.UINT, c.c_void_p, c.c_int]
        if self.user.SendInput(1, c.byref(entry), c.sizeof(Input)) != 1:
            fail(
                "Windows no aceptó el clic o la rueda de Chrome; revisá que Chrome no esté ejecutándose como administrador"
            )

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
    el mismo stdout binario. `capture(hwnd, width, height)` y `locked()` se inyectan en las pruebas.
    Con la PC bloqueada no se captura: se avisa {"t": "desktop", "locked": true} y el visor pasa a la
    vista por pestanas hasta el aviso contrario."""

    def __init__(self, windows, out, capture=None, clock=time.monotonic, sleep=time.sleep, locked=None):
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
        self.last = None  # (hwnd, ancho, alto, bgra) del ultimo cuadro enviado
        self.v2 = False
        self.clipboard_ready = None  # numero del portapapeles anunciado al visor, hasta que lo pida
        self._prefetch = None  # (hwnd, futuro de la captura, cuando arranco)
        self._executor = None
        self.stats = {"capture": [], "encode": [], "frames": 0, "bytes": 0, "since": clock()}
        self.closed = False
        self.lock = LockWatch()
        self.lock_mutex = threading.Lock()  # el bloqueo lo tocan el hilo de stdin, el de captura y el suyo
        self.locked_now = locked or getattr(windows, "locked", lambda: False)

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
                self.v2 = data.get("v") == 2  # el visor entiende scroll y varios parches
                self.paused = False
                self.cv.notify_all()
            self.clipboard_ready = None
            self.json({"t": "opened", "window": str(hwnd)})
            with self.lock_mutex:
                if data.get("desktop") is True and not self.lock.locked:
                    # el visor que lo pide sabe el estado ya, sin esperar las lecturas de la histeresis
                    try:
                        if self.locked_now():
                            self.lock.force()
                    except OSError, ValueError:
                        pass
                if data.get("desktop") is True or self.lock.locked:
                    self.json({"t": "desktop", "locked": self.lock.locked})
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
        elif kind == "copy":
            if self.hwnd is None:
                fail("Todavía no hay una ventana abierta")
            try:
                self.json({"t": "clipboard", "text": self.windows.copy(self.hwnd)})
            except (ValueError, UnicodeError) as exc:
                self.json({"t": "error", "input": True, "message": str(exc)})
        elif kind == "pull":
            ready, self.clipboard_ready = self.clipboard_ready, None
            try:
                if ready is None:
                    fail("No hay nada copiado allá para traer")
                self.json({"t": "clipboard", "text": self.windows.pull(ready)})
            except (ValueError, UnicodeError) as exc:
                self.json({"t": "error", "input": True, "message": str(exc)})
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

    def must_wait(self):
        return self.hwnd is None or self.paused or self.in_flight >= MAX_IN_FLIGHT or self.lock.locked

    def check_lock(self, now):
        """Una lectura del bloqueo; si cambia (con histeresis), se avisa al visor y se despierta la
        captura. Si Windows no deja leerlo, esta vuelta no cuenta."""
        try:
            raw = self.locked_now()
        except OSError, ValueError:
            return
        with self.lock_mutex:
            self._lock_changed(self.lock.update(now, raw))

    def _lock_changed(self, locked):
        """Se llama con lock_mutex tomado: el aviso sale en el mismo orden que los cambios."""
        if locked is None:
            return
        with self.cv:
            self.cv.notify_all()
        self.json({"t": "desktop", "locked": locked})

    def run_lock(self):
        """Mira el bloqueo mientras hay una ventana abierta (tambien en pausa: el visor en espera se
        entera asi del desbloqueo). Termina con el worker o con stdout cerrado."""
        try:
            while not self.closed:
                if self.hwnd is not None:
                    self.check_lock(self.clock())
                self.sleep(LOCK_CHECK_S)
        except OSError, ValueError:
            pass  # stdout cerrado (ValueError si ya se cerro del todo): run() ya termina

    def step(self):
        """Una vuelta de captura: devuelve el cuadro emitido (cabecera, PNG) o None. Espera si hay
        demasiados cuadros sin acusar, no hay ventana o la PC esta bloqueada."""
        with self.cv:
            while not self.closed and self.must_wait():
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
            pixels, width, height = self._grab(hwnd, refit)
            if self.v2 and self.idle == 0:
                # con movimiento, la proxima captura arranca ya, mientras este cuadro se arma y viaja
                self._prefetch = (hwnd, self._pool().submit(self.capture, hwnd), self.clock())
            try:
                cursor = self.windows.cursor()
            except ValueError:
                # GetCursorInfo falla a ratos (medido el 2026-10-22) y antes cerraba la vista entera
                cursor = self.last_cursor
            if cursor != self.last_cursor:
                self.json({"t": "cursor", "cursor": cursor})
                self.last_cursor = cursor
            copied = self.windows.clipboard_changed(hwnd)
            if copied is not None:
                self.clipboard_ready = copied
                self.json({"t": "clipboard-ready"})
        except ValueError as exc:
            try:
                locked = self.locked_now()
            except OSError, ValueError:
                locked = False
            if locked:
                # con la sesion bloqueada BitBlt y PrintWindow fallan: no es un error de la vista, se
                # avisa el bloqueo ya (sin esperar la segunda lectura) y se retoma al desbloquear
                with self.lock_mutex:
                    self._lock_changed(self.lock.force())
                return None
            self.json({"t": "error", "message": str(exc)})
            with self.cv:
                if self.hwnd == hwnd:
                    self.hwnd = None
            return None
        last = self.last
        if self.v2:
            captured = self.clock()
            payload = frame_v2(
                self.seq + 1, pixels, width, height, last[3] if last and last[:3] == (hwnd, width, height) else None
            )
            self._measure(captured - started, self.clock() - captured, len(payload) if payload else 0)
            if payload is None:
                self.idle += 1
                pause = IDLE_INTERVAL_S if self.idle < IDLE_FAST_STEPS else IDLE_SLOW_S
                self.rest(max(0, pause - (self.clock() - started)))
                return None
            return self._send_frame(hwnd, width, height, pixels, payload, started)
        box = (0, 0, width, height)
        full = True
        if last and last[:3] == (hwnd, width, height):
            box = dirty_box(last[3], pixels, width, height)
            if box is None:
                self.idle += 1
                pause = IDLE_INTERVAL_S if self.idle < IDLE_FAST_STEPS else IDLE_SLOW_S
                self.rest(max(0, pause - (self.clock() - started)))
                return None
            if (box[2] - box[0]) * (box[3] - box[1]) < width * height * 0.7:
                full = False
            else:
                box = (0, 0, width, height)
        header = FRAME_HEADER.pack(
            self.seq + 1, box[0], box[1], box[2] - box[0], box[3] - box[1], width, height, FRAME_FULL if full else 0
        )
        return self._send_frame(hwnd, width, height, pixels, header + png(pixels, width, box), started)

    def _pool(self):
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="captura")
        return self._executor

    def _grab(self, hwnd, refit):
        """La captura adelantada si es de esta ventana y reciente; si no, una nueva. Medido el
        2026-10-21 en ar-it33940: captura 50 ms y armado 27 ms en serie daban 12 cuadros/s.
        PrintWindow y zlib sueltan el GIL, asi que las dos etapas se pisan."""
        pending, self._prefetch = self._prefetch, None
        if pending and pending[0] == hwnd and not refit:
            result = pending[1].result()  # una falla de la captura sube como ValueError, igual que sin adelantar
            if self.clock() - pending[2] <= PREFETCH_MAX_AGE_S:
                return result
        return self.capture(hwnd)

    def _measure(self, capture_s, encode_s, size):
        """Suma lo que tardo cada vuelta y cada segundo manda {"t": "stats"}: captura y armado del
        cuadro en ms (medianas) y cuadros enviados. Es lo que dice donde se va el tiempo en la PC de
        alla; el visor lo muestra y un visor viejo lo ignora."""
        st = self.stats
        st["capture"].append(capture_s * 1000)
        st["encode"].append(encode_s * 1000)
        st["frames"] += 1 if size else 0
        st["bytes"] += size
        if self.clock() - st["since"] < 1:
            return
        mid = lambda xs: round(sorted(xs)[len(xs) // 2], 1)
        self.json(
            {
                "t": "stats",
                "capture_ms": mid(st["capture"]),
                "encode_ms": mid(st["encode"]),
                "frames": st["frames"],
                "bytes": st["bytes"],
            }
        )
        self.stats = {"capture": [], "encode": [], "frames": 0, "bytes": 0, "since": self.clock()}

    def _send_frame(self, hwnd, width, height, pixels, payload, started):
        self.idle = 0
        self.seq += 1
        with self.cv:
            if self.hwnd != hwnd:
                return None  # cambio la ventana mientras se capturaba: el cuadro ya no vale
            self.last = (hwnd, width, height, pixels)
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
        threading.Thread(target=self.run_lock, daemon=True).start()
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
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
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
                result = windows.frame(
                    windows.target(data.get("window")),
                    data.get("width"),
                    data.get("height"),
                    data.get("delta", False),
                    data.get("base"),
                )
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
