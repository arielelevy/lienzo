"""LIENZO_HOME (plan multi-PC §F0): state.py, auth.py y hook.py leen la carpeta de estado de ahi
si esta definida, y si no siguen en ~/.lienzo. Cada modulo la computa una sola vez al importarse
(igual que ya hace con HOME), asi que probar los dos casos en el mismo proceso no sirve: se corre
`python -c` como proceso nuevo, que es como corren de verdad el server y cada hook."""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIENZO_DIR = os.path.join(os.path.dirname(HERE), "lienzo")


def _env(**extra) -> dict:
    e = dict(os.environ)
    e.pop("LIENZO_HOME", None)
    e.update(extra)
    return e


def _run(code: str, env: dict) -> str:
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=LIENZO_DIR,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_state_sin_la_variable_sigue_en_home_lienzo(tmp_path):
    home = tmp_path / "casa"
    home.mkdir()
    out = _run(
        "import state as s\n"
        "print(s.LIENZO); print(s.EVENTS); print(s.PENDING); print(s.ANSWERS); print(s.ADJUNTOS); print(s.SESSIONS)",
        _env(USERPROFILE=str(home)),
    )
    esperado = str(home / ".lienzo")
    lines = out.splitlines()
    assert lines[0] == esperado
    assert lines[1:] == [os.path.join(esperado, d) for d in ("events", "pending", "answers", "adjuntos", "sessions")]


def test_state_con_la_variable_sale_de_ahi(tmp_path):
    home = tmp_path / "casa"
    custom = tmp_path / "otra-carpeta"
    out = _run(
        "import state as s\nprint(s.LIENZO); print(s.EVENTS); print(s.SESSIONS)",
        _env(USERPROFILE=str(home), LIENZO_HOME=str(custom)),
    )
    lines = out.splitlines()
    assert lines[0] == str(custom)
    assert lines[1] == str(custom / "events")
    assert lines[2] == str(custom / "sessions")


def test_auth_sale_de_la_misma_fuente_que_state(tmp_path):
    custom = tmp_path / "otra-carpeta"
    out = _run(
        "import auth as a\nprint(a.LIENZO); print(a.AUTH_FILE); print(a.WEB_SESSIONS)",
        _env(LIENZO_HOME=str(custom)),
    )
    lines = out.splitlines()
    assert lines[0] == str(custom)
    assert lines[1] == str(custom / "auth.json")
    assert lines[2] == str(custom / "sessions-web.json")


def test_auth_sin_la_variable_sigue_en_home_lienzo(tmp_path):
    home = tmp_path / "casa"
    home.mkdir()
    out = _run("import auth as a\nprint(a.LIENZO)", _env(USERPROFILE=str(home)))
    assert out.strip() == str(home / ".lienzo")


def test_hook_con_la_variable_sale_de_ahi(tmp_path):
    custom = tmp_path / "otra-carpeta"
    out = _run(
        "import hook\nprint(hook.LIENZO); print(hook.EVENTS); print(hook.PENDING); print(hook.ANSWERS)",
        _env(LIENZO_HOME=str(custom)),
    )
    lines = out.splitlines()
    assert lines[0] == str(custom)
    assert lines[1:] == [str(custom / d) for d in ("events", "pending", "answers")]


def test_hook_sin_la_variable_sigue_en_home_lienzo(tmp_path):
    home = tmp_path / "casa"
    home.mkdir()
    out = _run("import hook\nprint(hook.LIENZO)", _env(USERPROFILE=str(home)))
    assert out.strip() == str(home / ".lienzo")


def test_hook_prioriza_el_flag_de_argv_sobre_la_variable(tmp_path):
    de_la_variable = tmp_path / "de-la-variable"
    del_flag = tmp_path / "del-flag"
    code = (
        "import sys\n"
        f"sys.argv = ['hook.py', 'claude', '--lienzo-home', {str(del_flag)!r}]\n"
        "import hook\nprint(hook.LIENZO)"
    )
    out = _run(code, _env(LIENZO_HOME=str(de_la_variable)))
    assert out.strip() == str(del_flag)


def test_install_le_pasa_el_flag_al_hook_solo_si_la_variable_estaba_definida(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import install

    custom = str(tmp_path / "otra-carpeta")
    monkeypatch.setattr(install, "LIENZO_HOME", custom)
    assert f'--lienzo-home "{custom}"' in install.cmd("claude")
    entry = install.entry("coda", True, 5)
    assert entry["hooks"][0]["args"][-2:] == ["--lienzo-home", custom]

    monkeypatch.setattr(install, "LIENZO_HOME", None)
    assert "--lienzo-home" not in install.cmd("claude")
    entry = install.entry("coda", True, 5)
    assert "--lienzo-home" not in entry["hooks"][0]["args"]
