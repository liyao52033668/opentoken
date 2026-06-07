"""统一配置存储（基于 StorageBackend）。

提供统一的 JSON 存储接口，支持本地文件系统和 S3 兼容对象存储。
所有配置、凭证、会话数据都通过此模块存储。
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentoken.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

# 配置存储键（与原 state_dir 结构对应）
_CONFIG_KEY = "config.json"
_OPENTOKEN_KEY = "opentoken.json"
_AUTH_PROFILES_KEY = "auth-profiles.json"
_PROVIDER_SESSIONS_KEY = "provider-sessions.json"
_RESPONSES_KEY = "responses.json"
_MODEL_CACHE_KEY = "model-catalog-cache.json"


def _config_backend() -> "StorageBackend":
    """获取配置存储后端。"""
    from opentoken.storage.factory import get_storage_backend

    return get_storage_backend()


# ============================================================
# 通用 JSON 存储操作
# ============================================================


def read_json(key: str, default: dict | None = None) -> dict | None:
    """读取 JSON 数据。"""
    backend = _config_backend()
    data = backend.read_json(key)
    if data is None:
        return copy.deepcopy(default) if default is not None else None
    return data


def write_json(key: str, data: dict, sensitive: bool = False) -> None:
    """写入 JSON 数据。

    Args:
        key: 存储键
        data: 要写入的数据
        sensitive: 是否标记为敏感（s3_backend 会在日志中提示）
    """
    backend = _config_backend()
    backend.write_json(key, data)
    logger.debug(f"Wrote config: {key}")


# ============================================================
# 配置存储函数
# ============================================================


def read_config() -> dict | None:
    """读取网关配置。"""
    return read_json(_CONFIG_KEY)


def write_config(data: dict) -> None:
    """写入网关配置。"""
    write_json(_CONFIG_KEY, data)


def read_opentoken_config() -> dict | None:
    """读取用户配置。"""
    return read_json(_OPENTOKEN_KEY)


def write_opentoken_config(data: dict) -> None:
    """写入用户配置。"""
    write_json(_OPENTOKEN_KEY, data)


def read_auth_profiles() -> dict | None:
    """读取认证 profiles。"""
    return read_json(
        _AUTH_PROFILES_KEY,
        default={"version": 1, "profiles": {}, "order": {}, "lastGood": {}, "usageStats": {}},
    )


def write_auth_profiles(data: dict) -> None:
    """写入认证 profiles。"""
    write_json(_AUTH_PROFILES_KEY, data, sensitive=True)


def read_provider_sessions() -> dict | None:
    """读取 provider 会话。"""
    return read_json(_PROVIDER_SESSIONS_KEY, default={})


def write_provider_sessions(data: dict) -> None:
    """写入 provider 会话。"""
    write_json(_PROVIDER_SESSIONS_KEY, data, sensitive=True)


def read_responses() -> dict | None:
    """读取响应历史。"""
    return read_json(
        _RESPONSES_KEY, default={"version": 1, "responses": {}}
    )


def write_responses(data: dict) -> None:
    """写入响应历史。"""
    write_json(_RESPONSES_KEY, data, sensitive=True)


def read_model_cache() -> dict | None:
    """读取模型发现缓存。"""
    return read_json(_MODEL_CACHE_KEY)


def write_model_cache(data: dict) -> None:
    """写入模型发现缓存。"""
    write_json(_MODEL_CACHE_KEY, data)


# ============================================================
# Provider 凭证存储
# ============================================================


def read_provider_credential(provider: str) -> dict | None:
    """读取单个 provider 凭证。"""
    key = f"providers/{provider}.json"
    return read_json(key)


def write_provider_credential(provider: str, data: dict) -> None:
    """写入单个 provider 凭证。"""
    key = f"providers/{provider}.json"
    write_json(key, data, sensitive=True)


def list_provider_credentials() -> list[tuple[str, dict]]:
    """列出所有 provider 凭证。

    注意：由于 S3 不支持目录列表，此函数需要额外实现。
    对于 S3 后端，需要在元数据中维护 provider 列表。
    """
    backend = _config_backend()
    store = read_auth_profiles()
    profiles = store.get("profiles", {}) if store else {}

    result = []
    # 从 auth-profiles 中提取 provider 凭证
    for profile_id, raw in profiles.items():
        if isinstance(raw, dict) and "token" in raw:
            try:
                record = json.loads(raw["token"])
                if isinstance(record, dict):
                    result.append((record.get("provider", ""), record))
            except (json.JSONDecodeError, TypeError):
                pass

    # 尝试直接读取各 provider 文件
    # 注意：对于 S3 后端，这个方法可能无法找到所有 provider
    # 推荐使用 auth-profiles 作为主索引
    return result


def delete_provider_credential(provider: str) -> bool:
    """删除单个 provider 凭证。"""
    key = f"providers/{provider}.json"
    backend = _config_backend()
    return backend.delete(key)


# ============================================================
# 初始化（创建必要目录结构）
# ============================================================


def ensure_directories() -> None:
    """确保存储目录结构存在。

    对于 S3 后端，不需要创建目录（对象存储无目录概念）。
    对于本地后端，确保子目录存在。
    """
    backend = _config_backend()
    from opentoken.storage.local_backend import LocalStorage

    if isinstance(backend, LocalStorage):
        # 本地存储需要创建目录
        import os

        base_dir = backend._base_dir
        for name in ("providers", "browser", "logs", "opentoken", "files", "uploads"):
            subdir = base_dir / name
            subdir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(subdir, 0o700)
            except OSError:
                pass
        logger.info(f"Initialized local storage directories: {base_dir}")
    else:
        # S3 后端：目录结构由键前缀管理，无需额外初始化
        logger.info("Using cloud storage (no local directory initialization needed)")
