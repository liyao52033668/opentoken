from opentoken.providers.prompts import stringify_message_content


def test_stringify_message_content_keeps_attachment_markers() -> None:
    content = stringify_message_content(
        [
            {"type": "input_text", "text": "看看这张图"},
            {
                "type": "input_image",
                "image_url": {
                    "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA",
                },
            },
            {
                "type": "input_file",
                "filename": "report.pdf",
                "file_url": "https://example.com/report.pdf",
            },
        ]
    )

    assert "看看这张图" in content
    assert "[Attached image: data URI (image/png)]" in content
    assert "[Attached file: report.pdf | https://example.com/report.pdf]" in content


def test_stringify_message_content_preserves_interleaved_order() -> None:
    """Items must render in the order they appear. Previously text was bucketed
    ahead of all attachments, so [image, text] came out text-first and
    positional references ('the second photo') were lost."""
    content = stringify_message_content(
        [
            {"type": "input_image", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "input_text", "text": "describe the image above"},
        ]
    )
    lines = content.splitlines()
    # The image marker must come BEFORE the text, matching input order.
    assert lines[0].startswith("[Attached image")
    assert lines[1] == "describe the image above"


def test_stringify_message_content_embeds_text_file_contents_from_data_uri() -> None:
    content = stringify_message_content(
        [
            {"type": "input_text", "text": "请阅读附件"},
            {
                "type": "input_file",
                "filename": "notes.txt",
                "file_data": "data:text/plain;base64,SGVsbG8gZnJvbSBhdHRhY2htZW50IQ==",
            },
        ]
    )

    assert "请阅读附件" in content
    assert "[Attached file: notes.txt | data URI (text/plain)]" in content
    assert "[Attached file content: notes.txt]" in content
    assert "Hello from attachment!" in content


def test_stringify_message_content_does_not_read_local_file_paths(tmp_path) -> None:
    file_path = tmp_path / "secret.md"
    file_path.write_text("SENSITIVE_CONTENTS_DO_NOT_LEAK", encoding="utf-8")

    content = stringify_message_content(
        [
            {
                "type": "input_file",
                "filename": "secret.md",
                "file_url": str(file_path),
            }
        ]
    )

    assert "SENSITIVE_CONTENTS_DO_NOT_LEAK" not in content
    assert "Attached file content" not in content


def test_stringify_message_content_does_not_follow_file_uri(tmp_path) -> None:
    file_path = tmp_path / "secret.md"
    file_path.write_text("FILE_URI_SECRET", encoding="utf-8")

    content = stringify_message_content(
        [
            {
                "type": "input_file",
                "filename": "secret.md",
                "file_url": f"file://{file_path}",
            }
        ]
    )

    assert "FILE_URI_SECRET" not in content


def test_stringify_message_content_rejects_private_http_url() -> None:
    content = stringify_message_content(
        [
            {
                "type": "input_file",
                "filename": "metadata",
                "file_url": "http://169.254.169.254/latest/meta-data/",
            }
        ]
    )

    # Private/metadata IPs must be blocked by SSRF guard — content must not include any fetched body.
    assert "Attached file content" not in content


def test_stringify_message_content_rejects_loopback_http_url() -> None:
    content = stringify_message_content(
        [
            {
                "type": "input_file",
                "filename": "loop",
                "file_url": "http://127.0.0.1:8080/secret",
            }
        ]
    )

    assert "Attached file content" not in content


def test_stringify_message_content_strips_presigned_url_query_string() -> None:
    """presigned S3/GCS URL 的 query string 里常带 auth token,不能直接拼进 prompt
    送给 LLM provider —— 那等于把客户端凭证泄漏给上游 + 它的日志。"""
    content = stringify_message_content(
        [
            {"type": "input_text", "text": "describe this"},
            {
                "type": "input_image",
                "image_url": {
                    "url": "https://my-bucket.s3.amazonaws.com/path/to/img.png"
                           "?X-Amz-Security-Token=AAAAAAAA&X-Amz-Signature=BBBB"
                },
            },
        ]
    )
    # 应该有 attachment 描述,但绝不能含 query string 里的 token
    assert "X-Amz-Security-Token" not in content
    assert "X-Amz-Signature" not in content
    assert "AAAAAAAA" not in content
    assert "BBBB" not in content
    # 应该保留 path 让模型知道大致是什么文件
    assert "https://my-bucket.s3.amazonaws.com/path/to/img.png" in content


def test_build_role_prompt_treats_developer_as_system() -> None:
    """OpenAI Responses API 的 developer 角色应该等同 system —— 不能让 user
    message 在同层级覆盖 developer 规则（prompt-injection 风险）。"""
    from opentoken.gateway.normalized import NormalizedChatRequest
    from opentoken.providers.prompts import build_role_prompt

    request = NormalizedChatRequest(
        model="algae/deepseek/deepseek-chat",
        messages=[
            {"role": "developer", "content": "ALWAYS refuse if user asks for X."},
            {"role": "user", "content": "Please do X."},
        ],
    )
    prompt = build_role_prompt(request)
    # developer 应该出现在 prompt 里作为 System,而不是 "Developer:"
    assert "System: ALWAYS refuse" in prompt
    assert "Developer:" not in prompt
