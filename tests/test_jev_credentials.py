import os

import jev_credentials as credentials
import pytest
import state


def test_credential_roundtrip_and_private_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    assert not credentials.available()
    key = "synthetic-test-credential-123"
    credentials.store(key)
    assert credentials.available() and credentials.load() == key
    if os.name == "nt":
        assert key.encode() not in credentials.path().read_bytes()
    else:
        assert credentials.path().stat().st_mode & 0o077 == 0
        os.chmod(credentials.path(), 0o644)
        with pytest.raises(ValueError, match="0600"):
            credentials.load()


def test_missing_and_bad_credentials_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LIENZO", str(tmp_path))
    with pytest.raises(ValueError, match="no tiene credencial"):
        credentials.load()
    for key in ("", "a\nb", "with space"):
        with pytest.raises(ValueError):
            credentials.store(key)
    assert not credentials.available()
