from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from opentoken.browser import qwen as qwen_module


class _FakeRequest:
    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}


class _FakePage:
    """Minimal sync-API page stub.

    Drives the capture loop by replaying a scripted sequence of page.evaluate
    results: each call pops the next entry. A probe that returns ok=True ends
    the loop (login succeeded); ok=False keeps it spinning.
    """

    def __init__(self, evaluate_results: list[dict]) -> None:
        self._evaluate_results = list(evaluate_results)
        self.url = 'https://chat.qwen.ai/'
        self.request_handlers: list = []

    def on(self, event: str, handler) -> None:
        self.request_handlers.append(handler)

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url

    def evaluate(self, script, _payload=None):
        if not self._evaluate_results:
            raise AssertionError(
                'page.evaluate called more times than scripted; capture loop did '
                'not exit on the authenticated probe result'
            )
        return self._evaluate_results.pop(0)

    def close(self) -> None:
        pass


class _FakeContext:
    def __init__(self, page: _FakePage, cookies: list[dict]) -> None:
        self._page = page
        self._cookies = cookies

    @property
    def pages(self) -> list[_FakePage]:
        return [self._page]

    def new_page(self) -> _FakePage:
        return self._page

    def cookies(self, _urls) -> list[dict]:
        return list(self._cookies)

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context

    def launch_persistent_context(self, _path, **_kwargs):
        # In real Playwright, launch_persistent_context returns the BrowserContext
        # directly (it IS closeable, has .cookies/.pages/.new_page) — no wrapper.
        return self._context


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_playwright(monkeypatch, context: _FakeContext) -> None:
    fake_module = types.ModuleType('fake_playwright')
    fake_module._chromium = _FakeChromium(context)

    class _Factory:
        def __call__(self):
            return _FakePlaywright(fake_module._chromium)

    fake_pw = _FakePlaywright(fake_module._chromium)
    factory = _Factory()

    monkeypatch.setattr(
        qwen_module, 'require_sync_playwright', lambda: factory
    )


_LOGIN_COOKIES = [
    {'name': 'cna', 'value': 'guest-cna'},
    {'name': 'login_session_ticket', 'value': 'real-session-ticket'},
    {'name': 'qwenai_search', 'value': 'abc123'},
]


def test_capture_returns_cookie_when_auth_probe_succeeds(monkeypatch, tmp_path):
    """Login success: the in-page auth probe returns 200 → capture returns
    cookie + user_agent, no Bearer required (qwen.ai is cookie-only)."""
    page = _FakePage(
        evaluate_results=[
            'Mozilla/5.0 (fake UA)',  # navigator.userAgent
            {'ok': True},  # /api/v2/me probe: authenticated
        ]
    )
    context = _FakeContext(page, _LOGIN_COOKIES)
    _install_fake_playwright(monkeypatch, context)
    # Fast clock so the legacy Bearer-only implementation times out quickly
    # instead of blocking the test for 300s; the new probe-based implementation
    # exits on the authenticated evaluate() before the clock advances far.
    monkeypatch.setattr(qwen_module.time, 'monotonic', _make_clock(seconds_total=400))
    monkeypatch.setattr(qwen_module.time, 'sleep', lambda _s: None)

    result = qwen_module.capture_qwen_browser_credentials(state_dir=tmp_path)

    assert result['cookie'] == 'cna=guest-cna; login_session_ticket=real-session-ticket; qwenai_search=abc123'
    assert result['user_agent'] == 'Mozilla/5.0 (fake UA)'


def test_capture_times_out_when_probe_never_succeeds(monkeypatch, tmp_path):
    """Guest harvest: the auth probe never returns 200 (cookies exist but
    aren't authenticated). Capture must time out rather than accept the guest
    cookies as a real login — that was the bug the Bearer-only guard was
    trying to prevent, and the probe-based guard preserves it."""
    page = _FakePage(
        evaluate_results=[
            'Mozilla/5.0 (fake UA)',
            {'ok': False, 'status': 401},  # guest probe
            {'ok': False, 'status': 401},  # still guest
            {'ok': False, 'status': 401},  # still guest
        ]
    )
    context = _FakeContext(page, _LOGIN_COOKIES)
    _install_fake_playwright(monkeypatch, context)
    monkeypatch.setattr(qwen_module.time, 'monotonic', _make_clock(seconds_total=400))
    monkeypatch.setattr(qwen_module.time, 'sleep', lambda _s: None)

    with pytest.raises(RuntimeError, match='Timed out'):
        qwen_module.capture_qwen_browser_credentials(state_dir=tmp_path)


def _make_clock(seconds_total: int):
    """A fake monotonic clock that advances ~120s per call so the loop's
    300s deadline trips after a couple of probe attempts (no real sleeping)."""
    state = {'t': 0.0}
    per_tick = seconds_total / 4

    def _monotonic() -> float:
        state['t'] += per_tick
        return state['t']

    return _monotonic
