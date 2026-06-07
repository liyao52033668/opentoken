"""Provider 凭证存储（使用 StorageBackend）。

支持本地文件系统或 S3 兼容对象存储。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.storage.config_store import (
    delete_provider_credential,
    list_provider_credentials as _list_provider_credentials_from_config,
    read_provider_credential,
    write_provider_credential,
)
from opentoken.storage.auth_profiles import (
    delete_auth_profile_record,
    list_auth_profile_records,
    load_auth_profile_record,
    save_auth_profile_record,
)


def save_provider_credentials(
    state_dir: Path,
    record: ProviderCredentialRecord,
    *,
    validator: Callable[[ProviderCredentialRecord], bool] | None = None,
) -> Path | None:
    """持久化 provider 凭证。

    如果提供了 `validator`，必须返回 True 才会覆盖现有凭证。
    这用于浏览器采集后的 dry-run-before-overwrite 校验。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        record: ProviderCredentialRecord
        validator: 可选的验证器

    Returns:
        保存路径或 None（验证失败时）
    """
    if validator is not None:
        try:
            ok = bool(validator(record))
        except Exception:
            ok = False
        if not ok:
            return None

    # 保存到 auth-profiles（主要存储位置，支持 S3）
    save_auth_profile_record(state_dir, record)

    # 同时保存到单独的 provider 文件（用于向后兼容）
    provider_data = record.model_dump()
    write_provider_credential(record.provider, provider_data)

    return Path(f"providers/{record.provider}.json")


def load_provider_credentials(state_dir: Path, provider: str) -> ProviderCredentialRecord | None:
    """加载 provider 凭证。

    先尝试从 auth-profiles 加载，再尝试从单独的 provider 文件加载。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        provider: provider 名称

    Returns:
        ProviderCredentialRecord 或 None
    """
    # 优先从 auth-profiles 加载
    auth_record = load_auth_profile_record(state_dir, provider)
    if auth_record is not None:
        return auth_record

    # 回退到单独的 provider 文件
    provider_data = read_provider_credential(provider)
    if provider_data is None:
        return None

    return _load_record_from_dict(provider_data)


def list_provider_credentials(state_dir: Path) -> list[ProviderCredentialRecord]:
    """列出所有 provider 凭证。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）

    Returns:
        ProviderCredentialRecord 列表
    """
    # 从 auth-profiles 获取凭证
    records_by_provider = {
        record.provider: record for record in list_auth_profile_records(state_dir)
    }

    # 补充从单独的 provider 文件读取的凭证
    for _, provider_data in _list_provider_credentials_from_config():
        if not isinstance(provider_data, dict):
            continue
        record = _load_record_from_dict(provider_data)
        if record is not None and record.provider not in records_by_provider:
            records_by_provider[record.provider] = record

    return [records_by_provider[key] for key in sorted(records_by_provider)]


def delete_provider_credentials(state_dir: Path, provider: str) -> bool:
    """删除 provider 凭证。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        provider: provider 名称

    Returns:
        是否删除成功
    """
    deleted = False

    # 从 auth-profiles 删除
    if delete_auth_profile_record(state_dir, provider):
        deleted = True

    # 从单独的 provider 文件删除
    if delete_provider_credential(provider):
        deleted = True

    return deleted


def _load_record_from_dict(data: dict) -> ProviderCredentialRecord | None:
    """从字典加载 ProviderCredentialRecord。"""
    try:
        return ProviderCredentialRecord.model_validate(data)
    except (ValidationError, TypeError):
        return None
