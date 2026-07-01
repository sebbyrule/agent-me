"""The provider adapter interface.

Designed against all three targets (Anthropic / OpenAI / Ollama, DESIGN.md §5)
so the shape won't change when the later two arrive — but only Anthropic is
implemented now (principle #3: interface now, implementation later).

A provider's single job: take normalized messages (and, later, tool schemas) and
yield the kernel's internal `Event` stream.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from ..events import Event


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfill a request (auth, network, etc.)."""


def stringify_tool_result(result: Any) -> str:
    """Render a tool result as the text both provider wire formats expect."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


class Provider(ABC):
    """Common interface every provider adapter satisfies."""

    #: Stable identifier, e.g. "anthropic".
    name: str = "provider"

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[Event]:
        """Stream a single assistant turn as normalized events.

        `messages` is a provider-neutral history: a list of
        ``{"role": "user"|"assistant", "content": str}`` (content grows to
        support tool blocks in M1). `tools` is unused until M1.
        """
        raise NotImplementedError
