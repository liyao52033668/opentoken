"""存储后端工厂。

通过环境变量配置选择存储后端：
- OPENTOKEN_STORAGE_BACKEND: "local" 或 "s3"（默认 "local"）
- S3 配置见 s3_backend.py
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from opentoken.storage.backend import StorageBackend
from opentoken.storage.local_backend import LocalStorage

logger = logging.getLogger(__name__)

# 全局存储后端实例（延迟初始化）
_BACKEND: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """获取存储后端实例（单例）。

    通过 OPENTOKEN_STORAGE_BACKEND 环境变量选择后端：
    - "local"（默认）：本地文件系统
    - "s3"：S3 兼容对象存储

    Returns:
        StorageBackend 实例
    """
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    backend_type = os.getenv("OPENTOKEN_STORAGE_BACKEND", "local").lower()

    if backend_type == "s3":
        from opentoken.storage.s3_backend import S3Storage

        try:
            _BACKEND = S3Storage.from_env()
            logger.info("Using S3 storage backend")
        except Exception as e:
            logger.error(f"Failed to initialize S3 storage: {e}")
            raise
    elif backend_type == "local":
        from opentoken.config.paths import resolve_state_dir

        state_dir = resolve_state_dir()
        _BACKEND = LocalStorage(state_dir)
        logger.info(f"Using local storage backend: {state_dir}")
    else:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            "Supported: 'local', 's3'"
        )

    return _BACKEND


def reset_storage_backend() -> None:
    """重置存储后端实例（用于测试）。"""
    global _BACKEND
    _BACKEND = None
