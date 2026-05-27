"""Storage modules must survive corrupt / non-dict / truncated JSON on disk.

A crash mid-write (pre-atomic-write era) or external tampering can leave a
store file unparseable. Every store's _load_store should degrade to the
default empty store rather than raise, so the gateway keeps working (and the
next atomic write heals the file).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from opentoken.models.provider_credentials import ProviderCredentialRecord


def _corrupt(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize("bad", ['{"truncated":', "not json at all", "[1,2,3]", "null", "12345"])
def test_file_store_survives_corrupt_store(tmp_path: Path, bad: str) -> None:
    from opentoken.storage import file_store

    _corrupt(tmp_path / "files.json", bad)
    # Listing should not raise; it returns an empty list for a corrupt store.
    assert file_store.list_files(tmp_path) == []
    # And a subsequent write heals it.
    created = file_store.create_file(
        tmp_path, filename="a.txt", content=b"hi", purpose="assistants", mime_type="text/plain"
    )
    assert created["id"].startswith("file-")
    assert any(item["id"] == created["id"] for item in file_store.list_files(tmp_path))


@pytest.mark.parametrize("bad", ['{"x":', "garbage", "[]", "true"])
def test_response_store_survives_corrupt_store(tmp_path: Path, bad: str) -> None:
    from opentoken.storage import response_store

    _corrupt(tmp_path / "responses.json", bad)
    assert response_store.load_response_messages(tmp_path, "resp-x") is None
    response_store.save_response_messages(
        tmp_path, response_id="resp-1", model="m", messages=[{"role": "user", "content": "hi"}]
    )
    loaded = response_store.load_response_messages(tmp_path, "resp-1")
    assert loaded == [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize("bad", ['{"profiles":', "nope", "[]", "42"])
def test_auth_profiles_survives_corrupt_store(tmp_path: Path, bad: str) -> None:
    from opentoken.storage import auth_profiles

    providers_dir = tmp_path / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    _corrupt(auth_profiles.resolve_auth_profiles_path(providers_dir), bad)

    assert auth_profiles.load_auth_profile_record(providers_dir, "deepseek") is None

    record = ProviderCredentialRecord(
        provider="deepseek",
        kind="web_session",
        cookie="c",
        headers={},
        user_agent="ua",
        metadata={},
        status="valid",
    )
    auth_profiles.save_auth_profile_record(providers_dir, record)
    loaded = auth_profiles.load_auth_profile_record(providers_dir, "deepseek")
    assert loaded is not None
    assert loaded.cookie == "c"


@pytest.mark.parametrize("bad", ['{"uploads":', "??", "[]", "false"])
def test_upload_store_survives_corrupt_store(tmp_path: Path, bad: str) -> None:
    from opentoken.storage import upload_store

    _corrupt(tmp_path / "uploads.json", bad)
    # A corrupt store yields no upload; creating a new one heals it.
    created = upload_store.create_upload(
        tmp_path, filename="j.txt", expected_bytes=2, purpose="assistants", mime_type="text/plain"
    )
    assert created["id"].startswith("upload")
