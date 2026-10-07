"""Límites de la vista de Chrome, sin inyectar entrada en ventanas del usuario."""
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
    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 456,
                                   GetWindowThreadProcessId=lambda hwnd, pid: 2, AttachThreadInput=lambda source, target, attach: False)
    windows.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    with pytest.raises(ValueError, match="no se envió la entrada"):
        windows.input(123, [{"kind": "key", "keyCode": 65, "modifiers": 0, "type": "keyDown"}])


@pytest.mark.parametrize("key,modifiers", [(91, 0), (9, 1), (27, 10), (115, 1)])
def test_system_shortcuts_rejected_before_injection(key, modifiers):
    windows = module.Windows.__new__(module.Windows)
    windows.chrome = lambda hwnd: True
    windows.rect = lambda hwnd: SimpleNamespace(left=0, top=0, right=1280, bottom=800)
    windows.user = SimpleNamespace(IsIconic=lambda hwnd: False, SetForegroundWindow=lambda hwnd: None, GetForegroundWindow=lambda: 123)
    with pytest.raises(ValueError, match="atajo de Windows"):
        windows.input(123, [{"kind": "key", "keyCode": key, "modifiers": modifiers, "type": "keyDown"}])
