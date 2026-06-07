"""S3 兼容对象存储后端。"""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from opentoken.storage.backend import StorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# 全局锁表：用于单实例场景的内存锁
# 注意：多实例部署时需要使用分布式锁（如 DynamoDB Lock Client）
_LOCK_TABLE: dict[str, threading.Lock] = {}
_LOCK_TABLE_MUTEX = threading.Lock()


class S3Storage(StorageBackend):
    """S3 兼容对象存储后端。

    支持所有兼容 S3 API 的对象存储：
    - AWS S3
    - MinIO
    - 阿里云 OSS（S3 兼容模式）
    - 腾讯云 COS（S3 兼容模式）
    - Cloudflare R2

    环境变量配置：
    - OPENTOKEN_S3_ENDPOINT: S3 端点 URL（可选，默认 AWS S3）
    - OPENTOKEN_S3_REGION: 区域（默认 us-east-1）
    - OPENTOKEN_S3_BUCKET: 存储桶名称
    - OPENTOKEN_S3_ACCESS_KEY: Access Key ID
    - OPENTOKEN_S3_SECRET_KEY: Secret Access Key
    - OPENTOKEN_S3_PREFIX: 键前缀（可选，用于在桶内分区）
    - OPENTOKEN_S3_SIGNATURE_VERSION: 签名版本（默认 s3v4）
    - OPENTOKEN_S3_ADDRESSING_STYLE: 寻址样式（virtual/path/auto，默认 virtual）
    - OPENTOKEN_S3_PAYLOAD_SIGNING: 是否启用内容签名（true/false，默认 false）
    """

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        bucket_name: str,
        access_key: str,
        secret_key: str,
        prefix: str = "",
        signature_version: str = "s3v4",
        addressing_style: str = "virtual",
        payload_signing: bool = False,
    ) -> None:
        """初始化 S3 存储后端。

        Args:
            endpoint_url: S3 端点 URL（None 表示 AWS S3）
            region_name: 区域名称
            bucket_name: 存储桶名称
            access_key: Access Key ID
            secret_key: Secret Access Key
            prefix: 键前缀
            signature_version: 签名版本（s3v4/s3）
            addressing_style: 寻址样式（virtual/path/auto）
            payload_signing: 是否启用内容 SHA256 签名
        """
        self._endpoint_url = endpoint_url
        self._region_name = region_name
        self._bucket_name = bucket_name
        self._prefix = prefix.rstrip("/") if prefix else ""
        self._signature_version = signature_version
        self._addressing_style = addressing_style
        self._payload_signing = payload_signing
        self._client = self._create_client(access_key, secret_key)

    def _create_client(self, access_key: str, secret_key: str):
        """创建 boto3 S3 客户端。"""
        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:
            raise ImportError(
                "boto3 is required for S3 storage. "
                "Install it with: pip install boto3"
            ) from e

        config = Config(
            # 连接超时和读取超时配置
            connect_timeout=5,
            read_timeout=30,
            # 重试配置
            retries={"max_attempts": 3, "mode": "standard"},
            # S3 签名版本配置 - 使用 v4 签名以兼容更多 S3 兼容服务
            signature_version=self._signature_version,
            # S3 特定配置
            s3={
                # 寻址样式 - 兼容 Cloudflare R2、MinIO 等服务
                "addressing_style": self._addressing_style,
                # 内容 SHA256 签名 - 禁用可解决 XAmzContentSHA256Mismatch 错误
                # 某些代理或负载均衡器可能会修改请求体导致哈希不匹配
                "payload_signing_enabled": self._payload_signing,
            },
        )

        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )

    def _resolve_key(self, key: str) -> str:
        """将存储键解析为 S3 对象键。"""
        # 安全校验：禁止路径遍历
        if ".." in key or key.startswith("/") or "\\" in key:
            raise ValueError(f"Invalid storage key: {key!r}")
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def read_json(self, key: str) -> dict | None:
        s3_key = self._resolve_key(key)
        try:
            response = self._client.get_object(
                Bucket=self._bucket_name, Key=s3_key
            )
            payload = json.loads(response["Body"].read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
        except self._client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.warning(f"Failed to read JSON from S3: {key}, error: {e}")
        return None

    def write_json(self, key: str, data: dict) -> None:
        s3_key = self._resolve_key(key)
        try:
            self._client.put_object(
                Bucket=self._bucket_name,
                Key=s3_key,
                Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as e:
            logger.error(f"Failed to write JSON to S3: {key}, error: {e}")
            raise

    def read_bytes(self, key: str) -> bytes | None:
        s3_key = self._resolve_key(key)
        try:
            response = self._client.get_object(
                Bucket=self._bucket_name, Key=s3_key
            )
            return response["Body"].read()
        except self._client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.warning(f"Failed to read bytes from S3: {key}, error: {e}")
            return None

    def write_bytes(self, key: str, data: bytes) -> None:
        s3_key = self._resolve_key(key)
        try:
            self._client.put_object(
                Bucket=self._bucket_name,
                Key=s3_key,
                Body=data,
                ContentType="application/octet-stream",
            )
        except Exception as e:
            logger.error(f"Failed to write bytes to S3: {key}, error: {e}")
            raise

    def delete(self, key: str) -> bool:
        s3_key = self._resolve_key(key)
        try:
            self._client.delete_object(
                Bucket=self._bucket_name, Key=s3_key
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to delete from S3: {key}, error: {e}")
            return False

    def exists(self, key: str) -> bool:
        s3_key = self._resolve_key(key)
        try:
            self._client.head_object(
                Bucket=self._bucket_name, Key=s3_key
            )
            return True
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception:
            return False

    @contextmanager
    def acquire_lock(self, key: str) -> Iterator[None]:
        """获取内存锁。

        注意：此锁仅在单进程内有效。多实例部署时需要实现分布式锁。

        对于 S3 场景，推荐：
        1. 单实例：当前内存锁足够
        2. 多实例：使用 DynamoDB Lock Client 或 Redis 分布式锁
        3. 乐观锁：使用 S3 对象版本控制
        """
        lock_key = f"{self._bucket_name}:{self._resolve_key(key)}"
        with _LOCK_TABLE_MUTEX:
            lock = _LOCK_TABLE.setdefault(lock_key, threading.Lock())

        with lock:
            yield

    @classmethod
    def from_env(cls) -> "S3Storage":
        """从环境变量创建 S3 存储后端。"""
        endpoint_url = os.getenv("OPENTOKEN_S3_ENDPOINT")
        region_name = os.getenv("OPENTOKEN_S3_REGION", "us-east-1")
        bucket_name = os.getenv("OPENTOKEN_S3_BUCKET", "")
        access_key = os.getenv("OPENTOKEN_S3_ACCESS_KEY", "")
        secret_key = os.getenv("OPENTOKEN_S3_SECRET_KEY", "")
        prefix = os.getenv("OPENTOKEN_S3_PREFIX", "")
        signature_version = os.getenv("OPENTOKEN_S3_SIGNATURE_VERSION", "s3v4")
        addressing_style = os.getenv("OPENTOKEN_S3_ADDRESSING_STYLE", "virtual")
        payload_signing = os.getenv("OPENTOKEN_S3_PAYLOAD_SIGNING", "false").lower() == "true"

        if not bucket_name:
            raise ValueError("OPENTOKEN_S3_BUCKET is required for S3 storage")
        if not access_key:
            raise ValueError("OPENTOKEN_S3_ACCESS_KEY is required for S3 storage")
        if not secret_key:
            raise ValueError("OPENTOKEN_S3_SECRET_KEY is required for S3 storage")

        return cls(
            endpoint_url=endpoint_url,
            region_name=region_name,
            bucket_name=bucket_name,
            access_key=access_key,
            secret_key=secret_key,
            prefix=prefix,
            signature_version=signature_version,
            addressing_style=addressing_style,
            payload_signing=payload_signing,
        )
