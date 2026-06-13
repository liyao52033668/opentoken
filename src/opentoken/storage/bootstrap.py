"""存储初始化。

使用 StorageBackend 统一管理存储后端。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from opentoken.config.app_config import load_or_create_app_config
from opentoken.storage.config_store import ensure_directories

logger = logging.getLogger(__name__)


def initialize_state_dir(state_dir: Path) -> Path:
    """初始化状态目录。

    根据存储后端类型（本地文件系统或 S3）执行相应的初始化：
    - 本地文件系统：创建目录并设置权限（0700）
    - S3：无需创建目录

    Args:
        state_dir: 状态目录

    Returns:
        状态目录路径
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass

    # 确保存储后端目录结构存在
    ensure_directories()

    # 加载或创建网关配置
    load_or_create_app_config(state_dir / "config.json")

    logger.info(f"Initialized storage: {state_dir}")
    return state_dir
