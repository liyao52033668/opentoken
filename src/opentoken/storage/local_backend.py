"""本地文件系统存储后端。"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from opentoken.storage._atomic import file_lock, write_json_atomic

if TYPE_CHECKING:
    from collections.abc import Iterator


_SENSITIVE_JSON_KEYS = {
    "auth-profiles.json",
    "provider-sessions.json",
    "responses.json",
}


class LocalStorage:
    """本地文件系统存储后端。

    将数据存储在本地文件系统中：
    - JSON 元数据：直接存储为 .json 文件
    - 二进制数据：存储为 .bin 文件
    """

    def __init__(self, base_dir: Path) -> None:
        """初始化本地存储后端。

        Args:
            base_dir: 存储根目录
        """
        self._base_dir = base_dir

    def _resolve_path(self, key: str) -> Path:
        """将存储键解析为文件系统路径。"""
        # 安全校验：禁止路径遍历
        if ".." in key or key.startswith("/") or "\\" in key:
            raise ValueError(f"Invalid storage key: {key!r}")
        return self._base_dir / key

    def read_json(self, key: str) -> dict | None:
        path = self._resolve_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def write_json(self, key: str, data: dict) -> None:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            path,
            data,
            sensitive=key in _SENSITIVE_JSON_KEYS or key.startswith("providers/"),
        )

    def read_bytes(self, key: str) -> bytes | None:
        path = self._resolve_path(key)
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def write_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写入：先写临时文件，再 rename
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_bytes(data)
        # 设置权限为 0600（仅所有者可读写）
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)

    def delete(self, key: str) -> bool:
        path = self._resolve_path(key)
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def exists(self, key: str) -> bool:
        path = self._resolve_path(key)
        return path.exists()

    @contextmanager
    def acquire_lock(self, key: str) -> Iterator[None]:
        """使用文件锁锁定指定的键。"""
        path = self._resolve_path(key)
        with file_lock(path):
            yield
