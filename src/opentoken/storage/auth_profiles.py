"""认证 profiles 存储（使用 StorageBackend）。

跨 provider 的认证 profile 存储，支持本地文件系统或 S3。
"""
from __future__ import annotations

import copy
from pathlib import Path

from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.storage.factory import get_storage_backend_for_path

_DEFAULT_STORE: dict[str, object] = {
    "version": 1,
    "profiles": {},
    "order": {},
    "lastGood": {},
    "usageStats": {},
}


def resolve_auth_profiles_key() -> str:
    """获取 auth-profiles 存储键（用于向后兼容）。"""
    return "auth-profiles.json"


def resolve_auth_profiles_path(providers_dir: Path) -> Path:
    """获取 auth-profiles 文件路径。"""
    providers_path = providers_dir.expanduser().resolve()
    if providers_path.name == "providers":
        return providers_path.parent / "auth-profiles.json"
    return providers_path / "auth-profiles.json"


def _backend_for_providers_dir(providers_dir: Path):
    return get_storage_backend_for_path(resolve_auth_profiles_path(providers_dir).parent)


def load_auth_profile_record(providers_dir: Path, provider: str) -> ProviderCredentialRecord | None:
    """加载指定 provider 的认证 profile。

    Args:
        providers_dir: providers 目录（保留参数，用于向后兼容）
        provider: provider 名称

    Returns:
        ProviderCredentialRecord 或 None
    """
    backend = _backend_for_providers_dir(providers_dir)
    store = backend.read_json(resolve_auth_profiles_key())
    if store is None:
        store = copy.deepcopy(_DEFAULT_STORE)

    profiles = store.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        store["profiles"] = profiles

    # 查找匹配的 profile
    preferred_id = f"{provider}:default"
    candidates: list[tuple[str, object]] = []
    if preferred_id in profiles:
        candidates.append((preferred_id, profiles[preferred_id]))
    for profile_id, raw in profiles.items():
        if profile_id == preferred_id:
            continue
        if isinstance(raw, dict) and str(raw.get("provider", "")).strip() == provider:
            candidates.append((profile_id, raw))

    for _, raw in candidates:
        record = _decode_profile_record(raw)
        if record is not None:
            return record
    return None


def list_auth_profile_records(providers_dir: Path) -> list[ProviderCredentialRecord]:
    """列出所有认证 profiles。

    Args:
        providers_dir: providers 目录（保留参数，用于向后兼容）

    Returns:
        ProviderCredentialRecord 列表
    """
    backend = _backend_for_providers_dir(providers_dir)
    store = backend.read_json(resolve_auth_profiles_key())
    if store is None:
        store = copy.deepcopy(_DEFAULT_STORE)

    profiles = store.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}

    deduped: dict[str, ProviderCredentialRecord] = {}
    for profile_id, raw in profiles.items():
        record = _decode_profile_record(raw)
        if record is None:
            continue
        preferred = deduped.get(record.provider)
        if preferred is None or profile_id == f"{record.provider}:default":
            deduped[record.provider] = record
    return [deduped[key] for key in sorted(deduped)]


def save_auth_profile_record(providers_dir: Path, record: ProviderCredentialRecord) -> Path:
    """保存认证 profile。

    Args:
        providers_dir: providers 目录（保留参数，用于向后兼容）
        record: ProviderCredentialRecord

    Returns:
        保存路径（虚拟路径，用于向后兼容）
    """
    backend = _backend_for_providers_dir(providers_dir)
    with backend.acquire_lock(resolve_auth_profiles_key()):
        store = backend.read_json(resolve_auth_profiles_key())
        if store is None:
            store = copy.deepcopy(_DEFAULT_STORE)

        profiles = store.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            store["profiles"] = profiles

        profiles[f"{record.provider}:default"] = {
            "type": "token",
            "provider": record.provider,
            "token": record.model_dump_json(),
        }
        backend.write_json(resolve_auth_profiles_key(), store)
    return resolve_auth_profiles_path(providers_dir)


def delete_auth_profile_record(providers_dir: Path, provider: str) -> bool:
    """删除指定 provider 的认证 profile。

    Args:
        providers_dir: providers 目录（保留参数，用于向后兼容）
        provider: provider 名称

    Returns:
        是否删除成功
    """
    backend = _backend_for_providers_dir(providers_dir)
    store = backend.read_json(resolve_auth_profiles_key())
    if store is None:
        return False

    profiles = store.get("profiles", {})
    if not isinstance(profiles, dict):
        return False

    profile_ids = [
        profile_id
        for profile_id, raw in profiles.items()
        if profile_id == f"{provider}:default"
        or (isinstance(raw, dict) and str(raw.get("provider", "")).strip() == provider)
    ]
    if not profile_ids:
        return False

    for profile_id in profile_ids:
        profiles.pop(profile_id, None)

    backend.write_json(resolve_auth_profiles_key(), store)
    return True


def _decode_profile_record(raw: object) -> ProviderCredentialRecord | None:
    """解码 profile 记录为 ProviderCredentialRecord。"""
    if not isinstance(raw, dict):
        return None

    token = raw.get("token")
    if isinstance(token, str) and token.strip():
        try:
            return ProviderCredentialRecord.model_validate_json(token)
        except Exception:
            pass

    try:
        return ProviderCredentialRecord.model_validate(raw)
    except Exception:
        return None


# ============================================================
# 内部函数（用于测试，保持向后兼容）
# ============================================================


def _load_store(providers_dir: Path) -> dict[str, object]:
    """加载 auth-profiles 存储（测试用）。"""
    backend = _backend_for_providers_dir(providers_dir)
    store = backend.read_json(resolve_auth_profiles_key())
    if store is None:
        return copy.deepcopy(_DEFAULT_STORE)
    return store


def _save_store(providers_dir: Path, store: dict[str, object]) -> None:
    """保存 auth-profiles 存储（测试用）。"""
    backend = _backend_for_providers_dir(providers_dir)
    backend.write_json(resolve_auth_profiles_key(), store)
