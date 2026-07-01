"""Provider selection.

Picks the provider adapter from config so the agent loop and API layer never
name a concrete provider. Adding OpenAI/Ollama (M3) is a matter of another
branch here, nothing more.
"""

from __future__ import annotations

from ..config import Config
from .anthropic import AnthropicProvider
from .base import Provider, ProviderError
from .lmstudio import LMStudioProvider


def create_provider(config: Config) -> Provider:
    if config.provider == "anthropic":
        return AnthropicProvider(
            api_key=config.anthropic_api_key or "", model=config.model
        )
    if config.provider == "lmstudio":
        return LMStudioProvider(
            base_url=config.lmstudio_base_url,
            model=config.lmstudio_model,
            api_key=config.lmstudio_api_key,
        )
    raise ProviderError(
        f"Unknown AGENT_PROVIDER: {config.provider!r} (expected 'anthropic' or 'lmstudio')."
    )
