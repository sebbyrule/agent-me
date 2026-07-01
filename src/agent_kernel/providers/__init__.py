"""Provider adapters. Anthropic ships first; OpenAI/Ollama slot in at M3
behind the same `Provider` interface without touching the agent loop.
"""

from .base import Provider, ProviderError
from .factory import create_provider

__all__ = ["Provider", "ProviderError", "create_provider"]
