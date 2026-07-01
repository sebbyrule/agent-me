import dataclasses

import pytest

from agent_kernel.config import Config
from agent_kernel.providers import ProviderError, create_provider
from agent_kernel.providers.anthropic import AnthropicProvider
from agent_kernel.providers.lmstudio import LMStudioProvider
from agent_kernel.providers.ollama import OllamaProvider
from agent_kernel.providers.openai import OpenAIProvider


def _config(**overrides) -> Config:
    base = Config(
        provider="anthropic",
        anthropic_api_key="sk-test",
        model="claude-opus-4-8",
        lmstudio_base_url="http://localhost:1234/v1",
        lmstudio_model="local-model",
        lmstudio_api_key="lm-studio",
        openai_api_key="sk-openai",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        tool_policy="ask",
        host="127.0.0.1",
        port=8765,
        session_dir=__import__("pathlib").Path("."),
    )
    return dataclasses.replace(base, **overrides)


def test_factory_selects_anthropic():
    assert isinstance(create_provider(_config(provider="anthropic")), AnthropicProvider)


def test_factory_selects_lmstudio_without_api_key():
    assert isinstance(create_provider(_config(provider="lmstudio")), LMStudioProvider)


def test_factory_selects_openai():
    assert isinstance(create_provider(_config(provider="openai")), OpenAIProvider)


def test_factory_selects_ollama():
    assert isinstance(create_provider(_config(provider="ollama")), OllamaProvider)


def test_factory_openai_requires_key():
    with pytest.raises(ProviderError):
        create_provider(_config(provider="openai", openai_api_key=None))


def test_factory_rejects_unknown_provider():
    with pytest.raises(ProviderError):
        create_provider(_config(provider="bogus"))
