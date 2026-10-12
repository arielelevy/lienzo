"""El archivo vigente decide el acceso, incluso si conserva timestamp y tamaño."""

import json
import os

import auth
import pytest


@pytest.fixture
def sessions_file(tmp_path, monkeypatch):
    path = tmp_path / "sessions-web.json"
    monkeypatch.setattr(auth, "WEB_SESSIONS", str(path))
    future = (auth.now() + auth.dt.timedelta(days=1)).isoformat()
    data = {auth._key("revoked"): {"expires": future}, auth._key("kept"): {"expires": future}}
    auth._atomic(str(path), data)
    assert auth.check("revoked") and auth.check("kept")
    return path, data


@pytest.mark.parametrize("operation", ["revocar", "logout", "write"])
def test_successful_write_with_same_mtime_revokes_access(sessions_file, monkeypatch, operation):
    path, data = sessions_file
    stamp = path.stat().st_mtime_ns
    original = auth._atomic

    def write_same_stamp(destination, value):
        original(destination, value)
        os.utime(destination, ns=(stamp, stamp))

    monkeypatch.setattr(auth, "_atomic", write_same_stamp)
    if operation == "revocar":
        assert auth.revocar(auth._key("revoked")[:16])
    elif operation == "logout":
        auth.logout("revoked")
    else:
        auth._atomic(str(path), {auth._key("kept"): data[auth._key("kept")]})
    assert auth._key("revoked") not in json.loads(path.read_text())
    assert path.stat().st_mtime_ns == stamp
    assert not auth.check("revoked") and auth.check("kept")


@pytest.mark.parametrize("operation", ["replace", "inplace"])
def test_external_change_with_same_mtime_and_size_is_observed(sessions_file, operation):
    path, data = sessions_file
    previous = path.stat()
    # Cambiar una clave por otra de igual longitud mantiene el tamaño y el timestamp.
    data[auth._key("new-token")] = data.pop(auth._key("revoked"))
    raw = json.dumps(data, indent=1)
    if operation == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_text(raw, encoding="utf-8")
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        os.replace(replacement, path)
    else:
        path.write_text(raw, encoding="utf-8")
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns == previous.st_mtime_ns
    assert not auth.check("revoked")
    assert auth.check("new-token") and auth.check("kept")


@pytest.mark.parametrize("content", [None, "{invalid", "[]", "null", '"text"'])
def test_missing_or_invalid_file_never_keeps_authenticated_access(sessions_file, content):
    path, _ = sessions_file
    if content is None:
        path.unlink()
    else:
        stamp = path.stat().st_mtime_ns
        path.write_text(content, encoding="utf-8")
        os.utime(path, ns=(stamp, stamp))
    assert auth.check("revoked") is False


@pytest.mark.parametrize("operation", ["revocar", "logout"])
def test_failed_write_does_not_report_revocation(sessions_file, monkeypatch, operation):
    def cannot_write(*args):
        raise OSError("fixture disk unavailable")

    monkeypatch.setattr(auth, "atomic_write", cannot_write)
    with pytest.raises(OSError, match="fixture disk unavailable"):
        if operation == "revocar":
            auth.revocar(auth._key("revoked")[:16])
        else:
            auth.logout("revoked")
    assert auth.check("revoked") is True


def test_expired_session_is_denied(sessions_file):
    path, data = sessions_file
    data[auth._key("revoked")]["expires"] = (auth.now() - auth.dt.timedelta(seconds=1)).isoformat()
    auth._atomic(str(path), data)
    assert not auth.check("revoked") and auth.check("kept")


@pytest.mark.parametrize("entry", [None, [], "invalid", {"expires": None}, {"expires": 123}, {"expires": "invalid"}])
def test_invalid_token_entry_is_denied(sessions_file, entry):
    path, data = sessions_file
    data[auth._key("revoked")] = entry
    auth._atomic(str(path), data)
    assert not auth.check("revoked") and auth.check("kept")


def test_successful_login_is_visible_with_same_mtime(sessions_file, tmp_path, monkeypatch):
    path, _ = sessions_file
    monkeypatch.setattr(auth, "LIENZO", str(tmp_path))
    monkeypatch.setattr(auth, "AUTH_FILE", str(tmp_path / "auth.json"))
    account = auth.setup(mode="code")
    stamp = path.stat().st_mtime_ns
    original = auth._atomic

    def write_same_stamp(destination, value):
        original(destination, value)
        if destination == str(path):
            os.utime(destination, ns=(stamp, stamp))

    monkeypatch.setattr(auth, "_atomic", write_same_stamp)
    ok, reason, token = auth.login("", auth.totp(account["totp_secret"]), "fixture-ip")
    assert ok and reason == "ok" and token
    assert path.stat().st_mtime_ns == stamp
    assert auth.check(token) and auth.check("kept")
