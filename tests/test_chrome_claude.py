"""chrome_claude.perfiles: los perfiles de Chrome con la extensión Claude in Chrome, sólo por metadatos."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lienzo"))

import chrome_claude


def _chrome(tmp_path, cache):
    (tmp_path / "Local State").write_text(json.dumps({"profile": {"info_cache": cache}}), encoding="utf-8")
    return tmp_path


def test_lista_solo_los_perfiles_con_la_extension(tmp_path):
    root = _chrome(
        tmp_path,
        {
            "Default": {"name": "Personal", "user_name": "yo@example.com"},
            "Profile 2": {"name": "Globant", "user_name": "ariel@example.com"},
            "System Profile": {"name": "x"},
            "Profile 3": {"name": "Sin extension"},
        },
    )
    for pid in ("Profile 2", "System Profile"):
        (root / pid / "Extensions" / chrome_claude.EXTENSION_ID).mkdir(parents=True)
    assert chrome_claude.perfiles(str(root)) == [{"id": "Profile 2", "name": "Globant", "cuenta": "ariel@example.com"}]


def test_conexiones_solo_hosts_con_el_origen_de_la_extension(monkeypatch):
    procesos = {
        10: (
            r"C:\x\Claude-NativeHost\2.42304.0\chrome-native-host.exe",
            f'"host.exe" {chrome_claude.ORIGEN} --parent-window=0',
        ),
        11: (r"C:\Windows\System32\cmd.exe", f'cmd /c "chrome-native-host.exe" {chrome_claude.ORIGEN}'),
        12: (r"C:\u\.local\bin\claude.exe", "claude.exe -n lienzo"),
        13: (r"C:\u\.local\bin\claude.exe", f"claude.exe --chrome-native-host {chrome_claude.ORIGEN}"),
        14: (r"C:\otro\chrome-native-host.exe", "chrome-native-host.exe chrome-extension://otra/"),
    }
    monkeypatch.setattr(chrome_claude.sys, "platform", "win32")
    monkeypatch.setattr(chrome_claude, "_pids", lambda: list(procesos))
    monkeypatch.setattr(chrome_claude.procinfo, "image_path", lambda pid: procesos[pid][0])
    monkeypatch.setattr(chrome_claude.procinfo, "command_line", lambda pid: procesos[pid][1])
    # 2026-10-21 17:19:19 UTC como FILETIME
    monkeypatch.setattr(chrome_claude.procs, "creation_filetime", lambda pid: 116444736000000000 + 1792603159 * 10**7)
    assert chrome_claude.conexiones() == [
        {"pid": 10, "host": "desktop", "desde": "2026-10-21T17:19:19+00:00"},
        {"pid": 13, "host": "code", "desde": "2026-10-21T17:19:19+00:00"},
    ]


def test_conexiones_fuera_de_windows_da_vacio(monkeypatch):
    monkeypatch.setattr(chrome_claude.sys, "platform", "linux")
    assert chrome_claude.conexiones() == []


def test_sin_chrome_o_local_state_roto_da_vacio(tmp_path):
    assert chrome_claude.perfiles(str(tmp_path)) == []
    (tmp_path / "Local State").write_text("{no", encoding="utf-8")
    assert chrome_claude.perfiles(str(tmp_path)) == []
    (tmp_path / "Local State").write_text('{"profile": []}', encoding="utf-8")
    assert chrome_claude.perfiles(str(tmp_path)) == []
