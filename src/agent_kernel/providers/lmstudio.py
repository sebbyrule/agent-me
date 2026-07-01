"""LM Studio provider adapter.

LM Studio exposes an OpenAI-compatible REST API from its local server (default
``http://localhost:1234/v1``). This adapter hand-rolls the streaming
``/chat/completions`` call over httpx (already a dependency) and normalizes the
OpenAI-style SSE chunks into the kernel's internal `Event` stream — so the agent
loop stays provider-agnostic, exactly as the Anthropic adapter does (DESIGN.md
§5).

Deliberate deviation from the M3 sequencing (see AGENT.md §4): LM Studio runs
locally and free, which lets us exercise the streaming loop and, soon, M1
tool-calling without spending Anthropic tokens.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from ..events import Event, MessageComplete, TextDelta
from .base import Provider, ProviderError


def decode_chunk(data: str) -> tuple[str | None, str | None] | None:
    """Decode one OpenAI-style SSE ``data:`` payload.

    Returns ``(text_delta, finish_reason)`` for a normal chunk, or ``None`` to
    signal the terminal ``[DONE]`` sentinel. Pure and side-effect free so the
    streaming path is unit-testable without a live server.
    """
    if data == "[DONE]":
        return None
    obj = json.loads(data)
    choices = obj.get("choices") or [{}]
    choice = choices[0]
    delta = choice.get("delta") or {}
    return delta.get("content"), choice.get("finish_reason")


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

    @staticmethod
    def _to_openai_messages(
        messages: list[dict[str, Any]], system: str | None
    ) -> list[dict[str, Any]]:
        # OpenAI carries the system prompt as a leading message (Anthropic takes
        # it as a separate arg); our internal history is otherwise compatible.
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        out.extend(messages)
        return out

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[Event]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._to_openai_messages(messages, system),
            "max_tokens": self._max_tokens,
            "stream": True,
        }
        if tools:  # M1: OpenAI-style tool schemas pass through here.
            payload["tools"] = tools

        collected: list[str] = []
        finish_reason: str | None = None
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
                    decoded = decode_chunk(line[len("data:") :].strip())
                    if decoded is None:  # [DONE]
                        break
                    text, reason = decoded
                    if reason:
                        finish_reason = reason
                    if text:
                        collected.append(text)
                        yield TextDelta(text=text)
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach LM Studio at {self._base_url}. "
                f"Is the local server running with a model loaded? ({exc})"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"LM Studio request failed: {exc}") from exc

        yield MessageComplete(text="".join(collected), stop_reason=finish_reason)
