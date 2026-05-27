import pytest
from typer.testing import CliRunner

import opentoken.cli.app as cli_app_module
from opentoken.cli.app import _is_loopback_host, app


def test_start_invokes_uvicorn_with_configured_bind(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    captured: dict[str, object] = {}

    def fake_run(app_ref: str, *, factory: bool, host: str, port: int) -> None:
        captured["app_ref"] = app_ref
        captured["factory"] = factory
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(cli_app_module.uvicorn, "run", fake_run)
    runner = CliRunner()

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    assert captured["app_ref"] == "opentoken.api.app:create_app"
    assert captured["factory"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 32117
    assert (tmp_path / ".opentoken" / "config.json").exists()


@pytest.mark.parametrize(
    "host,loopback",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
    ],
)
def test_is_loopback_host(host: str, loopback: bool) -> None:
    assert _is_loopback_host(host) is loopback


def test_start_warns_when_binding_non_loopback(monkeypatch, tmp_path) -> None:
    """Binding a public interface must print a stderr warning (provider sessions
    would otherwise be silently exposed beyond this machine)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli_app_module.uvicorn, "run", lambda *a, **k: None)
    runner = CliRunner()

    result = runner.invoke(app, ["start", "--host", "0.0.0.0"])

    assert result.exit_code == 0
    # CliRunner's `output` mixes stdout+stderr by default in this click version;
    # the warning text is enough — it ends up in the captured combined buffer.
    assert "exposes OpenToken" in result.output
