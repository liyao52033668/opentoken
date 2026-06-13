"""上传存储（使用抽象存储后端）。"""
from __future__ import annotations

import copy
from pathlib import Path
from time import time
from uuid import uuid4

from opentoken.storage.factory import get_storage_backend_for_path


_DEFAULT_STORE: dict[str, object] = {
    "version": 1,
    "uploads": {},
}

# 元数据存储键
_METADATA_KEY = "uploads.json"


def _backend_for_state_dir(state_dir: Path):
    return get_storage_backend_for_path(state_dir)


class UploadSizeExceededError(Exception):
    """Raised by add_upload_part when accepting the part would push the running
    parts-byte total beyond the upload's declared `bytes`. The route turns this
    into a 413 so the client knows to stop sending."""


def create_upload(
    state_dir: Path,
    *,
    filename: str,
    expected_bytes: int,
    mime_type: str | None,
    purpose: str,
) -> dict[str, object]:
    """创建上传会话。"""
    upload_id = f"upload-{uuid4().hex}"
    metadata = {
        "id": upload_id,
        "object": "upload",
        "created_at": int(time()),
        "filename": filename,
        "bytes": int(expected_bytes),
        "purpose": purpose,
        "mime_type": mime_type or "application/octet-stream",
        "status": "created",
        "parts": [],
    }

    backend = _backend_for_state_dir(state_dir)

    with backend.acquire_lock(_METADATA_KEY):
        store = _load_store(backend)
        uploads = store.setdefault("uploads", {})
        if not isinstance(uploads, dict):
            uploads = {}
            store["uploads"] = uploads
        uploads[upload_id] = metadata
        _save_store(backend, store)

    return _public_upload(metadata)


def get_upload(state_dir: Path, upload_id: str) -> dict[str, object] | None:
    """获取上传会话。"""
    backend = _backend_for_state_dir(state_dir)
    uploads = _load_store(backend).get("uploads", {})
    if not isinstance(uploads, dict):
        return None
    entry = uploads.get(upload_id)
    if not isinstance(entry, dict):
        return None
    return copy.deepcopy(entry)


def add_upload_part(
    state_dir: Path,
    upload_id: str,
    *,
    content: bytes,
    content_type: str | None = None,
) -> dict[str, object] | None:
    """添加上传分片。"""
    backend = _backend_for_state_dir(state_dir)

    with backend.acquire_lock(_METADATA_KEY):
        store = _load_store(backend)
        uploads = store.get("uploads", {})
        if not isinstance(uploads, dict):
            return None
        entry = uploads.get(upload_id)
        if not isinstance(entry, dict):
            return None
        if str(entry.get("status", "")) != "created":
            return None
        parts = entry.setdefault("parts", [])
        if not isinstance(parts, list):
            parts = []
            entry["parts"] = parts

        # 检查分片大小是否超出声明
        declared = int(entry.get("bytes", 0) or 0)
        existing_total = sum(
            int(p.get("bytes", 0) or 0) for p in parts if isinstance(p, dict)
        )
        if declared and existing_total + len(content) > declared:
            raise UploadSizeExceededError(
                f"Upload {upload_id} parts exceed the declared size of {declared} bytes."
            )

        part_id = f"part-{uuid4().hex}"
        part = {
            "id": part_id,
            "object": "upload.part",
            "created_at": int(time()),
            "upload_id": upload_id,
            "bytes": len(content),
            "content_type": content_type or "application/octet-stream",
        }
        parts.append(part)
        _save_store(backend, store)

        # 写入分片内容
        blob_key = _resolve_part_blob_key(upload_id, part_id)
        backend.write_bytes(blob_key, content)

    return copy.deepcopy(part)


def complete_upload(
    state_dir: Path,
    upload_id: str,
    *,
    part_ids: list[str] | None = None,
) -> tuple[dict[str, object], bytes] | None:
    """完成上传。"""
    backend = _backend_for_state_dir(state_dir)

    with backend.acquire_lock(_METADATA_KEY):
        store = _load_store(backend)
        uploads = store.get("uploads", {})
        if not isinstance(uploads, dict):
            return None
        entry = uploads.get(upload_id)
        if not isinstance(entry, dict):
            return None
        if str(entry.get("status", "")) != "created":
            return None
        parts = entry.get("parts", [])
        if not isinstance(parts, list):
            return None

        ordered_parts: list[dict[str, object]] = []
        if part_ids:
            part_lookup = {
                str(part.get("id", "")): part
                for part in parts
                if isinstance(part, dict)
            }
            for part_id in part_ids:
                part = part_lookup.get(part_id)
                if not isinstance(part, dict):
                    return None
                ordered_parts.append(part)
        else:
            ordered_parts = [part for part in parts if isinstance(part, dict)]

        # 读取所有分片内容
        part_blob_keys = [
            _resolve_part_blob_key(upload_id, str(part.get("id", "")))
            for part in ordered_parts
        ]
        try:
            content_parts = []
            for blob_key in part_blob_keys:
                part_content = backend.read_bytes(blob_key)
                if part_content is None:
                    raise FileNotFoundError
                content_parts.append(part_content)
            content = b"".join(content_parts)
        except FileNotFoundError:
            entry["status"] = "cancelled"
            entry["cancelled_reason"] = "missing_part_blob"
            entry["cancelled_at"] = int(time())
            _save_store(backend, store)
            return None

        entry["status"] = "completed"
        entry["completed_at"] = int(time())
        _save_store(backend, store)

        # 清理分片文件
        for blob_key in part_blob_keys:
            backend.delete(blob_key)

    return _public_upload(entry), content


def cancel_upload(state_dir: Path, upload_id: str) -> dict[str, object] | None:
    """取消上传。"""
    backend = _backend_for_state_dir(state_dir)

    with backend.acquire_lock(_METADATA_KEY):
        store = _load_store(backend)
        uploads = store.get("uploads", {})
        if not isinstance(uploads, dict):
            return None
        entry = uploads.get(upload_id)
        if not isinstance(entry, dict):
            return None
        entry["status"] = "cancelled"
        entry["cancelled_at"] = int(time())
        _save_store(backend, store)

    return _public_upload(entry)


def _public_upload(entry: dict[str, object]) -> dict[str, object]:
    parts = entry.get("parts", [])
    part_count = len(parts) if isinstance(parts, list) else 0
    return {
        "id": str(entry.get("id", "")),
        "object": "upload",
        "created_at": int(entry.get("created_at", 0)),
        "filename": str(entry.get("filename", "")),
        "bytes": int(entry.get("bytes", 0)),
        "purpose": str(entry.get("purpose", "")),
        "mime_type": str(entry.get("mime_type", "application/octet-stream")),
        "status": str(entry.get("status", "created")),
        "part_count": part_count,
    }


def _resolve_part_blob_key(upload_id: str, part_id: str) -> str:
    """解析分片内容的存储键。"""
    return f"uploads/{upload_id}/{part_id}.bin"


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
