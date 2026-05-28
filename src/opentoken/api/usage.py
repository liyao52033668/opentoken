"""Token usage estimation for OpenAI-compatible responses.

opentoken is a gateway over many providers, most of which never report
token counts. Returning {"prompt_tokens": 0, ...} confuses clients that
use usage to manage context windows or estimate cost. We approximate
with a deterministic char-based heuristic — accurate to within ~20% on
English/Chinese mixed text, which is good enough for downstream pacing.

Estimate: 1 token ≈ 4 characters for ASCII text, 1 token ≈ 1.5 characters
for CJK. We blend by counting non-ASCII separately, which is cheap.
"""
from __future__ import annotations


# Server-side identifier returned in OpenAI responses so cache-aware clients can
# distinguish backend versions. We don't currently rotate this; bump on breaking
# changes to backend protocol handling so client-side caches reset.
SYSTEM_FINGERPRINT = "fp_opentoken_v1"


def estimate_tokens(text: str) -> int:
    """ASCII ≈ 1 token / 4 chars; CJK 范围 ≈ 1 token / 1.5 chars; emoji /
    astral-plane (code point > 0xFFFF) ≈ 3 tokens / 字符 —— 真实 BPE 把一个
    emoji 拆成 3-4 个 byte-level token。之前把 astral 字符也按 1.5 比 1 算,
    100 个 emoji 估算 ~67,真实 ~300,严重低估推理成本/上下文消耗。"""
    if not text:
        return 0
    ascii_count = 0
    cjk_or_bmp_count = 0
    astral_count = 0
    for char in text:
        codepoint = ord(char)
        if codepoint < 128:
            ascii_count += 1
        elif codepoint > 0xFFFF:
            astral_count += 1
        else:
            cjk_or_bmp_count += 1
    return max(
        1,
        round(ascii_count / 4 + cjk_or_bmp_count / 1.5 + astral_count * 3),
    )


def estimate_prompt_tokens(messages: list[dict[str, object]] | None) -> int:
    if not messages:
        return 0
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
            continue
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        total += estimate_tokens(text)
    return total
