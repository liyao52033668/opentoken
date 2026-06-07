import json
import logging
import os
import secrets
from pathlib import Path

from opentoken.storage._atomic import write_json_atomic

logger = logging.getLogger(__name__)
_ENV_API_KEY = "OPENTOKEN_API_KEY"


def default_app_config() -> dict[str, object]:
    env_key = os.getenv(_ENV_API_KEY)
    if env_key:
        api_key = env_key
    else:
        api_key = secrets.token_hex(16)
        logger.warning("首次生成 API key，请妥善保存：%s", api_key)
    return {
        "api_key": api_key,
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
            # 环境变量优先：运行时覆盖配置文件中的值
            env_key = os.getenv(_ENV_API_KEY)
            if env_key:
                parsed["api_key"] = env_key
            return parsed
        raise RuntimeError(
            f"Configuration file {config_path} is not a JSON object."
        )
    payload = default_app_config()
    # config.json holds the local gateway API key — write atomically and
    # owner-only (0600) so it isn't briefly world-readable on a shared host.
    write_json_atomic(config_path, payload, sensitive=True)
    return payload

