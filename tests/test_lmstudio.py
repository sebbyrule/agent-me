import httpx

from agent_kernel.events import MessageComplete, TextDelta
from agent_kernel.providers.lmstudio import LMStudioProvider, decode_chunk


def test_decode_chunk_content():
    assert decode_chunk('{"choices":[{"delta":{"content":"hi"}}]}') == ("hi", None)


def test_decode_chunk_finish():
    text, reason = decode_chunk(
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}'
    )
    assert text is None
    assert reason == "stop"


def test_decode_chunk_done_sentinel():
    assert decode_chunk("[DONE]") is None


async def test_stream_normalizes_openai_sse():
    body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = request.read()
        assert b'"stream": true' in payload or b'"stream":true' in payload
        return httpx.Response(200, text=body)

    provider = LMStudioProvider(
        base_url="http://localhost:1234/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    events = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]

    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert [d.text for d in deltas] == ["Hel", "lo"]

    complete = events[-1]
    assert isinstance(complete, MessageComplete)
    assert complete.text == "Hello"
    assert complete.stop_reason == "stop"


async def test_stream_surfaces_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="model not loaded")

    provider = LMStudioProvider(
        base_url="http://localhost:1234/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    import pytest

    from agent_kernel.providers.base import ProviderError

    with pytest.raises(ProviderError):
        _ = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]
