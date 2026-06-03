from __future__ import annotations

import time
from pathlib import Path

from opentoken.browser.common import (
    build_cookie_string,
    prepare_browser_state_dir,
    require_sync_playwright,
)

# MiniMax Agent (agent.minimaxi.com) authenticates with a JWT stored in
# localStorage under "_token"; the request layer reads it and signs every API
# call itself. We run the real chat through the browser (Camoufox) DOM, so the
# only thing we must capture is enough to recognize a completed login and to
# re-seat the token if the runtime profile is rebuilt.
_MINIMAX_URL = "https://agent.minimaxi.com/"
_MINIMAX_TOKEN_LS_KEY = "_token"


def capture_minimax_browser_credentials(*, state_dir: Path) -> dict[str, object]:
    sync_playwright = require_sync_playwright()
    browser_state_dir = prepare_browser_state_dir(state_dir, "minimax")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_state_dir),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_MINIMAX_URL, wait_until="domcontentloaded", timeout=120000)
            user_agent = page.evaluate("() => navigator.userAgent")

            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                token = ""
                has_input = False
                try:
                    state = page.evaluate(
                        """
                        () => {
                          let token = "";
                          try { token = localStorage.getItem("_token") || ""; } catch (e) {}
                          const input = document.querySelector(
                            '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
                          );
                          return { token, has_input: !!input };
                        }
                        """
                    )
                    token = str(state.get("token") or "").strip()
                    has_input = bool(state.get("has_input"))
                except Exception:
                    token = ""
                    has_input = False

                # A real, authenticated JWT carries an `exp`/`user` payload — a
                # bare presence check on the token plus the chat composer being
                # rendered is enough to know the user finished logging in.
                if token and token.count(".") == 2 and has_input:
                    cookies = context.cookies(["https://agent.minimaxi.com", "https://minimaxi.com"])
                    return {
                        "cookie": build_cookie_string(cookies) or None,
                        "user_agent": user_agent,
                        "metadata": {"token": token},
                    }

                time.sleep(2)
        finally:
            context.close()

    raise RuntimeError("Timed out waiting for MiniMax browser login to complete.")
