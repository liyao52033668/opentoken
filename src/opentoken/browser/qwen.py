from __future__ import annotations

import time
from pathlib import Path

from opentoken.browser.common import (
    build_cookie_string,
    prepare_browser_state_dir,
    require_sync_playwright,
)


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
            session_token: dict[str, str] = {'value': ''}

            def on_request(request) -> None:
                if 'qwen.ai' not in request.url:
                    return
                # 真登录的 Bearer 头是最可靠的信号 —— 只信它,不要再从 cookie
                # 里宽松 regex 匹配 (?:session|token|auth)[^=]+ —— 那个会命中
                # _csrf_session / XSRF-TOKEN / oauth_state 等非鉴权 cookie,
                # 把 guest 当登录把可用凭证替换掉。
                auth = request.headers.get('authorization', '')
                if auth.lower().startswith('bearer '):
                    bearer_token = auth[7:].strip()
                    if bearer_token and bearer_token.lower() not in {'undefined', 'null'}:
                        session_token['value'] = bearer_token

            page.on('request', on_request)
            page.goto('https://chat.qwen.ai/', wait_until='domcontentloaded')
            user_agent = page.evaluate('() => navigator.userAgent')

            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                cookies = context.cookies(['https://chat.qwen.ai', 'https://qwen.ai'])
                cookie_string = build_cookie_string(cookies)
                if cookie_string and session_token['value']:
                    return {
                        'cookie': cookie_string,
                        'session_token': session_token['value'],
                        'user_agent': user_agent,
                    }
                time.sleep(2)
        finally:
            context.close()

    raise RuntimeError('Timed out waiting for Qwen browser login to complete.')
