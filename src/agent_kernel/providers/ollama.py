"""Ollama provider adapter (M3).

Unlike OpenAI/LM Studio, Ollama has its own transport: a native `/api/chat`
endpoint that streams **newline-delimited JSON** (not SSE), with tool calls
arriving whole (not in fragments) and arguments as objects rather than JSON
strings, and without call ids (DESIGN.md §5). This adapter normalizes all of that
into the same internal `Event` stream, so the agent loop never notices the
difference.

Ollama's parallel tool calls are "inconsistent — needs guarding" (§5): the model
sometimes repeats a call, so we de-duplicate identical calls before emitting.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from ..events import Event, MessageComplete, TextDelta, ToolCallStart
from .base import Provider, ProviderError, stringify_tool_result
from .openai_compat import to_openai_tools

# Ollama accepts the same function-tool shape OpenAI uses.
to_ollama_tools = to_openai_tools


def to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the loop's neutral history -> Ollama `messages`."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            for r in msg["tool_results"]:
                out.append(
                    {
                        "role": "tool",
                        "tool_name": r.get("name", ""),
                        "content": stringify_tool_result(r["result"]),
                    }
                )
        elif role == "assistant" and msg.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            }
                        }
                        for tc in msg["tool_calls"]
                    ],
                }
            )
        else:
            out.append({"role": role, "content": msg["content"]})
    return out


def parse_ollama_chunk(obj: dict[str, Any]) -> tuple[str | None, list[tuple[str, dict]], bool, str | None]:
    """Decode one NDJSON chunk -> (text, tool_calls, done, done_reason)."""
    message = obj.get("message") or {}
    text = message.get("content") or None
    tool_calls: list[tuple[str, dict]] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_calls.append((fn.get("name") or "", args or {}))
    return text, tool_calls, bool(obj.get("done")), obj.get("done_reason")


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout, transport=transport
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[Event]:
        ollama_messages = to_ollama_messages(messages)
        if system:
            ollama_messages = [{"role": "system", "content": system}, *ollama_messages]

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = to_ollama_tools(tools)

        collected: list[str] = []
        finish_reason: str | None = None
        raw_calls: list[tuple[str, dict]] = []

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    raise ProviderError(f"Ollama returned {resp.status_code}: {body[:300]}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    text, tcs, done, reason = parse_ollama_chunk(json.loads(line))
                    if text:
                        collected.append(text)
                        yield TextDelta(text=text)
                    raw_calls.extend(tcs)
                    if done:
                        finish_reason = reason
                        break
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self._base_url}. "
                f"Is `ollama serve` running? ({exc})"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        # Guard Ollama's inconsistent parallel calls: drop exact duplicates,
        # and synthesize ids (Ollama doesn't provide them).
        seen: set[str] = set()
        index = 0
        for name, args in raw_calls:
            key = name + json.dumps(args, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            yield ToolCallStart(id=f"call_{index}", name=name, arguments=args)
            index += 1

        yield MessageComplete(text="".join(collected), stop_reason=finish_reason)
