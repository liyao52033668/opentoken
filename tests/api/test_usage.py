"""token 估算：ASCII / CJK / emoji (astral-plane) 三种字符权重不同。"""
from __future__ import annotations

from opentoken.api.usage import estimate_prompt_tokens, estimate_tokens


def test_empty_text_returns_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None or "") == 0


def test_ascii_is_about_one_token_per_four_chars():
    # "hello world" 11 chars / 4 ≈ 3
    assert estimate_tokens("hello world") == 3


def test_cjk_is_about_one_token_per_one_and_half_chars():
    # 6 个汉字 / 1.5 = 4
    assert estimate_tokens("你好世界，再见") == 5  # 7 chars with punctuation


def test_emoji_costs_about_three_tokens_each():
    """surrogate-pair / astral-plane code point 一个 emoji ≈ 3 tokens。
    之前 emoji 被按 BMP 算 → 严重低估 prompt 成本。"""
    # 单个 emoji
    assert estimate_tokens("😀") == 3
    # 5 个 emoji ≈ 15 tokens
    assert estimate_tokens("😀" * 5) == 15
    # 之前的实现会算成 round(5 / 1.5) = 3（严重低估）


def test_mixed_emoji_ascii_cjk():
    # "hi 😀 你好" -> "hi " (3 ASCII) + emoji(1 astral) + " " (1 ASCII) + "你好" (2 CJK)
    # 4 ASCII / 4 + 2 CJK / 1.5 + 1 astral * 3 = 1 + 1.33 + 3 ≈ 5
    result = estimate_tokens("hi 😀 你好")
    assert 4 <= result <= 6


def test_prompt_tokens_sums_messages():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "你好"},
    ]
    expected = estimate_tokens("hello") + estimate_tokens("你好")
    assert estimate_prompt_tokens(messages) == expected


def test_prompt_tokens_handles_multimodal_content_array():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "describe"},
                {"type": "input_image", "image_url": {"url": "data:image/png;base64,AAAA"}},
                {"type": "text", "text": "this"},
            ],
        }
    ]
    # 只算 text 部分: "describe" + "this"
    expected = estimate_tokens("describe") + estimate_tokens("this")
    assert estimate_prompt_tokens(messages) == expected
