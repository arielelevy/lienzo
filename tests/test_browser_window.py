"""Límites de la vista de Chrome, sin inyectar entrada en ventanas del usuario."""

import io
import json
import struct
import zlib
from types import SimpleNamespace

import browser_window as module
import pytest


def test_stream_copy_returns_text_from_selected_window():
    seen = []
    stream = module.Streamer(
        SimpleNamespace(copy=lambda hwnd: seen.append(hwnd) or "ñ 🧉"), io.BytesIO(), capture=lambda: None
    )
    stream.hwnd = 123
    messages = []
    stream.json = messages.append
    stream.handle({"t": "copy"})
    assert seen == [123]
    assert messages == [{"t": "clipboard", "text": "ñ 🧉"}]


def test_stream_copy_reports_error_without_returning_old_clipboard():
    def copy(hwnd):
        raise ValueError("Chrome no copió texto nuevo")

    stream = module.Streamer(SimpleNamespace(copy=copy), io.BytesIO(), capture=lambda: None)
    stream.hwnd = 123
    messages = []
    stream.json = messages.append
    stream.handle({"t": "copy"})
    assert messages == [{"t": "error", "input": True, "message": "Chrome no copió texto nuevo"}]


def test_copy_waits_for_new_clipboard_and_preserves_unicode(monkeypatch):
    import ctypes

    windows = module.Windows.__new__(module.Windows)
    windows.clipboard_lock = module.threading.RLock()
    content = ("selección ñ 🧉\0").encode("utf-16-le")
    buffer = ctypes.create_string_buffer(content)
    sequence = [1]
    closed = []
    windows.user = SimpleNamespace(
        GetClipboardSequenceNumber=lambda: sequence[0],
        OpenClipboard=lambda owner: True,
        GetClipboardData=lambda format: 99,
        CloseClipboard=lambda: closed.append(True),
    )
    windows.kernel = SimpleNamespace(
        GlobalSize=lambda handle: len(content),
        GlobalLock=lambda handle: ctypes.addressof(buffer),
        GlobalUnlock=lambda handle: None,
    )
    windows.release = lambda: None
    windows.input = lambda hwnd, events: sequence.__setitem__(0, 2)
    windows.active = windows.chrome = lambda hwnd: True
    assert windows.copy(123) == "selección ñ 🧉"
    assert closed == [True]


def test_copy_rejects_stale_clipboard(monkeypatch):
    windows = module.Windows.__new__(module.Windows)
    windows.clipboard_lock = module.threading.RLock()
    windows.user = SimpleNamespace(GetClipboardSequenceNumber=lambda: 7)
    windows.release = lambda: None
    windows.input = lambda hwnd, events: None
    windows.active = windows.chrome = lambda hwnd: True
    ticks = iter([0, 0.1, 2])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    with pytest.raises(ValueError, match="no copió texto nuevo"):
        windows.copy(123)


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
    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        SetForegroundWindow=lambda hwnd: None,
        GetForegroundWindow=lambda: 456,
        GetWindowThreadProcessId=lambda hwnd, pid: 2,
        AttachThreadInput=lambda source, target, attach: False,
        keybd_event=lambda *a: None,
        SwitchToThisWindow=lambda hwnd, alt: None,
        ShowWindow=lambda hwnd, cmd: None,
        SystemParametersInfoW=lambda *a: 1,
    )
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.describe = lambda hwnd: "ConsoleWindowClass · Teorema · WindowsTerminal.exe"
    with pytest.raises(
        ValueError, match="no se envió la entrada. Al frente está: ConsoleWindowClass · Teorema · WindowsTerminal.exe"
    ):
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

    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        SetForegroundWindow=set_foreground,
        GetForegroundWindow=lambda: foreground[0],
        keybd_event=lambda vk, scan, flags, extra: calls.append("shift" if vk == 16 and flags == 0 else "shift-up"),
        GetWindowThreadProcessId=lambda hwnd, pid: 2,
        AttachThreadInput=lambda source, target, attach: calls.append("attach") or True,
        BringWindowToTop=lambda hwnd: calls.append("top"),
        SwitchToThisWindow=lambda hwnd, alt: calls.append("switch"),
        ShowWindow=lambda hwnd, cmd: calls.append({6: "min", 9: "restore"}.get(cmd, cmd)),
        SystemParametersInfoW=lambda *a: calls.append("lock0") or 1,
    )
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
    assert calls == [
        "foreground",
        "shift",
        "shift-up",
        "foreground",
        "attach",
        "top",
        "foreground",
        "attach",
        "switch",
        "min",
        "restore",
    ]


def test_focus_succeeds_through_switch_or_restore_without_failing():
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    foreground = [456]

    def switch(hwnd, alt):
        foreground[0] = hwnd

    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        SetForegroundWindow=lambda hwnd: None,
        GetForegroundWindow=lambda: foreground[0],
        keybd_event=lambda *a: None,
        GetWindowThreadProcessId=lambda hwnd, pid: 2,
        AttachThreadInput=lambda s_, t, a: False,
        SwitchToThisWindow=switch,
        ShowWindow=lambda hwnd, cmd: None,
        SystemParametersInfoW=lambda *a: 1,
    )
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.focus(123)  # SwitchToThisWindow alcanzo: no hay error
    foreground[0] = 456
    windows.user.SwitchToThisWindow = lambda hwnd, alt: None
    windows.user.ShowWindow = lambda hwnd, cmd: foreground.__setitem__(0, hwnd) if cmd == 9 else None
    windows.focus(123)  # restaurar alcanzo


def test_focus_detects_the_windows_lock_screen_and_does_not_try_anything():
    """Medido el 2026-10-08 desde la otra PC: GetForegroundWindow no da 0 con la sesion bloqueada,
    da la ventana de LockApp.exe; los trucos de foco no sirven y el aviso tiene que decir eso."""
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    calls = []
    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        GetForegroundWindow=lambda: 777,
        SetForegroundWindow=lambda hwnd: calls.append("foreground"),
        keybd_event=lambda *a: calls.append("key"),
        SystemParametersInfoW=lambda *a: calls.append("lock0") or 1,
    )
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.describe = lambda hwnd: (
        "Windows.UI.Core.CoreWindow · Pantalla de bloqueo predeterminada de Windows · LockApp.exe"
    )
    with pytest.raises(ValueError, match="bloqueada .*desbloqueala allá"):
        windows.focus(123)
    assert calls == []


def test_focus_says_when_the_pc_is_locked():
    windows = module.Windows.__new__(module.Windows)
    windows.owner = lambda hwnd: hwnd
    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        SetForegroundWindow=lambda hwnd: None,
        GetForegroundWindow=lambda: 0,
        keybd_event=lambda *a: None,
        GetWindowThreadProcessId=lambda hwnd, pid: 0,
        AttachThreadInput=lambda source, target, attach: False,
        SwitchToThisWindow=lambda hwnd, alt: None,
        ShowWindow=lambda hwnd, cmd: None,
        SystemParametersInfoW=lambda *a: 1,
    )
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    windows.describe = lambda hwnd: "?"
    with pytest.raises(ValueError, match="no tiene escritorio activo"):
        windows.focus(123)


NAMES = {"Default": "Persona", "Profile 1": "Ariel", "Profile 3": "globant.com"}


@pytest.mark.parametrize(
    "app_id,relaunch,expected",
    [
        # medido el 2026-10-22 en esta PC, con los dos perfiles de Ariel abiertos
        ("Chrome.UserData.Profile3", '"C:/x/chrome.exe" --profile-directory="Profile 3"', "globant.com"),
        ("Chrome.UserData.Profile1", None, "Ariel"),  # sin comando de relanzado: el id sin espacios
        ("Chrome.UserData.Profile9", None, None),  # un perfil que Local State no nombra
        ("Chrome.Pchrome33680.Default", None, None),  # otra carpeta de datos (un Chrome aislado)
        ("Chrome", None, None),
        # el perfil Default de la carpeta de siempre tiene el id «Chrome» a secas (revisión 2026-10-22)
        ("Chrome", '"C:/x/chrome.exe" --profile-directory="Default"', "Persona"),
        ("Chrome", '"C:/x/chrome.exe" --user-data-dir="D:/otra" --profile-directory="Default"', None),
        (None, None, None),
    ],
)
def test_profile_label_from_the_window_app_id(app_id, relaunch, expected):
    assert module.profile_label(app_id, relaunch, NAMES) == expected


def test_profile_names_reads_local_state_and_ignores_the_rest():
    text = json.dumps({"profile": {"info_cache": {"Profile 1": {"name": "Ariel"}, "System Profile": {"name": "x"}}}})
    assert module.profile_names(text) == {"Profile 1": "Ariel"}
    assert module.profile_names("no es json") == {}


def test_windows_list_says_the_profile_of_each_chrome_window():
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: True
    titles = {11: "YouTube - Google Chrome", 12: "Nueva pestaña - Google Chrome"}

    def enum(callback, _):
        for hwnd in titles:
            callback(hwnd, 0)

    def text(hwnd, buffer, size):
        buffer.value = titles[hwnd]

    windows.user = SimpleNamespace(EnumWindows=enum, GetWindowTextW=text, GetForegroundWindow=lambda: 12)
    reads = []
    windows.profile_names = lambda: reads.append(1) or NAMES
    windows.profile = lambda hwnd, names: {11: "Ariel", 12: None}[hwnd] if names is NAMES else "?"
    assert windows.windows() == [
        {"id": "12", "title": "Nueva pestaña - Google Chrome"},
        {"id": "11", "title": "YouTube - Google Chrome", "profile": "Ariel"},
    ]
    assert reads == [1]  # Local State se lee una vez por lista, no una por ventana


@pytest.mark.parametrize(
    "desktop,front,locked",
    [
        ("Default", "Chrome_WidgetWin_1 · x · chrome.exe", False),
        ("Default", "Windows.UI.Core.CoreWindow · Pantalla de bloqueo predeterminada de Windows · LockApp.exe", True),
        ("Winlogon", "?", True),  # pedir la contraseña o el escritorio seguro de UAC
        (None, None, True),  # sin acceso al escritorio de entrada ni ventana al frente: bloqueada
        # sin acceso pero con una ventana normal al frente no es bloqueo (revisión: un contexto sin
        # permiso de escritorio dejaba la vista quieta para siempre)
        (None, "Chrome_WidgetWin_1 · x · chrome.exe", False),
        ("Default", None, False),  # un instante sin ventana al frente (Alt+Tab) no es bloqueo
    ],
)
def test_locked_reads_the_input_desktop_and_the_lock_screen(desktop, front, locked):
    windows = module.Windows.__new__(module.Windows)
    windows.input_desktop = lambda: desktop
    windows.user = SimpleNamespace(GetForegroundWindow=lambda: 0 if front is None else 5)
    windows.describe = lambda hwnd: front
    assert windows.locked() is locked


def test_lock_watch_enters_after_two_reads_and_leaves_after_three_quiet_seconds():
    watch = module.LockWatch()
    assert [watch.update(t, raw) for t, raw in [(0, False), (0.5, True), (1.0, True)]] == [None, None, True]
    # desbloqueo con un rebote: el plazo de salida vuelve a empezar
    steps = [(1.5, False), (2.0, True), (2.5, False), (5.4, False), (5.6, False), (6.0, False)]
    assert [watch.update(t, raw) for t, raw in steps] == [None, None, None, None, False, None]
    assert watch.update(6.5, True) is None and watch.locked is False


@pytest.mark.parametrize("key,modifiers", [(91, 0), (9, 1), (27, 10), (115, 1)])
def test_system_shortcuts_rejected_before_injection(key, modifiers):
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=1280, bottom=800)
    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 123
    )
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

    windows.user = SimpleNamespace(
        IsIconic=lambda hwnd: False,
        GetForegroundWindow=lambda: 456,
        SetForegroundWindow=lambda hwnd: calls.append("foreground"),
        SetCursorPos=lambda x, y: True,
        mouse_event=lambda *a: calls.append(a),
        GetCursorPos=cursor,
    )
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


@pytest.mark.parametrize("clip_ok", [True, False])
def test_mouse_position_mismatch_reports_requested_observed_and_bounds_without_click(clip_ok):
    windows = module.Windows.__new__(module.Windows)
    windows.focus = lambda hwnd: None
    windows.active = windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=-100, top=10, right=100, bottom=110)
    calls = []

    def observed(point):
        point._obj.x, point._obj.y = -90, 30
        return True

    def clip(area):
        area._obj.left, area._obj.top, area._obj.right, area._obj.bottom = -90, 20, 100, 100
        return clip_ok

    windows.user = SimpleNamespace(
        SetCursorPos=lambda x, y: calls.append((x, y)) or True,
        GetCursorPos=observed,
        GetClipCursor=clip,
    )
    windows.send_mouse = lambda flag: calls.append(flag)
    with pytest.raises(ValueError) as raised:
        windows.input(123, [{"kind": "mouse", "type": "mousePressed", "x": 5, "y": 6, "button": "left"}])
    assert "pedido=(-95,16)" in str(raised.value)
    assert "observado=(-90,30)" in str(raised.value)
    assert ("área permitida=(-90,20,100,100)" if clip_ok else "área permitida no disponible") in str(raised.value)
    assert calls == [(-95, 16)]  # un solo movimiento, ningún clic ni retry


def test_mouse_position_read_failure_does_not_claim_cursor_was_clipped_or_click():
    windows = module.Windows.__new__(module.Windows)
    windows.focus = lambda hwnd: None
    windows.active = windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=100, bottom=100)
    calls = []
    windows.user = SimpleNamespace(SetCursorPos=lambda x, y: True, GetCursorPos=lambda point: False)
    windows.send_mouse = lambda flag: calls.append(flag)
    with pytest.raises(ValueError, match="no permitió comprobar la posición"):
        windows.input(123, [{"kind": "mouse", "type": "mousePressed", "x": 5, "y": 6, "button": "left"}])
    assert calls == []


def test_control_a_restores_modifier_before_key_and_releases_it():
    windows = module.Windows.__new__(module.Windows)
    windows.focus = lambda hwnd: None
    windows.active = windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=1280, bottom=800)
    calls = []
    windows.user = SimpleNamespace(keybd_event=lambda *args: calls.append(args))
    windows.pressed = set()
    windows.input(
        1,
        [
            {"kind": "key", "keyCode": 65, "modifiers": 2, "type": "keyDown"},
            {"kind": "key", "keyCode": 65, "modifiers": 2, "type": "keyUp"},
            {"kind": "key", "keyCode": 17, "modifiers": 0, "type": "keyUp"},
        ],
    )
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

    windows.user = SimpleNamespace(
        EnumWindows=enumerate_windows,
        IsWindowVisible=lambda hwnd: hwnd != 5,
        GetAncestor=lambda hwnd, flag: 1 if hwnd in [2, 4, 5] else hwnd,
    )
    assert windows.popups(1) == [2]  # no otra ventana principal ni otro proceso ni un menú oculto


# --- captura continua (Streamer) y caja de cambios, sin Win32 ---------------------------------


def px(color):
    """Un pixel como lo deja la captura de Windows: BGRA (el color se escribe en RGB)."""
    return bytes((color[2], color[1], color[0], 255))


def rgb(width, height, color=(255, 255, 255)):
    return px(color) * (width * height)


def paint(frame, width, x, y, w, h, color):
    data = bytearray(frame)
    for row in range(y, y + h):
        data[(row * width + x) * 4 : (row * width + x + w) * 4] = px(color) * w
    return bytes(data)


def to_bgra(line):
    out = bytearray(b"\xff" * (len(line) // 3 * 4))
    out[0::4], out[1::4], out[2::4] = line[2::3], line[1::3], line[0::3]
    return bytes(out)


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
    idat = data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 4]
    assert zlib.decompress(idat) == (b"\x00" + bytes((9, 8, 7)) * 3) * 2


def test_png_takes_the_bgra_capture_and_writes_rgb():
    # la captura queda en BGRA: convertirla entera costaba 8-12 ms por cuadro (2026-10-22); solo se
    # convierte lo que viaja
    frame = bytes((1, 2, 3, 255)) * 8 + bytes((4, 5, 6, 255)) * 8
    data = module.png(frame, 4, (1, 2, 3, 4))
    assert struct.unpack(">II", data[16:24]) == (2, 2)
    idat = data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 4]
    assert zlib.decompress(idat) == (b"\x00" + bytes((6, 5, 4)) * 2) * 2


def page(width, height, offset, header=20, sidebar=40):
    """Una pagina con encabezado y barra lateral fijos y un contenido de filas distintas, corrido
    `offset` filas hacia arriba (scroll)."""
    data = bytearray()
    for y in range(height):
        for x in range(width):
            if y < header:
                data += px((10, 10, 10))
            elif x < sidebar:
                data += px((200, y % 251, 0))  # fija, pero distinta en cada fila (texto)
            else:
                r = y + offset
                data += px(((r * 7) % 251, (r * 13 + x // 50) % 251, (r * 31) % 251))
    return bytes(data)


def apply_v2(canvas, width, payload):
    """Lo que hace el visor con un cuadro v2: corre la imagen y pega los parches (PNG sin filtros)."""
    *_, fw, fh, flags = module.FRAME_HEADER.unpack(payload[: module.FRAME_HEADER.size])
    assert flags & module.FRAME_V2 and fw == width
    pos = module.FRAME_HEADER.size
    dy, x0, x1, top, bottom, count = module.SCROLL.unpack(payload[pos : pos + module.SCROLL.size])
    pos += module.SCROLL.size
    out = bytearray(canvas)
    if dy:
        out = bytearray(module.shifted(bytes(canvas), width, (dy, x0, x1, top, bottom)))
    for _ in range(count):
        x, y, w, h, n = module.PATCH.unpack(payload[pos : pos + module.PATCH.size])
        pos += module.PATCH.size
        data = payload[pos : pos + n]
        pos += n
        rows = zlib.decompress(data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 4])
        for r in range(h):
            line = rows[r * (w * 3 + 1) + 1 : (r + 1) * (w * 3 + 1)]  # el PNG viaja en RGB
            out[((y + r) * width + x) * 4 : ((y + r) * width + x + w) * 4] = to_bgra(line)
    assert pos == len(payload)
    return bytes(out), (dy, x0, x1, top, bottom), count


def test_frame_v2_scroll_copies_the_content_and_sends_only_the_new_strip():
    w, h = 160, 120
    old, new = page(w, h, 0), page(w, h, 37)
    payload = module.frame_v2(5, new, w, h, old)
    canvas, scroll, count = apply_v2(old, w, payload)
    assert canvas == new  # la copia mas los parches reconstruyen el cuadro exacto
    dy, x0, x1, top, bottom = scroll
    assert dy == -37 and x0 == 40 and x1 == w  # la barra lateral fija no se corre
    assert count == 1 and len(payload) < len(module.png(new, w, (0, 0, w, h))) / 2


def menu_page(width, height, offset, sidebar=48):
    """Como la barra de navegacion de una pagina real: fija, gris parejo y con un renglon de texto
    cada 32 filas. Un muestreo de pocas filas cae en el gris y la cree parte del contenido corrido."""
    data = bytearray()
    for y in range(height):
        for x in range(width):
            if x < sidebar:
                data += px((0, 0, 0)) if y % 32 == 11 and 6 <= x < 40 else px((240, 240, 240))
            else:
                r = y + offset
                data += px(((r * 7) % 251, (r * 13 + x // 50) % 251, (r * 31) % 251))
    return bytes(data)


def test_frame_v2_scroll_leaves_a_fixed_sparse_text_menu_out_of_the_copy():
    # medido el 2026-10-22 con la página de prueba: la copia tomaba la barra lateral y dejaba 15 parches por cuadro
    w, h = 240, 240
    old, new = menu_page(w, h, 0), menu_page(w, h, 41)
    payload = module.frame_v2(5, new, w, h, old)
    canvas, scroll, count = apply_v2(old, w, payload)
    assert canvas == new
    # el texto del menu llega a x=40; el gris liso de 40 a 48 da igual corrido o no
    assert scroll[0] == -41 and 40 <= scroll[1] <= 48 and scroll[2] == w
    assert count == 1  # sólo la franja nueva de abajo


def test_frame_v2_scroll_reaches_past_a_small_floating_box():
    # un reloj o boton fijo arriba a la derecha cortaba la copia y el texto de ese lado viajaba
    # como un parche por renglon (14 por cuadro con la pagina de prueba)
    w, h = 240, 240
    old, new = (paint(page(w, h, offset, header=0, sidebar=0), w, 200, 30, 30, 12, (255, 255, 0)) for offset in (0, 23))
    payload = module.frame_v2(5, new, w, h, old)
    canvas, scroll, count = apply_v2(old, w, payload)
    assert canvas == new
    assert scroll[0] == -23 and scroll[1] == 0 and scroll[2] == w
    assert count == 3  # la franja nueva y el recuadro fijo donde estaba y donde esta


def test_span_box_is_exact_to_the_pixel():
    base = rgb(200, 10)
    changed = paint(base, 200, 70, 2, 5, 3, (0, 0, 0))
    assert module.span_box(base, changed, 200, 0, 10) == (70, 0, 75, 10)
    assert module.span_box(base, base, 200, 0, 10) is None
    edge = paint(base, 200, 199, 9, 1, 1, (254, 255, 255))  # un solo byte, del ultimo pixel
    assert module.span_box(base, edge, 200, 0, 10) == (199, 0, 200, 10)


def test_dirty_rects_over_the_limit_merges_neighbours_not_everything():
    # 20 cambios chicos en dos columnas lejanas: la caja de todos cubría el cuadro entero
    w, h = 400, 400
    base = rgb(w, h)
    changed = base
    for i in range(20):
        changed = paint(changed, w, 4 if i % 2 else 380, i * 20, 8, 3, (0, 0, 0))
    boxes = module.dirty_rects(base, changed, w, h)
    assert len(boxes) <= module.MAX_PATCHES
    assert sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes) < w * h * 0.15
    canvas = bytearray(base)
    for left, top, right, bottom in boxes:
        for y in range(top, bottom):
            canvas[(y * w + left) * 4 : (y * w + right) * 4] = changed[(y * w + left) * 4 : (y * w + right) * 4]
    assert bytes(canvas) == changed


def test_frame_v2_separate_patches_and_none_when_equal():
    base = rgb(200, 100)
    assert module.frame_v2(1, base, 200, 100, base) is None
    changed = paint(paint(base, 200, 5, 2, 3, 2, (0, 0, 0)), 200, 150, 90, 4, 4, (1, 2, 3))
    payload = module.frame_v2(2, changed, 200, 100, base)
    canvas, scroll, count = apply_v2(base, 200, payload)
    assert canvas == changed and scroll[0] == 0 and count == 2  # dos esquinas: dos parches, no una caja


def test_frame_v2_full_without_previous():
    frame = page(64, 40, 0)
    payload = module.frame_v2(1, frame, 64, 40, None)
    assert module.FRAME_HEADER.unpack(payload[: module.FRAME_HEADER.size])[-1] == module.FRAME_V2 | module.FRAME_FULL
    assert apply_v2(rgb(64, 40), 64, payload)[0] == frame


def test_streamer_uses_v2_only_when_the_viewer_asks():
    base = rgb(8, 4)
    streamer, out, windows, captures = make_streamer([base, base])
    streamer.handle({"t": "open", "window": "7", "v": 2})
    first = streamer.step()
    assert module.FRAME_HEADER.unpack(first[: module.FRAME_HEADER.size])[-1] & module.FRAME_V2
    streamer.handle({"t": "open", "window": "7"})
    second = streamer.step()
    assert not module.FRAME_HEADER.unpack(second[: module.FRAME_HEADER.size])[-1] & module.FRAME_V2


def test_streamer_v2_prefetches_the_next_capture_only_while_moving():
    base = rgb(8, 4)
    changed = paint(base, 8, 1, 1, 1, 1, (0, 0, 0))
    streamer, out, windows, captures = make_streamer([base, changed, changed, changed, changed])
    streamer.handle({"t": "open", "window": "7", "v": 2})
    assert streamer.step()  # completo; arranca la captura siguiente
    streamer._prefetch[1].result()
    assert len(captures) == 2
    streamer.handle({"t": "ack", "n": 1})
    patch = streamer.step()  # usa la adelantada: no captura de nuevo en el momento
    assert patch and len(captures) >= 2
    streamer._prefetch[1].result()
    streamer.handle({"t": "ack", "n": 2})
    assert streamer.step() is None and streamer.idle == 1  # sin cambios: la adelantada de esta vuelta queda
    streamer._prefetch[1].result()
    assert streamer.step() is None and streamer.idle == 2
    assert streamer._prefetch is None  # quieta: ya no adelanta


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

    copied = None
    pulled = ()

    def clipboard_changed(self, hwnd):
        copied, self.copied = self.copied, None
        return copied

    def pull(self, sequence):
        self.pulled = [*self.pulled, sequence]
        return "copiado allá"


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
        items.append((chr(kind), data[5 : 4 + n]))
        data = data[4 + n :]
    return items


def test_streamer_sends_full_then_patch_then_nothing_and_waits_for_acks():
    base = rgb(8, 4)
    changed = paint(base, 8, 1, 1, 1, 1, (0, 0, 0))
    streamer, out, windows, captures = make_streamer([base, base, changed, changed])
    streamer.handle({"t": "open", "window": "7", "width": 1280, "height": 720})
    assert json.loads(records(out)[0][1]) == {"t": "opened", "window": "7"}
    first = streamer.step()
    assert module.FRAME_HEADER.unpack(first[: module.FRAME_HEADER.size]) == (1, 0, 0, 8, 4, 8, 4, module.FRAME_FULL)
    assert captures[0] == (7, None, None) and windows.fits == [(7, 1280, 720)]
    assert streamer.step() is None  # sin cambios: nada viaja
    assert windows.fits == [(7, 1280, 720)]  # el ajuste de tamano no se repite cuadro a cuadro
    patch = streamer.step()
    assert module.FRAME_HEADER.unpack(patch[: module.FRAME_HEADER.size])[:5] == (2, 0, 1, 8, 1)
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


def test_streamer_tells_the_viewer_when_the_pc_locks_and_does_not_capture_meanwhile():
    base = rgb(8, 4)
    changed = paint(base, 8, 1, 1, 1, 1, (0, 0, 0))
    streamer, out, windows, captures = make_streamer([base, changed])
    lock = [False]
    streamer.locked_now = lambda: lock[0]
    streamer.handle({"t": "open", "window": "7"})
    assert streamer.step()
    lock[0] = True
    streamer.check_lock(10.0)
    streamer.check_lock(10.5)
    assert json.loads(records(out)[-1][1]) == {"t": "desktop", "locked": True}
    assert streamer.must_wait() and len(captures) == 1  # bloqueada: el hilo de captura espera
    streamer.handle({"t": "open", "window": "7"})  # un visor que reconecta se entera enseguida
    assert [json.loads(p) for k, p in records(out)[-2:]] == [
        {"t": "opened", "window": "7"},
        {"t": "desktop", "locked": True},
    ]
    lock[0] = False
    streamer.check_lock(11.0)
    streamer.check_lock(14.1)
    assert json.loads(records(out)[-1][1]) == {"t": "desktop", "locked": False}
    assert not streamer.must_wait()


@pytest.mark.parametrize("locked", [False, True])
def test_open_with_desktop_reports_the_state_right_away(locked):
    # un visor que reconecta en la vista por pestanas puesta por el bloqueo tiene que saber ya si
    # sigue bloqueada: sin esto el worker nuevo arranca «desbloqueado» y el visor oscilaba
    streamer, out, windows, _ = make_streamer([])
    streamer.locked_now = lambda: locked
    streamer.handle({"t": "open", "window": "7", "desktop": True})
    assert json.loads(records(out)[-1][1]) == {"t": "desktop", "locked": locked}
    assert streamer.lock.locked is locked


def test_a_capture_failure_with_the_pc_locked_keeps_the_view_open():
    # con la sesion bloqueada BitBlt y PrintWindow fallan: antes la vista se cerraba con un error
    streamer, out, windows, _ = make_streamer([])
    streamer.capture = lambda hwnd, width=None, height=None: module.fail("Windows no pudo capturar Chrome")
    streamer.locked_now = lambda: True
    streamer.handle({"t": "open", "window": "7"})
    assert streamer.step() is None and streamer.hwnd == 7
    texts = [json.loads(payload) for kind, payload in records(out) if kind == "J"]
    assert texts[-1] == {"t": "desktop", "locked": True}
    assert not any(t["t"] == "error" for t in texts)


def test_lock_thread_ends_quietly_when_the_output_is_closed():
    # revisión 2026-10-22: escribir en un stdout cerrado da ValueError y el hilo moría con traza
    streamer, out, windows, _ = make_streamer([])
    streamer.handle({"t": "open", "window": "7"})
    streamer.locked_now = lambda: True
    out.close()
    streamer.run_lock()  # no levanta


def test_lock_thread_does_not_look_without_a_window():
    streamer, out, windows, _ = make_streamer([])
    looked = []
    streamer.locked_now = lambda: looked.append(1) or False

    def sleep(seconds):
        streamer.closed = True

    streamer.sleep = sleep
    streamer.run_lock()
    assert looked == []


def test_a_cursor_read_failure_does_not_end_the_view():
    # medido el 2026-10-22: GetCursorInfo falla a ratos y la vista entera se cerraba con ese error
    base = rgb(8, 4)
    streamer, out, windows, _ = make_streamer([base])
    windows.cursor = lambda: module.fail("Windows no pudo leer el cursor de Chrome")
    streamer.handle({"t": "open", "window": "7"})
    assert streamer.step() is not None and streamer.hwnd == 7
    assert not any(json.loads(p)["t"] == "error" for k, p in records(out) if k == "J")


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


class FakeClipboard:
    """Portapapeles de Windows en memoria: número de secuencia, dueño y un solo texto."""

    def __init__(self, text=None, sequence=1):
        import ctypes

        self.ctypes = ctypes
        self.sequence = sequence
        self.text = text
        self.open = None
        self.buffers = {}
        self.freed = []
        self.events = []

    def user(self, **extra):
        def open_clipboard(owner):
            if self.open is not None:
                return False
            self.open = owner
            return True

        def close():
            self.open = None
            return True

        def empty():
            self.text = None
            self.sequence += 1
            return True

        def set_data(fmt, handle):
            if not self.open:  # sin ventana dueña, Windows rechaza SetClipboardData
                return None
            raw = self.buffers[handle].raw
            self.text = raw.decode("utf-16-le").split("\0", 1)[0]
            return handle

        def get_data(fmt):
            if self.text is None:
                return None
            data = (self.text + "\0").encode("utf-16-le")
            self.buffers[999] = self.ctypes.create_string_buffer(data, len(data))
            return 999

        return SimpleNamespace(
            GetClipboardSequenceNumber=lambda: self.sequence,
            OpenClipboard=open_clipboard,
            CloseClipboard=close,
            EmptyClipboard=empty,
            SetClipboardData=set_data,
            GetClipboardData=get_data,
            CreateWindowExW=lambda *args: 4242,
            DestroyWindow=lambda hwnd: True,
            keybd_event=lambda key, scan, flags, extra_info: self.events.append((key, flags)),
            **extra,
        )

    def kernel(self):
        def alloc(flags, size):
            handle = 100 + len(self.buffers)
            self.buffers[handle] = self.ctypes.create_string_buffer(size)
            return handle

        return SimpleNamespace(
            GlobalAlloc=alloc,
            GlobalFree=lambda handle: self.freed.append(handle),
            GlobalLock=lambda handle: self.ctypes.addressof(self.buffers[handle]),
            GlobalUnlock=lambda handle: True,
            GlobalSize=lambda handle: len(self.buffers[handle]),
        )


def clipboard_windows(board, foreground=True):
    windows = module.Windows.__new__(module.Windows)
    windows.user = board.user(GetForegroundWindow=lambda: 123)
    windows.kernel = board.kernel()
    windows.pressed = set()
    windows.mouse_pressed = set()
    windows.clipboard_lock = module.threading.RLock()
    windows.clipboard_seen = board.sequence
    windows.focus = lambda hwnd: None
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=100, bottom=100)
    windows.active = lambda hwnd: foreground
    windows.chrome = lambda hwnd: True
    return windows


def test_paste_puts_local_text_in_the_remote_clipboard_and_presses_ctrl_v():
    board = FakeClipboard(text="lo que había allá")
    windows = clipboard_windows(board)
    windows.input(123, [{"kind": "paste", "text": "línea 1\nñ 🧉"}])
    assert board.text == "línea 1\r\nñ 🧉"  # CF_UNICODETEXT usa CRLF
    assert board.open is None
    assert (86, 0) in board.events and (17, 0) in board.events  # Ctrl+V abajo
    assert board.events[-1] == (17, 2)  # y Ctrl suelto al final
    assert windows.clipboard_seen == board.sequence  # lo pegado no se anuncia como copia de allá


@pytest.mark.parametrize("text", [None, 5, "", "x" * (module.PASTE_MAX_CHARS + 1)])
def test_paste_rejects_non_text_empty_or_oversized_without_touching_the_clipboard(text):
    board = FakeClipboard(text="lo que había allá")
    windows = clipboard_windows(board)
    with pytest.raises(ValueError):
        windows.input(123, [{"kind": "paste", "text": text}])
    assert board.text == "lo que había allá" and board.events == []


def test_paste_reports_a_clipboard_held_by_another_program(monkeypatch):
    board = FakeClipboard(text="lo que había allá")
    board.open = 77  # otro programa lo tiene abierto
    windows = clipboard_windows(board)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    with pytest.raises(ValueError, match="portapapeles"):
        windows.input(123, [{"kind": "paste", "text": "hola"}])
    assert board.events == []  # sin texto puesto no se aprieta Ctrl+V


def test_remote_copy_is_announced_without_content_only_with_that_chrome_window_in_front(monkeypatch):
    board = FakeClipboard(text="viejo", sequence=5)
    windows = clipboard_windows(board)
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    assert windows.clipboard_changed(123) is None  # sin cambios desde que se abrió
    board.text, board.sequence = "copiado en Chrome", 6
    assert windows.clipboard_changed(123) == 6
    assert windows.clipboard_changed(123) is None  # se anuncia una sola vez
    front = [77]
    windows.user.GetForegroundWindow = lambda: front[0]  # otra ventana (u otro Chrome) al frente
    board.text, board.sequence = "copiado en otro programa", 7
    assert windows.clipboard_changed(123) is None
    front[0] = 123
    board.text, board.sequence = "contraseña copiada mientras no se miraba", 8
    clock[0] += 30  # visor en pausa: nadie miró en 30 s
    assert windows.clipboard_changed(123) is None
    assert windows.clipboard_changed(123) is None  # y no se anuncia después


def test_pull_reads_only_the_announced_copy():
    board = FakeClipboard(text="copiado en Chrome", sequence=6)
    windows = clipboard_windows(board)
    assert windows.pull(6) == "copiado en Chrome"
    board.text, board.sequence = "otra cosa", 7
    with pytest.raises(ValueError, match="cambió"):
        windows.pull(6)


def test_streamer_announces_remote_copy_and_pulls_it_on_request():
    streamer, out, windows, _ = make_streamer([rgb(8, 4)])
    streamer.handle({"t": "open", "window": "7"})
    windows.copied = 9
    streamer.step()
    streamer.handle({"t": "pull"})
    texts = [json.loads(payload) for kind, payload in records(out) if kind == "J"]
    assert {"t": "clipboard-ready"} in texts
    assert texts[-1] == {"t": "clipboard", "text": "copiado allá"}
    assert windows.pulled == [9]
    streamer.handle({"t": "pull"})  # sin otra copia anunciada no se lee nada
    texts = [json.loads(payload) for kind, payload in records(out) if kind == "J"]
    assert texts[-1]["t"] == "error" and windows.pulled == [9]
