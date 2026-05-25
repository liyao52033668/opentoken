"""Unified backend proxy — bridges opentoken to 100+ providers via LiteLLM.

This adapter exists so users can swing opentoken at any OpenAI-compatible
backend (OpenRouter, Groq, Together, Bedrock, Mistral, Cohere, Perplexity,
xAI, Fireworks, DeepInfra, Ollama, LM Studio…) without writing a one-off
adapter for each. The litellm package is intentionally a soft dependency:
opentoken stays installable in lean environments where you don't need this
proxy, and importing this module is a no-op until you actually configure
the `unified` provider.

Credential layout (`~/.opentoken/providers/unified.json`):

    {
      "kind": "api_key",
      "metadata": {
        "api_key_openrouter":   "sk-or-v1-...",
        "api_key_groq":         "gsk_...",
        "api_key_together":     "...",
        "api_key_anthropic":    "sk-ant-...",
        "api_key_openai":       "sk-..."
      },
      "status": "valid"
    }

Model id format coming in:

    unified/<backend>/<model-id>

For example `unified/openrouter/anthropic/claude-3.5-sonnet` becomes a
LiteLLM call of `openrouter/anthropic/claude-3.5-sonnet`. The backend
segment names what LiteLLM calls the provider; everything after it is the
upstream model id verbatim.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from opentoken.gateway.normalized import NormalizedChatRequest
from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.providers.base import ChatResponse, ProviderAdapter, ProviderRateLimitError


_LITELLM_AVAILABLE: bool | None = None


def _import_litellm():
    """Lazy-import litellm so the soft dep stays soft.

    Imports are cached; the function returns the litellm module or raises a
    descriptive RuntimeError that points the user at the install command.
    """
    global _LITELLM_AVAILABLE
    if _LITELLM_AVAILABLE is False:
        raise RuntimeError(
            "litellm is not installed. Install with `uv add 'litellm>=1.50.0'` "
            "or `uv sync --extra unified` to enable the unified proxy provider."
        )
    try:
        import litellm  # type: ignore
    except ImportError as exc:
        _LITELLM_AVAILABLE = False
        raise RuntimeError(
            "litellm is not installed. Install with `uv add 'litellm>=1.50.0'` "
            "or `uv sync --extra unified` to enable the unified proxy provider."
        ) from exc
    _LITELLM_AVAILABLE = True
    return litellm


_KEY_TO_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "cohere": "COHERE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "fireworks": "FIREWORKS_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "xai": "XAI_API_KEY",
    "azure": "AZURE_API_KEY",
}


_ENV_LOCK = threading.Lock()


@contextmanager
def _injected_env(envs: dict[str, str]):
    """Inject env vars for litellm's duration, then restore.

    LiteLLM reads provider keys from process env. We don't want a long-lived
    process to keep them set (it pollutes other libraries and is harder to
    rotate). The lock prevents two concurrent unified-proxy calls from
    interfering with each other's env state.
    """
    if not envs:
        yield
        return
    with _ENV_LOCK:
        saved: dict[str, str | None] = {key: os.environ.get(key) for key in envs}
        os.environ.update(envs)
        try:
            yield
        finally:
            for key, original in saved.items():
                if original is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original


def _resolve_envs(credentials: ProviderCredentialRecord) -> dict[str, str]:
    out: dict[str, str] = {}
    if not credentials.metadata:
        return out
    for meta_key, value in credentials.metadata.items():
        if not isinstance(meta_key, str) or not meta_key.startswith("api_key_"):
            continue
        backend = meta_key[len("api_key_"):]
        env_name = _KEY_TO_ENV.get(backend)
        if not env_name:
            continue
        text = str(value or "").strip()
        if text:
            out[env_name] = text
    return out


def _model_id_from_request(request: NormalizedChatRequest) -> str:
    """Strip the `unified/` / `algae/unified/` prefixes from the model id."""
    raw = (request.model or "").strip()
    if raw.startswith("algae/unified/"):
        return raw[len("algae/unified/"):]
    if raw.startswith("unified/"):
        return raw[len("unified/"):]
    return raw


def _messages_from_request(request: NormalizedChatRequest) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for msg in request.messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
            content = "\n".join(text_parts)
        out.append({"role": role, "content": content if isinstance(content, str) else str(content)})
    return out


class UnifiedProxyAdapter(ProviderAdapter):
    """ProviderAdapter that fans requests out to LiteLLM-supported backends."""

    def chat(
        self,
        request: NormalizedChatRequest,
        credentials: ProviderCredentialRecord | None = None,
    ) -> ChatResponse:
        if credentials is None:
            raise RuntimeError(
                "Missing credentials for the unified proxy. "
                "Run `opentoken login unified --header api_key_openrouter=sk-or-...` (or similar)."
            )
        litellm = _import_litellm()
        envs = _resolve_envs(credentials)
        model = _model_id_from_request(request)
        if not model:
            raise RuntimeError("unified proxy: missing backend/model id in request.")
        with _injected_env(envs):
            response = litellm.completion(
                model=model,
                messages=_messages_from_request(request),
                stream=False,
                temperature=request.temperature,
                tools=request.tools,
                tool_choice=request.tool_choice,
            )
        return _convert_litellm_completion(request.model, response)

    def stream_chat(
        self,
        request: NormalizedChatRequest,
        credentials: ProviderCredentialRecord | None = None,
    ) -> Iterator[str] | None:
        if credentials is None:
            raise RuntimeError(
                "Missing credentials for the unified proxy. "
                "Run `opentoken login unified` first."
            )
        litellm = _import_litellm()
        envs = _resolve_envs(credentials)
        model = _model_id_from_request(request)
        if not model:
            raise RuntimeError("unified proxy: missing backend/model id in request.")
        return _stream_unified(
            litellm=litellm,
            model=model,
            messages=_messages_from_request(request),
            temperature=request.temperature,
            tools=request.tools,
            tool_choice=request.tool_choice,
            envs=envs,
        )


def _convert_litellm_completion(requested_model: str, response: object) -> ChatResponse:
    choices = getattr(response, "choices", None) or (
        response.get("choices") if isinstance(response, dict) else None  # type: ignore[union-attr]
    )
    if not choices:
        raise RuntimeError("unified proxy: backend returned no choices.")
    choice = choices[0]
    message = getattr(choice, "message", None) or (
        choice.get("message") if isinstance(choice, dict) else None
    )
    if message is None:
        raise RuntimeError("unified proxy: backend returned no message in choice.")
    content_raw = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content")
    tool_calls_raw = (
        getattr(message, "tool_calls", None) if not isinstance(message, dict) else message.get("tool_calls")
    )
    finish_reason = (
        getattr(choice, "finish_reason", None) if not isinstance(choice, dict) else choice.get("finish_reason")
    ) or "stop"
    return ChatResponse(
        model=requested_model,
        content=str(content_raw or ""),
        tool_calls=list(tool_calls_raw) if isinstance(tool_calls_raw, list) else [],
        finish_reason=str(finish_reason),
    )


def _stream_unified(
    *,
    litellm,
    model: str,
    messages: list[dict[str, object]],
    temperature: float | None,
    tools: list[dict[str, object]] | None,
    tool_choice: object,
    envs: dict[str, str],
) -> Iterator[str]:
    with _injected_env(envs):
        stream = litellm.completion(
            model=model,
            messages=messages,
            stream=True,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
        )
        for chunk in stream:
            delta = _extract_delta(chunk)
            if delta:
                yield delta


def _extract_delta(chunk: object) -> str:
    choices = getattr(chunk, "choices", None) or (
        chunk.get("choices") if isinstance(chunk, dict) else None  # type: ignore[union-attr]
    )
    if not choices:
        return ""
    first = choices[0]
    delta = getattr(first, "delta", None) or (
        first.get("delta") if isinstance(first, dict) else None
    )
    if delta is None:
        return ""
    content = (
        getattr(delta, "content", None) if not isinstance(delta, dict) else delta.get("content")
    )
    return str(content) if isinstance(content, str) else ""
