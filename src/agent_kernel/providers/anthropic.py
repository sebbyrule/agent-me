"""Anthropic provider adapter.

Uses the official `anthropic` async SDK for transport and normalizes its SSE
streaming into the kernel's internal `Event` stream. Translates the loop's
provider-neutral history (see `agent.loop`) into Anthropic's content blocks, and
turns `tool_use` blocks in the model's reply into `ToolCallStart` events.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from anthropic import APIError, AsyncAnthropic

from ..events import Event, MessageComplete, TextDelta, ToolCallStart
from .base import Provider, ProviderError, stringify_tool_result


def to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate neutral history -> Anthropic `messages`."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            # Tool results go back as a user message of tool_result blocks.
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r["id"],
                            "content": stringify_tool_result(r["result"]),
                            "is_error": r.get("is_error", False),
                        }
                        for r in msg["tool_results"]
                    ],
                }
            )
        elif role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": msg["content"]})
    return out


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
            "messages": to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            # Registry schemas already match Anthropic's {name, description,
            # input_schema} shape.
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

        for block in final.content:
            if getattr(block, "type", None) == "tool_use":
                yield ToolCallStart(
                    id=block.id, name=block.name, arguments=dict(block.input)
                )

        yield MessageComplete(
            text="".join(collected),
            stop_reason=getattr(final, "stop_reason", None),
        )
