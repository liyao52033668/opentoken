"""Streaming-error payload classification.

A stream error mid-response can only signal its kind via the error.type field
in the SSE event (HTTP status is already 200 because the stream started).
Until we routed RuntimeErrors through classify_provider_runtime_error, an
upstream 502 / session-expired / unsupported-model RuntimeError mid-stream
was labeled `invalid_request_error` — telling clients their request was
malformed when it wasn't, so they wouldn't retry an outage.
"""
from __future__ import annotations

import httpx
import pytest

from opentoken.api.routes.chat import _stream_error_payload as chat_payload
from opentoken.api.routes.responses import _stream_error_payload as responses_payload
from opentoken.providers.base import ProviderRateLimitError


# ── chat completions ─────────────────────────────────────────────────────────


def test_chat_stream_payload_rate_limit_is_rate_limit_error():
    p = chat_payload(ProviderRateLimitError("nim is throttled"))
    assert p["error"]["type"] == "rate_limit_error"


def test_chat_stream_payload_httpx_error_is_api_error():
    p = chat_payload(httpx.ReadError("upstream tcp reset"))
    assert p["error"]["type"] == "api_error"


@pytest.mark.parametrize(
    "message,expected",
    [
        # Auth-flavored RuntimeErrors classify as authentication_error.
        ("Claude session expired or invalid. Run `opentoken login claude`.", "authentication_error"),
        ("Qwen returned no chat id (status=200).", "authentication_error"),
        ("Kimi error: {'code': 'unauthenticated'}", "authentication_error"),
        # Upstream / parse failures classify as api_error (NOT invalid_request_error).
        ("DeepSeek chat completion returned no text content.", "api_error"),
        ("upstream tcp reset", "api_error"),
        # Request-validation errors stay invalid_request_error (rare mid-stream
        # but the classifier is shared).
        ("Unsupported model: algae/foo/bar", "invalid_request_error"),
    ],
)
def test_chat_stream_payload_runtime_error_uses_classifier(message: str, expected: str):
    p = chat_payload(RuntimeError(message))
    assert p["error"]["type"] == expected


def test_chat_stream_payload_plain_exception_is_api_error():
    """Unexpected non-RuntimeError exceptions are gateway-side problems, not
    client validation failures — must not be labeled invalid_request_error."""
    p = chat_payload(ValueError("totally unexpected"))
    assert p["error"]["type"] == "api_error"


# ── responses ────────────────────────────────────────────────────────────────


def test_responses_stream_payload_runtime_error_uses_classifier():
    p = responses_payload(RuntimeError("Claude session expired or invalid."))
    # Responses uses flat top-level fields, not a nested error object.
    assert p["code"] == "authentication_error"
    assert p["type"] == "error"


def test_responses_stream_payload_upstream_error_is_api_error_not_invalid_request():
    p = responses_payload(RuntimeError("DeepSeek chat completion returned no text content."))
    assert p["code"] == "api_error"


# ── no upstream-URL/credential leak on mid-stream httpx errors ────────────────
#
# Once the SSE stream has started the HTTP status is already 200, so the error
# event is the only signal — but str(httpx.HTTPStatusError) embeds the full
# upstream URL (often with a session id in the query string). The non-stream
# path scrubs this; the stream path must too.

_LEAKY_URL = "https://chat.qwen.ai/api/v2/chat?session=SECRET-TOKEN-123"


def _httpx_status_error_with_url() -> httpx.HTTPStatusError:
    # Reproduce exactly how providers raise: response.raise_for_status() builds
    # a message that embeds the full request URL (including the query string).
    request = httpx.Request("POST", _LEAKY_URL)
    response = httpx.Response(502, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        assert "chat.qwen.ai" in str(exc)  # sanity: the leak source is present
        return exc
    raise AssertionError("raise_for_status did not raise")


def test_chat_stream_payload_httpx_error_does_not_leak_upstream_url():
    p = chat_payload(_httpx_status_error_with_url())
    message = str(p["error"]["message"])
    assert "chat.qwen.ai" not in message
    assert "SECRET-TOKEN-123" not in message
    assert "://" not in message  # no URL of any scheme leaked


def test_responses_stream_payload_httpx_error_does_not_leak_upstream_url():
    p = responses_payload(_httpx_status_error_with_url())
    message = str(p["message"])
    assert "chat.qwen.ai" not in message
    assert "SECRET-TOKEN-123" not in message
    assert "://" not in message  # no URL of any scheme leaked


def test_chat_stream_payload_unexpected_exception_does_not_leak_internal_detail():
    p = chat_payload(KeyError("/Users/secret/internal/path/state.json"))
    message = str(p["error"]["message"])
    assert "secret" not in message
    assert p["error"]["type"] == "api_error"
