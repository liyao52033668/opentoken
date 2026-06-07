"""网关配置管理。

优先从环境变量读取配置，存储使用 StorageBackend。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)
_ENV_API_KEY = "OPENTOKEN_API_KEY"


def default_app_config() -> dict[str, object]:
    """生成默认网关配置。"""
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


def load_or_create_app_config(state_dir: Path) -> dict[str, object]:
    """加载或创建网关配置。

    配置存储使用 StorageBackend（支持本地文件系统或 S3）。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）

    Returns:
        网关配置字典
    """
    from opentoken.storage.config_store import read_config, write_config

    # 读取配置
    config = read_config()

    if config is not None:
        # 配置文件存在，验证格式
        if not isinstance(config, dict):
            raise RuntimeError(
                "Configuration file is not a JSON object."
            )
        # 环境变量优先：运行时覆盖配置文件中的值
        env_key = os.getenv(_ENV_API_KEY)
        if env_key:
            config["api_key"] = env_key
        return config

    # 配置不存在，创建默认配置
    payload = default_app_config()
    write_config(payload)
    return payload
