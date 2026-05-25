import os
from pathlib import Path


def resolve_state_dir() -> Path:
    return Path.home() / ".opentoken"


def resolve_app_config_path() -> Path:
    return resolve_state_dir() / "config.json"


def resolve_providers_dir() -> Path:
    return resolve_state_dir() / "providers"


def resolve_opentoken_state_dir() -> Path:
    override = os.getenv("OPENTOKEN_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".opentoken"


def resolve_opentoken_config_path() -> Path:
    override = os.getenv("OPENTOKEN_CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return resolve_opentoken_state_dir() / "opentoken.json"
