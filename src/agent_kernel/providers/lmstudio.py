"""LM Studio provider adapter.

LM Studio exposes an OpenAI-compatible REST API from its local server (default
``http://localhost:1234/v1``). This adapter hand-rolls the streaming
``/chat/completions`` call over httpx and normalizes the OpenAI-style SSE chunks
into the kernel's internal `Event` stream — including accumulating the
incrementally-streamed `tool_calls` into `ToolCallStart` events. Translates the
loop's provider-neutral history (see `agent.loop`) into OpenAI's wire format.

Deliberate deviation from the M3 sequencing (see AGENT.md §4): LM Studio runs
locally and free, which lets us exercise the streaming loop and M1 tool-calling
without spending Anthropic tokens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from ..events import Event, MessageComplete, TextDelta, ToolCallStart
from .base import Provider, ProviderError, stringify_tool_result


@dataclass
class ChunkDelta:
    """The decoded, provider-agnostic-ish content of one SSE chunk."""

    text: str | None = None
    finish_reason: str | None = None
    #: Raw OpenAI tool_call delta fragments, accumulated across chunks.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def parse_sse_chunk(data: str) -> ChunkDelta | None:
    """Decode one OpenAI-style SSE ``data:`` payload.

    Returns a `ChunkDelta`, or ``None`` for the terminal ``[DONE]`` sentinel.
    Pure and side-effect free so the streaming path is unit-testable without a
    live server.
    """
    if data == "[DONE]":
        return None
    obj = json.loads(data)
    choice = (obj.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    return ChunkDelta(
        text=delta.get("content"),
        finish_reason=choice.get("finish_reason"),
        tool_calls=delta.get("tool_calls") or [],
    )


def to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate neutral history -> OpenAI `messages`."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            # Each tool result is its own role:"tool" message.
            for r in msg["tool_results"]:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": r["id"],
                        "content": stringify_tool_result(r["result"]),
                    }
                )
        elif role == "assistant" and msg.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in msg["tool_calls"]
                    ],
                }
            )
        else:
            out.append({"role": role, "content": msg["content"]})
    return out


def to_openai_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate registry tool schemas -> OpenAI `tools` (function shape)."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


class LMStudioProvider(Provider):
    name = "lmstudio"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "lm-studio",
        *,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[Event]:
        openai_messages = to_openai_messages(messages)
        if system:
            openai_messages = [{"role": "system", "content": system}, *openai_messages]

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = to_openai_tools(tools)

        collected: list[str] = []
        finish_reason: str | None = None
        # index -> {"id", "name", "arguments": partial-json-string}
        tool_acc: dict[int, dict[str, Any]] = {}

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    raise ProviderError(
                        f"LM Studio returned {resp.status_code}: {body[:300]}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = parse_sse_chunk(line[len("data:") :].strip())
                    if chunk is None:  # [DONE]
                        break
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.text:
                        collected.append(chunk.text)
                        yield TextDelta(text=chunk.text)
                    _accumulate_tool_calls(tool_acc, chunk.tool_calls)
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach LM Studio at {self._base_url}. "
                f"Is the local server running with a model loaded? ({exc})"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"LM Studio request failed: {exc}") from exc

        for index in sorted(tool_acc):
            slot = tool_acc[index]
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            yield ToolCallStart(
                id=slot["id"] or f"call_{index}",
                name=slot["name"] or "",
                arguments=arguments,
            )

        yield MessageComplete(text="".join(collected), stop_reason=finish_reason)


def _accumulate_tool_calls(
    acc: dict[int, dict[str, Any]], fragments: list[dict[str, Any]]
) -> None:
    """Merge streamed OpenAI tool_call fragments (name/args arrive in pieces)."""
    for frag in fragments:
        index = frag.get("index", 0)
        slot = acc.setdefault(index, {"id": None, "name": None, "arguments": ""})
        if frag.get("id"):
            slot["id"] = frag["id"]
        fn = frag.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]
