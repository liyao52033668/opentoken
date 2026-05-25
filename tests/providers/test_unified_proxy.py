from __future__ import annotations

import os
import sys
import types

import pytest

from opentoken.gateway.normalized import NormalizedChatRequest
from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.providers.base import ChatResponse


def _credentials() -> ProviderCredentialRecord:
    return ProviderCredentialRecord(
        provider="unified",
        kind="api_key",
        cookie="",
        headers={},
        user_agent="",
        metadata={
            "api_key_openrouter": "sk-or-test",
            "api_key_anthropic": "sk-ant-test",
        },
        status="valid",
    )


def _request(model: str) -> NormalizedChatRequest:
    return NormalizedChatRequest(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        stream=False,
    )


@pytest.fixture
def fake_litellm(monkeypatch):
    """Inject a fake `litellm` module to test the adapter without the real dep."""
    seen_calls: list[dict] = []

    def fake_completion(**kwargs):
        seen_calls.append(kwargs)
        # Mimic the OpenAI-style response object that LiteLLM returns.
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "fake-response",
                        "tool_calls": None,
                    },
                    "finish_reason": "stop",
                }
            ],
        }

    module = types.SimpleNamespace(completion=fake_completion, _seen=seen_calls)
    monkeypatch.setitem(sys.modules, "litellm", module)
    # Reset the cached availability flag from the adapter module so the new fake
    # is picked up even if a previous test marked it unavailable.
    import opentoken.providers.unified_proxy as up
    up._LITELLM_AVAILABLE = None
    return module


def test_unified_proxy_calls_litellm_with_stripped_prefix(fake_litellm):
    from opentoken.providers.unified_proxy import UnifiedProxyAdapter

    adapter = UnifiedProxyAdapter()
    response = adapter.chat(_request("unified/openrouter/anthropic/claude-3.5-sonnet"), _credentials())

    assert isinstance(response, ChatResponse)
    assert response.content == "fake-response"
    assert response.finish_reason == "stop"

    call = fake_litellm._seen[-1]
    # The unified/ prefix is stripped before being passed to litellm.
    assert call["model"] == "openrouter/anthropic/claude-3.5-sonnet"
    assert call["stream"] is False
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_unified_proxy_injects_env_for_only_known_backends(monkeypatch, fake_litellm):
    from opentoken.providers.unified_proxy import UnifiedProxyAdapter

    saved_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
    saved_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

    captured: dict[str, str | None] = {}

    real_completion = fake_litellm.completion

    def spying_completion(**kwargs):
        captured["openrouter"] = os.environ.get("OPENROUTER_API_KEY")
        captured["anthropic"] = os.environ.get("ANTHROPIC_API_KEY")
        return real_completion(**kwargs)

    fake_litellm.completion = spying_completion

    adapter = UnifiedProxyAdapter()
    adapter.chat(_request("unified/openrouter/foo"), _credentials())

    # During the call the env vars were set …
    assert captured["openrouter"] == "sk-or-test"
    assert captured["anthropic"] == "sk-ant-test"
    # … and after the call they're restored / removed.
    assert os.environ.get("OPENROUTER_API_KEY") is None
    assert os.environ.get("ANTHROPIC_API_KEY") is None

    if saved_openrouter is not None:
        os.environ["OPENROUTER_API_KEY"] = saved_openrouter
    if saved_anthropic is not None:
        os.environ["ANTHROPIC_API_KEY"] = saved_anthropic


def test_unified_proxy_raises_when_litellm_missing(monkeypatch):
    import opentoken.providers.unified_proxy as up

    monkeypatch.setitem(sys.modules, "litellm", None)
    # Reset cached flag and make the import attempt fail.
    up._LITELLM_AVAILABLE = None
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError("no litellm")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match="litellm is not installed"):
        up.UnifiedProxyAdapter().chat(_request("unified/openrouter/x"), _credentials())
