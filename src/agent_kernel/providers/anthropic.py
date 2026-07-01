"""Anthropic provider adapter (the only one shipping in M0).

Uses the official `anthropic` async SDK for transport, and normalizes its SSE
streaming events into the kernel's internal `Event` stream. Tool handling is
scaffolded but not exercised until M1.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic
from anthropic import APIError

from ..events import Event, MessageComplete, TextDelta
from .base import Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, *, max_tokens: int = 4096) -> None:
        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[Event]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:  # M1: pass tool schemas through.
            kwargs["tools"] = tools

        collected: list[str] = []
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    collected.append(text)
                    yield TextDelta(text=text)
                final = await stream.get_final_message()
        except APIError as exc:  # pragma: no cover - network path
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        yield MessageComplete(
            text="".join(collected),
            stop_reason=getattr(final, "stop_reason", None),
        )
