"""Console admin password and signed-cookie session.

No external deps: the session token is a HMAC-SHA256-signed base64 payload,
verified in constant time. The signing key is derived from the admin password,
so rotating the password (env var) invalidates every outstanding session with
zero bookkeeping.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Response

COOKIE_NAME = "opentoken_console"
_SESSION_TTL_SECONDS = 7 * 24 * 3600


def get_admin_password() -> str | None:
    """Read OPENTOKEN_ADMIN_PASSWORD once per call. Empty string is treated as
    "not set" — the console stays disabled so an accidental blank value never
    silently enables a passwordless admin surface."""
    raw = os.environ.get("OPENTOKEN_ADMIN_PASSWORD")
    if raw is None:
        return None
    password = raw.strip()
    return password or None


def is_console_enabled() -> bool:
    return get_admin_password() is not None


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _signing_key(password: str) -> bytes:
    # Derive a fixed-length key from the password so two different passwords
    # never collide and the key length is independent of the password length.
    return hashlib.sha256(b"opentoken-console-v1:" + password.encode("utf-8")).digest()


def create_session_token(password: str, *, ttl_seconds: int = _SESSION_TTL_SECONDS) -> str:
    """Create a signed session token bound to *password*. Expires after
    *ttl_seconds*."""
    key = _signing_key(password)
    # time.time() is fine here: this is a runtime value, not persisted module
    # state, so it doesn't need to survive a session restart.
    payload = {"exp": int(time.time()) + ttl_seconds}
    payload_b = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64u(payload_b)
    signature = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str | None, password: str | None) -> bool:
    """Return True iff *token* is a valid, unexpired session signed with
    *password*. None/missing password always rejects."""
    if not token or password is None:
        return False
    if "." not in token:
        return False
    payload_b64, signature = token.rsplit(".", 1)
    key = _signing_key(password)
    expected = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    # Constant-time compare on the signature so a brute-force timing oracle
    # can't recover it byte by byte.
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(_unb64u(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return False
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return int(time.time()) < int(exp)


def _cookie_params() -> dict[str, object]:
    # Secure only makes sense over https; setting it on a plain-http local
    # gateway would drop the cookie on every request. We set it only when the
    # deployment looks TLS-fronted.
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "max_age": _SESSION_TTL_SECONDS,
    }


def set_session_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    params = _cookie_params()
    params["secure"] = secure
    response.set_cookie(value=token, **params)


def clear_session_cookie(response: Response, *, secure: bool = False) -> None:
    # delete_cookie has its own signature (key/path/domain/...); max_age is not
    # accepted, so build the params without it.
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=None,
        secure=secure,
        httponly=True,
        samesite="lax",
    )
