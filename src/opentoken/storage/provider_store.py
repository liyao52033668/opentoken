"""Provider 凭证存储（使用 StorageBackend）。

支持本地文件系统或 S3 兼容对象存储。
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.storage._atomic import write_json_atomic
from opentoken.storage.auth_profiles import (
    delete_auth_profile_record,
    list_auth_profile_records,
    load_auth_profile_record,
    save_auth_profile_record,
)


def _legacy_provider_path(providers_dir: Path, provider: str) -> Path:
    return providers_dir.expanduser().resolve() / f"{provider}.json"


def _write_legacy_provider_credential(providers_dir: Path, provider: str, data: dict) -> Path:
    path = _legacy_provider_path(providers_dir, provider)
    write_json_atomic(path, data, sensitive=True)
    return path


def _read_legacy_provider_credential(providers_dir: Path, provider: str) -> dict | None:
    path = _legacy_provider_path(providers_dir, provider)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _list_legacy_provider_credentials(providers_dir: Path) -> list[tuple[str, dict]]:
    base_dir = providers_dir.expanduser().resolve()
    if not base_dir.exists():
        return []
    result: list[tuple[str, dict]] = []
    for path in sorted(base_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            result.append((path.stem, payload))
    return result


def _delete_legacy_provider_credential(providers_dir: Path, provider: str) -> bool:
    path = _legacy_provider_path(providers_dir, provider)
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


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
    return _write_legacy_provider_credential(state_dir, record.provider, provider_data)


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
    provider_data = _read_legacy_provider_credential(state_dir, provider)
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
    for _, provider_data in _list_legacy_provider_credentials(state_dir):
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
    if _delete_legacy_provider_credential(state_dir, provider):
        deleted = True

    return deleted


def _load_record_from_dict(data: dict) -> ProviderCredentialRecord | None:
    """从字典加载 ProviderCredentialRecord。"""
    try:
        return ProviderCredentialRecord.model_validate(data)
    except (ValidationError, TypeError):
        return None
