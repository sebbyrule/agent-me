import dataclasses

import pytest

from agent_kernel.config import Config
from agent_kernel.providers import ProviderError, create_provider
from agent_kernel.providers.anthropic import AnthropicProvider
from agent_kernel.providers.lmstudio import LMStudioProvider


def _config(**overrides) -> Config:
    base = Config(
        provider="anthropic",
        anthropic_api_key="sk-test",
        model="claude-opus-4-8",
        lmstudio_base_url="http://localhost:1234/v1",
        lmstudio_model="local-model",
        lmstudio_api_key="lm-studio",
        host="127.0.0.1",
        port=8765,
        session_dir=__import__("pathlib").Path("."),
    )
    return dataclasses.replace(base, **overrides)


def test_factory_selects_anthropic():
    provider = create_provider(_config(provider="anthropic"))
    assert isinstance(provider, AnthropicProvider)


def test_factory_selects_lmstudio_without_api_key():
    provider = create_provider(_config(provider="lmstudio"))
    assert isinstance(provider, LMStudioProvider)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ProviderError):
        create_provider(_config(provider="bogus"))
