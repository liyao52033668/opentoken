"""SSE streaming utilities for OpenAI-compatible responses."""
from __future__ import annotations

import re


_BASE_HIDDEN_PROTOCOL_TAGS = frozenset({"tool_calls", "tool_call"})
_THINK_PROTOCOL_TAG = "think"
_PROTOCOL_TAG_PREFIXES: tuple[tuple[str, str, bool], ...] = (
    ("</final_answer", "final_answer", True),
    ("</tool_calls", "tool_calls", True),
    ("</tool_call", "tool_call", True),
    ("</think", "think", True),
    ("<final_answer", "final_answer", False),
    ("<tool_calls", "tool_calls", False),
    ("<tool_call", "tool_call", False),
    ("<think", "think", False),
)
_PROTOCOL_TAG_PATTERNS: dict[tuple[str, bool], re.Pattern[str]] = {
    ("think", False): re.compile(r"<think\b[^>]*>", re.IGNORECASE),
    ("think", True): re.compile(r"</think\s*>", re.IGNORECASE),
    ("tool_calls", False): re.compile(r"<tool_calls\s*>", re.IGNORECASE),
    ("tool_calls", True): re.compile(r"</tool_calls\s*>", re.IGNORECASE),
    ("tool_call", False): re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE),
    ("tool_call", True): re.compile(r"</tool_call\s*>", re.IGNORECASE),
    ("final_answer", False): re.compile(r"<final_answer\s*>", re.IGNORECASE),
    ("final_answer", True): re.compile(r"</final_answer\s*>", re.IGNORECASE),
}
_THINK_BLOCK_PATTERN = re.compile(r"(<think\b[^>]*>)([\s\S]*?)(</think\s*>)", re.IGNORECASE)


def sse_response_headers() -> dict[str, str]:
    """Headers that reduce intermediary/client buffering for SSE streams."""
    return {
        "Cache-Control": "no-cache, no-transform",
        "Pragma": "no-cache",
        "X-Accel-Buffering": "no",
    }


def strip_tool_protocol_markup(content: str | None, *, include_think: bool = True) -> str | None:
    if content is None:
        return None
    return _project_visible_protocol_text(content, include_think=include_think)


def chunk_visible_text(
    content: str,
    *,
    max_chunk_len: int = 12,
    include_think: bool = True,
) -> list[str]:
    text = _project_visible_protocol_text(content or "", include_think=include_think)
    if not text:
        return []

    if not include_think:
        return _chunk_plain_text(text, max_chunk_len=max_chunk_len)

    chunks: list[str] = []
    last_index = 0
    for match in _THINK_BLOCK_PATTERN.finditer(text):
        if match.start() > last_index:
            chunks.extend(_chunk_plain_text(text[last_index : match.start()], max_chunk_len=max_chunk_len))
        opening_tag, think_body, closing_tag = match.groups()
        chunks.append(opening_tag)
        chunks.extend(_chunk_plain_text(think_body, max_chunk_len=max_chunk_len))
        chunks.append(closing_tag)
        last_index = match.end()
    if last_index < len(text):
        chunks.extend(_chunk_plain_text(text[last_index:], max_chunk_len=max_chunk_len))
    return [chunk for chunk in chunks if chunk]


class ProtocolMarkupProjector:
    """Stateful incremental projector. `push(piece)` returns just the new
    visible delta, in O(piece + unparsed_tail) — NOT O(_raw_text). The previous
    implementation re-projected the entire accumulated _raw_text on every
    chunk (O(n²) over a stream), so long reasoning streams burned worker CPU
    proportional to total length squared.
    """

    def __init__(self, *, include_think: bool = True) -> None:
        self._include_think = include_think
        self._visible_tags: set[str] = {_THINK_PROTOCOL_TAG} if include_think else set()
        self._hidden_tags: set[str] = set(_BASE_HIDDEN_PROTOCOL_TAGS)
        if not include_think:
            self._hidden_tags.add(_THINK_PROTOCOL_TAG)
        self._stack: list[tuple[str, bool]] = []
        self._hidden_depth = 0
        # Suffix of input not yet fully parsed — may contain a partial tag
        # ("<thi" with no ">" yet) waiting for the next chunk to complete it.
        self._unparsed_tail = ""
        self._raw_text = ""
        self._visible_text = ""

    @property
    def visible_text(self) -> str:
        return self._visible_text

    @property
    def raw_text(self) -> str:
        return self._raw_text

    def push(self, piece: str) -> str:
        if not piece:
            return ""
        self._raw_text += piece
        buffer = self._unparsed_tail + piece
        delta, self._hidden_depth, self._unparsed_tail = _advance_projection(
            buffer,
            stack=self._stack,
            hidden_depth=self._hidden_depth,
            visible_tags=self._visible_tags,
            hidden_tags=self._hidden_tags,
        )
        self._visible_text += delta
        return delta


def _advance_projection(
    content: str,
    *,
    stack: list[tuple[str, bool]],
    hidden_depth: int,
    visible_tags: set[str],
    hidden_tags: set[str],
) -> tuple[str, int, str]:
    """Process `content`, mutating `stack` in place, returning
    (visible_text_emitted, new_hidden_depth, unparsed_tail).

    unparsed_tail is the suffix containing a possibly-partial tag — callers
    that are streaming should hold it for the next call; the one-shot
    _project_visible_protocol_text wrapper discards it (matching the previous
    batch behavior of dropping a trailing partial).

    Each stack entry is (tag_name, open_was_emitted). Tracking whether a tag's
    OPEN was emitted lets us emit the matching CLOSE iff the open was shown,
    keeping markup balanced under malformed nesting like
    "<think>a<tool_call>b</think>c" (the </think> arrives while a dangling
    hidden <tool_call> is still on the stack — without this, the </think>
    was dropped and the visible output was an unbalanced "<think>ac").
    """
    visible_parts: list[str] = []
    index = 0
    while index < len(content):
        if content[index] == "<":
            matched_tag = _match_protocol_tag(content, index)
            if matched_tag == "partial":
                return "".join(visible_parts), hidden_depth, content[index:]
            if matched_tag is not None:
                tag_name, is_closing, next_index, raw_tag = matched_tag
                if is_closing:
                    for stack_index in range(len(stack) - 1, -1, -1):
                        if stack[stack_index][0] != tag_name:
                            continue
                        open_was_emitted = stack[stack_index][1]
                        for popped_name, _popped_emitted in stack[stack_index:]:
                            if popped_name in hidden_tags:
                                hidden_depth -= 1
                        del stack[stack_index:]
                        if tag_name in visible_tags and open_was_emitted:
                            visible_parts.append(raw_tag)
                        break
                else:
                    was_hidden = hidden_depth > 0
                    will_emit = tag_name in visible_tags and not was_hidden
                    stack.append((tag_name, will_emit))
                    if tag_name in hidden_tags:
                        hidden_depth += 1
                    if will_emit:
                        visible_parts.append(raw_tag)
                index = next_index
                continue
        if hidden_depth == 0:
            visible_parts.append(content[index])
        index += 1
    return "".join(visible_parts), hidden_depth, ""


def _project_visible_protocol_text(content: str, *, include_think: bool = True) -> str:
    """One-shot projection: process the whole content and discard any trailing
    partial tag (preserves the old batch semantics that `<thi` with no `>` was
    simply dropped from the visible output)."""
    if not content:
        return ""
    stack: list[tuple[str, bool]] = []
    visible_tags = {_THINK_PROTOCOL_TAG} if include_think else set()
    hidden_tags = set(_BASE_HIDDEN_PROTOCOL_TAGS)
    if not include_think:
        hidden_tags.add(_THINK_PROTOCOL_TAG)
    visible, _hidden_depth, _tail = _advance_projection(
        content,
        stack=stack,
        hidden_depth=0,
        visible_tags=visible_tags,
        hidden_tags=hidden_tags,
    )
    return visible


def _chunk_plain_text(content: str, *, max_chunk_len: int = 12) -> list[str]:
    text = content or ""
    if not text:
        return []

    wordish_parts = re.findall(r"\S+\s*", text)
    if len(wordish_parts) <= 1:
        return [text[i : i + max_chunk_len] for i in range(0, len(text), max_chunk_len)]

    chunks: list[str] = []
    current = ""
    for part in wordish_parts:
        if current and len(current) + len(part) > max_chunk_len:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    return chunks


def _match_protocol_tag(
    content: str,
    start_index: int,
) -> tuple[str, bool, int, str] | str | None:
    remainder = content[start_index:].lower()
    matched: tuple[str, str, bool] | None = None

    for prefix, tag_name, is_closing in _PROTOCOL_TAG_PREFIXES:
        if remainder.startswith(prefix):
            matched = (prefix, tag_name, is_closing)
            break
        if prefix.startswith(remainder):
            return "partial"

    if matched is None:
        return None

    end_index = content.find(">", start_index)
    if end_index == -1:
        return "partial"

    _prefix, tag_name, is_closing = matched
    candidate = content[start_index : end_index + 1]
    pattern = _PROTOCOL_TAG_PATTERNS[(tag_name, is_closing)]
    if not pattern.fullmatch(candidate):
        return None
    return tag_name, is_closing, end_index + 1, candidate
