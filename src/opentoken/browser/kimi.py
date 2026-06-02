from __future__ import annotations

import time
from pathlib import Path

from opentoken.browser.common import (
    build_cookie_string,
    prepare_browser_state_dir,
    require_sync_playwright,
)


def capture_kimi_browser_credentials(*, state_dir: Path) -> dict[str, str]:
    """Capture Kimi credentials by waiting for user to close the browser.

    Kimi generates a guest 'kimi-auth' cookie on first page load, so we
    cannot detect login automatically. Instead we wait for the user to
    complete login and close the browser manually.
    """
    sync_playwright = require_sync_playwright()
    browser_state_dir = prepare_browser_state_dir(state_dir, 'kimi')

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_state_dir),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto('https://www.kimi.com/', wait_until='domcontentloaded')
            user_agent = page.evaluate('() => navigator.userAgent')

            # flush=True: this CLI runs with stdout redirected (not a TTY) when
            # launched in the background, where print() is block-buffered — the
            # user never sees the instruction and has no idea the capture is
            # waiting on them to close the window. Force a flush so the prompt
            # appears immediately.
            print("Please login to Kimi and close the browser window when done.", flush=True)
            print("Waiting for browser to close (timeout 600s)...", flush=True)

            # 加 deadline —— 之前的 `while True` 如果浏览器没正常关闭（用户
            # Ctrl+C 不生效 / SSH session 被砍 / 进程被信号 trap）会永远挂住,
            # 现在 10 分钟超时强制返回。
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                try:
                    page.evaluate('() => document.title')
                    time.sleep(1)
                except Exception:
                    # Browser closed
                    break
            else:
                raise RuntimeError(
                    "Timed out waiting for Kimi browser login (10 min). "
                    "Please re-run `opentoken login kimi`."
                )

            # 抓 cookies。kimi 在首页加载时就 set guest `kimi-auth`,所以 cookie 非空
            # 不等于"用户已登录"。要求至少有一个**非 guest / 非 analytics** 的
            # cookie —— 排除 kimi-auth、_ga*、_clck、_clsk、cf_clearance 等已知
            # guest / 第三方追踪 cookie 后,还得剩下东西。
            cookies = context.cookies(['https://www.kimi.com', 'https://kimi.com'])
            cookie_string = build_cookie_string(cookies)
            if not cookie_string:
                raise RuntimeError("No cookies captured after Kimi login.")
            _GUEST_NAMES = {"kimi-auth", "cf_clearance"}
            _GUEST_PREFIXES = ("_ga", "_gid", "_gat", "_clck", "_clsk", "_uetsid", "_uetvid")
            user_cookies = [
                c for c in cookies
                if c.get("name") and c["name"].lower() not in _GUEST_NAMES
                and not any(c["name"].startswith(prefix) for prefix in _GUEST_PREFIXES)
            ]
            if not user_cookies:
                raise RuntimeError(
                    "Kimi browser closed without a real login — only the guest "
                    "`kimi-auth` cookie was set. Please complete the Kimi login "
                    "before closing the browser."
                )

            return {
                'cookie': cookie_string,
                'user_agent': user_agent,
            }
        finally:
            try:
                context.close()
            except Exception:
                pass

    raise RuntimeError('Failed to capture Kimi credentials.')
