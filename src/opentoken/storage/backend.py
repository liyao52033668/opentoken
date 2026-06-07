"""抽象存储后端接口。

支持可插拔的存储后端（本地文件系统、S3 兼容对象存储等）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class StorageBackend(ABC):
    """存储后端抽象接口。

    所有存储后端必须实现此接口，提供统一的读写操作。
    """

    @abstractmethod
    def read_json(self, key: str) -> dict | None:
        """读取 JSON 数据。

        Args:
            key: 存储键（如 "files.json" 或 "uploads.json"）

        Returns:
            解析后的字典，不存在或解析失败返回 None
        """
        ...

    @abstractmethod
    def write_json(self, key: str, data: dict) -> None:
        """写入 JSON 数据。

        Args:
            key: 存储键
            data: 要写入的字典数据
        """
        ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes | None:
        """读取二进制数据。

        Args:
            key: 存储键（如 "files/file-xxx.bin"）

        Returns:
            二进制数据，不存在返回 None
        """
        ...

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> None:
        """写入二进制数据。

        Args:
            key: 存储键
            data: 要写入的二进制数据
        """
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """删除数据。

        Args:
            key: 存储键

        Returns:
            是否成功删除
        """
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查数据是否存在。

        Args:
            key: 存储键

        Returns:
            是否存在
        """
        ...

    @abstractmethod
    @contextmanager
    def acquire_lock(self, key: str) -> Iterator[None]:
        """获取锁。

        Args:
            key: 要锁定的键（通常是对应的 JSON 文件键）

        Yields:
            锁定上下文
        """
        ...
