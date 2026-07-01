"""Entrypoint: `agent-kernel` (or `python -m agent_kernel`).

Starts the long-running kernel process — a normal local server bound to
localhost (DESIGN.md §3). Frontends connect over HTTP/WS.
"""

from __future__ import annotations

import sys

import uvicorn

from .api.app import create_app
from .config import get_config

# Force UTF-8 so any non-ASCII in startup output won't crash a legacy Windows console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Note: the MCP client spawns server subprocesses via asyncio, which on Windows
# requires the Proactor event loop. That is the default on Windows since Python
# 3.8, so no policy override is needed here (and the policy API is deprecated as
# of 3.14). The live MCP smoke test confirms the running kernel supports this.


def main() -> None:
    config = get_config()
    app = create_app(config)
    print(f"agent-me kernel listening on http://{config.host}:{config.port}")
    print(f"  provider: {config.provider}")
    if config.provider == "anthropic" and not config.anthropic_api_key:
        print("  warning: ANTHROPIC_API_KEY is not set - conversations will fail.")
    elif config.provider == "lmstudio":
        print(
            f"  LM Studio: {config.lmstudio_base_url} (model {config.lmstudio_model!r}) "
            "- ensure the local server is running with a model loaded."
        )
    elif config.provider == "openai" and not config.openai_api_key:
        print("  warning: OPENAI_API_KEY is not set - conversations will fail.")
    elif config.provider == "ollama":
        print(
            f"  Ollama: {config.ollama_base_url} (model {config.ollama_model!r}) "
            "- ensure `ollama serve` is running and the model is pulled."
        )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
