"""Kernel configuration, loaded from the environment (and `.env`).

Punt on keychain integration (DESIGN.md §8): a plain `.env` is fine until
distribution. Never log or print secret values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # Which provider adapter the kernel uses: "anthropic" or "lmstudio".
    provider: str
    anthropic_api_key: str | None
    model: str
    # LM Studio (OpenAI-compatible local server) settings.
    lmstudio_base_url: str
    lmstudio_model: str
    lmstudio_api_key: str
    host: str
    port: int
    session_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            provider=os.getenv("AGENT_PROVIDER", "anthropic").strip().lower(),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            model=os.getenv("AGENT_MODEL", "claude-opus-4-8"),
            lmstudio_base_url=os.getenv(
                "LMSTUDIO_BASE_URL", "http://localhost:1234/v1"
            ),
            lmstudio_model=os.getenv("LMSTUDIO_MODEL", "local-model"),
            # LM Studio ignores the key, but the OpenAI-style header needs a value.
            lmstudio_api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"),
            host=os.getenv("KERNEL_HOST", "127.0.0.1"),
            port=int(os.getenv("KERNEL_PORT", "8765")),
            session_dir=Path(os.getenv("SESSION_DIR", "./sessions")).resolve(),
        )


def get_config() -> Config:
    return Config.from_env()
