"""Provider 会话存储（使用 StorageBackend）。

会话上下文存储，支持本地文件系统或 S3 兼容对象存储。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.storage.factory import get_storage_backend_for_path


# Cap the session store. The key embeds a credential fingerprint, so each
# re-login (fresh cookie → new fingerprint) adds a new entry and the old one is
# never reclaimed — the file grew without bound. Keep the most-recently-written
# entries (insertion/update order) and evict the oldest beyond the cap; the
# only state here is short-lived conversation context, so an evicted entry just
# means a fresh conversation next time. (response_store is capped for the same
# reason.)
_MAX_SESSION_ENTRIES = 256


def _backend_for_state_dir(state_dir: Path):
    return get_storage_backend_for_path(state_dir)


def load_provider_session(
    state_dir: Path,
    *,
    provider: str,
    credentials: ProviderCredentialRecord,
) -> dict[str, str]:
    """加载 provider 会话。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        provider: provider 名称
        credentials: ProviderCredentialRecord

    Returns:
        会话状态字典
    """
    backend = _backend_for_state_dir(state_dir)
    store = backend.read_json("provider-sessions.json") or {}
    return dict(store.get(_session_key(provider, credentials), {}))


def save_provider_session(
    state_dir: Path,
    *,
    provider: str,
    credentials: ProviderCredentialRecord,
    state: dict[str, str],
) -> Path:
    """保存 provider 会话。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        provider: provider 名称
        credentials: ProviderCredentialRecord
        state: 会话状态

    Returns:
        保存路径（虚拟路径，用于向后兼容）
    """
    backend = _backend_for_state_dir(state_dir)
    key = _session_key(provider, credentials)

    with backend.acquire_lock("provider-sessions.json"):
        store = backend.read_json("provider-sessions.json") or {}

        # Re-insert at the end so this key counts as most-recent (dicts preserve
        # insertion order); then evict the oldest entries beyond the cap.
        store.pop(key, None)
        store[key] = dict(state)

        if len(store) > _MAX_SESSION_ENTRIES:
            for stale_key in list(store.keys())[: len(store) - _MAX_SESSION_ENTRIES]:
                store.pop(stale_key, None)

        backend.write_json("provider-sessions.json", store)
    return _resolve_session_store_path(state_dir)


def credential_fingerprint(credentials: ProviderCredentialRecord) -> str:
    """计算凭证指纹。"""
    payload = json.dumps(
        {
            "provider": credentials.provider,
            "kind": credentials.kind,
            "cookie": credentials.cookie or "",
            "headers": credentials.headers,
            "user_agent": credentials.user_agent or "",
            "metadata": credentials.metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _session_key(provider: str, credentials: ProviderCredentialRecord) -> str:
    """生成会话键。"""
    return f"{provider}:{credential_fingerprint(credentials)}"


def _resolve_session_store_path(state_dir: Path) -> Path:
    """获取会话存储路径。"""
    return state_dir / "provider-sessions.json"


def _load_store(state_dir: Path) -> dict[str, object]:
    """加载会话存储（测试用）。"""
    resolved = state_dir.expanduser().resolve()
    if resolved.name == "provider-sessions.json":
        if not resolved.exists():
            return {}
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    backend = _backend_for_state_dir(state_dir)
    return backend.read_json("provider-sessions.json") or {}
