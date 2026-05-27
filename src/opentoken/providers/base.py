from collections.abc import Iterator
from dataclasses import dataclass, field

from opentoken.gateway.normalized import NormalizedChatRequest
from opentoken.models.provider_credentials import ProviderCredentialRecord


@dataclass(frozen=True)
class ChatResponse:
    model: str
    content: str | None = ""
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    finish_reason: str = "stop"


class ProviderRateLimitError(RuntimeError):
    pass


def raise_for_provider_auth(status_code: int, *, provider: str, login_command: str) -> None:
    """Convert an upstream auth failure (401/403) into a friendly RuntimeError.

    The gateway's error classifier maps "session expired" / "re-login"
    RuntimeErrors to a 401 authentication_error. Without this conversion an
    expired cookie would fall through to response.raise_for_status() ->
    httpx.HTTPStatusError -> a generic 502 api_error, hiding the real fix.
    Call this just before raise_for_status() (after any in-adapter refresh
    retry has already been exhausted)."""
    if status_code in (401, 403):
        raise RuntimeError(
            f"{provider} session expired or invalid. Run `{login_command}` to refresh."
        )


class ProviderAdapter:
    def chat(
        self,
        request: NormalizedChatRequest,
        credentials: ProviderCredentialRecord | None = None,
    ) -> ChatResponse:
        return ChatResponse(model=request.model, content="stub response")

    def stream_chat(
        self,
        request: NormalizedChatRequest,
        credentials: ProviderCredentialRecord | None = None,
    ) -> Iterator[str] | None:
        return None
