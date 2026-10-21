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


def test_sin_chrome_o_local_state_roto_da_vacio(tmp_path):
    assert chrome_claude.perfiles(str(tmp_path)) == []
    (tmp_path / "Local State").write_text("{no", encoding="utf-8")
    assert chrome_claude.perfiles(str(tmp_path)) == []
    (tmp_path / "Local State").write_text('{"profile": []}', encoding="utf-8")
    assert chrome_claude.perfiles(str(tmp_path)) == []
