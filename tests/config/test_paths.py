from pathlib import Path

from opentoken.config.paths import resolve_opentoken_config_path, resolve_state_dir


def test_resolve_state_dir_defaults_to_user_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_state_dir() == tmp_path / ".opentoken"


def test_resolve_opentoken_config_path_defaults_to_opentoken_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_opentoken_config_path() == tmp_path / ".opentoken" / "opentoken.json"


def test_resolve_opentoken_config_path_prefers_config_env_override(
    monkeypatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom" / "opentoken.json"
    monkeypatch.setenv("OPENTOKEN_CONFIG_PATH", str(override))

    assert resolve_opentoken_config_path() == override


def test_resolve_opentoken_config_path_uses_state_dir_override(
    monkeypatch, tmp_path: Path
) -> None:
    override = tmp_path / "state-dir"
    monkeypatch.setenv("OPENTOKEN_STATE_DIR", str(override))

    assert resolve_opentoken_config_path() == override / "opentoken.json"
