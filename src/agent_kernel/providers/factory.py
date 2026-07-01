"""Provider selection.

Picks the provider adapter from config so the agent loop and API layer never
name a concrete provider (DESIGN.md §5). Adding a provider is a branch here plus
an adapter module — nothing else in the kernel changes.
"""

from __future__ import annotations

from ..config import Config
from .anthropic import AnthropicProvider
from .base import Provider, ProviderError
from .lmstudio import LMStudioProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


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
    if config.provider == "openai":
        return OpenAIProvider(
            api_key=config.openai_api_key or "",
            model=config.openai_model,
            base_url=config.openai_base_url,
        )
    if config.provider == "ollama":
        return OllamaProvider(
            base_url=config.ollama_base_url, model=config.ollama_model
        )
    raise ProviderError(
        f"Unknown AGENT_PROVIDER: {config.provider!r} "
        "(expected 'anthropic', 'lmstudio', 'openai', or 'ollama')."
    )
