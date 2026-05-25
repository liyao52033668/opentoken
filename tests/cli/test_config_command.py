from typer.testing import CliRunner
import json

from opentoken.cli.app import app


def test_config_dry_run_prints_algae_provider_patch(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["onboard"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["config", "--dry-run"])

    assert result.exit_code == 0
    algae_config = json.loads((tmp_path / ".opentoken" / "config.json").read_text(encoding="utf-8"))
    assert '"algae"' in result.stdout
    assert algae_config["api_key"] in result.stdout


def test_config_apply_updates_opentoken_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    opentoken_config = tmp_path / ".opentoken" / "opentoken.json"
    opentoken_config.parent.mkdir(parents=True, exist_ok=True)
    opentoken_config.write_text(
        json.dumps(
            {
                "channels": {"default": "stable"},
                "models": {"providers": {}},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    algae_config = json.loads((tmp_path / ".opentoken" / "config.json").read_text(encoding="utf-8"))
    payload = json.loads(opentoken_config.read_text(encoding="utf-8"))
    assert payload["channels"]["default"] == "stable"
    assert "algae" in payload["models"]["providers"]
    assert payload["models"]["providers"]["algae"]["apiKey"] == algae_config["api_key"]
    assert list(opentoken_config.parent.glob("opentoken.json.*.bak"))
