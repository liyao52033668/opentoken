"""Serve the admin console HTML.

The page lives in a sibling ``console.html`` so its JavaScript stays free of
Python string-escaping artifacts (backslashes, quote doubling) that an inline
triple-quoted string would mangle. It's read once at import time and cached.
"""
from __future__ import annotations

from importlib.resources import files

_HTML: str | None = None


def render_console_html() -> str:
    global _HTML
    if _HTML is None:
        _HTML = (
            files(__package__)
            .joinpath("console.html")
            .read_text(encoding="utf-8")
        )
    return _HTML
