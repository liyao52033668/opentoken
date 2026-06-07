"""响应历史存储（使用 StorageBackend）。

/v1/responses 历史记录存储，支持本地文件系统或 S3 兼容对象存储。
"""
from __future__ import annotations

import copy
import time
from collections import OrderedDict
from pathlib import Path

from opentoken.storage.config_store import read_responses, write_responses


_DEFAULT_STORE: dict[str, object] = {
    "version": 1,
    "responses": {},
}

# Default retention: 7 days OR 1024 entries, whichever fires first. previous_response_id
# is meant for short-lived conversation context — the store used to grow forever, which
# eventually corrupted JSON on disk and made every load slower.
_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
_DEFAULT_MAX_ENTRIES = 1024


def load_response_messages(state_dir: Path, response_id: str) -> list[dict[str, object]] | None:
    """加载响应消息。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        response_id: 响应 ID

    Returns:
        消息列表或 None
    """
    store = read_responses()
    if store is None:
        store = _DEFAULT_STORE

    responses = store.get("responses", {})
    if not isinstance(responses, dict):
        return None

    entry = responses.get(response_id)
    if not isinstance(entry, dict):
        return None

    messages = entry.get("messages")
    if not isinstance(messages, list):
        return None

    return copy.deepcopy([message for message in messages if isinstance(message, dict)])


def save_response_messages(
    state_dir: Path,
    *,
    response_id: str,
    model: str,
    messages: list[dict[str, object]],
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    max_entries: int = _DEFAULT_MAX_ENTRIES,
) -> None:
    """保存响应消息。

    Args:
        state_dir: 状态目录（保留参数，用于向后兼容）
        response_id: 响应 ID
        model: 模型名称
        messages: 消息列表
        ttl_seconds: TTL 秒数
        max_entries: 最大条目数
    """
    store = read_responses()
    if store is None:
        store = copy.deepcopy(_DEFAULT_STORE)

    responses_raw = store.get("responses", {})
    # Use an OrderedDict so we can evict LRU when over the cap. Re-inserting moves
    # to the end implicitly because we del-then-set below.
    if isinstance(responses_raw, dict):
        responses = OrderedDict(responses_raw)
    else:
        responses = OrderedDict()

    now = int(time.time())

    # Expire by age first.
    if ttl_seconds > 0:
        cutoff = now - ttl_seconds
        for stale_id in [
            key
            for key, entry in responses.items()
            if isinstance(entry, dict) and int(entry.get("updated_at", 0)) < cutoff
        ]:
            responses.pop(stale_id, None)

    responses.pop(response_id, None)
    responses[response_id] = {
        "model": model,
        "messages": copy.deepcopy(messages),
        "updated_at": now,
    }

    # Cap by count.
    while max_entries > 0 and len(responses) > max_entries:
        responses.popitem(last=False)

    store["responses"] = dict(responses)
    write_responses(store)


def _resolve_response_store_path(state_dir: Path) -> Path:
    """获取响应存储路径（测试用）。"""
    return state_dir / "responses.json"
