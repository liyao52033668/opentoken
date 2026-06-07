"""网关配置管理。

优先从环境变量读取配置，存储使用 StorageBackend。

支持的环境变量：
- OPENTOKEN_API_KEY: API 密钥
- OPENTOKEN_HOST: 绑定地址（默认自动检测）
- OPENTOKEN_PORT: 绑定端口（默认 32117）
- PORT: 容器环境端口（自动检测，优先级低于 OPENTOKEN_PORT）
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)
_ENV_API_KEY = "OPENTOKEN_API_KEY"
_ENV_HOST = "OPENTOKEN_HOST"
_ENV_PORT = "OPENTOKEN_PORT"


def _detect_container_env() -> bool:
    """检测是否在容器环境中运行。

    Returns:
        True 如果在容器环境中，否则 False
    """
    # 检查常见的容器/云平台环境变量
    container_env_vars = [
        "KUBERNETES_SERVICE_HOST",
        "KUBERNETES_PORT",
        "DOCKER_HOST",
        "CONTAINER_NAME",
        "HOSTNAME",  # 在容器中通常是容器 ID
        "CF_PAGES",  # Cloudflare Pages
        "RENDER",  # Render
        "VERCEL",  # Vercel
        "NETLIFY",  # Netlify
        "HEROKU",  # Heroku
    ]
    for var in container_env_vars:
        if os.getenv(var):
            return True

    # 检查文件系统特征
    container_files = [
        "/.dockerenv",
        "/run/secrets/kubernetes.io/serviceaccount",
    ]
    for path in container_files:
        if os.path.exists(path):
            return True

    return False


def _get_default_host() -> str:
    """获取默认绑定地址。

    在容器环境中自动绑定到 0.0.0.0，否则绑定到 127.0.0.1。

    Returns:
        默认绑定地址
    """
    # 优先使用环境变量
    env_host = os.getenv(_ENV_HOST)
    if env_host:
        return env_host

    # 容器环境中绑定到所有接口
    if _detect_container_env():
        logger.info("Detected container environment, binding to 0.0.0.0")
        return "0.0.0.0"

    # 默认绑定到 localhost
    return "127.0.0.1"


def _get_default_port() -> int:
    """获取默认绑定端口。

    优先级：OPENTOKEN_PORT > PORT > 32117

    Returns:
        默认绑定端口
    """
    # 优先使用 OPENTOKEN_PORT
    env_port = os.getenv(_ENV_PORT)
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            logger.warning(f"Invalid OPENTOKEN_PORT value: {env_port}, using default")

    # 其次使用 PORT（容器环境常用）
    container_port = os.getenv("PORT")
    if container_port:
        try:
            return int(container_port)
        except ValueError:
            logger.warning(f"Invalid PORT value: {container_port}, using default")

    # 默认端口
    return 32117


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
        "host": _get_default_host(),
        "port": _get_default_port(),
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

        # 更新 host（环境变量优先）
        env_host = os.getenv(_ENV_HOST)
        if env_host:
            config["host"] = env_host

        # 更新 port（环境变量优先）
        env_port = os.getenv(_ENV_PORT)
        if env_port:
            try:
                config["port"] = int(env_port)
            except ValueError:
                logger.warning(f"Invalid OPENTOKEN_PORT value: {env_port}, keeping config value")

        # 容器环境中检查 PORT 变量
        if "PORT" in os.environ and _ENV_PORT not in os.environ:
            try:
                config["port"] = int(os.getenv("PORT"))
            except ValueError:
                pass

        return config

    # 配置不存在，创建默认配置
    payload = default_app_config()
    write_config(payload)
    return payload
