"""Console management API.

All routes are mounted under /console/api. Session auth is enforced by the
``require_console_session`` dependency; only /console/api/login is open. The
console must be enabled via OPENTOKEN_ADMIN_PASSWORD — when it's not set, every
endpoint returns 503 so a misconfigured deployment can never expose an
adminless control surface.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from opentoken.api.auth import reset_auth_cache
from opentoken.api.streaming import strip_tool_protocol_markup
from opentoken.config.app_config import load_or_create_app_config
from opentoken.config.paths import resolve_app_config_path, resolve_providers_dir
from opentoken.gateway.normalized import normalize_chat_completions_request
from opentoken.gateway.router import get_default_router
from opentoken.models.provider_credentials import ProviderCredentialRecord
from opentoken.models.openai_compat import build_openai_model_objects
from opentoken.providers.registry import (
    get_provider_definition,
    list_supported_providers,
)
from opentoken.storage._atomic import write_json_atomic
from opentoken.storage.provider_store import (
    delete_provider_credentials,
    list_provider_credentials,
    save_provider_credentials,
)
from opentoken.gateway.model_registry import get_default_model_registry
from opentoken.console.auth import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session_token,
    get_admin_password,
    is_console_enabled,
    set_session_cookie,
    verify_session_token,
)

router = APIRouter(prefix="/console/api", tags=["console"])


def _console_disabled_response() -> HTTPException:
    # Don't reveal whether the console is merely disabled vs the password is
    # wrong — same 401 envelope either way so the admin surface can't be probed.
    return HTTPException(status_code=401, detail="Console is not available.")


def require_console_session(request: Request) -> None:
    """Reject any request when the console is disabled, or when the session
    cookie isn't a valid signature for the current admin password."""
    password = get_admin_password()
    if password is None:
        raise _console_disabled_response()
    token = request.cookies.get(COOKIE_NAME)
    if not verify_session_token(token, password):
        raise _console_disabled_response()


def _is_secure_request(request: Request) -> bool:
    # X-Forwarded-Proto is set by TLS-terminating reverse proxies; fall back to
    # the direct connection scheme.
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded:
        return forwarded == "https"
    return request.url.scheme == "https"


class LoginRequest(BaseModel):
    password: str


class ProviderLoginRequest(BaseModel):
    cookie: str | None = None
    headers: dict[str, str] | None = None
    api_key: str | None = None
    user_agent: str | None = None


class ChatTestRequest(BaseModel):
    model: str
    message: str


@router.get("/status")
def console_status(request: Request) -> dict[str, object]:
    """Probe endpoint (no auth): tells the page whether to render the login
    form or the "console disabled" message. Authenticated state is reported so
    the SPA can skip re-prompting an already-logged-in browser."""
    enabled = is_console_enabled()
    authenticated = False
    if enabled:
        authenticated = verify_session_token(
            request.cookies.get(COOKIE_NAME), get_admin_password()
        )
    return {"enabled": enabled, "authenticated": authenticated}


@router.post("/login")
def console_login(payload: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    password = get_admin_password()
    if password is None:
        # Disabled: respond with the same 401 shape as a bad password so the
        # existence/enabled-ness of the console isn't distinguishable.
        raise _console_disabled_response()
    # Constant-time compare against the configured password.
    if not hmac.compare_digest(payload.password.encode("utf-8"), password.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid password.")
    token = create_session_token(password)
    set_session_cookie(response, token, secure=_is_secure_request(request))
    return {"authenticated": True}


@router.post("/logout", dependencies=[Depends(require_console_session)])
def console_logout(request: Request, response: Response) -> dict[str, object]:
    clear_session_cookie(response, secure=_is_secure_request(request))
    return {"authenticated": False}


@router.get("/apikey", dependencies=[Depends(require_console_session)])
def console_apikey() -> dict[str, object]:
    config = load_or_create_app_config(resolve_app_config_path())
    api_key = str(config.get("api_key", "")).strip()
    keyless = bool(config.get("keyless_local", False))
    return {
        "api_key": api_key,
        "keyless_local": keyless,
        # Active = there's a real key gating /v1/*; when false the gateway is
        # in keyless local mode (or about to be) and the UI should warn.
        "has_key": bool(api_key),
    }


def _persist_app_config(updates: dict[str, object]) -> dict[str, object]:
    """Read the current config, apply *updates*, write it back atomically, and
    drop the auth cache so the API-key middleware re-reads on the next request.
    Returns the new config payload."""
    config_path = resolve_app_config_path()
    config = load_or_create_app_config(config_path)
    payload = dict(config)
    payload.update(updates)
    write_json_atomic(config_path, payload, sensitive=True)
    reset_auth_cache()
    return payload


@router.post("/apikey/rotate", dependencies=[Depends(require_console_session)])
def console_apikey_rotate() -> dict[str, object]:
    payload = _persist_app_config(
        {"api_key": secrets.token_hex(16), "keyless_local": False}
    )
    return {
        "api_key": str(payload["api_key"]),
        "keyless_local": False,
        "has_key": True,
    }


@router.post("/apikey/clear", dependencies=[Depends(require_console_session)])
def console_apikey_clear() -> dict[str, object]:
    # Clearing the key opts into explicit keyless local mode so the gateway
    # keeps serving (rather than failing closed); the UI flags the exposure.
    payload = _persist_app_config({"api_key": "", "keyless_local": True})
    return {
        "api_key": "",
        "keyless_local": True,
        "has_key": False,
    }


@router.get("/providers", dependencies=[Depends(require_console_session)])
def console_providers() -> dict[str, object]:
    providers_dir = resolve_providers_dir()
    records = {record.provider: record for record in list_provider_credentials(providers_dir)}
    items: list[dict[str, object]] = []
    for definition in list_supported_providers():
        record = records.get(definition.key)
        items.append(
            {
                "key": definition.key,
                "display_name": definition.display_name,
                "manual_auth": list(definition.manual_auth),
                "status": record.status if record is not None else "not_logged_in",
            }
        )
    return {"providers": items}


@router.post(
    "/providers/{provider_key}/login",
    dependencies=[Depends(require_console_session)],
)
def console_provider_login(
    provider_key: str, payload: ProviderLoginRequest
) -> dict[str, object]:
    definition = get_provider_definition(provider_key)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_key}")

    manual_auth = definition.manual_auth
    cookie = (payload.cookie or "").strip() or None
    api_key = (payload.api_key or "").strip() or None
    user_agent = (payload.user_agent or "").strip() or None
    headers: dict[str, str] = {}
    for raw_key, raw_value in (payload.headers or {}).items():
        key = raw_key.strip()
        value = str(raw_value).strip()
        if key and value:
            headers[key] = value
    if api_key:
        headers["api_key"] = api_key

    # Validate that the supplied material matches what this provider accepts,
    # mirroring cli/app.py's manual-login branch.
    if api_key and "api_key" not in manual_auth:
        raise HTTPException(
            status_code=400, detail=f"{definition.key} does not support api_key login."
        )
    if "api_key" in manual_auth and manual_auth == ("api_key",) and not api_key:
        raise HTTPException(
            status_code=400, detail=f"{definition.key} requires an api_key."
        )
    if not api_key and not cookie and not headers:
        raise HTTPException(
            status_code=400,
            detail=f"{definition.key} requires cookie, header, or api_key credentials.",
        )
    # Cookie-based web sessions are bound to the User-Agent that earned them;
    # upstream tends to reject a cookie presented from a different UA. Require
    # an explicit UA whenever a cookie is supplied so the saved session isn't
    # dead on arrival.
    if cookie and not user_agent:
        raise HTTPException(
            status_code=400,
            detail="User-Agent is required when a cookie is supplied.",
        )

    record = ProviderCredentialRecord(
        provider=definition.key,
        kind="api_key" if api_key else "web_session",
        cookie=cookie,
        headers=headers,
        user_agent=user_agent,
        metadata={"api_key": api_key} if api_key else {},
        status="valid",
    )
    save_provider_credentials(resolve_providers_dir(), record)
    return {"provider": definition.key, "status": "valid"}


@router.delete(
    "/providers/{provider_key}",
    dependencies=[Depends(require_console_session)],
)
def console_provider_delete(provider_key: str) -> dict[str, object]:
    definition = get_provider_definition(provider_key)
    target = definition.key if definition is not None else provider_key
    deleted = delete_provider_credentials(resolve_providers_dir(), target)
    return {"provider": target, "deleted": deleted}


@router.get("/models", dependencies=[Depends(require_console_session)])
def console_models() -> dict[str, object]:
    entries = get_default_model_registry().list_models()
    # Reuse the OpenAI-compat projector so the console shows the exact same
    # model objects /v1/models advertises, grouped by provider for the UI.
    items = build_openai_model_objects(entries)
    grouped: dict[str, list[dict[str, object]]] = {}
    for entry, item in zip(entries, items):
        grouped.setdefault(entry.provider, []).append(item)
    return {"models": grouped}


@router.post("/chat/test", dependencies=[Depends(require_console_session)])
def console_chat_test(payload: ChatTestRequest) -> dict[str, object]:
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be empty.")
    try:
        request = normalize_chat_completions_request(
            {
                "model": payload.model,
                "messages": [{"role": "user", "content": message}],
            }
        )
    except Exception as exc:  # model resolution / validation errors → 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        response = get_default_router().chat(request)
    except Exception as exc:
        # Surface a clean message; classify_provider_runtime_error scrubs
        # internal URLs, but the router already wraps upstream details — keep
        # the message verbatim so the user sees the real reason (rate limit,
        # not-logged-in, camoufox missing, …).
        return {"ok": False, "error": str(exc)}

    visible = strip_tool_protocol_markup(response.content or "", include_think=False)
    return {
        "ok": True,
        "content": visible,
        "model": response.model,
        "finish_reason": response.finish_reason,
    }
