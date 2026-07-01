"""OpenAI provider adapter (M3).

Hosted OpenAI speaks the same `/chat/completions` wire format as LM Studio, so
this is a thin subclass of `OpenAICompatibleProvider` — it just points at
api.openai.com and requires a real API key. (Note: this module is
`agent_kernel.providers.openai`, not the `openai` PyPI package; we hand-roll the
HTTP calls via httpx and never import that package.)
"""

from __future__ import annotations

import httpx

from .base import ProviderError
from .openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    service_hint = "Check your network and OPENAI_API_KEY."

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        max_tokens: int = 4096,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError(
                "OPENAI_API_KEY is not set. Add it to .env to use AGENT_PROVIDER=openai."
            )
        super().__init__(
            base_url,
            model,
            api_key,
            max_tokens=max_tokens,
            timeout=timeout,
            transport=transport,
        )
