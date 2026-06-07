"""文件存储（使用抽象存储后端）。"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from time import time
from uuid import uuid4

from opentoken.storage.factory import get_storage_backend


_SAFE_FILE_ID = re.compile(r"^file-[A-Za-z0-9]{16,}$")

_DEFAULT_STORE: dict[str, object] = {
    "version": 1,
    "files": {},
}

# 元数据存储键
_METADATA_KEY = "files.json"


def create_file(
    state_dir: Path,
    *,
    filename: str,
    content: bytes,
    purpose: str,
    mime_type: str | None = None,
) -> dict[str, object]:
    """创建文件。

    Args:
        state_dir: 状态目录（保留用于向后兼容，实际使用 StorageBackend）
        filename: 文件名
        content: 文件内容
        purpose: 用途
        mime_type: MIME 类型

    Returns:
        文件元数据
    """
    file_id = f"file-{uuid4().hex}"
    metadata = {
        "id": file_id,
        "object": "file",
        "bytes": len(content),
        "created_at": int(time()),
        "filename": filename,
        "purpose": purpose,
        "status": "processed",
        "mime_type": mime_type or "application/octet-stream",
    }

    backend = get_storage_backend()
    blob_key = _resolve_blob_key(file_id)

    with backend.acquire_lock(_METADATA_KEY):
        # 先写文件内容，再更新元数据
        backend.write_bytes(blob_key, content)

        # 更新元数据
        store = _load_store(backend)
        files = store.setdefault("files", {})
        if not isinstance(files, dict):
            files = {}
            store["files"] = files
        files[file_id] = copy.deepcopy(metadata)
        _save_store(backend, store)

    return copy.deepcopy(metadata)


def list_files(state_dir: Path) -> list[dict[str, object]]:
    """列出所有文件。"""
    backend = get_storage_backend()
    store = _load_store(backend)
    files = store.get("files", {})
    if not isinstance(files, dict):
        return []
    items = [
        _public_metadata(value)
        for value in files.values()
        if isinstance(value, dict)
    ]
    return sorted(items, key=lambda item: (int(item.get("created_at", 0)), str(item.get("id", ""))))


def get_file(state_dir: Path, file_id: str) -> dict[str, object] | None:
    """获取文件元数据。"""
    backend = get_storage_backend()
    store = _load_store(backend)
    files = store.get("files", {})
    if not isinstance(files, dict):
        return None
    entry = files.get(file_id)
    if not isinstance(entry, dict):
        return None
    return _public_metadata(entry)


def read_file_content(state_dir: Path, file_id: str) -> tuple[dict[str, object], bytes] | None:
    """读取文件内容。"""
    metadata = get_file(state_dir, file_id)
    if metadata is None:
        return None

    backend = get_storage_backend()
    blob_key = _resolve_blob_key(file_id)
    content = backend.read_bytes(blob_key)
    if content is None:
        return None

    return metadata, content


def delete_file(state_dir: Path, file_id: str) -> bool:
    """删除文件。"""
    if not _SAFE_FILE_ID.match(file_id):
        return False

    backend = get_storage_backend()

    with backend.acquire_lock(_METADATA_KEY):
        store = _load_store(backend)
        files = store.get("files", {})
        if not isinstance(files, dict) or file_id not in files:
            return False
        files.pop(file_id, None)
        _save_store(backend, store)

    # 删除文件内容
    blob_key = _resolve_blob_key(file_id)
    backend.delete(blob_key)

    return True


def _public_metadata(entry: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(entry.get("id", "")),
        "object": "file",
        "bytes": int(entry.get("bytes", 0)),
        "created_at": int(entry.get("created_at", 0)),
        "filename": str(entry.get("filename", "")),
        "purpose": str(entry.get("purpose", "")),
        "status": str(entry.get("status", "processed")),
        "mime_type": str(entry.get("mime_type", "application/octet-stream")),
    }


def _resolve_blob_key(file_id: str) -> str:
    """解析文件内容的存储键。"""
    if not _SAFE_FILE_ID.match(file_id):
        raise ValueError(f"Refusing to resolve unsafe file id: {file_id!r}")
    return f"files/{file_id}.bin"


def _load_store(backend) -> dict[str, object]:
    """加载元数据存储。"""
    store = backend.read_json(_METADATA_KEY)
    if store is None:
        return copy.deepcopy(_DEFAULT_STORE)
    result = copy.deepcopy(_DEFAULT_STORE)
    result.update(store)
    return result


def _save_store(backend, store: dict[str, object]) -> None:
    """保存元数据存储。"""
    backend.write_json(_METADATA_KEY, store)
