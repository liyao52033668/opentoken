"""Tool-name alias resolution in web_tool_calling.

When a model invents a slightly-different name for a known tool (case mismatch,
alias for a builtin like web_search, or a name from the alias groups), we have
to map it back to a name the caller actually advertised. The original bug-scan
flagged these branches as untested.
"""
from __future__ import annotations

from opentoken.providers.web_tool_calling import (
    _resolve_available_tool_name,
    _rewrite_tool_call_names,
)


def _function_tool(name: str) -> dict[str, object]:
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {"type": "object"}},
    }


def test_resolve_returns_name_unchanged_when_already_available() -> None:
    tools = [_function_tool("get_weather")]
    assert _resolve_available_tool_name("get_weather", tools) == "get_weather"


def test_resolve_does_case_insensitive_lookup() -> None:
    tools = [_function_tool("get_weather")]
    # Model emitted Get_Weather (case-only variant); gateway resolves to the
    # registered name. Note: the resolver is case-insensitive but NOT
    # separator-insensitive, so "GetWeather" (no underscore) wouldn't match.
    assert _resolve_available_tool_name("GET_WEATHER", tools) == "get_weather"
    assert _resolve_available_tool_name("Get_Weather", tools) == "get_weather"


def test_resolve_returns_none_when_no_match() -> None:
    tools = [_function_tool("get_weather")]
    assert _resolve_available_tool_name("send_email", tools) is None


def test_resolve_returns_none_when_no_tools_declared() -> None:
    assert _resolve_available_tool_name("anything", []) is None


def test_resolve_normalises_builtin_web_search_alias() -> None:
    # A model that emits "web_search_preview" or similar variant should map to
    # the caller's registered "web_search" if any. _canonical_builtin_tool_name
    # collapses the prefix family.
    tools = [_function_tool("web_search")]
    assert _resolve_available_tool_name("web_search_preview", tools) == "web_search"


def test_rewrite_tool_call_names_mutates_in_place() -> None:
    tools = [_function_tool("get_weather")]
    tool_calls: list[dict[str, object]] = [
        {"id": "call_1", "function": {"name": "Get_Weather", "arguments": "{}"}},
        {"id": "call_2", "function": {"name": "send_email", "arguments": "{}"}},
    ]
    _rewrite_tool_call_names(tool_calls, tools)
    assert tool_calls[0]["function"]["name"] == "get_weather"
    # Unmappable name stays untouched (the validator will catch it).
    assert tool_calls[1]["function"]["name"] == "send_email"


def test_rewrite_tool_call_names_tolerates_malformed_entries() -> None:
    tools = [_function_tool("get_weather")]
    tool_calls: list[dict[str, object]] = [
        {"id": "call_1"},  # No function — skipped.
        {"id": "call_2", "function": {"name": ""}},  # Empty name — skipped.
        {"id": "call_3", "function": {"name": "Get_Weather", "arguments": "{}"}},
    ]
    _rewrite_tool_call_names(tool_calls, tools)
    assert tool_calls[2]["function"]["name"] == "get_weather"
