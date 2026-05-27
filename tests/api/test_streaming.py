from opentoken.api.streaming import ProtocolMarkupProjector, chunk_visible_text, strip_tool_protocol_markup


def test_protocol_markup_projector_preserves_fragmented_think_tags_and_hides_tool_markup() -> None:
    projector = ProtocolMarkupProjector()

    pieces = [
        "<thi",
        "nk>先想",
        "一想</think><tool_",
        'call id="call_weather_1" name="get_weather">',
        '{"location":"Tokyo"}',
        "</tool_call><final_",
        "answer>最终答案</final_answer>",
    ]

    deltas = [projector.push(piece) for piece in pieces]

    assert deltas == [
        "",
        "<think>先想",
        "一想</think>",
        "",
        "",
        "",
        "最终答案",
    ]
    assert projector.visible_text == "<think>先想一想</think>最终答案"


def test_strip_tool_protocol_markup_keeps_think_but_removes_tool_and_final_tags() -> None:
    assert (
        strip_tool_protocol_markup(
            '<think>先想一想</think><tool_calls>[{"name":"get_weather","arguments":{"location":"Tokyo"}}]</tool_calls><final_answer>最终答案</final_answer>'
        )
        == "<think>先想一想</think>最终答案"
    )


def test_strip_tool_protocol_markup_can_hide_think_for_chat_completions() -> None:
    assert (
        strip_tool_protocol_markup(
            '<think>先想一想</think><tool_calls>[{"name":"get_weather","arguments":{"location":"Tokyo"}}]</tool_calls><final_answer>最终答案</final_answer>',
            include_think=False,
        )
        == "最终答案"
    )


def test_protocol_markup_projector_can_hide_fragmented_think_for_chat_completions() -> None:
    projector = ProtocolMarkupProjector(include_think=False)

    pieces = [
        "<thi",
        "nk>先想",
        "一想</think><final_",
        "answer>最终答案</final_answer>",
    ]

    deltas = [projector.push(piece) for piece in pieces]

    assert deltas == ["", "", "", "最终答案"]
    assert projector.visible_text == "最终答案"


def test_chunk_visible_text_preserves_complete_think_tag_boundaries() -> None:
    assert chunk_visible_text("<think>先想一想</think>最终答案") == [
        "<think>",
        "先想一想",
        "</think>",
        "最终答案",
    ]


def test_projector_handles_tags_split_character_by_character() -> None:
    """Incremental projector: feeding one character per push must reassemble
    tags across the unparsed-tail boundary and yield the same final visible
    text as a single batch projection (no chars lost or tags mis-split)."""
    raw = '<think>reason</think><tool_call id="x" name="t">{}</tool_call>answer'
    projector = ProtocolMarkupProjector()
    out = "".join(projector.push(ch) for ch in raw)
    assert out == "<think>reason</think>answer"
    assert projector.visible_text == "<think>reason</think>answer"
    # Equivalent to the one-shot projection.
    assert strip_tool_protocol_markup(raw) == "<think>reason</think>answer"


def test_project_emits_close_think_even_when_inner_hidden_tag_was_open() -> None:
    """Malformed nesting: a <tool_call> opens inside <think> and never closes
    before </think> fires. The visible region is "<think>a" + "</think>c"; the
    close MUST be emitted to keep the markup balanced, even though hidden
    state was True at the moment </think> arrived. The old code suppressed
    the close, leaving downstream `<think>` block parsers permanently open."""
    text = '<think>a<tool_call id="x" name="t">b</think>c'
    assert strip_tool_protocol_markup(text) == "<think>a</think>c"


def test_project_via_projector_handles_unclosed_inner_hidden_tag() -> None:
    """Same scenario but driven through the streaming projector, since SSE
    clients see the projector's output, not strip_tool_protocol_markup's."""
    projector = ProtocolMarkupProjector()
    final = projector.push('<think>reason</think>')  # baseline
    assert projector.visible_text == "<think>reason</think>"

    projector2 = ProtocolMarkupProjector()
    projector2.push('<think>reason here')
    projector2.push('<tool_call id="x" name="t">{}</tool_call>')
    # The close of think must eventually appear once we send it.
    projector2.push('</think>after')
    assert projector2.visible_text == "<think>reason here</think>after"
