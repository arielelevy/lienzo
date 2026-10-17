import claude_pipe_adapter as adapter
import pytest


@pytest.mark.parametrize(
    "error", [ValueError("bootstrap_server_recycled"), TimeoutError(), ValueError("bootstrap_server_identity_mismatch")]
)
def test_bootstrap_stale_reports_recovery_without_secrets(monkeypatch, capsys, error):
    monkeypatch.setattr(adapter.sys, "argv", ["adapter", "--bootstrap"])

    def fail():
        raise error

    monkeypatch.setattr(adapter, "main", fail)
    assert adapter.cli() == 2
    output = capsys.readouterr().err
    assert "bootstrap vencido o servidor reiniciado" in output
    assert "Conectar esta sesión Claude" in output
    assert "esa conversación de Claude" in output


@pytest.mark.parametrize("mode", ["--bootstrap", "--serve", "--hook"])
def test_diagnostics_never_print_exception_secrets(monkeypatch, capsys, mode):
    monkeypatch.setattr(adapter.sys, "argv", ["adapter", mode])

    def fail():
        raise OSError("PRIVATE_TOKEN_DO_NOT_PRINT")

    monkeypatch.setattr(adapter, "main", fail)
    assert adapter.cli() == 2
    output = capsys.readouterr().err
    assert "PRIVATE_TOKEN_DO_NOT_PRINT" not in output
    assert "claude_pipe_adapter_failed" in output


def test_success_remains_zero(monkeypatch, capsys):
    monkeypatch.setattr(adapter, "main", lambda: None)
    assert adapter.cli() == 0
    assert capsys.readouterr().err == ""


def test_missing_pipe_reports_expiration(monkeypatch, capsys):
    monkeypatch.setattr(adapter.sys, "argv", ["adapter", "--bootstrap"])
    error = OSError("PRIVATE_PIPE_PATH")
    error.winerror = 2

    def fail():
        raise error

    monkeypatch.setattr(adapter, "main", fail)
    assert adapter.cli() == 2
    output = capsys.readouterr().err
    assert "bootstrap vencido" in output
    assert "PRIVATE_PIPE_PATH" not in output
