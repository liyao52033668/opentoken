import json

from typer.testing import CliRunner

from opentoken.cli.app import app


def test_onboard_creates_default_config_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    config_path = tmp_path / ".opentoken" / "config.json"
    assert config_path.exists()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["api_key"]

