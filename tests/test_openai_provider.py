"""The OpenAI adapter is a thin subclass of the shared OpenAI-compatible base
(which is exercised in depth by the LM Studio tests). Here we just confirm the
subclass specifics: key requirement, auth header, and that streaming works."""

from __future__ import annotations

import httpx
import pytest

from agent_kernel.events import MessageComplete, TextDelta
from agent_kernel.providers.base import ProviderError
from agent_kernel.providers.openai import OpenAIProvider


def test_requires_api_key():
    with pytest.raises(ProviderError):
        OpenAIProvider(api_key="", model="gpt-4o-mini")


async def test_streams_and_sends_auth_header():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["path"] = request.url.path
        body = (
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body)

    provider = OpenAIProvider(
        api_key="sk-secret",
        model="gpt-4o-mini",
        transport=httpx.MockTransport(handler),
    )
    events = [e async for e in provider.stream([{"role": "user", "content": "hi"}])]

    assert captured["auth"] == "Bearer sk-secret"
    assert captured["path"].endswith("/chat/completions")
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["hi"]
    assert isinstance(events[-1], MessageComplete)
