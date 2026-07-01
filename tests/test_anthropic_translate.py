from agent_kernel.providers.anthropic import to_anthropic_messages


def test_plain_messages_pass_through():
    out = to_anthropic_messages([{"role": "user", "content": "hi"}])
    assert out == [{"role": "user", "content": "hi"}]


def test_assistant_tool_calls_become_blocks():
    neutral = [
        {
            "role": "assistant",
            "content": "let me look",
            "tool_calls": [
                {"id": "c1", "name": "read_file", "arguments": {"path": "a.txt"}}
            ],
        }
    ]
    out = to_anthropic_messages(neutral)
    blocks = out[0]["content"]
    assert blocks[0] == {"type": "text", "text": "let me look"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "read_file",
        "input": {"path": "a.txt"},
    }


def test_tool_results_become_user_tool_result_blocks():
    neutral = [
        {
            "role": "tool",
            "tool_results": [
                {"id": "c1", "name": "read_file", "result": {"k": 1}, "is_error": False}
            ],
        }
    ]
    out = to_anthropic_messages(neutral)
    assert out[0]["role"] == "user"
    block = out[0]["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "c1"
    assert block["content"] == '{"k": 1}'
    assert block["is_error"] is False
