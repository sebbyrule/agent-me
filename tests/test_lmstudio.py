import httpx
import pytest

from agent_kernel.events import MessageComplete, TextDelta, ToolCallStart
from agent_kernel.providers.base import ProviderError
from agent_kernel.providers.lmstudio import (
    LMStudioProvider,
    parse_sse_chunk,
    to_openai_messages,
    to_openai_tools,
)


def test_parse_chunk_content():
    chunk = parse_sse_chunk('{"choices":[{"delta":{"content":"hi"}}]}')
    assert chunk.text == "hi"
    assert chunk.finish_reason is None


def test_parse_chunk_finish():
    chunk = parse_sse_chunk('{"choices":[{"delta":{},"finish_reason":"stop"}]}')
    assert chunk.text is None
    assert chunk.finish_reason == "stop"


def test_parse_chunk_done_sentinel():
    assert parse_sse_chunk("[DONE]") is None


def test_to_openai_messages_translates_tool_history():
    neutral = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}],
        },
        {
            "role": "tool",
            "tool_results": [{"id": "c1", "name": "read_file", "result": "data", "is_error": False}],
        },
    ]
    out = to_openai_messages(neutral)
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert out[2] == {"role": "tool", "tool_call_id": "c1", "content": "data"}


def test_to_openai_tools_shape():
    schemas = [{"name": "read_file", "description": "d", "input_schema": {"type": "object"}}]
    tools = to_openai_tools(schemas)
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "read_file"
    assert tools[0]["function"]["parameters"] == {"type": "object"}


async def test_stream_normalizes_text():
    body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, text=body)

    provider = LMStudioProvider(
        base_url="http://localhost:1234/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    events = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]
    deltas = [e.text for e in events if isinstance(e, TextDelta)]
    assert deltas == ["Hel", "lo"]
    assert isinstance(events[-1], MessageComplete)
    assert events[-1].text == "Hello"


async def test_stream_accumulates_streamed_tool_calls():
    # As OpenAI streams them: the name (and id) arrive whole in the first
    # fragment; only the JSON arguments are split across later fragments.
    body = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"function":{"name":"read_file","arguments":"{\\"pa"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"th\\":\\"a.txt\\"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    provider = LMStudioProvider(
        base_url="http://localhost:1234/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    events = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]
    calls = [e for e in events if isinstance(e, ToolCallStart)]
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.txt"}


async def test_stream_surfaces_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="model not loaded")

    provider = LMStudioProvider(
        base_url="http://localhost:1234/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError):
        _ = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]
