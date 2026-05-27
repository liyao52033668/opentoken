from __future__ import annotations

from pathlib import Path

from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.storage.provider_sessions import (
    load_provider_session,
    save_provider_session,
)


def test_provider_session_store_roundtrips_conversation_state(tmp_path: Path) -> None:
    credentials = ProviderCredentialRecord(
        provider="chatgpt",
        kind="browser_session",
        cookie="session=abc",
        headers={},
        user_agent="ua",
        metadata={},
        status="valid",
    )

    save_provider_session(
        tmp_path,
        provider="chatgpt",
        credentials=credentials,
        state={"conversation_id": "conv-1", "parent_message_id": "msg-1"},
    )

    loaded = load_provider_session(tmp_path, provider="chatgpt", credentials=credentials)

    assert loaded == {"conversation_id": "conv-1", "parent_message_id": "msg-1"}


def test_provider_session_store_is_isolated_by_credential_fingerprint(tmp_path: Path) -> None:
    credentials_one = ProviderCredentialRecord(
        provider="qwen-intl",
        kind="browser_session",
        cookie="token=one",
        headers={},
        user_agent="ua",
        metadata={},
        status="valid",
    )
    credentials_two = ProviderCredentialRecord(
        provider="qwen-intl",
        kind="browser_session",
        cookie="token=two",
        headers={},
        user_agent="ua",
        metadata={},
        status="valid",
    )

    save_provider_session(tmp_path, provider="qwen-intl", credentials=credentials_one, state={"chat_id": "chat-1"})

    assert load_provider_session(tmp_path, provider="qwen-intl", credentials=credentials_one) == {"chat_id": "chat-1"}
    assert load_provider_session(tmp_path, provider="qwen-intl", credentials=credentials_two) == {}


def test_provider_session_store_caps_unbounded_growth(tmp_path: Path) -> None:
    """Each re-login (fresh cookie → new fingerprint) adds a new key; without a
    cap the store grew forever. Saving past the cap evicts the oldest entries
    while keeping the most-recent ones intact."""
    from opentoken.storage.provider_sessions import _MAX_SESSION_ENTRIES, _load_store
    from opentoken.storage.provider_sessions import _resolve_session_store_path

    total = _MAX_SESSION_ENTRIES + 20
    for i in range(total):
        creds = ProviderCredentialRecord(
            provider="chatgpt",
            kind="browser_session",
            cookie=f"session={i}",  # distinct cookie → distinct fingerprint
            headers={},
            user_agent="ua",
            metadata={},
            status="valid",
        )
        save_provider_session(
            tmp_path, provider="chatgpt", credentials=creds, state={"conversation_id": f"c{i}"}
        )

    store = _load_store(_resolve_session_store_path(tmp_path))
    assert len(store) == _MAX_SESSION_ENTRIES

    # The most recent credential's session is still present.
    last_creds = ProviderCredentialRecord(
        provider="chatgpt", kind="browser_session", cookie=f"session={total - 1}",
        headers={}, user_agent="ua", metadata={}, status="valid",
    )
    assert load_provider_session(tmp_path, provider="chatgpt", credentials=last_creds) == {
        "conversation_id": f"c{total - 1}"
    }
    # An evicted early credential's session is gone (fresh conversation next time).
    first_creds = ProviderCredentialRecord(
        provider="chatgpt", kind="browser_session", cookie="session=0",
        headers={}, user_agent="ua", metadata={}, status="valid",
    )
    assert load_provider_session(tmp_path, provider="chatgpt", credentials=first_creds) == {}
