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
