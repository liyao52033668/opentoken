import json
import os
import stat
import sys

import pytest

from opentoken.opentoken.bridge import apply_algae_provider_patch, build_algae_provider_patch


def test_build_algae_provider_patch_writes_envelope_with_dynamic_model_list(monkeypatch) -> None:
    # The bridge now pulls live-discovered models, so seed a deterministic catalog.
    from opentoken.models.catalog import ModelCatalogEntry

    monkeypatch.setattr(
        "opentoken.opentoken.bridge.load_model_catalog",
        lambda: [
            ModelCatalogEntry(id="algae/deepseek/deepseek-chat", provider="opentoken", name="DeepSeek Chat"),
            ModelCatalogEntry(id="algae/claude/claude-sonnet-4-6", provider="opentoken", name="Claude Sonnet 4.6"),
        ],
    )

    patch = build_algae_provider_patch(
        base_url="http://127.0.0.1:32117/v1",
        api_key="test-algae-key",
    )

    assert "models" in patch
    assert "algae" in patch["models"]["providers"]
    provider = patch["models"]["providers"]["algae"]
    assert provider["api"] == "openai-completions"
    assert provider["apiKey"] == "test-algae-key"
    assert provider["baseUrl"] == "http://127.0.0.1:32117/v1"
    assert any(model["id"] == "deepseek/deepseek-chat" for model in provider["models"])
    assert any(model["id"] == "claude/claude-sonnet-4-6" for model in provider["models"])


def test_build_algae_provider_patch_handles_empty_discovery(monkeypatch) -> None:
    # When no providers are logged in / discovery returns nothing, the patch
    # should still produce a valid envelope with an empty models list rather
    # than fall back to a stale hardcoded list.
    monkeypatch.setattr("opentoken.opentoken.bridge.load_model_catalog", lambda: [])
    patch = build_algae_provider_patch(
        base_url="http://127.0.0.1:32117/v1",
        api_key="test-algae-key",
    )
    provider = patch["models"]["providers"]["algae"]
    assert provider["models"] == []


def test_apply_algae_provider_patch_writes_owner_only_and_atomic(tmp_path, monkeypatch) -> None:
    """The upstream config carries the gateway apiKey — it must land 0600 and
    leave no temp file behind (atomic tmp + os.replace)."""
    monkeypatch.setattr("opentoken.opentoken.bridge.load_model_catalog", lambda: [])
    config_path = tmp_path / "opentoken.json"
    patch = build_algae_provider_patch(base_url="http://127.0.0.1:32117/v1", api_key="secret-key")
    apply_algae_provider_patch(config_path, patch)

    assert config_path.exists()
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["models"]["providers"]["algae"]["apiKey"] == "secret-key"
    if not sys.platform.startswith("win"):
        mode = stat.S_IMODE(os.stat(config_path).st_mode)
        assert mode & 0o077 == 0, f"upstream config too permissive: {oct(mode)}"
    assert list(tmp_path.glob("*.tmp")) == []


def test_apply_algae_provider_patch_rejects_corrupt_existing_config(tmp_path, monkeypatch) -> None:
    """A corrupt existing upstream config must raise a clear error, not a raw
    JSONDecodeError, and must not overwrite the corrupt file."""
    monkeypatch.setattr("opentoken.opentoken.bridge.load_model_catalog", lambda: [])
    config_path = tmp_path / "opentoken.json"
    config_path.write_text("{ this is not json", encoding="utf-8")
    patch = build_algae_provider_patch(base_url="http://x/v1", api_key="k")

    with pytest.raises(RuntimeError, match="not valid JSON"):
        apply_algae_provider_patch(config_path, patch)

    # The corrupt file is left intact (we refused to overwrite it).
    assert config_path.read_text(encoding="utf-8") == "{ this is not json"
