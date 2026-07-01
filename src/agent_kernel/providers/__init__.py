"""Provider adapters. Anthropic ships first; OpenAI/Ollama slot in at M3
behind the same `Provider` interface without touching the agent loop.
"""

from .base import Provider, ProviderError

__all__ = ["Provider", "ProviderError"]
