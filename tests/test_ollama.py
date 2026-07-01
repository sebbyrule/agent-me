"""Ollama uses a distinct NDJSON transport with whole (id-less) tool calls whose
arguments are objects. These tests cover the translation + streaming normalization."""

from __future__ import annotations

import httpx

from agent_kernel.events import MessageComplete, TextDelta, ToolCallStart
from agent_kernel.providers.ollama import (
    OllamaProvider,
    parse_ollama_chunk,
    to_ollama_messages,
)


def test_parse_chunk_text_and_done():
    text, calls, done, reason = parse_ollama_chunk(
        {"message": {"content": "hello"}, "done": False}
    )
    assert text == "hello" and calls == [] and done is False and reason is None


def test_parse_chunk_tool_call_object_args():
    _text, calls, _done, _reason = parse_ollama_chunk(
        {"message": {"tool_calls": [{"function": {"name": "add", "arguments": {"a": 1, "b": 2}}}]}}
    )
    assert calls == [("add", {"a": 1, "b": 2})]


def test_to_ollama_messages_tool_history():
    neutral = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "add", "arguments": {"a": 1, "b": 2}}],
        },
        {"role": "tool", "tool_results": [{"id": "c1", "name": "add", "result": "3", "is_error": False}]},
    ]
    out = to_ollama_messages(neutral)
    assert out[1]["tool_calls"][0]["function"] == {"name": "add", "arguments": {"a": 1, "b": 2}}
    assert out[2] == {"role": "tool", "tool_name": "add", "content": "3"}


async def test_stream_text_and_tool_call():
    body = (
        json_line({"message": {"content": "Let me "}, "done": False})
        + json_line({"message": {"content": "add."}, "done": False})
        + json_line(
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "add", "arguments": {"a": 40, "b": 2}}}],
                },
                "done": False,
            }
        )
        + json_line({"message": {"content": ""}, "done": True, "done_reason": "stop"})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, text=body)

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="llama3.2",
        transport=httpx.MockTransport(handler),
    )
    events = [e async for e in provider.stream([{"role": "user", "content": "add 40 and 2"}])]

    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Let me add."
    calls = [e for e in events if isinstance(e, ToolCallStart)]
    assert len(calls) == 1
    assert calls[0].name == "add"
    assert calls[0].arguments == {"a": 40, "b": 2}
    assert isinstance(events[-1], MessageComplete)


async def test_stream_dedupes_repeated_tool_calls():
    # Ollama sometimes repeats a call; the adapter must not emit it twice.
    call = {"function": {"name": "add", "arguments": {"a": 1, "b": 1}}}
    body = json_line(
        {"message": {"tool_calls": [call, call]}, "done": True, "done_reason": "stop"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="llama3.2",
        transport=httpx.MockTransport(handler),
    )
    events = [e async for e in provider.stream([{"role": "user", "content": "x"}])]
    assert len([e for e in events if isinstance(e, ToolCallStart)]) == 1


def json_line(obj) -> str:
    import json

    return json.dumps(obj) + "\n"
