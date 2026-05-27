import hmac
import json
import threading
from pathlib import Path

from fastapi import Request

from opentoken.api.errors import openai_error_response
from opentoken.config.paths import resolve_app_config_path


_CACHE_LOCK = threading.Lock()
_CACHED_API_KEY: str | None = None
_CACHED_MTIME_NS: int | None = None
_CACHED_PATH: Path | None = None


def maybe_require_api_key(request: Request):
    if request.url.path == "/health":
        return None

    expected_api_key = _get_expected_api_key(resolve_app_config_path())
    if expected_api_key is None:
        # The config file EXISTS but couldn't be parsed (corrupt/truncated).
        # Fail CLOSED: we must never serve authenticated provider sessions
        # unauthenticated just because we couldn't read the key. A genuinely
        # absent config / empty key returns "" (handled below), which is the
        # documented keyless-local mode.
        return openai_error_response(
            status_code=503,
            message="Gateway configuration is unreadable; cannot verify the API key.",
            error_type="api_error",
        )
    if not expected_api_key:
        return None

    authorization = request.headers.get("Authorization", "")
    expected_header = f"Bearer {expected_api_key}"
    # 常量时间比较：避免逐字节 timing 探测 API key 内容
    if not hmac.compare_digest(authorization.encode("utf-8"), expected_header.encode("utf-8")):
        return openai_error_response(
            status_code=401,
            message="Invalid or missing API key.",
            error_type="authentication_error",
        )
    return None


def _get_expected_api_key(config_path: Path) -> str | None:
    """Return the configured gateway API key.

    Returns:
      - the key string when one is configured,
      - "" when there is no config file or no key field (keyless-local mode),
      - None when the config file EXISTS but is corrupt/unreadable, so callers
        can fail closed rather than fall through to the keyless path.
    """
    global _CACHED_API_KEY, _CACHED_MTIME_NS, _CACHED_PATH
    try:
        stat = config_path.stat()
        mtime_ns = stat.st_mtime_ns
    except FileNotFoundError:
        with _CACHE_LOCK:
            _CACHED_API_KEY = None
            _CACHED_MTIME_NS = None
            _CACHED_PATH = config_path
        return ""

    with _CACHE_LOCK:
        if (
            _CACHED_PATH == config_path
            and _CACHED_MTIME_NS == mtime_ns
            and _CACHED_API_KEY is not None
        ):
            return _CACHED_API_KEY

    payload = _load_existing_app_config(config_path)
    if payload is None:
        # File exists (stat succeeded) but parse failed or wasn't a JSON object.
        # Don't cache — the user will likely fix it; signal "unreadable" so the
        # middleware fails closed instead of treating it as keyless.
        return None
    api_key = str(payload.get("api_key", "")).strip()

    with _CACHE_LOCK:
        _CACHED_API_KEY = api_key
        _CACHED_MTIME_NS = mtime_ns
        _CACHED_PATH = config_path
    return api_key


def reset_auth_cache() -> None:
    """Drop cached config; useful for tests / config rotation."""
    global _CACHED_API_KEY, _CACHED_MTIME_NS, _CACHED_PATH
    with _CACHE_LOCK:
        _CACHED_API_KEY = None
        _CACHED_MTIME_NS = None
        _CACHED_PATH = None


def _load_existing_app_config(config_path: Path) -> dict[str, object] | None:
    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupt / truncated config must NOT crash the auth middleware on every
        # request (a 500 storm). Return None; the caller fails closed.
        return None
    if not isinstance(payload, dict):
        return None
    return payload
