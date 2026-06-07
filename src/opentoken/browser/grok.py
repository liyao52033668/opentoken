from __future__ import annotations

import time
from pathlib import Path

from opentoken.browser.common import (
    build_cookie_string,
    prepare_browser_state_dir,
    require_sync_playwright,
)


def capture_grok_browser_credentials(*, state_dir: Path) -> dict[str, str]:
    sync_playwright = require_sync_playwright()
    browser_state_dir = prepare_browser_state_dir(state_dir, "grok")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_state_dir),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://grok.com", wait_until="domcontentloaded")
            user_agent = page.evaluate("() => navigator.userAgent")

            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                cookies = context.cookies(["https://grok.com"])
                cookie_string = build_cookie_string(cookies)
                cookie_names = {str(item["name"]).lower() for item in cookies}
                # 真登录后 grok 会下发 sso-* / auth_token / user 类 cookie。
                # 之前的 fallback `len(cookies) > 1 and has_chat_input` 太宽松：
                # 未登录页本身就有 textarea + 一堆匿名 cookie,所以会假阳性把
                # guest 抓走覆盖真凭证。去掉那个 fallback,只信明确的 auth marker。
                has_auth_cookie = any(
                    "sso" in name or "auth_token" in name or name == "user_id"
                    for name in cookie_names
                )

                if cookie_string and has_auth_cookie:
                    return {
                        "cookie": cookie_string,
                        "user_agent": user_agent.strip(),
                    }

                time.sleep(2)
        finally:
            context.close()

    raise RuntimeError("Timed out waiting for Grok browser login to complete.")
