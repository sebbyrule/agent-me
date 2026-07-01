"""LM Studio provider adapter.

LM Studio exposes an OpenAI-compatible server locally (default
``http://localhost:1234/v1``), so this is a thin subclass of
`OpenAICompatibleProvider` — only the defaults and the connect-error hint differ.

Deliberate deviation from the M3 sequencing (see AGENT.md §4): LM Studio runs
locally and free, which let us exercise the streaming loop and tool-calling early
without spending Anthropic tokens.
"""

from __future__ import annotations

import httpx

# Re-exported for callers/tests that import the OpenAI helpers from here.
from .openai_compat import (  # noqa: F401
    ChunkDelta,
    OpenAICompatibleProvider,
    parse_sse_chunk,
    to_openai_messages,
    to_openai_tools,
)


class LMStudioProvider(OpenAICompatibleProvider):
    name = "lmstudio"
    service_hint = "Is the LM Studio local server running with a model loaded?"

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
        super().__init__(
            base_url,
            model,
            api_key,
            max_tokens=max_tokens,
            timeout=timeout,
            transport=transport,
        )
