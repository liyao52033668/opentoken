import json
import secrets
from pathlib import Path

from opentoken.storage._atomic import write_json_atomic


def default_app_config() -> dict[str, object]:
    return {
        "api_key": secrets.token_hex(16),
        "host": "127.0.0.1",
        "port": 32117,
    }


def load_or_create_app_config(config_path: Path) -> dict[str, object]:
    if config_path.exists():
        try:
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt/truncated config used to crash every CLI entry point
            # (start, status, config, doctor) with a raw JSONDecodeError stack
            # trace and no recovery hint. Surface a clear actionable error
            # instead. Don't silently regenerate — that would lose the user's
            # API key and break clients holding the old one.
            raise RuntimeError(
                f"Configuration file is unreadable: {config_path}. "
                f"Repair or remove it and restart. ({exc.__class__.__name__}: {exc})"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
        raise RuntimeError(
            f"Configuration file {config_path} is not a JSON object."
        )
    payload = default_app_config()
    # config.json holds the local gateway API key — write atomically and
    # owner-only (0600) so it isn't briefly world-readable on a shared host.
    write_json_atomic(config_path, payload, sensitive=True)
    return payload

