from __future__ import annotations

import time
from pathlib import Path

from opentoken.browser.common import (
    build_cookie_string,
    prepare_browser_state_dir,
    require_sync_playwright,
)


# The endpoint polled inside the page to decide "is the user logged in?".
# chat.qwen.ai authenticates purely via cookies (its page fetches send no
# Authorization header — see camoufox_clients._chat_qwen_intl), so we can't
# key login-completion off a Bearer token the way claude/glm do. Instead we
# hit an authenticated-only API: 200 = logged in, 401/403 = guest, anything
# else = keep polling. /api/v2/me is the whoami-style endpoint qwen.ai's own
# SPA calls after login; it returns the user profile under a valid session and
# 401 for an anonymous one.
_QWEN_AUTH_PROBE_URL = 'https://chat.qwen.ai/api/v2/me'
_QWEN_AUTH_PROBE_JS = """
async ({ probeUrl }) => {
  try {
    const res = await fetch(probeUrl, {
      method: 'GET',
      credentials: 'include',
      headers: { 'Accept': 'application/json' },
    });
    return { ok: res.ok, status: res.status };
  } catch (err) {
    return { ok: false, status: 0, error: String(err) };
  }
}
"""


def capture_qwen_browser_credentials(*, state_dir: Path) -> dict[str, str]:
    sync_playwright = require_sync_playwright()
    browser_state_dir = prepare_browser_state_dir(state_dir, 'qwen-intl')

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_state_dir),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto('https://chat.qwen.ai/', wait_until='domcontentloaded')
            user_agent = page.evaluate('() => navigator.userAgent')

            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                cookies = context.cookies(['https://chat.qwen.ai', 'https://qwen.ai'])
                cookie_string = build_cookie_string(cookies)
                if cookie_string:
                    # chat.qwen.ai is cookie-only auth: there is no Bearer to
                    # harvest. Treat "the cookie jar passes the authenticated
                    # whoami probe" as the login-complete signal. This avoids
                    # both failure modes the prior guards hit — accepting guest
                    # cookies (CSRF/anonymous cookies exist before login) and
                    # waiting forever for a Bearer header that never arrives.
                    probe = page.evaluate(
                        _QWEN_AUTH_PROBE_JS,
                        {'probeUrl': _QWEN_AUTH_PROBE_URL},
                    )
                    if probe.get('ok'):
                        return {
                            'cookie': cookie_string,
                            'user_agent': user_agent,
                        }
                time.sleep(2)
        finally:
            context.close()

    raise RuntimeError('Timed out waiting for Qwen browser login to complete.')
