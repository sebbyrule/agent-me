"""Shared implementation for OpenAI-compatible chat APIs.

OpenAI, LM Studio, and any drop-in server all speak the same `/chat/completions`
wire format (SSE streaming, function-style tool calls). This module hand-rolls
that once, over httpx; the concrete providers (`OpenAIProvider`,
`LMStudioProvider`) are thin subclasses that only differ in base URL, auth, and
defaults. Ollama is *not* here — it has its own NDJSON transport (see `ollama`).
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
    """The decoded content of one SSE chunk."""

    text: str | None = None
    finish_reason: str | None = None
    #: Raw OpenAI tool_call delta fragments, accumulated across chunks.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def parse_sse_chunk(data: str) -> ChunkDelta | None:
    """Decode one OpenAI-style SSE ``data:`` payload, or ``None`` for ``[DONE]``.

    Pure and side-effect free, so the streaming path is unit-testable without a
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
    """Translate the loop's neutral history -> OpenAI `messages`."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
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


def _accumulate_tool_calls(
    acc: dict[int, dict[str, Any]], fragments: list[dict[str, Any]]
) -> None:
    """Merge streamed OpenAI tool_call fragments (name whole, args in pieces)."""
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


class OpenAICompatibleProvider(Provider):
    """Streaming `/chat/completions` client. Subclasses set `name`, `service_hint`,
    and construction defaults."""

    name = "openai-compatible"
    #: Appended to the ConnectError message to help the user.
    service_hint = "Is the server reachable?"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
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
        tool_acc: dict[int, dict[str, Any]] = {}

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    raise ProviderError(
                        f"{self.name} returned {resp.status_code}: {body[:300]}"
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
                f"Could not reach {self.name} at {self._base_url}. "
                f"{self.service_hint} ({exc})"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"{self.name} request failed: {exc}") from exc

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
